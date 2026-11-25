"""Read Aloud HTTP access, incremental delivery, and cache behavior."""
from contextlib import contextmanager
import json
import os
import threading
import unittest
import urllib.request
from unittest.mock import patch

import ai
from kokoro_service import SpeechServer
from narration_choices import prose_for_read_aloud, public_body
from read_aloud import spoken_text
import test_flow


class ReadAloudTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    ready_save = test_flow.FlowTest.ready_save
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error

    @contextmanager
    def speech(self, engine):
        with SpeechServer(0, engine) as origin:
            worker = threading.Thread(target=origin.serve_forever, daemon=True)
            worker.start()
            try:
                with patch.dict(os.environ, {'TABLEFORGE_KOKORO_PORT': str(origin.server_port)}):
                    yield
            finally:
                origin.shutdown()
                worker.join(timeout=3)

    def test_spoken_text_preserves_prose_and_discards_internal_metadata(self):
        body = ('## The mine\n> **Alicia** whispers.\n- Roll \x602d6\x60.\n'
                '[Map](https://example.com/map) [Location: Mine]\n'
                '\x60\x60\x60tableforge-choices\nsecret choices\n\x60\x60\x60\nThe torch goes out. '
                '[[TABLEFORGE_COMBAT:START]]')
        self.assertEqual(spoken_text(body), 'The mine\nAlicia whispers.\nRoll 2d6.\nMap \n\nThe torch goes out.')
        self.assertEqual(spoken_text('The door shuts. [[TABLEFORGE_CHO'), 'The door shuts.')

    def test_only_saved_ai_narration_can_stream_and_replay(self):
        line = 'The lantern sputters as the group reaches the last steps of the bridge.'
        prose = '**'+line+'**\n\n'+('A whisper floats out from beneath the walkway. '*4)+'What do you do?'
        save_id = self.ready_save()
        url = f'/api/saves/{save_id}'
        player = self.api(url)['players'][0]['id']
        groups = [{'playerId': None, 'options': ['Call to the guard.']},
                  {'playerId': player, 'options': ['Inspect the *loose* stone.']}]
        body = prose + '\n\n\x60\x60\x60tableforge-choices\n' + json.dumps({'groups': groups}) + '\n\x60\x60\x60'
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(body)):
            saved = self.api(url+'/advance', {})
        self.assertIn('Call to the guard.', saved['messages'][-1]['body'])
        self.assertEqual(len(saved['messages'][-1]['choices']['groups']), 2)
        message = saved['messages'][-1]['id']
        audio_url = f'{url}/read-aloud/{message}?playerId={player}'
        with patch.dict(os.environ, {'TABLEFORGE_KOKORO_PORT': ''}):
            self.assertNotIn('readAloud', self.api(url)['activity'])
            self.assertIn('disabled', self.api_error(audio_url)['error'])

        started_second = threading.Event()
        release = threading.Event()

        class Engine:
            speaker = 3

            def __init__(self):
                self.calls = []

            def encode(self, text, speaker):
                self.calls.append(text)
                if len(self.calls) == 2:
                    started_second.set()
                    if not release.wait(5):
                        raise ValueError('second speech segment timed out in test')
                return text.encode()

        engine = Engine()
        with self.speech(engine):
            self.assertTrue(self.api(url)['activity']['readAloud'])
            self.assertIn('Join this table', self.api_error(audio_url.replace(player, 'wrong'))['error'])
            self.assertIn('saved AI-DM', self.api_error(f'{url}/read-aloud/{saved["messages"][0]["id"]}'
                                                        f'?playerId={player}')['error'])
            self.assertIn('saved AI-DM', self.api_error(f'{url}/read-aloud/999999?playerId={player}')['error'])
            self.assertFalse(engine.calls)
            with urllib.request.urlopen(self.base+audio_url, timeout=5) as response:
                try:
                    self.assertTrue(response.chunked)
                    self.assertEqual(response.headers.get_content_type(), 'audio/mpeg')
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    first = response.read1(8192)
                    self.assertTrue(first.startswith(line.encode()))
                    self.assertTrue(started_second.wait(3))
                    self.assertEqual(self.api(url)['messages'], saved['messages'])
                finally:
                    release.set()
                content = first + response.read()
            with urllib.request.urlopen(self.base+audio_url, timeout=5) as replay:
                self.assertEqual(replay.read(), content)
                self.assertFalse(replay.chunked)
            self.assertEqual(content, ''.join(engine.calls).encode())
            self.assertGreaterEqual(len(engine.calls), 2)
            self.assertEqual(' '.join(engine.calls), ' '.join(spoken_text(prose).split()))

    def test_only_exact_structured_footer_is_removed(self):
        prose = 'The sign has two lines.\n\n- Keep left.\n- Stay dry.\n\nWhat now?'
        choices = {'groups': [{'playerId': 'p1', 'options': [{'letter': 'A', 'text': 'Cross [carefully].'}]}]}
        saved = public_body(prose, choices, [{'id': 'p1', 'character': 'Character at the time'}])
        self.assertEqual(prose_for_read_aloud(saved, choices), prose)
        self.assertEqual(prose_for_read_aloud(saved, None), saved)
        changed = saved + '\n\nA final ray of light falls across the door.'
        self.assertEqual(prose_for_read_aloud(changed, choices), changed)

    def test_selected_voices_are_discoverable_and_cached_independently(self):
        save_id = self.ready_save()
        url = f'/api/saves/{save_id}'
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider('A fox stops.')):
            saved = self.api(url+'/advance', {})
        player = saved['players'][0]['id']
        message = saved['messages'][-1]['id']
        audio_url = f'{url}/read-aloud/{message}?playerId={player}'
        calls = []

        class Engine:
            speaker = 25

            def encode(self, text, speaker):
                calls.append(speaker)
                return f'{speaker}:{text}'.encode()

        with self.speech(Engine()):
            voices = self.api('/api/runtime')['readAloudVoices']
            self.assertEqual([voice['id'] for voice in voices], ['heart', 'daniel', 'george', 'fable'])
            self.assertIn('available Read Aloud voice', self.api_error(audio_url+'&voice=unknown')['error'])
            for suffix, speaker in [('', 25), ('&voice=george', 26), ('&voice=daniel', 24),
                                    ('&voice=george', 26), ('&voice=fable', 25)]:
                with urllib.request.urlopen(self.base+audio_url+suffix, timeout=5) as audio:
                    self.assertEqual(audio.read(), f'{speaker}:A fox stops.'.encode())
            self.assertEqual(calls, [25, 26, 24])
