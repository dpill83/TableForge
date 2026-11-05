"""Offline maintenance must preserve other saves and roll back incomplete deletion."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import server
from deploy.kilo import manage_saves as manager


class ManageSavesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tableforge.sqlite3'
        with patch.object(server, 'DATA', self.path.parent):
            server.initialize()
        self.db = manager.connect(self.path)
        self.addCleanup(self.db.close)
        with self.db:
            self.db.execute("INSERT INTO cartridges(id,title,source,resources,created_at) VALUES ('cart','Adventure','original.zip','{}','today')")
            for save_id in ('old', 'keep'):
                self.db.execute("INSERT INTO saves(id,name,cartridge_id,created_at,updated_at) VALUES (?,?,'cart','today','today')", (save_id, save_id))
                self.db.execute("INSERT INTO players(id,save_id,name,character) VALUES (?,?,'Player','Character')", (save_id, save_id))
                self.db.execute("INSERT INTO sessions(id,save_id,number,started_at,participants) VALUES (?,?,1,'today','[]')", (save_id, save_id))
                self.db.execute("INSERT INTO messages(save_id,kind,name,body,created_at) VALUES (?,'ai','AI-DM','Narration','today')", (save_id,))
                self.db.execute("INSERT INTO pilot_messages(save_id,player_id,thread_player_id,kind,name,body,created_at) VALUES (?,?,?,'player','Player','Question','today')", (save_id, save_id, save_id))
                self.db.execute("INSERT INTO player_portraits(player_id,save_id,mime,image,updated_at) VALUES (?,?,'image/png',X'00','today')", (save_id, save_id))
                self.db.execute("INSERT INTO ai_requests(id,save_id,session_id,player_id,purpose,provider,status,started_at) VALUES (?,?,?,?,'advance','mock','complete','today')", (save_id,) * 4)
                self.db.execute("INSERT INTO ai_usage(save_id,session_id,request_id,purpose,model,created_at) VALUES (?,?,?,'advance','mock','today')", (save_id,) * 3)

    def test_delete_preserves_other_save_cartridge_and_restorable_backup(self):
        backup = manager.change_save(self.db, self.path, 'old')
        self.assertEqual([row[0] for row in self.db.execute('SELECT id FROM saves')], ['keep'])
        for table in manager.save_tables(self.db):
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM "{table}" WHERE save_id="old"').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cartridges').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM ai_usage WHERE save_id="keep"').fetchone()[0], 1)
        self.assertFalse(self.db.execute('PRAGMA foreign_key_check').fetchall())
        with closing(sqlite3.connect(backup)) as restored:
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM saves').fetchone()[0], 2)
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM ai_usage').fetchone()[0], 2)

    def test_rename_only_changes_selected_name_and_timestamp(self):
        manager.change_save(self.db, self.path, 'old', name='New name')
        self.assertEqual(self.db.execute('SELECT name FROM saves WHERE id="old"').fetchone()[0], 'New name')
        self.assertEqual(self.db.execute('SELECT name FROM saves WHERE id="keep"').fetchone()[0], 'keep')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 2)

    def test_unhandled_reference_rolls_back_every_deleted_row(self):
        with self.db:
            self.db.execute('CREATE TABLE future_reference (owner TEXT REFERENCES saves(id))')
            self.db.execute("INSERT INTO future_reference VALUES ('old')")
        with self.assertRaisesRegex(RuntimeError, 'rolled back'):
            manager.change_save(self.db, self.path, 'old')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM saves').fetchone()[0], 2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM ai_usage').fetchone()[0], 2)

    def test_backup_failure_prevents_deletion(self):
        with patch.object(manager, 'backup', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                manager.change_save(self.db, self.path, 'old')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM saves').fetchone()[0], 2)

    def test_unknown_save_table_blocks_deletion(self):
        self.db.execute('CREATE TABLE future_save_data (save_id TEXT)')
        with self.assertRaisesRegex(RuntimeError, 'Unrecognized save table'):
            manager.change_save(self.db, self.path, 'old')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM saves').fetchone()[0], 2)

    def test_typed_confirmation_and_service_guard(self):
        with patch('builtins.input', side_effect=['1', 'd', 'delete', 'q']), patch.object(manager, 'change_save') as change:
            manager.menu(self.db, self.path)
            change.assert_not_called()
        with patch.object(manager.subprocess, 'run') as run:
            run.return_value.stdout = 'LoadState=loaded\nActiveState=active\n'
            with self.assertRaisesRegex(RuntimeError, 'Stop TableForge'):
                manager.require_stopped()
            run.return_value.stdout = 'LoadState=loaded\nActiveState=inactive\n'
            manager.require_stopped()


if __name__ == '__main__':
    unittest.main()
