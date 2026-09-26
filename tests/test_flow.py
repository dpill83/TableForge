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
        self.env = patch.dict(os.environ, {'TABLEFORGE_OPENAI_API_KEY': '', 'TABLEFORGE_AIDM_MODEL': '', 'TABLEFORGE_MODEL': ''})
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

    def override(self, save_id, **extra):
        """A Pilot's Ready Override, made by the first player."""
        return {'override': True, 'playerId': self.api(f'/api/saves/{save_id}')['players'][0]['id'], **extra}

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
        error = self.api_error(f'/api/saves/{save_id}/advance', self.override(save_id, beat=1))
        self.assertIn('already advanced', error['error'])
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['save']['beat'], 2)
        self.assertEqual([m['kind'] for m in restored['messages']].count('ai'), 1)

    def test_draft_from_previous_beat_is_held_for_review(self):
        save_id = self.ready_save()
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        self.api(f'/api/saves/{save_id}/advance', self.override(save_id, beat=1))
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

    def play_long_history(self, save_id, player, beats=4, size=15000):
        for beat in range(beats):
            self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': str(beat) * size})
            self.api(f'/api/saves/{save_id}/advance', self.override(save_id))

    def test_context_preview_is_the_exact_provider_payload(self):
        save_id = self.ready_save('# Intro\n' + 'x' * ai.MODULE_CAP + '\n# Finale\nSecret ending.\n## Epilogue\n')
        preview = self.api(f'/api/saves/{save_id}/context')
        module = preview['report']['module']
        self.assertTrue(module['truncated'])
        self.assertEqual(module['cutSection'], '# Intro')
        self.assertEqual(module['omittedSections'], ['# Finale', '## Epilogue'])
        self.assertNotIn('Secret ending', preview['messages'][0]['content'])
        self.assertEqual(preview['report']['transcript']['omitted'], 0)
        fake = FakeProvider()
        with patch.object(ai, 'current_provider', return_value=fake):
            self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertEqual(preview['messages'], ai.chat_messages(fake.context))

    def test_current_beat_is_never_trimmed_and_omissions_are_reported(self):
        save_id = self.ready_save()
        first, second = [p['id'] for p in self.api(f'/api/saves/{save_id}')['players']]
        self.play_long_history(save_id, first)
        self.api(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': 'a' * 20000})
        self.api(f'/api/saves/{save_id}/messages', {'playerId': second, 'text': 'b' * 20000})
        self.api(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': 'I keep watch.'})
        report = self.api(f'/api/saves/{save_id}/context')['report']['transcript']
        self.assertEqual(report['currentBeat'], 3)
        self.assertTrue(report['currentBeatOverBudget'])
        self.assertEqual(report['history'], 0)
        self.assertEqual(report['omitted'], 9)
        fake = FakeProvider()
        with patch.object(ai, 'current_provider', return_value=fake):
            self.api(f'/api/saves/{save_id}/advance', self.override(save_id))
        self.assertEqual([m['body'] for m in fake.context['messages']], ['a' * 20000, 'b' * 20000, 'I keep watch.'])

    def test_summary_is_drafted_reviewed_saved_and_used(self):
        save_id = self.ready_save()
        first, second = [p['id'] for p in self.api(f'/api/saves/{save_id}')['players']]
        self.assertIn('no older history', self.api_error(f'/api/saves/{save_id}/summary-draft', {'playerId': first})['error'])
        self.play_long_history(save_id, first)
        before = self.api(f'/api/saves/{save_id}/context')
        self.assertGreater(before['report']['transcript']['omitted'], 0)
        draft = self.api(f'/api/saves/{save_id}/summary-draft', {'playerId': first})
        self.assertIsNone(draft['basedOn'])
        self.assertIn('Mock summary', draft['draft'])
        self.assertIsNone(self.api(f'/api/saves/{save_id}')['summary'])
        with patch.object(ai, 'current_provider', return_value=MeteredProvider()):
            self.api(f'/api/saves/{save_id}/summary-draft', {'playerId': first})
        with closing(sqlite3.connect(self.path / 'tableforge.sqlite3')) as conn:
            self.assertEqual([row[0] for row in conn.execute('SELECT purpose FROM ai_usage')], ['summary'])

        current = self.api(f'/api/saves/{save_id}/messages', {'playerId': first, 'text': 'Open beat.'})
        open_id = current['messages'][-1]['id']
        error = self.api_error(f'/api/saves/{save_id}/summaries', {'playerId': first, 'text': 'x', 'basedOn': None,
                                                                   'throughMessageId': open_id})
        self.assertIn('completed beats', error['error'])
        saved = self.api(f'/api/saves/{save_id}/summaries', {'playerId': second, 'text': 'The party crossed the moor.',
                                                             'basedOn': None, 'throughMessageId': draft['throughMessageId']})
        self.assertEqual(saved['summary']['player_character'], 'Ethereal')
        self.assertEqual(saved['summary']['through_message_id'], draft['throughMessageId'])
        stale = self.api_error(f'/api/saves/{save_id}/summaries', {'playerId': first, 'text': 'Again.', 'basedOn': None,
                                                                   'throughMessageId': draft['throughMessageId']})
        self.assertIn('Another summary', stale['error'])

        after = self.api(f'/api/saves/{save_id}/context')
        self.assertIn('The party crossed the moor.', after['messages'][0]['content'])
        self.assertEqual(after['report']['transcript']['summarized'],
                         len([m for m in saved['messages'] if m['id'] <= draft['throughMessageId']]))
        self.assertEqual(after['report']['transcript']['omitted'], 0)
        self.assertEqual(after['messages'][-1]['content'], 'George: Open beat.')

    FOCUSED_MODULE = """# Well Job
Always-known premise.

## Running notes
The bell clock rings.

## Hook

### Player Briefing (read aloud)
Sybil hires you.

### DM Secrets (never read aloud)
The robbers are hostages.

## Approach & arrival
The road to the graveyard.

## Areas

### Area 1: Gate  *(entrance)*
Gate text.

### Area 2: Hall  *(breather)*
Hall text.

### Area 3: Stage  *(boss)*
Stage text.

## Stat blocks

### Muxus (CR 15)
Muxus block.

### Flyman (CR 7)
Flyman block.
"""
    FOCUSED_RUN_DATA = {'title': 'Well Job', 'rooms': [
        {'roomNumber': 1, 'beat': 'entrance', 'connectsTo': [2], 'encounter': {'monsters': []}},
        {'roomNumber': 2, 'beat': 'breather', 'connectsTo': [1, 3], 'encounter': {'monsters': []}},
        {'roomNumber': 3, 'beat': 'boss', 'connectsTo': [2], 'encounter': {'monsters': ['Muxus', '2 Flyman']}}]}

    def focused_save(self, module=None, run_data=None):
        cartridge = self.cartridge_zip({'manifest.json': json.dumps({'format': 'tableforge-adventure', 'formatVersion': 1,
                                                                     'title': 'Well Job', 'resources': {}}),
                                        'module.md': module if module is not None else self.FOCUSED_MODULE,
                                        'run-data.json': json.dumps(run_data if run_data is not None else self.FOCUSED_RUN_DATA)})
        save = self.api('/api/saves', {'cartridgeId': cartridge['id'], 'players': [{'name': 'A', 'character': 'Alice'}]})
        return save['save']['id'], save['players'][0]['id']

    def test_action_retrieval_matches_preview_and_expires_with_beat(self):
        from test_module_context import MODULE, ROOMS
        save_id, player = self.focused_save(MODULE, {'rooms': ROOMS})
        self.api(f'/api/saves/{save_id}/location', {'playerId': player, 'location': 5})
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'I read the prompt-book.'})
        preview = self.api(f'/api/saves/{save_id}/context')
        fake = FakeProvider('You study the book. [Location: Area 5]')
        with patch.object(ai, 'current_provider', return_value=fake):
            advanced = self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertEqual(preview['messages'], ai.chat_messages(fake.context))
        self.assertIn('EXACT MUXUS LAIR ACTIONS', fake.context['module'])
        self.assertNotIn('OBSERVATORY SECRET', fake.context['module'])
        self.assertEqual(advanced['save']['location'], 5)
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'I wait quietly.'})
        next_context = ai.build_context(self.api(f'/api/saves/{save_id}'), self.path)
        self.assertNotIn('EXACT MUXUS LAIR ACTIONS', next_context['module'])
        self.assertIn('I read the prompt-book.', [m['body'] for m in next_context['messages']])

    def test_remote_pilot_question_retrieves_stat_block_without_table_changes(self):
        from test_module_context import MODULE, ROOMS
        save_id, player = self.focused_save(MODULE, {'rooms': ROOMS})
        before = self.api(f'/api/saves/{save_id}/location', {'playerId': player, 'location': 1})
        fake = FakeProvider('Those are the available lair actions.')
        with patch.object(ai, 'current_provider', return_value=fake):
            after = self.api(f'/api/saves/{save_id}/ask', {'playerId': player, 'text': "What are Muxus's lair actions?"})
        self.assertIn('EXACT MUXUS LAIR ACTIONS', fake.context['module'])
        self.assertNotIn('OBSERVATORY SECRET', fake.context['module'])
        self.assertEqual(after['save']['location'], 1)
        self.assertEqual(after['save']['beat'], before['save']['beat'])
        self.assertEqual(after['messages'], before['messages'])
        self.assertEqual([p['ready'] for p in after['players']], [p['ready'] for p in before['players']])

    def test_followup_uses_immediate_narration_for_retrieval(self):
        from test_module_context import MODULE, ROOMS
        save_id, player = self.focused_save(MODULE, {'rooms': ROOMS})
        self.api(f'/api/saves/{save_id}/location', {'playerId': player, 'location': 5})
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'Look around.'})
        fake = FakeProvider('The prompt-book lies open on the chair. [Location: Area 5]')
        with patch.object(ai, 'current_provider', return_value=fake):
            self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'I read it.'})
        context = ai.build_context(self.api(f'/api/saves/{save_id}'), self.path)
        self.assertIn('EXACT MUXUS LAIR ACTIONS', context['module'])
        self.assertTrue(any('preceding reply' in s['reason'] for s in context['report']['module']['included']))

    def test_focused_context_follows_ai_dm_location_marker(self):
        save_id, player = self.focused_save()
        preview = self.api(f'/api/saves/{save_id}/context')
        module = preview['report']['module']
        self.assertEqual((module['mode'], module['location']), ('focused', None))
        system = preview['messages'][0]['content']
        for text in ('Always-known premise', 'bell clock', 'hostages', 'Sybil hires you', 'road to the graveyard', 'Gate text'):
            self.assertIn(text, system)
        for text in ('Hall text', 'Stage text', 'Muxus block'):
            self.assertNotIn(text, system)
        self.assertIn('[Location: Area N]', system)
        self.assertEqual([item['label'] for item in preview['report']['locations']],
                         ['Approach (not yet at the site)', 'Area 1: Gate', 'Area 2: Hall', 'Area 3: Stage'])

        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'We go in.'})
        with patch.object(ai, 'current_provider', return_value=FakeProvider('You pass the gate into the hall.\n\n[Location: Area 2]')):
            advanced = self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertEqual(advanced['messages'][-1]['body'], 'You pass the gate into the hall.')
        self.assertEqual(advanced['save']['location'], 2)
        event = [e for e in advanced['events'] if e['kind'] == 'location'][-1]
        self.assertEqual((event['player_id'], json.loads(event['body'])), (None, {'location': 2, 'source': 'ai-dm'}))

        system = self.api(f'/api/saves/{save_id}/context')['messages'][0]['content']
        for text in ('Gate text', 'Hall text', 'Stage text', 'Muxus block', 'Flyman block', 'bell clock'):
            self.assertIn(text, system)
        self.assertNotIn('Sybil hires you', system)

        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'Wait.'})
        with patch.object(ai, 'current_provider', return_value=FakeProvider('Nothing moves. [Location: Area 9]')):
            advanced = self.api(f'/api/saves/{save_id}/advance', {'beat': 2})
        self.assertEqual(advanced['messages'][-1]['body'], 'Nothing moves.')
        self.assertEqual(advanced['save']['location'], 2)

    def test_pilot_corrects_location(self):
        save_id, player = self.focused_save()
        moved = self.api(f'/api/saves/{save_id}/location', {'playerId': player, 'location': 3})
        self.assertEqual(moved['save']['location'], 3)
        event = [e for e in moved['events'] if e['kind'] == 'location'][-1]
        self.assertEqual((event['player_id'], json.loads(event['body'])['source']), (player, 'pilot'))
        for bad in (7, '3'):
            self.assertIn('Choose a location', self.api_error(f'/api/saves/{save_id}/location',
                                                              {'playerId': player, 'location': bad})['error'])
        preview = self.api(f'/api/saves/{save_id}/context')
        self.assertIn('Muxus block', preview['messages'][0]['content'])
        self.assertNotIn('Gate text', preview['messages'][0]['content'])
        back = self.api(f'/api/saves/{save_id}/location', {'playerId': player, 'location': None})
        self.assertIsNone(back['save']['location'])

    def test_mock_ai_dm_keeps_location_and_hides_marker(self):
        save_id, player = self.focused_save()
        self.api(f'/api/saves/{save_id}/location', {'playerId': player, 'location': 1})
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'Look around.'})
        advanced = self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertNotIn('[Location', advanced['messages'][-1]['body'])
        self.assertEqual(advanced['save']['location'], 1)

    def test_unstructured_run_data_sends_full_module(self):
        save_id = self.ready_save('# Test adventure\n\n## Areas\n\n### Area 1: Gate\nGate text.')
        preview = self.api(f'/api/saves/{save_id}/context')
        self.assertEqual(preview['report']['module']['mode'], 'full')
        self.assertIn('Gate text', preview['messages'][0]['content'])
        self.assertNotIn('[Location:', preview['messages'][0]['content'])

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
            self.override(save_id, beat=1))['error'])
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
            blocked = self.api_error(f'/api/saves/{save_id}/advance', self.override(save_id, beat=2))
            self.assertIn('already responding', blocked['error'])
            gate.release.set()
            worker.join(5)
        self.assertEqual(len(errors), 1)
        restored = self.api(f'/api/saves/{save_id}')
        self.assertEqual(restored['save']['beat'], 2)
        self.assertEqual(restored['pilot'][-1]['body'], 'Operational slowly.')

    def test_retried_send_with_request_id_posts_once(self):
        save_id = self.ready_save()
        first, second = [p['id'] for p in self.api(f'/api/saves/{save_id}')['players']]
        request_id = '7b0f5e1c-2d4a-4c8e-9f11-0a1b2c3d4e5f'
        send = {'playerId': first, 'text': 'I check the rope.', 'beat': 1, 'requestId': request_id}
        self.api(f'/api/saves/{save_id}/messages', send)
        again = self.api(f'/api/saves/{save_id}/messages', send)
        self.assertEqual([m['body'] for m in again['messages']].count('I check the rope.'), 1)
        # The response was lost and the table moved on: the retry is still recognized, not held as stale.
        self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        late = self.api(f'/api/saves/{save_id}/messages', send)
        self.assertEqual([m['body'] for m in late['messages']].count('I check the rope.'), 1)
        self.assertEqual(late['save']['beat'], 2)
        self.assertIn('different message', self.api_error(f'/api/saves/{save_id}/messages', {**send, 'text': 'Edited.'})['error'])
        self.assertIn('different message', self.api_error(f'/api/saves/{save_id}/messages', {**send, 'playerId': second})['error'])
        self.assertIn('request ID', self.api_error(f'/api/saves/{save_id}/messages', {**send, 'requestId': 'nope'})['error'])
        # Other saves may reuse the same client ID without colliding.
        other = self.ready_save()
        other_player = self.api(f'/api/saves/{other}')['players'][0]['id']
        self.api(f'/api/saves/{other}/messages', {**send, 'playerId': other_player})

    def test_ready_override_records_initiator_and_ready_states(self):
        save_id = self.ready_save()
        first, second = [p['id'] for p in self.api(f'/api/saves/{save_id}')['players']]
        self.api(f'/api/saves/{save_id}/ready', {'playerId': first, 'ready': False})
        self.assertIn('Select a player', self.api_error(f'/api/saves/{save_id}/advance', {'beat': 1, 'override': True})['error'])
        with patch.object(ai, 'current_provider', return_value=BoomProvider()):
            self.api_error(f'/api/saves/{save_id}/advance', {'beat': 1, 'override': True, 'playerId': second})
        self.assertFalse([e for e in self.api(f'/api/saves/{save_id}')['events'] if e['kind'] == 'ready_override'])
        fake = FakeProvider()
        with patch.object(ai, 'current_provider', return_value=fake):
            result = self.api(f'/api/saves/{save_id}/advance', {'beat': 1, 'override': True, 'playerId': second})
        self.assertNotIn('override', fake.context)
        [event] = [e for e in result['events'] if e['kind'] == 'ready_override']
        self.assertEqual(event['player_id'], second)
        self.assertEqual(json.loads(event['body']), {'beat': 1, 'messageId': result['messages'][-1]['id'],
                                                     'ready': {first: False, second: True}, 'waitingOn': [first]})
        # A normal all-Ready advance leaves no override record.
        for player in (first, second):
            self.api(f'/api/saves/{save_id}/ready', {'playerId': player, 'ready': True})
        normal = self.api(f'/api/saves/{save_id}/advance', {'beat': 2})
        self.assertEqual(len([e for e in normal['events'] if e['kind'] == 'ready_override']), 1)

    def test_party_notes_are_pilot_authored_and_kept_out_of_ai_context(self):
        save_id = self.ready_save()
        first, second = [p['id'] for p in self.api(f'/api/saves/{save_id}')['players']]
        note = {'playerId': first, 'pilot': True, 'category': 'npc', 'title': 'Sybil Peti',
                'body': "Cheese-factor from Gillian's Hill."}
        self.assertIn('Pilot Mode', self.api_error(f'/api/saves/{save_id}/notes', {**note, 'pilot': False})['error'])
        self.assertIn('Choose NPCs', self.api_error(f'/api/saves/{save_id}/notes', {**note, 'category': 'secret'})['error'])
        self.assertIn('title', self.api_error(f'/api/saves/{save_id}/notes', {**note, 'title': ' '})['error'])
        created = self.api(f'/api/saves/{save_id}/notes', note)
        [saved] = created['notes']
        self.assertEqual((saved['title'], saved['created_by']), ('Sybil Peti', first))
        self.assertEqual(created['players'], self.api(f'/api/saves/{save_id}')['players'])
        edited = self.api(f'/api/saves/{save_id}/notes', {**note, 'id': saved['id'], 'playerId': second,
                                                           'body': 'Hired the party to stop impostors.'})
        self.assertEqual((edited['notes'][0]['body'], edited['notes'][0]['updated_by']), ('Hired the party to stop impostors.', second))
        fake = FakeProvider()
        with patch.object(ai, 'current_provider', return_value=fake):
            self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertNotIn('impostors', json.dumps(fake.context))
        removed = self.api(f'/api/saves/{save_id}/notes', {'playerId': first, 'pilot': True, 'id': saved['id'], 'remove': True})
        self.assertEqual(removed['notes'], [])
        self.assertIn('no longer exists', self.api_error(f'/api/saves/{save_id}/notes', {**note, 'id': saved['id']})['error'])
        with closing(sqlite3.connect(self.path / 'tableforge.sqlite3')) as conn:
            self.assertEqual(conn.execute('SELECT removed_by FROM party_notes').fetchone()[0], first)

    def test_backup_restore_round_trip_keeps_cartridges_separate(self):
        save_id = self.ready_save()
        player = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        backup = self.api('/api/backups', {})
        self.assertEqual(backup['integrity'], 'ok')
        self.assertEqual((backup['counts']['saves'], backup['counts']['messages']), (1, 1))
        self.assertEqual(backup['missingCartridges'], [])
        self.assertFalse(list((self.path / 'backups').glob('*.zip')))
        self.assertEqual([b['name'] for b in self.api('/api/backups')['backups']], [backup['name']])
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'After the backup.'})
        server.GENERATING[save_id] = 'advance'
        self.assertIn('Wait for the AI-DM', self.api_error(f'/api/backups/{backup["name"]}/restore', {})['error'])
        server.GENERATING.clear()
        restored = self.api(f'/api/backups/{backup["name"]}/restore', {})
        self.assertEqual(restored['live']['counts'], backup['counts'])
        self.assertEqual([m['body'] for m in self.api(f'/api/saves/{save_id}')['messages']], ['I look ahead.'])
        # The data replaced by the restore is itself kept and can be restored.
        safety = self.api(f'/api/backups/{restored["safetyBackup"]}/verify', {})
        self.assertEqual(safety['counts']['messages'], 2)
        # Cartridges are referenced, never bundled: a missing package is reported, not recreated.
        cartridge = self.api(f'/api/saves/{save_id}')['cartridge']['id']
        (self.path / 'cartridges' / (cartridge + '.zip')).unlink()
        self.assertEqual(self.api(f'/api/backups/{backup["name"]}/verify', {})['missingCartridges'], [cartridge])
        (self.path / 'backups' / 'broken.sqlite3').write_bytes(b'not a database' * 100)
        self.assertIn('not a TableForge database', self.api_error('/api/backups/broken.sqlite3/restore', {})['error'])
        self.assertIn('Choose a backup', self.api_error('/api/backups/..%2Ftableforge.sqlite3/verify', {})['error'])
        self.assertEqual(len(self.api(f'/api/saves/{save_id}')['messages']), 1)


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
