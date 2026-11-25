"""Exercise editor keyboard input and cancellation without a real terminal."""
from types import SimpleNamespace
import unittest

from routing_tui import CANCEL, TerminalMenu


KEYS = SimpleNamespace(
    A_BOLD=1, A_DIM=2, A_REVERSE=4,
    KEY_UP=301, KEY_DOWN=302, KEY_HOME=303, KEY_END=304, KEY_PPAGE=305, KEY_NPAGE=306,
    KEY_BACKSPACE=307, KEY_ENTER=308,
    curs_set=lambda _value: None, has_colors=lambda: False, set_escdelay=lambda _value: None,
)


class Screen:
    def __init__(self, *keys, size=(24, 80)):
        self.keys = iter(keys)
        self.size = size
        self.frames = []

    def getmaxyx(self):
        return self.size

    def get_wch(self):
        return next(self.keys)

    def erase(self):
        self.lines = {}

    def addnstr(self, y, x, text, width, style):
        self.lines[y] = (text[:width].rstrip(), style)

    def refresh(self):
        self.frames.append(self.lines)


class TerminalMenuTest(unittest.TestCase):
    def test_main_menu_shows_groups_and_keeps_the_selected_row_visible(self):
        screen = Screen(KEYS.KEY_END, '\n', size=(10, 80))
        menu = TerminalMenu(screen, KEYS)
        menu.setup(None, 'Laya', 'gpt-6.1-sol')
        choices = {index: f'Option {index}' for index in range(10)}
        selected = menu.choose('AI routing', choices, sections={0: 'LAYA TIERS', 8: 'REQUEST TYPES'})
        self.assertEqual(selected, 9)
        self.assertIn(('LAYA TIERS', KEYS.A_BOLD), screen.frames[0].values())
        self.assertIn(('> Option 9', KEYS.A_REVERSE), screen.frames[-1].values())

    def test_typing_filters_models_and_arrow_keys_pick_a_result(self):
        screen = Screen(*'6.2', KEYS.KEY_DOWN, '\n')
        menu = TerminalMenu(screen, KEYS)
        models = []
        loaded = ['gpt-6.1-sol', 'gpt-6.2-astra', 'gpt-6.2-sol']
        picked = menu.choose_model('gpt-6.1-sol', 'Use the model from Laya', models, lambda: loaded)
        self.assertEqual(picked, (True, 'gpt-6.2-sol'))
        self.assertEqual(models, loaded)
        self.assertIn(('Filter: 6.2', KEYS.A_BOLD), screen.frames[-1].values())
        self.assertNotIn('gpt-6.1-sol', ' '.join(text for text, _ in screen.frames[-1].values()))

    def test_escape_cancels_and_enter_on_empty_search_does_not_select(self):
        screen = Screen('z', '\n', '\x1b')
        menu = TerminalMenu(screen, KEYS)
        selected = menu.choose('Select model', {'sol': 'Sol'}, search=True)
        self.assertIs(selected, CANCEL)
        self.assertIn(('No matching models', KEYS.A_DIM), screen.frames[-1].values())

    def test_discard_defaults_to_keep_editing(self):
        self.assertFalse(TerminalMenu(Screen('\n'), KEYS).confirm_discard())
        self.assertTrue(TerminalMenu(Screen(KEYS.KEY_DOWN, '\n'), KEYS).confirm_discard())
