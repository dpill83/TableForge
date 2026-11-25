"""LAN Laya router; model selection and reasoning effort are independent."""
import json
import logging
import os
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel
from router_policy import MODEL_CRITERIA, EFFORT_CRITERIA, model_decision, effort_decision
import routing_settings

LOGGER = logging.getLogger(__name__)
LAYA_URL = os.environ.get('LAYA_URL', 'http://10.0.0.22:8000/v1/systemone')
MODEL_MAP = {tier: os.environ.get('ROUTER_MODEL_' + tier.upper(), model)
             for tier, model in [('cheap', 'gpt-6-luna'), ('standard', 'gpt-6.1-sol'),
                                 ('heavy', 'gpt-6-astra')]}
app = FastAPI(title='Laya Model Router', version='0.3.0')


class RouteRequest(BaseModel):
    prompt: str


@app.get('/health')
def health():
    return {'status': 'ok', 'version': app.version}


@app.get('/routing-defaults')
def routing_defaults():
    return {'models': MODEL_MAP}


def tier_settings(tier, effort):
    try:
        overrides = routing_settings.load(routing_settings.laya_data_path())['tiers'].get(tier, {})
    except ValueError:
        LOGGER.warning('Could not read Laya routing settings. Using service defaults.')
        overrides = {}
    override = overrides.get('effort', 'auto')
    if override != 'auto':
        effort.update(reasoning_effort=None if override == 'default' else override,
                      effort_override=override, effort_fallback_used=False,
                      effort_reason=f'Laya {tier} tier setting')
    return {'model': overrides.get('model') or MODEL_MAP[tier], **effort}


@app.post('/route')
def route(request: RouteRequest):
    body = {'state': request.prompt, 'questions': {
        'model_tier': {'type': 'choice',
                       'instructions': 'Choose the minimum AI model capability needed to handle this task well.',
                       'criteria': MODEL_CRITERIA},
        'reasoning_effort': {'type': 'choice',
                            'instructions': ('Choose reasoning intensity within the minimum suitable model tier. '
                                             'This is separate from choosing the model capability.'),
                            'criteria': EFFORT_CRITERIA},
    }}
    req = urllib.request.Request(LAYA_URL, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.load(response)
        answers = result['answers']
        answer = answers['model_tier']
        tier, reason, scores = model_decision(answer)
    except (OSError, ValueError, KeyError, TypeError):
        return {'tier': 'standard',
                'reason': 'Laya unavailable, using safe fallback', 'scores': None,
                'router_internal_fallback_used': True,
                'router_internal_fallback_reason': 'Laya unavailable, using safe fallback',
                **tier_settings('standard', effort_decision(None))}
    return {'tier': tier, 'reason': reason, 'scores': scores,
            'laya_choice': answer.get('choice'), 'laya_confidence': answer.get('confidence'),
            'router_internal_fallback_used': False,
            **tier_settings(tier, effort_decision(answers.get('reasoning_effort')))}
