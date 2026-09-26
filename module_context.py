"""Focused module context: the always-sent core plus the party's current area and its horizon.

run-data.json supplies the structure (rooms, connectsTo, monsters); module.md supplies the
authored prose, split on its `##`/`###` headings. Sections are matched by convention:

- `### Area N: Name` under `## Areas` belongs to room N.
- `### Name (CR x)` under `## Stat blocks` is the stat block for monster `Name`.
- `Player Briefing` and `Approach...` sections are sent only before the party reaches the site.
- Every other section is core and is always sent, so nothing unrecognized is silently dropped.
- Current contributions can add named subjects and their explicit cross-references before narration.
"""
import json
import re
import zipfile
from pathlib import Path

APPROACH = 'approach'
AREA_HEADING = re.compile(r'^Area\s+(\d+)\b', re.IGNORECASE)
MARKER = re.compile(r'\[\s*Location\s*:\s*(Approach|Area\s*(\d+))[^\]]*\]', re.IGNORECASE)


def split_sections(text):
    """Split markdown into sections at level-2 and level-3 headings, keeping each parent heading."""
    sections, parent = [], None
    current = {'level': 1, 'title': '', 'parent': None, 'lines': []}
    for line in text.splitlines(keepends=True):
        match = re.match(r'^(#{2,3})\s+(.*)$', line.rstrip('\r\n'))
        if match:
            sections.append(current)
            level, title = len(match.group(1)), match.group(2).strip()
            if level == 2:
                parent = title
            current = {'level': level, 'title': title, 'parent': parent if level == 3 else None, 'lines': []}
        current['lines'].append(line)
    sections.append(current)
    for section in sections:
        section['text'] = ''.join(section.pop('lines'))
    return [section for section in sections if section['text']]


def stat_name(value):
    return re.sub(r'\s*\(CR [^)]*\)\s*$', '', re.sub(r'^\d+\s+', '', str(value))).strip().lower()


def phrase(value):
    """Compare authored names across case, apostrophes and hyphen styles."""
    return ' '.join(re.findall(r'\w+', str(value).lower().replace('\u2019', "'"))).removeprefix('the ')


def mentions(text, name):
    return bool(name) and f' {name} ' in f' {phrase(text)} '


def area_references(text):
    for match in re.finditer(r'\bAreas?\s+(\d+(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+)\d+)*)', text, re.I):
        yield from (int(number) for number in re.findall(r'\d+', match.group(1)))


def classify(section):
    parent = (section['parent'] or '').lower()
    title = section['title']
    area = AREA_HEADING.match(title)
    if parent == 'areas' and area:
        return 'area', int(area.group(1))
    if parent == 'stat blocks' and section['level'] == 3:
        return 'stat', stat_name(title)
    if title.lower().startswith(('player briefing', 'approach')):
        return 'approach', None
    return 'core', None


class Adventure:
    def __init__(self, module_text, run_data):
        self.module_text = module_text
        self.sections = split_sections(module_text)
        self.rooms = {}
        for room in run_data.get('rooms') or []:
            number = room.get('roomNumber')
            if isinstance(number, int):
                self.rooms[number] = room
        for section in self.sections:
            section['kind'], section['key'] = classify(section)
        self.area_sections = {s['key']: s for s in self.sections if s['kind'] == 'area' and s['key'] in self.rooms}
        self.focused = bool(self.rooms) and set(self.rooms) <= set(self.area_sections)
        self.stat_sections = {s['key']: s for s in self.sections if s['kind'] == 'stat'}
        self.stat_aliases = {}
        for name in self.stat_sections:
            for alias in (name, re.split(r',|\s+the\s+', name)[0]):
                self.stat_aliases.setdefault(phrase(alias), set()).add(name)
        # Only unambiguous shortened creature names are usable.
        self.stat_aliases = {alias: next(iter(names)) for alias, names in self.stat_aliases.items()
                             if len(names) == 1}
        self.topics = []
        generic = {'encounter', 'space', 'lore and dm notes', 'treasure', 'exits', 'dials', 'trap'}
        for number, section in self.area_sections.items():
            paragraphs = re.split(r'\n\s*\n', section['text'])
            for paragraph in paragraphs:
                # Named definitions, such as THE PROMPT-BOOK (...) or **Iron key.**.
                labels = re.findall(r'\b[A-Z][A-Z\u2019\'-]*(?: [A-Z][A-Z\u2019\'-]*){0,5}(?=\s*[:(])', paragraph)
                labels += re.findall(r'\*\*([^*]+)\*\*', paragraph)
                for label in labels:
                    alias = phrase(label)
                    if len(alias) >= 4 and alias not in generic:
                        self.topics.append((alias, number, paragraph))
            for item in self.rooms[number].get('treasure') or []:
                alias = phrase(re.split(r'[(:]', str(item))[0])
                if len(alias) >= 4 and not any(a == alias and n == number for a, n, _ in self.topics):
                    for paragraph in paragraphs:
                        if mentions(paragraph, alias):
                            self.topics.append((alias, number, paragraph))

    def area_name(self, number):
        section = self.area_sections.get(number)
        title = section['title'] if section else f'Area {number}'
        return re.sub(r'\s*\*\(.*\)\*\s*$', '', title).strip()

    def locations(self):
        return [{'value': None, 'label': 'Approach (not yet at the site)'}] + [
            {'value': number, 'label': self.area_name(number)} for number in sorted(self.rooms)]

    def valid(self, location):
        return location is None or location in self.rooms

    def retrieve(self, queries):
        """Resolve named subjects before generation; follow their explicit references once.

        This deliberately does not crawl every exit of every retrieved room.
        The returned reasons are also used in the Pilot's exact context preview.
        """
        areas, stats = {}, {}
        for source, query in queries:
            if not query.strip():
                continue
            direct = set(area_references(query)) & self.rooms.keys()
            for number in self.rooms:
                name = self.area_name(number).partition(':')[2].strip()
                if name and mentions(query, phrase(name)):
                    direct.add(number)
            for number in sorted(direct):
                areas.setdefault(number, f'named in {source}')
                for neighbor in self.rooms[number].get('connectsTo') or []:
                    if neighbor in self.rooms and neighbor != number:
                        areas.setdefault(neighbor, f'connected to Area {number}, named in {source}')
            for alias, name in self.stat_aliases.items():
                if mentions(query, alias):
                    stats.setdefault(name, f'named in {source}')
            for alias, number, paragraph in self.topics:
                if not mentions(query, alias):
                    continue
                areas.setdefault(number, f'{alias} referenced in {source}')
                for referenced in area_references(paragraph):
                    if referenced in self.rooms:
                        areas.setdefault(referenced, f'referenced by {alias} in Area {number} ({source})')
                for creature_alias, name in self.stat_aliases.items():
                    if mentions(paragraph, creature_alias):
                        stats.setdefault(name, f'referenced by {alias} in Area {number} ({source})')
        return areas, stats

    def assemble(self, location, queries=()):
        """Return the module text to send and a report of what was included and why."""
        if not self.focused:
            return self.module_text, {'mode': 'full', 'location': location, 'included': [], 'excluded': []}
        if location is None:
            current = []
            horizon = sorted(n for n, room in self.rooms.items() if room.get('beat') == 'entrance') or sorted(self.rooms)[:1]
        else:
            current = [location]
            horizon = [n for n in self.rooms[location].get('connectsTo') or [] if n in self.rooms and n != location]
        retrieved, requested_stats = self.retrieve(queries)
        creatures = {}
        for number in dict.fromkeys(current + horizon + list(retrieved)):
            for monster in (self.rooms[number].get('encounter') or {}).get('monsters') or []:
                creatures.setdefault(stat_name(monster), number)
        reasons = {}
        for section in self.sections:
            kind, key = section['kind'], section['key']
            if kind == 'core':
                reasons[id(section)] = 'core'
            elif kind == 'approach' and location is None:
                reasons[id(section)] = 'approach'
            elif kind == 'area' and key in current:
                reasons[id(section)] = 'current area'
            elif kind == 'area' and key in horizon:
                reasons[id(section)] = 'connected area'
            elif kind == 'area' and key in retrieved:
                reasons[id(section)] = retrieved[key]
            elif kind == 'stat' and key in requested_stats:
                reasons[id(section)] = requested_stats[key]
            elif kind == 'stat' and key in creatures:
                reasons[id(section)] = f'appears in {self.area_name(creatures[key]).split(":")[0]}'
        # Core first and in authored order keeps the cacheable prefix stable; focus follows.
        core = [s for s in self.sections if reasons.get(id(s)) == 'core']
        focus = [s for s in self.sections if id(s) in reasons and reasons[id(s)] != 'core']
        text = ''.join(s['text'] for s in core)
        if focus:
            label = self.area_name(location) if location is not None else 'Approach'
            text += ('\n\n# Current focus\n\nTracked party location: ' + label + '.\n'
                     'Additional sections are reference material, not evidence that the party has moved '
                     'or discovered their contents. Resolve declared actions using the transcript.\n\n'
                     + ''.join(s['text'] for s in focus))
        report = {
            'mode': 'focused',
            'location': location,
            'locationLabel': self.area_name(location) if location is not None else 'Approach',
            'included': [{'title': s['title'] or 'Introduction', 'reason': reasons[id(s)], 'chars': len(s['text'])}
                         for s in core + focus],
            'excluded': [s['title'] for s in self.sections if id(s) not in reasons],
        }
        return text, report

    def marker_instructions(self):
        if not self.focused:
            return ''
        areas = '; '.join(self.area_name(number) for number in sorted(self.rooms))
        return ('\n\nLocation tracking: end every reply with one final line of the form [Location: Area N], '
                'naming where the party is when your narration ends, or [Location: Approach] if they have not '
                'yet entered the site. TableForge removes this line before players see it. Areas: ' + areas + '.')


def load(data_dir, cartridge_id, resources):
    archive_path = Path(data_dir) / 'cartridges' / (cartridge_id + '.zip')
    module_name, run_name = resources.get('module.md'), resources.get('run-data.json')
    if not module_name:
        raise ValueError('Cartridge is missing module.md')
    if not archive_path.is_file():
        raise ValueError('Locate the cartridge for this save')
    with zipfile.ZipFile(archive_path) as archive:
        module_text = archive.read(module_name).decode('utf-8')
        try:
            run_data = json.loads(archive.read(run_name).decode('utf-8')) if run_name else {}
        except (KeyError, ValueError):
            run_data = {}
    return Adventure(module_text, run_data if isinstance(run_data, dict) else {})


def take_marker(text):
    """Strip location markers from AI-DM text; return the clean text and the last location named."""
    found = MARKER.findall(text)
    clean = MARKER.sub('', text).rstrip()
    if not found:
        return clean, False, None
    label, number = found[-1]
    return clean, True, (int(number) if number else None)
