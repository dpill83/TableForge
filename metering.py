"""Persisted API token usage and dated, approximate USD pricing."""

PRICING_AS_OF = '2026-09-25'
PRICING_URL = 'https://developers.openai.com/api/docs/pricing'
# Standard text rates in USD per million tokens: input, cached input, cache write, output.
# Keep historical estimates on each usage row when these rates are updated.
RATES = {
    'gpt-4o-mini': (0.15, 0.075, 0.15, 0.60),
    'gpt-5.4-mini': (0.75, 0.075, 0.75, 4.50),
    'gpt-5.4': (2.50, 0.25, 2.50, 15.00),
    'gpt-5.6-terra': (2.00, 0.20, 2.50, 12.00),
    'gpt-6-luna': (0.10, 0.01, 0.125, 0.50),
    'gpt-6-sol': (2.00, 0.20, 2.50, 10.00),
    'gpt-6-astra': (10.00, 1.00, 12.50, 50.00),
}


def token_count(value):
    return value if type(value) is int and value >= 0 else None


def rate_for(model):
    for name, rates in RATES.items():
        if model == name or model.startswith(name + '-'):
            return rates
    return None


def record(model, usage, service_tier=None):
    """Return database values for one provider response; unknown values stay unknown."""
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = token_count(usage.get('prompt_tokens'))
    output_tokens = token_count(usage.get('completion_tokens'))
    reported_total = token_count(usage.get('total_tokens'))
    details = usage.get('prompt_tokens_details') or {}
    if not isinstance(details, dict):
        details = {}
    cached_tokens = token_count(details.get('cached_tokens')) or 0
    write_tokens = token_count(details.get('cache_write_tokens')) or 0
    total_tokens = reported_total if reported_total is not None else (
        input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else None)
    cost = None
    rates = rate_for(model)
    if (rates and input_tokens is not None and output_tokens is not None
            and cached_tokens + write_tokens <= input_tokens
            and service_tier in (None, 'auto', 'default', 'standard')):
        ordinary = input_tokens - cached_tokens - write_tokens
        cost = (ordinary * rates[0] + cached_tokens * rates[1]
                + write_tokens * rates[2] + output_tokens * rates[3]) / 1_000_000
    return (model, input_tokens, cached_tokens, write_tokens, output_tokens,
            total_tokens, cost, service_tier)


def summary(conn, where='', params=()):
    rows = conn.execute('SELECT input_tokens,cached_tokens,output_tokens,total_tokens,estimated_cost_usd '
                        'FROM ai_usage ' + where, params).fetchall()
    missing_tokens = sum(row['total_tokens'] is None for row in rows)
    missing_cost = sum(row['estimated_cost_usd'] is None for row in rows)
    return {
        'requests': len(rows),
        'inputTokens': sum(row['input_tokens'] or 0 for row in rows),
        'cachedInputTokens': sum(row['cached_tokens'] or 0 for row in rows),
        'outputTokens': sum(row['output_tokens'] or 0 for row in rows),
        'totalTokens': sum(row['total_tokens'] or 0 for row in rows),
        'estimatedCostUsd': None if missing_cost else round(sum(row['estimated_cost_usd'] for row in rows), 8),
        'unmeteredRequests': missing_tokens,
        'unpricedRequests': missing_cost,
    }


def image_cost(model, usage):
    """Text-only image generation; rates verified 2026-09-25 on the model page."""
    if model not in ('gpt-image-2.5-flare', 'gpt-image-2.5-flare-2026-09-08') or not isinstance(usage, dict):
        return None
    incoming, outgoing = token_count(usage.get('input_tokens')), token_count(usage.get('output_tokens'))
    details = usage.get('input_tokens_details') or {}
    if not isinstance(details, dict) or details.get('image_tokens', 0) or details.get('cached_tokens', 0):
        return None
    if incoming is None or outgoing is None:
        return None
    return (incoming * 5 + outgoing * 30) / 1_000_000


def image_summary(conn, where='', params=()):
    rows = conn.execute('SELECT status,completed_at,estimated_cost_usd FROM scene_images ' + where, params).fetchall()
    missing = sum(row['estimated_cost_usd'] is None for row in rows)
    return {'requests': len(rows), 'generated': sum(row['completed_at'] is not None for row in rows),
            'unpricedRequests': missing,
            'estimatedCostUsd': None if missing else round(sum(row['estimated_cost_usd'] for row in rows), 8)}
