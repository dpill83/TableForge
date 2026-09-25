"""Local TableForge server. Start with: python3 server.py"""
import argparse
import base64
import hashlib
import io
import json
import os
import sqlite3
import threading
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import ai

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = Path(os.environ.get("TABLEFORGE_DATA", ROOT / "data"))
LOCK = threading.RLock()
GENERATING = set()
MAX_REQUEST = 32 * 1024 * 1024
REQUIRED = ("module.md", "run-data.json")
OPTIONAL = ("cast.json", "cast.md", "continuity.json", "scenes.json", "music-cues.json", "map-art-brief.md")
RESOURCE_KEYS = {
    'module.md': 'module', 'run-data.json': 'runData',
    'cast.json': 'cast', 'cast.md': 'castMarkdown',
    'continuity.json': 'continuity', 'scenes.json': 'scenes',
    'music-cues.json': 'musicCues', 'map-art-brief.md': 'mapArtBrief',
}


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
        """)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(saves)')}
        if 'resource_bindings' not in columns:
            conn.execute('ALTER TABLE saves ADD COLUMN resource_bindings TEXT')
        if 'adventure_title' not in columns:
            conn.execute('ALTER TABLE saves ADD COLUMN adventure_title TEXT')
        if 'format_version' not in columns:
            conn.execute('ALTER TABLE saves ADD COLUMN format_version INTEGER NOT NULL DEFAULT 1')
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(messages)')}
        if 'session_id' not in columns:
            conn.execute('ALTER TABLE messages ADD COLUMN session_id TEXT')
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


def validate_bindings(files, resources):
    if not isinstance(resources, dict) or any(key not in RESOURCE_KEYS for key in resources):
        raise ValueError('Invalid resource bindings')
    bindings = {}
    missing = []
    invalid = {}
    for role in REQUIRED + OPTIONAL:
        path = resources.get(role)
        if path == '':
            path = None
        if path is not None and not isinstance(path, str):
            raise ValueError(f'Invalid binding for {role}')
        bindings[role] = path
        if path is None:
            if role in REQUIRED:
                missing.append(role)
        elif path not in files:
            invalid[role] = 'File is not in the cartridge'
    run_data = None
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
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            invalid['run-data.json'] = 'Run data must contain a UTF-8 JSON object'
    manifest, _ = package_manifest(files)
    title = str(manifest.get('title') or '').strip()
    if not title and run_data:
        title = str(run_data.get('title') or run_data.get('adventureTitle') or '').strip()
    return {'title': title or 'Untitled Adventure', 'resources': bindings,
            'missing': missing, 'invalid': invalid}


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
    return {
        'save': dict(save),
        'cartridge': {'id': cartridge['id'], 'title': save['adventure_title'] or cartridge['title'],
                      'resources': resources, 'available': (DATA / 'cartridges' / (cartridge['id'] + '.zip')).is_file()},
        'players': [dict(row) for row in conn.execute('SELECT * FROM players WHERE save_id=? ORDER BY rowid', (save_id,))],
        'messages': [dict(row) for row in conn.execute('SELECT * FROM messages WHERE save_id=? ORDER BY id', (save_id,))],
        'pilot': [dict(row) for row in conn.execute('SELECT * FROM pilot_messages WHERE save_id=? ORDER BY id', (save_id,))],
        'sessions': sessions,
        'events': [dict(row) for row in conn.execute('SELECT * FROM session_events WHERE save_id=? ORDER BY id', (save_id,))],
        'checkpoint': checkpoint,
    }


def begin_advance(conn, save_id, payload):
    state = snapshot(conn, save_id)
    if not state['cartridge']['available']:
        raise ValueError('Locate the cartridge before advancing')
    if not active_session(conn, save_id):
        raise ValueError('Start the next session before advancing')
    if state['save']['mode'] != 'normal':
        raise ValueError('Resume combat explicitly')
    if not payload.get('override') and not all(p['ready'] for p in state['players']):
        raise ValueError('Waiting for all players to be Ready')
    beat = state['save']['beat']
    if payload.get('beat') is not None and int(payload['beat']) != beat:
        raise ValueError('This beat has already advanced')
    if save_id in GENERATING:
        raise ValueError('The AI-DM is already responding')
    context = ai.build_context(state, DATA)
    GENERATING.add(save_id)
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
    GENERATING.add(save_id)
    return context


def publish_advance(conn, save_id, text):
    session = active_session(conn, save_id)
    conn.execute(
        'INSERT INTO messages (save_id,session_id,kind,name,body,created_at) VALUES (?,?,?,?,?,?)',
        (save_id, session['id'], 'ai', 'AI-DM', text, utc()),
    )
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
            if path == '/api/runtime':
                return self.respond(ai.runtime_status())
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
            if len(parts) == 4 and parts[:2] == ['api', 'saves'] and parts[3] == 'advance':
                return self.handle_advance(parts[2], payload)
            if len(parts) == 4 and parts[:2] == ['api', 'saves'] and parts[3] == 'ask':
                return self.handle_ask(parts[2], payload)
            with LOCK, db() as conn:
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
                    stamp = utc()
                    conn.execute('INSERT INTO saves (id,name,cartridge_id,created_at,updated_at,resource_bindings,adventure_title) VALUES (?,?,?,?,?,?,?)',
                                 (save_id, str(payload.get('name') or info['title']).strip(), payload['cartridgeId'], stamp, stamp,
                                  json.dumps(info['resources']), info['title']))
                    for player in roster:
                        conn.execute('INSERT INTO players (id,save_id,name,character) VALUES (?,?,?,?)', (str(uuid.uuid4()), save_id, player['name'].strip(), player['character'].strip()))
                    start_session(conn, save_id)
                    return self.respond(snapshot(conn, save_id), 201)
                if len(parts) != 4 or parts[:2] != ['api', 'saves']:
                    return self.send_error(404)
                save_id, action = parts[2:]
                state = snapshot(conn, save_id)
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
                    validation = validate_bindings(files, state['cartridge']['resources'])
                    if validation['missing'] or validation['invalid']:
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
                    conn.execute('INSERT INTO messages (save_id,session_id,player_id,kind,name,body,created_at) VALUES (?,?,?,?,?,?,?)',
                                 (save_id, session['id'], player['id'], 'player', player['character'], body, utc()))
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
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile, UnicodeDecodeError) as error:
            self.respond({'error': str(error)}, 400)

    def run_generation(self, save_id, begin, publish, payload):
        with LOCK, db() as conn:
            context = begin(conn, save_id, payload)
        try:
            text = str(ai.current_provider().generate(context) or '').strip()
            if not text:
                raise ValueError('The AI-DM returned an empty response')
        except Exception as error:
            with LOCK:
                GENERATING.discard(save_id)
            if isinstance(error, ValueError):
                raise
            raise ValueError(f'AI-DM request failed: {error}') from error
        with LOCK, db() as conn:
            try:
                return self.respond(publish(conn, save_id, text))
            finally:
                GENERATING.discard(save_id)

    def handle_advance(self, save_id, payload):
        return self.run_generation(save_id, begin_advance, publish_advance, payload)

    def handle_ask(self, save_id, payload):
        return self.run_generation(save_id, begin_ask, publish_ask, payload)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    initialize()
    print(f'TableForge: http://{args.host}:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
