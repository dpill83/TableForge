"""Whole-database backups of the memory card.

Backups copy the save database only. Cartridges stay in data/cartridges and are
never copied into a backup; a restored save still points at its cartridge by id
and asks to locate it if the package is missing.
"""
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATABASE = 'tableforge.sqlite3'
REQUIRED_TABLES = ('cartridges', 'saves', 'players', 'messages', 'sessions')
# Counted tables; missing ones (older backups) count as zero.
COUNTED = {'saves': 'saves', 'messages': 'messages', 'portraits': 'player_portraits',
           'images': 'scene_images', 'notes': 'party_notes'}
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.sqlite3$')


def directory(data):
    return Path(data) / 'backups'


def path_for(data, name):
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError('Choose a backup file from the list')
    folder = directory(data).resolve()
    path = (folder / name).resolve()
    if path.parent != folder or not path.is_file():
        raise ValueError('Backup not found')
    return path


def listing(data):
    folder = directory(data)
    if not folder.is_dir():
        return []
    items = []
    for path in folder.iterdir():
        if path.is_file() and NAME.match(path.name):
            stat = path.stat()
            items.append({'name': path.name, 'bytes': stat.st_size,
                          'modifiedAt': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
    return sorted(items, key=lambda item: item['modifiedAt'], reverse=True)


def inspect(data, path):
    """Open a database read-only and describe it; raises ValueError if it cannot be restored."""
    try:
        conn = sqlite3.connect(f'{Path(path).resolve().as_uri()}?mode=ro', uri=True)
    except sqlite3.Error as error:
        raise ValueError('This file is not a TableForge database') from error
    try:
        conn.row_factory = sqlite3.Row
        try:
            integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        except sqlite3.DatabaseError as error:
            raise ValueError('This file is not a TableForge database') from error
        if integrity != 'ok':
            raise ValueError(f'Backup failed its integrity check: {integrity}')
        tables = {row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [table for table in REQUIRED_TABLES if table not in tables]
        if missing:
            raise ValueError('This file is not a TableForge database (missing ' + ', '.join(missing) + ')')
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(saves)')}
        if 'format_version' in columns and conn.execute('SELECT 1 FROM saves WHERE format_version<>1').fetchone():
            raise ValueError('This backup contains a save format this TableForge cannot open')
        counts = {key: (conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] if table in tables else 0)
                  for key, table in COUNTED.items()}
        title = 'COALESCE(s.adventure_title,c.title)' if 'adventure_title' in columns else 'c.title'
        saves = [dict(row) for row in conn.execute(
            f'SELECT s.id,s.name,s.cartridge_id,s.updated_at,{title} AS title '
            'FROM saves s LEFT JOIN cartridges c ON c.id=s.cartridge_id ORDER BY s.updated_at DESC')]
    finally:
        conn.close()
    for save in saves:
        save['cartridgeAvailable'] = (Path(data) / 'cartridges' / (save['cartridge_id'] + '.zip')).is_file()
    return {'integrity': 'ok', 'counts': counts, 'saves': saves,
            'missingCartridges': sorted({s['cartridge_id'] for s in saves if not s['cartridgeAvailable']})}


def copy_database(source, target):
    """SQLite's online backup: a consistent copy even while the source is in use."""
    src = sqlite3.connect(source)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def create(data, label='manual'):
    """Snapshot the live database into data/backups and verify the copy before listing it."""
    folder = directory(data)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    name = f'tableforge-{stamp}-{label}.sqlite3'
    if (folder / name).exists():
        name = f'tableforge-{stamp}-{label}-{uuid.uuid4().hex[:6]}.sqlite3'
    temporary = folder / (name + '.tmp')
    try:
        copy_database(Path(data) / DATABASE, temporary)
        details = inspect(data, temporary)
        os.replace(temporary, folder / name)
    finally:
        temporary.unlink(missing_ok=True)
    return {'name': name, **details}


def restore(data, name):
    """Replace the live database with a verified backup, keeping a backup of the current one first."""
    path = path_for(data, name)
    expected = inspect(data, path)
    safety = create(data, 'before-restore')
    copy_database(path, Path(data) / DATABASE)
    return {'restored': name, 'safetyBackup': safety['name'], 'expected': expected}
