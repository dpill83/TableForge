"""Edit the models and reasoning effort used by TableForge on this host."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

import ai
from local_config import load_env
import routing_settings as settings
from routing_tui import CANCEL, TerminalMenu, terminal_library

ROOT = Path(__file__).resolve().parent
MODELS_URL = 'https://api.openai.com/v1/models'
EFFORT_LABELS = {
    'auto': 'Follow Laya and server defaults',
    'default': 'OpenAI model default',
    **{effort: effort for effort in settings.EFFORTS},
}
LAYA_EFFORT_LABELS = {**EFFORT_LABELS, 'auto': 'Let Laya choose the effort'}


def openai_json(url, payload=None):
    key = os.environ.get('TABLEFORGE_OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('Set TABLEFORGE_OPENAI_API_KEY in the server environment to select models.')
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(request, timeout=ai.OPENAI_TIMEOUT) as result:
            return json.load(result)
    except urllib.error.HTTPError as error:
        raise ValueError(f'OpenAI returned HTTP {error.code}.') from None
    except (OSError, ValueError):
        raise ValueError('Could not read the response from OpenAI.') from None


def available_models():
    result = openai_json(MODELS_URL)
    rows = result.get('data') if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise ValueError('OpenAI returned an invalid model list.')
    return sorted({row['id'] for row in rows if isinstance(row, dict)
                   and isinstance(row.get('id'), str) and settings.MODEL_ID.fullmatch(row['id'])})


def laya_base_models():
    url = os.environ.get('TABLEFORGE_ROUTER_URL', '').strip()
    try:
        origin = urlsplit(url)
        if origin.scheme not in ('http', 'https') or not origin.netloc:
            raise ValueError
        endpoint = urlunsplit((origin.scheme, origin.netloc,
                               origin.path.rstrip('/').rpartition('/')[0] + '/routing-defaults', '', ''))
        with urllib.request.urlopen(endpoint, timeout=ai.ROUTER_TIMEOUT) as response:
            data = json.loads(response.read(ai.ROUTER_RESPONSE_CAP))
        models = data.get('models') if isinstance(data, dict) else None
        if (not isinstance(models, dict) or models.keys() != set(settings.TIERS)
                or any(not isinstance(model, str) or not settings.MODEL_ID.fullmatch(model)
                       for model in models.values())):
            raise ValueError
        return models
    except (OSError, ValueError):
        raise ValueError('Cannot read Laya service defaults. Check TABLEFORGE_ROUTER_URL and the Laya router update.') from None


def probe_models(choices, verified, progress):
    """Check the selected model and concrete effort using a short, synthetic prompt."""
    for model, effort in choices:
        if (model, effort) in verified:
            continue
        payload = {'model': model, 'max_completion_tokens': 32, 'messages': [
            {'role': 'system', 'content': 'Give a short plain-text response.'},
            {'role': 'user', 'content': 'Reply with OK.'},
        ]}
        if effort != 'default':
            payload['reasoning_effort'] = effort
        progress(f'Checking {model} ({EFFORT_LABELS[effort]})...')
        try:
            result = openai_json(ai.OPENAI_URL, payload)
            if not isinstance(result, dict) or not result.get('choices'):
                raise ValueError('OpenAI returned no chat completion.')
        except ValueError as error:
            raise ValueError(f'{model} ({EFFORT_LABELS[effort]}) failed its Chat Completions check. {error}') from None
        verified.add((model, effort))


def model_choices(config, laya_models=None):
    choices = set()
    defaults = laya_models or {}
    for group in config.values():
        for name, row in group.items():
            model = row.get('model') or defaults.get(name)
            if model:
                effort = row.get('effort', 'auto')
                choices.add((model, 'default' if effort == 'auto' else effort))
    return choices


def choose(label, choices, current=None):
    for number, text in enumerate(choices.values(), 1):
        print(f'  {number}. {text}')
    default = f' [{choices[current]}]' if current in choices else ''
    while True:
        answer = input(f'{label}{default}> ').strip()
        if not answer and current in choices:
            return current
        if answer.isascii() and answer.isdecimal() and len(answer) <= 6:
            number = int(answer)
            if 1 <= number <= len(choices):
                return tuple(choices)[number - 1]
        print('Enter a number from the list.')


def choose_model(current, inherited_label, models, load_models):
    shortcut = f', - to {inherited_label.lower()}' if inherited_label else ''
    while True:
        previous = f' [{current}]' if current else ''
        term = input(f'Model search{previous} (* for all{shortcut}, or B to go back)> ').strip()
        if term.casefold() == 'b':
            return False, current
        if term == '-' and inherited_label:
            return True, None
        if not term and current:
            return True, current
        if not term:
            continue
        if not models:
            models.extend(load_models())
        matching = {model: model for model in models if term == '*' or term.casefold() in model.casefold()}
        if not matching:
            print('No models found. Try a different search.')
            continue
        selected = choose('Select model', {**matching, None: 'Back to model search'}, None)
        if selected is not None:
            return True, selected


class NumberedMenu:
    def setup(self, path, policy, fallback=None):
        print(f'TableForge AI routing\nSettings file | {path}')
        if fallback:
            print(f'Inherited policy | {policy}\nServer fallback model | {fallback}')
        else:
            print(policy)

    def choose(self, label, choices, current=None, *, detail='', sections=None):
        return choose(label, choices, None if sections else current)

    def choose_model(self, current, inherited_label, models, load_models, *, detail=''):
        return choose_model(current, inherited_label, models, load_models)

    def notice(self, message):
        print(message, flush=True)

    progress = notice

    def confirm_discard(self):
        return True


def edit_row(group, label, row, models, laya_enabled, menu, *, service_model=None):
    if group == 'requests':
        modes = {'inherit': 'Inherit the server policy', 'laya': 'Route through Laya', 'fixed': 'Use a fixed model'}
        mode = menu.choose('Routing', modes, row.get('mode', 'inherit'), detail=label)
        if mode is CANCEL:
            return row
        if mode == 'inherit':
            return {}
        if mode == 'laya' and not laya_enabled:
            raise ValueError('Set TABLEFORGE_ROUTER_URL on the server to use Laya.')
    else:
        mode = None

    model = None
    if mode != 'laya':
        inherited = None
        if service_model:
            inherited = f'Use service default ({service_model})'
        elif group == 'tiers':
            inherited = 'Use the model from Laya'
        accepted, model = menu.choose_model(row.get('model'), inherited, models, available_models,
                                            detail=label)
        if not accepted:
            return row
    labels = LAYA_EFFORT_LABELS if service_model else EFFORT_LABELS
    efforts = {key: text for key, text in labels.items() if mode != 'fixed' or key != 'auto'}
    effort = menu.choose('Reasoning effort', efforts, row.get('effort', 'default' if mode == 'fixed' else 'auto'),
                         detail=f'{label} | {model or service_model or "Model from Laya"}')
    if effort is CANCEL:
        return row
    if mode:
        result = {'mode': mode, 'effort': effort}
    else:
        result = {'effort': effort} if model or effort != 'auto' else {}
    if model:
        result['model'] = model
    return result


def describe(group, name, row, table_play, laya_enabled, *, service_model=None):
    if group == 'tiers':
        model = row.get('model') or service_model or 'Model from Laya'
        labels = LAYA_EFFORT_LABELS if service_model else EFFORT_LABELS
        return f'{model} / {labels[row.get("effort", "auto")]}'
    if row:
        model = row.get('model', 'Laya')
        return f'{model} / {EFFORT_LABELS[row.get("effort", "auto")]}'
    if table_play:
        model, effort = ai.table_play_route(name)
        return f'Inherit Table play / {model} / {effort}'
    return 'Inherit Laya' if laya_enabled else f'Inherit server default / {ai.configured_model()}'


def run(data_path, menu=None, *, laya_models=None):
    menu = menu if menu is not None else NumberedMenu()
    original = settings.load(data_path)
    config = deepcopy(original)
    models = []
    verified = set()
    table_play = laya_models is None and ai.table_play_routing()
    laya_enabled = bool(os.environ.get('TABLEFORGE_ROUTER_URL', '').strip())
    service_models = laya_models or {}
    choices = {('tiers', tier): f'Laya / {tier.title()}' for tier in settings.TIERS}
    if laya_models is None:
        title = 'TableForge routing'
        inherited_policy = 'Table play' if table_play else 'Laya' if laya_enabled else 'Server default'
        menu.setup(settings.path_for(data_path), inherited_policy, ai.configured_model())
        choices.update({('requests', name): label for name, label in settings.REQUESTS.items()})
        sections = {('tiers', 'cheap'): 'TABLEFORGE OVERRIDES FOR LAYA TIERS',
                    ('requests', 'advance'): 'TABLEFORGE REQUEST TYPES', 'save': 'ACTIONS'}
    else:
        title = 'Laya service defaults'
        menu.setup(settings.path_for(data_path), 'Shared settings for all clients of this Laya router')
        sections = {('tiers', 'cheap'): 'SHARED LAYA TIERS', 'save': 'ACTIONS'}
    focus = next(iter(choices))
    while True:
        rows = {}
        for (group, name), label in choices.items():
            description = describe(group, name, config[group].get(name, {}), table_play, laya_enabled,
                                   service_model=service_models.get(name))
            rows[group, name] = f'{label:<24} | {description}'
        dirty = config != original
        action = menu.choose(title, {
            **rows, 'save': 'Save and exit', 'quit': 'Exit without saving',
        }, focus, detail='Unsaved changes' if dirty else 'All settings saved', sections=sections)
        try:
            if action is CANCEL or action == 'quit':
                if not dirty or menu.confirm_discard():
                    return
                continue
            focus = action
            if action == 'save':
                if dirty:
                    pending = model_choices(config, laya_models) - model_choices(original, laya_models) - verified
                    if pending:
                        menu.notice(f'OpenAI will receive {len(pending)} short compatibility check(s) before saving. '
                                    'These use API tokens.')
                        if menu.choose('Confirm compatibility checks',
                                       {True: 'Verify and save', False: 'Back'}, False) is not True:
                            continue
                        probe_models(sorted(pending), verified, menu.progress)
                    settings.save(data_path, config, expected=original)
                    return ('Saved. Laya reads the changes on the next routing request.' if laya_models
                            else 'Saved. TableForge reads the changes on the next AI request.')
                return
            group, name = action
            row = edit_row(group, choices[action], config[group].get(name, {}), models, laya_enabled, menu,
                           service_model=service_models.get(name))
            if row:
                config[group][name] = row
            else:
                config[group].pop(name, None)
        except (OSError, ValueError) as error:
            menu.notice(str(error))


def run_editor(data_path, menu, scope):
    laya_data = settings.laya_data_path()
    ready = settings.path_for(laya_data).is_file()
    while scope != 'tableforge' and (scope == 'laya' or ready):
        choice = scope or menu.choose('Choose routing settings', {
            'tableforge': 'TableForge routing',
            'laya': 'Laya service defaults',
        }, 'tableforge')
        if choice is CANCEL:
            return
        if choice == 'tableforge':
            break
        if not ready:
            raise ValueError('Laya service settings are not installed. See deploy/laya/README.md.')
        try:
            menu.progress('Reading Laya service defaults...')
            models = laya_base_models()
        except ValueError as error:
            if scope == 'laya':
                raise
            menu.notice(str(error))
            continue
        return run(laya_data, menu, laya_models=models)
    return run(data_path, menu)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env',
                        help='Load the same settings file used by the TableForge server.')
    parser.add_argument('--plain', action='store_true', help='Use numbered prompts.')
    parser.add_argument('--scope', choices=('tableforge', 'laya'), help='Open a specific settings menu.')
    args = parser.parse_args()
    try:
        load_env(args.env_file)
        data_path = Path(os.environ.get('TABLEFORGE_DATA', ROOT / 'data'))
        curses = None if args.plain else terminal_library()
        if curses is None:
            result = run_editor(data_path, NumberedMenu(), args.scope)
        else:
            result = curses.wrapper(lambda screen: run_editor(data_path, TerminalMenu(screen, curses), args.scope))
        if result:
            print(result, flush=True)
    except (EOFError, KeyboardInterrupt):
        print('\nEditor closed without saving.')
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
