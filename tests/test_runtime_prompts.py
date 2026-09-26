"""Exercise pinned Stage 3 instructions and explicit save upgrades without paid AI calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai
import module_context
import runtime_prompts
import server
import test_flow
from test_module_context import MODULE, ROOMS


class PromptAssetsTest(unittest.TestCase):
    def test_bundled_source_is_complete_and_adapter_has_precedence(self):
        prompt = runtime_prompts.default_snapshot()
        source = (runtime_prompts.PROMPT_DIR / 'stage3-run-prompt-v2.1.1.md').read_text(encoding='utf-8')
        self.assertTrue(prompt['instructions'].endswith(source))
        self.assertEqual(prompt['sourceSha256'], runtime_prompts.digest(source))
        self.assertLess(prompt['instructions'].index('These integration instructions take precedence'),
                        prompt['instructions'].index('# Stage 3'))
        self.assertEqual(runtime_prompts.decode(json.dumps(prompt)), prompt)

    def test_missing_empty_changed_and_invalid_utf8_assets_fail_clearly(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime_prompts, 'PROMPT_DIR', Path(directory)):
            path = Path(directory) / 'stage3-run-prompt-v2.1.1.md'
            for data in (None, b'', b'changed', b'\xff'):
                if data is not None:
                    path.write_bytes(data)
                with self.subTest(data=data), self.assertRaisesRegex(ValueError, 'Required AI-DM prompt'):
                    runtime_prompts.default_snapshot()

    def test_structured_data_keeps_opening_and_retrieved_numbers_with_room_focus(self):
        data = {'promptVersion': '1.1.5', 'party': [{'name': 'George', 'ac': 18}],
                'hook': {'playerBriefing': 'Find the ledger.'}, 'rooms': ROOMS,
                'statBlocks': [{'name': 'Muxus, the Spared', 'ac': 17}, {'name': 'Star Beast', 'ac': 22}]}
        adventure = module_context.Adventure(MODULE, data)
        _, focus = adventure.assemble(5, [('action', 'I read the prompt book.')])
        supplied = adventure.structured_context(focus)
        self.assertEqual(supplied['party'], data['party'])
        self.assertEqual(supplied['hook'], data['hook'])
        self.assertIn(8, [r['roomNumber'] for r in supplied['rooms']])
        self.assertNotIn(9, [r['roomNumber'] for r in supplied['rooms']])
        self.assertEqual(supplied['statBlocks'], [{'name': 'Muxus, the Spared', 'ac': 17}])


class PromptFlowTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    ready_save = test_flow.FlowTest.ready_save
    cartridge_zip = test_flow.FlowTest.cartridge_zip
    override = test_flow.FlowTest.override

    def new_save(self):
        cartridge = self.cartridge_zip({
            'manifest.json': json.dumps({'format': 'tableforge-adventure', 'formatVersion': 1, 'title': 'Test', 'resources': {}}),
            'module.md': '# Adventure\nThe hook begins in the market.',
            'run-data.json': json.dumps({'promptVersion': '1.1.5', 'party': [{'name': 'George', 'ac': 18}],
                                         'hook': {'playerBriefing': 'Find the ledger.'}})})
        return self.api('/api/saves', {'cartridgeId': cartridge['id'], 'players': [{'name': 'Dan', 'character': 'George'}]})

    def make_legacy(self, save_id):
        with server.db() as conn:
            prompt = runtime_prompts.legacy_snapshot()
            conn.execute('UPDATE saves SET narration_prompt_id=? WHERE id=?', (runtime_prompts.store(conn, prompt), save_id))
        return prompt

    def test_first_narration_then_advance_and_resume_keep_the_saved_instructions(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        preview = self.api(f'/api/saves/{save_id}/context')
        prompt = runtime_prompts.default_snapshot()
        self.assertTrue(preview['messages'][0]['content'].startswith(prompt['instructions']))
        self.assertIn('Find the ledger.', preview['messages'][0]['content'])
        self.assertIn('"ac": 18', preview['messages'][0]['content'])
        self.assertIn('first AI-DM narration', preview['messages'][-1]['content'])
        self.assertEqual(preview['report']['narrationPrompt']['version'], '2.1.1')
        self.assertIsNone(preview['promptUpdate'])
        fake = test_flow.FakeProvider('Where is George this morning?')
        self.api(f'/api/saves/{save_id}/ready', {'playerId': player, 'ready': True})
        with patch.object(ai, 'current_provider', return_value=fake):
            self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        self.assertEqual(preview['messages'], ai.chat_messages(fake.context))
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'At the market.'})
        with patch.object(ai, 'current_provider', return_value=fake):
            self.api(f'/api/saves/{save_id}/advance', {'beat': 2})
        self.assertFalse(fake.context['opening'])
        self.assertEqual(fake.context['narrationPrompt'], prompt)
        self.api(f'/api/saves/{save_id}/end-session', {'playerId': player, 'note': 'At the market.'})
        self.api(f'/api/saves/{save_id}/start-session', {'playerId': player})
        with patch.object(runtime_prompts, 'PROMPT_DIR', self.path / 'absent'):
            server.initialize()
            resumed = self.api(f'/api/saves/{save_id}/context')
        self.assertTrue(resumed['messages'][0]['content'].startswith(prompt['instructions']))
        self.assertIn('Do not restart the session opening', resumed['messages'][0]['content'])
        self.assertNotIn('first AI-DM narration', resumed['messages'][-1]['content'])
        self.assertIn('could not be loaded', resumed['promptUpdateError'])

    def test_first_request_honors_existing_player_contributions(self):
        save_id = self.ready_save()
        context = ai.build_context(self.api(f'/api/saves/{save_id}'), self.path)
        self.assertTrue(context['opening'])
        messages = ai.chat_messages(context)
        self.assertIn('George: I look ahead.', [m['content'] for m in messages])
        self.assertIn('first AI-DM narration', messages[-1]['content'])

    def test_missing_bundle_prevents_new_save_without_partial_writes(self):
        state = self.new_save()
        with patch.object(runtime_prompts, 'PROMPT_DIR', self.path / 'absent'):
            error = self.api_error('/api/saves', {'cartridgeId': state['cartridge']['id'],
                'players': [{'name': 'Dan', 'character': 'George'}]})
        self.assertIn('Required AI-DM prompt', error['error'])
        self.assertEqual(len(self.api('/api/saves')['saves']), 1)

    def test_saved_prompt_survives_new_default_and_backup_restore(self):
        save_id = self.ready_save()
        original = self.api(f'/api/saves/{save_id}/context')['messages']
        changed = runtime_prompts.make_snapshot('stage3', 'future', '2', 'Future instructions')
        backup = self.api('/api/backups', {})
        with patch.object(runtime_prompts, 'default_snapshot', return_value=changed):
            server.initialize()
            preview = self.api(f'/api/saves/{save_id}/context')
            self.assertEqual(preview['messages'], original)
            self.assertEqual(preview['promptUpdate'], changed)
            self.api(f'/api/backups/{backup["name"]}/restore', {})
            self.assertEqual(self.api(f'/api/saves/{save_id}/context')['messages'], original)

    def test_damaged_saved_prompt_blocks_generation_without_ready_or_history_changes(self):
        save_id = self.ready_save()
        before = self.api(f'/api/saves/{save_id}')
        with server.db() as conn:
            prompt = runtime_prompts.for_save(conn, save_id)
            prompt['instructions'] = 'damaged'
            conn.execute('UPDATE narration_prompts SET snapshot=? WHERE sha256=?', (json.dumps(prompt), prompt['sha256']))
        with patch.object(ai, 'current_provider') as provider:
            error = self.api_error(f'/api/saves/{save_id}/advance', {'beat': 1})
            provider.assert_not_called()
        self.assertIn('missing or damaged', error['error'])
        after = self.api(f'/api/saves/{save_id}')
        self.assertEqual(after['save'], before['save'])
        self.assertEqual(after['players'], before['players'])
        self.assertEqual(after['messages'], before['messages'])
        self.assertEqual(server.GENERATING, {})

    def test_legacy_upgrade_is_explicit_guarded_attributed_and_preserves_play(self):
        save_id = self.ready_save()
        legacy = self.make_legacy(save_id)
        self.api(f'/api/saves/{save_id}/advance', {'beat': 1})
        before = self.api(f'/api/saves/{save_id}')
        player = before['players'][0]['id']
        preview = self.api(f'/api/saves/{save_id}/context')
        self.assertTrue(preview['messages'][0]['content'].startswith(legacy['instructions']))
        self.assertNotIn('# Stage 3', preview['messages'][0]['content'])
        target = preview['promptUpdate']
        payload = {'playerId': player, 'pilot': True, 'confirm': True,
                   'fromSha256': legacy['sha256'], 'toSha256': target['sha256']}
        route = f'/api/saves/{save_id}/narration-prompt'
        for change in ({'pilot': False}, {'confirm': False}, {'playerId': 'absent'},
                       {'fromSha256': 'stale'}, {'toSha256': 'stale'}):
            self.assertIn('error', self.api_error(route, {**payload, **change}))
        server.GENERATING[save_id] = 'advance'
        self.assertIn('already responding', self.api_error(route, payload)['error'])
        server.GENERATING.clear()
        with patch.object(runtime_prompts, 'PROMPT_DIR', self.path / 'absent'):
            self.assertIn('Required AI-DM prompt', self.api_error(route, payload)['error'])
        after = self.api(route, payload)
        self.assertEqual(after['messages'], before['messages'])
        self.assertEqual(after['players'], before['players'])
        self.assertEqual(after['save']['beat'], before['save']['beat'])
        [event] = [e for e in after['events'] if e['kind'] == 'prompt_upgrade']
        self.assertEqual(event['player_id'], player)
        self.assertEqual(json.loads(event['body'])['from']['sha256'], legacy['sha256'])
        with server.db() as conn:
            self.assertEqual(runtime_prompts.for_save(conn, save_id), target)
            self.assertEqual(runtime_prompts.decode(conn.execute('SELECT snapshot FROM narration_prompts WHERE sha256=?',
                             (legacy['sha256'],)).fetchone()[0]), legacy)
        upgraded = self.api(f'/api/saves/{save_id}/context')
        self.assertIsNone(upgraded['promptUpdate'])
        self.assertIn('Do not restart the session opening', upgraded['messages'][0]['content'])
        self.assertIn('changed', self.api_error(route, payload)['error'])

    def test_pilot_and_summary_do_not_receive_narration_contract(self):
        save_id = self.ready_save()
        state = self.api(f'/api/saves/{save_id}')
        fake = test_flow.FakeProvider('Use the encounter tactics.')
        with patch.object(ai, 'current_provider', return_value=fake):
            self.api(f'/api/saves/{save_id}/ask', {'playerId': state['players'][0]['id'], 'text': 'What are its tactics?'})
        operational = ai.chat_messages(fake.context)
        self.assertTrue(operational[0]['content'].startswith(ai.ASK_PROMPT))
        self.assertNotIn('narrationPrompt', fake.context)
        self.assertNotIn('# Stage 3', json.dumps(operational))
        for i in range(4):
            state['messages'].append({'id': i + 100, 'kind': 'ai', 'name': 'AI-DM', 'body': 'A' * 15000})
        summary = ai.chat_messages(ai.build_summary_context(state))
        self.assertTrue(summary[0]['content'].startswith(ai.SUMMARY_PROMPT))
        self.assertNotIn('# Stage 3', json.dumps(summary))


if __name__ == '__main__':
    unittest.main()
