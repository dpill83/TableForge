"""LAN Laya router; model selection and reasoning effort are independent."""
import json
import os
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel
from router_policy import MODEL_CRITERIA, EFFORT_CRITERIA, model_decision, effort_decision

LAYA_URL = os.environ.get('LAYA_URL', 'http://10.0.0.22:8000/v1/systemone')
MODEL_MAP = {tier: os.environ.get('ROUTER_MODEL_' + tier.upper(), model)
             for tier, model in [('cheap', 'gpt-6-luna'), ('standard', 'gpt-6.1-sol'),
                                 ('heavy', 'gpt-6-astra')]}
app = FastAPI(title='Laya Model Router', version='0.2.0')


class RouteRequest(BaseModel):
    prompt: str


@app.get('/health')
def health():
    return {'status': 'ok', 'version': '0.2.0'}


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
        return {'tier': 'standard', 'model': MODEL_MAP['standard'],
                'reason': 'Laya unavailable, using safe fallback', 'scores': None,
                'router_internal_fallback_used': True,
                'router_internal_fallback_reason': 'Laya unavailable, using safe fallback',
                **effort_decision(None)}
    return {'tier': tier, 'model': MODEL_MAP[tier], 'reason': reason, 'scores': scores,
            'laya_choice': answer.get('choice'), 'laya_confidence': answer.get('confidence'),
            'router_internal_fallback_used': False,
            **effort_decision(answers.get('reasoning_effort'))}
