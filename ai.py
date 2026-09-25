"""AI-DM providers and context assembly for table advancement."""
import json
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

SYSTEM_PROMPT = (
    'You are the AI-DM for TableForge, running an AdventureForge cartridge. '
    'Narrate the scene and play NPCs. Treat the transcript as what has already happened. '
    'Do not run combat turns. Do not ask players to reconfirm actions they already declared.'
)
ASK_PROMPT = (
    'You are the AI-DM for TableForge in an operational Pilot console. '
    'Answer the Pilot. Do not narrate a new table beat. '
    'Do not treat this reply as public #table narration.'
)
MODULE_CAP = 60_000
TRANSCRIPT_CAP = 40_000
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
OPENAI_TIMEOUT = 60


def runtime_status():
    key = os.environ.get('TABLEFORGE_OPENAI_API_KEY', '').strip()
    model = os.environ.get('TABLEFORGE_MODEL', '').strip() or 'gpt-4o-mini'
    if key:
        return {'provider': 'openai', 'model': model}
    return {'provider': 'mock', 'model': 'local mock runtime'}


def current_provider():
    status = runtime_status()
    if status['provider'] == 'openai':
        return OpenAIProvider(os.environ.get('TABLEFORGE_OPENAI_API_KEY', '').strip(), status['model'])
    return MockProvider()


def read_module(data_dir, cartridge_id, resources):
    archive_path = Path(data_dir) / 'cartridges' / (cartridge_id + '.zip')
    name = resources.get('module.md')
    if not name:
        raise ValueError('Cartridge is missing module.md')
    if not archive_path.is_file():
        raise ValueError('Locate the cartridge for this save')
    with zipfile.ZipFile(archive_path) as archive:
        text = archive.read(name).decode('utf-8')
    return text[:MODULE_CAP]


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
    cartridge = state['cartridge']
    messages = trim_transcript(state['messages'])
    context = {
        'purpose': purpose,
        'title': cartridge['title'],
        'module': read_module(data_dir, cartridge['id'], cartridge['resources']),
        'beat': state['save']['beat'],
        'messages': [{'kind': m['kind'], 'name': m['name'], 'body': m['body']} for m in messages],
    }
    if purpose == 'ask':
        context['pilot'] = [{'kind': m['kind'], 'name': m['name'], 'body': m['body']}
                            for m in trim_transcript(state.get('pilot') or [])]
        return context
    outcomes = [event for event in state.get('events', []) if event['kind'] == 'combat_outcome'][-5:]
    context['checkpoint'] = state.get('checkpoint')
    context['combatOutcomes'] = [{'body': event['body'], 'createdAt': event['created_at']} for event in outcomes]
    return context


def chat_messages(context):
    if context.get('purpose') == 'ask':
        return ask_chat_messages(context)
    system = SYSTEM_PROMPT + f"\n\nAdventure: {context['title']}\n\nModule:\n{context['module']}"
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
    if not any(item['role'] == 'user' for item in messages):
        messages.append({'role': 'user', 'content': 'Continue the adventure from the current beat.'})
    return messages


def ask_chat_messages(context):
    system = ASK_PROMPT + f"\n\nAdventure: {context['title']}\n\nModule:\n{context['module']}"
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


class MockProvider:
    def generate(self, context):
        if context.get('purpose') == 'ask':
            return 'Mock AI-DM (Pilot): This is an operational answer. No table beat was advanced.'
        beat = context['beat']
        return (
            'Mock AI-DM, beat ' + str(beat) + ': The party has a moment to consider what happens next. '
            'This is placeholder narration; no AI provider is connected yet.'
        )


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
        return text
