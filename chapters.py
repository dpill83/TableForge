"""Chapters: the adventure's story phases, each condensed into one recap.

The prologue ends automatically when the opening flow reaches exploration.
Later chapters end when a Pilot says so, often prompted by an AI-DM suggestion.
A closed chapter's recap replaces its raw chat in AI-DM context once it exists;
until then nothing from that chapter is dropped.

Only closed chapters and the current open chapter after the first are stored.
With no rows, the save is in an implicit Chapter 1.
"""
import re

import opening_flow

TITLE_LIMIT = 80
RECAP_LIMIT = 20_000
MARKER = re.compile(r'^[ \t]*\[\s*Chapter\s*:\s*([^\]\r\n]{1,80}?)\s*\][ \t]*\r?$', re.I | re.M)

INSTRUCTIONS = (
    '\n\nChapters: TableForge groups the adventure into chapters (prologue, exploring, the '
    'middle where the story comes together and builds to its climax, then the finale and '
    'epilogue). When this narration clearly completes the current chapter, add a final line '
    '[Chapter: Short title for the next chapter]. Use it only at a natural break, never '
    'mid-scene or mid-fight, and at most once per chapter. It is a suggestion a Pilot confirms; '
    'never mention chapters in the narration itself.'
)

RECAP_PROMPT = (
    'You write the recap of one finished chapter of a TableForge adventure for the players\' '
    'journal. Write one to three short paragraphs in past tense covering what the party did, '
    'learned, decided, and left unresolved in this chapter. Use only facts from the material '
    'given. OOC questions are hypothetical and never happened. Do not narrate a new beat.'
)


def initialize(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT, save_id TEXT NOT NULL REFERENCES saves(id),
            number INTEGER NOT NULL, title TEXT NOT NULL,
            started_after INTEGER NOT NULL DEFAULT 0, ended_through INTEGER,
            recap TEXT, recap_by TEXT, recap_at TEXT,
            closed_by TEXT, closed_source TEXT, created_at TEXT NOT NULL, closed_at TEXT,
            revision INTEGER NOT NULL DEFAULT 1,
            UNIQUE(save_id, number)
        );
    ''')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(saves)')}
    if 'chapter_suggestion' not in columns:
        conn.execute('ALTER TABLE saves ADD COLUMN chapter_suggestion TEXT')


def default_title(number, save):
    if number == 1:
        return 'Prologue' if save.get('opening_stage') in opening_flow.GUIDANCE else 'Chapter 1'
    return f'Chapter {number}'


def label(number, title):
    """'Chapter 2: The Mine', or just 'Chapter 2' when the title is the default."""
    return f'Chapter {number}' if title == f'Chapter {number}' else f'Chapter {number}: {title}'


def rows(conn, save_id):
    return [dict(r) for r in conn.execute('SELECT * FROM chapters WHERE save_id=? ORDER BY number', (save_id,))]


def visible(conn, save):
    """Every chapter, closed ones first, ending with the open one (implicit Chapter 1 if none)."""
    listed = rows(conn, save['id'])
    if not listed or listed[-1]['ended_through'] is not None:
        number = listed[-1]['number'] + 1 if listed else 1
        listed.append({'id': None, 'save_id': save['id'], 'number': number, 'title': default_title(number, save),
                       'started_after': listed[-1]['ended_through'] if listed else 0, 'ended_through': None,
                       'recap': None, 'recap_by': None, 'recap_at': None, 'closed_by': None,
                       'closed_source': None, 'created_at': None, 'closed_at': None, 'revision': 0})
    return listed


def current(listed):
    return listed[-1]


def recapped_end(listed):
    """The last message id covered by chapter recaps, in order with no gaps."""
    end = 0
    for chapter in listed:
        if chapter['ended_through'] is None or not chapter['recap']:
            break
        end = chapter['ended_through']
    return end


def pending_recap(listed):
    """The earliest closed chapter still waiting for its recap."""
    return next((c for c in listed if c['ended_through'] is not None and not c['recap']), None)


def clean_title(title):
    title = ' '.join(str(title or '').split())
    if len(title) > TITLE_LIMIT:
        raise ValueError(f'Chapter titles are limited to {TITLE_LIMIT} characters')
    return title


def close(conn, save, through, next_title, player_id, source, stamp):
    """End the open chapter through message `through` and open the next one."""
    listed = visible(conn, save)
    chapter = current(listed)
    if through is None or through <= chapter['started_after']:
        raise ValueError('This chapter has no completed play yet')
    if chapter['id'] is None:
        chapter['id'] = conn.execute(
            'INSERT INTO chapters (save_id,number,title,started_after,created_at) VALUES (?,?,?,?,?)',
            (save['id'], chapter['number'], chapter['title'], chapter['started_after'], stamp)).lastrowid
    conn.execute('UPDATE chapters SET ended_through=?,closed_by=?,closed_source=?,closed_at=?,revision=revision+1 WHERE id=?',
                 (through, player_id, source, stamp, chapter['id']))
    number = chapter['number'] + 1
    conn.execute('INSERT INTO chapters (save_id,number,title,started_after,created_at) VALUES (?,?,?,?,?)',
                 (save['id'], number, clean_title(next_title) or default_title(number, save), through, stamp))
    conn.execute('UPDATE saves SET chapter_suggestion=NULL WHERE id=?', (save['id'],))
    return number


def take_marker(text):
    """Strip chapter suggestions from narration; return clean text and the last suggested title."""
    found = MARKER.findall(text)
    clean = MARKER.sub('', text).rstrip()
    return clean, (clean_title(found[-1])[:TITLE_LIMIT] or None) if found else None


def store_recap(conn, chapter_id, body, player_id, stamp, revision=None):
    """Save a recap. Automatic recaps (revision None) only fill an empty recap."""
    body = str(body or '').strip()
    if not body or len(body) > RECAP_LIMIT:
        raise ValueError(f'A recap must contain 1 to {RECAP_LIMIT:,} characters')
    found = conn.execute('SELECT * FROM chapters WHERE id=?', (chapter_id,)).fetchone()
    if not found or found['ended_through'] is None:
        raise ValueError('Only a finished chapter has a recap')
    if revision is None and found['recap']:
        raise ValueError('This chapter already has a recap')
    if revision is not None and revision != found['revision']:
        raise ValueError('This recap changed since you opened it. Review the latest version.')
    conn.execute('UPDATE chapters SET recap=?,recap_by=?,recap_at=?,revision=revision+1 WHERE id=?',
                 (body, player_id, stamp, chapter_id))
