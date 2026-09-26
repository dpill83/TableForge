"""Image requests stay independent of narration, readiness, and cartridge secrets."""
import base64
import io
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch

import ai
import metering
import scene_images
import server
from test_flow import FlowTest as _FlowTest


JPEG = b'\xff\xd8\xff\xe0test-image\xff\xd9'


class SceneImageFlowTest(unittest.TestCase):
    setUp = _FlowTest.setUp
    tearDown = _FlowTest.tearDown
    api = _FlowTest.api
    api_error = _FlowTest.api_error
    ready_save = _FlowTest.ready_save

    def prepare(self):
        save_id = self.ready_save('# The secret dragon is behind the wall.')
        state = self.api(f'/api/saves/{save_id}/advance', {})
        self.save_id = save_id
        self.player = state['players'][0]['id']
        self.image_path = f'/api/saves/{save_id}/images'
        self.payload = {'requestId': str(uuid.uuid4()), 'playerId': self.player, 'pilot': True,
                        'sourceMessageId': state['messages'][-1]['id'], 'direction': 'Warm torchlight.'}
        self.key = patch.dict(os.environ, {'TABLEFORGE_OPENAI_API_KEY': 'test-key'})
        self.key.start()
        self.addCleanup(self.key.stop)
        narration = patch.object(ai, 'current_provider', return_value=ai.MockProvider())
        narration.start()
        self.addCleanup(narration.stop)
        return state

    def generate(self):
        with patch.object(scene_images, 'generate', return_value=scene_images.GeneratedImage(
                JPEG, scene_images.DEFAULT_MODEL, {'input_tokens': 100, 'output_tokens': 200})) as provider:
            result = self.api(self.image_path, self.payload)
        return result['images'][-1], provider

    def test_generate_share_reload_and_context_isolation(self):
        before = self.prepare()
        image, provider = self.generate()
        prompt = provider.call_args.args[0]
        self.assertIn(before['messages'][-1]['body'], prompt)
        self.assertIn('Warm torchlight', prompt)
        self.assertNotIn('secret dragon', prompt)
        pending = self.api(f'/api/saves/{self.save_id}')
        self.assertEqual(pending['messages'], before['messages'])
        self.assertEqual(pending['images'], [])
        self.assertEqual(pending['save']['beat'], before['save']['beat'])
        self.assertEqual(pending['players'], before['players'])
        self.assertEqual(pending['imageUsage']['save']['generated'], 1)
        self.assertAlmostEqual(pending['imageUsage']['save']['estimatedCostUsd'], .0065)
        self.assertEqual(pending['usage'], before['usage'])
        self.assertEqual(self.api(self.image_path+'?playerId='+self.player)['images'][0]['status'], 'draft')
        self.api_error(self.image_path+'/'+image['id'])  # Drafts are not on the public media route.
        with urllib.request.urlopen(self.base+self.image_path+'/'+image['id']+'?playerId='+self.player) as response:
            self.assertEqual(response.read(), JPEG)
        share = self.image_path+'/'+image['id']+'/share'
        self.api(share, self.payload)
        self.api(share, self.payload)  # Retrying a lost acknowledgement does not duplicate history.
        restored = self.api(f'/api/saves/{self.save_id}')
        self.assertEqual(len(restored['messages']), len(before['messages'])+1)
        self.assertEqual(restored['messages'][-1]['kind'], 'image')
        self.assertEqual(restored['images'][0]['source_message_id'], self.payload['sourceMessageId'])
        self.assertEqual(restored['players'], before['players'])
        self.assertEqual(restored['save']['beat'], before['save']['beat'])
        with urllib.request.urlopen(self.base+self.image_path+'/'+image['id']) as response:
            self.assertEqual(response.headers['Content-Type'], 'image/jpeg')
            self.assertEqual(response.read(), JPEG)
        context = ai.build_context(restored, self.path)
        self.assertFalse(any(m['kind']=='image' for m in context['messages']))
        self.assertNotIn('Scene illustration', json.dumps(ai.chat_messages(context)))
        self.assertFalse(any(m['kind']=='image' for m in ai.summary_range(restored['messages'])))
        self.assertEqual(self.api('/api/usage')['imageUsage']['generated'], 1)

    def test_discard_retains_usage_but_never_posts(self):
        before = self.prepare()
        image, _ = self.generate()
        self.api(self.image_path+'/'+image['id']+'/discard', self.payload)
        self.api(self.image_path+'/'+image['id']+'/discard', self.payload)
        state = self.api(f'/api/saves/{self.save_id}')
        self.assertEqual(state['messages'], before['messages'])
        self.assertEqual(state['imageUsage']['save']['generated'], 1)
        self.assertEqual(self.api(self.image_path+'?playerId='+self.player)['images'], [])
        self.api_error(self.image_path+'/'+image['id']+'/share', self.payload)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.base+self.image_path+'/'+image['id']+'?playerId='+self.player)

    def test_duplicate_generation_request_is_not_billed_again(self):
        self.prepare()
        with patch.object(scene_images, 'generate', return_value=scene_images.GeneratedImage(JPEG, scene_images.DEFAULT_MODEL, {})) as provider:
            self.api(self.image_path, self.payload)
            self.api(self.image_path, self.payload)
            self.assertEqual(provider.call_count, 1)

    def test_failure_keeps_state_and_requires_explicit_new_request(self):
        before = self.prepare()
        with patch.object(scene_images, 'generate', side_effect=ValueError('Image rate limit')) as provider:
            error = self.api_error(self.image_path, self.payload)
            self.assertIn('rate limit', error['error'])
            self.assertEqual(self.api(self.image_path, self.payload)['images'][0]['status'], 'failed')
            self.assertEqual(provider.call_count, 1)
        state = self.api(f'/api/saves/{self.save_id}')
        self.assertEqual(state['players'], before['players'])
        self.assertEqual(state['messages'], before['messages'])
        self.assertEqual(state['save']['beat'], before['save']['beat'])
        self.assertIsNone(state['imageUsage']['save']['estimatedCostUsd'])
        self.payload['requestId'] = str(uuid.uuid4())
        image, _ = self.generate()
        self.assertEqual(image['status'], 'draft')
        state = self.api(f'/api/saves/{self.save_id}')
        for usage in (state['imageUsage']['save'], state['imageUsage']['session'],
                      self.api('/api/usage')['imageUsage']):
            self.assertAlmostEqual(usage['knownEstimatedCostUsd'], .0065)
            self.assertIsNone(usage['estimatedCostUsd'])
            self.assertEqual(usage['unpricedRequests'], 1)

    def test_in_flight_request_does_not_block_play_and_keeps_source(self):
        before = self.prepare()
        started, release = threading.Event(), threading.Event()
        results = []
        def slow(prompt, model):
            started.set()
            if not release.wait(5):
                raise ValueError('test gate timed out')
            return scene_images.GeneratedImage(JPEG, model, {})
        with patch.object(scene_images, 'generate', side_effect=slow):
            thread = threading.Thread(target=lambda: results.append(self.api(self.image_path, self.payload)))
            thread.start()
            try:
                self.assertTrue(started.wait(3))
                duplicate = dict(self.payload, requestId=str(uuid.uuid4()))
                self.assertIn('already generating', self.api_error(self.image_path, duplicate)['error'])
                self.api(f'/api/saves/{self.save_id}/messages', {'playerId': self.player, 'text': 'I step inside.'})
                moved = self.api(f'/api/saves/{self.save_id}/advance', {'override': True, 'playerId': self.player})
                self.assertEqual(moved['save']['beat'], before['save']['beat']+1)
                self.assertEqual(moved['activity']['aiDm'], None)
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        image = results[0]['images'][0]
        self.assertEqual(image['source_message_id'], self.payload['sourceMessageId'])
        self.api(self.image_path+'/'+image['id']+'/share', self.payload)
        state = self.api(f'/api/saves/{self.save_id}')
        self.assertEqual(state['save']['beat'], moved['save']['beat'])
        self.assertEqual(state['players'], moved['players'])

    def test_validates_pilot_source_player_and_key_before_provider(self):
        self.prepare()
        with patch.object(scene_images, 'generate') as provider:
            for changes in ({'pilot': False}, {'sourceMessageId': -1}, {'playerId': 'missing'},
                            {'requestId': '../bad'}, {'direction': 'x'*2001}):
                self.api_error(self.image_path, dict(self.payload, **changes))
            with patch.dict(os.environ, {'TABLEFORGE_OPENAI_API_KEY': ''}):
                self.assertIn('API_KEY', self.api_error(self.image_path, self.payload)['error'])
            provider.assert_not_called()

    def test_restart_recovers_pending_and_preserves_completed_drafts(self):
        self.prepare()
        image, _ = self.generate()
        with server.db() as conn:
            conn.execute("UPDATE scene_images SET status='generating' WHERE id=?", (image['id'],))
        server.initialize()
        rows = self.api(self.image_path+'?playerId='+self.player)['images']
        self.assertEqual(rows[0]['status'], 'failed')
        self.assertIn('restarted', rows[0]['error'])
        self.payload['requestId'] = str(uuid.uuid4())
        draft, _ = self.generate()
        server.initialize()
        self.assertEqual(self.api(self.image_path+'?playerId='+self.player)['images'][-1]['status'], 'draft')
        self.api(self.image_path+'/'+draft['id']+'/share', self.payload)


del _FlowTest


class ImageProviderTest(unittest.TestCase):
    def test_payload_decoding_and_usage(self):
        raw = {'data': [{'b64_json': base64.b64encode(JPEG).decode()}],
               'usage': {'input_tokens': 100, 'output_tokens': 200}}
        with patch.dict(os.environ, {'TABLEFORGE_OPENAI_API_KEY': 'test-key'}), patch.object(
                scene_images.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(raw).encode())) as call:
            result = scene_images.generate('An empty courtyard.', scene_images.DEFAULT_MODEL)
        payload = json.loads(call.call_args.args[0].data)
        self.assertEqual((payload['quality'], payload['output_format'], payload['size'], payload['n']),
                         ('low', 'jpeg', '1536x1024', 1))
        self.assertEqual(result.data, JPEG)
        self.assertEqual(result.usage, raw['usage'])

    def test_errors_do_not_echo_api_keys_or_retry(self):
        error = urllib.error.HTTPError('https://api.openai.com', 401, 'Unauthorized', {}, io.BytesIO(b'test-key'))
        with patch.dict(os.environ, {'TABLEFORGE_OPENAI_API_KEY': 'test-key'}), patch.object(
                scene_images.urllib.request, 'urlopen', side_effect=error) as call:
            with self.assertRaisesRegex(ValueError, 'key was rejected'):
                scene_images.generate('test', scene_images.DEFAULT_MODEL)
            self.assertEqual(call.call_count, 1)

    def test_invalid_image_and_unknown_cost(self):
        with patch.dict(os.environ, {'TABLEFORGE_OPENAI_API_KEY': 'test-key'}), patch.object(
                scene_images.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"data":[{"b64_json":"bm90LWpwZWc="}]}')):
            with self.assertRaisesRegex(ValueError, 'JPEG'):
                scene_images.generate('test', scene_images.DEFAULT_MODEL)
        self.assertIsNone(metering.image_cost('unlisted-model', {'input_tokens': 100, 'output_tokens': 200}))
        self.assertIsNone(metering.image_cost(scene_images.DEFAULT_MODEL, {}))
