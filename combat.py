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
    handoff = current(conn, save_id)
    if not handoff or handoff['phase'] not in ('fighting', 'outcome_pending'):
        return
    players = conn.execute('SELECT ready FROM players WHERE save_id=?', (save_id,)).fetchall()
    phase = 'outcome_pending' if players and all(p['ready'] for p in players) else 'fighting'
    conn.execute('UPDATE combat_handoffs SET phase=? WHERE id=?', (phase, handoff['id']))


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
