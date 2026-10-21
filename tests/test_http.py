import functools
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from source_finder.__main__ import Handler
from source_finder.core import connect


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'library.sqlite3'
        connect(self.db).close()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, db=self.db, token='test-token'))
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
            self.assertIn('原文查找', response.read().decode('utf-8'))
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


if __name__ == '__main__':
    unittest.main()
