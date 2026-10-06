"""Run with the router's FastAPI environment; all HTTP is mocked."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import router_service as router


class RouterServiceTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
