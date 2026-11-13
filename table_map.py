"""Shared table map: which revealed cartridge image the table is looking at and
where the party token sits on each one. Visual aid only; never AI context.

Positions are normalized image coordinates (0..1 from the top-left corner), so
they do not depend on any viewer's zoom or screen size. Each map keeps its own
position. The last committed move wins.
"""
import json
import math


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS map_tokens (
        save_id TEXT NOT NULL, asset_id TEXT NOT NULL,
        x REAL NOT NULL, y REAL NOT NULL, moved_by TEXT, moved_at TEXT NOT NULL,
        PRIMARY KEY(save_id, asset_id),
        FOREIGN KEY(save_id) REFERENCES saves(id))''')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(saves)')}
    if 'table_map_asset_id' not in columns:
        # NULL: no shared map chosen yet. Older saves start that way.
        conn.execute('ALTER TABLE saves ADD COLUMN table_map_asset_id TEXT')


def _revealed(conn, save_id, asset_id):
    return isinstance(asset_id, str) and conn.execute(
        'SELECT 1 FROM revealed_assets WHERE save_id=? AND asset_id=?', (save_id, asset_id)).fetchone() is not None


def current(conn, save_id):
    """Player-safe map state: only revealed maps are ever referenced."""
    selected = conn.execute('SELECT table_map_asset_id FROM saves WHERE id=?', (save_id,)).fetchone()
    asset_id = selected['table_map_asset_id'] if selected else None
    tokens = {row['asset_id']: {'x': row['x'], 'y': row['y'], 'movedBy': row['moved_by'], 'movedAt': row['moved_at']}
              for row in conn.execute(
                  'SELECT m.* FROM map_tokens m JOIN revealed_assets r '
                  'ON r.save_id=m.save_id AND r.asset_id=m.asset_id WHERE m.save_id=?', (save_id,))}
    return {'assetId': asset_id if _revealed(conn, save_id, asset_id) else None, 'tokens': tokens}


def _coordinate(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Token position must be inside the map')
    return float(value)


def update(conn, save_id, player_id, session_id, payload, stamp):
    """Select the shared map or move its party token. Any player may do either."""
    asset_id = payload.get('assetId')
    if not _revealed(conn, save_id, asset_id):
        raise ValueError('Choose a map that has been revealed to the party')
    op = payload.get('op')
    if op == 'select':
        changed = conn.execute('UPDATE saves SET table_map_asset_id=? WHERE id=? AND '
                               'table_map_asset_id IS NOT ?', (asset_id, save_id, asset_id)).rowcount
        if changed and session_id:
            conn.execute('INSERT INTO session_events (save_id,session_id,player_id,kind,body,created_at) '
                         'VALUES (?,?,?,?,?,?)', (save_id, session_id, player_id, 'table_map_selected',
                                                  json.dumps({'assetId': asset_id}), stamp))
    elif op == 'move':
        # Moves name their map, so a move made just before someone switches maps
        # lands on the map it was made on, never on the newly selected one.
        x, y = _coordinate(payload.get('x')), _coordinate(payload.get('y'))
        conn.execute('''INSERT INTO map_tokens (save_id,asset_id,x,y,moved_by,moved_at) VALUES (?,?,?,?,?,?)
                        ON CONFLICT(save_id,asset_id) DO UPDATE SET
                        x=excluded.x,y=excluded.y,moved_by=excluded.moved_by,moved_at=excluded.moved_at''',
                     (save_id, asset_id, x, y, player_id, stamp))
    else:
        raise ValueError('Unknown table map action')
    conn.execute('UPDATE saves SET updated_at=? WHERE id=?', (stamp, save_id))
