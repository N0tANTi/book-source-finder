from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / 'data' / 'library.sqlite3'
SOURCE_MARKER = re.compile(r'^--- PDF page (\d+); printed page (.*?) ---\s*$', re.M)
ZH_MARKER = re.compile(r'<!--\s*原书第\s*([^<>]+?)\s*页\s*-->')


def normalize(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).strip()


def plain(text: str) -> str:
    text = re.sub(r'<sup\b[^>]*>.*?</sup>', '', text, flags=re.S)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'^\s*>\s?', '', text, flags=re.M)
    return html.unescape(text).strip()


def roman(number: int) -> str:
    result = ''
    for value, symbol in [(1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'),
                          (100, 'c'), (90, 'xc'), (50, 'l'), (40, 'xl'),
                          (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i')]:
        while number >= value:
            result += symbol
            number -= value
    return result


def source_pages(text: str, front_matter_start: int | None = None, page_headers: list[str] | None = None) -> list[dict]:
    markers = list(SOURCE_MARKER.finditer(text))
    if not markers:
        raise ValueError('原文缺少页码标记：--- PDF page 67; printed page 39 ---')
    pages = []
    for i, marker in enumerate(markers):
        label = marker[2].strip().casefold()
        if label == 'front matter':
            if front_matter_start is None:
                raise ValueError('前言页需要 front_matter_start，不能猜测罗马页码。')
            label = roman(front_matter_start + i)
        raw = text[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)].strip()
        # Raw extraction is retained. Only known running headers and a matching
        # trailing page number are removed from the reading copy.
        lines = raw.splitlines()
        if lines and lines[-1].strip().casefold() == label:
            lines.pop()
        known_headers = {whitespace(h).casefold() for h in page_headers or []}
        lines = [line for j, line in enumerate(lines)
                 if not (j < 4 and whitespace(line).casefold() in known_headers)]
        pages.append(dict(label=label, pdf_page=int(marker[1]), raw_text=raw,
                          text=whitespace('\n'.join(lines))))
    if len({p['label'] for p in pages}) != len(pages):
        raise ValueError('同一章的原书页码重复。')
    return pages


def translation_paragraphs(text: str) -> list[dict]:
    paragraphs, label, heading = [], None, ''
    # Split markers independently from blank lines, including markers inside paragraphs.
    chunks = ZH_MARKER.split(text)
    for i, chunk in enumerate(chunks):
        if i % 2:
            label = chunk.strip().casefold()
            continue
        for block in re.split(r'\n\s*\n', chunk):
            block = block.strip()
            if not block:
                continue
            if block.startswith('#'):
                heading = block.lstrip('#').strip()
                continue
            if re.match(r'^(原书页码[：:]|[-*_]{3,}$)', block):
                continue
            body = plain(block)
            if not body or not re.search(r'[\u3400-\u9fff]', body):
                continue
            if label is None:
                # Introductory prose before the first page marker has no provenance.
                continue
            paragraphs.append(dict(text=body, page_label=label, heading=heading))
    if not paragraphs:
        raise ValueError('译文没有带页码的中文段落；请添加 <!-- 原书第39页 -->。')
    return paragraphs


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS books (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, language TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chapters (
            id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            position INTEGER NOT NULL, title TEXT NOT NULL,
            source_path TEXT NOT NULL, translation_path TEXT NOT NULL,
            source_hash TEXT NOT NULL, translation_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            position INTEGER NOT NULL, label TEXT NOT NULL, pdf_page INTEGER NOT NULL,
            text TEXT NOT NULL, raw_text TEXT NOT NULL,
            UNIQUE(chapter_id, label));
        CREATE TABLE IF NOT EXISTS paragraphs (
            id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            position INTEGER NOT NULL, page_id TEXT NOT NULL REFERENCES pages(id),
            heading TEXT NOT NULL, text TEXT NOT NULL, normalized TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS alignments (
            paragraph_id TEXT PRIMARY KEY REFERENCES paragraphs(id) ON DELETE CASCADE,
            page_ids TEXT NOT NULL, quote TEXT NOT NULL, reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS paragraph_order ON paragraphs(chapter_id, position);
        CREATE INDEX IF NOT EXISTS page_order ON pages(chapter_id, position);
    ''')
    return conn


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def import_book(conn: sqlite3.Connection, spec: dict, base: Path) -> dict:
    book_id = spec['id']
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', book_id):
        raise ValueError('书籍 id 只能包含英文字母、数字、下划线或短横线。')
    if not spec.get('chapters'):
        raise ValueError('至少需要一章原文和译文。')
    prepared = []
    seen = set()
    for position, chapter in enumerate(spec['chapters']):
        cid = f"{book_id}:{chapter['id']}"
        if cid in seen:
            raise ValueError('章节 id 重复。')
        seen.add(cid)
        src = (base / chapter['source']).resolve()
        zh = (base / chapter['translation']).resolve()
        src_data, zh_data = src.read_bytes(), zh.read_bytes()
        pages = source_pages(src_data.decode('utf-8-sig'), chapter.get('front_matter_start'), chapter.get('page_headers'))
        paragraphs = translation_paragraphs(zh_data.decode('utf-8-sig'))
        labels = {p['label'] for p in pages}
        missing = {p['page_label'] for p in paragraphs} - labels
        if missing:
            raise ValueError(f"{chapter['title']}：译文页码在原文中不存在：{sorted(missing)}")
        source_options = json.dumps(dict(parser_version=2, front_matter_start=chapter.get('front_matter_start'),
                                        page_headers=chapter.get('page_headers')), sort_keys=True).encode()
        prepared.append((position, chapter, cid, src, zh, digest(src_data + source_options), digest(zh_data), pages, paragraphs))
    # Validate all files before mutating anything; each book is one transaction.
    changed = 0
    with conn:
        conn.execute('INSERT INTO books VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, language=excluded.language',
                     (book_id, spec['title'], spec.get('language', '原文')))
        for position, chapter, cid, src, zh, src_hash, zh_hash, pages, paragraphs in prepared:
            old = conn.execute('SELECT * FROM chapters WHERE id=?', (cid,)).fetchone()
            if old and old['source_hash'] == src_hash and old['translation_hash'] == zh_hash:
                conn.execute('UPDATE chapters SET position=?, title=?, source_path=?, translation_path=? WHERE id=?',
                             (position, chapter['title'], str(src), str(zh), cid))
                continue
            changed += 1
            # Any changed source invalidates chapter confirmations, including whitespace edits.
            conn.execute('DELETE FROM chapters WHERE id=?', (cid,))
            conn.execute('INSERT INTO chapters VALUES (?,?,?,?,?,?,?,?)',
                         (cid, book_id, position, chapter['title'], str(src), str(zh), src_hash, zh_hash))
            page_map = {}
            for j, page in enumerate(pages):
                pid = f'{cid}:page:{j}'
                page_map[page['label']] = pid
                conn.execute('INSERT INTO pages VALUES (?,?,?,?,?,?,?)',
                             (pid, cid, j, page['label'], page['pdf_page'], page['text'], page['raw_text']))
            for j, paragraph in enumerate(paragraphs):
                pid = f'{cid}:para:{j}'
                conn.execute('INSERT INTO paragraphs VALUES (?,?,?,?,?,?,?)',
                             (pid, cid, j, page_map[paragraph['page_label']], paragraph['heading'],
                              paragraph['text'], normalize(paragraph['text'])))
        for row in conn.execute('SELECT id FROM chapters WHERE book_id=?', (book_id,)).fetchall():
            if row['id'] not in seen:
                conn.execute('DELETE FROM chapters WHERE id=?', (row['id'],))
    return dict(book=spec['title'], chapters=len(prepared), changed_chapters=changed)


def import_workspace(conn: sqlite3.Connection, root: Path) -> list[dict]:
    results = []
    for folder, title, language in [('on_flirtation', '论调情 · 七章选译', '英文'),
                                     ('de_lintime', '论亲密 · 所选章节', '法文')]:
        manifest = root / 'work' / folder / 'source' / 'manifest.json'
        if not manifest.is_file():
            continue
        chapters = []
        for item in json.loads(manifest.read_text(encoding='utf-8')):
            slug = item['slug']
            translated = root / 'output' / folder / f'{slug}_zh.md'
            original = manifest.parent / f'{slug}.txt'
            if not translated.is_file() or not original.is_file():
                raise ValueError(f'书籍文件不完整：{folder}/{slug}')
            first_heading = translated.read_text(encoding='utf-8').splitlines()[0].lstrip('#').strip()
            chapter = dict(id=slug, title=first_heading, source=str(original), translation=str(translated))
            chapter['page_headers'] = [item['title'], 'ON FLIRTATION' if folder == 'on_flirtation' else 'DE L’INTIME']
            if folder == 'on_flirtation' and slug == '00_introduction':
                chapter['front_matter_start'] = 17
            chapters.append(chapter)
        results.append(import_book(conn, dict(id=folder, title=title, language=language, chapters=chapters), root))
    if not results:
        raise ValueError('该目录没有可导入的书籍；请用 import-book 导入自己的配对文件。')
    return results


def library(conn: sqlite3.Connection) -> dict:
    books = []
    for book in conn.execute('SELECT * FROM books ORDER BY title'):
        item = dict(book)
        item['chapters'] = [dict(row) for row in conn.execute('''
            SELECT c.id,c.title,COUNT(p.id) paragraph_count,COUNT(a.paragraph_id) verified_count
            FROM chapters c LEFT JOIN paragraphs p ON p.chapter_id=c.id
            LEFT JOIN alignments a ON a.paragraph_id=p.id
            WHERE c.book_id=? GROUP BY c.id ORDER BY c.position''', (book['id'],))]
        item['paragraph_count'] = sum(c['paragraph_count'] for c in item['chapters'])
        item['verified_count'] = sum(c['verified_count'] for c in item['chapters'])
        books.append(item)
    examples = [dict(r) for r in conn.execute('''
        SELECT p.id,p.text,b.title FROM paragraphs p JOIN chapters c ON c.id=p.chapter_id
        JOIN books b ON b.id=c.book_id LEFT JOIN alignments a ON a.paragraph_id=p.id
        WHERE length(p.normalized)>45
        ORDER BY (a.paragraph_id IS NOT NULL) DESC, c.position,p.position LIMIT 3''')]
    return dict(books=books, examples=examples)


def grams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)}


def search(conn: sqlite3.Connection, query: str, book_id: str = '', chapter_id: str = '') -> list[dict]:
    q = normalize(query)
    if len(q) < 2:
        raise ValueError('请输入至少两个文字。')
    if len(q) > 6000:
        raise ValueError('一次最多查询 6000 个文字，请缩短片段。')
    rows = conn.execute('''
        SELECT p.id,p.text,p.normalized,p.chapter_id,p.position,c.title chapter_title,
        b.id book_id,b.title book_title,pg.label page_label,
        a.paragraph_id IS NOT NULL AS verified
        FROM paragraphs p JOIN chapters c ON c.id=p.chapter_id
        JOIN books b ON b.id=c.book_id JOIN pages pg ON pg.id=p.page_id
        LEFT JOIN alignments a ON a.paragraph_id=p.id
        WHERE (?='' OR b.id=?) AND (?='' OR c.id=?)
        ORDER BY b.id,c.position,p.position''', (book_id, book_id, chapter_id, chapter_id)).fetchall()
    exact, approximate = [], []
    qgrams = grams(q)
    for i, row in enumerate(rows):
        item = dict(row)
        n = item.pop('normalized')
        if q in n:
            item.update(match='exact', score=1.0)
            exact.append(item)
            continue
        # Support copied excerpts crossing paragraph and page boundaries.
        if len(q) > 30:
            combined = n
            for following in rows[i + 1:i + 5]:
                if following['chapter_id'] != row['chapter_id']:
                    break
                combined += following['normalized']
                start = combined.find(q)
                if start >= 0 and start < len(n):
                    item.update(match='across', score=1.0)
                    exact.append(item)
                    break
            if item.get('match'):
                continue
        if len(q) >= 4:
            common = len(qgrams & grams(n))
            score = common / max(len(qgrams), 1)
            if common >= 2 and score >= 0.38:
                item.update(match='similar', score=round(score, 3))
                approximate.append(item)
    results = exact if exact else sorted(approximate, key=lambda r: -r['score'])
    return results[:20]


def detail(conn: sqlite3.Connection, paragraph_id: str) -> dict:
    row = conn.execute('''
        SELECT p.*, c.title chapter_title,b.title book_title,b.language,pg.label page_label
        FROM paragraphs p JOIN chapters c ON c.id=p.chapter_id
        JOIN books b ON b.id=c.book_id JOIN pages pg ON pg.id=p.page_id
        WHERE p.id=?''', (paragraph_id,)).fetchone()
    if not row:
        raise ValueError('该段落不存在；文件重新导入后请重新查询。')
    result = dict(row)
    result.pop('normalized')
    pages = [dict(p) for p in conn.execute(
        'SELECT id,position,label,pdf_page,text,raw_text FROM pages WHERE chapter_id=? ORDER BY position',
        (row['chapter_id'],))]
    source_position = next(p['position'] for p in pages if p['id'] == row['page_id'])
    result['source_pages'] = pages[max(0, source_position - 1):source_position + 3]
    result['chapter_page_count'] = len(pages)
    result['reader_pages'] = pages
    result['reader_paragraphs'] = [dict(p) for p in conn.execute('''
        SELECT p.id,p.text,p.position,p.page_id,pg.label page_label FROM paragraphs p
        JOIN pages pg ON pg.id=p.page_id WHERE p.chapter_id=? ORDER BY p.position''', (row['chapter_id'],))]
    result['context'] = [dict(p) for p in conn.execute('''
        SELECT p.id,p.text,p.position,pg.label page_label FROM paragraphs p
        JOIN pages pg ON pg.id=p.page_id WHERE p.chapter_id=? AND p.position BETWEEN ? AND ?
        ORDER BY p.position''', (row['chapter_id'], row['position'] - 1, row['position'] + 1))]
    result['alignment'] = None
    alignment = conn.execute('SELECT * FROM alignments WHERE paragraph_id=?', (paragraph_id,)).fetchone()
    if alignment:
        result['alignment'] = dict(alignment)
        result['alignment']['page_ids'] = json.loads(alignment['page_ids'])
        result['alignment']['pages'] = [p for p in pages if p['id'] in result['alignment']['page_ids']]
    return result


def save_alignment(conn: sqlite3.Connection, paragraph_id: str, page_ids: list[str], quote: str) -> None:
    paragraph = conn.execute('SELECT chapter_id FROM paragraphs WHERE id=?', (paragraph_id,)).fetchone()
    if not paragraph:
        raise ValueError('段落不存在。')
    if not isinstance(page_ids, list) or not 1 <= len(page_ids) <= 4 or len(set(page_ids)) != len(page_ids):
        raise ValueError('请选择一至四个连续原文页。')
    pages = []
    for pid in page_ids:
        page = conn.execute('SELECT * FROM pages WHERE id=? AND chapter_id=?', (pid, paragraph['chapter_id'])).fetchone()
        if not page:
            raise ValueError('原文页不属于该章节。')
        pages.append(page)
    pages.sort(key=lambda p: p['position'])
    if any(b['position'] != a['position'] + 1 for a, b in zip(pages, pages[1:])):
        raise ValueError('跨页选取必须使用连续原文页。')
    # Preserve punctuation in quote validation; never accept invented translations as source.
    original = whitespace(' '.join(p['text'] for p in pages))
    selected = whitespace(quote)
    if len(selected) < 8 or selected not in original:
        raise ValueError('所选内容必须是这些原文页中连续、完整的原文（至少 8 个字符）。')
    with conn:
        conn.execute('''INSERT INTO alignments(paragraph_id,page_ids,quote) VALUES(?,?,?)
            ON CONFLICT(paragraph_id) DO UPDATE SET page_ids=excluded.page_ids,
            quote=excluded.quote,reviewed_at=CURRENT_TIMESTAMP''',
                     (paragraph_id, json.dumps([p['id'] for p in pages]), selected))


def export_alignments(conn: sqlite3.Connection) -> dict:
    return dict(format='source-finder-alignments-v1', alignments=[dict(r) for r in conn.execute('''
        SELECT a.*,p.text translation,c.source_hash,c.translation_hash
        FROM alignments a JOIN paragraphs p ON p.id=a.paragraph_id
        JOIN chapters c ON c.id=p.chapter_id ORDER BY a.paragraph_id''')])
