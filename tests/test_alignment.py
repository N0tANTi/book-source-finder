import json
import re
import tempfile
import unittest
from pathlib import Path

from source_finder.ai import AIService, MODEL
from source_finder.alignment import (cached, canonical_cluster, fragment_vectors,
                                     segments_from_offsets, validate_segments)
from source_finder.core import connect
from source_finder.documents import add_file_book, confirm_pair, file_detail, lexical_search
from test_documents import epub, FakeSettings


class SemanticFixture:
    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        features = [('rain','雨'), ('windows','窗'), ('sky','晴'), ('sun','光'),
                    ('wind','风'), ('trees','树'), ('dragon','龙')]
        output = []
        for text in texts:
            vector = [int(bool(re.search(r'\b'+english+r'\b',text.lower())) or chinese in text) for english,chinese in features] + [0]
            if 'clocks' in text.lower():
                vector[-1] = 1
            if not any(vector):
                vector[-1] = 1
            output.append(vector)
        return output


class PassageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'test.sqlite3'
        self.conn = connect(self.db)
        self.provider = SemanticFixture()
        source = ('An unrelated sentence about clocks. Rain covers the quiet gar-\n\n'
                  'chapter one ( ) 13 den. Windows remain open. The sky is clear in the early morning. '
                  'Sun shines warmly across the room. Wind moves the trees and gently sways their leafy branches.')
        self.chinese = ['雨落在安静的花园里，窗户仍然敞开，可以听见远处的雨声。',
                        '早晨带来了晴朗的天空，温暖的阳光照亮房间，使人慢慢醒来。',
                        '风吹过树林，树叶随着微风摇摆，树木的枝条也轻轻地晃动。']
        self.book = add_file_book(self.conn,self.root,'Synthetic pair','source.txt',source.encode(),
                                  'translation.epub',epub(self.chinese,'第一章'))
        with self.conn:
            self.conn.execute("UPDATE documents SET format='pdf' WHERE id=?", (self.book['id']+':source',))
            source_rows = self.conn.execute('SELECT id,position FROM units WHERE document_id=? ORDER BY position', (self.book['id']+':source',)).fetchall()
            for row in source_rows:
                self.conn.execute('UPDATE units SET section=?,location=? WHERE id=?',
                    (f'PDF window {row["position"]}',f'PDF page {12+row["position"]}',row['id']))
            rows = self.conn.execute('SELECT id,text FROM units WHERE document_id IN (?,?)',
                (self.book['id']+':source',self.book['id']+':translation')).fetchall()
            self.conn.executemany('INSERT INTO vectors VALUES(?,?,?)',
                [(r['id'],MODEL,json.dumps(v)) for r,v in zip(rows,self.provider.embed([r['text'] for r in rows]))])
        self.target = lexical_search(self.conn,self.chinese[1],self.book['id'])[0]
        self.service = AIService(self.db,FakeSettings(),self.provider)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_range_alignment_crosses_pages_excludes_context_and_preserves_order(self):
        before = file_detail(self.conn,self.target['id'],MODEL)
        self.assertEqual(before['source_segments'],[])
        self.assertTrue(before['needs_refinement'])
        self.service.refine(self.conn,self.target['id'])
        details = [file_detail(self.conn,lexical_search(self.conn,t,self.book['id'])[0]['id'],MODEL) for t in self.chinese]
        first,second,third = details
        self.assertEqual(len(first['source_segments']),2)
        self.assertTrue(first['source_quote'].startswith('Rain'))
        self.assertTrue(first['source_quote'].endswith('open.'))
        self.assertNotIn('clocks',first['source_quote'])
        self.assertNotIn('chapter one',first['source_quote'])
        self.assertIn('sky',second['source_quote'])
        self.assertIn('Sun',second['source_quote'])
        self.assertNotIn('Rain',second['source_quote'])
        self.assertIn('Wind',third['source_quote'])
        self.assertFalse(any(d['verified'] for d in details))
        self.assertEqual({r['location'] for r in first['source_units']},{'PDF page 12','PDF page 13'})
        count = self.provider.calls
        self.service.refine(self.conn,self.target['id'])
        self.assertEqual(count,self.provider.calls)

    def test_confirmed_span_survives_read_and_cancel_without_confirming_neighbors(self):
        self.service.refine(self.conn,self.target['id'])
        detail = file_detail(self.conn,self.target['id'],MODEL)
        confirm_pair(self.conn,self.target['id'],detail['source_id'],segments=detail['source_segments'])
        verified = file_detail(self.conn,self.target['id'],MODEL)
        self.assertTrue(verified['verified'])
        self.assertEqual(verified['source_quote'],detail['source_quote'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM file_reviews').fetchone()[0],1)
        confirm_pair(self.conn,self.target['id'],detail['source_id'],cancel=True)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM passage_reviews').fetchone()[0],0)
        self.assertFalse(file_detail(self.conn,self.target['id'],MODEL)['verified'])

    def test_stale_cache_and_cross_book_or_invalid_offsets_are_rejected(self):
        self.service.refine(self.conn,self.target['id'])
        detail = file_detail(self.conn,self.target['id'],MODEL)
        bad = [dict(detail['source_segments'][0],start=-1)]
        with self.assertRaises(ValueError):
            validate_segments(self.conn,self.target['id'],bad)
        other = add_file_book(self.conn,self.root,'Other','o.txt',b'Other source sentence.','t.txt','其他书中的译文。'.encode())
        foreign = self.conn.execute('SELECT id FROM units WHERE document_id=?',(other['id']+':source',)).fetchone()[0]
        with self.assertRaises(ValueError):
            validate_segments(self.conn,self.target['id'],[dict(unit_id=foreign,start=0,end=5)])
        with self.conn:
            self.conn.execute("UPDATE documents SET sha256='changed' WHERE id=?",(self.book['id']+':source',))
        self.assertIsNone(cached(self.conn,self.target['id']))

    def test_failed_fragment_batch_retains_completed_vectors_and_cools_down(self):
        class Broken(SemanticFixture):
            def embed(self,texts):
                if self.calls:
                    raise ValueError('Synthetic quota limit')
                return super().embed(texts)
        broken = Broken()
        with self.assertRaises(ValueError):
            fragment_vectors(self.conn,self.book['id'],[f'Synthetic sentence {i}' for i in range(30)],broken)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM alignment_vectors').fetchone()[0],24)
        class Unavailable:
            def embed(self,texts):
                raise ValueError('Synthetic unavailable')
        service=AIService(self.db,FakeSettings(),Unavailable())
        with self.assertRaises(ValueError):
            service.refine(self.conn,self.target['id'])
        self.assertEqual(cached(self.conn,self.target['id'])['state'],'unavailable')
        self.assertEqual(service.refine(self.conn,self.target['id'])['segments'],[])

    def test_unicode_normalization_keeps_raw_character_offsets(self):
        raw='A ﬁne 😀 day.'
        text,offsets=canonical_cluster([dict(id='example',text=raw,format='epub')])
        start=text.index('😀')
        segment=segments_from_offsets(offsets[start:])[0]
        self.assertEqual(raw[segment['start']:segment['end']],'😀 day.')

    def test_weak_cross_language_match_does_not_create_a_highlight(self):
        class Unrelated:
            def embed(self,texts):
                return [[0,1,0,0,0,0,0,0] if re.search('[\u3400-\u9fff]',t) else [1,0,0,0,0,0,0,0] for t in texts]
        service=AIService(self.db,FakeSettings(),Unrelated())
        service.refine(self.conn,self.target['id'])
        detail=file_detail(self.conn,self.target['id'],MODEL)
        self.assertEqual(detail['range_state'],'uncertain')
        self.assertEqual(detail['source_segments'],[])
        self.assertFalse(detail['verified'])


if __name__=='__main__':
    unittest.main()
