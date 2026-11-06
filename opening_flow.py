"""Save-backed opening stages for AdventureForge's first playable scenes.

The stage names describe what the next AI-DM beat may address, not actions the
players have selected. The server owns the stage; a model normally requests the
next adjacent stage, and its request is checked before the reply is published.
"""
import re

import narration_pacing


STAGES = ('establishing', 'hook', 'decision', 'travel', 'arrival', 'exploration')
MARKER = re.compile(r'^\s*\[Opening:\s*([a-z]+)\s*\]\s*$', re.IGNORECASE | re.MULTILINE)
OPENING_LINE = re.compile(r'^\s*\[Opening\s*:', re.IGNORECASE | re.MULTILINE)
ESTABLISHING_QUESTION = re.compile(
    r'\b(?:where\b[^?]{0,180}\b(?:you|your|characters?|party|are|start|begin)\b[^?]{0,100}'
    r'|what\b[^?]{0,120}\b(?:doing|up to)\b[^?]{0,100}'
    r'|who\b[^?]{0,120}\b(?:with|alongside|accompanies)\b[^?]{0,80}'
    r'|how\b[^?]{0,120}\b(?:begin|start|positioned|introduce)\b[^?]{0,80})\?', re.IGNORECASE,
)


def supported(run_data):
    """Only authored Stage 2 openings have enough structure for stage gating."""
    return (isinstance(run_data, dict) and isinstance(run_data.get('hook'), dict)
            and bool(run_data['hook'].get('dmSecrets')))

GUIDANCE = {
    'establishing': (
        'Invite the players to establish where their characters are, what they are doing, '
        'and who they are with. Brief scene color is fine. Do not resolve the opening '
        'incident, introduce the patron offer, narrate travel, or arrive at the site.'
    ),
    'hook': (
        'Use only the authored opening incident and patron material. Let players act '
        'on unresolved dangers before narrating their outcome. Offer the job in character '
        'when the scene permits. Do not decide whether they accept or narrate travel.'
    ),
    'decision': (
        'The offer is pending. Answer questions, resolve declared actions, or let the '
        'players decline or seek another path. Do not treat Ready without a message as '
        'acceptance. Only explicit player intent to undertake the journey permits '
        'moving to travel, and actual travel belongs to a later beat. If the '
        'players explicitly refuse and leave this adventure hook, move to '
        'exploration for freeform play without sending them to the site.'
    ),
    'travel': (
        'The players have chosen to travel. Narrate its established consequences and '
        'any new choices; do not assume they enter the destination. You may move to '
        'arrival once the journey has genuinely reached it.'
    ),
    'arrival': (
        'The party is at the site, not inside it. Describe the immediate surroundings '
        'and await their actions. Only move to exploration after the players actually '
        'choose to enter or investigate the site.'
    ),
}


def instructions(stage, first=False, has_player_input=False):
    """Place the stage gate after all cartridge reference text for recency."""
    if stage not in GUIDANCE:
        return ''
    pending = (' There are no new player contributions this beat; no one has '
               'accepted the offer or entered the site.'
               if not has_player_input and stage in ('decision', 'arrival') else '')
    return (
        '\n\nTableForge authoritative opening state: ' + stage + '. '
        + ('This is the very first public AI-DM response. ' if first else '')
        + GUIDANCE[stage] + pending
        + '\nThe stage reflects the SAVE, not the module outline. A module description '
        'of a later scene is not evidence that it occurred. Do not narrate private '
        'thoughts, choices, or movement for player characters. '
        'After the public prose, include a separate machine line [Opening: NEXT] '
        '(before the required final [Location: ...] line, if there is one), where NEXT '
        'is the stage for the next AI-DM response. NEXT must be the current stage '
        'or the immediately following stage in this order: '
        + ', '.join(STAGES) + '. The very first response may only mark hook (if '
        'the establishing question has been asked) or establishing (if more setup '
        'is genuinely needed). A job offer can advance hook to decision; only '
        'actual player intent can advance decision to travel or arrival to '
        'exploration. The one exception to adjacent progression is an explicit '
        'player choice to abandon the opening path: mark exploration and continue '
        'freeform play without inventing arrival. TableForge strips this line '
        'before publication.'
    )


def prepare(text, stage, *, first=False, has_player_input=False, require_opening_contract=False):
    """Strip stage metadata and reject invalid opening progress without saving it.

    Older/simple modules without formal starting-scene setup can still use
    Stage 3 without the strict format and establishing-question checks.
    """
    if stage not in GUIDANCE:
        return text, stage
    matches = list(MARKER.finditer(text))
    remaining = MARKER.sub('', text)
    if (len(matches) > 1 or OPENING_LINE.search(remaining)
            or (matches and text[matches[0].end():].strip())):
        raise ValueError('Invalid AI-DM opening-stage marker. No narration was published. Retry the beat.')
    if require_opening_contract and not matches:
        raise ValueError('The AI-DM omitted its opening-stage marker. '
                         'No narration was published. Retry the beat.')
    next_stage = matches[0].group(1).lower() if matches else ('hook' if first else stage)
    adjacent = next_stage in STAGES and STAGES.index(next_stage) in (
        STAGES.index(stage), STAGES.index(stage) + 1)
    off_script = next_stage == 'exploration' and stage in ('hook', 'decision', 'travel') and has_player_input
    if not adjacent and not off_script:
        raise ValueError('The AI-DM skipped an opening stage. No narration was published. Retry the beat.')
    if first and next_stage != 'hook' and next_stage != 'establishing':
        raise ValueError('The AI-DM skipped the establishing round. No narration was published. Retry the beat.')
    if next_stage == 'travel' and stage == 'decision' and not has_player_input:
        raise ValueError('No player accepted the journey. No narration was published. Retry the beat.')
    if next_stage == 'exploration' and stage == 'arrival' and not has_player_input:
        raise ValueError('No player entered the site. No narration was published. Retry the beat.')
    clean = remaining.strip()
    if require_opening_contract and first:
        question = ESTABLISHING_QUESTION.search(clean)
        if not question:
            raise ValueError(
                'The AI-DM skipped character establishment and began a later scene. '
                'No narration was published. Retry the beat or review its context in Pilot Mode.'
            )
        if not narration_pacing.is_clarification(clean[question.end():]):
            raise ValueError(
                'The AI-DM continued the opening after asking players to establish their characters. '
                'No narration was published. Retry the beat.'
            )
    return clean, next_stage
