"""Privacy boundaries for player-owned operational conversations."""
import json
import unittest
from unittest.mock import patch

import ai
import server
import test_flow as flow
from test_flow import FakeProvider, BoomProvider


class PrivateAskTest(unittest.TestCase):
    setUp = flow.FlowTest.setUp
    tearDown = flow.FlowTest.tearDown
    api = flow.FlowTest.api
    api_error = flow.FlowTest.api_error
    ready_save = flow.FlowTest.ready_save

    def private_thread(self, save_id, player_id):
        return self.api(f'/api/saves/{save_id}/ask?playerId={player_id}&pilot=true')['pilot']

    def ask(self, save_id, player_id, text, reply):
        provider = FakeProvider(reply)
        with patch.object(ai, 'current_provider', return_value=provider):
            result = self.api(f'/api/saves/{save_id}/ask',
                              {'playerId': player_id, 'pilot': True, 'text': text})
        return result, provider.context

    def test_questions_replies_context_and_request_logs_are_player_scoped(self):
        save_id = self.ready_save()
        before = self.api(f'/api/saves/{save_id}')
        first, second = [p['id'] for p in before['players']]
        dan, _ = self.ask(save_id, first, 'Dan private question', 'Dan private answer')
        self.assertEqual(dan['pilot'][0]['name'], 'Dan')
        self.assertEqual(dan['pilot'][1]['name'], 'AI-DM')
        self.assertTrue(all(m['created_at'] and m['thread_player_id'] == first for m in dan['pilot']))
        self.assertEqual(self.private_thread(save_id, second), [])
        dani, context = self.ask(save_id, second, 'Dani private question', 'Dani private answer')
        self.assertEqual(dani['pilot'][0]['name'], 'Dani')
        self.assertNotIn('Dan private', json.dumps(context))
        again, context = self.ask(save_id, first, 'Dan follow-up', 'Dan follow-up answer')
        self.assertIn('Dan private answer', json.dumps(ai.chat_messages(context)))
        self.assertNotIn('Dani private', json.dumps(context))
        self.assertIn('I look ahead.', json.dumps(context))  # Shared table background remains available.
        self.assertEqual(len(again['pilot']), 4)
        self.assertEqual(len(self.private_thread(save_id, second)), 2)
        public = self.api(f'/api/saves/{save_id}')
        self.assertEqual(public['pilot'], [])
        self.assertNotIn('private question', json.dumps(public))
        self.assertNotIn('private question', json.dumps(self.api(f'/api/saves/{save_id}/context')))
        self.assertEqual(public['messages'], before['messages'])
        self.assertEqual(public['save']['beat'], before['save']['beat'])
        self.assertEqual(public['players'], before['players'])
        # Exercise temporary captures as well as persisted request metadata.
        with server.db() as conn:
            rows = conn.execute('SELECT id,player_id FROM ai_requests WHERE save_id=?', (save_id,)).fetchall()
        server.AI_REQUEST_LOGS[save_id] = [
            {'id': row['id'], 'payload': 'private payload ' + row['player_id']} for row in rows]
        for owner, other, count in ((first, second, 2), (second, first, 1)):
            log = self.api(f'/api/saves/{save_id}/request-log?playerId={owner}&pilot=true')['entries']
            self.assertEqual(len(log), count)
            self.assertNotIn(other, json.dumps(log))
            self.assertTrue(all(entry['payload'] == 'private payload ' + owner for entry in log))
        server.AI_REQUEST_LOGS.clear()
        server.initialize()
        self.assertEqual(self.private_thread(save_id, first), again['pilot'])
        self.assertEqual(len(self.api(f'/api/saves/{save_id}/request-log?playerId={second}&pilot=true')['entries']), 1)
        backup = self.api('/api/backups', {})
        self.ask(save_id, first, 'After backup', 'After backup reply')
        self.api(f'/api/backups/{backup["name"]}/restore', {})
        self.assertEqual(self.private_thread(save_id, first), again['pilot'])
        self.assertEqual(self.private_thread(save_id, second), dani['pilot'])

    def test_private_routes_require_pilot_mode_and_a_player_from_this_save(self):
        save_id = self.ready_save()
        first = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        other_save = self.ready_save()
        foreign = self.api(f'/api/saves/{other_save}')['players'][0]['id']
        for owner in (None, 'absent', foreign):
            self.assertIn('error', self.api_error(f'/api/saves/{save_id}/ask?playerId={owner}&pilot=true'))
            self.assertIn('error', self.api_error(f'/api/saves/{save_id}/ask',
                                                {'playerId': owner, 'pilot': True, 'text': 'Question'}))
        self.assertIn('Pilot Mode', self.api_error(f'/api/saves/{save_id}/ask?playerId={first}')['error'])
        self.assertIn('Pilot Mode', self.api_error(f'/api/saves/{save_id}/ask',
                                                 {'playerId': first, 'text': 'Question'})['error'])
        self.assertEqual(self.private_thread(save_id, first), [])

    def test_legacy_shared_rows_are_preserved_without_guessing_private_ownership(self):
        save_id = self.ready_save()
        first, second = [p['id'] for p in self.api(f'/api/saves/{save_id}')['players']]
        with server.db() as conn:
            conn.execute('DROP INDEX pilot_thread')
            conn.execute('ALTER TABLE pilot_messages DROP COLUMN thread_player_id')
            conn.execute('ALTER TABLE ai_requests DROP COLUMN player_id')
            conn.execute('INSERT INTO pilot_messages (save_id,player_id,kind,name,body,created_at) VALUES (?,?,?,?,?,?)',
                         (save_id, first, 'pilot', 'George', 'Old shared question', server.utc()))
            conn.execute('INSERT INTO pilot_messages (save_id,kind,name,body,created_at) VALUES (?,?,?,?,?)',
                         (save_id, 'ai', 'AI-DM', 'Old shared answer', server.utc()))
        server.initialize()
        server.initialize()
        for owner in (first, second):
            self.assertEqual(self.private_thread(save_id, owner), [])
        _, context = self.ask(save_id, first, 'New question', 'New answer')
        self.assertNotIn('Old shared', json.dumps(context))
        with server.db() as conn:
            archive = [dict(row) for row in conn.execute(
                'SELECT * FROM pilot_messages WHERE thread_player_id IS NULL')]
        self.assertEqual([row['body'] for row in archive], ['Old shared question', 'Old shared answer'])
        self.assertEqual(archive[0]['name'], 'George')

    def test_failed_question_survives_restart_only_in_its_owner_thread(self):
        save_id = self.ready_save()
        first, second = [p['id'] for p in self.api(f'/api/saves/{save_id}')['players']]
        with patch.object(ai, 'current_provider', return_value=BoomProvider()):
            self.api_error(f'/api/saves/{save_id}/ask',
                           {'playerId': first, 'pilot': True, 'text': 'Failed private question'})
        server.initialize()
        self.assertEqual([m['body'] for m in self.private_thread(save_id, first)], ['Failed private question'])
        self.assertEqual(self.private_thread(save_id, second), [])
        self.assertEqual(self.api(f'/api/saves/{save_id}')['pilot'], [])
        _, context = self.ask(save_id, first, 'Follow-up', 'Recovered answer')
        self.assertIn('Failed private question', json.dumps(context))


if __name__ == '__main__':
    unittest.main()
