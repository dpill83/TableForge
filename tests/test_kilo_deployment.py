"""Linux deployment failure-path tests; no real sudo, systemd, or production IO."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if sys.platform == 'win32':
    raise unittest.SkipTest('KILO deployment uses Linux flock and systemd')

spec = importlib.util.spec_from_file_location('kilo_deploy',
    Path(__file__).resolve().parents[1] / 'deploy/kilo/deploy.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)
OLD = '1' * 40
NEW = '2' * 40


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base, self.state = root / 'app', root / 'state'
        self.repo = self.base / 'repo'
        self.repo.mkdir(parents=True)
        self.state.mkdir()
        self.old_venv = self.base / 'venvs' / OLD
        self.new_venv = self.base / 'venvs' / NEW
        for venv in (self.old_venv, self.new_venv):
            (venv / 'bin').mkdir(parents=True)
            (venv / 'bin/python').touch()
        (self.base / 'venv').symlink_to(self.old_venv, target_is_directory=True)
        self.old = {'commit': OLD, 'venv': str(self.old_venv)}
        self.write_state(self.old, None)
        self.resets = []
        self.files = ['server.py', '.env.example', 'web/index.html']
        self.branch = 'main'
        self.dirty = ''
        self.patches = [patch.object(deployment, 'BASE', self.base),
                        patch.object(deployment, 'REPO', self.repo),
                        patch.object(deployment, 'STATE', self.state),
                        patch.object(deployment, 'git', side_effect=self.git),
                        patch.object(deployment, 'prepare', return_value=self.new_venv),
                        patch.object(deployment, 'restart_and_check')]
        self.mocks = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.prepare, self.restart = self.mocks[-2:]

    def write_state(self, current, previous):
        (self.state / 'deployment.json').write_text(json.dumps({'current': current, 'previous': previous}))

    def git(self, *args):
        if args[:2] == ('remote', 'get-url'):
            return deployment.URL
        if args[0] == 'branch':
            return self.branch
        if args[0] == 'status':
            return self.dirty
        if args[0] == 'rev-parse':
            return OLD if args[1] == 'HEAD' else NEW
        if args[0] == 'ls-tree':
            return '\n'.join(self.files)
        if args[0] == 'reset':
            self.resets.append(args[-1])
        return ''

    def test_success_records_previous_commit_and_venv(self):
        deployment.execute('deploy', NEW)
        saved = json.loads((self.state / 'deployment.json').read_text())
        self.assertEqual(saved['previous'], self.old)
        self.assertEqual(saved['current']['commit'], NEW)
        self.assertEqual((self.base / 'venv').resolve(), self.new_venv)
        self.assertEqual(self.resets, [NEW])
        self.assertFalse((self.state / 'pending.json').exists())

    def test_failed_restart_restores_code_and_venv_and_still_fails(self):
        data = Path(self.temp.name) / 'persistent'
        data.mkdir()
        sentinel = data / 'tableforge.sqlite3'
        sentinel.write_bytes(b'untouched-save-data')
        self.restart.side_effect = [RuntimeError('HTTP unavailable'), None]
        with self.assertRaisesRegex(RuntimeError, 'HTTP unavailable'):
            deployment.execute('deploy', NEW)
        self.assertEqual(self.resets, [NEW, OLD])
        self.assertEqual((self.base / 'venv').resolve(), self.old_venv)
        self.assertEqual(json.loads((self.state / 'deployment.json').read_text())['current'], self.old)
        self.assertEqual(sentinel.read_bytes(), b'untouched-save-data')
        self.assertFalse((self.state / 'pending.json').exists())

    def test_failed_candidate_tests_leave_live_checkout_untouched(self):
        self.prepare.side_effect = RuntimeError('tests failed')
        with self.assertRaisesRegex(RuntimeError, 'tests failed'):
            deployment.execute('deploy', NEW)
        self.assertEqual(self.resets, [])
        self.restart.assert_not_called()

    def test_refuses_feature_branch(self):
        self.branch = 'feature/example'
        with self.assertRaisesRegex(RuntimeError, 'must be main'):
            deployment.execute('deploy', NEW)
        self.prepare.assert_not_called()

    def test_refuses_local_changes(self):
        self.dirty = ' M server.py'
        with self.assertRaisesRegex(RuntimeError, 'local changes'):
            deployment.execute('deploy', NEW)
        self.assertEqual(self.resets, [])

    def test_refuses_git_tracked_data_and_config(self):
        for path in ['data/tableforge.sqlite3', '.env', '.env.production']:
            with self.subTest(path=path):
                self.files = ['server.py', path]
                with self.assertRaisesRegex(RuntimeError, 'persistent data or local config'):
                    deployment.execute('deploy', NEW)
        self.prepare.assert_not_called()

    def test_refuses_local_repo_data_even_when_ignored(self):
        (self.repo / 'data').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'Unexpected local data'):
            deployment.execute('deploy', NEW)

    def test_interrupted_deployment_requires_inspection(self):
        (self.state / 'pending.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'interrupted deployment'):
            deployment.execute('deploy', NEW)
        self.prepare.assert_not_called()

    def test_no_previous_deployment_is_a_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, 'No previous successful'):
            deployment.execute('rollback')
        self.assertEqual(self.resets, [])

    def test_rollback_reuses_saved_previous_venv(self):
        previous = {'commit': NEW, 'venv': str(self.new_venv)}
        self.write_state(self.old, previous)
        deployment.execute('rollback')
        self.prepare.assert_not_called()
        self.assertEqual(self.resets, [NEW])
        saved = json.loads((self.state / 'deployment.json').read_text())
        self.assertEqual(saved['current'], previous)
        self.assertEqual(saved['previous'], self.old)

    def test_failed_recovery_retains_pending_record(self):
        self.restart.side_effect = [RuntimeError('candidate failed'), RuntimeError('recovery failed')]
        with self.assertRaisesRegex(RuntimeError, 'recovery failed'):
            deployment.execute('deploy', NEW)
        self.assertTrue((self.state / 'pending.json').exists())


if __name__ == '__main__':
    unittest.main()
