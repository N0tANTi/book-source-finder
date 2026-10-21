import json
import tempfile
import unittest
from pathlib import Path

from source_finder.core import (connect, detail, export_alignments, import_book,
                                library, normalize, save_alignment, search, source_pages)


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conn = connect(self.root / 'test.sqlite3')
        self.original = (
            '--- PDF page 8; printed page 1 ---\n'
            'Rain falls across the quiet garden. The windows remain open.\n'
            '--- PDF page 9; printed page 2 ---\n'
            'The morning brings a clear sky. Nobody remembers the rain.\n'
            '--- PDF page 10; printed page 3 ---\n'
            'A final page with a different story.\n')
        self.translation = (
            '# 第一章\n\n<!-- 原书第1页 -->\n\n'
            '雨落在安静的花园里。窗户依然敞开着。\n\n'
            '这是一段关于雨天和花园的补充说明，足够长以便测试跨段落复制查找时的段落边界。\n\n'
            '<!-- 原书第2页 -->\n\n清晨带来了晴朗的天空。没有人记得那场雨。\n\n'
            '<!-- 原书第3页 -->\n\n最后一页讲述了一个不同的故事。\n')
        (self.root / 'original.txt').write_text(self.original, encoding='utf-8')
        (self.root / 'translation.md').write_text(self.translation, encoding='utf-8')
        self.spec = dict(id='sample', title='测试书', language='英文', chapters=[
            dict(id='one', title='第一章', source='original.txt', translation='translation.md')])
        import_book(self.conn, self.spec, self.root)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def first(self):
        return search(self.conn, '雨落在安静的花园里')[0]

    def test_exact_normalizes_punctuation_spacing_and_width(self):
        results = search(self.conn, '雨 落在，安静的花园里！')
        self.assertEqual(results[0]['match'], 'exact')
        self.assertEqual(normalize('ＡＢＣ１２３'), 'abc123')

    def test_multi_paragraph_copy_and_page_context(self):
        query = '这是一段关于雨天和花园的补充说明，足够长以便测试跨段落复制查找时的段落边界。清晨带来了晴朗的天空。'
        self.assertEqual(search(self.conn, query)[0]['match'], 'across')
        passage = detail(self.conn, self.first()['id'])
        self.assertEqual([p['label'] for p in passage['source_pages']], ['1', '2', '3'])
        self.assertIsNone(passage['alignment'])
        self.assertEqual(len(passage['reader_paragraphs']), 4)
        self.assertEqual(len(passage['reader_pages']), 3)

    def test_filters_no_match_and_short_query(self):
        self.assertEqual(search(self.conn, '雨落在安静的花园里', book_id='other'), [])
        self.assertEqual(search(self.conn, '量子场论黑洞和相对论'), [])
        with self.assertRaises(ValueError):
            search(self.conn, '雨')

    def test_lexical_near_match_is_labeled(self):
        results = search(self.conn, '雨落在宁静的花园里')
        self.assertEqual(results[0]['match'], 'similar')

    def test_review_exact_provenance_and_cross_page(self):
        pid = self.first()['id']
        pages = detail(self.conn, pid)['source_pages']
        save_alignment(self.conn, pid, [pages[0]['id']], 'Rain falls across the quiet garden.')
        self.assertEqual(detail(self.conn, pid)['alignment']['quote'], 'Rain falls across the quiet garden.')
        self.assertEqual(library(self.conn)['books'][0]['verified_count'], 1)
        save_alignment(self.conn, pid, [pages[0]['id'], pages[1]['id']],
                       'The windows remain open. The morning brings a clear sky.')
        self.assertEqual(len(detail(self.conn, pid)['alignment']['pages']), 2)
        with self.assertRaises(ValueError):
            save_alignment(self.conn, pid, [pages[0]['id']], 'This invented quote is not in the original.')
        with self.assertRaises(ValueError):
            save_alignment(self.conn, pid, [pages[0]['id'], pages[2]['id']], 'Rain falls across the quiet garden.')
        self.assertEqual(len(export_alignments(self.conn)['alignments']), 1)

    def test_reimport_preserves_then_invalidates_reviews(self):
        pid = self.first()['id']
        page = detail(self.conn, pid)['source_pages'][0]
        save_alignment(self.conn, pid, [page['id']], 'Rain falls across the quiet garden.')
        result = import_book(self.conn, self.spec, self.root)
        self.assertEqual(result['changed_chapters'], 0)
        self.assertIsNotNone(detail(self.conn, pid)['alignment'])
        (self.root / 'original.txt').write_text(self.original.replace('Rain falls', 'Rain drifts'), encoding='utf-8')
        result = import_book(self.conn, self.spec, self.root)
        self.assertEqual(result['changed_chapters'], 1)
        self.assertIsNone(detail(self.conn, pid)['alignment'])

    def test_bad_import_is_atomic(self):
        broken = dict(self.spec, title='不应保存的标题', chapters=self.spec['chapters'] + [
            dict(id='two', title='缺少文件', source='missing.txt', translation='translation.md')])
        with self.assertRaises(OSError):
            import_book(self.conn, broken, self.root)
        self.assertEqual(library(self.conn)['books'][0]['title'], '测试书')
        (self.root / 'translation.md').write_text(self.translation.replace('原书第1页', '原书第99页'), encoding='utf-8')
        with self.assertRaises(ValueError):
            import_book(self.conn, self.spec, self.root)
        self.assertEqual(len(search(self.conn, '雨落在安静的花园里')), 1)

    def test_front_matter_mapping_and_raw_text(self):
        pages = source_pages('--- PDF page 19; printed page front matter ---\nSome\ntext.\n'
                             '--- PDF page 20; printed page front matter ---\nNext page.', 17)
        self.assertEqual([p['label'] for p in pages], ['xvii', 'xviii'])
        self.assertEqual(pages[0]['text'], 'Some text.')
        self.assertIn('\n', pages[0]['raw_text'])
        with self.assertRaises(ValueError):
            source_pages('--- PDF page 19; printed page front matter ---\nSome text.')

    def test_known_header_cleanup_keeps_raw_extraction(self):
        pages = source_pages('--- PDF page 8; printed page 1 ---\nA BOOK\nA sentence.\n1', page_headers=['A BOOK'])
        self.assertEqual(pages[0]['text'], 'A sentence.')
        self.assertEqual(pages[0]['raw_text'], 'A BOOK\nA sentence.\n1')


if __name__ == '__main__':
    unittest.main()
