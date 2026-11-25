"""Run with the router's FastAPI environment; all HTTP is mocked."""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import router_service as router
import routing_settings


class RouterServiceTests(unittest.TestCase):
    def setUp(self):
        area = tempfile.TemporaryDirectory()
        self.addCleanup(area.cleanup)
        self.data = area.name
        env = patch.dict(os.environ, {'LAYA_ROUTING_DATA': self.data})
        env.start()
        self.addCleanup(env.stop)

    def classify(self, result):
        response = io.BytesIO(json.dumps(result).encode())
        with patch.object(router.urllib.request, 'urlopen', return_value=response) as opened:
            route = router.route(router.RouteRequest(prompt='Synthetic tabletop task'))
        return route, json.loads(opened.call_args.args[0].data)

    def test_all_nine_routes_use_one_classification_request(self):
        for tier in router.MODEL_MAP:
            for level, effort in [('light', 'low'), ('normal', 'medium'), ('hard', 'xhigh')]:
                with self.subTest(tier=tier, effort=effort):
                    scores = dict.fromkeys(router.MODEL_MAP, .1)
                    scores[tier] = .8
                    effort_scores = dict.fromkeys(('light', 'normal', 'hard'), .1)
                    effort_scores[level] = .8
                    route, body = self.classify({'answers': {
                        'model_tier': {'probabilities': scores},
                        'reasoning_effort': {'probabilities': effort_scores}}})
                    self.assertEqual(route['tier'], tier)
                    self.assertEqual(route['model'], router.MODEL_MAP[tier])
                    self.assertEqual(route['reasoning_effort'], effort)
                    self.assertFalse(route['router_internal_fallback_used'])
                    self.assertFalse(route['effort_fallback_used'])
                    self.assertEqual(set(body['questions']), {'model_tier', 'reasoning_effort'})

    def test_missing_effort_preserves_successful_tier_decision(self):
        route, _ = self.classify({'answers': {'model_tier': {
            'probabilities': {'cheap': .8, 'standard': .1, 'heavy': .1}}}})
        self.assertEqual(route['tier'], 'cheap')
        self.assertFalse(route['router_internal_fallback_used'])
        self.assertTrue(route['effort_fallback_used'])
        self.assertEqual(route['reasoning_effort'], 'medium')

    def test_invalid_model_scores_use_standard_internal_fallback(self):
        for result in ({}, [], {'answers': {'model_tier': {'probabilities': {'cheap': .9}}}}):
            route, _ = self.classify(result)
            self.assertEqual(route['tier'], 'standard')
            self.assertEqual(route['model'], router.MODEL_MAP['standard'])
            self.assertTrue(route['router_internal_fallback_used'])
            self.assertEqual(route['reasoning_effort'], 'medium')

    def test_transport_error_does_not_expose_exception_body(self):
        with patch.object(router.urllib.request, 'urlopen', side_effect=urllib.error.URLError('PRIVATE PROMPT')):
            route = router.route(router.RouteRequest(prompt='Synthetic tabletop task'))
        self.assertNotIn('PRIVATE', json.dumps(route))
        self.assertTrue(route['router_internal_fallback_used'])

    def test_existing_standard_threshold_decision_is_preserved(self):
        route, _ = self.classify({'answers': {'model_tier': {
            'probabilities': {'cheap': .1951, 'standard': .5117, 'heavy': .2932}},
            'reasoning_effort': {'probabilities': {'light': .8, 'normal': .1, 'hard': .1}}}})
        self.assertEqual(route['tier'], 'standard')
        self.assertEqual(route['reason'], 'defaulted to standard because routing was uncertain')
        self.assertEqual(route['reasoning_effort'], 'low')

    def test_service_defaults_endpoint_gives_the_environment_baseline(self):
        self.assertEqual(router.routing_defaults(), {'models': router.MODEL_MAP})

    def test_saved_service_settings_change_router_replies_on_the_next_request(self):
        result = {'answers': {'model_tier': {
            'probabilities': {'cheap': .15, 'standard': .7, 'heavy': .15}},
            'reasoning_effort': {'probabilities': {'light': .8, 'normal': .1, 'hard': .1}}}}
        route, _ = self.classify(result)
        self.assertEqual(route['model'], router.MODEL_MAP['standard'])
        self.assertEqual(route['reasoning_effort'], 'low')

        routing_settings.save(self.data, {'tiers': {'standard': {
            'model': 'gpt-6.2-sol', 'effort': 'high',
        }}, 'requests': {}})
        route, _ = self.classify(result)
        self.assertEqual((route['model'], route['reasoning_effort']), ('gpt-6.2-sol', 'high'))
        self.assertEqual(route['effort_override'], 'high')
        self.assertEqual(route['effort_reason'], 'Laya standard tier setting')

    def test_service_settings_apply_to_the_standard_internal_fallback(self):
        routing_settings.save(self.data, {'tiers': {'standard': {
            'model': 'gpt-6.2-sol', 'effort': 'default',
        }}, 'requests': {}})
        route, _ = self.classify({})
        self.assertTrue(route['router_internal_fallback_used'])
        self.assertEqual(route['model'], 'gpt-6.2-sol')
        self.assertEqual(route['effort_override'], 'default')
        self.assertIsNone(route['reasoning_effort'])


if __name__ == '__main__':
    unittest.main()
