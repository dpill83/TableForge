"""Build identity must distinguish a running process from replaced files."""
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import build_info
import server


class BuildInfoTest(unittest.TestCase):
    def test_changes_and_cross_platform_line_endings(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(build_info, 'ROOT', Path(folder)):
            root = Path(folder)
            (root / 'web').mkdir()
            (root / 'prompts').mkdir()
            code = root / 'server.py'
            code.write_bytes(b'original\r\n')
            page = root / 'web' / 'index.html'
            page.write_bytes(b'page\n')
            running = build_info.server_build()
            code.write_bytes(b'original\n')
            self.assertEqual(running, build_info.server_build())
            with patch.object(build_info, 'RUNNING_SERVER_BUILD', running):
                before = build_info.status()
                self.assertFalse(before['restartRequired'])
                (root / '.env').write_text('private config')
                self.assertEqual(before, build_info.status())
                code.write_text('updated code')
                after = build_info.status()
                self.assertTrue(after['restartRequired'])
                self.assertEqual(after['serverBuild'], running)
                self.assertNotEqual(after['installedServerBuild'], running)
                self.assertEqual(after['uiBuild'], before['uiBuild'])
                page.write_text('updated UI')
                self.assertNotEqual(build_info.status()['uiBuild'], before['uiBuild'])

    def test_http_version_and_loaded_page_identity(self):
        http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{http.server_port}'
            with urllib.request.urlopen(base + '/api/version') as response:
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                info = json.load(response)
            self.assertEqual(info['serverBuild'], build_info.RUNNING_SERVER_BUILD)
            with urllib.request.urlopen(base + '/') as response:
                page = response.read().decode('utf-8')
            self.assertNotIn('__TABLEFORGE_UI_BUILD__', page)
            self.assertIn(f'name="tableforge-ui-build" content="{info["uiBuild"]}"', page)
        finally:
            http.shutdown()
            http.server_close()
            thread.join()
