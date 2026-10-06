"""Model tier thresholds and a separate effort choice; no provider calls."""
import math

MODEL_CRITERIA = {
    'cheap': 'Simple mechanical, formatting, lookup, renaming, conversion, or obvious transformation work',
    'standard': 'Normal coding, writing, debugging, analysis, or multi-step implementation work',
    'heavy': ('Complex architecture, ambiguous reasoning, difficult debugging, unfamiliar large systems, '
              'or decisions requiring substantial planning'),
}
EFFORT_CRITERIA = {
    'light': 'Routine task with explicit instructions, few dependencies, and little reasoning within the chosen model tier',
    'normal': 'Ordinary task requiring several connected reasoning steps within the chosen model tier',
    'hard': 'Task requiring careful planning, conflicting constraints, or substantial multi-step reasoning within the chosen model tier',
}
EFFORT_MAP = {'light': 'low', 'normal': 'medium', 'hard': 'xhigh'}


def probabilities(answer, keys):
    scores = answer['probabilities']
    if not isinstance(scores, dict) or any(
        type(scores.get(key)) not in (int, float) or not math.isfinite(scores[key])
        or not 0 <= scores[key] <= 1 for key in keys
    ):
        raise ValueError('Invalid classifier scores')
    return {key: scores[key] for key in keys}


def model_decision(answer):
    scores = probabilities(answer, MODEL_CRITERIA)
    # Preserve the deployed router's existing thresholds and priority exactly.
    if scores['heavy'] >= 0.33:
        tier, reason = 'heavy', 'heavy probability exceeded escalation threshold'
    elif scores['cheap'] >= 0.48 and scores['cheap'] - scores['standard'] >= 0.05:
        tier, reason = 'cheap', 'cheap probability cleared confidence threshold'
    else:
        tier, reason = 'standard', 'defaulted to standard because routing was uncertain'
    return tier, reason, scores


def effort_decision(answer):
    try:
        scores = probabilities(answer, EFFORT_MAP)
        maximum = max(scores.values())
        winners = [key for key, value in scores.items() if value == maximum]
        if len(winners) != 1 or maximum == 0:
            raise ValueError('Ambiguous effort')
        level = winners[0]
        return {'effortLevel': level, 'reasoning_effort': EFFORT_MAP[level],
                'effort_reason': 'Laya selected ' + level + ' reasoning within the model tier',
                'effort_scores': scores, 'effort_fallback_used': False}
    except (KeyError, TypeError, ValueError):
        return {'effortLevel': 'normal', 'reasoning_effort': 'medium',
                'effort_reason': 'Effort classification unavailable or ambiguous; using normal effort',
                'effort_scores': None, 'effort_fallback_used': True}
