"""Local file library, independent of pre-existing page-aligned imports."""
from __future__ import annotations

import hashlib
import io
import json
import math
import posixpath
import re
import shutil
import sqlite3
import uuid
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

MAX_FILE = 80 * 1024 * 1024
MAX_EXPANDED = 200 * 1024 * 1024
MAX_UNITS = 30000
EXTENSIONS = {'.epub', '.pdf', '.md', '.txt'}


def init_schema(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS documents(
        id TEXT PRIMARY KEY,book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('source','translation')),name TEXT NOT NULL,
        path TEXT NOT NULL,format TEXT NOT NULL,sha256 TEXT NOT NULL,
        UNIQUE(book_id,role));
      CREATE TABLE IF NOT EXISTS units(
        id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,section TEXT NOT NULL,location TEXT NOT NULL,
        reference TEXT NOT NULL,text TEXT NOT NULL,normalized TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS unit_document ON units(document_id,position);
      CREATE TABLE IF NOT EXISTS vectors(
        unit_id TEXT NOT NULL REFERENCES units(id) ON DELETE CASCADE,
        model TEXT NOT NULL,vector TEXT NOT NULL,PRIMARY KEY(unit_id,model));
      CREATE TABLE IF NOT EXISTS file_reviews(
        translation_id TEXT PRIMARY KEY REFERENCES units(id) ON DELETE CASCADE,
        source_id TEXT NOT NULL REFERENCES units(id) ON DELETE CASCADE);
      CREATE TABLE IF NOT EXISTS index_jobs(
        book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
        status TEXT NOT NULL,done INTEGER NOT NULL,total INTEGER NOT NULL,
        error TEXT NOT NULL DEFAULT '');
      CREATE TABLE IF NOT EXISTS query_vectors(
        hash TEXT NOT NULL,model TEXT NOT NULL,vector TEXT NOT NULL,
        PRIMARY KEY(hash,model));
    ''')


def normalized(text):
    from .core import normalize
    return normalize(text)


def text_chunks(text, limit=1100):
    """Keep exact wording; split long prose at sentence/space boundaries."""
    text = re.sub(r'\s+', ' ', text).strip()
    while len(text) > limit:
        bounds = [m.end() for m in re.finditer(r'[。！？.!?](?:[”’\"\']?)(?:\s|(?=[\u3400-\u9fff]))', text[:limit])]
        end = next((b for b in reversed(bounds) if b >= limit // 2), 0)
        if not end:
            end = text.rfind(' ', limit // 2, limit) + 1 or limit
        yield text[:end].strip()
        text = text[end:].strip()
    if text:
        yield text


class ProseParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.buffer = []
        self.parts = []
        self.heading = ''
        self.heading_tag = ''

    def flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self.buffer)).strip()
        if text:
            self.parts.append(text)
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if self.skip:
            return
        if tag in ('p', 'div', 'li', 'blockquote', 'h1', 'h2', 'h3'):
            self.flush()
        if tag in ('h1', 'h2', 'h3') and not self.heading:
            self.heading_tag = tag
        if tag == 'br':
            self.buffer.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == self.heading_tag and not self.heading:
            self.heading = re.sub(r'\s+', ' ', ''.join(self.buffer)).strip()
            self.heading_tag = ''
        if tag in ('p', 'div', 'li', 'blockquote', 'h1', 'h2', 'h3'):
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buffer.append(data)


def xml(data):
    if b'<!ENTITY' in data.upper():
        raise ValueError('不支持含自定义 XML 实体的 EPUB。')
    return ET.fromstring(data)


def extract_epub(data):
    output = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_EXPANDED:
                raise ValueError('EPUB 解压内容过大，请使用较小的文件。')
            container = xml(archive.read('META-INF/container.xml'))
            rootfile = next(e for e in container.iter() if e.tag.endswith('rootfile'))
            opf_path = rootfile.attrib['full-path']
            package = xml(archive.read(opf_path))
            manifest = {e.attrib['id']: e.attrib for e in package.iter() if e.tag.endswith('}item')}
            spine = [e.attrib['idref'] for e in package.iter()
                     if e.tag.endswith('itemref') and e.attrib.get('linear', 'yes') != 'no']
            for section_position, item_id in enumerate(spine):
                item = manifest.get(item_id, {})
                if 'nav' in item.get('properties', '').split():
                    continue
                href = item.get('href', '')
                if urlsplit(href).scheme or urlsplit(href).netloc:
                    raise ValueError('EPUB 正文必须保存在文件内部。')
                member = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), unquote(urlsplit(href).path)))
                if member.startswith('../') or member.startswith('/'):
                    raise ValueError('EPUB 正文路径无效。')
                if item.get('media-type') not in ('application/xhtml+xml', 'text/html'):
                    continue
                parser = ProseParser()
                parser.feed(archive.read(member).decode('utf-8-sig'))
                parser.flush()
                title = parser.heading or f'第 {section_position + 1} 节'
                section = f'{section_position}:{title}'
                for pindex, paragraph in enumerate(parser.parts):
                    for chunk in text_chunks(paragraph):
                        if len(normalized(chunk)) >= 2:
                            output.append(dict(section=section, location=title,
                                               reference=f'{member}#text-{pindex + 1}', text=chunk))
    except (zipfile.BadZipFile, KeyError, StopIteration, ET.ParseError, UnicodeError, RuntimeError) as exc:
        raise ValueError('EPUB 无法读取，可能损坏、加密或缺少正文。') from exc
    return output


def extract_pdf(data):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError('PDF 提取组件尚未安装，请在本工具目录运行 pip install -e .。') from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('PDF 已加密，请先提供可读取的版本。')
        if len(reader.pages) > 3000:
            raise ValueError('PDF 超过 3000 页，请按卷导入。')
        output = []
        for i, page in enumerate(reader.pages):
            raw = page.extract_text() or ''
            for chunk in text_chunks(raw):
                if len(normalized(chunk)) >= 2:
                    # A modest section window keeps large PDFs readable without
                    # inventing chapter boundaries that are not in the source.
                    section = f'PDF 页 {i // 12 * 12 + 1}–{min((i // 12 + 1) * 12, len(reader.pages))}'
                    output.append(dict(section=section, location=f'PDF 第 {i + 1} 页',
                                       reference=f'page={i + 1}', text=chunk))
        if len(''.join(p['text'] for p in output)) < max(30, len(reader.pages) * 10):
            raise ValueError('PDF 缺少可提取文字，可能是扫描版；请先 OCR 后再导入。')
        return output
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PDF 文字提取失败，请检查文件是否完整。') from exc


def extract_document(name, data):
    suffix = Path(name).suffix.lower()
    if suffix not in EXTENSIONS:
        raise ValueError('支持 EPUB、PDF、Markdown 和 TXT。')
    if not data or len(data) > MAX_FILE:
        raise ValueError('文件为空或超过 80 MB。')
    if suffix == '.epub':
        output = extract_epub(data)
    elif suffix == '.pdf':
        output = extract_pdf(data)
    else:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeError as exc:
            raise ValueError('文本请保存为 UTF-8 编码。') from exc
        from .core import plain
        section, output = '正文', []
        for block in re.split(r'\n\s*\n', text):
            if block.strip().startswith('#'):
                section = block.strip().lstrip('#').strip() or section
                continue
            for chunk in text_chunks(plain(block)):
                if len(normalized(chunk)) >= 2:
                    output.append(dict(section=section, location=section, reference=f'block={len(output) + 1}', text=chunk))
    if not output:
        raise ValueError('文件没有可读取的正文，请检查是否为图片版或加密文件。')
    if len(output) > MAX_UNITS:
        raise ValueError('文本片段超过 30000 个，请分卷导入。')
    return output


def add_file_book(conn, directory, title, source_name, source_data, translation_name, translation_data, language='原文'):
    # Both books are parsed before retaining files or changing the library.
    source = extract_document(source_name, source_data)
    translation = extract_document(translation_name, translation_data)
    if hashlib.sha256(source_data).digest() == hashlib.sha256(translation_data).digest():
        raise ValueError('原文与译文是同一个文件，请分别选择。')
    existing = conn.execute('''SELECT s.book_id,b.title FROM documents s JOIN documents t ON s.book_id=t.book_id
        JOIN books b ON b.id=s.book_id WHERE s.role='source' AND t.role='translation'
        AND s.sha256=? AND t.sha256=?''', (hashlib.sha256(source_data).hexdigest(), hashlib.sha256(translation_data).hexdigest())).fetchone()
    if existing:
        return dict(id=existing['book_id'], title=existing['title'], existing=True)
    Path(directory).mkdir(parents=True, exist_ok=True)
    capacity = shutil.disk_usage(directory)
    peak = (len(source_data) + len(translation_data)) * 3 + 100 * 1024 * 1024
    if capacity.free - peak < capacity.total * .1:
        raise ValueError('本地数据盘空间不足，导入后无法保留 10% 可用空间。')
    book_id = 'book-' + uuid.uuid4().hex
    folder = Path(directory) / 'books' / book_id
    folder.mkdir(parents=True)
    written = []
    try:
        with conn:
            conn.execute('INSERT INTO books VALUES(?,?,?)', (book_id, title.strip()[:200] or Path(translation_name).stem, language[:30]))
            for role, name, data, units in [('source', source_name, source_data, source),
                                            ('translation', translation_name, translation_data, translation)]:
                suffix = Path(name).suffix.lower()
                path = folder / (role + suffix)
                path.write_bytes(data)
                written.append(path)
                doc_id = book_id + ':' + role
                conn.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',
                             (doc_id, book_id, role, Path(name.replace('\\', '/')).name[:250], str(path), suffix[1:], hashlib.sha256(data).hexdigest()))
                conn.executemany('INSERT INTO units VALUES(?,?,?,?,?,?,?,?)',
                                 [(f'unit:{doc_id}:{i}', doc_id, i, u['section'], u['location'], u['reference'],
                                   u['text'], normalized(u['text'])) for i, u in enumerate(units)])
    except Exception:
        # Only the new, unique folder is touched; existing book files are never overwritten.
        for path in written:
            path.unlink(missing_ok=True)
        folder.rmdir()
        raise
    return {'id': book_id, 'title': title.strip() or Path(translation_name).stem,
            'source_count': len(source), 'translation_count': len(translation)}


def file_books(conn, model):
    result = []
    for row in conn.execute('SELECT b.* FROM books b WHERE EXISTS(SELECT 1 FROM documents d WHERE d.book_id=b.id) ORDER BY b.title'):
        item = dict(row)
        item['kind'] = 'files'
        item['files'] = [dict(r) for r in conn.execute('''SELECT d.role,d.name,d.format,COUNT(u.id) unit_count,
            COUNT(v.unit_id) indexed_count FROM documents d LEFT JOIN units u ON u.document_id=d.id
            LEFT JOIN vectors v ON v.unit_id=u.id AND v.model=? WHERE d.book_id=? GROUP BY d.id''', (model, row['id']))]
        item['paragraph_count'] = sum(f['unit_count'] for f in item['files'] if f['role'] == 'translation')
        item['verified_count'] = conn.execute('''SELECT COUNT(*) FROM file_reviews r JOIN units u ON u.id=r.translation_id
            JOIN documents d ON d.id=u.document_id WHERE d.book_id=?''', (row['id'],)).fetchone()[0]
        item['chapters'] = [dict(r) for r in conn.execute('''SELECT section AS id,location AS title,COUNT(*) paragraph_count
            FROM units u JOIN documents d ON d.id=u.document_id WHERE d.book_id=? AND d.role='translation'
            GROUP BY section ORDER BY MIN(u.position)''', (row['id'],))]
        total = sum(f['unit_count'] for f in item['files'])
        indexed = sum(f['indexed_count'] for f in item['files'])
        item.update(total_units=total, indexed_units=indexed, index_ready=total > 0 and total == indexed)
        job = conn.execute('SELECT status,done,total,error FROM index_jobs WHERE book_id=?', (row['id'],)).fetchone()
        item['job'] = dict(job) if job else None
        result.append(item)
    return result


def lexical_search(conn, query, book_id, section=''):
    q = normalized(query)
    if not q or len(q) > 6000:
        raise ValueError('请输入 1 至 6000 个文字。')
    from .core import grams
    qgrams = grams(q)
    exact, near = [], []
    for row in conn.execute('''SELECT u.*,b.title book_title,b.id book_id FROM units u JOIN documents d ON d.id=u.document_id
        JOIN books b ON b.id=d.book_id WHERE (?='' OR d.book_id=?) AND d.role='translation' AND (?='' OR u.section=?)
        ORDER BY b.title,u.position''', (book_id, book_id, section, section)):
        item = dict(row)
        item.update(chapter_title=item['location'], page_label=item['location'], kind='files', verified=0)
        if q in item['normalized']:
            item.update(match='exact', score=1)
            exact.append(item)
        elif len(q) >= 4:
            score = len(qgrams & grams(item['normalized'])) / max(1, len(qgrams))
            if score >= .4:
                item.update(match='similar', score=score)
                near.append(item)
    # A substantive match provides more context than a repeated chapter heading.
    exact.sort(key=lambda i: len(i['normalized']) < 60)
    return (exact or sorted(near, key=lambda i: -i['score']))[:20]


def cosine(left, right):
    if len(left) != len(right):
        raise ValueError('向量维度不一致，请重新建立本书索引。')
    a = math.sqrt(sum(x*x for x in left))
    b = math.sqrt(sum(x*x for x in right))
    return sum(x*y for x,y in zip(left, right)) / (a*b) if a and b else 0


def ranked_units(conn, vector, model, book_id, role, section=''):
    results = []
    for row in conn.execute('''SELECT u.*,v.vector,b.title book_title,b.id book_id FROM units u
        JOIN vectors v ON v.unit_id=u.id AND v.model=? JOIN documents d ON d.id=u.document_id
        JOIN books b ON b.id=d.book_id WHERE d.book_id=? AND d.role=? AND (?='' OR u.section=?)''',
        (model, book_id, role, section, section)):
        item = dict(row)
        item['score'] = round(cosine(vector, json.loads(item.pop('vector'))), 4)
        item.update(chapter_title=item['location'], page_label=item['location'], kind='files', verified=0, match='semantic')
        results.append(item)
    # For descriptions, show substantive reading passages before short titles or
    # glossary labels. Exact phrase/word search still includes every text unit.
    if role == 'translation':
        prose = [r for r in results if len(normalized(r['text'])) >= 60]
        if prose:
            results = prose
    return sorted(results, key=lambda i: -i['score'])[:5]


def file_detail(conn, unit_id, model, source_id=''):
    row = conn.execute('''SELECT u.*,b.title book_title,b.id book_id,b.language FROM units u
        JOIN documents d ON d.id=u.document_id JOIN books b ON b.id=d.book_id
        WHERE u.id=? AND d.role='translation' ''', (unit_id,)).fetchone()
    if not row:
        raise ValueError('译文位置不存在，请重新打开书籍。')
    result = dict(row)
    result['kind'] = 'files'
    review = conn.execute('SELECT source_id FROM file_reviews WHERE translation_id=?', (unit_id,)).fetchone()
    candidates = []
    vector = conn.execute('SELECT vector FROM vectors WHERE unit_id=? AND model=?', (unit_id, model)).fetchone()
    if vector:
        candidates = ranked_units(conn, json.loads(vector['vector']), model, row['book_id'], 'source')
    chosen = source_id or (review['source_id'] if review else '') or (candidates[0]['id'] if candidates else '')
    source = conn.execute('''SELECT u.* FROM units u JOIN documents d ON d.id=u.document_id
        WHERE d.book_id=? AND d.role='source' AND (?='' OR u.id=?) ORDER BY u.position LIMIT 1''',
        (row['book_id'], chosen, chosen)).fetchone()
    if not source:
        raise ValueError('原文位置不存在。')
    result.update(source_id=source['id'], candidates=candidates,
                  verified=bool(review and review['source_id'] == source['id']),
                  candidate=bool(candidates or review),
                  source_location=source['location'], translation_location=row['location'])
    result['source_sections'] = [dict(r) for r in conn.execute('''SELECT u.id,u.section FROM units u
        JOIN (SELECT section,MIN(position) first_position FROM units WHERE document_id=? GROUP BY section) s
          ON s.section=u.section AND s.first_position=u.position
        WHERE u.document_id=? ORDER BY u.position''', (source['document_id'], source['document_id']))]
    result['source_section'] = source['section']
    result['translation_units'] = [dict(r) for r in conn.execute('SELECT id,text,location FROM units WHERE document_id=? AND section=? ORDER BY position', (row['document_id'], row['section']))]
    result['source_units'] = [dict(r) for r in conn.execute('SELECT id,text,location FROM units WHERE document_id=? AND section=? ORDER BY position', (source['document_id'], source['section']))]
    return result


def confirm_pair(conn, translation_id, source_id, cancel=False):
    rows = conn.execute('''SELECT u.id,d.book_id,d.role FROM units u JOIN documents d ON d.id=u.document_id
                           WHERE u.id IN (?,?)''', (translation_id, source_id)).fetchall()
    by_role = {r['role']: r for r in rows}
    if (len(rows) != 2 or set(by_role) != {'source','translation'}
            or by_role['source']['id'] != source_id or by_role['translation']['id'] != translation_id
            or by_role['source']['book_id'] != by_role['translation']['book_id']):
        raise ValueError('只能确认同一本书的原文与译文对应。')
    with conn:
        if cancel:
            conn.execute('DELETE FROM file_reviews WHERE translation_id=?', (translation_id,))
        else:
            conn.execute('INSERT INTO file_reviews VALUES(?,?) ON CONFLICT(translation_id) DO UPDATE SET source_id=excluded.source_id', (translation_id, source_id))
