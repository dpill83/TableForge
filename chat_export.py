"""Readable Markdown exports of saved public conversation only."""
import json
import re
from datetime import datetime

import narration_choices


def export_chat(conn, save_id):
    save = conn.execute(
        'SELECT s.name, COALESCE(s.adventure_title, c.title) AS title '
        'FROM saves s JOIN cartridges c ON c.id=s.cartridge_id WHERE s.id=?',
        (save_id,)).fetchone()
    if not save:
        raise ValueError('Save not found')
    players = [dict(row) for row in conn.execute('SELECT id,character FROM players WHERE save_id=?', (save_id,))]
    characters = {p['id']: p['character'] for p in players}
    sessions = {row['id']: row['number'] for row in conn.execute(
        'SELECT id,number FROM sessions WHERE save_id=? ORDER BY number', (save_id,))}
    # Query the durable tables directly; never depend on a client snapshot or feed window.
    entries = []
    for row in conn.execute(
            "SELECT * FROM messages WHERE save_id=? AND kind IN ('ai','player') ORDER BY id", (save_id,)):
        label = 'AI-DM' if row['kind'] == 'ai' else row['name']
        body = row['body']
        if row['kind'] == 'ai' and row['choices_json']:
            body = narration_choices.public_body(body, json.loads(row['choices_json']), players)
        entries.append((row['created_at'], 1, row['id'], row['session_id'], label, body))
    for row in conn.execute(
            "SELECT * FROM session_events WHERE save_id=? AND kind IN ('combat_outcome','combat_correction') ORDER BY id", (save_id,)):
        entries.append((row['created_at'], 0, row['id'], row['session_id'],
                        characters.get(row['player_id'], 'A player') + (' — Combat correction' if row['kind'] == 'combat_correction' else ' — Combat outcome'), row['body']))
    heading = lambda value: narration_choices.markdown_text(' '.join(value.split()))
    parts = [f"# {heading(save['title'])}", f"Playthrough: {heading(save['name'])}"]
    previous = object()
    for _, _, _, session_id, label, body in sorted(entries):
        number = sessions.get(session_id, next(iter(sessions.values()), 1))
        if number != previous:
            parts.append(f'## Session {number}')
            previous = number
        parts.extend((f'### {heading(label)}', body))
    filename_title = re.sub(r'[^\w-]+', '-', save['title'], flags=re.UNICODE).strip('-_')[:100] or 'TableForge'
    filename = f'{filename_title}-chat-{datetime.now().astimezone().date().isoformat()}.md'
    return filename, ('\n\n'.join(parts) + '\n').encode('utf-8')
