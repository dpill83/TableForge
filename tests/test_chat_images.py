"""Player chat images are stored with the save and omitted from AI-DM context."""
import base64
import json
import unittest
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch

import ai
import server
from test_flow import FakeProvider, FlowTest as _FlowTest


JPEG = b'\xff\xd8\xff\xe0test-image\xff\xd9'
JPEG_OTHER = b'\xff\xd8\xff\xe0other-image\xff\xd9'


class ChatImageFlowTest(unittest.TestCase):
    setUp = _FlowTest.setUp
    tearDown = _FlowTest.tearDown
    api = _FlowTest.api
    api_error = _FlowTest.api_error
    ready_save = _FlowTest.ready_save
    override = _FlowTest.override

    def prepare(self):
        save_id = self.ready_save()
        state = self.api(f'/api/saves/{save_id}')
        self.save_id = save_id
        self.first, self.second = [player['id'] for player in state['players']]
        return state

    def send(self, extra=None, player=None, text='', image=JPEG):
        payload = {'playerId': player or self.first, 'text': text}
        if image is not None:
            payload['image'] = {'mime': 'image/jpeg', 'data': base64.b64encode(image).decode()}
        if extra:
            payload.update(extra)
        return self.api(f'/api/saves/{self.save_id}/messages', payload)

    def test_image_only_send_stores_bytes_and_marks_ready(self):
        before = self.prepare()
        self.api(f'/api/saves/{self.save_id}/ready', {'playerId': self.first, 'ready': False})
        posted = self.send()
        message = posted['messages'][-1]
        self.assertEqual(message['kind'], 'player')
        self.assertEqual(message['body'], '')
        self.assertTrue(posted['players'][0]['ready'])
        [attachment] = posted['attachments']
        self.assertEqual(attachment['messageId'], message['id'])
        self.assertEqual(attachment['mime'], 'image/jpeg')
        self.assertNotIn('image', attachment)
        path = f'/api/saves/{self.save_id}/attachments/{attachment["id"]}'
        with urllib.request.urlopen(self.base + path) as response:
            self.assertEqual(response.headers['Content-Type'], 'image/jpeg')
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(response.read(), JPEG)
        server.initialize()
        restored = self.api(f'/api/saves/{self.save_id}')
        self.assertEqual(restored['attachments'], posted['attachments'])
        with urllib.request.urlopen(self.base + path) as response:
            self.assertEqual(response.read(), JPEG)
        self.assertEqual(len(restored['messages']), len(before['messages']) + 1)

    def test_caption_is_in_context_and_image_only_messages_are_not(self):
        self.prepare()
        self.send(text='A sketch of the door.', image=JPEG)
        self.send(player=self.second, image=JPEG_OTHER)
        fake = FakeProvider()
        with patch.object(ai, 'current_provider', return_value=fake):
            self.api(f'/api/saves/{self.save_id}/advance', {'beat': 1})
        names_and_bodies = [(item['name'], item['body']) for item in fake.context['messages']]
        self.assertIn(('George', 'A sketch of the door.'), names_and_bodies)
        self.assertNotIn(('Ethereal', ''), names_and_bodies)
        self.assertFalse(any(item['body'] == '' for item in fake.context['messages']))
        payload = json.dumps(ai.chat_messages(fake.context))
        self.assertIn('A sketch of the door.', payload)
        self.assertNotIn(base64.b64encode(JPEG).decode(), payload)
        self.assertNotIn('test-image', payload)
        state = self.api(f'/api/saves/{self.save_id}')
        self.assertFalse(any(m['kind'] == 'image' for m in ai.summary_range(state['messages'])))
        self.assertFalse(any(not (m.get('body') or '').strip() for m in ai.context_messages(state['messages'])))

    def test_invalid_uploads_are_rejected(self):
        self.prepare()
        path = f'/api/saves/{self.save_id}/messages'
        bad_type = self.api_error(path, {'playerId': self.first, 'image': {
            'mime': 'image/gif', 'data': base64.b64encode(JPEG).decode()}})
        self.assertIn('PNG, JPEG, or WebP', bad_type['error'])
        bad_bytes = self.api_error(path, {'playerId': self.first, 'image': {
            'mime': 'image/jpeg', 'data': base64.b64encode(b'not an image').decode()}})
        self.assertIn('invalid', bad_bytes['error'])
        with patch.object(server, 'MAX_CHAT_IMAGE_BYTES', 10):
            oversize = self.api_error(path, {'playerId': self.first, 'image': {
                'mime': 'image/jpeg', 'data': base64.b64encode(JPEG).decode()}})
        self.assertTrue('20 MB' in oversize['error'] or 'invalid' in oversize['error'])
        restored = self.api(f'/api/saves/{self.save_id}')
        self.assertEqual(restored['attachments'], [])
        self.assertEqual(restored['messages'][-1]['body'], 'I look ahead.')

    def test_retried_request_id_does_not_duplicate_or_accept_a_different_image(self):
        self.prepare()
        request_id = str(uuid.uuid4())
        send = {'playerId': self.first, 'text': 'Look at this.', 'beat': 1, 'requestId': request_id,
                'image': {'mime': 'image/jpeg', 'data': base64.b64encode(JPEG).decode()}}
        first = self.api(f'/api/saves/{self.save_id}/messages', send)
        again = self.api(f'/api/saves/{self.save_id}/messages', send)
        self.assertEqual(len(again['messages']), len(first['messages']))
        self.assertEqual(again['attachments'], first['attachments'])
        different = {**send, 'image': {'mime': 'image/jpeg', 'data': base64.b64encode(JPEG_OTHER).decode()}}
        self.assertIn('different message', self.api_error(f'/api/saves/{self.save_id}/messages', different)['error'])
        self.assertIn('different message', self.api_error(f'/api/saves/{self.save_id}/messages', {**send, 'text': 'Edited.'})['error'])

    def test_stale_beat_rejects_an_image_without_posting(self):
        self.prepare()
        self.api(f'/api/saves/{self.save_id}/advance', self.override(self.save_id, beat=1))
        error = self.api_error(f'/api/saves/{self.save_id}/messages', {
            'playerId': self.first, 'beat': 1,
            'image': {'mime': 'image/jpeg', 'data': base64.b64encode(JPEG).decode()}})
        self.assertEqual(error['code'], 'stale_beat')
        restored = self.api(f'/api/saves/{self.save_id}')
        self.assertEqual(restored['attachments'], [])
        self.assertEqual([m['kind'] for m in restored['messages']], ['player', 'ai'])


if __name__ == '__main__':
    unittest.main()
