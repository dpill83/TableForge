"""Durable public questions, independent of narration and combat transitions."""
import json
import uuid

TIMEOUT = 180


def initialize(conn, stamp):
    conn.execute('''CREATE TABLE IF NOT EXISTS public_questions (
        id TEXT PRIMARY KEY, save_id TEXT NOT NULL REFERENCES saves(id),
        player_id TEXT NOT NULL REFERENCES players(id),
        message_id INTEGER NOT NULL UNIQUE REFERENCES messages(id),
        session_id TEXT NOT NULL REFERENCES sessions(id), beat INTEGER NOT NULL,
        source_message_id INTEGER, context TEXT NOT NULL,
        status TEXT NOT NULL, answer TEXT, token TEXT, error TEXT,
        UNIQUE(save_id,id))''')
    # No provider workers survive a process restart. Retrying keeps the original context.
    conn.execute("UPDATE saves SET updated_at=? WHERE id IN (SELECT save_id FROM public_questions WHERE status='pending')", (stamp,))
    conn.execute("UPDATE public_questions SET status='failed',token=NULL,error='Question interrupted; retry.' WHERE status='pending'")
    conn.execute('CREATE INDEX IF NOT EXISTS public_questions_save ON public_questions(save_id)')


def visible(conn, save_id):
    return {row['message_id']: dict(row) for row in conn.execute(
        'SELECT id,message_id,player_id,beat,source_message_id,status,answer,error '
        'FROM public_questions WHERE save_id=?', (save_id,))}


def context(state, question, image=None):
    # Deliberately never load a cartridge, summary, private thread, or pending IC actions.
    published = [m for m in state['messages'] if m['kind'] == 'ai'][-20:]
    rulings = [dict(question=m['body'], answer=m['ooc']['answer'])
               for m in state['messages'] if m.get('ooc', {}).get('status') == 'complete'][-20:]
    result = {'purpose': 'ooc', 'title': state['cartridge']['title'],
              'beat': state['save']['beat'], 'question': question,
              'messages': [{'kind': 'ai', 'name': m['name'], 'body': m['body']} for m in published],
              'publicRulings': rulings,
              'publicNotes': [{'title': n['title'], 'body': n['body']} for n in state.get('notes', [])],
              'publicOutcomes': [e['body'] for e in state.get('events', [])
                                 if e['kind'] in ('combat_outcome', 'combat_correction')]}
    if image:
        result['questionImage'] = image
    return result


def claim(conn, request_id):
    token = str(uuid.uuid4())
    row = conn.execute('SELECT * FROM public_questions WHERE id=?', (request_id,)).fetchone()
    if row['status'] in ('complete', 'pending'):
        return None
    conn.execute("UPDATE public_questions SET status='pending',token=?,error=NULL WHERE id=?", (token, request_id))
    return token, json.loads(row['context']), row['session_id']


def finish(conn, request_id, token, answer=None):
    return conn.execute('''UPDATE public_questions SET status=?,answer=?,error=?,token=NULL
        WHERE id=? AND token=? AND status='pending' ''',
        ('complete' if answer else 'failed', answer,
         None if answer else 'The AI-DM could not answer. Retry this question.', request_id, token)).rowcount
