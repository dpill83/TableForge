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
    sessions = {row['id']: dict(row) for row in conn.execute(
        'SELECT id,number,started_at,ended_at FROM sessions WHERE save_id=? ORDER BY number', (save_id,))}
    # Query the durable tables directly; never depend on a client snapshot or feed window.
    entries = []
    for row in conn.execute(
            "SELECT * FROM messages WHERE save_id=? AND kind IN ('ai','player') ORDER BY id", (save_id,)):
        label = 'AI-DM' if row['kind'] == 'ai' else row['name']
        body = row['body']
        if row['kind'] == 'ai' and row['choices_json']:
            body = narration_choices.public_body(body, json.loads(row['choices_json']), players)
        entries.append((row['created_at'], 1, row['id'], row['session_id'], 'message', label, body))
    for row in conn.execute(
            "SELECT * FROM session_events WHERE save_id=? AND kind IN ('combat_started','combat_outcome','combat_correction') "
            "ORDER BY id", (save_id,)):
        if row['kind'] == 'combat_started':
            label = 'Combat started'
        else:
            label = characters.get(row['player_id'], 'A player') + (
                ' — Combat correction' if row['kind'] == 'combat_correction' else ' — Combat outcome')
        entries.append((row['created_at'], 0, row['id'], row['session_id'], row['kind'], label, row['body']))
    entries.sort()
    default_session = next(iter(sessions), None)
    session_of = lambda session_id: session_id if session_id in sessions else default_session

    # Session spans: from session start to its recorded end, or to its last saved entry.
    spans = {}
    for stamp, _, _, session_id, *_ in entries:
        key = session_of(session_id)
        start, end = spans.get(key, (None, None))
        moment = _parse(stamp)
        spans[key] = (start if start and start <= moment else moment, end if end and end >= moment else moment)
    for key, session in sessions.items():
        if key not in spans:
            continue
        start, end = spans[key]
        started, ended = _parse(session['started_at']), _parse(session['ended_at'])
        spans[key] = (min(start, started) if started else start, ended if ended and ended >= start else end)

    # Pair each combat start with the outcome that closed it.
    combat_lengths, open_combat = {}, None
    for stamp, _, event_id, _, kind, *_ in entries:
        if kind == 'combat_started':
            open_combat = _parse(stamp)
        elif kind == 'combat_outcome' and open_combat:
            combat_lengths[event_id] = _parse(stamp) - open_combat
            open_combat = None

    heading = lambda value: narration_choices.markdown_text(' '.join(value.split()))
    parts = [f"# {heading(save['title'])}", f"Playthrough: {heading(save['name'])}"]
    if entries:
        first, last = _parse(entries[0][0]), _parse(entries[-1][0])
        table_time = sum((end - start for start, end in spans.values()), first - first)
        summary = [f"Played: {_date(first)}" + (f" – {_date(last)}" if _date(first) != _date(last) else ''),
                   f"Sessions: {len(spans)} · Table time: {_duration(table_time)}"]
        if combat_lengths:
            summary.append(f"Combat: {len(combat_lengths)} {'fight' if len(combat_lengths) == 1 else 'fights'} · "
                           f"{_duration(sum(combat_lengths.values(), first - first))} total")
        summary.append(f"Times shown in {first.strftime('%Z') or 'local time'}.")
        parts.append('  \n'.join(summary))
    previous, previous_day = object(), None
    for stamp, _, event_id, session_id, kind, label, body in entries:
        key = session_of(session_id)
        moment = _parse(stamp)
        if key != previous:
            number = sessions[key]['number'] if key in sessions else 1
            start, end = spans[key]
            parts.append(f'## Session {number} — {_date(start)}, {_time(start)} – '
                         f'{_time(end) if _date(end) == _date(start) else _date(end) + ", " + _time(end)} '
                         f'({_duration(end - start)})')
            previous, previous_day = key, _date(start)
        when = _time(moment) if _date(moment) == previous_day else f'{_date(moment)}, {_time(moment)}'
        previous_day = _date(moment)
        suffix = f' (combat lasted {_duration(combat_lengths[event_id])})' if event_id in combat_lengths and kind == 'combat_outcome' else ''
        parts.append(f'### {heading(label)} · {when}{suffix}')
        if body:
            parts.append(body)
    filename_title = re.sub(r'[^\w-]+', '-', save['title'], flags=re.UNICODE).strip('-_')[:100] or 'TableForge'
    filename = f'{filename_title}-chat-{datetime.now().astimezone().date().isoformat()}.md'
    return filename, ('\n\n'.join(parts) + '\n').encode('utf-8')


def _parse(value):
    """Saved UTC ISO stamps, shown in the host's local time."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone()


def _date(moment):
    return f"{moment.strftime('%a, %b')} {moment.day}, {moment.year}"


def _time(moment):
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def _duration(delta):
    minutes = max(0, round(delta.total_seconds() / 60))
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m' if hours else f'{minutes}m'
