"""Exercise optional choice output and durable narration over the HTTP workflow."""
import json
import unittest
import uuid
from unittest.mock import patch

import ai
import narration_choices
import runtime_prompts
import server
import test_flow


def footer(groups):
    return '\n\n```tableforge-choices\n' + json.dumps({'groups': groups}) + '\n```'


class ChoiceParserTest(unittest.TestCase):
    players = [{'id': 'first', 'character': 'Caravaggio'}, {'id': 'second', 'character': 'Ethereal'}]

    def test_public_labels_and_actions_share_one_mapping(self):
        text = 'How do you spend the time?' + footer([
            {'playerId': 'first', 'options': ['I help the crew.', '  I keep\nwatch.  ']},
            {'playerId': None, 'options': ['I suggest we stay aboard.']},
        ])
        prose, choices = narration_choices.extract(text, self.players, 3)
        self.assertEqual(prose, 'How do you spend the time?')
        self.assertEqual(choices['beat'], 3)
        self.assertEqual(choices['groups'][0]['options'][1], {'letter': 'B', 'text': 'I keep watch.'})
        body = narration_choices.public_body(prose, choices, self.players)
        self.assertIn('**Caravaggio**', body)
        self.assertIn('**Party**', body)
        self.assertIn('- **B.** I keep watch.', body)
        self.assertNotIn('tableforge-choices', body)
        self.assertNotIn('playerId', body)

    def test_invalid_groups_never_become_party_wide(self):
        groups = [{'playerId': 'unknown', 'options': ['Hidden target.']},
                  {'options': ['Missing target.']},
                  {'playerId': None, 'options': ['I wait.']}]
        with self.assertLogs('narration_choices', level='WARNING'):
            prose, choices = narration_choices.extract('Choose.' + footer(groups), self.players, 2)
        self.assertEqual([group['playerId'] for group in choices['groups']], [None])
        self.assertEqual(prose, 'Choose.')

    def test_invalid_footer_preserves_narration_without_protocol_leak(self):
        for block in ('\n```tableforge-choices\n{bad}\n```',
                      '\n```tableforge-choices\n{"groups":',
                      footer([{'playerId': None, 'options': ['I wait.']}]) * 2,
                      footer([{'playerId': None, 'options': [42]}]),
                      footer([{'playerId': [], 'options': ['I wait.']}])):
            with self.subTest(block=block), self.assertLogs('narration_choices', level='WARNING'):
                prose, choices = narration_choices.extract('Narration stays.' + block, self.players, 2)
                self.assertEqual(prose, 'Narration stays.')
                self.assertIsNone(choices)

    def test_plain_narration_and_ordinary_code_blocks_remain_unchanged(self):
        text = 'What do you do?\n\n```json\n{"example":true}\n```'
        self.assertEqual(narration_choices.extract(text, self.players, 2), (text, None))

    def test_choice_text_is_literal_and_size_is_bounded(self):
        prose, choices = narration_choices.extract('Choose.' + footer([
            {'playerId': None, 'options': ['I inspect **the blade** [carefully](https://example.com).']}
        ]), self.players, 2)
        body = narration_choices.public_body(prose, choices, self.players)
        self.assertIn('\\*\\*the blade\\*\\*', body)
        self.assertIn('\\[carefully\\]', body)
        for options in ([], ['I wait.'] * 27, ['x' * 2001]):
            with self.assertLogs('narration_choices', level='WARNING'):
                self.assertIsNone(narration_choices.extract('Choose.' + footer([
                    {'playerId': None, 'options': options}]), self.players, 2)[1])


class ChoiceFlowTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    ready_save = test_flow.FlowTest.ready_save
    override = test_flow.FlowTest.override
    focused_save = test_flow.FlowTest.focused_save
    cartridge_zip = test_flow.FlowTest.cartridge_zip
    FOCUSED_MODULE = test_flow.FlowTest.FOCUSED_MODULE
    FOCUSED_RUN_DATA = test_flow.FlowTest.FOCUSED_RUN_DATA

    def advance_with_choices(self, save_id):
        before = self.api(f'/api/saves/{save_id}')
        first = before['players'][0]['id']
        fake = test_flow.FakeProvider('How does George spend the time?' + footer([
            {'playerId': first, 'options': ['I help the crew.', 'I keep watch.']},
            {'playerId': None, 'options': ['I suggest we explore the island.']},
        ]))
        with patch.object(ai, 'current_provider', return_value=fake):
            after = self.api(f'/api/saves/{save_id}/advance', {'beat': before['save']['beat'], **self.override(save_id)})
        return before, after, fake

    def test_choices_persist_and_editable_reply_uses_existing_send_contract(self):
        save_id = self.ready_save()
        before, after, _ = self.advance_with_choices(save_id)
        message = after['messages'][-1]
        self.assertEqual(message['choices']['beat'], after['save']['beat'])
        self.assertFalse(any(player['ready'] for player in after['players']))
        self.assertNotIn('choices_json', message)
        self.assertNotIn('tableforge-choices', message['body'])
        self.assertEqual(self.api(f'/api/saves/{save_id}')['messages'][-1], message)
        server.initialize()
        self.assertEqual(self.api(f'/api/saves/{save_id}')['messages'][-1]['choices'], message['choices'])
        request = {'playerId': after['players'][0]['id'], 'text': 'I keep watch, especially toward the island.',
                   'beat': after['save']['beat'], 'requestId': str(uuid.uuid4())}
        sent = self.api(f'/api/saves/{save_id}/messages', request)
        again = self.api(f'/api/saves/{save_id}/messages', request)
        self.assertEqual(sent['messages'], again['messages'])
        self.assertEqual(sent['messages'][-1]['body'], request['text'])
        self.assertTrue(sent['players'][0]['ready'])
        self.assertIsNone(sent['messages'][-1]['choices'])
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider('Next beat.')):
            self.api(f'/api/saves/{save_id}/advance', self.override(save_id))
        error = self.api_error(f'/api/saves/{save_id}/messages', {**request, 'requestId': str(uuid.uuid4())})
        self.assertEqual(error['code'], 'stale_beat')

    def test_preview_and_generation_agree_without_replacing_saved_prompt(self):
        save_id = self.ready_save()
        with server.db() as conn:
            original = runtime_prompts.for_save(conn, save_id)
        preview = self.api(f'/api/saves/{save_id}/context')
        _, _, fake = self.advance_with_choices(save_id)
        self.assertEqual(preview['messages'], ai.chat_messages(fake.context))
        self.assertIn(narration_choices.instructions(), preview['messages'][0]['content'])
        self.assertIn(self.api(f'/api/saves/{save_id}')['players'][0]['id'], preview['messages'][0]['content'])
        with server.db() as conn:
            self.assertEqual(runtime_prompts.for_save(conn, save_id), original)
        state = self.api(f'/api/saves/{save_id}')
        ask = ai.chat_messages(ai.build_context(state, server.DATA, purpose='ask'))
        with patch.object(ai, 'summary_range', return_value=state['messages']):
            summary = ai.chat_messages(ai.build_summary_context(state))
        self.assertNotIn('tableforge-choices', json.dumps(ask))
        self.assertNotIn('tableforge-choices', json.dumps(summary))

    def test_legacy_saved_prompt_also_gets_output_format_only(self):
        save_id = self.ready_save()
        legacy = runtime_prompts.legacy_snapshot()
        with server.db() as conn:
            conn.execute('UPDATE saves SET narration_prompt_id=? WHERE id=?', (runtime_prompts.store(conn, legacy), save_id))
        preview = self.api(f'/api/saves/{save_id}/context')
        self.assertTrue(preview['messages'][0]['content'].startswith(legacy['instructions']))
        self.assertIn('Choice audiences', preview['messages'][0]['content'])
        with server.db() as conn:
            self.assertEqual(runtime_prompts.for_save(conn, save_id), legacy)

    def test_migration_preserves_old_messages(self):
        save_id = self.ready_save()
        before = self.api(f'/api/saves/{save_id}')['messages']
        with server.db() as conn:
            conn.execute('ALTER TABLE messages DROP COLUMN choices_json')
        server.initialize()
        self.assertEqual(self.api(f'/api/saves/{save_id}')['messages'], before)

    def test_location_marker_outside_footer_still_updates_location(self):
        save_id, _ = self.focused_save()
        fake = test_flow.FakeProvider('At the gate.' + footer([
            {'playerId': None, 'options': ['I inspect the gate.']}]) + '\n[Location: Area 1]')
        with patch.object(ai, 'current_provider', return_value=fake):
            result = self.api(f'/api/saves/{save_id}/advance', self.override(save_id))
        self.assertEqual(result['save']['location'], 1)
        self.assertNotIn('[Location:', result['messages'][-1]['body'])
        self.assertIsNotNone(result['messages'][-1]['choices'])
