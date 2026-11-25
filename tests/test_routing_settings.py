"""Configure routing interactively and exercise the resulting provider requests."""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import ai
import configure_ai_routing as editor
import routing_settings


def response(data):
    return io.BytesIO(json.dumps(data).encode())


class RoutingSettingsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = temp.name
        env = patch.dict(os.environ, {
            'TABLEFORGE_ROUTER_URL': 'http://router/route',
            'TABLEFORGE_OPENAI_API_KEY': 'test-key',
            'TABLEFORGE_AIDM_MODEL': 'gpt-6.1-sol',
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.context = {'title': 'Test', 'module': 'A test adventure', 'messages': [],
                        'narrationPrompt': {'instructions': 'Continue the adventure.'}}

    def test_terminal_search_validates_selection_and_saves_for_next_request(self):
        initial_provider = ai.current_provider(self.data)
        inputs = ['2', '6.2', '1', '6', '10', '1']
        with patch('builtins.input', side_effect=inputs), patch('builtins.print'), \
                patch.object(editor, 'openai_json', side_effect=[
                    {'data': [{'id': 'gpt-6.2-sol'}, {'id': 'gpt-4o-mini'}]}, {'choices': [{}]},
                ]) as provider_api:
            editor.run(self.data)
        self.assertEqual(provider_api.call_args_list[0].args, (editor.MODELS_URL,))
        self.assertEqual(provider_api.call_args.args[1]['reasoning_effort'], 'medium')
        self.assertEqual(routing_settings.load(self.data)['tiers']['standard'],
                         {'model': 'gpt-6.2-sol', 'effort': 'medium'})
        provider = ai.current_provider(self.data)
        self.assertEqual(initial_provider.tier_overrides, {})
        with patch('ai.urllib.request.urlopen', side_effect=[
            response({'tier': 'standard', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'low'}),
            response({'choices': [{'message': {'content': 'The scene continues.'}}]}),
        ]) as opened:
            result = provider.generate({**self.context, 'purpose': 'advance'})
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual((payload['model'], payload['reasoning_effort']), ('gpt-6.2-sol', 'medium'))
        self.assertEqual(result.routing['model'], 'gpt-6.1-sol')
        self.assertEqual(result.routing['modelOverride'], 'gpt-6.2-sol')
        self.assertEqual(result.routing['routerSelectedEffort'], 'low')
        self.assertEqual(result.routing['effortSource'], 'Laya tier settings')

    def test_preset_can_be_overridden_for_opening_and_pilot_ask(self):
        os.environ['TABLEFORGE_ROUTING_POLICY'] = 'table-play'
        routing_settings.save(self.data, {'tiers': {
            'standard': {'model': 'gpt-6.2-sol', 'effort': 'high'},
        }, 'requests': {
            'opening': {'mode': 'fixed', 'model': 'gpt-6-astra', 'effort': 'xhigh'},
            'ask': {'mode': 'laya', 'effort': 'default'},
        }})
        provider = ai.current_provider(self.data)
        self.assertEqual(provider.select_model({'openingStage': 'travel'})[0], 'gpt-6-astra')
        self.assertEqual(provider.select_model({'combatResume': {'id': 'encounter'}})[1]['policy'], 'table-play')
        with patch('ai.urllib.request.urlopen', side_effect=[
            response({'tier': 'standard', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'low'}),
            response({'choices': [{'message': {'content': 'An answer.'}}]}),
        ]) as opened:
            result = provider.generate({**self.context, 'purpose': 'ask'})
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload['model'], 'gpt-6.2-sol')
        self.assertNotIn('reasoning_effort', payload)
        self.assertEqual(result.routing['effortSource'], 'request settings')
        with patch('ai.urllib.request.urlopen', side_effect=TimeoutError):
            fallback, metadata = provider.select_model({'purpose': 'ask'})
        self.assertEqual(fallback, 'gpt-6.1-sol')
        self.assertTrue(metadata['tableforgeRouterFallbackUsed'])

    def test_failed_compatibility_check_preserves_saved_routing(self):
        original = {'tiers': {}, 'requests': {'opening': {
            'mode': 'fixed', 'model': 'gpt-6-astra', 'effort': 'xhigh',
        }}}
        routing_settings.save(self.data, original)
        with patch('builtins.input', side_effect=['5', '', 'embed', '1', '1', '10', '1', '11']), \
                patch('builtins.print'), patch.object(editor, 'openai_json', side_effect=[
                    {'data': [{'id': 'text-embedding-3-large'}]}, ValueError('OpenAI returned HTTP 400.'),
                ]):
            editor.run(self.data)
        self.assertEqual(routing_settings.load(self.data), original)

    def test_second_editor_cannot_overwrite_changes_from_its_old_snapshot(self):
        before = routing_settings.load(self.data)
        after = {'tiers': {'standard': {'model': 'gpt-6.2-sol'}}, 'requests': {}}
        routing_settings.save(self.data, after, expected=before)
        with self.assertRaisesRegex(ValueError, 'Another editor saved'):
            routing_settings.save(self.data, before, expected=before)
        self.assertEqual(routing_settings.load(self.data), after)
