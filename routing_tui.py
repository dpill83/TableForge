"""Keyboard-driven terminal screens for the routing editor."""
import os
import sys
from textwrap import wrap

CANCEL = object()


def terminal_library():
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or os.environ.get('TERM') == 'dumb':
        return None
    try:
        import curses
    except ImportError:
        return None
    try:
        curses.setupterm()
    except curses.error:
        return None
    return curses


class TerminalMenu:
    def __init__(self, screen, curses):
        self.screen = screen
        self.curses = curses
        self.heading = curses.A_BOLD
        self.details = ''
        self.message = ''
        try:
            curses.curs_set(0)
            if curses.has_colors():
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_CYAN, -1)
                self.heading |= curses.color_pair(1)
        except curses.error:
            pass
        curses.set_escdelay(100)

    def setup(self, _path, policy, fallback):
        self.details = f'Inherited policy: {policy}   |   Server fallback: {fallback}'

    def notice(self, message):
        self.message = message

    def progress(self, message):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self.line(0, 'TableForge  /  AI routing', self.heading)
        for y, line in enumerate(wrap(message, max(1, width - 2)), start=2):
            self.line(y, line)
        self.line(height - 1, 'Ctrl+C  Cancel', self.curses.A_DIM)
        self.screen.refresh()

    def choose(self, title, choices, current=None, *, detail='', sections=None, search=False):
        query = ''
        active = current
        offset = 0
        sections = sections or {}
        message, self.message = self.message, ''
        keys = self.curses
        while True:
            options = [key for key, label in choices.items() if query.casefold() in label.casefold()]
            if active not in options:
                active = options[0] if options else CANCEL
            rows = []
            for key in options:
                if key in sections:
                    rows.append((CANCEL, sections[key]))
                rows.append((key, choices[key]))
            offset, page = self.draw(title, detail, rows, active, offset, search, query, message=message)
            key = self.screen.get_wch()
            if key == '\x1b':
                return CANCEL
            if page == 0:
                continue
            if key in ('\n', '\r', keys.KEY_ENTER) and options:
                return active
            if options and key in (keys.KEY_UP, keys.KEY_DOWN, keys.KEY_PPAGE, keys.KEY_NPAGE,
                                   keys.KEY_HOME, keys.KEY_END):
                index = options.index(active)
                moves = {keys.KEY_UP: index - 1, keys.KEY_DOWN: index + 1,
                         keys.KEY_PPAGE: index - page, keys.KEY_NPAGE: index + page,
                         keys.KEY_HOME: 0, keys.KEY_END: len(options) - 1}
                active = options[max(0, min(len(options) - 1, moves[key]))]
            elif search:
                if key in ('\x08', '\x7f', keys.KEY_BACKSPACE):
                    query = query[:-1]
                elif key == '\x15':
                    query = ''
                elif isinstance(key, str) and key.isprintable() and len(query) < 200:
                    query += key

    def choose_model(self, current, allow_laya, models, load_models, *, detail=''):
        if not models:
            self.progress('Loading models from OpenAI...')
            try:
                models.extend(load_models())
            except ValueError as error:
                if not (allow_laya or current):
                    raise
                self.notice(str(error))
        choices = {model: model for model in models}
        if current and current not in choices:
            choices = {current: current, **choices}
        if allow_laya:
            choices = {None: 'Use the model from Laya', **choices}
        if not choices:
            raise ValueError('OpenAI returned no model IDs.')
        model = self.choose('Select model', choices, current, detail=detail, search=True)
        return (False, current) if model is CANCEL else (True, model)

    def confirm_discard(self):
        return self.choose('Discard unsaved changes?', {False: 'Keep editing', True: 'Discard and exit'},
                           False) is True

    def draw(self, title, detail, rows, active, offset, search, query, *, message):
        screen = self.screen
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 9 or width < 32:
            self.line(0, 'Resize terminal to continue | Esc to go back', self.heading)
            screen.refresh()
            return 0, 0

        self.line(0, 'TableForge  /  ' + title, self.heading)
        self.line(1, self.details, self.curses.A_DIM)
        self.line(2, detail)
        top = 4
        hints = 'Up/Down  Move   Enter  Select   Esc  Back'
        if search:
            self.line(3, 'Filter: ' + query, self.curses.A_BOLD)
            hints = 'Type to filter   Up/Down  Move   Enter  Select   Esc  Back'
        messages = wrap(message, width - 2)[:2] if message else []
        page = max(1, height - top - len(messages) - 2)
        selected = (next((index for index, (key, _) in enumerate(rows) if key == active), None)
                    if active is not CANCEL else None)
        if selected is not None:
            offset = max(0, min(offset, selected), selected - page + 1)
        else:
            offset = 0
        for number, (key, label) in enumerate(rows[offset:offset + page], offset):
            index = top + number - offset
            if key is CANCEL:
                self.line(index, label, self.heading)
            elif number == selected:
                self.line(index, ('> ' + label).ljust(width - 1), self.curses.A_REVERSE)
            else:
                self.line(index, '  ' + label)
        if search and not rows:
            self.line(top, 'No matching models', self.curses.A_DIM)
        for i, line in enumerate(messages, height - len(messages) - 2):
            self.line(i, line, self.curses.A_BOLD)
        if len(rows) > page:
            self.line(height - 2, f'{offset + 1}-{min(offset + page, len(rows))} of {len(rows)} rows',
                      self.curses.A_DIM)
        self.line(height - 1, hints, self.curses.A_DIM)
        screen.refresh()
        return offset, page

    def line(self, y, text, style=0):
        height, width = self.screen.getmaxyx()
        if y < height and width > 1:
            try:
                self.screen.addnstr(y, 0, text, width - 1, style)
            except self.curses.error:
                # The terminal may resize between measuring and drawing.
                pass
