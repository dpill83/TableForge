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
        return self.api(f'/api/saves/{save_id}/combat-report', {
            'playerId': state['players'][0]['id'], 'handoffId': state['combat']['id'],
            'action': 'claim', 'editorToken': 'editor-one', 'revision': state['combat']['revision']})

    def payload(self, state, **extra):
        return {'handoffId': state['combat']['id'], 'requestId': str(uuid.uuid4()),
                'playerId': state['players'][0]['id'], 'editorToken': 'editor-one',
                'revision': state['combat']['revision'], 'text': 'The ogre fled; nobody died.', **extra}

    def test_entry_resets_ready_and_blocks_contributions(self):
        save_id, state = self.enter(automatic=True)
        self.assertEqual(state['save']['mode'], 'combat')
        self.assertEqual(state['combat']['phase'], 'fighting')
        self.assertFalse(any(p['ready'] for p in state['players']))
        self.assertNotIn(combat.MARKER, state['messages'][-1]['body'])
        self.assertEqual(state['events'][-1]['kind'], 'combat_started')
        self.assertIn('Combat is at the table', self.api_error(f'/api/saves/{save_id}/messages',
            {'playerId': state['players'][0]['id'], 'editorToken': 'editor-one',
                'revision': state['combat']['revision'], 'text': 'I attack.'})['error'])
        self.assertIn('Resume combat', self.api_error(f'/api/saves/{save_id}/advance', {})['error'])
        state = self.finish(save_id, state)
        self.assertEqual(state['combat']['phase'], 'reporting')
        self.assertIn('replaces Ready', self.api_error(f'/api/saves/{save_id}/ready',
            {'playerId': state['players'][0]['id'], 'ready': True})['error'])
        self.assertIn('ownership changed', self.api_error(f'/api/saves/{save_id}/combat-outcome',
            self.payload(state, playerId=state['players'][1]['id']))['error'])

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

    def test_blank_and_skip_are_rejected_without_advancing(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        for extra in ({'text': ''}, {'text': 'Something', 'skip': True}, {'text': '   '}):
            self.assertIn('Combat outcome', self.api_error(f'/api/saves/{save_id}/combat-outcome',
                          self.payload(state, **extra))['error'])
        self.assertEqual(self.api(f'/api/saves/{save_id}')['save']['mode'], 'combat')

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
        self.assertIn('Combat is at the table', self.api_error(f'/api/saves/{save_id}/messages',
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
                    {'pilot': True, 'playerId': state['players'][0]['id'], 'editorToken': 'editor-one',
                'revision': state['combat']['revision'], 'text': 'A ruling?'})['error'])
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

    def test_new_session_preserves_reporter_and_draft(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        player_id = state['players'][0]['id']
        self.api(f'/api/saves/{save_id}/end-session', {'playerId': player_id})
        after = self.api(f'/api/saves/{save_id}/start-session', {'playerId': player_id})
        self.assertEqual(after['combat']['phase'], 'reporting')
        self.assertEqual(after['save']['mode'], 'combat')
        self.assertFalse(any(p['ready'] for p in after['players']))

    def test_multiplayer_claim_autosave_takeover_and_stale_tabs(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        payload = self.payload(state)
        draft = {**payload, 'action': 'draft', 'text': 'The ogre fled; we have not searched.'}
        state = self.api(f'/api/saves/{save_id}/combat-report', draft)
        refreshed = self.api(f'/api/saves/{save_id}')
        self.assertEqual(refreshed['combat']['draft'], draft['text'])
        self.assertEqual(refreshed['combat']['reporter_id'], payload['playerId'])
        self.assertIn('draft changed', self.api_error(f'/api/saves/{save_id}/combat-report', draft)['error'])
        other = state['players'][1]['id']
        self.assertIn('already recording', self.api_error(f'/api/saves/{save_id}/combat-report',
            {**draft, 'action': 'claim', 'playerId': other})['error'])
        state = self.api(f'/api/saves/{save_id}/combat-report', {**draft, 'action': 'takeover',
            'playerId': other, 'editorToken': 'editor-two', 'revision': state['combat']['revision']})
        self.assertEqual(state['combat']['draft'], draft['text'])
        for action in ('draft', 'return'):
            self.assertIn('ownership changed', self.api_error(f'/api/saves/{save_id}/combat-report',
                {**draft, 'action': action, 'revision': state['combat']['revision']})['error'])
        self.assertIn('ownership changed', self.api_error(f'/api/saves/{save_id}/combat-outcome',
            {**payload, 'revision': state['combat']['revision']})['error'])
        owner = {**draft, 'playerId': other, 'editorToken': 'editor-two', 'revision': state['combat']['revision']}
        state = self.api(f'/api/saves/{save_id}/combat-report', {**owner, 'action': 'return'})
        self.assertEqual(state['combat']['phase'], 'fighting')
        self.assertEqual(state['combat']['draft'], draft['text'])
        state = self.finish(save_id, state)
        latest = self.payload(state, text='Latest edit: ogre surrendered, still deciding what to do.')
        with patch('ai.current_provider', return_value=test_flow.FakeProvider('Aftermath.')):
            state = self.api(f'/api/saves/{save_id}/combat-outcome', latest)
        self.assertEqual(state['combat']['outcome'], latest['text'])
        self.assertEqual(state['combat']['draft'], latest['text'])
        state = self.api(f'/api/saves/{save_id}/mode', {'mode': 'combat', 'playerId': other})
        self.assertEqual(state['combat']['draft'], '')
        self.assertIn('no longer current', self.api_error(f'/api/saves/{save_id}/combat-report', draft)['error'])
        self.assertIn('no longer current', self.api_error(f'/api/saves/{save_id}/combat-outcome', latest)['error'])

    def test_simultaneous_claim_has_one_winner(self):
        save_id, state = self.enter()
        def claim(player):
            try:
                return self.api(f'/api/saves/{save_id}/combat-report', {
                    **self.payload(state, playerId=player['id']), 'action': 'claim'})
            except Exception:
                return None
        with concurrent.futures.ThreadPoolExecutor() as pool:
            results = list(pool.map(claim, state['players']))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_stall_retry_and_late_response_publish_only_once(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        payload = self.payload(state)
        stalled = test_flow.GateProvider('Late obsolete aftermath.')
        try:
            with patch('server.COMBAT_GENERATION_TIMEOUT', 0.03), patch('ai.current_provider', return_value=stalled):
                self.assertIn('stalled', self.api_error(f'/api/saves/{save_id}/combat-outcome', payload)['error'])
            failed = self.api(f'/api/saves/{save_id}')
            self.assertEqual(failed['combat']['phase'], 'failed')
            provider = test_flow.GateProvider('Accepted aftermath.')
            with patch('ai.current_provider', return_value=provider), concurrent.futures.ThreadPoolExecutor() as pool:
                retry = pool.submit(self.api, f'/api/saves/{save_id}/combat-retry', {**payload, 'playerId': state['players'][1]['id']})
                self.assertTrue(provider.started.wait(3))
                duplicate = self.api(f'/api/saves/{save_id}/combat-retry', payload)
                self.assertEqual(duplicate['combat']['phase'], 'resuming')
                stalled.release.set()
                provider.release.set()
                after = retry.result(timeout=5)
            self.assertEqual(after['messages'][-1]['body'], 'Accepted aftermath.')
            self.assertEqual(len(after['messages']), len(state['messages'])+1)
        finally:
            stalled.release.set()

    def test_pilot_correction_preserves_original_and_does_not_replay(self):
        save_id, state = self.enter()
        state = self.finish(save_id, state)
        payload = self.payload(state)
        with patch('ai.current_provider', return_value=test_flow.FakeProvider('Aftermath.')):
            after = self.api(f'/api/saves/{save_id}/combat-outcome', payload)
        correction = {**payload, 'text': 'The ogre surrendered rather than fled.'}
        self.assertIn('Pilot Mode', self.api_error(f'/api/saves/{save_id}/combat-correction', correction)['error'])
        provider = test_flow.FakeProvider('Correction noted; the ogre surrendered.')
        with patch('ai.current_provider', return_value=provider):
            corrected = self.api(f'/api/saves/{save_id}/combat-correction', {**correction, 'pilot': True})
        self.assertEqual(corrected['messages'], after['messages'])
        self.assertEqual(corrected['combat']['outcome'], payload['text'])
        self.assertEqual(corrected['save']['beat'], after['save']['beat'])
        self.assertIn(correction['text'], corrected['events'][-1]['body'])
        self.assertIn(correction['text'], self.api(f'/api/saves/{save_id}/context')['messages'][0]['content'])
        self.assertIn('do not replay', ai.chat_messages(provider.context)[-1]['content'])


if __name__ == '__main__':
    unittest.main()
