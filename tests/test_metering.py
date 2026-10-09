"""Billing math uses total output once and discounts only reported cache hits."""
import unittest

import metering


class MeteringTests(unittest.TestCase):
    def test_sol_61_cached_input_writes_and_reasoning_are_billed_once(self):
        usage = {'prompt_tokens': 1000, 'completion_tokens': 200, 'total_tokens': 1200,
                 'prompt_tokens_details': {'cached_tokens': 400, 'cache_write_tokens': 100},
                 'completion_tokens_details': {'reasoning_tokens': 150}}
        values = metering.record('gpt-6.1-sol-2026-10-01', usage, 'default')
        self.assertEqual(values[1:6], (1000, 400, 100, 200, 1200))
        self.assertAlmostEqual(values[6], (500 * 2 + 400 * .10 + 100 * 2.50 + 200 * 10) / 1e6)
        self.assertEqual(metering.reasoning_tokens(usage), 150)
        usage['completion_tokens_details']['reasoning_tokens'] = 0
        self.assertEqual(metering.reasoning_tokens(usage), 0)
        self.assertEqual(metering.record('gpt-6.1-sol', usage)[6], values[6])

    def test_missing_reasoning_does_not_block_pricing_or_invent_a_breakdown(self):
        usage = {'prompt_tokens': 12, 'completion_tokens': 3}
        values = metering.record('gpt-6.1-sol', usage)
        self.assertEqual(values[5], 15)
        self.assertAlmostEqual(values[6], (12 * 2 + 3 * 10) / 1e6)
        self.assertIsNone(metering.reasoning_tokens(usage))
        for details in (None, [], {'reasoning_tokens': -1}, {'reasoning_tokens': True},
                        {'reasoning_tokens': '2'}, {'reasoning_tokens': 4}):
            with self.subTest(details=details):
                self.assertIsNone(metering.reasoning_tokens({**usage, 'completion_tokens_details': details}))

    def test_unknown_models_and_service_tiers_keep_usage_without_cost(self):
        usage = {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15}
        for model, tier in [('unknown-model', None), ('gpt-6.1-sol', 'priority'), (None, None)]:
            with self.subTest(model=model, tier=tier):
                values = metering.record(model, usage, tier)
                self.assertEqual((values[1], values[4], values[5]), (12, 3, 15))
                self.assertIsNone(values[6])

    def test_invalid_usage_never_produces_a_misleading_cost(self):
        for usage in (None, [], {}, {'prompt_tokens': True, 'completion_tokens': 3},
                      {'prompt_tokens': 12, 'completion_tokens': -1},
                      {'prompt_tokens': 12, 'completion_tokens': 3, 'prompt_tokens_details': []},
                      {'prompt_tokens': 12, 'completion_tokens': 3,
                       'prompt_tokens_details': {'cached_tokens': '4'}},
                      {'prompt_tokens': 12, 'completion_tokens': 3,
                       'prompt_tokens_details': {'cached_tokens': 10, 'cache_write_tokens': 4}}):
            with self.subTest(usage=usage):
                self.assertIsNone(metering.record('gpt-6.1-sol', usage)[6])

    def test_long_context_boundary_applies_to_the_full_gpt_6_request(self):
        for model in metering.LONG_CONTEXT_MODELS:
            for incoming in (272_000, 272_001):
                with self.subTest(model=model, incoming=incoming):
                    usage = {'prompt_tokens': incoming, 'completion_tokens': 100,
                             'prompt_tokens_details': {'cached_tokens': 50_000, 'cache_write_tokens': 1000}}
                    rates = metering.rate_for(model)
                    in_multiplier, out_multiplier = (2, 1.5) if incoming > 272_000 else (1, 1)
                    expected = (((incoming - 51_000) * rates[0] + 50_000 * rates[1] + 1000 * rates[2])
                                * in_multiplier + 100 * rates[3] * out_multiplier) / 1e6
                    self.assertAlmostEqual(metering.record(model + '-snapshot', usage)[6], expected)

    def test_request_serialization_tolerates_older_columns(self):
        row = {'input_tokens': 12, 'output_tokens': 3, 'total_tokens': 15,
               'estimated_cost_usd': .5, 'service_tier': None}
        result = metering.request_usage(row)
        self.assertEqual(result['totalTokens'], 15)
        for field in ('cachedInputTokens', 'cacheWriteTokens', 'reasoningTokens'):
            self.assertIsNone(result[field])


if __name__ == '__main__':
    unittest.main()
