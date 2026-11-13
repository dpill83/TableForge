"""Download the complete saved public conversation without operational context."""
import json
import unittest
import urllib.error
import urllib.request

import server
import test_flow


class ChatExportTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    ready_save = test_flow.FlowTest.ready_save

    def test_saved_history_format_order_and_privacy(self):
        save_id = self.ready_save(module='# SECRET hidden adventure')
        state = self.api(f'/api/saves/{save_id}')
        session = state['sessions'][0]['id']
        player = state['players'][0]['id']
        with server.db() as conn:
            conn.execute('DELETE FROM messages WHERE save_id=?', (save_id,))
            # More history than a feed window should ever be expected to retain.
            for index in range(250):
                conn.execute('INSERT INTO messages (save_id,session_id,player_id,kind,name,body,created_at) '
                             'VALUES (?,?,?,?,?,?,?)',
                             (save_id, session, player, 'player', 'George', f'Older message {index}',
                              f'2026-11-10T10:{index // 60:02d}:{index % 60:02d}+00:00'))
            conn.execute('INSERT INTO sessions (id,save_id,number,started_at,participants) VALUES (?,?,?,?,?)',
                         ('next', save_id, 2, '2026-11-12T10:00:00+00:00', '[]'))
            conn.execute('INSERT INTO messages (save_id,session_id,kind,name,body,created_at,choices_json) '
                         'VALUES (?,?,?,?,?,?,?)', (save_id, 'next', 'ai', 'wrong label',
                         '**A doorway.**\n\n> “Who goes there?”\n\n- Listen\n- Wait',
                         '2026-11-12T10:00:00+00:00', json.dumps({'groups': [
                             {'playerId': None, 'options': [{'letter': 'A', 'text': 'Enter'}]}]})))
            for kind, text, stamp in [('ready_override', 'SECRET activity', '10:00:01'),
                                      ('combat_outcome', '*Victory!*\n\nTwo goblins fled.', '10:00:02'),
                                      ('combat_correction', 'Correction: one goblin surrendered.', '10:00:03'),
                                      ('combat_skipped', 'SECRET skip metadata', '10:00:03')]:
                conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) '
                             'VALUES (?,?,?,?,?,?)',
                             (save_id, 'next', player, kind, text, f'2026-11-12T{stamp}+00:00'))
            conn.execute('INSERT INTO pilot_messages (save_id,kind,name,body,created_at) VALUES (?,?,?,?,?)',
                         (save_id, 'ai', 'AI-DM', 'SECRET private answer', server.utc()))
            conn.execute('INSERT INTO messages (save_id,session_id,kind,name,body,created_at) VALUES (?,?,?,?,?,?)',
                         (save_id, 'next', 'system', 'System', 'SECRET internal prompt', server.utc()))
            conn.execute('INSERT INTO messages (save_id,session_id,kind,name,body,created_at) VALUES (?,?,?,?,?,?)',
                         (save_id, 'next', 'ai', 'AI-DM', 'Aftermath narration.', '2026-11-12T10:00:04+00:00'))
        # The cartridge need not be mounted for a public-history download.
        (server.DATA / 'cartridges' / (state['cartridge']['id'] + '.zip')).unlink()
        before = self.api(f'/api/saves/{save_id}')
        with urllib.request.urlopen(self.base + f'/api/saves/{save_id}/chat.md') as response:
            text = response.read().decode('utf-8')
            self.assertEqual(response.headers['Content-Type'], 'text/markdown; charset=utf-8')
            self.assertIn("filename*=UTF-8''Hollow-Well-chat-", response.headers['Content-Disposition'])
            self.assertTrue(response.headers['Content-Disposition'].endswith('.md'))
        self.assertTrue(text.startswith('# Hollow Well\n\nPlaythrough: Our game'))
        self.assertIn('## Session 1', text)
        self.assertIn('## Session 2', text)
        self.assertEqual(text.count('### George\n'), 250)
        self.assertLess(text.index('Older message 0\n'), text.index('Older message 249\n'))
        self.assertIn('### AI-DM\n\n**A doorway.**\n\n> “Who goes there?”\n\n- Listen\n- Wait', text)
        self.assertIn('**A.** Enter', text)
        self.assertIn('### George — Combat outcome\n\n*Victory!*\n\nTwo goblins fled.', text)
        self.assertLess(text.index('**A doorway.**'), text.index('*Victory!*'))
        self.assertLess(text.index('*Victory!*'), text.index('Aftermath narration.'))
        self.assertIn('### George — Combat correction\n\nCorrection: one goblin surrendered.', text)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('wrong label', text)
        self.assertEqual(before, self.api(f'/api/saves/{save_id}'))

    def test_missing_save_is_an_error(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + '/api/saves/missing/chat.md')
        self.assertEqual(caught.exception.code, 400)
        self.assertIn('Save not found', caught.exception.read().decode())
