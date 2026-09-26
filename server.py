"""Local TableForge server. Start with: python3 server.py"""
import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import ai
import backups
import metering
import scene_images
import module_context
import runtime_prompts
from local_config import load_env

ROOT = Path(__file__).resolve().parent
load_env(ROOT / '.env')
WEB = ROOT / "web"
DATA = Path(os.environ.get("TABLEFORGE_DATA", ROOT / "data"))
LOCK = threading.RLock()
# save_id -> 'advance' | 'ask' while the AI-DM is generating.
GENERATING = {}
# save_id -> {player_id: monotonic expiry}; presence only, never saved.
TYPING = {}
TYPING_SECONDS = 6
MAX_REQUEST = 32 * 1024 * 1024
MAX_PORTRAIT_BYTES = 5 * 1024 * 1024
PORTRAIT_SIGNATURES = {
    'image/png': lambda data: data.startswith(b'\x89PNG\r\n\x1a\n'),
    'image/jpeg': lambda data: data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'),
    'image/webp': lambda data: data.startswith(b'RIFF') and data[8:12] == b'WEBP',
}
ASSET_MIMES = {'image/png', 'image/jpeg', 'image/webp'}
REQUIRED = ("module.md", "run-data.json", runtime_prompts.RESOURCE)
OPTIONAL = ("cast.json", "cast.md", "continuity.json", "scenes.json", "music-cues.json", "map-art-brief.md")
RESOURCE_KEYS = {
    'module.md': 'module', 'run-data.json': 'runData',
    runtime_prompts.RESOURCE: 'stage3Prompt',
    'cast.json': 'cast', 'cast.md': 'castMarkdown',
    'continuity.json': 'continuity', 'scenes.json': 'scenes',
    'music-cues.json': 'musicCues', 'map-art-brief.md': 'mapArtBrief',
}


class StaleBeat(ValueError):
    """A contribution was drafted for a beat the table has already left."""

    def __init__(self, beat):
        super().__init__('The AI-DM continued while you were writing. Review your message before sending it.')
        self.beat = beat


def utc():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / "tableforge.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cartridges (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL,
                resources TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS saves (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, cartridge_id TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'normal', beat INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(cartridge_id) REFERENCES cartridges(id)
            );
            CREATE TABLE IF NOT EXISTS players (
                id TEXT PRIMARY KEY, save_id TEXT NOT NULL, name TEXT NOT NULL,
                character TEXT NOT NULL, ready INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(save_id) REFERENCES saves(id)
            );
            CREATE TABLE IF NOT EXISTS player_portraits (
                player_id TEXT PRIMARY KEY, save_id TEXT NOT NULL,
                mime TEXT NOT NULL, image BLOB NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(player_id) REFERENCES players(id),
                FOREIGN KEY(save_id) REFERENCES saves(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL,
                player_id TEXT, kind TEXT NOT NULL, name TEXT NOT NULL,
                body TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(save_id) REFERENCES saves(id)
            );
            CREATE TABLE IF NOT EXISTS pilot_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL,
                player_id TEXT, kind TEXT NOT NULL, name TEXT NOT NULL,
                body TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(save_id) REFERENCES saves(id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, save_id TEXT NOT NULL, number INTEGER NOT NULL,
                started_at TEXT NOT NULL, ended_at TEXT, ended_by TEXT,
                participants TEXT NOT NULL, UNIQUE(save_id, number),
                FOREIGN KEY(save_id) REFERENCES saves(id)
            );
            CREATE TABLE IF NOT EXISTS session_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL,
                session_id TEXT NOT NULL, player_id TEXT, kind TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                FOREIGN KEY(save_id) REFERENCES saves(id),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL,
                session_id TEXT NOT NULL UNIQUE, beat INTEGER NOT NULL,
                mode TEXT NOT NULL, last_message_id INTEGER,
                ready TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                FOREIGN KEY(save_id) REFERENCES saves(id),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL,
                through_message_id INTEGER NOT NULL, based_on INTEGER,
                body TEXT NOT NULL, player_id TEXT, created_at TEXT NOT NULL,
                FOREIGN KEY(save_id) REFERENCES saves(id),
                FOREIGN KEY(based_on) REFERENCES summaries(id)
            );
            CREATE TABLE IF NOT EXISTS ai_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                save_id TEXT NOT NULL, session_id TEXT NOT NULL,
                purpose TEXT NOT NULL, model TEXT NOT NULL,
                input_tokens INTEGER, cached_tokens INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER, total_tokens INTEGER,
                estimated_cost_usd REAL, service_tier TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(save_id) REFERENCES saves(id),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS party_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL,
                category TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
                created_by TEXT, created_at TEXT NOT NULL,
                updated_by TEXT, updated_at TEXT NOT NULL, removed_at TEXT, removed_by TEXT,
                FOREIGN KEY(save_id) REFERENCES saves(id)
            );
            CREATE TABLE IF NOT EXISTS revealed_assets (
                save_id TEXT NOT NULL, asset_id TEXT NOT NULL, path TEXT NOT NULL,
                media_type TEXT NOT NULL, revealed_by TEXT, revealed_at TEXT NOT NULL,
                PRIMARY KEY(save_id, asset_id),
                FOREIGN KEY(save_id) REFERENCES saves(id)
            );
            CREATE TABLE IF NOT EXISTS narration_prompts (
                sha256 TEXT PRIMARY KEY, snapshot TEXT NOT NULL
            );
        """)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(saves)')}
        if 'narration_prompt_id' not in columns:
            conn.execute('ALTER TABLE saves ADD COLUMN narration_prompt_id TEXT REFERENCES narration_prompts(sha256)')
            legacy_id = runtime_prompts.store(conn, runtime_prompts.legacy_snapshot())
            conn.execute('UPDATE saves SET narration_prompt_id=?', (legacy_id,))
        if 'resource_bindings' not in columns:
            conn.execute('ALTER TABLE saves ADD COLUMN resource_bindings TEXT')
        if 'adventure_title' not in columns:
            conn.execute('ALTER TABLE saves ADD COLUMN adventure_title TEXT')
        if 'format_version' not in columns:
            conn.execute('ALTER TABLE saves ADD COLUMN format_version INTEGER NOT NULL DEFAULT 1')
        if 'location' not in columns:
            # NULL means the party has not yet reached the site (approach).
            conn.execute('ALTER TABLE saves ADD COLUMN location INTEGER')
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(messages)')}
        if 'session_id' not in columns:
            conn.execute('ALTER TABLE messages ADD COLUMN session_id TEXT')
        if 'image_id' not in columns:
            conn.execute('ALTER TABLE messages ADD COLUMN image_id TEXT')
        if 'request_id' not in columns:
            # Client-minted per contribution so a retried send can never post twice.
            conn.execute('ALTER TABLE messages ADD COLUMN request_id TEXT')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS messages_request ON messages(save_id, request_id) '
                     'WHERE request_id IS NOT NULL')
        scene_images.initialize(conn)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(cartridges)')}
        if 'content_hash' not in columns:
            conn.execute('ALTER TABLE cartridges ADD COLUMN content_hash TEXT')
        for cartridge in list(conn.execute('SELECT id FROM cartridges WHERE content_hash IS NULL')):
            path = DATA / 'cartridges' / (cartridge['id'] + '.zip')
            if path.is_file():
                try:
                    fingerprint = content_fingerprint(read_archive(path.read_bytes()))
                    conn.execute('UPDATE cartridges SET content_hash=? WHERE id=?', (fingerprint, cartridge['id']))
                except (OSError, ValueError, zipfile.BadZipFile):
                    pass
        for save in list(conn.execute('SELECT id,created_at FROM saves WHERE NOT EXISTS (SELECT 1 FROM sessions WHERE sessions.save_id=saves.id)')):
            session_id = str(uuid.uuid4())
            participants = [row['id'] for row in conn.execute('SELECT id FROM players WHERE save_id=? ORDER BY rowid', (save['id'],))]
            conn.execute('INSERT INTO sessions (id,save_id,number,started_at,participants) VALUES (?,?,?,?,?)',
                         (session_id, save['id'], 1, save['created_at'], json.dumps(participants)))
            conn.execute('UPDATE messages SET session_id=? WHERE save_id=? AND session_id IS NULL', (session_id, save['id']))


def package_manifest(files):
    candidates = [name for name in files if Path(name.replace('\\', '/')).name.lower() == 'manifest.json']
    if not candidates:
        return {}, None
    if len(candidates) > 1:
        raise ValueError('Cartridge contains multiple manifest.json files')
    path = candidates[0]
    try:
        manifest = json.loads(files[path].decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('manifest.json is not valid UTF-8 JSON') from error
    if not isinstance(manifest, dict):
        raise ValueError('manifest.json must contain an object')
    if manifest.get('format') != 'tableforge-adventure' or type(manifest.get('formatVersion')) is not int or manifest['formatVersion'] != 1:
        raise ValueError('Unsupported cartridge format or formatVersion')
    if not isinstance(manifest.get('resources'), dict):
        raise ValueError('manifest.json resources must contain an object')
    return manifest, path


def package_assets(files, manifest=None, manifest_path=None):
    """Return inert image assets declared by the cartridge manifest."""
    if manifest is None:
        manifest, manifest_path = package_manifest(files)
    declared = manifest.get('assets', [])
    if not isinstance(declared, list):
        raise ValueError('manifest.json assets must contain an array')
    prefix = manifest_path.rsplit('/', 1)[0] + '/' if manifest_path and '/' in manifest_path else ''
    assets, seen = [], set()
    for item in declared:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str) or item.get('mediaType') not in ASSET_MIMES:
            raise ValueError('manifest.json has an invalid image asset')
        candidate = item['path'].replace('\\', '/')
        if candidate not in files and prefix + candidate in files:
            candidate = prefix + candidate
        if candidate not in files:
            raise ValueError('manifest.json image asset is not in the cartridge')
        asset_id = hashlib.sha256(candidate.encode()).hexdigest()[:16]
        if candidate in seen:
            raise ValueError('manifest.json contains a duplicate image asset')
        seen.add(candidate)
        assets.append({'id': asset_id, 'path': candidate, 'mediaType': item['mediaType']})
    return assets


def validate_bindings(files, resources, require_manifest=True):
    if not isinstance(resources, dict) or any(key not in RESOURCE_KEYS for key in resources):
        raise ValueError('Invalid resource bindings')
    manifest, manifest_path = package_manifest(files)
    assets = package_assets(files, manifest, manifest_path)
    bindings = {}
    missing = ['manifest.json'] if require_manifest and not manifest_path else []
    invalid = {}
    warnings = {}
    if manifest_path and not str(manifest.get('title') or '').strip():
        invalid['manifest.json'] = 'Manifest needs a title'
    for role in REQUIRED + OPTIONAL:
        path = resources.get(role)
        if path == '':
            path = None
        if path is not None and not isinstance(path, str):
            raise ValueError(f'Invalid binding for {role}')
        bindings[role] = path
        if path is None:
            if role in REQUIRED and (require_manifest or role != runtime_prompts.RESOURCE):
                missing.append(role)
        elif path not in files:
            invalid[role] = 'File is not in the cartridge'
    run_data = None
    prompt_path = bindings[runtime_prompts.RESOURCE]
    if prompt_path in files:
        try:
            runtime_prompts.read_source(files[prompt_path])
        except ValueError as error:
            invalid[runtime_prompts.RESOURCE] = str(error)
    module_path = bindings['module.md']
    run_path = bindings['run-data.json']
    if module_path in files:
        try:
            files[module_path].decode('utf-8')
        except UnicodeDecodeError:
            invalid['module.md'] = 'Module must be UTF-8 text'
    if run_path in files:
        try:
            run_data = json.loads(files[run_path].decode('utf-8'))
            if not isinstance(run_data, dict):
                raise ValueError('Run data must contain a JSON object')
            rooms = run_data.get('rooms')
            if rooms is not None and (not isinstance(rooms, list) or any(
                    not isinstance(room, dict) or type(room.get('roomNumber')) is not int for room in rooms)):
                raise ValueError('Run data rooms must be an array of objects with integer roomNumber values')
            party = run_data.get('party')
            if party is not None and not isinstance(party, list):
                raise ValueError('Run data party must be an array')
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            invalid['run-data.json'] = 'Run data must contain a UTF-8 JSON object'
    for role in module_context.OPTIONAL_JSON:
        path = bindings[role]
        if path in files:
            try:
                json.loads(files[path].decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                invalid[role] = 'File must contain valid UTF-8 JSON'
    for role in module_context.OPTIONAL_TEXT:
        path = bindings[role]
        if path in files:
            try:
                files[path].decode('utf-8')
            except UnicodeDecodeError:
                invalid[role] = 'File must contain UTF-8 text'
    if module_path in files and run_data and 'module.md' not in invalid and 'run-data.json' not in invalid:
        adventure = module_context.Adventure(files[module_path].decode('utf-8'), run_data)
        if adventure.rooms and not adventure.focused:
            absent = sorted(set(adventure.rooms) - set(adventure.area_sections))
            warnings['module.md'] = ('Full module will be sent because these run-data rooms have no matching '
                                     'Area headings: ' + ', '.join(map(str, absent)))
    setup_players = []
    if run_data:
        for character in run_data.get('party') or []:
            name = str(character.get('name') or '').strip() if isinstance(character, dict) else ''
            if name:
                setup_players.append({'player': '', 'character': name})
    title = str(manifest.get('title') or '').strip()
    if not title and run_data:
        title = str(run_data.get('title') or run_data.get('adventureTitle') or run_data.get('adventureName') or '').strip()
    return {'title': title or 'Untitled Adventure', 'resources': bindings,
            'missing': missing, 'invalid': invalid, 'warnings': warnings, 'manifest': manifest_path,
            'setupPlayers': setup_players, 'assets': assets}


def inspect_cartridge(files):
    manifest, manifest_path = package_manifest(files)
    names = {}
    for path in files:
        names.setdefault(Path(path.replace('\\', '/')).name.lower(), []).append(path)
    bindings = {}
    declared = manifest.get('resources', {})
    prefix = manifest_path.rsplit('/', 1)[0] + '/' if manifest_path and '/' in manifest_path else ''
    for role in REQUIRED + OPTIONAL:
        key = RESOURCE_KEYS[role]
        if key in declared:
            path = declared[key]
            if path is not None and not isinstance(path, str):
                raise ValueError(f'manifest.json has an invalid {key} binding')
            candidate = path.replace('\\', '/') if path else None
            if candidate and candidate not in files and prefix + candidate in files:
                candidate = prefix + candidate
        else:
            matches = names.get(role, [])
            if role == runtime_prompts.RESOURCE:
                matches = [path for name, paths in names.items()
                           if name == role or re.fullmatch(r'stage3-run-prompt-v\d+\.\d+\.\d+\.md', name)
                           for path in paths]
            candidate = matches[0] if len(matches) == 1 else None
        bindings[role] = candidate
    return {**validate_bindings(files, bindings), 'files': sorted(files)}


def read_archive(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > 500:
            raise ValueError('Too many files in cartridge')
        if sum(item.file_size for item in archive.infolist()) > MAX_REQUEST:
            raise ValueError('Unpacked cartridge is too large')
        files = {}
        for item in archive.infolist():
            if item.is_dir():
                continue
            path = Path(item.filename.replace('\\', '/'))
            if path.is_absolute() or '..' in path.parts or item.file_size > MAX_REQUEST:
                raise ValueError('Unsafe cartridge entry')
            if item.filename in files:
                raise ValueError('Duplicate cartridge entry')
            files[item.filename] = archive.read(item)
        return files


def content_fingerprint(files):
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        encoded = name.replace('\\', '/').encode('utf-8')
        digest.update(len(encoded).to_bytes(4, 'big'))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, 'big'))
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def stored_cartridge_files(cartridge_id):
    path = DATA / 'cartridges' / (cartridge_id + '.zip')
    if not path.is_file():
        raise ValueError('Locate the cartridge for this save')
    return read_archive(path.read_bytes())


def unpack_payload(payload):
    kind = payload.get('kind')
    if kind == 'zip':
        raw = base64.b64decode(payload.get('data') or '', validate=True)
        if len(raw) > MAX_REQUEST:
            raise ValueError("Cartridge is too large (32 MB maximum)")
        return read_archive(raw), raw
    if kind == 'files':
        files = {item['name']: base64.b64decode(item['data'] or '', validate=True) for item in payload.get('files', [])}
        if sum(map(len, files.values())) > MAX_REQUEST:
            raise ValueError('Cartridge is too large (32 MB maximum)')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                path = Path(name)
                if path.is_absolute() or '..' in path.parts:
                    raise ValueError('Unsafe cartridge entry')
                archive.writestr(name, content)
        return files, stream.getvalue()
    raise ValueError('Choose a ZIP file or a folder')


def active_session(conn, save_id):
    return conn.execute('SELECT * FROM sessions WHERE save_id=? AND ended_at IS NULL ORDER BY number DESC LIMIT 1',
                        (save_id,)).fetchone()


def start_session(conn, save_id):
    if active_session(conn, save_id):
        return
    number = conn.execute('SELECT COALESCE(MAX(number),0)+1 FROM sessions WHERE save_id=?', (save_id,)).fetchone()[0]
    participants = [row['id'] for row in conn.execute('SELECT id FROM players WHERE save_id=? ORDER BY rowid', (save_id,))]
    conn.execute('INSERT INTO sessions (id,save_id,number,started_at,participants) VALUES (?,?,?,?,?)',
                 (str(uuid.uuid4()), save_id, number, utc(), json.dumps(participants)))
    if number > 1:
        conn.execute('UPDATE players SET ready=0 WHERE save_id=?', (save_id,))
    conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (utc(), save_id))


def require_player(state, player_id):
    player = next((item for item in state['players'] if item['id'] == player_id), None)
    if not player:
        raise ValueError('Select a player first')
    return player


def snapshot(conn, save_id):
    save = conn.execute('SELECT * FROM saves WHERE id=?', (save_id,)).fetchone()
    if not save:
        raise ValueError('Save not found')
    if save['format_version'] != 1:
        raise ValueError('Unsupported save format version')
    cartridge = conn.execute('SELECT * FROM cartridges WHERE id=?', (save['cartridge_id'],)).fetchone()
    resources = json.loads(save['resource_bindings']) if save['resource_bindings'] else json.loads(cartridge['resources'])
    sessions = [dict(row) for row in conn.execute('SELECT * FROM sessions WHERE save_id=? ORDER BY number', (save_id,))]
    for session in sessions:
        session['participants'] = json.loads(session['participants'])
    checkpoint = conn.execute('SELECT * FROM checkpoints WHERE save_id=? ORDER BY id DESC LIMIT 1', (save_id,)).fetchone()
    checkpoint = dict(checkpoint) if checkpoint else None
    if checkpoint:
        checkpoint['ready'] = json.loads(checkpoint['ready'])
    players = [dict(row) for row in conn.execute('SELECT * FROM players WHERE save_id=? ORDER BY rowid', (save_id,))]
    summary = conn.execute(
        'SELECT s.*, p.character AS player_character FROM summaries s LEFT JOIN players p ON p.id=s.player_id '
        'WHERE s.save_id=? ORDER BY s.id DESC LIMIT 1', (save_id,)).fetchone()
    portraits = {row['player_id']: row['updated_at'] for row in conn.execute(
        'SELECT player_id,updated_at FROM player_portraits WHERE save_id=?', (save_id,))}
    for player in players:
        player['portraitUrl'] = (f'/api/saves/{save_id}/players/{player["id"]}/portrait?v={quote(portraits[player["id"]], safe="")}'
                                 if player['id'] in portraits else None)
    return {
        'save': dict(save),
        'cartridge': {'id': cartridge['id'], 'title': save['adventure_title'] or cartridge['title'],
                      'resources': resources, 'available': (DATA / 'cartridges' / (cartridge['id'] + '.zip')).is_file()},
        'players': players,
        'messages': [dict(row) for row in conn.execute('SELECT * FROM messages WHERE save_id=? ORDER BY id', (save_id,))],
        'pilot': [dict(row) for row in conn.execute('SELECT * FROM pilot_messages WHERE save_id=? ORDER BY id', (save_id,))],
        'sessions': sessions,
        'events': [dict(row) for row in conn.execute('SELECT * FROM session_events WHERE save_id=? ORDER BY id', (save_id,))],
        'checkpoint': checkpoint,
        'summary': dict(summary) if summary else None,
        'notes': [dict(row) for row in conn.execute(
            'SELECT id,category,title,body,created_by,created_at,updated_by,updated_at FROM party_notes '
            'WHERE save_id=? AND removed_at IS NULL ORDER BY category, title COLLATE NOCASE, id', (save_id,))],
        'activity': activity(save_id),
        'images': scene_images.list_images(conn, save_id, shared_only=True),
        'imageSettings': scene_images.settings(),
        'imageUsage': {
            'session': metering.image_summary(conn, 'WHERE session_id=?', (sessions[-1]['id'],)) if sessions else metering.image_summary(conn, 'WHERE 0'),
            'save': metering.image_summary(conn, 'WHERE save_id=?', (save_id,)),
        },
        'usage': {
            'session': metering.summary(conn, 'WHERE session_id=?', (sessions[-1]['id'],)) if sessions else metering.summary(conn, 'WHERE 0'),
            'save': metering.summary(conn, 'WHERE save_id=?', (save_id,)),
            'pricingAsOf': metering.PRICING_AS_OF,
            'pricingUrl': metering.PRICING_URL,
        },
    }


def typing_players(save_id):
    now = time.monotonic()
    typing = {pid: expiry for pid, expiry in TYPING.get(save_id, {}).items() if expiry > now}
    TYPING[save_id] = typing
    return sorted(typing)


def activity(save_id):
    return {'aiDm': GENERATING.get(save_id), 'typing': typing_players(save_id)}


def begin_advance(conn, save_id, payload):
    state = snapshot(conn, save_id)
    if not state['cartridge']['available']:
        raise ValueError('Locate the cartridge before advancing')
    if not active_session(conn, save_id):
        raise ValueError('Start the next session before advancing')
    if state['save']['mode'] != 'normal':
        raise ValueError('Resume combat explicitly')
    if payload.get('override'):
        # An override is a Pilot decision; the table should always be able to see who made it.
        initiator = require_player(state, payload.get('playerId'))
    elif not all(p['ready'] for p in state['players']):
        raise ValueError('Waiting for all players to be Ready')
    beat = state['save']['beat']
    if payload.get('beat') is not None and int(payload['beat']) != beat:
        raise ValueError('This beat has already advanced')
    if save_id in GENERATING:
        raise ValueError('The AI-DM is already responding')
    context = ai.build_context(state, DATA)
    GENERATING[save_id] = 'advance'
    if payload.get('override'):
        # Kept outside the provider context and saved only if the advance is published.
        context = {**context, 'override': {
            'playerId': initiator['id'], 'beat': beat,
            'ready': {p['id']: bool(p['ready']) for p in state['players']},
            'waitingOn': [p['id'] for p in state['players'] if not p['ready']],
        }}
    return context


def begin_ask(conn, save_id, payload):
    state = snapshot(conn, save_id)
    if not state['cartridge']['available']:
        raise ValueError('Locate the cartridge before asking the AI-DM')
    if not active_session(conn, save_id):
        raise ValueError('Start the next session before playing')
    player = require_player(state, payload.get('playerId'))
    body = str(payload.get('text', '')).strip()
    if not body or len(body) > 20000:
        raise ValueError('Message must contain 1 to 20,000 characters')
    if save_id in GENERATING:
        raise ValueError('The AI-DM is already responding')
    conn.execute(
        'INSERT INTO pilot_messages (save_id,player_id,kind,name,body,created_at) VALUES (?,?,?,?,?,?)',
        (save_id, player['id'], 'pilot', player['character'], body, utc()),
    )
    conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (utc(), save_id))
    context = ai.build_context(snapshot(conn, save_id), DATA, purpose='ask')
    GENERATING[save_id] = 'ask'
    return context


def context_preview(conn, save_id):
    """The exact provider payload the next advance would send, with everything left out."""
    state = snapshot(conn, save_id)
    if not state['cartridge']['available']:
        raise ValueError('Locate the cartridge to review AI context')
    context = ai.build_context(state, DATA)
    report = context.pop('report')
    update, update_error = None, None
    try:
        candidate, _ = cartridge_prompt_for(state)
        if candidate['sha256'] != report['narrationPrompt']['sha256']:
            update = candidate
    except ValueError as error:
        update_error = str(error)
    return {'purpose': context['purpose'], 'beat': context['beat'], 'mode': state['save']['mode'],
            'runtime': ai.runtime_status(), 'messages': ai.chat_messages(context), 'report': report,
            'summary': state['summary'], 'promptUpdate': update, 'promptUpdateError': update_error}


def upgrade_narration_prompt(conn, state, session, payload):
    if payload.get('pilot') is not True or payload.get('confirm') is not True:
        raise ValueError('Review and confirm the AI-DM prompt upgrade in Pilot Mode')
    player = require_player(state, payload.get('playerId'))
    current = runtime_prompts.for_save(conn, state['save']['id'])
    candidate, bindings = cartridge_prompt_for(state)
    if payload.get('fromSha256') != current['sha256'] or payload.get('toSha256') != candidate['sha256']:
        raise ValueError('The AI-DM prompt changed. Review the prompt upgrade again')
    if current['sha256'] == candidate['sha256']:
        return
    prompt_id = runtime_prompts.store(conn, candidate)
    stamp = utc()
    conn.execute('UPDATE saves SET narration_prompt_id=?,resource_bindings=?,updated_at=? WHERE id=?',
                 (prompt_id, json.dumps(bindings), stamp, state['save']['id']))
    conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) VALUES (?,?,?,?,?,?)',
                 (state['save']['id'], session['id'], player['id'], 'prompt_upgrade',
                  json.dumps({'from': runtime_prompts.metadata(current), 'to': runtime_prompts.metadata(candidate)}), stamp))


def cartridge_prompt_for(state):
    files = stored_cartridge_files(state['cartridge']['id'])
    bindings = dict(state['cartridge']['resources'])
    # Saves from before cartridge prompts have no binding for this resource.
    if runtime_prompts.RESOURCE not in bindings:
        bindings[runtime_prompts.RESOURCE] = inspect_cartridge(files)['resources'][runtime_prompts.RESOURCE]
    return runtime_prompts.cartridge_snapshot(files, bindings), bindings


def begin_summary(conn, save_id, payload):
    state = snapshot(conn, save_id)
    if not active_session(conn, save_id):
        raise ValueError('Start the next session before summarizing')
    require_player(state, payload.get('playerId'))
    if save_id in GENERATING:
        raise ValueError('The AI-DM is already responding')
    context = ai.build_summary_context(state)
    context['basedOn'] = state['summary']['id'] if state['summary'] else None
    GENERATING[save_id] = 'summary'
    return context


def save_summary(conn, save_id, payload):
    state = snapshot(conn, save_id)
    player = require_player(state, payload.get('playerId'))
    body = str(payload.get('text') or '').strip()
    if not body or len(body) > 20000:
        raise ValueError('Summary must contain 1 to 20,000 characters')
    current = state['summary']
    if payload.get('basedOn') != (current['id'] if current else None):
        raise ValueError('Another summary was saved first. Draft a new summary from the latest one.')
    through = int(payload.get('throughMessageId'))
    history, _ = ai.split_beat(state['messages'])
    if not any(message['id'] == through for message in history):
        raise ValueError('Summaries can only cover completed beats')
    if current and through <= current['through_message_id']:
        raise ValueError('This history is already summarized')
    conn.execute('INSERT INTO summaries (save_id,through_message_id,based_on,body,player_id,created_at) VALUES (?,?,?,?,?,?)',
                 (save_id, through, current['id'] if current else None, body, player['id'], utc()))
    conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (utc(), save_id))


NOTE_CATEGORIES = ('npc', 'location', 'world')


def save_note(conn, state, payload):
    """Pilot-authored party knowledge. Only what the table chooses to write down is ever shown."""
    player = require_player(state, payload.get('playerId'))
    if payload.get('pilot') is not True:
        raise ValueError('Enable Pilot Mode to edit party knowledge')
    save_id, stamp = state['save']['id'], utc()
    note_id = payload.get('id')
    if note_id is not None:
        if type(note_id) is not int or not conn.execute(
                'SELECT 1 FROM party_notes WHERE id=? AND save_id=? AND removed_at IS NULL', (note_id, save_id)).fetchone():
            raise ValueError('This note no longer exists')
    if payload.get('remove') is True:
        if note_id is None:
            raise ValueError('Choose a note to remove')
        # Kept in the save as history; it just stops appearing in reference views.
        conn.execute('UPDATE party_notes SET removed_at=?,removed_by=? WHERE id=?', (stamp, player['id'], note_id))
    else:
        category = payload.get('category')
        title = str(payload.get('title') or '').strip()
        body = str(payload.get('body') or '').strip()
        if category not in NOTE_CATEGORIES:
            raise ValueError('Choose NPCs, Locations, or World Notes')
        if not title or len(title) > 200:
            raise ValueError('Note title must contain 1 to 200 characters')
        if len(body) > 10000:
            raise ValueError('Note text must be 10,000 characters or less')
        if note_id is None:
            conn.execute('INSERT INTO party_notes (save_id,category,title,body,created_by,created_at,updated_by,updated_at) '
                         'VALUES (?,?,?,?,?,?,?,?)', (save_id, category, title, body, player['id'], stamp, player['id'], stamp))
        else:
            conn.execute('UPDATE party_notes SET category=?,title=?,body=?,updated_by=?,updated_at=? WHERE id=?',
                         (category, title, body, player['id'], stamp, note_id))
    conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (stamp, save_id))


def adventure_for(state):
    cartridge = state['cartridge']
    return module_context.load(DATA, cartridge['id'], cartridge['resources'])


def set_location(conn, state, location, player_id, source):
    """Move the party's tracked location; every change is kept as a session event."""
    if location == state['save']['location']:
        return
    session = active_session(conn, state['save']['id'])
    conn.execute('UPDATE saves SET location=?, updated_at=? WHERE id=?', (location, utc(), state['save']['id']))
    conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) VALUES (?,?,?,?,?,?)',
                 (state['save']['id'], session['id'], player_id, 'location',
                  json.dumps({'location': location, 'source': source}), utc()))


def publish_advance(conn, save_id, text, override=None):
    session = active_session(conn, save_id)
    text, marked, location = module_context.take_marker(text)
    if not text:
        raise ValueError('The AI-DM returned an empty response')
    if marked:
        state = snapshot(conn, save_id)
        adventure = adventure_for(state)
        if adventure.focused and adventure.valid(location):
            set_location(conn, state, location, None, 'ai-dm')
    stamp = utc()
    message_id = conn.execute(
        'INSERT INTO messages (save_id,session_id,kind,name,body,created_at) VALUES (?,?,?,?,?,?)',
        (save_id, session['id'], 'ai', 'AI-DM', text, stamp),
    ).lastrowid
    if override:
        conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) VALUES (?,?,?,?,?,?)',
                     (save_id, session['id'], override['playerId'], 'ready_override',
                      json.dumps({'beat': override['beat'], 'messageId': message_id,
                                  'ready': override['ready'], 'waitingOn': override['waitingOn']}), stamp))
    conn.execute('UPDATE saves SET beat=beat+1, updated_at=? WHERE id=?', (utc(), save_id))
    conn.execute('UPDATE players SET ready=0 WHERE save_id=?', (save_id,))
    return snapshot(conn, save_id)


def publish_ask(conn, save_id, text):
    conn.execute(
        'INSERT INTO pilot_messages (save_id,kind,name,body,created_at) VALUES (?,?,?,?,?)',
        (save_id, 'ai', 'AI-DM', text, utc()),
    )
    conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (utc(), save_id))
    return snapshot(conn, save_id)


class Handler(BaseHTTPRequestHandler):
    def respond(self, value, code=200):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length > MAX_REQUEST * 2 or length < 0:
            raise ValueError('Request too large')
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            parts = path.strip('/').split('/')
            if len(parts) in (4, 5) and parts[:2] == ['api', 'saves'] and parts[3] == 'images':
                return self.get_images(parts)
            if len(parts) in (4, 5) and parts[:2] == ['api', 'saves'] and parts[3] == 'assets':
                return self.get_assets(parts)
            if len(parts) == 6 and parts[:2] == ['api', 'saves'] and parts[3] == 'players' and parts[5] == 'portrait':
                with LOCK, db() as conn:
                    portrait = conn.execute('SELECT mime,image FROM player_portraits WHERE save_id=? AND player_id=?',
                                            (parts[2], parts[4])).fetchone()
                    if not portrait:
                        return self.send_error(404)
                    image = portrait['image']
                    self.send_response(200)
                    self.send_header('Content-Type', portrait['mime'])
                    self.send_header('Content-Length', str(len(image)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    return self.wfile.write(image)
            if path == '/api/runtime':
                return self.respond(ai.runtime_status())
            if path == '/api/backups':
                return self.respond({'backups': backups.listing(DATA), 'folder': str(backups.directory(DATA).resolve())})
            if len(parts) == 3 and parts[:2] == ['api', 'backups']:
                content = backups.path_for(DATA, parts[2]).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.sqlite3')
                self.send_header('Content-Disposition', f'attachment; filename="{parts[2]}"')
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                return self.wfile.write(content)
            if path == '/api/usage':
                with LOCK, db() as conn:
                    return self.respond({'usage': metering.summary(conn),
                                         'imageUsage': metering.image_summary(conn),
                                         'pricingAsOf': metering.PRICING_AS_OF,
                                         'pricingUrl': metering.PRICING_URL})
            if path == '/api/saves':
                with LOCK, db() as conn:
                    rows = conn.execute('''
                        SELECT s.id,s.name,s.updated_at,s.cartridge_id,
                               COALESCE(s.adventure_title,c.title) AS title,
                               (SELECT number FROM sessions WHERE save_id=s.id ORDER BY number DESC LIMIT 1) AS session_number,
                               (SELECT ended_at FROM sessions WHERE save_id=s.id ORDER BY number DESC LIMIT 1) AS session_ended_at
                        FROM saves s JOIN cartridges c ON c.id=s.cartridge_id ORDER BY s.updated_at DESC
                    ''').fetchall()
                    saves = []
                    for row in rows:
                        item = dict(row)
                        item['cartridgeAvailable'] = (DATA / 'cartridges' / (item['cartridge_id'] + '.zip')).is_file()
                        saves.append(item)
                    return self.respond({'saves': saves})
            if len(parts) == 4 and parts[:2] == ['api', 'saves'] and parts[3] == 'context':
                with LOCK, db() as conn:
                    return self.respond(context_preview(conn, parts[2]))
            if path.startswith('/api/saves/'):
                with LOCK, db() as conn:
                    return self.respond(snapshot(conn, path.rsplit('/', 1)[-1]))
            asset = '/index.html' if path == '/' else path
            file = (WEB / asset.lstrip('/')).resolve()
            if not file.is_relative_to(WEB) or not file.is_file():
                return self.send_error(404)
            content = file.read_bytes()
            mime = {'.html':'text/html', '.css':'text/css', '.js':'text/javascript', '.svg':'image/svg+xml'}.get(file.suffix, 'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(content)
        except (ValueError, KeyError) as error:
            self.respond({'error': str(error)}, 400)

    def do_POST(self):
        try:
            payload = self.body()
            path = urlparse(self.path).path
            parts = path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'saves'] and parts[3] == 'images':
                return self.handle_image(parts[2], payload)
            if len(parts) == 6 and parts[:2] == ['api', 'saves'] and parts[3] == 'images' and parts[5] in ('share', 'discard'):
                return self.resolve_image(parts[2], parts[4], parts[5], payload)
            if len(parts) == 4 and parts[:2] == ['api', 'saves'] and parts[3] == 'advance':
                return self.handle_advance(parts[2], payload)
            if len(parts) == 4 and parts[:2] == ['api', 'saves'] and parts[3] == 'ask':
                return self.handle_ask(parts[2], payload)
            if len(parts) == 4 and parts[:2] == ['api', 'saves'] and parts[3] == 'summary-draft':
                return self.handle_summary_draft(parts[2], payload)
            if path == '/api/backups':
                with LOCK:
                    return self.respond(backups.create(DATA), 201)
            if len(parts) == 4 and parts[:2] == ['api', 'backups'] and parts[3] == 'verify':
                with LOCK:
                    return self.respond(backups.inspect(DATA, backups.path_for(DATA, parts[2])))
            if len(parts) == 4 and parts[:2] == ['api', 'backups'] and parts[3] == 'restore':
                return self.handle_restore(parts[2])
            with LOCK, db() as conn:
                if len(parts) == 6 and parts[:2] == ['api', 'saves'] and parts[3] == 'players' and parts[5] == 'portrait':
                    save_id, player_id = parts[2], parts[4]
                    if not conn.execute('SELECT 1 FROM players WHERE id=? AND save_id=?', (player_id, save_id)).fetchone():
                        raise ValueError('Choose a player in this save')
                    if payload.get('remove') is True:
                        conn.execute('DELETE FROM player_portraits WHERE player_id=? AND save_id=?', (player_id, save_id))
                    else:
                        mime, encoded = payload.get('mime'), payload.get('data')
                        if mime not in PORTRAIT_SIGNATURES or not isinstance(encoded, str) or len(encoded) > ((MAX_PORTRAIT_BYTES + 2) // 3) * 4:
                            raise ValueError('Choose a PNG, JPEG, or WebP image up to 5 MB')
                        try:
                            image = base64.b64decode(encoded, validate=True)
                        except (binascii.Error, ValueError) as error:
                            raise ValueError('Portrait image data is invalid') from error
                        if not image or len(image) > MAX_PORTRAIT_BYTES or not PORTRAIT_SIGNATURES[mime](image):
                            raise ValueError('Portrait image data is invalid')
                        conn.execute('''INSERT INTO player_portraits (player_id,save_id,mime,image,updated_at)
                                        VALUES (?,?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET
                                        mime=excluded.mime,image=excluded.image,updated_at=excluded.updated_at''',
                                     (player_id, save_id, mime, image, utc()))
                    conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (utc(), save_id))
                    return self.respond(snapshot(conn, save_id))
                if path == '/api/cartridges':
                    files, raw = unpack_payload(payload)
                    info = inspect_cartridge(files)
                    cartridge_id = hashlib.sha256(raw or b''.join(k.encode()+v for k,v in sorted(files.items()))).hexdigest()
                    conn.execute('INSERT OR IGNORE INTO cartridges (id,title,source,resources,created_at,content_hash) VALUES (?,?,?,?,?,?)',
                                 (cartridge_id, info['title'], payload.get('kind', 'zip'),
                                  json.dumps(info['resources']), utc(), content_fingerprint(files)))
                    conn.execute('UPDATE cartridges SET content_hash=COALESCE(content_hash,?) WHERE id=?',
                                 (content_fingerprint(files), cartridge_id))
                    # Keep authored bytes outside the mutable save database.
                    if raw:
                        directory = DATA / 'cartridges'
                        directory.mkdir(parents=True, exist_ok=True)
                        (directory / (cartridge_id + '.zip')).write_bytes(raw)
                    return self.respond({'id':cartridge_id, **info})
                if len(parts) == 4 and parts[:2] == ['api', 'cartridges'] and parts[3] == 'validate':
                    cartridge = conn.execute('SELECT id FROM cartridges WHERE id=?', (parts[2],)).fetchone()
                    if not cartridge:
                        raise ValueError('Choose a valid cartridge first')
                    files = stored_cartridge_files(parts[2])
                    return self.respond(validate_bindings(files, payload.get('resources')))
                if path == '/api/saves':
                    cartridge = conn.execute('SELECT title,resources FROM cartridges WHERE id=?', (payload.get('cartridgeId'),)).fetchone()
                    if not cartridge:
                        raise ValueError('Choose a valid cartridge first')
                    files = stored_cartridge_files(payload['cartridgeId'])
                    selected = payload.get('resources', json.loads(cartridge['resources']))
                    info = validate_bindings(files, selected)
                    if info['missing']:
                        raise ValueError('Cartridge is missing required files: ' + ', '.join(info['missing']))
                    if info['invalid']:
                        raise ValueError('Invalid cartridge bindings: ' + ', '.join(f'{key}: {message}' for key, message in info['invalid'].items()))
                    roster = payload.get('players') or []
                    if not roster or any(not str(p.get('name', '')).strip() or not str(p.get('character', '')).strip() for p in roster):
                        raise ValueError('Every player needs a name and character')
                    save_id = str(uuid.uuid4())
                    prompt_id = runtime_prompts.store(conn, runtime_prompts.cartridge_snapshot(files, info['resources']))
                    stamp = utc()
                    conn.execute('INSERT INTO saves (id,name,cartridge_id,created_at,updated_at,resource_bindings,adventure_title,narration_prompt_id) VALUES (?,?,?,?,?,?,?,?)',
                                 (save_id, str(payload.get('name') or info['title']).strip(), payload['cartridgeId'], stamp, stamp,
                                   json.dumps(info['resources']), info['title'], prompt_id))
                    for player in roster:
                        conn.execute('INSERT INTO players (id,save_id,name,character) VALUES (?,?,?,?)', (str(uuid.uuid4()), save_id, player['name'].strip(), player['character'].strip()))
                    start_session(conn, save_id)
                    return self.respond(snapshot(conn, save_id), 201)
                if len(parts) == 6 and parts[:2] == ['api', 'saves'] and parts[3] == 'assets' and parts[5] == 'reveal':
                    save_id, asset_id = parts[2], parts[4]
                    state = snapshot(conn, save_id)
                    player = require_player(state, payload.get('playerId'))
                    if payload.get('pilot') is not True:
                        raise ValueError('Enable Pilot Mode to reveal a cartridge asset')
                    assets = {asset['id']: asset for asset in package_assets(stored_cartridge_files(state['cartridge']['id']))}
                    asset = assets.get(asset_id)
                    if not asset:
                        raise ValueError('Choose an image from this cartridge')
                    stamp = utc()
                    changed = conn.execute('INSERT OR IGNORE INTO revealed_assets '
                                           '(save_id,asset_id,path,media_type,revealed_by,revealed_at) VALUES (?,?,?,?,?,?)',
                                           (save_id, asset_id, asset['path'], asset['mediaType'], player['id'], stamp)).rowcount
                    if changed:
                        session = active_session(conn, save_id)
                        conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) '
                                     'VALUES (?,?,?,?,?,?)',
                                     (save_id, session['id'], player['id'], 'asset_revealed',
                                      json.dumps({'assetId': asset_id, 'path': asset['path']}), stamp))
                        conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (stamp, save_id))
                    return self.respond({'revealed': True, 'assetId': asset_id})
                if len(parts) != 4 or parts[:2] != ['api', 'saves']:
                    return self.send_error(404)
                save_id, action = parts[2:]
                if action == 'typing':
                    player_id = payload.get('playerId')
                    if not conn.execute('SELECT 1 FROM players WHERE id=? AND save_id=?', (player_id, save_id)).fetchone():
                        raise ValueError('Choose a player in this save')
                    typing = TYPING.setdefault(save_id, {})
                    if payload.get('typing'):
                        typing[player_id] = time.monotonic() + TYPING_SECONDS
                    else:
                        typing.pop(player_id, None)
                    return self.respond(activity(save_id))
                state = snapshot(conn, save_id)
                request_id = None
                if action == 'messages' and payload.get('requestId') is not None:
                    try:
                        request_id = str(uuid.UUID(str(payload['requestId'])))
                    except ValueError as error:
                        raise ValueError('A valid message request ID is required') from error
                    sent = conn.execute('SELECT player_id,body FROM messages WHERE save_id=? AND request_id=?',
                                        (save_id, request_id)).fetchone()
                    if sent:
                        # A retry of a send that already landed: report the table as it is now.
                        if sent['player_id'] != payload.get('playerId') or sent['body'] != str(payload.get('text', '')).strip():
                            raise ValueError('This message request was already used for a different message')
                        return self.respond(snapshot(conn, save_id))
                if action == 'notes':
                    save_note(conn, state, payload)
                    return self.respond(snapshot(conn, save_id))
                if save_id in GENERATING:
                    raise ValueError('The AI-DM is already responding')
                if action == 'locate-cartridge':
                    cartridge = conn.execute('SELECT content_hash FROM cartridges WHERE id=?', (state['cartridge']['id'],)).fetchone()
                    files, raw = unpack_payload(payload)
                    expected = cartridge['content_hash']
                    if expected and content_fingerprint(files) != expected:
                        raise ValueError('This package does not match the save cartridge')
                    if not expected and hashlib.sha256(raw).hexdigest() != state['cartridge']['id']:
                        raise ValueError('This older save requires its original cartridge package')
                    validation = validate_bindings(files, state['cartridge']['resources'], require_manifest=False)
                    if any(role in validation['missing'] for role in REQUIRED) or validation['invalid']:
                        raise ValueError('The package cannot satisfy the saved resource bindings')
                    directory = DATA / 'cartridges'
                    directory.mkdir(parents=True, exist_ok=True)
                    target = directory / (state['cartridge']['id'] + '.zip')
                    temporary = directory / (state['cartridge']['id'] + '.' + uuid.uuid4().hex + '.tmp')
                    try:
                        temporary.write_bytes(raw)
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                    return self.respond(snapshot(conn, save_id))
                if action == 'start-session':
                    if not state['cartridge']['available']:
                        raise ValueError('Locate the cartridge before continuing')
                    require_player(state, payload.get('playerId'))
                    start_session(conn, save_id)
                    return self.respond(snapshot(conn, save_id))
                session = active_session(conn, save_id)
                if not session:
                    raise ValueError('Start the next session before playing')
                if action == 'narration-prompt':
                    upgrade_narration_prompt(conn, state, session, payload)
                    return self.respond(snapshot(conn, save_id))
                if action == 'end-session':
                    require_player(state, payload.get('playerId'))
                    note = str(payload.get('note') or '').strip()
                    if len(note) > 10000:
                        raise ValueError('Session note must be 10,000 characters or less')
                    last_message = conn.execute('SELECT MAX(id) FROM messages WHERE save_id=?', (save_id,)).fetchone()[0]
                    ready = {player['id']: bool(player['ready']) for player in state['players']}
                    stamp = utc()
                    conn.execute('INSERT INTO checkpoints (save_id,session_id,beat,mode,last_message_id,ready,note,created_at) VALUES (?,?,?,?,?,?,?,?)',
                                 (save_id, session['id'], state['save']['beat'], state['save']['mode'],
                                  last_message, json.dumps(ready), note, stamp))
                    conn.execute('UPDATE sessions SET ended_at=?,ended_by=? WHERE id=?',
                                 (stamp, payload['playerId'], session['id']))
                    conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (stamp, save_id))
                    return self.respond(snapshot(conn, save_id))
                if action == 'location':
                    player = require_player(state, payload.get('playerId'))
                    location = payload.get('location')
                    if location is not None and type(location) is not int:
                        raise ValueError('Choose a location from the list')
                    if not state['cartridge']['available']:
                        raise ValueError('Locate the cartridge before changing location')
                    adventure = adventure_for(state)
                    if not adventure.focused or not adventure.valid(location):
                        raise ValueError('Choose a location from the list')
                    set_location(conn, state, location, player['id'], 'pilot')
                    return self.respond(snapshot(conn, save_id))
                if action == 'summaries':
                    save_summary(conn, save_id, payload)
                    return self.respond(snapshot(conn, save_id))
                if action == 'combat-outcome':
                    if state['save']['mode'] != 'combat':
                        raise ValueError('The table is not in Combat Mode')
                    require_player(state, payload.get('playerId'))
                    outcome = str(payload.get('text') or '').strip()
                    if not outcome or len(outcome) > 20000:
                        raise ValueError('Combat outcome must contain 1 to 20,000 characters')
                    conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) VALUES (?,?,?,?,?,?)',
                                 (save_id, session['id'], payload['playerId'], 'combat_outcome', outcome, utc()))
                    conn.execute("UPDATE saves SET mode='normal',updated_at=? WHERE id=?", (utc(), save_id))
                    conn.execute('UPDATE players SET ready=0 WHERE save_id=?', (save_id,))
                    return self.respond(snapshot(conn, save_id))
                if action == 'messages':
                    player = require_player(state, payload.get('playerId'))
                    body = str(payload.get('text', '')).strip()
                    if not body or len(body) > 20000:
                        raise ValueError('Message must contain 1 to 20,000 characters')
                    # Drafts carry the beat they were started in so they never slip into a later one.
                    if payload.get('beat') is not None and int(payload['beat']) != state['save']['beat']:
                        raise StaleBeat(state['save']['beat'])
                    conn.execute('INSERT INTO messages (save_id,session_id,player_id,kind,name,body,created_at,request_id) VALUES (?,?,?,?,?,?,?,?)',
                                 (save_id, session['id'], player['id'], 'player', player['character'], body, utc(), request_id))
                    conn.execute('UPDATE players SET ready=1 WHERE id=?', (player['id'],))
                    TYPING.get(save_id, {}).pop(player['id'], None)
                elif action == 'ready':
                    player = require_player(state, payload.get('playerId'))
                    conn.execute('UPDATE players SET ready=? WHERE id=?', (int(bool(payload.get('ready'))), player['id']))
                elif action == 'mode':
                    mode = payload.get('mode')
                    if mode != 'combat' or state['save']['mode'] != 'normal':
                        raise ValueError('Record a combat outcome to resume normal play')
                    player_id = payload.get('playerId')
                    if player_id is not None:
                        require_player(state, player_id)
                    conn.execute("UPDATE saves SET mode='combat' WHERE id=?", (save_id,))
                    conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) VALUES (?,?,?,?,?,?)',
                                 (save_id, session['id'], player_id, 'combat_started', '', utc()))
                else:
                    return self.send_error(404)
                conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (utc(), save_id))
                return self.respond(snapshot(conn, save_id))
        except StaleBeat as error:
            self.respond({'error': str(error), 'code': 'stale_beat', 'beat': error.beat}, 409)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile, UnicodeDecodeError) as error:
            self.respond({'error': str(error)}, 400)
        except (OSError, sqlite3.Error) as error:
            if urlparse(self.path).path.startswith('/api/backups'):
                return self.respond({'error': f'Backup storage failed: {error}'}, 500)
            raise

    def get_images(self, parts):
        save_id = parts[2]
        with LOCK, db() as conn:
            if len(parts) == 4:
                player_id = parse_qs(urlparse(self.path).query).get('playerId', [None])[0]
                require_player(snapshot(conn, save_id), player_id)
                return self.respond({'images': scene_images.list_images(conn, save_id),
                                     'settings': scene_images.settings()})
            row = conn.execute('SELECT status,image FROM scene_images WHERE save_id=? AND id=?',
                               (save_id, parts[4])).fetchone()
            if not row or row['status'] not in ('draft', 'shared') or not row['image']:
                return self.send_error(404)
            if row['status'] == 'draft':
                player_id = parse_qs(urlparse(self.path).query).get('playerId', [None])[0]
                require_player(snapshot(conn, save_id), player_id)
            content = row['image']
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(content)

    def get_assets(self, parts):
        save_id = parts[2]
        query = parse_qs(urlparse(self.path).query)
        player_id = query.get('playerId', [None])[0]
        pilot = query.get('pilot', ['false'])[0] == 'true'
        with LOCK, db() as conn:
            state = snapshot(conn, save_id)
            require_player(state, player_id)
            files = stored_cartridge_files(state['cartridge']['id'])
            assets = package_assets(files)
            revealed = {row['asset_id'] for row in conn.execute(
                'SELECT asset_id FROM revealed_assets WHERE save_id=?', (save_id,))}
            if len(parts) == 4:
                visible = assets if pilot else [asset for asset in assets if asset['id'] in revealed]
                return self.respond({'assets': [{**asset, 'revealed': asset['id'] in revealed,
                    'url': f'/api/saves/{save_id}/assets/{asset["id"]}?playerId={quote(player_id)}'
                           + ('&pilot=true' if pilot else '')} for asset in visible]})
            asset = next((item for item in assets if item['id'] == parts[4]), None)
            if not asset or (not pilot and asset['id'] not in revealed):
                return self.send_error(404)
            image = files[asset['path']]
            media_type = asset['mediaType']
        self.send_response(200)
        self.send_header('Content-Type', media_type)
        self.send_header('Content-Length', str(len(image)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(image)

    def handle_image(self, save_id, payload):
        with LOCK, db() as conn:
            state = snapshot(conn, save_id)
            player = require_player(state, payload.get('playerId'))
            if payload.get('pilot') is not True:
                raise ValueError('Enable Pilot Mode to illustrate a scene.')
            try:
                image_id = str(uuid.UUID(payload.get('requestId', '')))
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError('A valid image request ID is required.') from error
            existing = conn.execute('SELECT save_id,player_id FROM scene_images WHERE id=?', (image_id,)).fetchone()
            if existing:
                if existing['save_id'] != save_id or existing['player_id'] != player['id']:
                    raise ValueError('This image request belongs to another player or save.')
                return self.respond({'images': scene_images.list_images(conn, save_id)})
            session = active_session(conn, save_id)
            if not session:
                raise ValueError('Start the next session before illustrating a scene.')
            settings = scene_images.settings()
            if not settings['enabled']:
                raise ValueError('Configure TABLEFORGE_OPENAI_API_KEY on the server to illustrate scenes.')
            if conn.execute("SELECT 1 FROM scene_images WHERE save_id=? AND status='generating'", (save_id,)).fetchone():
                raise ValueError('A scene image is already generating for this table.')
            source = next((m for m in state['messages'] if m['id'] == payload.get('sourceMessageId') and m['kind'] == 'ai'), None)
            if not source:
                raise ValueError('Choose an AI-DM narration from this save.')
            direction = payload.get('direction', '')
            if not isinstance(direction, str) or len(direction) > 2000:
                raise ValueError('Visual direction must be at most 2,000 characters.')
            if len(source['body']) > 60000:
                raise ValueError('This narration is too long to illustrate in one request.')
            prompt = scene_images.prompt_for(source['body'], direction.strip())
            conn.execute('''INSERT INTO scene_images
                (id,save_id,session_id,player_id,source_message_id,direction,prompt,model,quality,size,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (image_id, save_id, session['id'], player['id'], source['id'], direction.strip(), prompt,
                 settings['model'], settings['quality'], settings['size'], 'generating', utc()))
        # Keep the request outside the database lock and the AI-DM generation lock.
        try:
            generated = scene_images.generate(prompt, settings['model'])
            with LOCK, db() as conn:
                conn.execute("""UPDATE scene_images SET status='draft',image=?,model=?,usage=?,estimated_cost_usd=?,completed_at=?
                                WHERE id=?""", (generated.data, generated.model, json.dumps(generated.usage),
                                metering.image_cost(generated.model, generated.usage), utc(), image_id))
                conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (utc(), save_id))
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else 'The image could not be saved or generated. Check provider usage before retrying.'
            with LOCK, db() as conn:
                conn.execute("UPDATE scene_images SET status='failed',error=? WHERE id=?", (message, image_id))
                conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (utc(), save_id))
            raise ValueError(message) from error
        with LOCK, db() as conn:
            result = {'images': scene_images.list_images(conn, save_id)}
        return self.respond(result)

    def resolve_image(self, save_id, image_id, action, payload):
        with LOCK, db() as conn:
            state = snapshot(conn, save_id)
            player = require_player(state, payload.get('playerId'))
            if payload.get('pilot') is not True:
                raise ValueError('Enable Pilot Mode to review scene images.')
            row = conn.execute('SELECT * FROM scene_images WHERE save_id=? AND id=?', (save_id, image_id)).fetchone()
            if not row:
                raise ValueError('Scene image not found.')
            target = 'shared' if action == 'share' else 'discarded'
            if row['status'] == target:
                return self.respond({'images': scene_images.list_images(conn, save_id)})
            if row['status'] != 'draft' and not (action == 'discard' and row['status'] == 'failed'):
                raise ValueError('This scene image is no longer awaiting review.')
            stamp = utc()
            if action == 'share':
                session = active_session(conn, save_id)
                if not session:
                    raise ValueError('Start the next session before sharing an image.')
                conn.execute('''INSERT INTO messages (save_id,session_id,player_id,kind,name,body,created_at,image_id)
                                VALUES (?,?,?,?,?,?,?,?)''',
                             (save_id, session['id'], player['id'], 'image', player['character'],
                              'Scene illustration · Inspired by an AI-DM narration. Illustrative, not authoritative.', stamp, image_id))
                conn.execute("UPDATE scene_images SET status='shared',shared_at=?,shared_by=?,resolved_by=? WHERE id=?",
                             (stamp, player['id'], player['id'], image_id))
            else:
                conn.execute("UPDATE scene_images SET status='discarded',image=NULL,resolved_by=? WHERE id=?", (player['id'], image_id))
            conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (stamp, save_id))
            result = {'images': scene_images.list_images(conn, save_id)}
        return self.respond(result)

    def run_generation(self, save_id, begin, publish, payload):
        with LOCK, db() as conn:
            context = begin(conn, save_id, payload)
        try:
            generated = ai.current_provider().generate(context)
            text = str(generated or '').strip()
            if not text:
                raise ValueError('The AI-DM returned an empty response')
        except Exception as error:
            with LOCK:
                GENERATING.pop(save_id, None)
            if isinstance(error, ValueError):
                raise
            raise ValueError(f'AI-DM request failed: {error}') from error
        with LOCK:
            try:
                with db() as conn:
                    if isinstance(generated, ai.GeneratedText):
                        session = active_session(conn, save_id)
                        if not session:
                            raise ValueError('Start the next session before playing')
                        values = metering.record(generated.model or 'unknown', generated.usage,
                                                 generated.service_tier)
                        conn.execute('''INSERT INTO ai_usage
                            (save_id,session_id,purpose,model,input_tokens,cached_tokens,cache_write_tokens,
                             output_tokens,total_tokens,estimated_cost_usd,service_tier,created_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (save_id, session['id'], context['purpose'], *values, utc()))
                    result = publish(conn, save_id, text)
            finally:
                GENERATING.pop(save_id, None)
            result['activity'] = activity(save_id)
        return self.respond(result)

    def handle_restore(self, name):
        with LOCK:
            if GENERATING:
                raise ValueError('Wait for the AI-DM to finish before restoring a backup')
            with db() as conn:
                if conn.execute("SELECT 1 FROM scene_images WHERE status='generating'").fetchone():
                    raise ValueError('Wait for the scene illustration to finish before restoring a backup')
            result = backups.restore(DATA, name)
            TYPING.clear()
            # Bring an older backup's schema up to date, then prove the live database matches it.
            initialize()
            live = backups.inspect(DATA, DATA / backups.DATABASE)
            if live['counts'] != result['expected']['counts']:
                raise ValueError('The restored database does not match the backup. '
                                 f'Your previous data is kept in {result["safetyBackup"]}.')
        return self.respond({**result, 'live': live})

    def handle_advance(self, save_id, payload):
        override = {}

        def begin(conn, save_id, payload):
            context = begin_advance(conn, save_id, payload)
            override.update(context.pop('override', {}))
            return context

        def publish(conn, save_id, text):
            return publish_advance(conn, save_id, text, override or None)

        return self.run_generation(save_id, begin, publish, payload)

    def handle_ask(self, save_id, payload):
        return self.run_generation(save_id, begin_ask, publish_ask, payload)

    def handle_summary_draft(self, save_id, payload):
        # Drafts are returned for Pilot review; nothing is saved until they choose to keep it.
        drafted = {}

        def begin(conn, save_id, payload):
            drafted.update(begin_summary(conn, save_id, payload))
            return drafted

        def publish(conn, save_id, text):
            return {'draft': text, 'basedOn': drafted['basedOn'], 'messageCount': len(drafted['messages']),
                    'fromMessageId': drafted['fromMessageId'], 'throughMessageId': drafted['throughMessageId']}

        return self.run_generation(save_id, begin, publish, payload)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    initialize()
    print(f'TableForge: http://{args.host}:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
