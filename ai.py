"""AI-DM providers and context assembly for table advancement."""
import json
import os
import re
import urllib.error
import urllib.request

import module_context
import runtime_prompts

ASK_PROMPT = (
    'You are the AI-DM for TableForge in an operational Pilot console. '
    'Answer the Pilot. Do not narrate a new table beat. '
    'Do not treat this reply as public #table narration.'
)
SUMMARY_PROMPT = (
    'You maintain the durable campaign summary for a TableForge playthrough. '
    'Rewrite the previous summary and the new transcript into one cumulative summary of what has happened: '
    'party decisions, discoveries, NPCs met and their attitudes, locations visited, items gained or lost, '
    'combat outcomes, and open threads. Use only facts from the summary and transcript. '
    'Be concise, use plain prose or short bullet lists, and do not narrate a new beat.'
)
MODULE_CAP = 60_000
TRANSCRIPT_CAP = 40_000
# Older history is summarized so the verbatim window keeps headroom for new play.
SUMMARY_WINDOW = TRANSCRIPT_CAP // 2
SUMMARY_INPUT_CAP = 120_000
COMBAT_OUTCOME_LIMIT = 5
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
OPENAI_TIMEOUT = 60


class GeneratedText(str):
    """AI text with provider-reported usage; mock providers may return plain strings."""

    def __new__(cls, text, *, usage=None, model=None, service_tier=None):
        result = super().__new__(cls, text)
        result.usage = usage
        result.model = model
        result.service_tier = service_tier
        return result


def runtime_status():
    key = os.environ.get('TABLEFORGE_OPENAI_API_KEY', '').strip()
    model = (os.environ.get('TABLEFORGE_AIDM_MODEL', '').strip()
             or os.environ.get('TABLEFORGE_MODEL', '').strip() or 'gpt-4o-mini')
    if key:
        return {'provider': 'openai', 'model': model}
    return {'provider': 'mock', 'model': 'local mock runtime'}


def current_provider():
    status = runtime_status()
    if status['provider'] == 'openai':
        return OpenAIProvider(os.environ.get('TABLEFORGE_OPENAI_API_KEY', '').strip(), status['model'])
    return MockProvider()


def module_report(text, cap=MODULE_CAP):
    """Describe how much of the module fits and which sections fall past the cut."""
    report = {'chars': len(text), 'sentChars': min(len(text), cap), 'truncated': len(text) > cap,
              'cutSection': None, 'omittedSections': []}
    if not report['truncated']:
        return report
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.startswith('#'):
            heading = line.strip()
            if offset < cap:
                report['cutSection'] = heading
            else:
                report['omittedSections'].append(heading)
        offset += len(line)
    return report


def message_size(message):
    return len(message.get('body') or '') + len(message.get('name') or '')


def split_beat(messages):
    """Split messages into completed history and the open beat after the latest AI-DM narration."""
    messages = [m for m in messages if m['kind'] != 'image']
    last_ai = max((index for index, message in enumerate(messages) if message['kind'] == 'ai'), default=-1)
    return messages[:last_ai + 1], messages[last_ai + 1:]


def unsummarized(messages, summary):
    if not summary:
        return list(messages)
    return [message for message in messages if message['id'] > summary['through_message_id']]


def recent_history(history, budget):
    kept = []
    for message in reversed(history):
        if message_size(message) > budget:
            break
        kept.append(message)
        budget -= message_size(message)
    kept.reverse()
    return kept


def select_transcript(messages, summary=None, cap=TRANSCRIPT_CAP):
    """Always keep the open beat; fill the remaining budget with the newest unsummarized history."""
    messages = [m for m in messages if m['kind'] != 'image']
    history, current = split_beat(unsummarized(messages, summary))
    current_chars = sum(message_size(message) for message in current)
    kept = recent_history(history, max(0, cap - current_chars))
    omitted = history[:len(history) - len(kept)]
    report = {
        'total': len(messages),
        'summarized': len(messages) - len(history) - len(current),
        'currentBeat': len(current),
        'currentBeatChars': current_chars,
        'currentBeatOverBudget': current_chars > cap,
        'history': len(kept),
        'omitted': len(omitted),
        'omittedChars': sum(message_size(message) for message in omitted),
        'omittedFrom': omitted[0]['created_at'] if omitted else None,
        'omittedThrough': omitted[-1]['created_at'] if omitted else None,
        'cap': cap,
    }
    return kept + current, report


def summary_range(messages, summary=None):
    """Oldest unsummarized history outside the recent window, sized for one summary request."""
    history, current = split_beat(unsummarized(messages, summary))
    current_chars = sum(message_size(message) for message in current)
    kept = recent_history(history, max(0, SUMMARY_WINDOW - current_chars))
    candidates = history[:len(history) - len(kept)]
    selected, total = [], 0
    for message in candidates:
        if selected and total + message_size(message) > SUMMARY_INPUT_CAP:
            break
        selected.append(message)
        total += message_size(message)
    return selected


def trim_transcript(messages, cap=TRANSCRIPT_CAP):
    kept = []
    total = 0
    for message in reversed(list(messages)):
        size = len(message.get('body') or '') + len(message.get('name') or '')
        if kept and total + size > cap:
            break
        kept.append(message)
        total += size
    kept.reverse()
    return kept


def build_context(state, data_dir, purpose='advance'):
    """Assemble provider context plus a report of everything left out of it."""
    cartridge = state['cartridge']
    summary = state.get('summary')
    adventure = module_context.load(data_dir, cartridge['id'], cartridge['resources'])
    location = state['save'].get('location')
    stale_location = not adventure.valid(location)
    if stale_location:
        location = None
    # Only the open response window drives action retrieval. Old dialogue remains
    # in history without repeatedly pulling its former locations into the module.
    history, current = split_beat(state['messages'])
    queries = [('current player contributions', '\n'.join(m['body'] for m in current))]
    if purpose == 'ask':
        pilot_history, pilot_current = split_beat(state.get('pilot') or [])
        queries = [('current Pilot question', '\n'.join(m['body'] for m in pilot_current))]
        previous = pilot_history[-1:]
    else:
        previous = history[-1:]
    # Resolve short follow-ups such as "I read it" from the immediate reply,
    # without using the entire transcript or summary as a retrieval query.
    if any(re.search(r'\b(it|that|those|them|there|him|her|this)\b', query, re.I) for _, query in queries):
        queries += [('preceding reply', m['body']) for m in previous]
    module, focus = adventure.assemble(location, queries)
    messages, transcript = select_transcript(state['messages'], summary)
    context = {
        'purpose': purpose,
        'title': cartridge['title'],
        'module': module[:MODULE_CAP],
        'location': location,
        'beat': state['save']['beat'],
        'summary': {'body': summary['body'], 'throughMessageId': summary['through_message_id']} if summary else None,
        'messages': [{'kind': m['kind'], 'name': m['name'], 'body': m['body']} for m in messages],
        'cartridgeResources': adventure.optional_resources,
    }
    report = {
        'module': {**module_report(module), **focus, 'fullChars': len(adventure.module_text),
                   'roomsInRunData': len(adventure.rooms), 'staleLocation': stale_location},
        'locations': adventure.locations() if adventure.focused else [],
        'transcript': transcript,
        'summaryAvailable': len(summary_range(state['messages'], summary)),
    }
    context['report'] = report
    if purpose == 'ask':
        pilot = state.get('pilot') or []
        kept = trim_transcript(pilot)
        context['pilot'] = [{'kind': m['kind'], 'name': m['name'], 'body': m['body']} for m in kept]
        report['pilot'] = {'total': len(pilot), 'omitted': len(pilot) - len(kept)}
        return context
    prompt = runtime_prompts.load_saved(data_dir, state['save']['id'])
    context['narrationPrompt'] = prompt
    report['narrationPrompt'] = runtime_prompts.metadata(prompt)
    if prompt['kind'] == 'stage3':
        context['opening'] = (state['save']['beat'] == 1 and not summary
                              and not any(m['kind'] == 'ai' for m in state['messages'])
                              and not state.get('checkpoint') and not state.get('save', {}).get('location'))
        context['party'] = [{'player': p['name'], 'character': p['character']} for p in state['players']]
        context['runData'] = adventure.structured_context(focus)
    context['locationInstructions'] = adventure.marker_instructions()
    outcomes = [event for event in state.get('events', []) if event['kind'] == 'combat_outcome']
    context['checkpoint'] = state.get('checkpoint')
    context['combatOutcomes'] = [{'body': event['body'], 'createdAt': event['created_at']}
                                 for event in outcomes[-COMBAT_OUTCOME_LIMIT:]]
    report['combatOutcomes'] = {'total': len(outcomes), 'omitted': max(0, len(outcomes) - COMBAT_OUTCOME_LIMIT)}
    return context


def build_summary_context(state):
    """Context for rolling the oldest out-of-window history into the durable summary."""
    summary = state.get('summary')
    selected = summary_range(state['messages'], summary)
    if not selected:
        raise ValueError('There is no older history to summarize yet')
    return {
        'purpose': 'summary',
        'title': state['cartridge']['title'],
        'beat': state['save']['beat'],
        'previousSummary': summary['body'] if summary else '',
        'messages': [{'kind': m['kind'], 'name': m['name'], 'body': m['body']} for m in selected],
        'fromMessageId': selected[0]['id'],
        'throughMessageId': selected[-1]['id'],
    }


def summary_text(context):
    if not context.get('summary'):
        return ''
    return ('\n\nSummary of earlier play (older transcript messages are not repeated below):\n'
            + context['summary']['body'])


def chat_messages(context):
    if context.get('purpose') == 'ask':
        return ask_chat_messages(context)
    if context.get('purpose') == 'summary':
        return summary_chat_messages(context)
    system = context['narrationPrompt']['instructions'] + context.get('locationInstructions', '')
    system += f"\n\nAdventure: {context['title']}\n\nModule:\n{context['module']}"
    system += optional_resource_text(context)
    system += summary_text(context)
    if 'runData' in context:
        system += '\n\nRun-data (authored reference, not party knowledge):\n' + json.dumps(context['runData'], ensure_ascii=False)
        system += '\n\nSaved player/character assignments:\n' + json.dumps(context['party'], ensure_ascii=False)
        if not context.get('opening'):
            system += ('\n\nRuntime request: continue the current situation. Do not restart the session opening. '
                       'If combat has just been resumed, narrate its aftermath using the recorded outcome.')
    checkpoint = context.get('checkpoint')
    if checkpoint:
        system += (f"\n\nLast session checkpoint (beat {checkpoint['beat']}, mode {checkpoint['mode']}): "
                   + (checkpoint['note'] or 'No additional table note.'))
    outcomes = context.get('combatOutcomes') or []
    if outcomes:
        system += '\n\nRecorded combat outcomes:\n' + '\n'.join('- ' + item['body'] for item in outcomes)
    messages = [{'role': 'system', 'content': system}]
    for item in context['messages']:
        if item['kind'] == 'ai':
            messages.append({'role': 'assistant', 'content': item['body']})
        else:
            messages.append({'role': 'user', 'content': f"{item['name']}: {item['body']}"})
    if context.get('opening'):
        messages.append({'role': 'user', 'content':
                         'Begin the adventure. This is the first AI-DM narration. Follow the opening sequence '
                         'as adapted for TableForge, honoring any player contributions above.'})
    elif not any(item['role'] == 'user' for item in messages):
        messages.append({'role': 'user', 'content': 'Continue the adventure from the current beat.'})
    return messages


def ask_chat_messages(context):
    system = ASK_PROMPT + f"\n\nAdventure: {context['title']}\n\nModule:\n{context['module']}"
    system += optional_resource_text(context)
    system += summary_text(context)
    table = context.get('messages') or []
    if table:
        system += '\n\nRecent table transcript (background only):\n' + '\n'.join(
            f"{item['name']}: {item['body']}" for item in table)
    messages = [{'role': 'system', 'content': system}]
    for item in context.get('pilot') or []:
        if item['kind'] == 'ai':
            messages.append({'role': 'assistant', 'content': item['body']})
        else:
            messages.append({'role': 'user', 'content': f"{item['name']}: {item['body']}"})
    if not any(item['role'] == 'user' for item in messages):
        messages.append({'role': 'user', 'content': 'The Pilot is waiting for an operational answer.'})
    return messages


def optional_resource_text(context):
    """Make bound Stage 2 companion artifacts available as authored reference."""
    resources = context.get('cartridgeResources') or {}
    if not resources:
        return ''
    parts, remaining = [], 60000
    for name, value in resources.items():
        body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if remaining <= 0:
            break
        truncated = len(body) > min(20000, remaining)
        body = body[:min(20000, remaining)]
        remaining -= len(body)
        if truncated:
            body += '\n[TableForge truncated this companion file to fit the AI context budget.]'
        parts.append(f'\n\n{name} (authored reference, not proof of party discovery):\n{body}')
    return ''.join(parts)


def summary_chat_messages(context):
    transcript = '\n\n'.join(f"{item['name']}: {item['body']}" for item in context['messages'])
    return [
        {'role': 'system', 'content': SUMMARY_PROMPT + f"\n\nAdventure: {context['title']}"},
        {'role': 'user', 'content': 'Previous summary:\n' + (context['previousSummary'] or '(none yet)')
                                    + '\n\nNew transcript to fold in:\n' + transcript},
    ]


class MockProvider:
    def generate(self, context):
        if context.get('purpose') == 'summary':
            previous = context['previousSummary'] + ' ' if context['previousSummary'] else ''
            return f"Mock summary: {previous}{len(context['messages'])} more messages of play happened."
        if context.get('purpose') == 'ask':
            return 'Mock AI-DM (Pilot): This is an operational answer. No table beat was advanced.'
        beat = context['beat']
        text = (
            'Mock AI-DM, beat ' + str(beat) + ': The party has a moment to consider what happens next. '
            'This is placeholder narration; no AI provider is connected yet.'
        )
        if context.get('locationInstructions'):
            where = context.get('location')
            text += '\n\n[Location: ' + ('Approach' if where is None else f'Area {where}') + ']'
        return text


class OpenAIProvider:
    def __init__(self, key, model):
        self.key = key
        self.model = model

    def generate(self, context):
        payload = json.dumps({'model': self.model, 'messages': chat_messages(context)}).encode()
        request = urllib.request.Request(
            OPENAI_URL,
            data=payload,
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=OPENAI_TIMEOUT) as response:
                data = json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')[:400]
            raise ValueError(f'OpenAI request failed ({error.code}): {detail}') from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            raise ValueError(f'OpenAI request failed: {error}') from error
        choices = data.get('choices') if isinstance(data, dict) else None
        if not choices:
            raise ValueError('OpenAI returned no choices')
        text = str((choices[0].get('message') or {}).get('content') or '').strip()
        if not text:
            raise ValueError('OpenAI returned an empty response')
        return GeneratedText(text, usage=data.get('usage'), model=data.get('model') or self.model,
                             service_tier=data.get('service_tier'))
