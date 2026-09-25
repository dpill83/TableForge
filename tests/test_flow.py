"""Exercise cartridge → save → messages → Ready → AI → reload over HTTP."""
import base64
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import ai
import server


class FakeProvider:
    def __init__(self, text='Narrated from the well.'):
        self.context = None
        self.text = text

    def generate(self, context):
        self.context = context
        return self.text


class BoomProvider:
    def generate(self, context):
        raise ValueError('provider down')


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.old_data = server.DATA
        server.DATA = self.path
        server.GENERATING.clear()
        server.initialize()
        self.env = patch.dict(os.environ, {'TABLEFORGE_OPENAI_API_KEY': '', 'TABLEFORGE_MODEL': ''})
        self.env.start()
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.env.stop()
        server.GENERATING.clear()
        server.DATA = self.old_data
        self.temp.cleanup()

    def api(self, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def api_error(self, path, payload=None):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.api(path, payload)
        return json.loads(caught.exception.read().decode())

    def ready_save(self, module='# Test adventure'):
        with io.BytesIO() as file:
            with zipfile.ZipFile(file, 'w') as archive:
                archive.writestr('module.md', module)
                archive.writestr('run-data.json', '{"title":"Hollow Well"}')
            cartridge = self.api('/api/cartridges', {'kind':'zip','data':base64.b64encode(file.getvalue()).decode()})
        save = self.api('/api/saves', {'cartridgeId':cartridge['id'],'name':'Our game','players':[
            {'name':'Dan','character':'George'}, {'name':'Dani','character':'Ethereal'}]})
        save_id = save['save']['id']
        first, second = [p['id'] for p in save['players']]
        self.api(f'/api/saves/{save_id}/messages', {'playerId':first,'text':'I look ahead.'})
        self.api(f'/api/saves/{save_id}/ready', {'playerId':first,'ready':True})
        self.api(f'/api/saves/{save_id}/ready', {'playerId':second,'ready':True})
        return save_id

    def cartridge_zip(self, entries):
        with io.BytesIO() as file:
            with zipfile.ZipFile(file, 'w') as archive:
                for name, content in entries.items():
                    archive.writestr(name, content)
            return self.api('/api/cartridges', {'kind': 'zip', 'data': base64.b64encode(file.getvalue()).decode()})

    def test_playthrough_and_reload(self):
        with io.BytesIO() as file:
            with zipfile.ZipFile(file, 'w') as archive:
                archive.writestr('module.md', '# Test adventure')
                archive.writestr('run-data.json', '{"title":"Hollow Well"}')
            cartridge = self.api('/api/cartridges', {'kind':'zip','data':base64.b64encode(file.getvalue()).decode()})
        self.assertEqual(cartridge['missing'], [])
        self.assertEqual(cartridge['title'], 'Hollow Well')
        save = self.api('/api/saves', {'cartridgeId':cartridge['id'],'name':'Our game','players':[
            {'name':'Dan','character':'George'}, {'name':'Dani','character':'Ethereal'}]})
        save_id = save['save']['id']
        first,second = [p['id'] for p in save['players']]
        self.api(f'/api/saves/{save_id}/messages', {'playerId':first,'text':'I look ahead.'})
        self.api(f'/api/saves/{save_id}/ready', {'playerId':first,'ready':True})
        with self.assertRaises(urllib.error.HTTPError):
            self.api(f'/api/saves/{save_id}/advance', {})
        self.api(f'/api/saves/{save_id}/ready', {'playerId':second,'ready':True})
        self.api(f'/api/saves/{save_id}/advance', {})
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual([m['kind'] for m in restored['messages']], ['player','ai'])
        self.assertTrue(all(not p['ready'] for p in restored['players']))
        self.assertEqual(restored['save']['beat'],2)
        self.assertEqual(self.api('/api/saves')['saves'][0]['id'],save_id)
        self.assertTrue((self.path/'cartridges'/(cartridge['id']+'.zip')).exists())
        self.assertIn('Mock AI-DM, beat 1', restored['messages'][-1]['body'])

    def test_missing_required_file_blocks_save(self):
        cartridge=self.api('/api/cartridges', {'kind':'files','files':[
            {'name':'module.md','data':base64.b64encode(b'# A').decode()}]})
        self.assertEqual(cartridge['missing'], ['run-data.json'])
        # Server must independently refuse an incomplete cartridge.
        with self.assertRaises(urllib.error.HTTPError):
            self.api('/api/saves', {'cartridgeId':cartridge['id'],'players':[{'name':'A','character':'B'}]})

    def test_demo_cartridge_files(self):
        module = '# Dress Rehearsal at Hollow Well\n\nExample cartridge for testing the TableForge interface.'
        run = json.dumps({'title': 'Dress Rehearsal at Hollow Well', 'sample': True})
        cartridge = self.api('/api/cartridges', {'kind': 'files', 'files': [
            {'name': 'module.md', 'data': base64.b64encode(module.encode()).decode()},
            {'name': 'run-data.json', 'data': base64.b64encode(run.encode()).decode()},
        ]})
        self.assertEqual(cartridge['missing'], [])
        self.assertEqual(cartridge['title'], 'Dress Rehearsal at Hollow Well')
        save = self.api('/api/saves', {'cartridgeId': cartridge['id'], 'name': 'Demo', 'players': [
            {'name': 'Dan', 'character': 'George'}]})
        self.api(f"/api/saves/{save['save']['id']}/ready", {'playerId': save['players'][0]['id'], 'ready': True})
        result = self.api(f"/api/saves/{save['save']['id']}/advance", {})
        self.assertEqual(result['messages'][-1]['kind'], 'ai')
        self.assertIn('# Dress Rehearsal at Hollow Well', ai.build_context(result, self.path)['module'])

    def test_runtime_reports_mock(self):
        self.assertEqual(self.api('/api/runtime'), {'provider': 'mock', 'model': 'local mock runtime'})

    def test_messages_while_ready_stay_in_current_beat(self):
        save_id = self.ready_save()
        state = self.api(f'/api/saves/{save_id}')
        first = state['players'][0]['id']
        posted = self.api(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': 'I also check the door.'})
        self.assertTrue(posted['players'][0]['ready'])
        self.assertEqual([m['body'] for m in posted['messages']], ['I look ahead.', 'I also check the door.'])

        error = self.api_error(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': '   '})
        self.assertIn('Message must contain', error['error'])
        restored = self.api(f'/api/saves/{save_id}')
        self.assertTrue(restored['players'][0]['ready'])
        self.assertEqual(len(restored['messages']), 2)

        advanced = self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertTrue(all(not player['ready'] for player in advanced['players']))
        self.assertEqual(advanced['save']['beat'], 2)
        self.assertEqual([m['kind'] for m in advanced['messages']], ['player', 'player', 'ai'])

    def test_advance_uses_provider_context(self):
        fake = FakeProvider()
        save_id = self.ready_save('# Test adventure')
        with patch.object(ai, 'current_provider', return_value=fake):
            result = self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertEqual(result['messages'][-1]['body'], 'Narrated from the well.')
        self.assertEqual(result['save']['beat'], 2)
        self.assertIn('# Test adventure', fake.context['module'])
        self.assertTrue(any(m['body'] == 'I look ahead.' for m in fake.context['messages']))

    def test_provider_error_leaves_beat_and_ready(self):
        save_id = self.ready_save()
        with patch.object(ai, 'current_provider', return_value=BoomProvider()):
            error = self.api_error(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertIn('provider down', error['error'])
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['save']['beat'], 1)
        self.assertTrue(all(p['ready'] for p in restored['players']))
        self.assertEqual([m['kind'] for m in restored['messages']], ['player'])
        self.assertEqual(server.GENERATING, set())

    def test_stale_beat_is_rejected(self):
        save_id = self.ready_save()
        error = self.api_error(f'/api/saves/{save_id}/advance', {'beat': 99})
        self.assertIn('already advanced', error['error'])
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['save']['beat'], 1)
        self.assertEqual([m['kind'] for m in restored['messages']], ['player'])
        self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        error = self.api_error(f'/api/saves/{save_id}/advance', {'beat': 1, 'override': True})
        self.assertIn('already advanced', error['error'])
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['save']['beat'], 2)
        self.assertEqual([m['kind'] for m in restored['messages']].count('ai'), 1)

    def test_manifest_paths_and_saved_bindings(self):
        manifest = {'format': 'tableforge-adventure', 'formatVersion': 1,
                    'title': 'Manifest Adventure',
                    'resources': {'module': 'text/story.md', 'runData': 'data/adventure.json',
                                  'castMarkdown': 'notes/people.md'}}
        cartridge = self.cartridge_zip({
            'adventure/manifest.json': json.dumps(manifest),
            'adventure/text/story.md': '# Manifest story',
            'adventure/data/adventure.json': '{"title":"Ignored in favor of manifest"}',
            'adventure/notes/people.md': 'The cast',
        })
        self.assertEqual(cartridge['missing'], [])
        self.assertEqual(cartridge['invalid'], {})
        self.assertEqual(cartridge['resources']['module.md'], 'adventure/text/story.md')
        self.assertEqual(cartridge['resources']['cast.md'], 'adventure/notes/people.md')
        save = self.api('/api/saves', {'cartridgeId':cartridge['id'], 'resources':cartridge['resources'],
                                      'players':[{'name':'Dan','character':'George'}]})
        restored = self.api(f"/api/saves/{save['save']['id']}")
        self.assertEqual(restored['cartridge']['resources'], cartridge['resources'])
        self.assertEqual(restored['cartridge']['title'], 'Manifest Adventure')
        self.assertIn('# Manifest story', ai.build_context(restored, self.path)['module'])

    def test_manual_correction_is_per_save_and_server_validated(self):
        cartridge = self.cartridge_zip({
            'module.md': '# Original module', 'run-data.json': '{"title":"Original"}',
            'alternate.md': '# Corrected module', 'alternate.json': '{"title":"Corrected"}',
        })
        bindings = dict(cartridge['resources'])
        bindings['module.md'] = 'alternate.md'
        bindings['run-data.json'] = 'alternate.json'
        preview = self.api(f"/api/cartridges/{cartridge['id']}/validate", {'resources':bindings})
        self.assertEqual(preview['title'], 'Corrected')
        self.assertEqual(preview['invalid'], {})

        invalid = dict(bindings, **{'module.md': '../outside.md'})
        error = self.api_error('/api/saves', {'cartridgeId':cartridge['id'], 'resources':invalid,
                                              'players':[{'name':'A','character':'B'}]})
        self.assertIn('Invalid cartridge bindings', error['error'])
        self.assertEqual(self.api('/api/saves')['saves'], [])

        corrected = self.api('/api/saves', {'cartridgeId':cartridge['id'], 'resources':bindings,
                                            'players':[{'name':'A','character':'B'}]})
        original = self.api('/api/saves', {'cartridgeId':cartridge['id'], 'resources':cartridge['resources'],
                                           'players':[{'name':'C','character':'D'}]})
        corrected_state = self.api(f"/api/saves/{corrected['save']['id']}")
        original_state = self.api(f"/api/saves/{original['save']['id']}")
        self.assertEqual(corrected_state['cartridge']['title'], 'Corrected')
        self.assertEqual(original_state['cartridge']['title'], 'Original')
        self.assertIn('# Corrected module', ai.build_context(corrected_state, self.path)['module'])
        self.assertIn('# Original module', ai.build_context(original_state, self.path)['module'])

    def test_invalid_content_can_be_corrected_before_save(self):
        cartridge = self.api('/api/cartridges', {'kind':'files', 'files':[
            {'name':'Adventure/module.md', 'data':base64.b64encode(b'# Good module').decode()},
            {'name':'Adventure/run-data.json', 'data':base64.b64encode(b'{broken').decode()},
            {'name':'Adventure/good.json', 'data':base64.b64encode(b'{"title":"Good"}').decode()},
        ]})
        self.assertIn('run-data.json', cartridge['invalid'])
        error = self.api_error('/api/saves', {'cartridgeId':cartridge['id'], 'resources':cartridge['resources'],
                                              'players':[{'name':'A','character':'B'}]})
        self.assertIn('run-data.json', error['error'])
        bindings = dict(cartridge['resources'], **{'run-data.json':'Adventure/good.json'})
        preview = self.api(f"/api/cartridges/{cartridge['id']}/validate", {'resources':bindings})
        self.assertEqual(preview['title'], 'Good')
        save = self.api('/api/saves', {'cartridgeId':cartridge['id'], 'resources':bindings,
                                      'players':[{'name':'A','character':'B'}]})
        self.assertEqual(save['cartridge']['resources']['run-data.json'], 'Adventure/good.json')

    def test_bad_manifest_and_unsafe_zip_are_rejected(self):
        for manifest in ('{broken', json.dumps({'format':'tableforge-adventure','formatVersion':2,'resources':{}})):
            with self.subTest(manifest=manifest):
                with self.assertRaises(urllib.error.HTTPError):
                    self.cartridge_zip({'manifest.json':manifest, 'module.md':'# A', 'run-data.json':'{}'})
        with self.assertRaises(urllib.error.HTTPError):
            self.cartridge_zip({'../outside.md':'# A'})


class MigrationTest(unittest.TestCase):
    def test_existing_save_uses_original_bindings_after_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            old_data = server.DATA
            server.DATA = Path(directory)
            try:
                with closing(sqlite3.connect(server.DATA / 'tableforge.sqlite3')) as conn:
                    conn.executescript('''
                        CREATE TABLE cartridges (id TEXT PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL,
                            resources TEXT NOT NULL, created_at TEXT NOT NULL);
                        CREATE TABLE saves (id TEXT PRIMARY KEY, name TEXT NOT NULL, cartridge_id TEXT NOT NULL,
                            mode TEXT NOT NULL DEFAULT 'normal', beat INTEGER NOT NULL DEFAULT 1,
                            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    ''')
                    conn.execute('INSERT INTO cartridges VALUES (?,?,?,?,?)',
                                 ('old', 'Old Adventure', 'zip', json.dumps({'module.md':'module.md'}), '2026-01-01'))
                    conn.execute('INSERT INTO saves VALUES (?,?,?,?,?,?,?)',
                                 ('old-save', 'Old Save', 'old', 'normal', 1, '2026-01-01', '2026-01-01'))
                    conn.commit()
                server.initialize()
                with server.db() as conn:
                    state = server.snapshot(conn, 'old-save')
                self.assertEqual(state['cartridge']['title'], 'Old Adventure')
                self.assertEqual(state['cartridge']['resources'], {'module.md':'module.md'})
            finally:
                server.DATA = old_data


if __name__ == '__main__':
    unittest.main()
