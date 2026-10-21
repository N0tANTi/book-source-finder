"""Cloudflare embeddings with a local credential vault and resumable indexing."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import math
import os
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

MODEL = '@cf/baai/bge-m3'
MAX_JOB_CHARACTERS = 2_000_000


def protect(value: bytes, decrypt=False) -> bytes:
    """Windows DPAPI binds the saved token to the current OS user."""
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    incoming = Blob(len(value), buffer)
    outgoing = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
    else:
        fn = crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(incoming), 'Book Source Finder', None, None, None, 1, ctypes.byref(outgoing))
    if not ok:
        raise ValueError('系统无法保护或读取 Token，请在模型设置中重新填写。')
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel32.LocalFree(outgoing.data)


class Settings:
    def __init__(self, directory):
        self.path = Path(directory) / 'cloudflare.protected.json'
        self.lock = threading.RLock()
        self.account = ''
        self.token = ''
        self.storage = 'session'
        if self.path.is_file() and os.name == 'nt':
            try:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                self.account = saved['account_id']
                self.token = protect(base64.b64decode(saved['protected_token']), decrypt=True).decode('utf-8')
                self.storage = 'windows-dpapi'
            except Exception:
                # An unreadable vault must not leak content or prevent offline use.
                self.account, self.token = '', ''

    def credentials(self):
        with self.lock:
            account = os.environ.get('CLOUDFLARE_ACCOUNT_ID') or self.account
            token = os.environ.get('CLOUDFLARE_API_TOKEN') or self.token
            if not re.fullmatch(r'[a-fA-F0-9]{32}', account or '') or not token:
                raise ValueError('请先在模型设置中填写 Account ID 和 Workers AI API Token。')
            return account, token

    def status(self):
        with self.lock:
            try:
                account, _ = self.credentials()
                configured = True
            except ValueError:
                account, configured = self.account, False
            return dict(configured=configured, account_id=account, model=MODEL,
                        storage='environment' if os.environ.get('CLOUDFLARE_API_TOKEN') else self.storage)

    def save(self, account, token):
        if not isinstance(account, str) or not re.fullmatch(r'[a-fA-F0-9]{32}', account.strip()):
            raise ValueError('Account ID 应为 32 位十六进制字符。')
        account = account.strip()
        if not isinstance(token, str):
            raise ValueError('Token 格式无效。')
        with self.lock:
            if not token and account == self.account:
                token = self.token
            if not token or len(token) > 500 or re.search(r'\s', token):
                raise ValueError('请输入有效的 API Token。')
            if os.name == 'nt':
                encrypted = base64.b64encode(protect(token.encode())).decode()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(dict(account_id=account, protected_token=encrypted)), encoding='utf-8')
                temporary.replace(self.path)
                self.storage = 'windows-dpapi'
            self.account, self.token = account, token
            return self.status()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_vectors(data, count):
    try:
        rows = sorted(data['data'], key=lambda r: r['index'])
        if len(rows) != count or [r['index'] for r in rows] != list(range(count)):
            raise ValueError()
        vectors = [r['embedding'] for r in rows]
        size = len(vectors[0])
        if not 8 <= size <= 8192:
            raise ValueError()
        if any(len(v) != size or any(not isinstance(n, (int,float)) or not math.isfinite(n) for n in v)
               or not any(v) for v in vectors):
            raise ValueError()
        return vectors
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise ValueError('模型返回的向量数量或格式不正确，未保存这一批索引。') from exc


class Cloudflare:
    def __init__(self, settings):
        self.settings = settings

    def embed(self, texts):
        account, token = self.settings.credentials()
        request = urllib.request.Request(
            f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/embeddings',
            data=json.dumps(dict(model=MODEL, input=texts), ensure_ascii=False).encode('utf-8'),
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=45) as response:
                body = response.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise ValueError('模型响应过大。')
                return validate_vectors(json.loads(body), len(texts))
        except urllib.error.HTTPError as exc:
            if exc.code in (401,403):
                raise ValueError('Cloudflare 未授权，请检查 Account ID、Token 和 Workers AI 权限。') from None
            if exc.code == 429:
                raise ValueError('Cloudflare 额度或速率受限。已保存完成的索引，稍后可以继续。') from None
            raise ValueError(f'Cloudflare 请求失败（HTTP {exc.code}），已保留完成的索引。') from None
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise ValueError('暂时无法连接 Cloudflare，请检查网络后重试。') from None


class AIService:
    def __init__(self, db, settings, provider=None):
        self.db = Path(db)
        self.settings = settings
        self.provider = provider or Cloudflare(settings)
        self.lock = threading.Lock()
        self.alignment_lock = threading.Lock()
        self.running = set()
        from .core import connect
        conn = connect(self.db)
        with conn:
            conn.execute("UPDATE index_jobs SET status='paused',error='服务已重启，可继续建立索引。' WHERE status='running'")
        conn.close()

    def start(self, book_id):
        self.settings.credentials()
        acquired = False
        from .core import connect
        conn = connect(self.db)
        try:
            total = conn.execute('SELECT COUNT(*) FROM units u JOIN documents d ON d.id=u.document_id WHERE d.book_id=?', (book_id,)).fetchone()[0]
            if not total:
                raise ValueError('这本书没有可索引的配对文件，请使用“添加书籍”导入原文和译文。')
            with self.lock:
                if self.running:
                    raise ValueError('已有书籍正在建立索引，请等待完成后再开始下一本。')
                self.running.add(book_id)
                acquired = True
            with conn:
                conn.execute("INSERT INTO index_jobs VALUES(?,'running',0,?,'') ON CONFLICT(book_id) DO UPDATE SET status='running',total=excluded.total,error=''", (book_id,total))
        except Exception:
            if acquired:
                with self.lock:
                    self.running.discard(book_id)
            raise
        finally:
            conn.close()
        threading.Thread(target=self._run, args=(book_id,), daemon=True).start()
        return dict(started=True)

    def _run(self, book_id):
        from .core import connect
        conn = connect(self.db)
        used = 0
        try:
            rows = conn.execute('''SELECT u.id,u.text FROM units u JOIN documents d ON d.id=u.document_id
                WHERE d.book_id=? AND NOT EXISTS(SELECT 1 FROM vectors v WHERE v.unit_id=u.id AND v.model=?)
                ORDER BY d.role,u.position''', (book_id,MODEL)).fetchall()
            for i in range(0, len(rows), 24):
                batch = rows[i:i+24]
                used += sum(len(r['text']) for r in batch)
                if used > MAX_JOB_CHARACTERS:
                    raise ValueError('本轮已达到 200 万字符处理上限。已保存进度，稍后可继续。')
                vectors = self.provider.embed([r['text'] for r in batch])
                if len(vectors) != len(batch):
                    raise ValueError('向量数量不匹配。')
                with conn:
                    conn.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',
                                     [(r['id'],MODEL,json.dumps(v)) for r,v in zip(batch,vectors)])
                    done = conn.execute('''SELECT COUNT(*) FROM vectors v JOIN units u ON u.id=v.unit_id
                        JOIN documents d ON d.id=u.document_id WHERE d.book_id=? AND v.model=?''', (book_id,MODEL)).fetchone()[0]
                    conn.execute('UPDATE index_jobs SET done=? WHERE book_id=?', (done,book_id))
            with conn:
                conn.execute("UPDATE index_jobs SET status='ready',done=total,error='' WHERE book_id=?", (book_id,))
        except Exception as exc:
            # Only known, sanitized validation messages can reach the interface.
            message = str(exc) if isinstance(exc, ValueError) else '处理暂时中断，已保存完成的索引。'
            with conn:
                conn.execute("UPDATE index_jobs SET status='paused',error=? WHERE book_id=?", (message,book_id))
        finally:
            conn.close()
            with self.lock:
                self.running.discard(book_id)

    def query(self, conn, text):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 6000:
            raise ValueError('请输入 1 至 6000 个文字。')
        hashed = hashlib.sha256(text.encode('utf-8')).hexdigest()
        row = conn.execute('SELECT vector FROM query_vectors WHERE hash=? AND model=?', (hashed,MODEL)).fetchone()
        if row:
            return json.loads(row['vector'])
        vector = self.provider.embed([text])[0]
        with conn:
            conn.execute('INSERT OR REPLACE INTO query_vectors VALUES(?,?,?)', (hashed,MODEL,json.dumps(vector)))
            # Query cache is disposable and bounded; no query text is retained here.
            conn.execute('DELETE FROM query_vectors WHERE rowid NOT IN (SELECT rowid FROM query_vectors ORDER BY rowid DESC LIMIT 500)')
        return vector

    def refine(self, conn, translation_id, refresh=False):
        from .alignment import cached, prepare, refine_windows, remember_failure
        existing = cached(conn, translation_id)
        if existing and not refresh:
            return existing
        # Serialize sentence indexing and check the cache again: neighboring clicks
        # often share the same five-paragraph result.
        if not self.alignment_lock.acquire(timeout=60):
            raise ValueError('正在定位相邻段落，请稍后再试。')
        try:
            existing = cached(conn, translation_id)
            if existing and not refresh:
                return existing
            context = prepare(conn, translation_id, MODEL)
            try:
                return refine_windows(conn, context, self.provider)
            except ValueError:
                remember_failure(conn, translation_id)
                raise
        finally:
            self.alignment_lock.release()
