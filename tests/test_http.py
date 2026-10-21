import functools
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from source_finder.__main__ import Handler
from source_finder.core import connect
from source_finder.ai import AIService,Settings
from test_documents import FakeProvider,epub,pdf


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'library.sqlite3'
        connect(self.db).close()
        self.settings = Settings(Path(self.temp.name))
        self.ai = AIService(self.db,self.settings,FakeProvider())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, db=self.db, token='test-token',settings=self.settings,ai=self.ai))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_ui_and_empty_library(self):
        with self.client.open(self.url) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('对照书库', response.read().decode('utf-8'))
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        with self.client.open(self.url + '/api/library') as response:
            self.assertEqual(json.load(response)['books'], [])

    def test_host_and_post_restrictions(self):
        request = urllib.request.Request(self.url + '/api/library', headers={'Host': 'untrusted.example'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.client.open(request)
        self.assertEqual(error.exception.code, 403)
        request = urllib.request.Request(self.url + '/api/align', data=b'{}', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.client.open(request)
        self.assertEqual(error.exception.code, 403)

    def test_invalid_queries_and_path_not_served(self):
        for path, expected in [('/api/search?q=x', 400), ('/../data/library.sqlite3', 404),
                               ('/api/detail?id=missing', 400)]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.client.open(self.url + path)
            self.assertEqual(error.exception.code, expected)

    def post(self,path,data):
        request=urllib.request.Request(self.url+path,data=json.dumps(data).encode(),
            headers={'Content-Type':'application/json','X-CSRF-Token':'test-token'},method='POST')
        with self.client.open(request) as response:
            return json.load(response)

    def upload(self,source_name,source,translation):
        boundary='SyntheticUploadBoundary'
        body=b''
        for name,filename,data in [('source',source_name,source),('translation','translated.epub',translation)]:
            body+=f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+data+b'\r\n'
        body+=f'--{boundary}--\r\n'.encode()
        request=urllib.request.Request(self.url+'/api/import',data=body,
            headers={'Content-Type':f'multipart/form-data; boundary={boundary}','X-CSRF-Token':'test-token'},method='POST')
        with self.client.open(request) as response:
            return json.load(response)

    def test_file_upload_read_and_mocked_model_lifecycle(self):
        book=self.upload('original.epub',epub(['Rain falls across the garden.']),epub(['雨落在花园里。'],'第一章'))
        with self.client.open(self.url+'/api/library') as response:
            listing=json.load(response)
        self.assertEqual(listing['books'][0]['kind'],'files')
        with self.client.open(self.url+'/api/open-book?book='+book['id']) as response:
            first=json.load(response)['id']
        self.assertTrue(first.startswith('unit:'))
        configured=self.post('/api/settings',{'account_id':'0'*32,'token':'synthetic-token-for-test'})
        self.assertTrue(configured['configured'])
        self.assertNotIn('synthetic-token-for-test',json.dumps(configured))
        self.assertTrue(self.post('/api/model-test',{})['ok'])
        self.post('/api/index',{'book_id':book['id'],'consent':True})
        for _ in range(100):
            with self.client.open(self.url+'/api/library') as response:
                ready=json.load(response)['books'][0]['index_ready']
            if ready:
                break
            time.sleep(.01)
        self.assertTrue(ready)
        results=self.post('/api/semantic',{'book_id':book['id'],'query':'雨天的花园','consent':True})['results']
        self.assertEqual(results[0]['match'],'semantic')
        calls=self.ai.provider.calls
        exact=self.post('/api/semantic',{'book_id':book['id'],'query':'雨落在花园里','consent':True})['results']
        self.assertEqual(exact[0]['match'],'exact')
        self.assertEqual(self.ai.provider.calls,calls)

    def test_pdf_upload_and_rejected_missing_file(self):
        result=self.upload('original.pdf',pdf('Rain falls across the quiet garden. The windows remain open.'),epub(['雨落在安静的花园里。'],'第一章'))
        self.assertTrue(result['id'])
        request=urllib.request.Request(self.url+'/api/import',data=b'{}',headers={'Content-Type':'application/json','X-CSRF-Token':'test-token'},method='POST')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.client.open(request)
        self.assertEqual(error.exception.code,400)


if __name__ == '__main__':
    unittest.main()
