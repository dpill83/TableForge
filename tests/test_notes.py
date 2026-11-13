"""Shared Notes HTTP permissions, revisions, history, and legacy migration."""
import json
import unittest

import ai
import server
import test_flow


class NotesTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    ready_save = test_flow.FlowTest.ready_save

    def test_shared_notes_retries_conflicts_permissions_and_restart(self):
        save_id = self.ready_save()
        path = f'/api/saves/{save_id}/notes'
        before = self.api(f'/api/saves/{save_id}')
        first, second = [p['id'] for p in before['players']]
        create = dict(playerId=first, category='world', title='Loot', body='  NOTE_SECRET: 42 gold\n',
                      clientKey='create-loot', mutationId='create-loot')
        self.assertIn('player', self.api_error(path, {**create, 'playerId': 'stranger'})['error'])
        created = self.api(path, create)
        note = created['notes'][0]
        self.assertEqual(note['body'], create['body'])
        self.assertEqual(created['players'], before['players'])
        self.assertEqual(created['messages'], before['messages'])
        self.assertEqual(created['save']['beat'], before['save']['beat'])
        self.assertEqual(self.api(path, create)['notes'], created['notes'])
        edit = dict(playerId=second, id=note['id'], category='world', revision=note['revision'],
                    title='Party loot', body='NOTE_SECRET: 43 gold', mutationId='edit-loot')
        edited = self.api(path, edit)['notes'][0]
        self.assertEqual((edited['revision'], edited['updated_by']), (2, second))
        self.assertEqual(self.api(path, edit)['notes'][0], edited)
        self.assertEqual(self.api_error(path, {**edit, 'mutationId': 'stale-edit', 'body': 'lost'})['code'], 'note_conflict')
        self.assertEqual(self.api_error(path, {**edit, 'mutationId': 'stale-delete', 'remove': True})['code'], 'note_conflict')
        self.assertEqual(self.api_error(path, create)['code'], 'note_conflict')
        # Even a Pilot must supply a matching revision for shared Notes.
        self.assertEqual(self.api_error(path, {**edit, 'pilot': True, 'mutationId': 'pilot-stale'})['code'], 'note_conflict')
        for category in ('npc', 'location'):
            restricted = dict(playerId=first, category=category, title='Known person/place', body='Known')
            self.assertIn('Pilot Mode', self.api_error(path, restricted)['error'])
            ref = next(n for n in self.api(path, {**restricted, 'pilot': True})['notes'] if n['category'] == category)
            for change in ({'body': 'Changed'}, {'remove': True}, {'category': 'world'}):
                self.assertIn('Pilot Mode', self.api_error(path, {**restricted, 'id': ref['id'], **change})['error'])
        server.initialize()
        resumed = self.api(f'/api/saves/{save_id}')
        self.assertEqual(next(n for n in resumed['notes'] if n['id'] == note['id']), edited)
        with server.LOCK, server.db() as conn:
            state = server.snapshot(conn, save_id)
            self.assertNotIn('NOTE_SECRET', json.dumps(ai.build_context(state, server.DATA)))
            self.assertNotIn('NOTE_SECRET', json.dumps(ai.build_context(state, server.DATA, purpose='ask')))
            # Supply completed history long enough to trigger a summary.
            state['messages'] = [dict(id=i, kind='ai', name='AI-DM', body='History ' * 1000, beat=i) for i in range(1, 101)]
            self.assertNotIn('NOTE_SECRET', json.dumps(ai.build_summary_context(state)))
        delete = dict(playerId=second, id=edited['id'], revision=edited['revision'], remove=True, mutationId='delete-loot')
        removed = self.api(path, delete)
        self.assertFalse(any(n['id'] == note['id'] for n in removed['notes']))
        self.api(path, delete)  # Lost delete acknowledgement is safe to retry.
        self.assertEqual(self.api_error(path, {**edit, 'revision': 2, 'mutationId': 'after-delete'})['code'], 'note_conflict')
        with server.db() as conn:
            row = conn.execute('SELECT * FROM party_notes WHERE id=?', (note['id'],)).fetchone()
            self.assertEqual((row['body'], row['removed_by']), ('NOTE_SECRET: 43 gold', second))

    def test_migrates_original_world_notes_in_place(self):
        save_id = self.ready_save()
        with server.LOCK, server.db() as conn:
            conn.execute('DROP TABLE party_notes')
            conn.execute('''CREATE TABLE party_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL,
                category TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
                created_by TEXT, created_at TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL,
                removed_at TEXT, removed_by TEXT)''')
            conn.execute("INSERT INTO party_notes (id,save_id,category,title,body,created_at,updated_at) VALUES (99,?,'world','Loot','Old gold','then','then')", (save_id,))
            conn.commit()
        server.initialize()
        [note] = self.api(f'/api/saves/{save_id}')['notes']
        self.assertEqual((note['id'], note['title'], note['body'], note['revision']), (99, 'Loot', 'Old gold', 1))


if __name__ == '__main__':
    unittest.main()
