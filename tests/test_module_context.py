"""Retrieval must supply remote facts before narration without crawling the dungeon."""
import unittest

import module_context


MODULE = """# Test adventure
## Running notes
The third bell changes the whole site.
## Areas
### Area 1: Gate *(entrance)*
GATE DESCRIPTION
### Area 4: Wardrobe
WARDROBE DESCRIPTION
### Area 5: The Prompt Room
PROMPT ROOM DESCRIPTION

**Lore and DM notes.** THE PROMPT-BOOK (the ledger). Reading it reveals Muxus's
lair actions in Area 8. ROLE-MASKS: these do not compel their wearers.

**Treasure.** The prompt-book; a silver compass.
### Area 6: The Fly Gallery
GALLERY TRIPWIRE
### Area 8: The Stage
STAGE CAGES
### Area 9: The Observatory
OBSERVATORY SECRET
## Stat blocks
### Muxus, the Spared (CR 15)
EXACT MUXUS LAIR ACTIONS
### Shenka the Prompter (CR 8)
SHENKA STAT BLOCK
### Star Beast (CR 9)
UNRELATED STAR BEAST
"""
ROOMS = [
    {'roomNumber': 1, 'beat': 'entrance', 'connectsTo': [4]},
    {'roomNumber': 4, 'connectsTo': [1, 5]},
    {'roomNumber': 5, 'connectsTo': [4, 6], 'encounter': {'monsters': ['Shenka the Prompter']},
     'treasure': ['the prompt-book (see lore)', 'a silver compass']},
    {'roomNumber': 6, 'connectsTo': [5]},
    {'roomNumber': 8, 'connectsTo': [4], 'encounter': {'monsters': ['Muxus, the Spared']}},
    {'roomNumber': 9, 'connectsTo': [], 'encounter': {'monsters': ['Star Beast']}},
]


class RetrievalTest(unittest.TestCase):
    def setUp(self):
        self.adventure = module_context.Adventure(MODULE, {'rooms': ROOMS})

    def assemble(self, query, location=5):
        return self.adventure.assemble(location, [('current player contributions', query)])

    def test_reading_book_supplies_remote_mechanics_without_recursive_crawl(self):
        base, _ = self.assemble('I wait.')
        self.assertNotIn('EXACT MUXUS LAIR ACTIONS', base)
        focused, report = self.assemble('I read the prompt book.')
        self.assertIn('EXACT MUXUS LAIR ACTIONS', focused)
        self.assertIn('STAGE CAGES', focused)
        self.assertNotIn('OBSERVATORY SECRET', focused)
        self.assertNotIn('GATE DESCRIPTION', focused)
        reason = next(s['reason'] for s in report['included'] if s['title'].startswith('Area 8'))
        self.assertIn('referenced by prompt book', reason)

    def test_remote_destination_is_loaded_without_moving_party(self):
        for query in ('We teleport to Area 9.', 'We travel to the Observatory.'):
            with self.subTest(query=query):
                focused, report = self.assemble(query)
                self.assertIn('OBSERVATORY SECRET', focused)
                self.assertIn('UNRELATED STAR BEAST', focused)
                self.assertEqual(report['location'], 5)

    def test_named_monster_is_retrieved_without_matching_substrings(self):
        focused, _ = self.assemble("What are Muxus's lair actions?")
        self.assertIn('EXACT MUXUS LAIR ACTIONS', focused)
        self.assertNotIn('STAGE CAGES', focused)
        focused, _ = self.assemble('Tell me about Muxusville.')
        self.assertNotIn('EXACT MUXUS LAIR ACTIONS', focused)

    def test_multi_area_references_and_stable_core(self):
        self.assertEqual(list(module_context.area_references('Areas 6, 3, and 2; Area 8.')), [6, 3, 2, 8])
        base, _ = self.assemble('Wait.')
        extra, _ = self.assemble('We teleport to Area 9.')
        self.assertEqual(base.split('# Current focus')[0], extra.split('# Current focus')[0])

    def test_unstructured_cartridge_keeps_full_fallback(self):
        adventure = module_context.Adventure(MODULE, {})
        focused, report = adventure.assemble(None, [('question', 'Muxus')])
        self.assertEqual(focused, MODULE)
        self.assertEqual(report['mode'], 'full')

    def test_stage2_level_two_areas_include_their_subsections(self):
        module = """# Adventure
## Running Notes
CORE
## Area 1: Gate
### Boxed Text
GATE TEXT
### DM Notes
GATE SECRET
## Area 4: Hall
### Boxed Text
HALL TEXT
"""
        adventure = module_context.Adventure(module, {'rooms': ROOMS[:2]})
        self.assertTrue(adventure.focused)
        focused, report = adventure.assemble(1)
        self.assertIn('GATE TEXT', focused)
        self.assertIn('GATE SECRET', focused)
        self.assertIn('HALL TEXT', focused)
        self.assertEqual(report['locationLabel'], 'Area 1: Gate')


if __name__ == '__main__':
    unittest.main()
