"""Binary cartridge HTTP uploads, including packages over the old 32 MB cap."""
import hashlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import server


class CartridgeUploadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = patch.object(server, 'DATA', Path(self.temp.name))
        self.data.start()
        server.initialize()
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.data.stop()
        self.temp.cleanup()

    def upload(self, raw, path='/api/cartridges'):
        req = urllib.request.Request(self.base + path, data=raw,
                                     headers={'Content-Type': 'application/zip'})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_large_binary_zip_is_preserved_and_retries_are_idempotent(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('module.md', '# Large adventure')
            archive.writestr('art.bin', b'x' * (33 * 1024 * 1024))
        raw = stream.getvalue()
        cartridge = self.upload(raw)
        cartridge_id = hashlib.sha256(raw).hexdigest()
        self.assertEqual(cartridge['id'], cartridge_id)
        stored = server.DATA / 'cartridges' / (cartridge_id + '.zip')
        self.assertEqual(stored.read_bytes(), raw)
        # A retry addresses the same cartridge and never creates a save.
        self.assertEqual(self.upload(raw)['id'], cartridge_id)
        with server.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM cartridges').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM saves').fetchone()[0], 0)

    def test_binary_zip_can_relocate_a_missing_cartridge(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({
                'format': 'tableforge-adventure', 'formatVersion': 1,
                'title': 'Recovered adventure', 'resources': {}}))
            archive.writestr('module.md', '# Recovered adventure')
            archive.writestr('run-data.json', '{"title":"Recovered adventure"}')
            prompt = Path(__file__).parent / 'fixtures' / 'stage3-run-prompt-v2.1.1.md'
            archive.writestr(prompt.name, prompt.read_bytes())
        raw = stream.getvalue()
        cartridge = self.upload(raw)
        req = urllib.request.Request(self.base + '/api/saves',
            data=json.dumps({'cartridgeId': cartridge['id'], 'players': [
                {'name': 'Player', 'character': 'Hero'}]}).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            save = json.load(response)
        stored = server.DATA / 'cartridges' / (cartridge['id'] + '.zip')
        stored.unlink()
        recovered = self.upload(raw, f'/api/saves/{save["save"]["id"]}/locate-cartridge')
        self.assertTrue(recovered['cartridge']['available'])
        self.assertEqual(stored.read_bytes(), raw)

    def test_binary_upload_rejects_wrong_route_and_oversized_body(self):
        for path, limit, expected in [('/api/saves', 100, 'only supported'),
                                      ('/api/cartridges', 4, '90 MB')]:
            with self.subTest(path=path), patch.object(server, 'MAX_CARTRIDGE_BYTES', limit):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.upload(b'not a zip', path)
                self.assertEqual(caught.exception.code, 400)
                self.assertIn(expected, json.load(caught.exception)['error'])

    def test_expansion_limit_remains_enforced(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('large.txt', b'x' * 1024)
        with patch.object(server, 'MAX_UNPACKED_CARTRIDGE_BYTES', 512):
            with self.assertRaisesRegex(ValueError, 'Unpacked cartridge is too large'):
                server.read_archive(stream.getvalue())
