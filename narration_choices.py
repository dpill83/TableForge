"""Public action choices carried alongside narration, without changing Stage 3."""
import json
import logging
import re
from pathlib import Path

PROMPT = Path(__file__).resolve().parent / 'prompts' / 'tableforge-choices-v1.md'
START = re.compile(r'^```tableforge-choices[^\r\n]*(?:\r?\n|$)', re.MULTILINE)
END = re.compile(r'^```[ \t]*\r?$', re.MULTILINE)
LOG = logging.getLogger(__name__)


def instructions():
    return PROMPT.read_text(encoding='utf-8')


def markdown_text(text):
    # Option strings are plain text, not authored Markdown or markup.
    return re.sub(r'([\\`*_\[\]~])', r'\\\1', text)


def extract(text, players, beat):
    """Strip protocol blocks and return public prose plus validated choice data."""
    starts = list(START.finditer(text))
    if not starts:
        return text.strip(), None
    parts, cursor, payload = [], 0, None
    complete = False
    for index, start in enumerate(starts):
        if start.start() < cursor:
            continue
        parts.append(text[cursor:start.start()])
        limit = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        end = END.search(text, start.end(), limit)
        cursor = end.end() if end else limit
        if len(starts) == 1 and end:
            payload = text[start.end():end.start()]
            complete = True
    parts.append(text[cursor:])
    prose = '\n'.join(part.strip() for part in parts if part.strip())
    try:
        data = json.loads(payload) if complete else None
    except (ValueError, TypeError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get('groups'), list):
        LOG.warning('Discarded invalid AI-DM choice footer')
        return prose, None
    audiences = {p['id']: p['character'] for p in players}
    groups, seen = [], set()
    # Bound this optional metadata independently of the narration.
    if len(data['groups']) > len(players) + 1:
        LOG.warning('Discarded oversized AI-DM choice footer')
        return prose, None
    for group in data['groups']:
        if not isinstance(group, dict) or 'playerId' not in group:
            LOG.warning('Discarded invalid AI-DM choice audience')
            continue
        player_id = group['playerId']
        if (player_id is not None and (not isinstance(player_id, str) or player_id not in audiences)):
            LOG.warning('Discarded unknown AI-DM choice audience')
            continue
        options = group.get('options')
        if (player_id in seen or not isinstance(options, list) or not 1 <= len(options) <= 26
                or any(not isinstance(option, str) or not option.strip() or len(option) > 2000
                       for option in options)):
            LOG.warning('Discarded invalid AI-DM choice group')
            continue
        seen.add(player_id)
        normalized = [{'letter': chr(65 + index), 'text': ' '.join(option.split())}
                      for index, option in enumerate(options)]
        groups.append({'playerId': player_id, 'options': normalized})
    if not groups:
        return prose, None
    return prose, {'beat': beat, 'groups': groups}


def public_body(prose, choices, players):
    if not choices:
        return prose
    audiences = {p['id']: p['character'] for p in players}
    lists = []
    for group in choices['groups']:
        label = audiences[group['playerId']] if group['playerId'] is not None else 'Party'
        lists.append('**' + markdown_text(label) + '**\n\n' + '\n'.join(
            f"- **{option['letter']}.** {markdown_text(option['text'])}" for option in group['options']))
    return '\n\n'.join([prose, *lists]).strip()
