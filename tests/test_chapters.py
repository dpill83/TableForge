import sqlite3
import unittest

import ai
import chapters


def chapter(number, start, end, recap=None, title=None):
    return {'id': number, 'number': number, 'title': title or f'Chapter {number}', 'started_after': start,
            'ended_through': end, 'recap': recap, 'recap_by': None, 'revision': 1}


def messages(count, size=1000):
    return [{'id': i, 'kind': 'ai' if i % 2 == 0 else 'player', 'name': 'George', 'body': str(i % 10) * size,
             'created_at': 't'} for i in range(1, count + 1)]


class MarkerTest(unittest.TestCase):
    def test_takes_the_last_marker_and_strips_every_marker_line(self):
        text, title = chapters.take_marker('The ogres flee.\n[Chapter: Into the Warrens]\n')
        self.assertEqual((text, title), ('The ogres flee.', 'Into the Warrens'))
        self.assertEqual(chapters.take_marker('No break here.'), ('No break here.', None))

    def test_inline_mentions_are_not_markers(self):
        text, title = chapters.take_marker('George reads "[Chapter: Lies]" on the wall.')
        self.assertIsNone(title)
        self.assertIn('[Chapter: Lies]', text)


class MemoryTest(unittest.TestCase):
    def state(self, listed, summary=None, count=20):
        return {'messages': messages(count), 'chapters': listed, 'summary': summary}

    def test_recaps_replace_chat_and_supersede_older_rolling_summaries(self):
        old = {'id': 1, 'body': 'Old rolling summary.', 'through_message_id': 6}
        state = self.state([chapter(1, 0, 10, 'Prologue recap.'), chapter(2, 10, None)], old)
        effective = ai.effective_summary(state)
        self.assertEqual((effective['body'], effective['through_message_id']), ('', 10))
        newer = {'id': 2, 'body': 'Chapter two so far.', 'through_message_id': 14}
        self.assertEqual(ai.effective_summary({**state, 'summary': newer}), newer)

    def test_a_closed_chapter_without_a_recap_covers_nothing_yet(self):
        state = self.state([chapter(1, 0, 10), chapter(2, 10, None)])
        self.assertIsNone(ai.effective_summary(state))
        self.assertEqual(ai.summary_limit(state), 10)
        self.assertEqual(ai.memory_due(state), 'recap')

    def test_rolling_summaries_stop_at_a_chapter_waiting_for_its_recap(self):
        listed = messages(40, size=3000)
        selected = ai.summary_range(listed, None, limit=10)
        self.assertTrue(selected)
        self.assertTrue(all(m['id'] <= 10 for m in selected))

    def test_recap_context_covers_only_the_chapter_after_its_rolling_summary(self):
        summary = {'id': 1, 'body': 'Early prologue.', 'through_message_id': 4}
        state = {**self.state([chapter(1, 0, 10, title='Prologue'), chapter(2, 10, None)], summary),
                 'cartridge': {'title': 'T'}, 'save': {'beat': 6}, 'facts': []}
        context = ai.build_recap_context(state, state['chapters'][0])
        self.assertEqual(context['previousSummary'], 'Early prologue.')
        self.assertEqual(len(context['messages']), 6)
        prompt = ai.chat_messages(context)
        self.assertTrue(prompt[0]['content'].startswith(chapters.RECAP_PROMPT))
        self.assertIn('Chapter 1: Prologue', prompt[1]['content'])
        self.assertIn('tableforge-facts', prompt[0]['content'])

    def test_narration_lists_recaps_then_the_current_chapter(self):
        text = ai.summary_text({'chapterRecaps': [{'number': 1, 'title': 'Prologue', 'recap': 'They took the job.'}],
                                'chapter': {'number': 2, 'title': 'The Mine'},
                                'summary': {'body': 'They found the tally board.'}})
        self.assertLess(text.index('Chapter 1: Prologue\nThey took the job.'), text.index('Current chapter: Chapter 2: The Mine'))
        self.assertIn('They found the tally board.', text)


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE saves (id TEXT PRIMARY KEY, opening_stage TEXT)')
        self.conn.execute("INSERT INTO saves VALUES ('s', 'exploration')")
        chapters.initialize(self.conn)
        self.save = {'id': 's', 'opening_stage': 'exploration'}

    def test_implicit_first_chapter_then_close_and_open_the_next(self):
        self.assertEqual([(c['number'], c['title'], c['id']) for c in chapters.visible(self.conn, self.save)],
                         [(1, 'Chapter 1', None)])
        with self.assertRaises(ValueError):
            chapters.close(self.conn, self.save, 0, None, 'p', 'pilot', 't')
        self.assertEqual(chapters.close(self.conn, self.save, 12, 'The Climax', 'p', 'pilot', 't'), 2)
        first, second = chapters.visible(self.conn, self.save)
        self.assertEqual((first['ended_through'], first['closed_by']), (12, 'p'))
        self.assertEqual((second['title'], second['started_after'], second['ended_through']), ('The Climax', 12, None))
        with self.assertRaises(ValueError):
            chapters.close(self.conn, self.save, 12, None, 'p', 'pilot', 't')

    def test_automatic_recaps_never_overwrite_and_pilot_edits_are_revision_checked(self):
        chapters.close(self.conn, self.save, 5, None, 'p', 'pilot', 't')
        first = chapters.visible(self.conn, self.save)[0]
        chapters.store_recap(self.conn, first['id'], 'Automatic recap.', None, 't')
        with self.assertRaises(ValueError):
            chapters.store_recap(self.conn, first['id'], 'Second automatic recap.', None, 't')
        revision = chapters.visible(self.conn, self.save)[0]['revision']
        chapters.store_recap(self.conn, first['id'], 'Pilot recap.', 'p', 't', revision)
        with self.assertRaises(ValueError):
            chapters.store_recap(self.conn, first['id'], 'Stale edit.', 'q', 't', revision)
        self.assertEqual(chapters.visible(self.conn, self.save)[0]['recap'], 'Pilot recap.')
        open_chapter = chapters.visible(self.conn, self.save)[-1]
        with self.assertRaises(ValueError):
            chapters.store_recap(self.conn, open_chapter['id'], 'Too early.', 'p', 't', open_chapter['revision'])


class CombatReportTest(unittest.TestCase):
    def state(self, summary=None, listed=None):
        listed_messages = [{**m, 'created_at': f't{m["id"]:02d}'} for m in messages(20)]
        events = [
            {'kind': 'combat_outcome', 'body': 'Goblins routed.', 'created_at': 't03'},
            {'kind': 'combat_outcome', 'body': 'Ogre chief fled.', 'created_at': 't09'},
            {'kind': 'combat_correction', 'body': 'Correction: the goblin boss escaped.', 'created_at': 't15'},
            {'kind': 'session_start', 'body': '', 'created_at': 't01'},
        ]
        return {'messages': listed_messages, 'events': events, 'summary': summary, 'chapters': listed or [],
                'cartridge': {'title': 'T'}, 'save': {'beat': 9}, 'facts': []}

    def test_every_report_is_sent_until_a_summary_covers_it(self):
        self.assertEqual(len(ai.combat_reports(self.state(), ai.covered_time(self.state()))), 3)
        summarized = self.state({'id': 1, 'body': 'Early play.', 'through_message_id': 6})
        sent = ai.combat_reports(summarized, ai.covered_time(summarized))
        self.assertEqual([e['body'] for e in sent], ['Ogre chief fled.', 'Correction: the goblin boss escaped.'])

    def test_a_correction_to_a_summarized_fight_stays_until_a_later_summary_folds_it_in(self):
        covered = self.state({'id': 1, 'body': 'Both fights.', 'through_message_id': 12})
        sent = ai.combat_reports(covered, ai.covered_time(covered))
        self.assertEqual([e['kind'] for e in sent], ['combat_correction'])
        self.assertEqual(ai.combat_reports(self.state({'id': 2, 'body': 'All.', 'through_message_id': 16}),
                                           't16'), [])

    def test_summaries_and_recaps_receive_the_reports_in_their_stretch(self):
        state = self.state({'id': 1, 'body': 'Early play.', 'through_message_id': 4})
        self.assertEqual([r['body'] for r in ai.report_inputs(state, 10)], ['Ogre chief fled.'])
        prompt = ai.summary_chat_messages({'title': 'T', 'previousSummary': '', 'messages': [],
                                           'combatReports': ai.report_inputs(state, 16)})
        self.assertIn("table's own account of how each fight ended", prompt[1]['content'])
        self.assertIn('- Correction: the goblin boss escaped.', prompt[1]['content'])
        recap = ai.build_recap_context(self.state(listed=[chapter(1, 0, 10), chapter(2, 10, None)]),
                                       chapter(1, 0, 10))
        self.assertEqual([r['body'] for r in recap['combatReports']], ['Goblins routed.', 'Ogre chief fled.'])

    def test_recapped_chapters_cover_their_fights(self):
        state = self.state(listed=[chapter(1, 0, 10, 'Recap.'), chapter(2, 10, None)])
        self.assertEqual([e['body'] for e in ai.combat_reports(state, ai.covered_time(state))],
                         ['Correction: the goblin boss escaped.'])


if __name__ == '__main__':
    unittest.main()
