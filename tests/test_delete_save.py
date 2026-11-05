"""Exercise the trusted-table web deletion API and its safety boundaries."""
import sqlite3
from contextlib import closing
from unittest.mock import patch
import unittest

import server
import test_flow


class DeleteSaveTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    ready_save = test_flow.FlowTest.ready_save

    def payload(self, **changes):
        return {'confirmed': True, 'confirmation': 'DELETE', 'name': 'Our game', **changes}

    def test_requires_both_confirmations_and_current_name(self):
        save_id = self.ready_save()
        for payload in ({}, self.payload(confirmed=False), self.payload(confirmation='delete'),
                        self.payload(name='Wrong save')):
            self.assertIn('error', self.api_error(f'/api/saves/{save_id}/delete', payload))
        self.assertEqual(self.api(f'/api/saves/{save_id}')['save']['id'], save_id)
        self.assertEqual(self.api('/api/backups')['backups'], [])

    def test_deletes_only_selected_save_with_all_dependencies_and_verified_backup(self):
        save_id, keep = self.ready_save(), self.ready_save()
        with server.db() as db:
            player = db.execute('SELECT id FROM players WHERE save_id=?', (save_id,)).fetchone()[0]
            session = db.execute('SELECT id FROM sessions WHERE save_id=?', (save_id,)).fetchone()[0]
            message = db.execute('SELECT id FROM messages WHERE save_id=?', (save_id,)).fetchone()[0]
            db.execute("INSERT INTO ai_requests(id,save_id,session_id,player_id,purpose,provider,status,started_at) VALUES ('req',?,?,?,'advance','mock','complete','today')", (save_id, session, player))
            db.execute("INSERT INTO ai_usage(save_id,session_id,request_id,purpose,model,created_at) VALUES (?,?,'req','advance','mock','today')", (save_id, session))
            db.execute("INSERT INTO chat_images(id,save_id,message_id,player_id,mime,image,created_at) VALUES ('attachment',?,?,?,'image/png',X'00','today')", (save_id, message, player))
            db.execute("INSERT INTO scene_images(id,save_id,session_id,player_id,source_message_id,direction,prompt,model,quality,size,status,created_at) VALUES ('scene',?,?,?,?,'','prompt','mock','low','small','draft','today')", (save_id, session, player, message))
            db.execute("INSERT INTO summaries(save_id,through_message_id,body,created_at) VALUES (?,?,'Summary','today')", (save_id, message))
            first_summary = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute("INSERT INTO summaries(save_id,through_message_id,based_on,body,created_at) VALUES (?,?,?,'Summary two','today')", (save_id, message, first_summary))
            db.execute("INSERT INTO pilot_messages(save_id,player_id,thread_player_id,kind,name,body,created_at) VALUES (?,?,?,'player','Player','Question','today')", (save_id, player, player))
        original = self.api(f'/api/saves/{keep}')
        with server.db() as db:
            db.execute("UPDATE scene_images SET status='generating' WHERE save_id=?", (save_id,))
        self.assertIn('illustration', self.api_error(f'/api/saves/{save_id}/delete', self.payload())['error'])
        with server.db() as db:
            db.execute("UPDATE scene_images SET status='draft' WHERE save_id=?", (save_id,))
        cartridge = self.path / 'cartridges' / (original['cartridge']['id'] + '.zip')
        server.TYPING[save_id] = {}
        server.AI_REQUEST_LOGS[save_id] = {'temporary': True}
        result = self.api(f'/api/saves/{save_id}/delete', self.payload())
        self.assertEqual(result['deleted'], save_id)
        self.assertEqual(self.api(f'/api/saves/{keep}')['messages'], original['messages'])
        self.assertTrue(cartridge.is_file())
        self.assertNotIn(save_id, server.TYPING)
        self.assertNotIn(save_id, server.AI_REQUEST_LOGS)
        self.assertEqual(self.api_error(f'/api/saves/{save_id}')['code'], 'save_unavailable')
        self.assertEqual(self.api_error(f'/api/saves/{save_id}/delete', self.payload())['code'], 'save_unavailable')
        with server.db() as db:
            for table in ('players', 'messages', 'sessions', 'summaries', 'scene_images', 'chat_images', 'ai_usage', 'ai_requests', 'pilot_messages'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table} WHERE save_id=?', (save_id,)).fetchone()[0], 0)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertGreater(db.execute('SELECT COUNT(*) FROM narration_prompts').fetchone()[0], 0)
        with closing(sqlite3.connect(self.path / 'backups' / result['backup'])) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM saves').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM chat_images').fetchone()[0], 1)

    def test_generation_and_backup_failure_block_deletion(self):
        save_id = self.ready_save()
        for purpose in ('advance', 'ask', 'summary'):
            server.GENERATING[save_id] = purpose
            self.assertIn('Wait', self.api_error(f'/api/saves/{save_id}/delete', self.payload())['error'])
        server.GENERATING.clear()
        with patch.object(server.backups, 'create', side_effect=OSError('disk full')):
            error = self.api_error(f'/api/saves/{save_id}/delete', self.payload())
        self.assertIn('No deletion was committed', error['error'])
        self.assertEqual(self.api(f'/api/saves/{save_id}')['save']['id'], save_id)

    def test_unknown_future_relationship_rolls_back(self):
        save_id = self.ready_save()
        with server.db() as db:
            db.execute('CREATE TABLE future_data (save_id TEXT REFERENCES saves(id))')
            db.execute('INSERT INTO future_data VALUES (?)', (save_id,))
        self.assertIn('Unknown save data', self.api_error(f'/api/saves/{save_id}/delete', self.payload())['error'])
        self.assertTrue(self.api(f'/api/saves/{save_id}')['messages'])


if __name__ == '__main__':
    unittest.main()
