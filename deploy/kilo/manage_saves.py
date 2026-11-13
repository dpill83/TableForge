#!/usr/bin/env python3
"""Offline, SSH-only playthrough maintenance. Uses only Python's standard library."""
import argparse
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


SAVE_TABLES = {
    'players', 'player_portraits', 'messages', 'chat_images', 'pilot_messages',
    'sessions', 'session_events', 'checkpoints', 'summaries', 'ai_usage',
    'ai_requests', 'party_notes', 'revealed_assets', 'scene_images', 'combat_handoffs',
    'map_tokens',
}


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def require_stopped():
    result = subprocess.run(
        ['systemctl', 'show', 'tableforge.service', '--property=LoadState',
         '--property=ActiveState'], capture_output=True, text=True, check=True)
    properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if properties.get('LoadState') != 'loaded' or properties.get('ActiveState') not in ('inactive', 'failed'):
        raise RuntimeError('Stop TableForge first: sudo systemctl stop tableforge.service')


def connect(path):
    # mode=rw prevents a typo from creating an empty database.
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def save_tables(db):
    tables = []
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        name = row[0]
        columns = {column[1] for column in db.execute(f'PRAGMA table_info({quote(name)})')}
        if 'save_id' in columns:
            if name not in SAVE_TABLES:
                raise RuntimeError(f'Unrecognized save table {name}; update this tool before deleting.')
            tables.append(name)
    return tables


def backup(db, path):
    folder = path.parent / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    target = folder / f'before-maintenance-{stamp}-{uuid4().hex[:8]}.sqlite3'
    with closing(sqlite3.connect(target)) as destination:
        db.backup(destination)
        if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup verification failed; no changes made.')
    return target


def change_save(db, path, save_id, *, name=None):
    """Back up, then rename or delete exactly one playthrough atomically."""
    if not db.execute('SELECT 1 FROM saves WHERE id=?', (save_id,)).fetchone():
        raise ValueError('Save no longer exists.')
    if name is not None:
        name = name.strip()
        if not name or len(name) > 200:
            raise ValueError('Use a name of 1 to 200 characters.')
    tables = save_tables(db) if name is None else []
    if db.execute('PRAGMA foreign_key_check').fetchone():
        raise RuntimeError('Database has broken relationships; no changes made.')
    target = backup(db, path)
    print(f'Backup: {target}')
    with db:
        db.execute('BEGIN IMMEDIATE')
        if name is not None:
            db.execute('UPDATE saves SET name=?, updated_at=? WHERE id=?',
                       (name, datetime.now(timezone.utc).isoformat(), save_id))
        else:
            # Dependencies include cycles/self references; validate at commit.
            db.execute('PRAGMA defer_foreign_keys=ON')
            for table in tables:
                db.execute(f'DELETE FROM {quote(table)} WHERE save_id=?', (save_id,))
            db.execute('DELETE FROM saves WHERE id=?', (save_id,))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Relationship check failed; changes rolled back.')
    return target


def menu(db, path):
    while True:
        saves = db.execute(
            'SELECT s.id,s.name,s.updated_at,s.beat,c.title FROM saves s '
            'JOIN cartridges c ON c.id=s.cartridge_id ORDER BY s.updated_at DESC,s.id').fetchall()
        print('\nTableForge playthrough maintenance\n')
        for number, save in enumerate(saves, 1):
            print(f'{number}. {save["name"]} | {save["title"]} | beat {save["beat"]}')
            print(f'   {save["id"]} | updated {save["updated_at"]}')
        if not saves:
            print('No saved adventures.')
        choice = input('\nSelect a number, or Q to quit: ').strip()
        if choice.lower() == 'q':
            return
        if not choice.isdecimal() or not 1 <= int(choice) <= len(saves):
            print('Choose a listed number.')
            continue
        save = saves[int(choice) - 1]
        action = input(f'\n{save["name"]}: [R]ename, [D]elete, or Enter to go back: ').strip().lower()
        try:
            if action == 'r':
                name = input('New playthrough name (blank cancels): ').strip()
                if not name:
                    continue
                require_stopped()
                change_save(db, path, save['id'], name=name)
                print('Renamed.')
            elif action == 'd':
                print(f'Permanently delete playthrough {save["name"]!r} ({save["id"]})?')
                print('This removes its history, players, notes, images, and usage records.')
                print('The cartridge and other playthroughs stay available. A backup is created first.')
                if input('Type DELETE exactly to confirm (anything else cancels): ') != 'DELETE':
                    print('Cancelled.')
                    continue
                require_stopped()
                change_save(db, path, save['id'])
                print('Deleted.')
        except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
            print(f'Unable to complete operation: {error}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path,
                        default=Path('/var/lib/tableforge/tableforge.sqlite3'))
    args = parser.parse_args()
    try:
        require_stopped()
        with closing(connect(args.database)) as db:
            menu(db, args.database)
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled.')
    except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')
    finally:
        print('When finished, start TableForge: sudo systemctl start tableforge.service')


if __name__ == '__main__':
    main()
