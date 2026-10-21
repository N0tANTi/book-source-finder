from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
from email import policy
from email.parser import BytesParser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import (DEFAULT_DB, connect, detail, export_alignments, import_book,
                   import_workspace, library, save_alignment, search)
from .documents import (MAX_FILE, add_file_book, file_books, file_detail, lexical_search,
                        confirm_pair, ranked_units)
from .ai import MODEL, AIService, Settings

STATIC = Path(__file__).parent / 'static'


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, db, token, settings=None, ai=None, **kwargs):
        self.db, self.token = db, token
        self.settings = settings or Settings(Path(db).parent)
        self.ai = ai
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):
        # Do not put query excerpts in server logs.
        pass

    def send(self, data, status=200, content_type='application/json; charset=utf-8', disposition=None):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if disposition:
            self.send_header('Content-Disposition', disposition)
        self.end_headers()
        self.wfile.write(raw)

    def valid_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def do_GET(self):
        if not self.valid_host():
            return self.send({'error': 'Invalid host'}, 403)
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        arg = lambda name: params.get(name, [''])[0]
        try:
            if parsed.path.startswith('/api/'):
                conn = connect(self.db)
                try:
                    if parsed.path == '/api/library':
                        data = library(conn)
                        for book in data['books']:
                            book['kind'] = 'legacy'
                        data['books'] = file_books(conn, MODEL) + data['books']
                        return self.send({**data, 'csrf_token': self.token, 'model': self.settings.status()})
                    if parsed.path == '/api/search':
                        if conn.execute('SELECT 1 FROM documents WHERE book_id=?', (arg('book'),)).fetchone():
                            return self.send({'results': lexical_search(conn, arg('q'), arg('book'), arg('chapter'))})
                        results = search(conn, arg('q'), arg('book'), arg('chapter'))
                        if not arg('book'):
                            results += lexical_search(conn, arg('q'), '', arg('chapter'))
                            exact = [r for r in results if r['match'] in ('exact', 'across')]
                            results = exact or sorted(results, key=lambda r: -r['score'])
                        return self.send({'results': results[:20]})
                    if parsed.path == '/api/detail':
                        return self.send(detail(conn, arg('id')))
                    if parsed.path == '/api/export':
                        return self.send(export_alignments(conn), disposition='attachment; filename="alignments.json"')
                    if parsed.path == '/api/file-detail':
                        return self.send(file_detail(conn, arg('id'), MODEL, arg('source')))
                    if parsed.path == '/api/settings':
                        return self.send(self.settings.status())
                    if parsed.path == '/api/open-book':
                        row = conn.execute('''SELECT u.id FROM units u JOIN documents d ON d.id=u.document_id
                            WHERE d.book_id=? AND d.role='translation' AND (?='' OR u.section=?)
                            ORDER BY CASE WHEN ?<>'' AND length(u.normalized)>=60 THEN 0 ELSE 1 END,
                            u.position LIMIT 1''', (arg('book'),arg('chapter'),arg('chapter'),arg('chapter'))).fetchone()
                        if not row:
                            row = conn.execute('''SELECT p.id FROM paragraphs p JOIN chapters c ON c.id=p.chapter_id
                                WHERE c.book_id=? AND (?='' OR c.id=?) ORDER BY c.position,p.position LIMIT 1''',
                                (arg('book'),arg('chapter'),arg('chapter'))).fetchone()
                        if not row:
                            raise ValueError('书籍不存在或没有可阅读的内容。')
                        return self.send({'id': row['id']})
                finally:
                    conn.close()
                return self.send({'error': 'Not found'}, 404)
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/library.js': ('library.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            files['/reader.css'] = ('reader.css', 'text/css; charset=utf-8')
            if parsed.path not in files:
                return self.send({'error': 'Not found'}, 404)
            name, mime = files[parsed.path]
            return self.send((STATIC / name).read_bytes(), content_type=mime)
        except (ValueError, KeyError) as exc:
            self.send({'error': str(exc)}, 400)
        except Exception:
            self.send({'error': '读取失败，请检查本地数据库和终端。'}, 500)

    def do_POST(self):
        expected_origin = f'http://{self.headers.get("Host", "")}'
        if (not self.valid_host() or self.headers.get('X-CSRF-Token') != self.token
                or self.headers.get('Origin', expected_origin) != expected_origin):
            return self.send({'error': '请从本地工具页面操作。'}, 403)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if self.path == '/api/import':
                if not 0 < size <= 2 * MAX_FILE + 100_000:
                    raise ValueError('每份文件最多 80 MB。')
                content_type = self.headers.get('Content-Type', '')
                if not content_type.startswith('multipart/form-data;') or '\n' in content_type or '\r' in content_type:
                    raise ValueError('请选择原文和译文文件。')
                message = BytesParser(policy=policy.default).parsebytes(
                    ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + self.rfile.read(size))
                fields, files = {}, {}
                if not message.is_multipart():
                    raise ValueError('文件上传格式无效。')
                parts = list(message.iter_parts())
                if len(parts) > 5:
                    raise ValueError('一次只能导入一本书的一份原文和一份译文。')
                for part in parts:
                    name = part.get_param('name', header='content-disposition')
                    if part.get_filename():
                        if name in files:
                            raise ValueError('文件字段重复。')
                        files[name] = (part.get_filename(), part.get_payload(decode=True))
                    elif name in ('title', 'language'):
                        value = part.get_payload(decode=True)
                        if len(value) > 1000:
                            raise ValueError('书名过长。')
                        fields[name] = value.decode('utf-8')
                if set(files) != {'source', 'translation'}:
                    raise ValueError('请分别选择原文与译文文件。')
                conn = connect(self.db)
                try:
                    result = add_file_book(conn, Path(self.db).parent, fields.get('title', ''),
                        *files['source'], *files['translation'], fields.get('language', '原文'))
                    return self.send(result)
                finally:
                    conn.close()
            if not 0 < size <= 100_000:
                raise ValueError('请求大小无效。')
            data = json.loads(self.rfile.read(size))
            conn = connect(self.db)
            try:
                if self.path == '/api/align':
                    save_alignment(conn, data['paragraph_id'], data['page_ids'], data['quote'])
                elif self.path == '/api/unconfirm':
                    with conn:
                        conn.execute('DELETE FROM alignments WHERE paragraph_id=?', (data['paragraph_id'],))
                elif self.path == '/api/settings':
                    return self.send(self.settings.save(data['account_id'], data.get('token', '')))
                elif self.path == '/api/model-test':
                    if not self.ai:
                        raise ValueError('模型服务尚未启动。')
                    self.ai.provider.embed(['Connection test.'])
                    return self.send({'ok': True, 'message': '模型连接成功。'})
                elif self.path == '/api/index':
                    if not self.ai or not data.get('consent'):
                        raise ValueError('请确认将本书原文和译文片段发送到 Cloudflare 建立索引。')
                    return self.send(self.ai.start(data['book_id']))
                elif self.path == '/api/semantic':
                    if not self.ai or not data.get('consent'):
                        raise ValueError('请先启用模型查询。')
                    book_id = data['book_id']
                    books = file_books(conn, MODEL)
                    selected = next((b for b in books if b['id'] == book_id), None)
                    if not selected or not selected['index_ready']:
                        raise ValueError('请先完成这本书的语义索引。')
                    exact = [r for r in lexical_search(conn, data['query'], book_id, data.get('chapter', '')) if r['match'] == 'exact']
                    if exact:
                        return self.send({'results': exact})
                    vector = self.ai.query(conn, data['query'])
                    return self.send({'results': ranked_units(conn, vector, MODEL, book_id, 'translation', data.get('chapter', ''))})
                elif self.path == '/api/confirm-file':
                    confirm_pair(conn, data['translation_id'], data['source_id'], data.get('cancel', False), data.get('segments'))
                elif self.path == '/api/refine':
                    if not self.ai or data.get('consent') is not True:
                        raise ValueError('句段定位会把当前译文及少量原文候选发送至 Cloudflare，请先确认。')
                    self.ai.refine(conn, data['translation_id'], data.get('refresh') is True)
                    return self.send(file_detail(conn, data['translation_id'], MODEL))
                else:
                    return self.send({'error': 'Not found'}, 404)
                self.send({'ok': True})
            finally:
                conn.close()
        except (ValueError, KeyError, TypeError) as exc:
            self.send({'error': str(exc)}, 400)
        except Exception:
            self.send({'error': '保存失败，请重试。'}, 500)


def main():
    parser = argparse.ArgumentParser(description='从中文译文查找原文，所有书籍留在本地。')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest='command', required=True)
    workspace = commands.add_parser('import-workspace', help='导入现有 book_ocr 工作目录中有页码的书籍')
    workspace.add_argument('--root', type=Path, required=True)
    book = commands.add_parser('import-book', help='按本地 JSON 配置导入一本书')
    book.add_argument('spec', type=Path)
    export = commands.add_parser('export-alignments', help='导出人工确认的对应关系到本地 JSON')
    export.add_argument('output', type=Path)
    restore = commands.add_parser('restore-alignments', help='仅在文件哈希相符时恢复对应关系')
    restore.add_argument('input', type=Path)
    serve = commands.add_parser('serve')
    serve.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    conn = connect(args.db)
    try:
        if args.command == 'import-workspace':
            result = import_workspace(conn, args.root.resolve())
        elif args.command == 'import-book':
            spec_path = args.spec.resolve()
            result = import_book(conn, json.loads(spec_path.read_text(encoding='utf-8-sig')), spec_path.parent)
        elif args.command == 'export-alignments':
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(export_alignments(conn), ensure_ascii=False, indent=2), encoding='utf-8')
            result = {'exported': str(args.output)}
        elif args.command == 'restore-alignments':
            snapshot = json.loads(args.input.read_text(encoding='utf-8-sig'))
            if snapshot.get('format') != 'source-finder-alignments-v1':
                raise ValueError('不支持的对应关系格式。')
            # Prevalidate everything, then restore in one transaction.
            items = snapshot['alignments']
            for item in items:
                row = conn.execute('''SELECT c.source_hash,c.translation_hash FROM paragraphs p
                    JOIN chapters c ON c.id=p.chapter_id WHERE p.id=?''', (item['paragraph_id'],)).fetchone()
                if not row or any(row[k] != item[k] for k in ('source_hash', 'translation_hash')):
                    raise ValueError('原文或译文版本不符，不能恢复旧的对应关系。')
            # save_alignment uses a transaction, so validate against an in-memory clone first.
            trial = connect(Path(':memory:'))
            try:
                conn.backup(trial)
                for item in items:
                    save_alignment(trial, item['paragraph_id'], json.loads(item['page_ids']), item['quote'])
                with conn:
                    for item in items:
                        conn.execute('''INSERT INTO alignments(paragraph_id,page_ids,quote) VALUES(?,?,?)
                            ON CONFLICT(paragraph_id) DO UPDATE SET page_ids=excluded.page_ids,
                            quote=excluded.quote,reviewed_at=CURRENT_TIMESTAMP''',
                                     (item['paragraph_id'], item['page_ids'], item['quote']))
            finally:
                trial.close()
            result = {'restored': len(items)}
        else:
            conn.close()
            token = secrets.token_urlsafe(32)
            settings = Settings(args.db.parent)
            ai = AIService(args.db, settings)
            server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, db=args.db, token=token, settings=settings, ai=ai))
            print(f'原文查找已启动：http://127.0.0.1:{args.port}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, sqlite3.Error) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        sys.exit(1)
