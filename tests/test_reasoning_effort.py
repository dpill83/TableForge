"""Effort transport, fallback, compatibility, and the independent router policy."""
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch

import ai

spec = importlib.util.spec_from_file_location('router_policy',
    Path(__file__).resolve().parents[1] / 'deploy/laya/router_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class EffortTests(unittest.TestCase):
    def generate(self, env, route=None, model='gpt-6-luna'):
        context = {'purpose': 'ask', 'text': 'Explain the rule.', 'messages': [], 'title': 'Private',
                   'module': 'Synthetic module', 'askMessages': []}
        completion = {'choices': [{'message': {'content': 'Answer'}}], 'model': model + '-snapshot'}
        responses = []
        if route is not None:
            responses.append(route if isinstance(route, Exception) else
                             io.BytesIO(json.dumps(route).encode()))
        responses.append(io.BytesIO(json.dumps(completion).encode()))
        captures, metadata = [], []
        with patch.dict(os.environ, env, clear=True), \
                patch('ai.urllib.request.urlopen', side_effect=responses):
            result = ai.OpenAIProvider('private-key', model, 'http://router' if route is not None else '').generate(
                context, on_request=captures.append, on_metadata=metadata.append)
        return result, json.loads(captures[-1]), metadata[-1]['routing']

    def test_all_nine_model_effort_combinations_reach_openai(self):
        for tier, model in [('cheap', 'gpt-6-luna'), ('standard', 'gpt-6.1-sol'), ('heavy', 'gpt-6-astra')]:
            for effort in ('low', 'medium', 'xhigh'):
                with self.subTest(model=model, effort=effort):
                    result, payload, metadata = self.generate({}, {'tier': tier, 'model': model,
                                                                 'reasoning_effort': effort})
                    self.assertEqual(payload['model'], model)
                    self.assertEqual(payload['reasoning_effort'], effort)
                    self.assertEqual(result.routing['routerSelectedEffort'], effort)
                    self.assertEqual(metadata['requestedEffort'], effort)
                    self.assertEqual(metadata['effortSource'], 'router')

    def test_tier_override_then_default_and_router_precedence(self):
        env = {'TABLEFORGE_REASONING_EFFORT': 'low', 'TABLEFORGE_ROUTER_EFFORT_STANDARD': 'medium'}
        route = {'tier': 'standard', 'model': 'gpt-6.1-sol'}
        self.assertEqual(self.generate(env, route)[1]['reasoning_effort'], 'medium')
        self.assertEqual(self.generate(env, {**route, 'reasoning_effort': 'xhigh'})[1]['reasoning_effort'], 'xhigh')
        self.assertEqual(self.generate(env)[1]['reasoning_effort'], 'low')

    def test_tableforge_router_failure_uses_default_effort_not_tier(self):
        result, payload, metadata = self.generate(
            {'TABLEFORGE_REASONING_EFFORT': 'low', 'TABLEFORGE_ROUTER_EFFORT_STANDARD': 'xhigh'},
            urllib.error.URLError('connection refused'))
        self.assertEqual(payload['model'], 'gpt-6-luna')
        self.assertEqual(payload['reasoning_effort'], 'low')
        self.assertTrue(metadata['tableforgeRouterFallbackUsed'])

    def test_internal_fallback_keeps_router_effort(self):
        _, payload, metadata = self.generate({}, {'tier': 'standard', 'model': 'gpt-6.1-sol',
            'reasoning_effort': 'medium', 'router_internal_fallback_used': True})
        self.assertEqual(payload['reasoning_effort'], 'medium')
        self.assertTrue(metadata['routerInternalFallbackUsed'])
        self.assertFalse(metadata['tableforgeRouterFallbackUsed'])

    def test_old_router_and_disabled_configuration_preserve_payload(self):
        for route in (None, {'tier': 'cheap', 'model': 'gpt-6-luna'}):
            _, payload, metadata = self.generate({}, route)
            self.assertNotIn('reasoning_effort', payload)
            self.assertIsNone(metadata['requestedEffort'])
            self.assertEqual(metadata['effortSource'], 'provider default')

    def test_invalid_router_effort_never_reaches_provider(self):
        for effort in ('max', '<private>', 123, {}, [], True):
            _, payload, metadata = self.generate({}, {'model': 'gpt-6-luna', 'reasoning_effort': effort})
            self.assertNotIn('reasoning_effort', payload)
            self.assertIn('invalid', metadata['effortNotice'])
            self.assertNotIn('<private>', json.dumps(metadata))

    def test_unknown_model_omits_effort_and_preserves_model(self):
        _, payload, metadata = self.generate({'TABLEFORGE_REASONING_EFFORT': 'low'}, model='unknown-model')
        self.assertNotIn('reasoning_effort', payload)
        self.assertEqual(payload['model'], 'unknown-model')
        self.assertIn('support', metadata['effortNotice'])

    def test_invalid_configuration_fails_with_setting_name_without_secret(self):
        with patch.dict(os.environ, {'TABLEFORGE_REASONING_EFFORT': 'PRIVATE'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'TABLEFORGE_REASONING_EFFORT must'):
                ai.OpenAIProvider('key', 'gpt-6-luna')

    def test_effort_does_not_change_model_tier_and_handles_missing_or_tied_scores(self):
        fixtures = [('cheap', {'cheap': .7, 'standard': .2, 'heavy': .1}),
                    ('standard', {'cheap': .2, 'standard': .6, 'heavy': .2}),
                    ('heavy', {'cheap': .3, 'standard': .3, 'heavy': .4})]
        for expected, scores in fixtures:
            for level, effort in policy.EFFORT_MAP.items():
                self.assertEqual(policy.model_decision({'probabilities': scores})[0], expected)
                effort_scores = dict.fromkeys(policy.EFFORT_MAP, .1)
                effort_scores[level] = .8
                decision = policy.effort_decision({'probabilities': effort_scores})
                self.assertEqual(decision['reasoning_effort'], effort)
                self.assertFalse(decision['effort_fallback_used'])
        for answer in (None, {}, {'probabilities': {'light': .5, 'normal': .5, 'hard': 0}},
                       {'probabilities': {'light': float('nan'), 'normal': .5, 'hard': .5}}):
            decision = policy.effort_decision(answer)
            self.assertEqual(decision['reasoning_effort'], 'medium')
            self.assertTrue(decision['effort_fallback_used'])
