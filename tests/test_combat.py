"""Combat handoff state, concurrency, and recovery without paid AI calls."""
import concurrent.futures
import unittest
import uuid
from unittest.mock import patch

import ai
import combat
import server
import test_flow


class MarkerTest(unittest.TestCase):
    def test_only_standalone_final_marker_operates(self):
        self.assertEqual(combat.extract('Roll initiative.\n'+combat.MARKER), ('Roll initiative.', True))
        for text in ('Roll initiative; combat is yours.', 'Example: '+combat.MARKER,
                     '> '+combat.MARKER, '```\n'+combat.MARKER,
                     combat.MARKER+'\nMore prose.', '~~~text\n'+combat.MARKER):
            with self.subTest(text=text):
                self.assertFalse(combat.extract(text)[1])


class CombatFlowTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    ready_save = test_flow.FlowTest.ready_save
    override = test_flow.FlowTest.override

    def enter(self, automatic=False):
        save_id = self.ready_save()
        if automatic:
            with patch('ai.current_provider', return_value=test_flow.FakeProvider(
                    'Roll initiative at the table; combat is yours.\n'+combat.MARKER)):
                state = self.api(f'/api/saves/{save_id}/advance', {})
        else:
            player = self.api(f'/api/saves/{save_id}')['players'][0]['id']
            state = self.api(f'/api/saves/{save_id}/mode', {'mode': 'combat', 'playerId': player})
        return save_id, state

    def finish(self, save_id, state):
        for player in state['players']:
            state = self.api(f'/api/saves/{save_id}/ready', {'playerId': player['id'], 'ready': True,
                                                         'handoffId': state['combat']['id']})
        return state

    def payload(self, state, **extra):
        return {'handoffId': state['combat']['id'], 'requestId': str(uuid.uuid4()),
                'playerId': state['players'][0]['id'], 'text': 'The ogre fled; nobody died.', **extra}

    def test_entry_resets_ready_and_blocks_contributions(self):
        save_id, state = self.enter(automatic=True)
        self.assertEqual(state['save']['mode'], 'combat')
        self.assertEqual(state['combat']['phase'], 'fighting')
        self.assertFalse(any(p['ready'] for p in state['players']))
        self.assertNotIn(combat.MARKER, state['messages'][-1]['body'])
        self.assertEqual(state['events'][-1]['kind'], 'combat_started')
        self.assertIn('Combat is at the table', self.api_error(f'/api/saves/{save_id}/messages',
            {'playerId': state['players'][0]['id'], 'text': 'I attack.'})['error'])
        self.assertIn('Resume combat', self.api_error(f'/api/saves/{save_id}/advance', {})['error'])
        state = self.finish(save_id, state)
        self.assertEqual(state['combat']['phase'], 'outcome_pending')
        self.assertIn('Combat has changed', self.api_error(f'/api/saves/{save_id}/ready',
            {'playerId': state['players'][0]['id'], 'ready': True})['error'])
        state = self.api(f'/api/saves/{save_id}/ready', {'playerId': state['players'][0]['id'], 'ready': False,
                                                     'handoffId': state['combat']['id']})
        self.assertEqual(state['combat']['phase'], 'fighting')
        self.assertIn('Waiting for everyone', self.api_error(f'/api/saves/{save_id}/combat-outcome',
            self.payload(state))['error'])

    def test_report_resumes_once_and_is_attributed(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        payload = self.payload(state)
        provider = test_flow.FakeProvider('The ogre disappears into the forest.')
        before = len(state['messages'])
        with patch('ai.current_provider', return_value=provider) as factory:
            after = self.api(f'/api/saves/{save_id}/combat-outcome', payload)
            duplicate = self.api(f'/api/saves/{save_id}/combat-outcome', payload)
            rival = self.api(f'/api/saves/{save_id}/combat-outcome',
                            self.payload(state, playerId=state['players'][1]['id']))
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(len(after['messages']), before+1)
        self.assertEqual(len(duplicate['messages']), before+1)
        self.assertEqual(len(rival['messages']), before+1)
        self.assertEqual(after['combat']['phase'], 'complete')
        self.assertEqual(after['combat']['message_id'], after['messages'][-1]['id'])
        self.assertEqual(after['combat']['player_id'], payload['playerId'])
        events = [e for e in after['events'] if e['kind'] == 'combat_outcome']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['body'], payload['text'])
        self.assertFalse(any(p['ready'] for p in after['players']))
        self.assertIn(payload['text'], ai.chat_messages(provider.context)[0]['content'])

    def test_skip_uses_missing_results_instruction_and_override_is_explicit(self):
        save_id, state = self.enter()
        provider = test_flow.FakeProvider()
        payload = self.payload(state, skip=True, text='', override=True)
        self.assertIn('Pilot Mode', self.api_error(f'/api/saves/{save_id}/combat-outcome', payload)['error'])
        with patch('ai.current_provider', return_value=provider):
            after = self.api(f'/api/saves/{save_id}/combat-outcome', {**payload, 'pilot': True})
        self.assertTrue(after['combat']['skipped'])
        self.assertEqual(after['events'][-2]['kind'], 'combat_skipped')
        self.assertEqual(after['events'][-1]['kind'], 'combat_override')
        instructions = ai.chat_messages(provider.context)[0]['content']
        self.assertIn('No outcome was supplied', instructions)
        self.assertIn('do not invent deaths', instructions)

    def test_failure_preserves_result_preview_and_restart_retry(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        payload = self.payload(state)
        with patch('ai.current_provider', return_value=test_flow.BoomProvider()):
            self.assertIn('provider down', self.api_error(f'/api/saves/{save_id}/combat-outcome', payload)['error'])
        failed = self.api(f'/api/saves/{save_id}')
        self.assertEqual(failed['combat']['phase'], 'failed')
        self.assertEqual(failed['combat']['outcome'], payload['text'])
        self.assertNotIn(save_id, server.GENERATING)
        self.assertIn('combat aftermath', self.api_error(f'/api/saves/{save_id}/messages',
            {'playerId': payload['playerId'], 'text': 'Hello'})['error'])
        preview = self.api(f'/api/saves/{save_id}/context')
        with server.db() as conn:
            conn.execute("UPDATE combat_handoffs SET phase='resuming' WHERE id=?", (payload['handoffId'],))
        server.initialize()
        provider = test_flow.FakeProvider('Aftermath.')
        with patch('ai.current_provider', return_value=provider):
            after = self.api(f'/api/saves/{save_id}/combat-retry', payload)
        self.assertEqual(after['combat']['phase'], 'complete')
        self.assertEqual(preview['messages'], ai.chat_messages(provider.context))
        self.assertEqual(len([e for e in after['events'] if e['kind']=='combat_outcome']), 1)

    def test_two_submissions_and_ask_cannot_generate_together(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        provider = test_flow.GateProvider('Aftermath.')
        with patch('ai.current_provider', return_value=provider), concurrent.futures.ThreadPoolExecutor() as pool:
            running = pool.submit(self.api, f'/api/saves/{save_id}/combat-outcome', self.payload(state))
            self.assertTrue(provider.started.wait(3))
            try:
                duplicate = self.api(f'/api/saves/{save_id}/combat-outcome',
                    self.payload(state, playerId=state['players'][1]['id'], text='Different report'))
                self.assertEqual(duplicate['combat']['phase'], 'resuming')
                self.assertIn('already responding', self.api_error(f'/api/saves/{save_id}/ask',
                    {'pilot': True, 'playerId': state['players'][0]['id'], 'text': 'A ruling?'})['error'])
            finally:
                provider.release.set()
            after = running.result(timeout=5)
        self.assertEqual(after['combat']['phase'], 'complete')
        self.assertEqual(len([e for e in after['events'] if e['kind']=='combat_outcome']), 1)

    def test_migration_stale_handoff_and_pinned_prompt(self):
        save_id, state = self.enter()
        pinned = self.api(f'/api/saves/{save_id}/context')['report']['narrationPrompt']
        with server.db() as conn:
            conn.execute('DELETE FROM combat_handoffs WHERE save_id=?', (save_id,))
        server.initialize()
        migrated = self.api(f'/api/saves/{save_id}')
        self.assertEqual(migrated['combat']['phase'], 'fighting')
        self.assertEqual(state['messages'], migrated['messages'])
        self.assertEqual(state['events'], migrated['events'])
        self.assertIn('no longer current', self.api_error(f'/api/saves/{save_id}/combat-outcome',
            self.payload(state))['error'])
        self.assertEqual(pinned, self.api(f'/api/saves/{save_id}/context')['report']['narrationPrompt'])

    def test_ask_reply_never_enters_combat(self):
        save_id = self.ready_save()
        before = self.api(f'/api/saves/{save_id}')
        with patch('ai.current_provider', return_value=test_flow.FakeProvider('Example\n'+combat.MARKER)):
            after = self.api(f'/api/saves/{save_id}/ask',
                {'pilot': True, 'playerId': before['players'][0]['id'], 'text': 'What is initiative?'})
        self.assertEqual(after['save']['mode'], 'normal')
        self.assertIsNone(after['combat'])
        self.assertEqual(after['messages'], before['messages'])

    def test_new_session_resets_finished_handoff(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        player_id = state['players'][0]['id']
        self.api(f'/api/saves/{save_id}/end-session', {'playerId': player_id})
        after = self.api(f'/api/saves/{save_id}/start-session', {'playerId': player_id})
        self.assertEqual(after['combat']['phase'], 'fighting')
        self.assertEqual(after['save']['mode'], 'combat')
        self.assertFalse(any(p['ready'] for p in after['players']))


if __name__ == '__main__':
    unittest.main()
