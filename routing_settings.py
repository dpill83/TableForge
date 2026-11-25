"""Host-wide OpenAI overrides for TableForge requests and Laya tiers."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

TIERS = ('cheap', 'standard', 'heavy')
REQUESTS = {
    'advance': 'Normal narration',
    'opening': 'Adventure opening',
    'aftermath': 'Combat aftermath',
    'ooc': 'Public OOC question',
    'ask': 'Private Pilot Ask',
    'summary': 'Campaign summary',
}
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
MODEL_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,199}')


def path_for(data_path):
    return Path(data_path) / 'ai-routing.sqlite3'


def validate(settings):
    if not isinstance(settings, dict) or settings.keys() != {'tiers', 'requests'}:
        raise ValueError('AI routing settings require tiers and requests.')
    for group, names in (('tiers', TIERS), ('requests', REQUESTS)):
        rows = settings[group]
        if not isinstance(rows, dict) or not rows.keys() <= set(names):
            raise ValueError(f'Invalid AI routing {group}.')
        for name, row in rows.items():
            allowed = {'model', 'effort'} if group == 'tiers' else {'mode', 'model', 'effort'}
            if not isinstance(row, dict) or not row.keys() <= allowed:
                raise ValueError(f'Invalid AI routing fields for {name}.')
            model = row.get('model')
            effort = row.get('effort', 'auto')
            if model is not None and (not isinstance(model, str) or not MODEL_ID.fullmatch(model)):
                raise ValueError(f'Invalid OpenAI model ID for {name}.')
            mode = row.get('mode')
            if group == 'requests' and (mode not in ('fixed', 'laya') or (mode == 'fixed') != bool(model)):
                raise ValueError(f'Choose Laya or a fixed model for {name}.')
            if effort not in ('auto', 'default', *EFFORTS) or (mode == 'fixed' and effort == 'auto'):
                raise ValueError(f'Invalid reasoning effort for {name}.')
    return settings


def read(connection):
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone():
        row = connection.execute('SELECT config FROM settings WHERE id=1').fetchone()
        if row is not None:
            return validate(json.loads(row[0]))
    return {'tiers': {}, 'requests': {}}


def load(data_path):
    path = path_for(data_path)
    if not path.exists():
        return {'tiers': {}, 'requests': {}}
    try:
        with closing(sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True)) as connection:
            return read(connection)
    except (sqlite3.Error, ValueError, RecursionError) as error:
        raise ValueError('Cannot load AI routing settings from ai-routing.sqlite3.') from error


def save(data_path, settings, *, expected=None):
    validate(settings)
    path = path_for(data_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            if expected is not None and read(connection) != expected:
                raise ValueError('Another editor saved routing changes. Reopen the editor before saving.')
            connection.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, config TEXT NOT NULL)')
            connection.execute('INSERT OR REPLACE INTO settings (id, config) VALUES (1, ?)', (json.dumps(settings),))
    except sqlite3.Error as error:
        raise ValueError('Cannot save AI routing settings to ai-routing.sqlite3.') from error
