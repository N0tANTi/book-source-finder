"""Sentence/clause vectors and monotonic passage candidates over raw source offsets."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata

ALIGN_MODEL = '@cf/baai/bge-m3'
VERSION = 'clause-windows-v3'
MAX_CONTEXT = 18000


def init_schema(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS passage_cache(
        translation_id TEXT PRIMARY KEY REFERENCES units(id) ON DELETE CASCADE,
        fingerprint TEXT NOT NULL,model TEXT NOT NULL,state TEXT NOT NULL,
        segments TEXT NOT NULL,created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS passage_reviews(
        translation_id TEXT PRIMARY KEY REFERENCES file_reviews(translation_id) ON DELETE CASCADE,
        segments TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS alignment_vectors(
        book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        hash TEXT NOT NULL,model TEXT NOT NULL,vector TEXT NOT NULL,
        PRIMARY KEY(book_id,hash,model));
    ''')


def fingerprint(conn, translation_id):
    row = conn.execute('''SELECT t.sha256 translated,s.sha256 original,u.text FROM units u
        JOIN documents t ON t.id=u.document_id JOIN documents s ON s.book_id=t.book_id AND s.role='source'
        WHERE u.id=? AND t.role='translation' ''', (translation_id,)).fetchone()
    if not row:
        raise ValueError('译文位置不存在。')
    return hashlib.sha256((VERSION + ALIGN_MODEL + row['translated'] + row['original'] + row['text']).encode()).hexdigest()


def validate_segments(conn, translation_id, segments):
    if not isinstance(segments, list) or not 1 <= len(segments) <= 24:
        raise ValueError('句段范围无效。')
    target = conn.execute('SELECT d.book_id FROM units u JOIN documents d ON d.id=u.document_id WHERE u.id=? AND d.role=\'translation\'', (translation_id,)).fetchone()
    previous, total, first_position = (-1, -1), 0, None
    checked = []
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != {'unit_id', 'start', 'end'}:
            raise ValueError('句段范围无效。')
        row = conn.execute('''SELECT u.*,d.book_id,d.role FROM units u JOIN documents d ON d.id=u.document_id WHERE u.id=?''', (segment['unit_id'],)).fetchone()
        a, b = segment['start'], segment['end']
        if (not target or not row or row['role'] != 'source' or row['book_id'] != target['book_id']
                or type(a) is not int or type(b) is not int or not 0 <= a < b <= len(row['text'])
                or (row['position'], a) < previous):
            raise ValueError('句段范围跨书籍、越界或顺序有误。')
        previous = row['position'], b
        first_position = row['position'] if first_position is None else first_position
        if row['position'] - first_position > 12:
            raise ValueError('句段跨越的原文区域过多。')
        total += b - a
        checked.append(dict(unit_id=row['id'], start=a, end=b))
    if total > 8000:
        raise ValueError('句段范围过长，未保存。')
    return checked


def cached(conn, translation_id):
    row = conn.execute('SELECT * FROM passage_cache WHERE translation_id=?', (translation_id,)).fetchone()
    if not row or row['fingerprint'] != fingerprint(conn, translation_id):
        return None
    if row['state'] == 'unavailable' and time.time() - row['created'] > 300:
        return None
    try:
        segments = json.loads(row['segments'])
        if row['state'] not in {'candidate','uncertain','unavailable'} or (row['state']=='candidate' and not segments):
            return None
        if segments:
            segments = validate_segments(conn, translation_id, segments)
        return dict(state=row['state'], segments=segments, model=row['model'])
    except (ValueError, TypeError, KeyError):
        return None


def remember_failure(conn, translation_id):
    with conn:
        conn.execute('INSERT OR REPLACE INTO passage_cache VALUES(?,?,?,?,?,?)',
                     (translation_id,fingerprint(conn,translation_id),ALIGN_MODEL,'unavailable','[]',time.time()))


def canonical_cluster(rows):
    """Normalize only the model view; retain a mapping to every raw character."""
    chars, mapping = [], []
    for row in rows:
        raw = row['text']
        start = 0
        # Recognize a PDF running header, not arbitrary prose or chapter titles.
        if row.get('format') == 'pdf':
            header = re.match(r'^.{0,75}?\(\s*\)\s*(?:\d+|[ivxlcdm]+)\s+', raw, re.I)
            if header:
                start = header.end()
        if chars:
            chars.append(' '); mapping.append(None)
        for offset in range(start, len(raw)):
            for char in unicodedata.normalize('NFKC', raw[offset]):
                chars.append(char); mapping.append((row['id'], offset))
    text = ''.join(chars)
    removed = set()
    for match in re.finditer(r'([A-Za-z]{2,})-\s+(?=[a-z])', text):
        # Keep common compound prefixes; otherwise repair PDF line hyphenation.
        a = match.start() + len(match[1])
        if match[1].lower() in {'all','self','non','anti','co','pre','post','de','re','cross'}:
            a += 1
        removed.update(range(a, match.end()))
    clean, offsets = [], []
    for i, char in enumerate(chars):
        if i in removed:
            continue
        char = ' ' if char.isspace() else char
        if char == ' ' and (not clean or clean[-1] == ' '):
            continue
        clean.append(char); offsets.append(mapping[i])
    return ''.join(clean), offsets


def sentence_ranges(text):
    start = 0
    for match in re.finditer(r'[;:—]|[.!?。！？](?:["”’\)\]]+)?(?=\s|$)', text):
        prefix = text[max(0, match.start() - 12):match.start() + 1]
        if re.search(r'\b(?:Mr|Mrs|Ms|Dr|Prof|St|vs|etc|e\.g|i\.e|[A-Z])\.$', prefix):
            continue
        following = text[match.end():].lstrip()
        if text[match.start()] in '.!?' and following and following[0].islower():
            continue
        end = match.end()
        if end - start >= 15:
            yield start, end
            start = end
            while start < len(text) and text[start].isspace():
                start += 1
    if start < len(text):
        yield start, len(text)


def prepare(conn, translation_id, model):
    from .documents import ranked_units
    row = conn.execute('''SELECT u.*,d.book_id FROM units u JOIN documents d ON d.id=u.document_id
        WHERE u.id=? AND d.role='translation' ''', (translation_id,)).fetchone()
    if not row:
        raise ValueError('译文位置不存在。')
    if len(row['normalized']) < 20:
        raise ValueError('这一项太短，暂不做段落边界定位。')
    nearby = [dict(r) for r in conn.execute('''SELECT * FROM units WHERE document_id=? AND section=?
        AND position BETWEEN ? AND ? ORDER BY position''',
        (row['document_id'], row['section'], row['position'] - 2, row['position'] + 2))
        if len(r['normalized']) >= 20]
    source = [dict(r) for r in conn.execute('''SELECT u.*,d.format FROM units u JOIN documents d ON d.id=u.document_id
        WHERE d.book_id=? AND d.role='source' ORDER BY u.position''', (row['book_id'],))]
    selected, size, anchor = set(), 0, None
    # Target neighborhood first, then neighboring translated paragraphs. This is
    # candidate retrieval only; the local optimizer enforces source order.
    priority = sorted(nearby, key=lambda r: abs(r['position'] - row['position']))
    for translated in priority:
        vector = conn.execute('SELECT vector FROM vectors WHERE unit_id=? AND model=?', (translated['id'], model)).fetchone()
        if not vector:
            continue
        for hit in ranked_units(conn, json.loads(vector[0]), model, row['book_id'], 'source')[:1]:
            if anchor is None:
                anchor = hit['position']
            if abs(hit['position'] - anchor) > 4:
                continue
            additions = [r for r in source if abs(r['position'] - hit['position']) <= 2
                         and abs(r['position'] - anchor) <= 4 and r['position'] not in selected]
            extra = sum(len(r['text']) for r in additions)
            if size + extra <= MAX_CONTEXT:
                size += extra; selected.update(r['position'] for r in additions)
    if not selected:
        raise ValueError('请先建立语义索引。')
    clusters = []
    for r in source:
        if r['position'] not in selected:
            continue
        if not clusters or r['position'] != clusters[-1][-1]['position'] + 1:
            clusters.append([])
        clusters[-1].append(r)
    sentences = []
    for cluster, rows in enumerate(clusters):
        text, offsets = canonical_cluster(rows)
        for a, b in sentence_ranges(text):
            sentences.append(dict(id=len(sentences), cluster=cluster, text=text[a:b], offsets=offsets[a:b]))
    lengths = dict(conn.execute('''SELECT d.role,SUM(length(u.normalized)) FROM units u JOIN documents d ON d.id=u.document_id
        WHERE d.book_id=? GROUP BY d.role''', (row['book_id'],)))
    ratio = min(8, max(.5, lengths['source'] / max(1,lengths['translation'])))
    return dict(target=translation_id, book_id=row['book_id'], ratio=ratio, paragraphs=nearby, sentences=sentences)


def fragment_vectors(conn, book_id, texts, provider):
    texts = list(dict.fromkeys(texts))
    if len(texts) > 1200 or sum(map(len,texts)) > 800000:
        raise ValueError('句级候选过多，暂不高亮；可缩小章节后重试。')
    values, pending = {}, []
    for text in texts:
        hashed = hashlib.sha256(text.encode()).hexdigest()
        row = conn.execute('SELECT vector FROM alignment_vectors WHERE book_id=? AND hash=? AND model=?', (book_id,hashed,ALIGN_MODEL)).fetchone()
        if row:
            values[text] = json.loads(row[0])
        else:
            pending.append((text,hashed))
    for offset in range(0,len(pending),24):
        batch = pending[offset:offset+24]
        vectors = provider.embed([t for t,h in batch])
        if len(vectors) != len(batch):
            raise ValueError('句级向量数量不正确。')
        with conn:
            conn.executemany('INSERT OR REPLACE INTO alignment_vectors VALUES(?,?,?,?)',
                [(book_id,h,ALIGN_MODEL,json.dumps(v)) for (t,h),v in zip(batch,vectors)])
        values.update((t,v) for (t,h),v in zip(batch,vectors))
    return values


def refine_windows(conn, context, provider):
    from .documents import cosine, normalized
    windows = []
    sentences = context['sentences']
    for a in range(len(sentences)):
        for b in range(a,min(a+12,len(sentences))):
            if sentences[b]['cluster'] != sentences[a]['cluster']:
                break
            text = ' '.join(s['text'] for s in sentences[a:b+1])
            if len(text) > 2400:
                break
            windows.append(dict(start=a,end=b,text=text,length=len(normalized(text))))
    vectors = fragment_vectors(conn, context['book_id'],
        [r['text'] for r in context['paragraphs']] + [w['text'] for w in windows], provider)
    levels = []
    for i, paragraph in enumerate(context['paragraphs']):
        current = []
        expected = max(1,len(paragraph['normalized']) * context['ratio'])
        for w in windows:
            similarity = cosine(vectors[paragraph['text']],vectors[w['text']])
            score = similarity - .09 * abs(math.log(max(1,w['length']) / expected))
            item = dict(w, similarity=similarity, local_score=score, path_score=-1e9, previous=None)
            if i == 0:
                item['path_score'] = score
            else:
                for p in levels[-1]:
                    if p['end'] >= w['start'] or sentences[p['start']]['cluster'] != sentences[w['start']]['cluster']:
                        continue
                    gap = w['start'] - p['end'] - 1
                    candidate = p['path_score'] + score - .045 * gap
                    if candidate > item['path_score']:
                        item['path_score'], item['previous'] = candidate, p
            current.append(item)
        levels.append(current)
    if not levels or not levels[-1]:
        raise ValueError('没有可定位的句段。')
    chosen, path = max(levels[-1],key=lambda w:w['path_score']), []
    while chosen:
        path.append(chosen); chosen = chosen['previous']
    path.reverse()
    records = []
    for i, paragraph in enumerate(context['paragraphs']):
        existing = cached(conn, paragraph['id'])
        if paragraph['id'] != context['target'] and existing and existing['state'] == 'candidate':
            continue
        segments = []
        if len(path) == len(context['paragraphs']):
            w = path[i]
            coverage = w['length'] / max(1,len(paragraph['normalized']) * context['ratio'])
            if w['similarity'] >= .58 and .55 <= coverage <= 2.5:
                start = w['start']
                lower = path[i-1]['end'] + 1 if i else 0
                # Do not strand a short introductory clause before an em-dash
                # (e.g. "In the conversation—"). Never overlap the prior pair.
                while start > lower:
                    previous = sentences[start-1]
                    if (previous['cluster'] != sentences[start]['cluster'] or len(previous['text']) > 60
                            or not previous['text'].rstrip().endswith(('—',':',';'))):
                        break
                    start -= 1
                offsets = [point for s in sentences[start:w['end']+1] for point in s['offsets']]
                segments = validate_segments(conn, paragraph['id'], segments_from_offsets(offsets))
        records.append((paragraph['id'],fingerprint(conn,paragraph['id']),ALIGN_MODEL,
                        'candidate' if segments else 'uncertain',json.dumps(segments),time.time()))
    with conn:
        conn.executemany('INSERT OR REPLACE INTO passage_cache VALUES(?,?,?,?,?,?)', records)
    return cached(conn,context['target'])


def segments_from_offsets(offsets):
    segments = []
    for point in offsets:
        if point is None:
            continue
        unit_id, offset = point
        if segments and segments[-1]['unit_id'] == unit_id and segments[-1]['end'] - 1 <= offset <= segments[-1]['end'] + 4:
            segments[-1]['end'] = offset + 1
        else:
            segments.append(dict(unit_id=unit_id, start=offset, end=offset + 1))
    return segments
