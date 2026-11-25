"""Edit the models and reasoning effort used by TableForge on this host."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

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


def model_choices(config):
    return {(row['model'], 'default' if row.get('effort', 'auto') == 'auto' else row['effort'])
            for group in config.values() for row in group.values() if row.get('model')}


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


def choose_model(current, allow_laya, models, load_models):
    shortcut = ', - for the model from Laya' if allow_laya else ''
    while True:
        previous = f' [{current}]' if current else ''
        term = input(f'Model search{previous} (* for all{shortcut}, or B to go back)> ').strip()
        if term.casefold() == 'b':
            return False, current
        if term == '-' and allow_laya:
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
    def setup(self, path, policy, fallback):
        print(f'TableForge AI routing\nSettings file | {path}')
        print(f'Inherited policy | {policy}\nServer fallback model | {fallback}')

    def choose(self, label, choices, current=None, *, detail='', sections=None):
        return choose(label, choices, None if sections else current)

    def choose_model(self, current, allow_laya, models, load_models, *, detail=''):
        return choose_model(current, allow_laya, models, load_models)

    def notice(self, message):
        print(message, flush=True)

    progress = notice

    def confirm_discard(self):
        return True


def edit_row(group, label, row, models, laya_enabled, menu):
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
        accepted, model = menu.choose_model(row.get('model'), group == 'tiers', models, available_models,
                                            detail=label)
        if not accepted:
            return row
    efforts = {key: label for key, label in EFFORT_LABELS.items() if mode != 'fixed' or key != 'auto'}
    effort = menu.choose('Reasoning effort', efforts, row.get('effort', 'default' if mode == 'fixed' else 'auto'),
                         detail=f'{label} | {model or "Model from Laya"}')
    if effort is CANCEL:
        return row
    if mode:
        result = {'mode': mode, 'effort': effort}
    else:
        result = {'effort': effort} if model or effort != 'auto' else {}
    if model:
        result['model'] = model
    return result


def describe(group, name, row, table_play, laya_enabled):
    if group == 'tiers':
        model = row.get('model', 'Model from Laya')
        return f'{model} / {EFFORT_LABELS[row.get("effort", "auto")]}'
    if row:
        model = row.get('model', 'Laya')
        return f'{model} / {EFFORT_LABELS[row.get("effort", "auto")]}'
    if table_play:
        model, effort = ai.table_play_route(name)
        return f'Inherit Table play / {model} / {effort}'
    return 'Inherit Laya' if laya_enabled else f'Inherit server default / {ai.configured_model()}'


def run(data_path, menu=None):
    menu = menu if menu is not None else NumberedMenu()
    original = settings.load(data_path)
    config = deepcopy(original)
    models = []
    verified = set()
    table_play = ai.table_play_routing()
    laya_enabled = bool(os.environ.get('TABLEFORGE_ROUTER_URL', '').strip())
    inherited_policy = 'Table play' if table_play else 'Laya' if laya_enabled else 'Server default'
    menu.setup(settings.path_for(data_path), inherited_policy, ai.configured_model())
    choices = {
        **{('tiers', tier): f'Laya / {tier.title()}' for tier in settings.TIERS},
        **{('requests', name): label for name, label in settings.REQUESTS.items()},
    }
    sections = {('tiers', 'cheap'): 'LAYA TIERS', ('requests', 'advance'): 'TABLEFORGE REQUEST TYPES',
                'save': 'ACTIONS'}
    focus = next(iter(choices))
    while True:
        rows = {key: f'{label:<24} | {describe(*key, config[key[0]].get(key[1], {}), table_play, laya_enabled)}'
                for key, label in choices.items()}
        dirty = config != original
        action = menu.choose('AI routing', {
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
                    pending = model_choices(config) - model_choices(original) - verified
                    if pending:
                        menu.notice(f'OpenAI will receive {len(pending)} short compatibility check(s) before saving. '
                                    'These use API tokens.')
                        if menu.choose('Confirm compatibility checks',
                                       {True: 'Verify and save', False: 'Back'}, False) is not True:
                            continue
                        probe_models(sorted(pending), verified, menu.progress)
                    settings.save(data_path, config, expected=original)
                    return 'Saved. TableForge reads the changes on the next AI request.'
                return
            group, name = action
            row = edit_row(group, choices[action], config[group].get(name, {}), models, laya_enabled, menu)
            if row:
                config[group][name] = row
            else:
                config[group].pop(name, None)
        except (OSError, ValueError) as error:
            menu.notice(str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env',
                        help='Load the same settings file used by the TableForge server.')
    parser.add_argument('--plain', action='store_true', help='Use numbered prompts.')
    args = parser.parse_args()
    try:
        load_env(args.env_file)
        data_path = Path(os.environ.get('TABLEFORGE_DATA', ROOT / 'data'))
        curses = None if args.plain else terminal_library()
        if curses is None:
            result = run(data_path)
        else:
            result = curses.wrapper(lambda screen: run(data_path, TerminalMenu(screen, curses)))
        if result:
            print(result, flush=True)
    except (EOFError, KeyboardInterrupt):
        print('\nEditor closed without saving.')
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
