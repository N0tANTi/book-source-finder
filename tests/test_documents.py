import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from source_finder.ai import AIService, MODEL, Settings, validate_vectors
from source_finder.core import connect, library
from source_finder.documents import (add_file_book, confirm_pair, extract_document,
                                     file_books, file_detail, lexical_search, ranked_units)


def epub(paragraphs, title='Chapter one'):
    from html import escape
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="EPUB/content.opf"/></rootfiles></container>')
        archive.writestr('EPUB/content.opf', '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>')
        archive.writestr('EPUB/one.xhtml', '<html><body><h1>' + escape(title) + '</h1>' + ''.join('<p>' + escape(p) + '</p>' for p in paragraphs) + '<script>BAD_SCRIPT_CONTENT</script></body></html>')
    return output.getvalue()


def pdf(text=None):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    if text:
        font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 20 300 Td ({text}) Tj ET'.encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class FakeSettings:
    def credentials(self):
        return '0'*32, 'synthetic-token'


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        def vector(text):
            if 'rain' in text.casefold() or '雨' in text:
                return [1,0,0,0,0,0,0,0]
            if 'sky' in text.casefold() or '晴' in text:
                return [0,1,0,0,0,0,0,0]
            return [0,0,1,0,0,0,0,0]
        return [vector(text) for text in texts]


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'library.sqlite3'
        self.conn = connect(self.db)
        self.source = epub(['Rain falls across the quiet garden.', 'The morning brings a clear sky.'])
        self.translation = epub(['雨落在安静的花园里。', '清晨带来了晴朗的天空。'], '第一章')

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def add(self):
        return add_file_book(self.conn,self.root,'测试书','original.epub',self.source,'译文.epub',self.translation)

    def test_epub_import_retains_files_and_can_search_without_page_markers(self):
        book = self.add()
        books = file_books(self.conn, MODEL)
        self.assertEqual(books[0]['title'], '测试书')
        self.assertFalse(books[0]['index_ready'])
        self.assertEqual(library(self.conn)['books'], [])
        self.assertNotIn('BAD_SCRIPT_CONTENT', str(extract_document('source.epub',self.source)))
        self.assertEqual((self.root/'books'/book['id']/'source.epub').read_bytes(), self.source)
        result = lexical_search(self.conn,'雨',book['id'])
        self.assertEqual(result[0]['match'], 'exact')
        detail = file_detail(self.conn,result[0]['id'],MODEL)
        self.assertFalse(detail['candidate'])
        self.assertEqual(len(detail['translation_units']),3)
        again = self.add()
        self.assertTrue(again['existing'])
        self.assertEqual(again['id'],book['id'])

    def test_invalid_pair_never_adds_half_a_book(self):
        with self.assertRaises(ValueError):
            add_file_book(self.conn,self.root,'bad','a.epub',self.source,'b.epub',b'broken')
        self.assertEqual(file_books(self.conn,MODEL),[])
        self.assertFalse((self.root/'books').exists())
        with self.assertRaises(ValueError):
            add_file_book(self.conn,self.root,'same','a.epub',self.source,'b.epub',self.source)

    def test_unindexed_source_navigation_does_not_claim_alignment(self):
        book = add_file_book(self.conn, self.root, 'Two chapters', 'source.md',
            b'# Start\n\nThe first chapter.\n\n# Ending\n\nThe final chapter.',
            'translation.epub', self.translation)
        target = lexical_search(self.conn, '雨落', book['id'])[0]
        first = file_detail(self.conn, target['id'], MODEL)
        self.assertEqual(len(first['source_sections']), 2)
        last = file_detail(self.conn, target['id'], MODEL, first['source_sections'][1]['id'])
        self.assertEqual(last['source_section'], 'Ending')
        self.assertIn('final chapter', last['source_units'][0]['text'])
        self.assertFalse(last['candidate'])
        self.assertFalse(last['verified'])
        self.assertEqual(last['translation_units'], first['translation_units'])

    def test_pdf_epub_pair_and_scanned_pdf(self):
        text = 'Rain falls across the quiet garden. The windows remain open.'
        book = add_file_book(self.conn,self.root,'PDF test','source.pdf',pdf(text),'译文.epub',self.translation)
        units = self.conn.execute('SELECT location,text FROM units WHERE document_id=?',(book['id']+':source',)).fetchall()
        self.assertEqual(units[0]['location'],'PDF 第 1 页')
        self.assertIn('quiet garden',units[0]['text'])
        with self.assertRaisesRegex(ValueError,'OCR'):
            extract_document('scan.pdf',pdf())

    def test_mocked_index_cross_language_lookup_and_confirm(self):
        book = self.add()
        provider = FakeProvider()
        service = AIService(self.db,FakeSettings(),provider)
        with self.conn:
            self.conn.execute("INSERT INTO index_jobs VALUES(?,'running',0,6,'')",(book['id'],))
        service._run(book['id'])
        self.assertTrue(file_books(self.conn,MODEL)[0]['index_ready'])
        target = lexical_search(self.conn,'雨落',book['id'])[0]
        detail = file_detail(self.conn,target['id'],MODEL)
        self.assertTrue(detail['candidate'])
        self.assertFalse(detail['verified'])
        self.assertIn('Rain',next(u['text'] for u in detail['source_units'] if u['id']==detail['source_id']))
        confirm_pair(self.conn,target['id'],detail['source_id'])
        self.assertTrue(file_detail(self.conn,target['id'],MODEL)['verified'])
        before = provider.calls
        vector = service.query(self.conn,'雨天的花园')
        service.query(self.conn,'雨天的花园')
        self.assertEqual(provider.calls,before+1)
        self.assertIn('雨',ranked_units(self.conn,vector,MODEL,book['id'],'translation')[0]['text'])
        service._run(book['id'])
        self.assertEqual(provider.calls,before+1)

    def test_failed_index_retains_completed_batches(self):
        book = self.add()
        class BrokenProvider:
            def embed(self,texts):
                raise ValueError('Synthetic quota limit')
        service = AIService(self.db,FakeSettings(),BrokenProvider())
        with self.conn:
            self.conn.execute("INSERT INTO index_jobs VALUES(?,'running',0,6,'')",(book['id'],))
        service._run(book['id'])
        self.assertEqual(file_books(self.conn,MODEL)[0]['job']['status'],'paused')
        self.assertFalse(file_books(self.conn,MODEL)[0]['index_ready'])

    def test_confirm_rejects_different_books(self):
        first = self.add()
        second = add_file_book(self.conn,self.root,'second','s.txt',b'Other original words.','t.txt','其他书的译文。'.encode())
        translation = lexical_search(self.conn,'雨',first['id'])[0]['id']
        source = self.conn.execute('SELECT id FROM units WHERE document_id=?',(second['id']+':source',)).fetchone()[0]
        with self.assertRaises(ValueError):
            confirm_pair(self.conn,translation,source)

    def test_response_validation_and_local_vault(self):
        with self.assertRaises(ValueError):
            validate_vectors({'data':[{'index':0,'embedding':[float('nan')]*8}]},1)
        self.assertEqual(validate_vectors({'data':[{'index':0,'embedding':[1]*8}]},1),[[1]*8])
        settings = Settings(self.root)
        token = 'synthetic-token-for-unit-testing'
        with patch.dict(os.environ,{'CLOUDFLARE_ACCOUNT_ID':'','CLOUDFLARE_API_TOKEN':''}):
            settings.save('0'*32,token)
            self.assertTrue(settings.status()['configured'])
            self.assertNotIn(token,json.dumps(settings.status()))
            if os.name == 'nt':
                self.assertNotIn(token,settings.path.read_text())
                self.assertEqual(Settings(self.root).credentials()[1],token)


if __name__ == '__main__':
    unittest.main()
