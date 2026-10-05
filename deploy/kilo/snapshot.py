#!/usr/bin/python3
"""Consistent pre-start DB backup, running as the application user, outside Git."""
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def main():
    data = Path(os.environ['TABLEFORGE_DATA']).resolve()
    if data != Path('/var/lib/tableforge'):
        raise SystemExit('Unexpected production data path; refusing to start')
    database = data / 'tableforge.sqlite3'
    if not database.exists():
        return
    folder = data / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    target = folder / f'tableforge-{stamp}-before-start-{uuid.uuid4().hex[:8]}.sqlite3'
    with sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True) as source:
        with sqlite3.connect(target) as destination:
            source.backup(destination)
            if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('Pre-start backup failed integrity check')
    print(f'Pre-start database backup: {target.name}', flush=True)


if __name__ == '__main__':
    main()
