"""Cartridge-supplied Stage 3 instructions plus the versioned console adapter."""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / 'prompts'
INTEGRATION_VERSION = '1'
# Digests use UTF-8 text with LF newlines, independent of checkout line endings.
INTEGRATION_SHA256 = '8d1a4ebf1a3b2621b55279e043991eb994047ac47dc3761a6a2a0e0dbeeedd70'
RESOURCE = 'stage3-run-prompt.md'
LEGACY_INSTRUCTIONS = (
    'You are the AI-DM for TableForge, running an AdventureForge cartridge. '
    'Narrate the scene and play NPCs. Treat the transcript as what has already happened. '
    'Do not run combat turns. Do not ask players to reconfirm actions they already declared.'
)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def make_snapshot(kind, version, integration, instructions, source_sha=None):
    return {'kind': kind, 'version': version, 'integrationVersion': integration,
            'instructions': instructions, 'sha256': digest(instructions), 'sourceSha256': source_sha}


def legacy_snapshot():
    return make_snapshot('legacy', 'legacy-1', None, LEGACY_INSTRUCTIONS)


def read_asset(name, expected):
    try:
        text = (PROMPT_DIR / name).read_text(encoding='utf-8')
    except (OSError, UnicodeError) as error:
        raise ValueError(f'Required AI-DM prompt could not be loaded: {name}. Restore the bundled prompt file.') from error
    if not text.strip() or digest(text) != expected:
        raise ValueError(f'Required AI-DM prompt failed its integrity check: {name}. Restore the bundled prompt file.')
    return text


def read_source(data):
    try:
        source = data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeError as error:
        raise ValueError('Stage 3 prompt must be UTF-8 Markdown') from error
    versions = re.findall(r'\bpromptVersion\b[\s:*`]+(\d+\.\d+\.\d+)\b', source)
    if not source.strip() or not versions or len(set(versions)) != 1:
        raise ValueError('Stage 3 prompt needs a promptVersion banner (for example, 2.1.1) and the full prompt text')
    return source, versions[0]


def cartridge_snapshot(files, resources):
    path = resources.get(RESOURCE)
    if not path or path not in files:
        raise ValueError('Cartridge is missing its Stage 3 run prompt. Re-export it from AdventureForge with stage3Prompt included.')
    source, version = read_source(files[path])
    integration = read_asset(f'tableforge-integration-v{INTEGRATION_VERSION}.md', INTEGRATION_SHA256)
    instructions = integration + '\n\n---\n\n# AdventureForge Stage 3 source (integration above takes precedence)\n\n' + source
    return make_snapshot('stage3', version, INTEGRATION_VERSION, instructions, digest(source))


def metadata(prompt):
    return {key: value for key, value in prompt.items() if key != 'instructions'}


def decode(raw):
    try:
        prompt = json.loads(raw)
        if (not isinstance(prompt, dict) or prompt.get('kind') not in ('legacy', 'stage3')
                or not isinstance(prompt.get('version'), str)
                or not isinstance(prompt.get('instructions'), str) or not prompt['instructions'].strip()
                or prompt.get('sha256') != digest(prompt['instructions'])):
            raise ValueError()
    except (TypeError, ValueError) as error:
        raise ValueError('Saved AI-DM prompt is missing or damaged. Restore a verified save backup.') from error
    return prompt


def store(conn, prompt):
    conn.execute('INSERT OR IGNORE INTO narration_prompts (sha256,snapshot) VALUES (?,?)',
                 (prompt['sha256'], json.dumps(prompt)))
    return prompt['sha256']


def for_save(conn, save_id):
    row = conn.execute('SELECT p.snapshot,p.sha256 FROM saves s LEFT JOIN narration_prompts p '
                       'ON p.sha256=s.narration_prompt_id WHERE s.id=?', (save_id,)).fetchone()
    prompt = decode(row[0] if row else None)
    if prompt['sha256'] != row[1]:
        raise ValueError('Saved AI-DM prompt identity is damaged. Restore a verified save backup.')
    return prompt


def load_saved(data_dir, save_id):
    # Read only; context assembly never migrates or silently substitutes instructions.
    uri = (Path(data_dir) / 'tableforge.sqlite3').resolve().as_uri() + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    try:
        return for_save(conn, save_id)
    finally:
        conn.close()
