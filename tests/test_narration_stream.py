"""Mock upstream and two independent listeners for the public narration prototype."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import select
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import ai
import combat
from narration_stream import contains_control, preview_text
import server
import test_combat
import test_flow
import test_opening_flow


def event(data):
    if data == '[DONE]':
        return b'data: [DONE]\n\n'
    return ('data: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode('utf-8')


def delta(text=None, finish=None):
    return event({'choices': [{'index': 0, 'delta': {'content': text},
                               'finish_reason': finish}], 'model': 'gpt-6.2-sol'})


class PrefixTest(unittest.TestCase):
    def test_control_markers_never_show_even_when_split_at_every_character(self):
        ordinary = 'The brass bell rings.'
        controls = [
            '[ Location \n : Area 4; Arrival: hidden door]',
            '[Opening: arrival]',
            '[Chapter: The Hidden Traitor]',
            combat.MARKER,
            '\x60\x60\x60tableforge-choices\n{"secret":"next encounter"}\n\x60\x60\x60',
        ]
        for marker in controls:
            joiner = '\n\n' if marker.startswith('\x60') else ' '
            for index in range(1, len(marker) + 1):
                with self.subTest(marker=marker, position=index):
                    self.assertEqual(preview_text(ordinary + joiner + marker[:index]), ordinary)

    def test_closed_markdown_is_allowed(self):
        text = 'Look at the [location notes](https://example.com).\n\n\x60\x60\x60text\nA sign.\n\x60\x60\x60'
        self.assertFalse(contains_control(text))
        self.assertIn('[location notes]', preview_text(text))
        self.assertTrue(contains_control('The door swings open. [ Location: unfinished'))
        self.assertTrue(contains_control('The door swings open. [[TABLEF'))
        self.assertTrue(contains_control('The road ends here.\n[Chap'))
        self.assertEqual(preview_text('The road ends here.\n[Chapter: The Hidden Traitor]'), 'The road ends here.')


class NarrationFlowTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    ready_save = test_flow.FlowTest.ready_save
    override = test_flow.FlowTest.override
    cartridge_zip = test_flow.FlowTest.cartridge_zip

    def ready_regular_advance(self):
        save_id = self.ready_save()
        # The initial narration stays on the buffered path.
        self.api(f'/api/saves/{save_id}/advance', {})
        state = self.api(f'/api/saves/{save_id}')
        for player in state['players']:
            self.api(f'/api/saves/{save_id}/ready', {'playerId': player['id'], 'ready': True})
        return save_id, self.api(f'/api/saves/{save_id}')

    @contextmanager
    def upstream(self, reply, **environment):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                reply(self)

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as origin:
            worker = threading.Thread(target=origin.serve_forever, daemon=True)
            worker.start()
            try:
                with patch.dict(os.environ, {'TABLEFORGE_STREAM_NARRATION': '1',
                    'TABLEFORGE_OPENAI_API_KEY': 'mock-only', 'TABLEFORGE_AIDM_MODEL': 'gpt-6.2-sol',
                    **environment}), patch.object(ai, 'OPENAI_URL', f'http://127.0.0.1:{origin.server_port}/'):
                    yield received
            finally:
                origin.shutdown()
                worker.join(timeout=3)

    def observe(self, save_id):
        return urllib.request.urlopen(self.base+f'/api/saves/{save_id}/narration', timeout=4)

    def read(self, response):
        while True:
            line = response.readline()
            if not line:
                self.fail('Narration observer closed early')
            if line.startswith(b'data:'):
                return json.loads(line[5:])

    def until(self, response, status):
        for _ in range(8):
            value = self.read(response)
            if value and value['status'] == status:
                return value
        self.fail(f'Status {status} did not arrive')

    def test_start_and_early_advance_stream_without_progressing_before_commit(self):
        state = test_opening_flow.OpeningFlowTest.new_save(self)
        save_id, player = state['save']['id'], state['players'][0]['id']
        url = f'/api/saves/{save_id}'
        for action, prose, payload in [
            ('start', 'A quiet lane stretches before you.\n\nWhere are your characters this morning?',
             {'playerId': player, 'beat': 1}),
            ('advance', 'Alicia steadies herself and looks at the wedged wheel. "Is either of you hurt?"',
             {'playerId': player, 'override': True}),
        ]:
            with self.subTest(action=action):
                before = self.api(url)
                release = threading.Event()

                def reply(handler):
                    handler.wfile.write(delta(prose + '\n\n[Open'))
                    if release.wait(4):
                        handler.wfile.write(delta('ing: hook]') + delta(finish='stop') + event('[DONE]'))

                with self.upstream(reply) as received, ThreadPoolExecutor() as pool, self.observe(save_id) as observer:
                    running = pool.submit(self.api, url+'/'+action, payload)
                    try:
                        self.assertEqual(self.until(observer, 'streaming')['text'], prose)
                        current = self.api(url)
                        self.assertEqual(current['messages'], before['messages'])
                        self.assertEqual(current['save']['beat'], before['save']['beat'])
                        self.assertEqual(current['save']['opening_stage'], before['save']['opening_stage'])
                        self.assertEqual(current['started'], before['started'])
                    finally:
                        release.set()
                    saved = running.result(timeout=4)
                    self.assertEqual(self.until(observer, 'committed')['messageId'], saved['messages'][-1]['id'])
                    self.assertTrue(received[0]['stream'])
                self.assertTrue(saved['started'])
                self.assertEqual(saved['save']['beat'], before['save']['beat'] + 1)
                self.assertEqual(saved['save']['opening_stage'], 'hook')
                self.assertEqual(saved['messages'][-1]['body'], prose)

    def test_aftermath_deadline_closes_stream_and_retry_publishes_once(self):
        combat_flow = test_combat.CombatFlowTest
        save_id, before = combat_flow.enter(self, automatic=True)
        before = combat_flow.finish(self, save_id, before)
        payload = combat_flow.payload(self, before)
        url = f'/api/saves/{save_id}'
        disconnected = threading.Event()
        release_retry = threading.Event()
        final = 'The ogre disappears into the forest.'

        def stall(handler):
            handler.wfile.write(delta('For a moment, nothing moves.') + b'data: ')
            stop = time.monotonic() + 4
            try:
                while time.monotonic() < stop:
                    readable, _, _ = select.select([handler.connection], [], [], 0.05)
                    if readable and handler.connection.recv(1) == b'':
                        disconnected.set()
                        return
                    handler.wfile.write(b' ')
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

        def retry(handler):
            handler.wfile.write(delta(final))
            if release_retry.wait(4):
                handler.wfile.write(delta(finish='stop') + event('[DONE]'))

        with self.upstream(stall), patch.object(server, 'COMBAT_GENERATION_TIMEOUT', 1), \
                ThreadPoolExecutor() as pool, self.observe(save_id) as observer:
            running = pool.submit(self.api_error, url+'/combat-outcome', payload)
            preview = self.until(observer, 'streaming')
            self.assertIn('nothing moves', preview['text'])
            mid = self.api(url)
            self.assertEqual(mid['messages'], before['messages'])
            self.assertEqual(mid['save']['beat'], before['save']['beat'])
            self.assertEqual(mid['save']['mode'], 'combat')
            self.assertEqual(mid['combat']['phase'], 'resuming')
            self.assertEqual(mid['combat']['outcome'], payload['text'])
            self.assertIn('stalled', running.result(timeout=3)['error'])
            self.assertNotIn('text', self.until(observer, 'failed'))
            self.assertTrue(disconnected.wait(1.5), 'The aftermath provider was still streaming after timeout')

        failed = self.api(url)
        self.assertEqual(failed['combat']['phase'], 'failed')
        self.assertEqual(failed['save']['mode'], 'combat')
        self.assertEqual(failed['messages'], before['messages'])
        retry_payload = {'playerId': failed['players'][1]['id'], 'handoffId': payload['handoffId']}
        with self.upstream(retry) as received, ThreadPoolExecutor() as pool, self.observe(save_id) as observer:
            running = pool.submit(self.api, url+'/combat-retry', retry_payload)
            try:
                preview = self.until(observer, 'streaming')
                self.assertEqual(preview['text'], final)
                self.assertEqual(self.api(url+'/combat-retry', retry_payload)['combat']['phase'], 'resuming')
            finally:
                release_retry.set()
            after = running.result(timeout=4)
            self.assertEqual(self.until(observer, 'committed')['messageId'], after['combat']['message_id'])
            self.assertEqual(len(received), 1)
            self.assertIn(payload['text'], received[0]['messages'][0]['content'])
        self.assertEqual(after['combat']['phase'], 'complete')
        self.assertEqual(after['save']['mode'], 'normal')
        self.assertEqual(after['save']['beat'], before['save']['beat'] + 1)
        self.assertEqual(after['messages'][:-1], before['messages'])
        self.assertEqual(after['messages'][-1]['body'], final)
        self.assertEqual([e['body'] for e in after['events'] if e['kind'] == 'combat_outcome'], [payload['text']])

    def test_streamed_aftermath_that_calls_initiative_again_ends_the_fight(self):
        combat_flow = test_combat.CombatFlowTest
        save_id, before = combat_flow.enter(self, automatic=True)
        before = combat_flow.finish(self, save_id, before)
        handoff = before['combat']['id']
        url = f'/api/saves/{save_id}'

        def reply(handler):
            handler.wfile.write(delta('The ogre falls, but its mate charges in! Roll initiative.\n') +
                                delta(combat.MARKER) + delta(finish='stop') + event('[DONE]'))

        with self.upstream(reply) as received:
            after = self.api(url+'/combat-outcome', combat_flow.payload(self, before))
        self.assertEqual(len(received), 1)
        self.assertEqual(after['messages'][-1]['body'], combat.ENDED_FALLBACK)
        self.assertEqual(after['save']['mode'], 'normal')
        self.assertEqual(after['combat']['id'], handoff)
        self.assertEqual(after['combat']['phase'], 'complete')
        self.assertEqual([e['kind'] for e in after['events']].count('combat_started'), 1)

    def test_two_listeners_and_rejoin_see_the_preview_before_combat_commits(self):
        save_id, before = self.ready_regular_advance()
        release = threading.Event()
        prose = 'The bell rings. **Roll initiative.**'

        def reply(handler):
            handler.wfile.write(delta(prose) + delta('\n\n[[TABLEFORGE_'))
            handler.wfile.flush()
            if release.wait(4):
                handler.wfile.write(delta('COMBAT:START]]') + delta(finish='stop') +
                    event({'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 8, 'total_tokens': 18}}) +
                    event('[DONE]'))

        url = f'/api/saves/{save_id}'
        with self.upstream(reply) as received, ThreadPoolExecutor() as pool:
            with self.observe(save_id) as first, self.observe(save_id) as second:
                self.assertEqual(first.headers.get_content_type(), 'text/event-stream')
                self.assertIsNone(self.read(first))
                self.assertIsNone(self.read(second))
                running = pool.submit(self.api, url+'/advance', {'beat': before['save']['beat']})
                try:
                    preview = self.until(first, 'streaming')
                    self.assertEqual(preview, self.until(second, 'streaming'))
                    self.assertEqual(preview['text'], prose)
                    with self.observe(save_id) as rejoined:
                        self.assertEqual(self.read(rejoined), preview)
                    mid = self.api(url)
                    self.assertEqual(mid['messages'], before['messages'])
                    self.assertEqual(mid['save']['beat'], before['save']['beat'])
                    self.assertEqual(mid['players'], before['players'])
                    self.assertIsNone(mid['combat'])
                    self.assertIn('already responding', self.api_error(url+'/advance', {})['error'])
                finally:
                    first.close()
                    release.set()
                settled = self.until(second, 'committed')
                after = running.result(timeout=4)
                self.assertEqual(settled['messageId'], after['messages'][-1]['id'])
                self.assertNotIn('text', settled)
                self.assertEqual(after['messages'][-1]['body'], prose)
                self.assertEqual(after['save']['beat'], before['save']['beat'] + 1)
                self.assertEqual(after['combat']['phase'], 'fighting')
                self.assertFalse(any(p['ready'] for p in after['players']))
                self.assertEqual(len(received), 1)
                self.assertIs(received[0]['stream'], True)
                self.assertEqual(received[0]['stream_options'], {'include_usage': True})
        with server.db() as db:
            actual = db.execute("SELECT total_tokens FROM ai_usage ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(actual['total_tokens'], 18)

    def test_rejected_narration_is_discarded_and_the_beat_can_be_retried(self):
        save_id, before = self.ready_regular_advance()
        url = f'/api/saves/{save_id}'
        release = threading.Event()

        def reply(handler):
            handler.wfile.write(delta('The bridge shudders.\n\nWhat do you do?'))
            if release.wait(4):
                handler.wfile.write(delta('\n\nYou cross before the guard can stop you.') +
                                    delta(finish='stop') + event('[DONE]'))

        with self.upstream(reply), ThreadPoolExecutor() as pool, self.observe(save_id) as observer:
            running = pool.submit(self.api_error, url+'/advance', {})
            try:
                self.assertIn('bridge', self.until(observer, 'streaming')['text'])
            finally:
                release.set()
            self.assertNotIn('text', self.until(observer, 'failed'))
            self.assertIn('No narration was published', running.result(timeout=4)['error'])
        failed = self.api(url)
        self.assertEqual(failed['messages'], before['messages'])
        self.assertEqual(failed['save']['beat'], before['save']['beat'])
        self.assertEqual(failed['players'], before['players'])
        self.assertEqual(self.api(url+'/advance', {})['save']['beat'], before['save']['beat']+1)

    def test_idle_timeout_closes_the_upstream_socket_and_discards_the_preview(self):
        save_id, before = self.ready_regular_advance()
        url = f'/api/saves/{save_id}'
        disconnected = threading.Event()

        def reply(handler):
            handler.wfile.write(delta('The reeds stir.'))
            handler.connection.settimeout(3)
            if handler.connection.recv(1) == b'':
                disconnected.set()

        with self.upstream(reply), patch.object(ai, 'OPENAI_TIMEOUT', 0.5), \
                ThreadPoolExecutor() as pool, self.observe(save_id) as observer:
            running = pool.submit(self.api_error, url+'/advance', {})
            self.until(observer, 'streaming')
            self.assertNotIn('text', self.until(observer, 'failed'))
            self.assertIn('connection ended', running.result(timeout=4)['error'])
            self.assertTrue(disconnected.wait(3))
        after = self.api(url)
        self.assertEqual(after['messages'], before['messages'])
        self.assertEqual(after['save']['beat'], before['save']['beat'])

    def test_generation_deadline_interrupts_an_unfinished_event(self):
        save_id, before = self.ready_regular_advance()
        url = f'/api/saves/{save_id}'
        disconnected = threading.Event()

        def reply(handler):
            handler.wfile.write(delta('Mist gathers at the bridge.') + b'data: ')
            stop = time.monotonic() + 3
            try:
                while time.monotonic() < stop:
                    readable, _, _ = select.select([handler.connection], [], [], 0.05)
                    if readable and handler.connection.recv(1) == b'':
                        disconnected.set()
                        return
                    # Socket reads keep succeeding, but the SSE line never completes.
                    handler.wfile.write(b' ')
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

        with self.upstream(reply), patch.object(ai, 'OPENAI_TIMEOUT', 2), \
                patch.object(ai, 'NARRATION_STREAM_SECONDS', 0.75), \
                ThreadPoolExecutor() as pool, self.observe(save_id) as observer:
            running = pool.submit(self.api_error, url+'/advance', {})
            self.until(observer, 'streaming')
            self.assertTrue(disconnected.wait(1.5), 'The provider socket stayed open past the deadline')
            self.assertIn('time limit', running.result(timeout=2)['error'])
            self.assertNotIn('text', self.until(observer, 'failed'))

        after = self.api(url)
        self.assertEqual(after['messages'], before['messages'])
        self.assertEqual(after['save']['beat'], before['save']['beat'])
        self.assertIsNone(after['activity']['aiDm'])
        retried = self.api(url+'/advance', {})
        self.assertEqual(retried['save']['beat'], before['save']['beat'] + 1)

    def test_early_eof_cannot_publish_even_after_stop(self):
        save_id, before = self.ready_regular_advance()
        url = f'/api/saves/{save_id}'

        def reply(handler):
            handler.wfile.write(delta('The reeds stir.') + delta(finish='stop'))

        with self.upstream(reply):
            self.assertIn('ended before it finished', self.api_error(url+'/advance', {})['error'])
        self.assertEqual(self.api(url)['messages'], before['messages'])

    def test_truncated_narration_records_reported_usage_without_publishing(self):
        save_id, before = self.ready_regular_advance()
        url = f'/api/saves/{save_id}'

        def reply(handler):
            handler.wfile.write(delta('The reeds stir.') + delta(finish='length') +
                event({'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}) +
                event('[DONE]'))

        with self.upstream(reply):
            self.assertIn('was incomplete', self.api_error(url+'/advance', {})['error'])
        self.assertEqual(self.api(url)['messages'], before['messages'])
        with server.db() as db:
            recorded = db.execute("""SELECT r.status,u.total_tokens FROM ai_requests r
                JOIN ai_usage u ON r.id=u.request_id WHERE r.save_id=?""", (save_id,)).fetchone()
        self.assertEqual(tuple(recorded), ('failed', 15))

    def test_disabled_endpoint_keeps_the_buffered_path(self):
        save_id, _ = self.ready_regular_advance()
        self.assertIn('disabled', self.api_error(f'/api/saves/{save_id}/narration')['error'])
