import json
import sqlite3
import unittest

import ai
import facts


def block(operations):
    return 'The party reached the camp.\n\n```tableforge-facts\n' + json.dumps(operations) + '\n```'


class ExtractTest(unittest.TestCase):
    def test_splits_summary_from_facts_block(self):
        summary, operations = facts.extract(block({'add': [{'category': 'item', 'text': 'The drum is cracked.'}]}))
        self.assertEqual(summary, 'The party reached the camp.')
        self.assertEqual(operations['add'][0]['text'], 'The drum is cracked.')

    def test_summary_without_block_or_with_bad_json_keeps_text_and_changes_nothing(self):
        self.assertEqual(facts.extract('Just a summary.'), ('Just a summary.', None))
        summary, operations = facts.extract('Summary.\n```tableforge-facts\n{not json\n```')
        self.assertEqual((summary, operations), ('Summary.', None))


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE saves (id TEXT PRIMARY KEY)')
        self.conn.execute("INSERT INTO saves VALUES ('s')")
        facts.initialize(self.conn)

    def add_auto(self, category, text):
        facts.apply_summary(self.conn, 's', {'add': [{'category': category, 'text': text}]}, 1, 't0')
        return facts.visible(self.conn, 's')[-1]

    def changes(self):
        return [dict(r) for r in self.conn.execute('SELECT action,body,reason,player_id,summary_id FROM fact_changes ORDER BY id')]

    def test_summary_adds_valid_facts_and_skips_duplicates_and_unknown_categories(self):
        applied = facts.apply_summary(self.conn, 's', {'add': [
            {'category': 'location', 'text': 'Ethereal hides in the supply tent.'},
            {'category': 'location', 'text': 'ethereal hides in the supply tent.'},
            {'category': 'hp', 'text': 'George has 12 HP.'},
            {'category': 'hook', 'text': ''},
        ]}, 7, 't1')
        self.assertEqual(applied['add'], 1)
        fact = facts.visible(self.conn, 's')[0]
        self.assertEqual((fact['category'], fact['locked'], fact['created_by']), ('location', 0, None))
        self.assertEqual(self.changes(), [{'action': 'add', 'body': 'Ethereal hides in the supply tent.',
                                           'reason': None, 'player_id': None, 'summary_id': 7}])

    def test_updates_and_resolutions_need_a_reason(self):
        fact = self.add_auto('promise', 'Viktor is weighing safe passage for the drum.')
        applied = facts.apply_summary(self.conn, 's', {
            'update': [{'id': fact['id'], 'text': 'Viktor refused the bargain.'}],
            'resolve': [{'id': fact['id']}],
        }, 2, 't2')
        self.assertEqual(applied, {'add': 0, 'update': 0, 'resolve': 0})
        applied = facts.apply_summary(self.conn, 's', {
            'update': [{'id': fact['id'], 'text': 'Viktor wants the drum repaired first.', 'reason': 'He countered.'}],
        }, 3, 't3')
        self.assertEqual(applied['update'], 1)
        current = facts.visible(self.conn, 's')[0]
        self.assertEqual((current['body'], current['reason']), ('Viktor wants the drum repaired first.', 'He countered.'))
        facts.apply_summary(self.conn, 's', {'resolve': [{'id': fact['id'], 'reason': 'Deal struck.'}]}, 4, 't4')
        self.assertEqual(facts.visible(self.conn, 's')[0]['status'], 'resolved')
        # The history keeps every version; nothing is overwritten.
        self.assertEqual([c['action'] for c in self.changes()], ['add', 'update', 'resolve'])
        self.assertEqual(self.changes()[0]['body'], 'Viktor is weighing safe passage for the drum.')

    def test_summary_cannot_delete_or_touch_pilot_locked_facts(self):
        facts.pilot_change(self.conn, 's', 'pilot', {'action': 'add', 'category': 'item', 'body': 'The drum is cracked.',
                                                    'mutationId': 'm1'}, 't1')
        fact = facts.visible(self.conn, 's')[0]
        self.assertEqual(fact['locked'], 1)
        facts.apply_summary(self.conn, 's', {
            'update': [{'id': fact['id'], 'text': 'The drum is fine.', 'reason': 'Misread.'}],
            'resolve': [{'id': fact['id'], 'reason': 'Gone.'}],
            'remove': [{'id': fact['id']}],
        }, 2, 't2')
        self.assertEqual(facts.visible(self.conn, 's')[0]['body'], 'The drum is cracked.')
        self.assertEqual(facts.visible(self.conn, 's')[0]['status'], 'open')

    def test_pilot_changes_are_revision_checked_idempotent_and_lock_the_fact(self):
        fact = self.add_auto('hook', 'Someone is watching from the ridge.')
        edit = {'action': 'edit', 'id': fact['id'], 'revision': fact['revision'],
                'body': 'A scout watches from the ridge.', 'mutationId': 'm2'}
        facts.pilot_change(self.conn, 's', 'pilot', edit, 't1')
        facts.pilot_change(self.conn, 's', 'pilot', edit, 't1')  # retry lands once
        current = facts.visible(self.conn, 's')[0]
        self.assertEqual((current['body'], current['locked'], current['revision']), ('A scout watches from the ridge.', 1, 2))
        with self.assertRaises(facts.FactConflict):
            facts.pilot_change(self.conn, 's', 'other', {**edit, 'mutationId': 'm3', 'body': 'Stale'}, 't2')
        facts.pilot_change(self.conn, 's', 'pilot', {'action': 'remove', 'id': fact['id'], 'revision': 2, 'mutationId': 'm4'}, 't3')
        self.assertEqual(facts.visible(self.conn, 's'), [])
        self.assertEqual(self.conn.execute('SELECT status FROM facts').fetchone()[0], 'removed')

    def test_pilot_input_is_validated(self):
        with self.assertRaises(ValueError):
            facts.pilot_change(self.conn, 's', 'p', {'action': 'add', 'category': 'hp', 'body': 'x', 'mutationId': 'a'}, 't')
        with self.assertRaises(ValueError):
            facts.pilot_change(self.conn, 's', 'p', {'action': 'add', 'category': 'item', 'body': 'x' * 501, 'mutationId': 'b'}, 't')
        with self.assertRaises(ValueError):
            facts.pilot_change(self.conn, 's', 'p', {'action': 'add', 'category': 'item', 'body': 'x'}, 't')

    def test_narration_text_groups_open_facts_only(self):
        listed = [{'category': 'location', 'body': 'George is at the gate.', 'status': 'open'},
                  {'category': 'hook', 'body': 'Old lead.', 'status': 'resolved'}]
        text = facts.narration_text(listed)
        self.assertIn('Where everyone is:\n- George is at the gate.', text)
        self.assertNotIn('Old lead', text)
        self.assertEqual(facts.narration_text([]), '')


class SummaryPromptTest(unittest.TestCase):
    def state(self):
        messages = [{'id': i, 'kind': 'player' if i % 2 else 'ai', 'name': 'George', 'body': 'x' * 12000,
                     'created_at': 't'} for i in range(1, 8)]
        return {'messages': messages, 'summary': None, 'cartridge': {'title': 'T'}, 'save': {'beat': 4},
                'facts': [{'id': 3, 'category': 'item', 'body': 'The drum is cracked.', 'status': 'open', 'locked': 1}]}

    def test_only_automatic_summaries_receive_the_ledger(self):
        automatic = ai.chat_messages(ai.build_summary_context(self.state(), with_facts=True))
        self.assertIn('tableforge-facts', automatic[0]['content'])
        self.assertIn('[3] (item, locked) The drum is cracked.', automatic[1]['content'])
        manual = ai.chat_messages(ai.build_summary_context(self.state()))
        self.assertNotIn('tableforge-facts', manual[0]['content'])
        self.assertNotIn('The drum is cracked.', manual[1]['content'])

    def test_summary_prompt_keeps_ooc_out_and_never_tracks_hit_points(self):
        self.assertIn('OOC questions are hypothetical and are never facts', facts.INSTRUCTIONS)
        self.assertIn('never hit points', facts.INSTRUCTIONS)


if __name__ == '__main__':
    unittest.main()
