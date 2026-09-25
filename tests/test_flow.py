"""Exercise cartridge → save → messages → Ready → AI → reload over HTTP."""
import base64
import io
import json
import os
import sqlite3
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
import zlib
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import ai
import metering
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


class MeteredProvider:
    def generate(self, context):
        return ai.GeneratedText('Narrated from the well.', model='gpt-4o-mini-2024-07-18',
                                usage={'prompt_tokens': 1000, 'completion_tokens': 200,
                                       'total_tokens': 1200,
                                       'prompt_tokens_details': {'cached_tokens': 400}})


class GateProvider:
    def __init__(self, text='slow reply'):
        self.context = None
        self.text = text
        self.started = threading.Event()
        self.release = threading.Event()

    def generate(self, context):
        self.context = context
        self.started.set()
        if not self.release.wait(timeout=5):
            raise ValueError('timed out waiting to finish generation')
        return self.text


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
                archive.writestr('manifest.json', json.dumps({'format': 'tableforge-adventure',
                    'formatVersion': 1, 'title': 'Hollow Well', 'resources': {}}))
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
                archive.writestr('manifest.json', json.dumps({'format': 'tableforge-adventure',
                    'formatVersion': 1, 'title': 'Hollow Well', 'resources': {}}))
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
            {'name':'manifest.json','data':base64.b64encode(json.dumps({'format':'tableforge-adventure','formatVersion':1,'title':'A','resources':{}}).encode()).decode()},
            {'name':'module.md','data':base64.b64encode(b'# A').decode()}]})
        self.assertEqual(cartridge['missing'], ['run-data.json'])
        # Server must independently refuse an incomplete cartridge.
        with self.assertRaises(urllib.error.HTTPError):
            self.api('/api/saves', {'cartridgeId':cartridge['id'],'players':[{'name':'A','character':'B'}]})

    def test_file_payload_with_manifest(self):
        module = '# Dress Rehearsal at Hollow Well\n\nExample cartridge for testing the TableForge interface.'
        run = json.dumps({'title': 'Dress Rehearsal at Hollow Well', 'sample': True})
        cartridge = self.api('/api/cartridges', {'kind': 'files', 'files': [
            {'name': 'manifest.json', 'data': base64.b64encode(json.dumps({'format':'tableforge-adventure',
                'formatVersion':1,'title':'Dress Rehearsal at Hollow Well','resources':{}}).encode()).decode()},
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

    def test_missing_manifest_is_visible_and_blocks_new_save(self):
        cartridge = self.cartridge_zip({'module.md': '# Adventure',
            'run-data.json': '{"adventureName":"Dress Rehearsal at Hollow Well"}'})
        self.assertEqual(cartridge['missing'], ['manifest.json'])
        self.assertIsNone(cartridge['manifest'])
        self.assertEqual(cartridge['title'], 'Dress Rehearsal at Hollow Well')
        self.assertEqual(sorted(cartridge['files']), ['module.md', 'run-data.json'])
        error = self.api_error('/api/saves', {'cartridgeId': cartridge['id'],
            'players': [{'name':'Dan', 'character':'George'}]})
        self.assertIn('manifest.json', error['error'])

    def test_runtime_reports_mock(self):
        self.assertEqual(self.api('/api/runtime'), {'provider': 'mock', 'model': 'local mock runtime'})

    def test_api_usage_persists_and_stays_with_its_session(self):
        save_id = self.ready_save()
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        with patch.object(ai, 'current_provider', return_value=MeteredProvider()):
            advanced = self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        measured = advanced['usage']['session']
        self.assertEqual((measured['inputTokens'], measured['cachedInputTokens'],
                          measured['outputTokens'], measured['totalTokens']), (1000, 400, 200, 1200))
        self.assertEqual(measured['requests'], 1)
        self.assertAlmostEqual(measured['estimatedCostUsd'],
                               (600 * 0.15 + 400 * 0.075 + 200 * 0.60) / 1_000_000)
        self.assertEqual(self.api('/api/usage')['usage']['totalTokens'], 1200)
        self.api(f'/api/saves/{save_id}/end-session', {'playerId': first})
        next_session = self.api(f'/api/saves/{save_id}/start-session', {'playerId': first})
        self.assertEqual(next_session['usage']['session']['totalTokens'], 0)
        self.assertEqual(next_session['usage']['save']['totalTokens'], 1200)
        server.initialize()
        self.assertEqual(self.api(f'/api/saves/{save_id}')['usage']['save']['totalTokens'], 1200)
        self.assertEqual(self.api('/api/usage')['usage']['requests'], 1)

    def test_pilot_question_usage_is_counted_without_advancing(self):
        save_id = self.ready_save()
        before = self.api(f'/api/saves/{save_id}')
        with patch.object(ai, 'current_provider', return_value=MeteredProvider()):
            answered = self.api(f'/api/saves/{save_id}/ask',
                                {'playerId': before['players'][0]['id'], 'text': 'What does the ogre want?'})
        self.assertEqual(answered['save']['beat'], before['save']['beat'])
        self.assertEqual([p['ready'] for p in answered['players']], [p['ready'] for p in before['players']])
        self.assertEqual(answered['usage']['save']['requests'], 1)
        with server.db() as conn:
            self.assertEqual(conn.execute('SELECT purpose FROM ai_usage WHERE save_id=?',
                                          (save_id,)).fetchone()['purpose'], 'ask')

    def test_unknown_model_keeps_tokens_without_cost_guess(self):
        model, input_tokens, cached, writes, output, total, cost, tier = metering.record(
            'unlisted-model', {'prompt_tokens': 120, 'completion_tokens': 30, 'total_tokens': 150})
        self.assertEqual((model, input_tokens, output, total), ('unlisted-model', 120, 30, 150))
        self.assertIsNone(cost)

    def test_openai_provider_reads_response_usage(self):
        response = {'model': 'gpt-6-sol', 'choices': [{'message': {'content': 'The door opens.'}}],
                    'usage': {'prompt_tokens': 50, 'completion_tokens': 20, 'total_tokens': 70}}
        with patch.object(ai.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
            result = ai.OpenAIProvider('test-key', 'gpt-6-sol').generate({
                'purpose': 'advance', 'title': 'Test', 'module': '# Test', 'messages': [], 'beat': 1})
        self.assertEqual(result, 'The door opens.')
        self.assertEqual(result.usage['total_tokens'], 70)
        self.assertEqual(result.model, 'gpt-6-sol')

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

    def test_sending_marks_player_ready_atomically(self):
        cartridge = self.cartridge_zip({'manifest.json': json.dumps({'format':'tableforge-adventure',
            'formatVersion':1,'title':'Test','resources':{}}),
            'module.md': '# Test', 'run-data.json': '{"title":"Test"}'})
        save = self.api('/api/saves', {'cartridgeId': cartridge['id'], 'players': [
            {'name': 'A', 'character': 'Alice'}, {'name': 'B', 'character': 'Bob'}]})
        save_id = save['save']['id']
        first, second = [player['id'] for player in save['players']]
        rejected = self.api_error(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': '  '})
        self.assertIn('Message must contain', rejected['error'])
        self.assertFalse(self.api(f'/api/saves/{save_id}')['players'][0]['ready'])
        sent = self.api(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': 'I open the door.'})
        self.assertEqual([bool(p['ready']) for p in sent['players']], [True, False])
        self.api(f'/api/saves/{save_id}/ready', {'playerId': first, 'ready': False})
        resent = self.api(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': 'Carefully.'})
        self.assertTrue(resent['players'][0]['ready'])
        last = self.api(f'/api/saves/{save_id}/messages', {'playerId': second, 'text': 'I follow.'})
        self.assertTrue(all(p['ready'] for p in last['players']))
        self.assertEqual(last['save']['beat'], 1)

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
        self.assertEqual(server.GENERATING, {})

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

    def test_draft_from_previous_beat_is_held_for_review(self):
        save_id = self.ready_save()
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        self.api(f'/api/saves/{save_id}/advance', {'beat': 1, 'override': True})
        request = urllib.request.Request(self.base + f'/api/saves/{save_id}/messages', headers={'Content-Type': 'application/json'},
                                         data=json.dumps({'playerId': first, 'text': 'I drafted this earlier.', 'beat': 1}).encode())
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 409)
        error = json.loads(caught.exception.read().decode())
        self.assertEqual((error['code'], error['beat']), ('stale_beat', 2))
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual([m['kind'] for m in restored['messages']], ['player', 'ai'])
        self.assertFalse(restored['players'][0]['ready'])
        kept = self.api(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': 'I drafted this earlier.', 'beat': 2})
        self.assertEqual(kept['messages'][-1]['body'], 'I drafted this earlier.')

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
            'manifest.json': json.dumps({'format':'tableforge-adventure','formatVersion':1,
                'title':'Binding Adventure','resources':{}}),
            'module.md': '# Original module', 'run-data.json': '{"title":"Original"}',
            'alternate.md': '# Corrected module', 'alternate.json': '{"title":"Corrected"}',
        })
        bindings = dict(cartridge['resources'])
        bindings['module.md'] = 'alternate.md'
        bindings['run-data.json'] = 'alternate.json'
        preview = self.api(f"/api/cartridges/{cartridge['id']}/validate", {'resources':bindings})
        self.assertEqual(preview['title'], 'Binding Adventure')
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
        self.assertEqual(corrected_state['cartridge']['title'], 'Binding Adventure')
        self.assertEqual(original_state['cartridge']['title'], 'Binding Adventure')
        self.assertIn('# Corrected module', ai.build_context(corrected_state, self.path)['module'])
        self.assertIn('# Original module', ai.build_context(original_state, self.path)['module'])

    def test_invalid_content_can_be_corrected_before_save(self):
        cartridge = self.api('/api/cartridges', {'kind':'files', 'files':[
            {'name':'Adventure/manifest.json', 'data':base64.b64encode(json.dumps({'format':'tableforge-adventure',
                'formatVersion':1,'title':'Good Adventure','resources':{}}).encode()).decode()},
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
        self.assertEqual(preview['title'], 'Good Adventure')
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

    def test_session_checkpoint_and_restart(self):
        save_id = self.ready_save()
        original = self.api(f'/api/saves/{save_id}')
        player_id = original['players'][0]['id']
        self.assertEqual(len(original['sessions']), 1)
        self.assertIsNone(original['sessions'][0]['ended_at'])
        server.initialize()  # Opening the database after a crash must keep the same session.
        self.assertEqual(len(self.api(f'/api/saves/{save_id}')['sessions']), 1)
        self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        ended = self.api(f'/api/saves/{save_id}/end-session', {'playerId': player_id, 'note': 'At the well.'})
        self.assertEqual(ended['checkpoint']['beat'], 2)
        self.assertEqual(ended['checkpoint']['note'], 'At the well.')
        self.assertEqual(ended['checkpoint']['last_message_id'], ended['messages'][-1]['id'])
        self.assertEqual(ended['sessions'][0]['ended_by'], player_id)
        self.assertTrue(ended['sessions'][0]['ended_at'])
        self.assertIn('Start the next session', self.api_error(f'/api/saves/{save_id}/messages',
            {'playerId': player_id, 'text': 'Hello'})['error'])
        self.assertTrue(self.api('/api/saves')['saves'][0]['session_ended_at'])
        server.initialize()
        self.assertEqual(len(self.api(f'/api/saves/{save_id}')['sessions']), 1)
        resumed = self.api(f'/api/saves/{save_id}/start-session', {'playerId': player_id})
        self.assertEqual([session['number'] for session in resumed['sessions']], [1, 2])
        self.assertIsNone(resumed['sessions'][-1]['ended_at'])
        self.assertFalse(any(p['ready'] for p in resumed['players']))
        self.api(f'/api/saves/{save_id}/start-session', {'playerId': player_id})
        self.assertEqual(len(self.api(f'/api/saves/{save_id}')['sessions']), 2)
        context = ai.build_context(self.api(f'/api/saves/{save_id}'), self.path)
        self.assertEqual(context['checkpoint']['note'], 'At the well.')
        self.assertIn('At the well.', ai.chat_messages(context)[0]['content'])

    def test_combat_outcome_is_append_only_and_used_by_ai(self):
        save_id = self.ready_save()
        player_id = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        combat = self.api(f'/api/saves/{save_id}/mode', {'mode': 'combat', 'playerId': player_id})
        self.assertEqual(combat['save']['mode'], 'combat')
        self.assertEqual(combat['events'][-1]['kind'], 'combat_started')
        self.assertIn('Record a combat outcome', self.api_error(f'/api/saves/{save_id}/mode',
            {'mode': 'normal'})['error'])
        self.assertIn('Combat outcome', self.api_error(f'/api/saves/{save_id}/combat-outcome',
            {'playerId': player_id, 'text': '  '})['error'])
        result = self.api(f'/api/saves/{save_id}/combat-outcome',
                          {'playerId': player_id, 'text': 'The ogre fled; nobody died.'})
        self.assertEqual(result['save']['mode'], 'normal')
        self.assertEqual(result['events'][-1]['player_id'], player_id)
        self.assertEqual(result['events'][-1]['body'], 'The ogre fled; nobody died.')
        self.assertFalse(any(p['ready'] for p in result['players']))
        context = ai.build_context(result, self.path)
        self.assertIn('The ogre fled', ai.chat_messages(context)[0]['content'])
        self.assertEqual(self.api(f'/api/saves/{save_id}')['events'][-1]['body'], result['events'][-1]['body'])

    def test_missing_cartridge_recovery_requires_exact_content(self):
        contents = {'manifest.json': json.dumps({'format':'tableforge-adventure','formatVersion':1,
            'title':'Original','resources':{}}),
            'module.md': '# Original', 'run-data.json': '{"title":"Original"}'}
        cartridge = self.cartridge_zip(contents)
        save = self.api('/api/saves', {'cartridgeId': cartridge['id'], 'players':
                                     [{'name': 'Dan', 'character': 'George'}]})
        save_id = save['save']['id']
        cartridge_path = self.path / 'cartridges' / (cartridge['id'] + '.zip')
        cartridge_path.unlink()
        self.assertFalse(self.api('/api/saves')['saves'][0]['cartridgeAvailable'])
        player_id = save['players'][0]['id']
        self.assertIn('Locate the cartridge', self.api_error(f'/api/saves/{save_id}/advance',
            {'beat': 1, 'override': True})['error'])
        self.assertIn('Locate the cartridge', self.api_error(f'/api/saves/{save_id}/start-session',
            {'playerId': player_id})['error'])
        def payload(entries):
            return {'kind': 'files', 'files': [{'name': name, 'data': base64.b64encode(value.encode()).decode()}
                                             for name, value in entries.items()]}
        self.assertIn('does not match', self.api_error(f'/api/saves/{save_id}/locate-cartridge',
            payload(dict(contents, **{'module.md': '# Changed'})))['error'])
        self.assertFalse(cartridge_path.exists())
        recovered = self.api(f'/api/saves/{save_id}/locate-cartridge', payload(contents))
        self.assertTrue(recovered['cartridge']['available'])
        self.assertTrue(cartridge_path.is_file())
        self.assertEqual(len(recovered['sessions']), 1)
        self.assertIn('# Original', ai.build_context(recovered, self.path)['module'])

    def test_ask_does_not_change_table_or_ready(self):
        save_id = self.ready_save()
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        result = self.api(f'/api/saves/{save_id}/ask', {'playerId': first, 'text': 'What would Shenka do?'})
        self.assertEqual(result['save']['beat'], 1)
        self.assertTrue(all(p['ready'] for p in result['players']))
        self.assertEqual([m['kind'] for m in result['messages']], ['player'])
        self.assertEqual([m['kind'] for m in result['pilot']], ['pilot', 'ai'])
        self.assertEqual(result['pilot'][0]['name'], 'George')
        self.assertIn('operational', result['pilot'][-1]['body'].lower())
        self.assertNotIn('Mock AI-DM, beat', result['pilot'][-1]['body'])

    def test_player_portrait_upload_persists_without_changing_play(self):
        save_id = self.ready_save()
        before = self.api(f'/api/saves/{save_id}')
        first = before['players'][0]['id']
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b''))
        path = f'/api/saves/{save_id}/players/{first}/portrait'
        uploaded = self.api(path, {'mime': 'image/png', 'data': base64.b64encode(png).decode()})
        self.assertTrue(uploaded['players'][0]['portraitUrl'].startswith(path))
        self.assertIsNone(uploaded['players'][1]['portraitUrl'])
        self.assertEqual(uploaded['save']['beat'], before['save']['beat'])
        self.assertEqual([p['ready'] for p in uploaded['players']], [p['ready'] for p in before['players']])
        self.assertEqual(uploaded['messages'], before['messages'])
        with urllib.request.urlopen(self.base + uploaded['players'][0]['portraitUrl']) as response:
            self.assertEqual(response.headers['Content-Type'], 'image/png')
            self.assertEqual(response.read(), png)
        server.initialize()
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['players'][0]['portraitUrl'], uploaded['players'][0]['portraitUrl'])
        self.assertIn('invalid', self.api_error(path, {'mime': 'image/png', 'data': base64.b64encode(b'not an image').decode()})['error'])
        removed = self.api(path, {'remove': True})
        self.assertIsNone(removed['players'][0]['portraitUrl'])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + path)
        self.assertEqual(caught.exception.code, 404)

    def test_ask_uses_provider_context(self):
        fake = FakeProvider('Shenka would likely flee north.')
        save_id = self.ready_save('# Test adventure')
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        with patch.object(ai, 'current_provider', return_value=fake):
            result = self.api(f'/api/saves/{save_id}/ask', {'playerId': first, 'text': 'Would Shenka flee?'})
        self.assertEqual(result['pilot'][-1]['body'], 'Shenka would likely flee north.')
        self.assertEqual(result['save']['beat'], 1)
        self.assertEqual(fake.context['purpose'], 'ask')
        self.assertIn('# Test adventure', fake.context['module'])
        self.assertTrue(any(m['body'] == 'I look ahead.' for m in fake.context['messages']))
        self.assertTrue(any(m['body'] == 'Would Shenka flee?' for m in fake.context['pilot']))

    def test_ask_provider_error_keeps_question(self):
        save_id = self.ready_save()
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        with patch.object(ai, 'current_provider', return_value=BoomProvider()):
            error = self.api_error(f'/api/saves/{save_id}/ask', {'playerId': first, 'text': 'Would Shenka flee?'})
        self.assertIn('provider down', error['error'])
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['save']['beat'], 1)
        self.assertTrue(all(p['ready'] for p in restored['players']))
        self.assertEqual([m['kind'] for m in restored['messages']], ['player'])
        self.assertEqual([m['kind'] for m in restored['pilot']], ['pilot'])
        self.assertEqual(restored['pilot'][0]['body'], 'Would Shenka flee?')
        self.assertEqual(server.GENERATING, {})

    def test_activity_shows_typing_and_ai_dm(self):
        save_id = self.ready_save()
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        stamp = self.api(f'/api/saves/{save_id}')['save']['updated_at']
        self.assertEqual(self.api(f'/api/saves/{save_id}/typing', {'playerId': first, 'typing': True})['typing'], [first])
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['activity'], {'aiDm': None, 'typing': [first]})
        self.assertEqual(restored['save']['updated_at'], stamp)
        self.api(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': 'Done.'})
        self.assertEqual(self.api(f'/api/saves/{save_id}')['activity']['typing'], [])
        self.assertIn('error', self.api_error(f'/api/saves/{save_id}/typing', {'playerId': 'nobody', 'typing': True}))

        gate = GateProvider('Narrated slowly.')
        with patch.object(ai, 'current_provider', return_value=gate):
            results = []
            worker = threading.Thread(target=lambda: results.append(self.api(f'/api/saves/{save_id}/advance', {'beat': 1})))
            worker.start()
            self.assertTrue(gate.started.wait(2))
            self.assertEqual(self.api(f'/api/saves/{save_id}')['activity']['aiDm'], 'advance')
            self.api(f'/api/saves/{save_id}/typing', {'playerId': first, 'typing': True})
            gate.release.set()
            worker.join(5)
        self.assertIsNone(results[0]['activity']['aiDm'])

    def test_ask_and_advance_cannot_run_together(self):
        save_id = self.ready_save()
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        gate = GateProvider('Narrated slowly.')
        with patch.object(ai, 'current_provider', return_value=gate):
            errors = []
            worker = threading.Thread(target=lambda: errors.append(self.api(f'/api/saves/{save_id}/advance', {'beat': 1})))
            worker.start()
            self.assertTrue(gate.started.wait(2))
            blocked = self.api_error(f'/api/saves/{save_id}/ask', {'playerId': first, 'text': 'Would Shenka flee?'})
            self.assertIn('already responding', blocked['error'])
            gate.release.set()
            worker.join(5)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['messages'][-1]['body'], 'Narrated slowly.')
        self.assertEqual(self.api(f'/api/saves/{save_id}')['pilot'], [])

        gate = GateProvider('Operational slowly.')
        with patch.object(ai, 'current_provider', return_value=gate):
            errors = []
            worker = threading.Thread(target=lambda: errors.append(self.api(f'/api/saves/{save_id}/ask', {'playerId': first, 'text': 'Would Shenka flee?'})))
            worker.start()
            self.assertTrue(gate.started.wait(2))
            blocked = self.api_error(f'/api/saves/{save_id}/advance', {'beat': 2, 'override': True})
            self.assertIn('already responding', blocked['error'])
            gate.release.set()
            worker.join(5)
        self.assertEqual(len(errors), 1)
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['save']['beat'], 2)
        self.assertEqual(restored['pilot'][-1]['body'], 'Operational slowly.')


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
                self.assertEqual(len(state['sessions']), 1)
                self.assertIsNone(state['sessions'][0]['ended_at'])
                server.initialize()
                with server.db() as conn:
                    self.assertEqual(len(server.snapshot(conn, 'old-save')['sessions']), 1)
            finally:
                server.DATA = old_data


if __name__ == '__main__':
    unittest.main()
