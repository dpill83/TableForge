import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from local_config import load_env
import ai


class LocalConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '.env'
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_file_loads_literal_values_quotes_comments_and_windows_paths(self):
        self.path.write_text('\ufeff# Local settings\n\nTABLEFORGE_OPENAI_API_KEY=test-key=abc#123\n'
                             'TABLEFORGE_AIDM_MODEL="test-model" # a comment\n'
                             "export TABLEFORGE_IMAGE_MODEL='image-model'\n"
                             'TABLEFORGE_DATA=C:\\Games\\Table Forge # keep the path\n', encoding='utf-8')
        load_env(self.path)
        self.assertEqual(os.environ['TABLEFORGE_OPENAI_API_KEY'], 'test-key=abc#123')
        self.assertEqual(os.environ['TABLEFORGE_AIDM_MODEL'], 'test-model')
        self.assertEqual(os.environ['TABLEFORGE_IMAGE_MODEL'], 'image-model')
        self.assertEqual(os.environ['TABLEFORGE_DATA'], 'C:\\Games\\Table Forge')

    def test_terminal_values_including_empty_override_file(self):
        self.path.write_text('TABLEFORGE_AIDM_MODEL=file-model\nTABLEFORGE_OPENAI_API_KEY=file-key\n', encoding='utf-8')
        os.environ['TABLEFORGE_AIDM_MODEL'] = 'terminal-model'
        os.environ['TABLEFORGE_OPENAI_API_KEY'] = ''
        load_env(self.path)
        self.assertEqual(os.environ['TABLEFORGE_AIDM_MODEL'], 'terminal-model')
        self.assertEqual(os.environ['TABLEFORGE_OPENAI_API_KEY'], '')

    def test_missing_file_is_optional(self):
        load_env(self.path)
        self.assertEqual(dict(os.environ), {})

    def test_aidm_model_takes_precedence_with_legacy_fallback(self):
        for new, old, expected in [('new-model', 'old-model', 'new-model'),
                                   ('', 'old-model', 'old-model'), (' ', '', 'gpt-4o-mini')]:
            with self.subTest(new=new, old=old), patch.dict(os.environ, {
                    'TABLEFORGE_OPENAI_API_KEY': 'test-key',
                    'TABLEFORGE_AIDM_MODEL': new, 'TABLEFORGE_MODEL': old}):
                self.assertEqual(ai.runtime_status()['model'], expected)
                self.assertEqual(ai.current_provider().model, expected)

    def test_server_loads_its_own_file_before_resolving_storage(self):
        app = self.path.parent / 'app'
        app.mkdir()
        root = Path(__file__).resolve().parents[1]
        for name in ('server.py', 'local_config.py', 'ai.py', 'scene_images.py', 'metering.py', 'module_context.py', 'backups.py', 'runtime_prompts.py'):
            shutil.copyfile(root / name, app / name)
        data = self.path.parent / 'custom data'
        (app / '.env').write_text(f'TABLEFORGE_OPENAI_API_KEY=local-test-key\nTABLEFORGE_DATA={data}\n', encoding='utf-8')
        script = ('import sys; sys.path.insert(0, sys.argv[1]); import server; '
                  'assert server.DATA == server.Path(sys.argv[2]); '
                  'assert server.ai.runtime_status()["provider"] == "openai"; '
                  'assert server.scene_images.settings()["enabled"] is True')
        completed = subprocess.run([sys.executable, '-c', script, str(app), str(data)],
                                   cwd=self.path.parent, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_invalid_line_never_prints_secret_or_partially_applies_settings(self):
        for invalid in ['secret-token-without-equals', 'KEY="secret-token', 'KEY="secret-token" trailing',
                        'INVALID KEY=secret-token', 'KEY=secret-token\x00']:
            self.path.write_text('TABLEFORGE_AIDM_MODEL=test\n'+invalid, encoding='utf-8')
            with self.assertRaises(ValueError) as error:
                load_env(self.path)
            self.assertIn('line 2', str(error.exception))
            self.assertNotIn('secret-token', str(error.exception))
            self.assertNotIn('TABLEFORGE_AIDM_MODEL', os.environ)
