"""Facts ledger: durable table facts the AI-DM must keep consistent.

Facts come only from shared table play. Automatic summaries may add a fact,
update one with a reason, or resolve one with a reason. They never delete or
silently reword a fact, and never touch one a Pilot has edited. Every change is
kept in fact_changes so the ledger's history stays append-oriented.
"""
import json
import re

CATEGORIES = {
    'location': 'Where everyone is',
    'promise': 'Open promises and bargains',
    'item': 'Important items',
    'condition': 'Conditions',
    'hook': 'Unresolved hooks',
}
BODY_LIMIT = 500
REASON_LIMIT = 300
OPEN_LIMIT = 80
OPS_LIMIT = 40
BLOCK = re.compile(r'```tableforge-facts[ \t]*\r?\n(.*?)```', re.S)

INSTRUCTIONS = (
    'You also maintain the facts ledger: short facts the AI-DM must keep consistent. '
    'Categories: location (where each character currently is), promise (offers, bargains and '
    'promises still open, and who has not answered), item (where important items are, or their '
    'condition), condition (lasting effects on a character, in plain words, never hit points), '
    'hook (unresolved leads and threats). Record only what happened in shared play. OOC questions '
    'are hypothetical and are never facts. Keep each fact to one sentence.\n'
    'After the summary, end with exactly one fenced block:\n'
    '```tableforge-facts\n'
    '{"add":[{"category":"location","text":"..."}],'
    '"update":[{"id":1,"text":"...","reason":"..."}],'
    '"resolve":[{"id":2,"reason":"..."}]}\n'
    '```\n'
    'Add new facts. Update a fact only when play changed it, and say why. Resolve a fact when it no '
    'longer applies, and say why. Never repeat an existing fact as new. Facts marked locked were set '
    'by a Pilot: do not update or resolve them. Use empty lists when nothing changed.'
)


def initialize(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL REFERENCES saves(id),
            category TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
            locked INTEGER NOT NULL DEFAULT 0, reason TEXT,
            created_by TEXT, created_at TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1, mutation_id TEXT
        );
        CREATE INDEX IF NOT EXISTS facts_save ON facts(save_id, status);
        CREATE TABLE IF NOT EXISTS fact_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL REFERENCES saves(id),
            fact_id INTEGER NOT NULL REFERENCES facts(id), action TEXT NOT NULL,
            category TEXT NOT NULL, body TEXT NOT NULL, reason TEXT,
            player_id TEXT, summary_id INTEGER, created_at TEXT NOT NULL
        );
    ''')


def visible(conn, save_id):
    """Open and resolved facts; removed facts stay in the save but leave every view."""
    return [dict(row) for row in conn.execute(
        "SELECT id,category,body,status,locked,reason,created_by,created_at,updated_by,updated_at,revision "
        "FROM facts WHERE save_id=? AND status!='removed' ORDER BY id", (save_id,))]


def open_facts(facts):
    return [f for f in facts or [] if f['status'] == 'open']


def log(conn, fact, action, reason, player_id, summary_id, stamp):
    conn.execute('INSERT INTO fact_changes (save_id,fact_id,action,category,body,reason,player_id,summary_id,created_at) '
                 'VALUES (?,?,?,?,?,?,?,?,?)', (fact['save_id'], fact['id'], action, fact['category'],
                                                fact['body'], reason, player_id, summary_id, stamp))


def clean(text, limit):
    text = ' '.join(str(text or '').split())
    return text if 0 < len(text) <= limit else None


class FactConflict(ValueError):
    pass


def pilot_change(conn, save_id, player_id, payload, stamp):
    """Pilot add/edit/resolve/reopen/remove. Any Pilot change locks the fact from summaries."""
    action = payload.get('action')
    mutation = payload.get('mutationId')
    if not isinstance(mutation, str) or not 1 <= len(mutation) <= 100:
        raise ValueError('Fact changes require a mutationId for safe retries')
    if conn.execute('SELECT 1 FROM facts WHERE save_id=? AND mutation_id=?', (save_id, mutation)).fetchone():
        return  # A retry of a change that already landed.
    if action == 'add':
        category, body = payload.get('category'), clean(payload.get('body'), BODY_LIMIT)
        if category not in CATEGORIES:
            raise ValueError('Choose a fact category')
        if not body:
            raise ValueError(f'A fact must contain 1 to {BODY_LIMIT} characters')
        fact_id = conn.execute('INSERT INTO facts (save_id,category,body,locked,created_by,created_at,updated_by,updated_at,mutation_id) '
                               'VALUES (?,?,?,1,?,?,?,?,?)', (save_id, category, body, player_id, stamp,
                                                             player_id, stamp, mutation)).lastrowid
        log(conn, row(conn, save_id, fact_id), 'add', None, player_id, None, stamp)
        return
    fact = row(conn, save_id, payload.get('id'))
    if not fact or fact['status'] == 'removed':
        raise FactConflict('This fact no longer exists')
    if type(payload.get('revision')) is not int or payload['revision'] != fact['revision']:
        raise FactConflict('This fact changed since you opened it. Review the latest version.')
    if action == 'edit':
        category = payload.get('category', fact['category'])
        body = clean(payload.get('body'), BODY_LIMIT)
        if category not in CATEGORIES:
            raise ValueError('Choose a fact category')
        if not body:
            raise ValueError(f'A fact must contain 1 to {BODY_LIMIT} characters')
        changes = {'category': category, 'body': body, 'reason': 'Edited by a Pilot'}
    elif action == 'resolve':
        changes = {'status': 'resolved', 'reason': 'Resolved by a Pilot'}
    elif action == 'reopen':
        changes = {'status': 'open', 'reason': 'Reopened by a Pilot'}
    elif action == 'remove':
        changes = {'status': 'removed', 'reason': 'Removed by a Pilot'}
    else:
        raise ValueError('Unknown fact change')
    update(conn, fact, changes, player_id, stamp, mutation, locked=True)
    log(conn, row(conn, save_id, fact['id']), action, None, player_id, None, stamp)


def row(conn, save_id, fact_id):
    if type(fact_id) is not int:
        return None
    found = conn.execute('SELECT * FROM facts WHERE id=? AND save_id=?', (fact_id, save_id)).fetchone()
    return dict(found) if found else None


def update(conn, fact, changes, player_id, stamp, mutation=None, locked=False):
    values = {**changes, 'updated_by': player_id, 'updated_at': stamp, 'mutation_id': mutation}
    if locked:
        values['locked'] = 1
    columns = ','.join(f'{name}=?' for name in values)
    conn.execute(f'UPDATE facts SET {columns},revision=revision+1 WHERE id=?', (*values.values(), fact['id']))


def summary_input(facts):
    """Open facts as the summarizer sees them, with ids for updates."""
    lines = [f"- [{f['id']}] ({f['category']}{', locked' if f['locked'] else ''}) {f['body']}"
             for f in open_facts(facts)]
    return '\n'.join(lines) or '(no facts yet)'


def extract(text):
    """Split summary text from its facts block. Returns (summary, operations or None)."""
    text = str(text or '')
    match = BLOCK.search(text)
    if not match:
        return text.strip(), None
    summary = (text[:match.start()] + text[match.end():]).strip()
    try:
        operations = json.loads(match.group(1))
    except ValueError:
        return summary, None
    return summary, operations if isinstance(operations, dict) else None


def apply_summary(conn, save_id, operations, summary_id, stamp):
    """Apply a summary's proposed changes within its rules. Returns counts applied."""
    applied = {'add': 0, 'update': 0, 'resolve': 0}
    if not isinstance(operations, dict):
        return applied
    current = {f['id']: f for f in (dict(r) for r in conn.execute(
        "SELECT * FROM facts WHERE save_id=? AND status='open'", (save_id,)))}
    known = {(f['category'], f['body'].casefold()) for f in current.values()}
    budget = OPS_LIMIT

    def items(name):
        value = operations.get(name)
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    for item in items('resolve'):
        fact, reason = current.get(item.get('id')), clean(item.get('reason'), REASON_LIMIT)
        if budget <= 0 or not fact or fact['locked'] or not reason:
            continue
        update(conn, fact, {'status': 'resolved', 'reason': reason}, None, stamp)
        log(conn, {**fact, 'status': 'resolved'}, 'resolve', reason, None, summary_id, stamp)
        current.pop(fact['id'])
        applied['resolve'] += 1
        budget -= 1
    for item in items('update'):
        fact = current.get(item.get('id'))
        body, reason = clean(item.get('text'), BODY_LIMIT), clean(item.get('reason'), REASON_LIMIT)
        if budget <= 0 or not fact or fact['locked'] or not body or not reason or body == fact['body']:
            continue
        update(conn, fact, {'body': body, 'reason': reason}, None, stamp)
        log(conn, {**fact, 'body': body}, 'update', reason, None, summary_id, stamp)
        applied['update'] += 1
        budget -= 1
    open_count = len(current)
    for item in items('add'):
        category, body = item.get('category'), clean(item.get('text'), BODY_LIMIT)
        if budget <= 0 or open_count >= OPEN_LIMIT or category not in CATEGORIES or not body:
            continue
        if (category, body.casefold()) in known:
            continue
        fact_id = conn.execute('INSERT INTO facts (save_id,category,body,created_at,updated_at) VALUES (?,?,?,?,?)',
                               (save_id, category, body, stamp, stamp)).lastrowid
        log(conn, row(conn, save_id, fact_id), 'add', None, None, summary_id, stamp)
        known.add((category, body.casefold()))
        open_count += 1
        applied['add'] += 1
        budget -= 1
    return applied


def narration_text(facts):
    """Open facts for the AI-DM, grouped by category."""
    groups = []
    for category, label in CATEGORIES.items():
        bodies = [f['body'] for f in open_facts(facts) if f['category'] == category]
        if bodies:
            groups.append(label + ':\n' + '\n'.join('- ' + body for body in bodies))
    if not groups:
        return ''
    return ('\n\nEstablished facts from play (keep narration consistent with these unless play '
            'changes them; recent transcript messages below are newer):\n' + '\n\n'.join(groups))
