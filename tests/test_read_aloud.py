"""Read Aloud HTTP access, incremental delivery, and cache behavior."""
from contextlib import contextmanager
import os
import threading
import unittest
import urllib.request
from unittest.mock import patch

import ai
from kokoro_service import SpeechServer
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
        body = '**'+line+'**\n\n'+('A whisper floats out from beneath the walkway. '*4).strip()
        save_id = self.ready_save()
        url = f'/api/saves/{save_id}'
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(body)):
            saved = self.api(url+'/advance', {})
        player = saved['players'][0]['id']
        message = saved['messages'][-1]['id']
        audio_url = f'{url}/read-aloud/{message}?playerId={player}'
        with patch.dict(os.environ, {'TABLEFORGE_KOKORO_PORT': ''}):
            self.assertNotIn('readAloud', self.api(url)['activity'])
            self.assertIn('disabled', self.api_error(audio_url)['error'])

        started_second = threading.Event()
        release = threading.Event()

        class Engine:
            def __init__(self):
                self.calls = []

            def encode(self, text):
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
