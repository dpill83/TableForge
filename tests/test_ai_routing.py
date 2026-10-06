"""Router selection, privacy boundaries, and configured-model fallback."""
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

import ai
import metering


def response(data):
    return io.BytesIO(json.dumps(data).encode('utf-8'))


class RoutingTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.context = {
            'purpose': 'advance', 'title': 'Secret adventure', 'module': 'SECRET MODULE' * 10000,
            'beat': 2, 'narrationPrompt': {'instructions': 'PRIVATE INSTRUCTIONS'},
            'messages': [
                {'kind': 'player', 'name': 'Old', 'body': 'OLD HISTORY' * 10000},
                {'kind': 'ai', 'name': 'AI-DM', 'body': 'A locked door stands ahead.'},
                {'kind': 'player', 'name': 'A', 'body': 'I inspect the lock.'},
                {'kind': 'player', 'name': 'B', 'body': 'I check for traps.'},
            ],
        }
        self.usage = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}

    def completion(self, model=None):
        data = {'choices': [{'message': {'content': 'The door opens.'}}],
                'usage': self.usage, 'service_tier': 'default'}
        if model:
            data['model'] = model
        return response(data)

    def test_disabled_preserves_payload_capture_usage_and_no_router_call(self):
        for url in (None, '', '   '):
            with self.subTest(url=url):
                if url is not None:
                    os.environ['TABLEFORGE_ROUTER_URL'] = url
                captured = []
                with patch('ai.urllib.request.urlopen', return_value=self.completion()) as opened:
                    result = ai.OpenAIProvider('secret-key', 'configured-model').generate(
                        self.context, on_request=captured.append)
                opened.assert_called_once()
                request = opened.call_args.args[0]
                self.assertEqual(request.full_url, ai.OPENAI_URL)
                self.assertEqual(opened.call_args.kwargs['timeout'], ai.OPENAI_TIMEOUT)
                self.assertEqual(json.loads(request.data), {
                    'model': 'configured-model', 'messages': ai.chat_messages(self.context)})
                self.assertEqual(captured, [request.data.decode()])
                self.assertEqual(result.model, 'configured-model')
                self.assertEqual(result.usage, self.usage)
                self.assertFalse(result.routing['enabled'])
                self.assertFalse(result.routing['fallback'])
                self.assertFalse(result.routing['routerContacted'])
                self.assertFalse(result.routing['routerInternalFallbackUsed'])
                self.assertFalse(result.routing['tableforgeRouterFallbackUsed'])
                self.assertIsNone(result.routing['model'])
                self.assertEqual(result.configured_model, 'configured-model')
                self.assertEqual(result.requested_model, 'configured-model')
                self.assertIsNone(result.reported_model)

    def test_cheap_standard_heavy_routes_capture_and_meter_selected_model(self):
        for tier, model in [('cheap', 'gpt-6-luna'), ('standard', 'gpt-6-sol'), ('heavy', 'gpt-6-astra')]:
            with self.subTest(tier=tier):
                route = {'tier': tier, 'model': model, 'reason': 'Task classification', 'scores': {tier: 0.9},
                         'router_internal_fallback_used': False}
                captured = []
                provider = ai.OpenAIProvider('secret-key', 'configured-model', 'http://router/route')
                with patch('ai.urllib.request.urlopen', side_effect=[response(route), self.completion()]) as opened:
                    with self.assertLogs('ai', level='INFO') as logs:
                        result = provider.generate(self.context, on_request=captured.append)
                first, second = opened.call_args_list
                router_request = first.args[0]
                self.assertEqual(router_request.get_method(), 'POST')
                self.assertEqual(router_request.full_url, 'http://router/route')
                self.assertEqual(first.kwargs['timeout'], 4)
                self.assertIsNone(router_request.get_header('Authorization'))
                self.assertEqual(router_request.get_header('Content-type'), 'application/json')
                payload = json.loads(router_request.data)
                self.assertEqual(set(payload), {'prompt'})
                self.assertIn('Purpose: advance', payload['prompt'])
                self.assertIn('I inspect the lock.', payload['prompt'])
                self.assertIn('I check for traps.', payload['prompt'])
                for secret in ('SECRET MODULE', 'OLD HISTORY', 'PRIVATE INSTRUCTIONS', 'secret-key'):
                    self.assertNotIn(secret, payload['prompt'])
                    self.assertNotIn(secret, ''.join(logs.output))
                self.assertEqual(json.loads(second.args[0].data)['model'], model)
                self.assertEqual(captured, [second.args[0].data.decode()])
                self.assertEqual(result.routing, {**ai.routing_state(True), 'tier': tier, 'model': model,
                                                 'effortSource': 'provider default',
                                                 'reason': 'Task classification', 'scores': {tier: 0.9},
                                                 'routerContacted': True, 'routerInternalFallbackUsed': False})
                self.assertEqual(result.model, model)
                self.assertEqual(result.usage, self.usage)
                self.assertEqual(result.service_tier, 'default')
                values = metering.record(result.model, result.usage, result.service_tier)
                self.assertEqual(values[0], model)
                self.assertIsNotNone(values[7])
                self.assertEqual(provider.model, 'configured-model')

    def test_reported_model_takes_precedence_over_route(self):
        with patch('ai.urllib.request.urlopen', side_effect=[response({'model': 'gpt-6-sol'}),
                                                            self.completion('gpt-6-sol-snapshot')]):
            result = ai.OpenAIProvider('key', 'fallback', 'http://router').generate(self.context)
        self.assertEqual(result.model, 'gpt-6-sol-snapshot')
        self.assertEqual(result.routing['model'], 'gpt-6-sol')
        self.assertEqual(result.requested_model, 'gpt-6-sol')
        self.assertEqual(result.reported_model, 'gpt-6-sol-snapshot')
        self.assertEqual(result.configured_model, 'fallback')

    def test_router_failures_fall_back_without_leaking_error_body(self):
        failures = [urllib.error.URLError('PRIVATE REQUEST'), TimeoutError('PRIVATE REQUEST'),
                    OSError('PRIVATE REQUEST'),
                    urllib.error.HTTPError('http://router', 503, 'PRIVATE REQUEST', {}, io.BytesIO(b'PRIVATE REQUEST'))]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch('ai.urllib.request.urlopen', side_effect=[failure, self.completion()]) as opened:
                    with self.assertLogs('ai', level='WARNING') as logs:
                        result = ai.OpenAIProvider('key', 'configured-model', 'http://router').generate(self.context)
                self.assertEqual(result.model, 'configured-model')
                self.assertTrue(result.routing['fallback'])
                self.assertTrue(result.routing['tableforgeRouterFallbackUsed'])
                self.assertEqual(result.routing['routerContacted'], isinstance(failure, urllib.error.HTTPError))
                self.assertIsNone(result.routing['routerInternalFallbackUsed'])
                self.assertIsNone(result.routing['model'])
                self.assertTrue(result.routing['fallbackReason'])
                self.assertNotIn('PRIVATE REQUEST', json.dumps(result.routing))
                self.assertEqual(json.loads(opened.call_args.args[0].data)['model'], 'configured-model')
                self.assertNotIn('PRIVATE REQUEST', ''.join(logs.output))

    def test_malformed_router_response_falls_back(self):
        bodies = [b'not json', b'\xff', b'[]', b'null', b'{}', b'{"model":null}',
                  b'{"model":42}', b'{"model":{}}', b'{"model":"  "}',
                  b'{"model":"bad\\nmodel"}', b'{"model":"' + b'a' * 201 + b'"}',
                  b'x' * (ai.ROUTER_RESPONSE_CAP + 1), b'[' * 1500 + b']' * 1500]
        for body in bodies:
            with self.subTest(body=body[:40]):
                with patch('ai.urllib.request.urlopen', side_effect=[io.BytesIO(body), self.completion()]):
                    with self.assertLogs('ai', level='WARNING'):
                        result = ai.OpenAIProvider('key', 'fallback', 'http://router').generate(self.context)
                self.assertEqual(result.model, 'fallback')
                self.assertTrue(result.routing['fallback'])
                self.assertTrue(result.routing['routerContacted'])
                self.assertTrue(result.routing['tableforgeRouterFallbackUsed'])
                self.assertIsNone(result.routing['routerInternalFallbackUsed'])

    def test_configured_fallback_precedence_and_router_env(self):
        for aidm, legacy, expected in [('custom', 'old', 'custom'), ('', 'old', 'old'), ('', '', 'gpt-4o-mini')]:
            with self.subTest(aidm=aidm, legacy=legacy), patch.dict(os.environ, {
                    'TABLEFORGE_OPENAI_API_KEY': 'key', 'TABLEFORGE_AIDM_MODEL': aidm,
                    'TABLEFORGE_MODEL': legacy, 'TABLEFORGE_ROUTER_URL': ' http://router/route '}):
                provider = ai.current_provider()
                self.assertEqual(provider.router_url, 'http://router/route')
                with patch('ai.urllib.request.urlopen', side_effect=[TimeoutError(), self.completion()]):
                    with self.assertLogs('ai', level='WARNING'):
                        result = provider.generate(self.context)
                self.assertEqual(result.model, expected)

    def test_pilot_request_takes_precedence_over_table_messages(self):
        self.context.update(purpose='ask', pilot=[
            {'kind': 'player', 'name': 'Pilot', 'body': 'An old question.'},
            {'kind': 'ai', 'name': 'AI', 'body': 'Earlier answer.'},
            {'kind': 'player', 'name': 'Pilot', 'body': 'Would the monster retreat?'}])
        prompt = ai.routing_description(self.context)
        self.assertIn('Purpose: ask', prompt)
        self.assertIn('Would the monster retreat?', prompt)
        self.assertNotIn('I inspect the lock.', prompt)
        self.assertNotIn('An old question.', prompt)

    def test_summary_routes_task_with_bounded_recent_request(self):
        self.context.update(purpose='summary', previousSummary='PRIVATE SUMMARY' * 10000)
        prompt = ai.routing_description(self.context)
        self.assertIn('Purpose: summary', prompt)
        self.assertIn('cumulative campaign summary', prompt)
        self.assertIn('I check for traps.', prompt)
        self.assertNotIn('PRIVATE SUMMARY', prompt)
        self.assertNotIn('OLD HISTORY', prompt)
        with patch('ai.urllib.request.urlopen', side_effect=[response({'model': 'gpt-6-sol'}), self.completion()]):
            result = ai.OpenAIProvider('key', 'fallback', 'http://router').generate(self.context)
        self.assertEqual(result.model, 'gpt-6-sol')

    def test_description_is_bounded_and_keeps_newest_request(self):
        self.context['messages'] = [{'kind': 'player', 'name': 'A' * 1000,
                                     'body': 'OLD' * 10000} for _ in range(20)]
        self.context['messages'].append({'kind': 'player', 'name': 'B', 'body': 'LATEST REQUEST'})
        self.context['combatOutcomes'] = [{'body': 'OUTCOME' * 10000}]
        prompt = ai.routing_description(self.context)
        self.assertLessEqual(len(prompt), ai.ROUTER_PROMPT_CAP)
        self.assertIn('LATEST REQUEST', prompt)

    def test_opening_and_no_contributions_still_describe_task(self):
        self.context.update(opening=True, messages=[])
        self.assertIn('opening narration', ai.routing_description(self.context))
        self.context['opening'] = False
        self.assertIn('Continue RPG narration', ai.routing_description(self.context))

    def test_bad_router_url_falls_back(self):
        with patch('ai.urllib.request.urlopen', return_value=self.completion()) as opened:
            with self.assertLogs('ai', level='WARNING'):
                result = ai.OpenAIProvider('key', 'fallback', 'invalid-url').generate(self.context)
        self.assertEqual(result.model, 'fallback')
        opened.assert_called_once()

    def test_mock_provider_does_not_route(self):
        os.environ['TABLEFORGE_ROUTER_URL'] = 'http://router'
        with patch('ai.urllib.request.urlopen') as opened:
            result = ai.current_provider().generate(self.context)
        self.assertIn('Mock AI-DM', result)
        opened.assert_not_called()

    def test_model_selection_is_per_request(self):
        provider = ai.OpenAIProvider('key', 'fallback', 'http://router')
        with patch('ai.urllib.request.urlopen', side_effect=[response({'model': 'gpt-6-astra'}),
                                                           self.completion(), TimeoutError(), self.completion()]):
            first = provider.generate(self.context)
            with self.assertLogs('ai', level='WARNING'):
                second = provider.generate(self.context)
        self.assertEqual(first.model, 'gpt-6-astra')
        self.assertEqual(second.model, 'fallback')

    def test_metadata_callback_precedes_provider_request_and_survives_failure(self):
        metadata = []
        route = {'tier': 'cheap', 'model': 'gpt-6-luna', 'reason': 'cheap choice'}
        def opened(request, **kwargs):
            if request.full_url == 'http://router':
                return response(route)
            self.assertEqual(metadata[0]['requestedModel'], 'gpt-6-luna')
            raise urllib.error.URLError('provider unavailable')
        with patch('ai.urllib.request.urlopen', side_effect=opened):
            with self.assertRaisesRegex(ValueError, 'OpenAI request failed'):
                ai.OpenAIProvider('key', 'default', 'http://router').generate(
                    self.context, on_metadata=metadata.append)
        self.assertEqual(metadata[0]['configuredModel'], 'default')
        self.assertEqual(metadata[0]['routing']['tier'], 'cheap')

    def test_optional_scores_are_bounded_numeric_metadata_and_reason_is_not_logged(self):
        scores = {'cheap': 0.49, 'standard': 0.42, 'heavy': 0.09, 'private': 'SECRET'}
        for supplied, expected in [(scores, {key: scores[key] for key in ('cheap', 'standard', 'heavy')}),
                                   ({'cheap': True, 'standard': '0.4', 'heavy': float('nan')}, None),
                                   ({'cheap': -0.1, 'standard': 2, 'heavy': 10 ** 400}, None),
                                   (['bad'], None)]:
            with self.subTest(scores=supplied):
                with patch('ai.urllib.request.urlopen', side_effect=[
                        response({'model': 'gpt-6-luna', 'reason': 'PRIVATE REQUEST', 'scores': supplied}),
                        self.completion()]):
                    with self.assertLogs('ai', level='INFO') as logs:
                        result = ai.OpenAIProvider('key', 'default', 'http://router').generate(self.context)
                self.assertEqual(result.routing['scores'], expected)
                self.assertNotIn('PRIVATE REQUEST', ''.join(logs.output))
                self.assertFalse(result.routing['fallback'])

    def test_router_internal_fallback_uses_returned_model_and_keeps_tableforge_fallback_false(self):
        reason = 'Laya unavailable, using safe fallback'
        for flags in [{}, {'router_internal_fallback_used': True}, {'routerInternalFallbackUsed': True},
                      {'fallback': True}, {'fallback_used': True}, {'fallbackUsed': True}]:
            with self.subTest(flags=flags):
                route = {'tier': 'standard', 'model': 'gpt-6.1-sol', 'reason': reason, **flags}
                with patch('ai.urllib.request.urlopen', side_effect=[response(route), self.completion()]) as opened:
                    with self.assertLogs('ai', level='INFO') as logs:
                        result = ai.OpenAIProvider('key', 'gpt-6-luna', 'http://router').generate(self.context)
                self.assertTrue(result.routing['routerContacted'])
                self.assertTrue(result.routing['routerInternalFallbackUsed'])
                self.assertEqual(result.routing['routerInternalFallbackReason'], reason)
                self.assertFalse(result.routing['tableforgeRouterFallbackUsed'])
                self.assertIsNone(result.routing['tableforgeRouterFallbackReason'])
                self.assertFalse(result.routing['fallback'])
                self.assertEqual(json.loads(opened.call_args.args[0].data)['model'], 'gpt-6.1-sol')
                self.assertNotIn(reason, ''.join(logs.output))

    def test_internal_fallback_flags_are_explicit_and_unrecognized_reasons_stay_unknown(self):
        for flags, reason, expected, detail in [
                ({'router_internal_fallback_used': False}, 'Laya unavailable, using safe fallback', False, None),
                ({}, 'No fallback was needed', None, None),
                ({'fallback': 'false'}, 'Task classification', None, None),
                ({'fallback': True, 'fallback_reason': 'Laya timeout'}, 'Safe decision', True, 'Laya timeout')]:
            with self.subTest(flags=flags, reason=reason):
                with patch('ai.urllib.request.urlopen', side_effect=[
                        response({'model': 'gpt-6.1-sol', 'reason': reason, **flags}), self.completion()]):
                    result = ai.OpenAIProvider('key', 'default', 'http://router').generate(self.context)
                self.assertIs(result.routing['routerInternalFallbackUsed'], expected)
                self.assertEqual(result.routing['routerInternalFallbackReason'], detail)
                self.assertFalse(result.routing['tableforgeRouterFallbackUsed'])

    def test_connection_refused_uses_safe_tableforge_reason(self):
        error = urllib.error.URLError(ConnectionRefusedError('PRIVATE REQUEST'))
        with patch('ai.urllib.request.urlopen', side_effect=[error, self.completion()]):
            with self.assertLogs('ai', level='WARNING') as logs:
                result = ai.OpenAIProvider('key', 'default', 'http://router').generate(self.context)
        self.assertFalse(result.routing['routerContacted'])
        self.assertTrue(result.routing['tableforgeRouterFallbackUsed'])
        self.assertEqual(result.routing['tableforgeRouterFallbackReason'], 'Router connection refused')
        self.assertIsNone(result.routing['routerInternalFallbackUsed'])
        self.assertNotIn('PRIVATE REQUEST', ''.join(logs.output))

    def test_legacy_metadata_only_maps_the_known_tableforge_field(self):
        for fallback in (False, True):
            old = {'enabled': True, 'fallback': fallback, 'fallbackReason': 'legacy reason',
                   'reason': 'Laya unavailable, using safe fallback'}
            original = dict(old)
            result = metering.routing_metadata(old)
            self.assertIsNone(result['routerContacted'])
            self.assertIsNone(result['routerInternalFallbackUsed'])
            self.assertIsNone(result['routerInternalFallbackReason'])
            self.assertIs(result['tableforgeRouterFallbackUsed'], fallback)
            self.assertEqual(result['tableforgeRouterFallbackReason'], 'legacy reason')
            self.assertEqual(old, original)
        self.assertIsNone(metering.routing_metadata(None))
        self.assertIsNone(metering.routing_metadata({})['tableforgeRouterFallbackUsed'])
