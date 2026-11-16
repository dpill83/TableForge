"""Start Adventure: the explicit "start engine" for a playthrough's first narration."""
import json
import unittest
from unittest.mock import patch

import ai
import test_flow


class StartAdventureTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    cartridge_zip = test_flow.FlowTest.cartridge_zip
    override = test_flow.FlowTest.override

    def new_save(self):
        cartridge = self.cartridge_zip({
            'manifest.json': json.dumps({'format': 'tableforge-adventure', 'formatVersion': 1,
                                         'title': 'Hollow Well', 'resources': {}}),
            'module.md': '# Hollow Well', 'run-data.json': '{"title":"Hollow Well"}',
        })
        return self.api('/api/saves', {'cartridgeId': cartridge['id'], 'players': [
            {'name': 'Dan', 'character': 'George'}, {'name': 'Dani', 'character': 'Ethereal'}]})

    def start(self, save_id, player_id, notes='', text='The well breathes cold air.'):
        provider = test_flow.FakeProvider(text)
        with patch.object(ai, 'current_provider', return_value=provider):
            result = self.api(f'/api/saves/{save_id}/start', {'playerId': player_id, 'notes': notes})
        return result, ai.chat_messages(provider.context)

    def test_new_save_offers_the_default_start_request(self):
        state = self.new_save()
        self.assertIs(state['started'], False)
        self.assertEqual(state['startPrompt'], ai.STAGE3_START_REQUEST)
        preview = self.api(f'/api/saves/{state["save"]["id"]}/context')
        self.assertEqual(preview['messages'][-1], {'role': 'user', 'content': ai.STAGE3_START_REQUEST})

    def test_start_without_notes_sends_default_and_records_who_started(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][1]['id']
        result, messages = self.start(save_id, player)
        self.assertEqual(messages[-1], {'role': 'user', 'content': ai.STAGE3_START_REQUEST})
        self.assertIs(result['started'], True)
        self.assertNotIn('startPrompt', result)
        self.assertEqual([m['kind'] for m in result['messages']], ['ai'])
        started = [e for e in result['events'] if e['kind'] == 'adventure_start']
        self.assertEqual(len(started), 1)
        self.assertEqual((started[0]['player_id'], started[0]['body']), (player, ''))
        self.assertEqual(result['save']['beat'], 2)
        # Nothing to carry forward when the default was used unchanged.
        later = self.api(f'/api/saves/{save_id}/context')
        self.assertNotIn('Table notes given when the adventure began', later['messages'][0]['content'])

    def test_start_notes_reach_the_opening_and_stay_in_later_context(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        notes = 'We are all level 3. Keep the tone light.'
        result, messages = self.start(save_id, player, notes=f'  {notes}  ')
        self.assertTrue(messages[-1]['content'].startswith(ai.STAGE3_START_REQUEST))
        self.assertTrue(messages[-1]['content'].endswith('\n' + notes))
        self.assertEqual([e['body'] for e in result['events'] if e['kind'] == 'adventure_start'], [notes])
        later = self.api(f'/api/saves/{save_id}/context')
        system = later['messages'][0]['content']
        self.assertIn('Table notes given when the adventure began', system)
        self.assertIn(notes, system)
        self.assertNotIn(ai.STAGE3_START_REQUEST, json.dumps(later['messages']))

    def test_player_contributions_before_start_are_honored(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'George is a retired sailor.'})
        _, messages = self.start(save_id, player)
        self.assertEqual(messages[-2], {'role': 'user', 'content': 'George: George is a retired sailor.'})
        self.assertEqual(messages[-1]['content'], ai.STAGE3_START_REQUEST)

    def test_start_is_rejected_once_begun_or_without_a_player(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        self.assertIn('error', self.api_error(f'/api/saves/{save_id}/start', {'notes': ''}))
        long_notes = 'x' * (ai.START_NOTES_LIMIT + 1)
        error = self.api_error(f'/api/saves/{save_id}/start', {'playerId': player, 'notes': long_notes})
        self.assertIn('Starting notes', error['error'])
        self.start(save_id, player)
        error = self.api_error(f'/api/saves/{save_id}/start', {'playerId': player})
        self.assertIn('already begun', error['error'])

    def test_failed_start_saves_nothing_and_can_be_retried(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        with patch.object(ai, 'current_provider', return_value=test_flow.BoomProvider()):
            self.api_error(f'/api/saves/{save_id}/start', {'playerId': player, 'notes': 'Begin at dusk.'})
        state = self.api(f'/api/saves/{save_id}')
        self.assertIs(state['started'], False)
        self.assertFalse([e for e in state['events'] if e['kind'] == 'adventure_start'])
        result, _ = self.start(save_id, player, notes='Begin at dusk.')
        self.assertIs(result['started'], True)


if __name__ == '__main__':
    unittest.main()
