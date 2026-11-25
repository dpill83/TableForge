"""Transient, public narration previews. The save remains the record of play."""
from contextlib import contextmanager
import re
import threading
import time


# A control marker can begin mid-line (Location), span chunks, or arrive
# malformed. Hold everything from a known marker until final publication.
CONTROL = re.compile(
    r'\[\s*(?:opening|location|chapter)\s*:|\[\[\s*tableforge'
    r'|^[ \t]*(?:\x60{3,}|~{3,})[ \t]*tableforge', re.IGNORECASE | re.MULTILINE
)
PARTIAL_CONTROL = re.compile(
    r'\[\[\s*[a-z_]*\Z|\[\s*[a-z]*\s*\Z'
    r'|^[ \t]*(?:\x60+|~+)[ \t]*[a-z-]*\Z', re.IGNORECASE | re.MULTILINE
)
# Chapter suggestions are for Pilots to confirm; players never see them stream.
CONTROL_NAMES = ('opening', 'location', 'chapter')
UNFINISHED_CONTROL = re.compile(
    r'\[\s*(?:open(?:i(?:n(?:g)?)?)?|loca(?:t(?:i(?:o(?:n)?)?)?)?|chap(?:t(?:e(?:r)?)?)?)\s*\Z'
    r'|\[\[\s*table[a-z_]*\Z|^[ \t]*(?:\x60{3,}|~{3,})[ \t]*tableforge(?:-[a-z]*)?\Z',
    re.IGNORECASE | re.MULTILINE,
)


def contains_control(text):
    return bool(CONTROL.search(text) or UNFINISHED_CONTROL.search(text))


def preview_text(text):
    marker = CONTROL.search(text)
    if marker:
        return text[:marker.start()].rstrip()
    tail = PARTIAL_CONTROL.search(text)
    if tail:
        fragment = tail.group().strip().lower()
        if fragment.startswith('[['):
            possible = 'tableforge'.startswith(fragment[2:].strip())
        elif fragment.startswith('['):
            name = fragment[1:].strip()
            possible = any(candidate.startswith(name) for candidate in CONTROL_NAMES)
        else:
            possible = 'tableforge-choices'.startswith(fragment.lstrip('\x60~').lstrip())
        if possible:
            return text[:tail.start()].rstrip()
    return text.rstrip()


class NarrationPreviews:
    def __init__(self):
        self.condition = threading.Condition()
        self.entries = {}
        self.listeners = 0

    @contextmanager
    def subscribe(self, limit=24):
        with self.condition:
            subscribed = self.listeners < limit
            self.listeners += int(subscribed)
        try:
            yield subscribed
        finally:
            with self.condition:
                self.listeners -= int(subscribed)

    def start(self, save_id, attempt, session_id, beat):
        with self.condition:
            now = time.monotonic()
            self.entries = {
                key: entry for key, entry in self.entries.items()
                if entry[1] is None or entry[1] > now
            }
            self.entries[save_id] = ({
                'attempt': attempt, 'revision': 0, 'sessionId': session_id,
                'beat': beat, 'status': 'waiting',
            }, None)
            self.condition.notify_all()

    def update(self, save_id, attempt, text):
        with self.condition:
            current, expires = self.entries.get(save_id, (None, None))
            if current is None or current['attempt'] != attempt or expires is not None:
                return
            self.entries[save_id] = ({
                **current, 'revision': current['revision'] + 1, 'status': 'streaming', 'text': text,
            }, None)
            self.condition.notify_all()

    def finish(self, save_id, attempt, message_id=None):
        with self.condition:
            current, expires = self.entries.get(save_id, (None, None))
            if current is None or current['attempt'] != attempt or expires is not None:
                return
            terminal = {key: value for key, value in current.items() if key != 'text'}
            terminal.update(revision=current['revision'] + 1,
                            status='committed' if message_id is not None else 'failed')
            if message_id is not None:
                terminal['messageId'] = message_id
            self.entries[save_id] = (terminal, time.monotonic() + 90)
            self.condition.notify_all()

    def clear(self, save_id=None):
        with self.condition:
            if save_id is None:
                self.entries.clear()
            else:
                self.entries.pop(save_id, None)
            self.condition.notify_all()

    def wait(self, save_id, previous, timeout):
        with self.condition:
            def current():
                entry, expires = self.entries.get(save_id, (None, None))
                return entry if expires is None or expires > time.monotonic() else None

            self.condition.wait_for(lambda: current() is not previous, timeout)
            return current()
