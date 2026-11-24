"""Public questions preserve runtime state, privacy, and request identity."""
import base64
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import ai
import public_questions
import server
import test_flow


class PublicQuestionsTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    ready_save = test_flow.FlowTest.ready_save
    override = test_flow.FlowTest.override

    def question(self, save_id, player, text, request_id=None):
        return self.api(f'/api/saves/{save_id}/public-question',
                        {'playerId': player, 'text': text, 'requestId': request_id or str(uuid.uuid4())})

    def wait(self, save_id, count=1, status='complete'):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.api(f'/api/saves/{save_id}')
            questions = [m for m in state['messages'] if m.get('ooc')]
            if len(questions) == count and all(m['ooc']['status'] == status for m in questions):
                return state
            time.sleep(.02)
        self.fail('Public questions did not settle')

    def test_public_question_has_no_action_or_ready_side_effects(self):
        sid = self.ready_save('# SECRET: a trap behind the closed door')
        before = self.api(f'/api/saves/{sid}')
        pid = before['players'][0]['id']
        provider = test_flow.FakeProvider('Describe searching the door; a roll may be needed.')
        with patch('ai.current_provider', return_value=provider):
            self.question(sid, pid, 'Would checking it for traps require a roll?')
            after = self.wait(sid)
        self.assertEqual(before['players'], after['players'])
        self.assertEqual(before['save']['beat'], after['save']['beat'])
        self.assertEqual(before['combat'], after['combat'])
        self.assertEqual([m for m in after['messages'] if m['kind'] != 'ooc'], before['messages'])
        self.assertNotIn('SECRET', str(ai.chat_messages(provider.context)))
        self.assertNotIn('I look ahead.', str(provider.context))  # pending IC declaration
        with server.db() as conn:
            context = ai.build_context(server.snapshot(conn, sid), server.DATA)
        self.assertFalse(any(m['kind'] == 'ooc' for m in context['messages']))
        self.assertEqual(context['publicRulings'][0]['answer'], provider.text)
        self.assertIn('NEVER actions', ai.chat_messages(context)[0]['content'])

    def test_visible_condition_ruling_carries_into_pending_check(self):
        sid = self.ready_save('# Hidden trap under the drum')
        scene = 'Ethereal, the captain leads you to the drum. Roll Dexterity (Stealth) to tamper with it.'
        with patch('ai.current_provider', return_value=test_flow.FakeProvider(scene)):
            before = self.api(f'/api/saves/{sid}/advance', {})
        ethereal = before['players'][1]['id']
        question = 'Is it dim light or darkness by the drum? My Stealth has disadvantage otherwise.'
        answer = 'It is dim light by the drum. That feature does not impose disadvantage on this check.'
        dm = test_flow.FakeProvider(answer)
        with patch('ai.current_provider', return_value=dm):
            self.question(sid, ethereal, question)
            after = self.wait(sid)
        prompt = ai.chat_messages(dm.context)[0]['content']
        self.assertIn('make a reasonable, scene-specific DM ruling', prompt)
        self.assertIn('Answer directly on the first request', prompt)
        self.assertIn('Do not perform actions, decide outcomes, roll checks', prompt)
        self.assertIn(scene, prompt)
        self.assertNotIn('Hidden trap under the drum', prompt)
        self.assertEqual(dm.context['character'], 'Ethereal')
        self.assertEqual(after['save']['beat'], before['save']['beat'])
        self.assertEqual(after['players'], before['players'])

        followup = test_flow.FakeProvider('Correct. Roll and report your total.')
        with patch('ai.current_provider', return_value=followup):
            self.question(sid, ethereal, 'Same spot. Does that mean I roll without that disadvantage?')
            self.wait(sid, 2)
        self.assertEqual(followup.context['publicRulings'], [{
            'character': 'Ethereal', 'beat': before['save']['beat'], 'question': question, 'answer': answer,
        }])

        self.api(f'/api/saves/{sid}/messages', {'playerId': ethereal, 'text': 'Stealth total is 15.'})
        narration = test_flow.FakeProvider('You steady your hand by the drum.')
        with patch('ai.current_provider', return_value=narration):
            final = self.api(f'/api/saves/{sid}/advance', self.override(sid))
        system = ai.chat_messages(narration.context)[0]['content']
        self.assertIn(answer, system)
        self.assertIn('including when resolving a reported check', system)
        self.assertFalse(any(m['kind'] == 'ooc' for m in narration.context['messages']))
        self.assertIn('Stealth total is 15.', narration.context['messages'][-1]['body'])
        with patch.object(ai, 'SUMMARY_WINDOW', 0):
            summary = ai.chat_messages(ai.build_summary_context(final))
        self.assertIn('Preserve relevant public DM rulings', summary[0]['content'])
        self.assertIn(answer, summary[1]['content'])

    def test_two_players_scene_advance_and_duplicate_pending_retry(self):
        sid = self.ready_save()
        with patch('ai.current_provider', return_value=test_flow.FakeProvider('A closed door stands ahead.')):
            self.api(f'/api/saves/{sid}/advance', {})
        original = self.api(f'/api/saves/{sid}')
        first, second = [p['id'] for p in original['players']]
        for pid in (first, second):
            self.api(f'/api/saves/{sid}/ready', {'playerId': pid, 'ready': True})
        source = original['messages'][-1]['id']
        started = threading.Event()
        release = threading.Event()
        class Questions:
            def generate(self, context):
                if context['purpose'] == 'ooc':
                    started.set()
                    if not release.wait(4):
                        raise ValueError('Test gate timed out')
                    return 'Answer to ' + context['question']
                return 'The door remains closed.'
        rid = str(uuid.uuid4())
        with patch('ai.current_provider', return_value=Questions()):
            self.question(sid, first, 'Could I open the door?', rid)
            self.assertTrue(started.wait(2))
            self.question(sid, first, 'Could I open the door?', rid)
            self.question(sid, second, 'How do I Help?')
            self.api(f'/api/saves/{sid}/advance', {})
            release.set()
            after = self.wait(sid, 2)
        questions = [m for m in after['messages'] if m.get('ooc')]
        for question in questions:
            self.assertEqual(question['ooc']['answer'], 'Answer to ' + question['body'])
            self.assertEqual(question['ooc']['beat'], original['save']['beat'])
            self.assertEqual(question['ooc']['source_message_id'], source)
        self.assertEqual(after['save']['beat'], original['save']['beat'] + 1)
        self.assertEqual(len(questions), 2)
        # Completed retry returns the same exchange without calling the provider.
        self.question(sid, first, 'Could I open the door?', rid)
        self.assertEqual(len([m for m in self.api(f'/api/saves/{sid}')['messages'] if m.get('ooc')]), 2)

    def test_private_exchange_never_enters_public_answers_or_narration(self):
        sid = self.ready_save('# cartridge secret')
        first, second = [p['id'] for p in self.api(f'/api/saves/{sid}')['players']]
        with patch('ai.current_provider', return_value=test_flow.FakeProvider('PRIVATE REPLY')):
            self.api(f'/api/saves/{sid}/ask', {'playerId': first, 'pilot': True, 'text': 'PRIVATE QUESTION'})
        other = self.api(f'/api/saves/{sid}/ask?playerId={second}&pilot=true')
        self.assertEqual(other['pilot'], [])
        provider = test_flow.FakeProvider('Public answer')
        with patch('ai.current_provider', return_value=provider):
            self.question(sid, second, 'Could I open the door?')
            state = self.wait(sid)
        self.assertNotIn('PRIVATE', str(ai.chat_messages(provider.context)))
        self.assertNotIn('PRIVATE', str(state))
        with server.db() as conn:
            context = ai.build_context(server.snapshot(conn, sid, first), server.DATA)
        self.assertNotIn('PRIVATE', str(ai.chat_messages(context)))

    def test_combat_lock_and_report_remain_intact(self):
        sid = self.ready_save()
        pid = self.api(f'/api/saves/{sid}')['players'][0]['id']
        before = self.api(f'/api/saves/{sid}/mode', {'playerId': pid, 'mode': 'combat'})
        with patch('ai.current_provider', return_value=test_flow.FakeProvider('Explain the rule.')):
            self.question(sid, pid, 'Can I disengage?')
            after = self.wait(sid)
        self.assertEqual(before['combat'], after['combat'])
        self.assertEqual(before['players'], after['players'])
        self.assertEqual(after['save']['mode'], 'combat')
        self.assertIn('Combat', self.api_error(f'/api/saves/{sid}/messages', {'playerId': pid, 'text': 'I attack'})['error'])

    def test_timeout_retry_reuses_exchange_and_rejects_late_worker(self):
        sid = self.ready_save()
        pid = self.api(f'/api/saves/{sid}')['players'][0]['id']
        rid = str(uuid.uuid4())
        gate = test_flow.GateProvider('LATE ANSWER')
        with patch('ai.current_provider', return_value=gate), patch.object(public_questions, 'TIMEOUT', .05):
            self.question(sid, pid, 'Could I open the door?', rid)
            self.wait(sid, status='failed')
        with patch('ai.current_provider', return_value=test_flow.FakeProvider('Retry answer')):
            self.question(sid, pid, 'Could I open the door?', rid)
            self.wait(sid)
        gate.release.set()
        state = self.wait(sid)
        self.assertEqual([m['ooc']['answer'] for m in state['messages'] if m.get('ooc')], ['Retry answer'])

    def test_prefix_only_rejected_and_failed_request_survives_restart(self):
        sid = self.ready_save()
        pid = self.api(f'/api/saves/{sid}')['players'][0]['id']
        self.assertIn('Question', self.api_error(f'/api/saves/{sid}/public-question',
            {'playerId': pid, 'text': 'OOC:', 'requestId': str(uuid.uuid4())})['error'])
        with patch('ai.current_provider', return_value=test_flow.BoomProvider()):
            self.question(sid, pid, 'OOC: Would a roll be needed?')
            state = self.wait(sid, status='failed')
        server.initialize()
        question = next(m for m in state['messages'] if m.get('ooc'))
        with patch('ai.current_provider', return_value=test_flow.FakeProvider('Recovered')):
            self.api(f'/api/saves/{sid}/public-question', {'playerId': pid, 'requestId': question['ooc']['id']})
            self.wait(sid)

    def test_ooc_cannot_authorize_opening_transitions_but_ic_can(self):
        for stage, next_stage, declaration, expected_error in (
                ('decision', 'travel', 'We accept the job and set out.', 'No player accepted'),
                ('arrival', 'exploration', 'I enter the site.', 'No player entered')):
            with self.subTest(stage=stage):
                sid = self.ready_save()
                with patch('ai.current_provider', return_value=test_flow.FakeProvider('The party waits.')):
                    self.api(f'/api/saves/{sid}/advance', {})
                with server.db() as conn:
                    conn.execute('UPDATE saves SET opening_stage=? WHERE id=?', (stage, sid))
                state = self.api(f'/api/saves/{sid}')
                pid = state['players'][0]['id']
                for player in state['players']:
                    self.api(f'/api/saves/{sid}/ready', {'playerId': player['id'], 'ready': True})
                with patch('ai.current_provider', return_value=test_flow.FakeProvider('Explain the attempt only.')):
                    self.question(sid, pid, 'Could we go inside?')
                    before = self.wait(sid)
                candidate = 'The party proceeds.\n[Opening: ' + next_stage + ']'
                with patch('ai.current_provider', return_value=test_flow.FakeProvider(candidate)):
                    error = self.api_error(f'/api/saves/{sid}/advance', {})
                self.assertIn(expected_error, error['error'])
                after = self.api(f'/api/saves/{sid}')
                self.assertEqual(after['messages'], before['messages'])
                self.assertEqual(after['players'], before['players'])
                self.assertEqual(after['save']['beat'], before['save']['beat'])
                self.assertEqual(after['save']['opening_stage'], stage)
                # Real IC intent still authorizes the same transition with OOC in history.
                self.api(f'/api/saves/{sid}/messages', {'playerId': pid, 'text': declaration})
                with patch('ai.current_provider', return_value=test_flow.FakeProvider(candidate)):
                    accepted = self.api(f'/api/saves/{sid}/advance', {})
                self.assertEqual(accepted['save']['opening_stage'], next_stage)

    def test_attachment_retry_and_public_snapshot(self):
        sid = self.ready_save()
        pid = self.api(f'/api/saves/{sid}')['players'][0]['id']
        image = {'mime': 'image/png', 'data': base64.b64encode(b'\x89PNG\r\n\x1a\nimage').decode()}
        payload = {'playerId': pid, 'text': 'What rule is shown?', 'requestId': str(uuid.uuid4()), 'image': image}
        provider = test_flow.FakeProvider('Public explanation')
        with patch('ai.current_provider', return_value=provider):
            self.api(f'/api/saves/{sid}/public-question', payload)
            self.wait(sid)
        repeated = self.api(f'/api/saves/{sid}/public-question', payload)
        self.assertEqual(len(repeated['attachments']), 1)
        self.assertEqual(provider.context['questionImages'], [image])
        self.assertEqual(ai.chat_messages(provider.context)[1]['content'][1]['type'], 'image_url')
        # Questions saved before multi-image support hold a single questionImage.
        legacy = {key: value for key, value in provider.context.items() if key != 'questionImages'}
        legacy['questionImage'] = image
        self.assertEqual(ai.chat_messages(legacy)[1]['content'][1]['image_url']['url'],
                         f"data:image/png;base64,{image['data']}")
        changed = {**payload, 'image': {**image, 'data': base64.b64encode(b'\x89PNG\r\n\x1a\nother').decode()}}
        self.assertIn('another question', self.api_error(f'/api/saves/{sid}/public-question', changed)['error'])

    def test_question_with_several_images_sends_each_to_the_ai(self):
        sid = self.ready_save()
        pid = self.api(f'/api/saves/{sid}')['players'][0]['id']
        images = [{'mime': 'image/png', 'data': base64.b64encode(b'\x89PNG\r\n\x1a\n' + name).decode()}
                  for name in (b'first', b'second')]
        payload = {'playerId': pid, 'text': 'Which of these is the rune?', 'requestId': str(uuid.uuid4()), 'images': images}
        provider = test_flow.FakeProvider('Public explanation')
        with patch('ai.current_provider', return_value=provider):
            result = self.api(f'/api/saves/{sid}/public-question', payload)
            self.wait(sid)
        self.assertEqual([a['position'] for a in result['attachments']], [0, 1])
        content = ai.chat_messages(provider.context)[1]['content']
        self.assertEqual([part['type'] for part in content], ['text', 'image_url', 'image_url'])
        self.assertTrue(content[2]['image_url']['url'].endswith(images[1]['data']))
        swapped = {**payload, 'images': images[::-1]}
        self.assertIn('another question', self.api_error(f'/api/saves/{sid}/public-question', swapped)['error'])


if __name__ == '__main__':
    unittest.main()
