"""Durable human-combat handoffs; no combat mechanics or provider dependencies."""
import re
import uuid

MARKER = '[[TABLEFORGE_COMBAT:START]]'
INSTRUCTIONS = '''\n\nTableForge combat runtime contract (takes precedence for handoff behavior):
When you call initiative and hand combat to humans, stop narration and append
[[TABLEFORGE_COMBAT:START]] as the exact final line, after any other metadata.
This is server metadata, never a quoted example, code block, or player choice.
Do not emit action choices on a combat handoff. Do not emit this marker for a
rules discussion or merely mentioning initiative. Humans run the fight.
'''


def extract(text):
    lines = text.rstrip().splitlines()
    if not lines or lines[-1] != MARKER:
        return text, False
    # A marker inside a quoted/code example must never operate the runtime.
    fenced = False
    fence = None
    for line in lines[:-1]:
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            token = match[1][0]
            if not fenced:
                fenced, fence = True, token
            elif token == fence:
                fenced, fence = False, None
    if fenced:
        return text, False
    return '\n'.join(lines[:-1]).rstrip(), True


def initialize(conn, stamp):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS combat_handoffs (
            id TEXT PRIMARY KEY, save_id TEXT NOT NULL REFERENCES saves(id),
            session_id TEXT NOT NULL REFERENCES sessions(id),
            phase TEXT NOT NULL, outcome TEXT, skipped INTEGER NOT NULL DEFAULT 0,
            player_id TEXT, request_id TEXT, override INTEGER NOT NULL DEFAULT 0,
            message_id INTEGER, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS combat_save ON combat_handoffs(save_id,created_at);
    ''')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(combat_handoffs)')}
    for name, spec in {'reporter_id': 'TEXT', 'editor_token': 'TEXT',
                       'draft': "TEXT NOT NULL DEFAULT ''", 'revision': 'INTEGER NOT NULL DEFAULT 0'}.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE combat_handoffs ADD COLUMN {name} {spec}')
    conn.execute("UPDATE combat_handoffs SET phase='fighting' WHERE phase='outcome_pending'")
    # initialize is called at startup or after a guarded restore, never mid-request.
    recovering = [row['save_id'] for row in conn.execute("SELECT save_id FROM combat_handoffs WHERE phase='resuming'")]
    conn.execute("UPDATE combat_handoffs SET phase='failed' WHERE phase='resuming'")
    for save_id in recovering:
        conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (stamp, save_id))
    for save in conn.execute("SELECT id FROM saves WHERE mode='combat'").fetchall():
        if current(conn, save['id']):
            continue
        session = conn.execute('SELECT id FROM sessions WHERE save_id=? ORDER BY number DESC LIMIT 1',
                               (save['id'],)).fetchone()
        if session:
            conn.execute('INSERT INTO combat_handoffs (id,save_id,session_id,phase,created_at) VALUES (?,?,?,?,?)',
                         (str(uuid.uuid4()), save['id'], session['id'], 'fighting', stamp))
            conn.execute('UPDATE players SET ready=0 WHERE save_id=?', (save['id'],))


def current(conn, save_id):
    row = conn.execute('SELECT * FROM combat_handoffs WHERE save_id=? ORDER BY rowid DESC LIMIT 1',
                       (save_id,)).fetchone()
    return dict(row) if row else None


def pending(handoff):
    return bool(handoff and handoff['phase'] != 'complete')


def sync_ready(conn, save_id):
    # Ready is only for ordinary play. Reporting is explicitly claimed.
    return


def require_editor(handoff, payload):
    if (handoff['phase'] != 'reporting' or handoff['reporter_id'] != payload.get('playerId')
            or not payload.get('editorToken') or handoff['editor_token'] != payload['editorToken']):
        raise ValueError('Outcome ownership changed; reopen or take over the saved draft')
    if payload.get('revision') != handoff['revision']:
        raise ValueError('Outcome draft changed; reopen the saved draft before editing')


def edit(conn, save_id, payload):
    handoff = current(conn, save_id)
    if not handoff or handoff['id'] != payload.get('handoffId'):
        raise ValueError('This combat handoff is no longer current')
    action = payload.get('action')
    if action in ('claim', 'takeover'):
        if handoff['phase'] not in ('fighting', 'reporting'):
            raise ValueError('The combat outcome has already been submitted')
        if action == 'claim' and handoff['phase'] == 'reporting':
            raise ValueError('Someone is already recording the combat outcome')
        if payload.get('revision') != handoff['revision']:
            raise ValueError('Outcome ownership changed; refresh before taking over')
        token = str(payload.get('editorToken') or '')
        if not token or len(token) > 100:
            raise ValueError('An editor token is required')
        conn.execute("UPDATE combat_handoffs SET phase='reporting',reporter_id=?,editor_token=?,revision=revision+1 WHERE id=?",
                     (payload['playerId'], token, handoff['id']))
    elif action in ('draft', 'return'):
        require_editor(handoff, payload)
        text = str(payload.get('text') or '')
        if len(text) > 20000:
            raise ValueError('Combat outcome must be at most 20,000 characters')
        conn.execute('UPDATE combat_handoffs SET draft=?,revision=revision+1 WHERE id=?', (text, handoff['id']))
        if action == 'return':
            conn.execute("UPDATE combat_handoffs SET phase='fighting',reporter_id=NULL,editor_token=NULL WHERE id=?", (handoff['id'],))
    else:
        raise ValueError('Unknown combat reporting action')


def start(conn, save_id, session_id, player_id, stamp):
    handoff = current(conn, save_id)
    if pending(handoff):
        raise ValueError('Finish the current combat handoff first')
    conn.execute('INSERT INTO combat_handoffs (id,save_id,session_id,phase,created_at) VALUES (?,?,?,?,?)',
                 (str(uuid.uuid4()), save_id, session_id, 'fighting', stamp))
    conn.execute("UPDATE saves SET mode='combat',updated_at=? WHERE id=?", (stamp, save_id))
    conn.execute('UPDATE players SET ready=0 WHERE save_id=?', (save_id,))
    conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) VALUES (?,?,?,?,?,?)',
                 (save_id, session_id, player_id, 'combat_started', '', stamp))
