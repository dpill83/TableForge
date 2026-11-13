"""Shared table map: reveal-gated map choice and one party token per map."""
import json
import unittest

import ai
import server
import test_flow


class TableMapTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    cartridge_zip = test_flow.FlowTest.cartridge_zip

    def mapped_save(self):
        manifest = {'format': 'tableforge-adventure', 'formatVersion': 1, 'title': 'Mapped', 'resources': {},
                    'assets': [{'path': 'maps/upper.png', 'mediaType': 'image/png'},
                               {'path': 'maps/lower.png', 'mediaType': 'image/png'}]}
        cartridge = self.cartridge_zip({
            'manifest.json': json.dumps(manifest), 'module.md': '# Mapped',
            'run-data.json': json.dumps({'adventureName': 'Mapped'}),
            'maps/upper.png': b'\x89PNG\r\n\x1a\nupper', 'maps/lower.png': b'\x89PNG\r\n\x1a\nlower'})
        save = self.api('/api/saves', {'cartridgeId': cartridge['id'], 'name': 'Our game', 'players': [
            {'name': 'Dan', 'character': 'George'}, {'name': 'Dani', 'character': 'Ethereal'}]})
        save_id = save['save']['id']
        first, second = [p['id'] for p in save['players']]
        assets = self.api(f'/api/saves/{save_id}/assets?playerId={first}&pilot=true')['assets']
        upper, lower = (next(a['id'] for a in assets if a['path'] == f'maps/{name}.png') for name in ('upper', 'lower'))
        return save_id, first, second, upper, lower

    def reveal(self, save_id, player, asset_id):
        self.api(f'/api/saves/{save_id}/assets/{asset_id}/reveal', {'playerId': player, 'pilot': True})

    def test_any_player_shares_a_revealed_map_and_moves_its_token(self):
        save_id, first, second, upper, lower = self.mapped_save()
        path = f'/api/saves/{save_id}/table-map'
        self.assertEqual(self.api(f'/api/saves/{save_id}')['tableMap'], {'assetId': None, 'tokens': {}})
        # Unrevealed cartridge images cannot be shared or marked, even by a Pilot.
        for op in ({'op': 'select'}, {'op': 'move', 'x': 0.5, 'y': 0.5}):
            self.assertIn('revealed', self.api_error(path, {'playerId': first, 'assetId': upper, 'pilot': True, **op})['error'])
        self.reveal(save_id, first, upper)
        self.assertIn('player', self.api_error(path, {'playerId': 'stranger', 'assetId': upper, 'op': 'select'})['error'])

        # No Pilot Mode needed for an already revealed map.
        selected = self.api(path, {'playerId': second, 'assetId': upper, 'op': 'select'})
        self.assertEqual(selected['tableMap']['assetId'], upper)
        self.api(path, {'playerId': first, 'assetId': upper, 'op': 'select'})
        events = [e for e in self.api(f'/api/saves/{save_id}')['events'] if e['kind'] == 'table_map_selected']
        self.assertEqual([(e['player_id'], json.loads(e['body'])['assetId']) for e in events], [(second, upper)])

        for bad in ({'x': 1.5, 'y': 0.2}, {'x': -0.1, 'y': 0.2}, {'x': True, 'y': 0.2}, {'x': '0.5', 'y': 0.2}, {'x': 0.5}):
            self.assertIn('inside the map', self.api_error(path, {'playerId': first, 'assetId': upper, 'op': 'move', **bad})['error'])
        self.assertIn('Unknown', self.api_error(path, {'playerId': first, 'assetId': upper, 'op': 'erase'})['error'])

        before = self.api(f'/api/saves/{save_id}')
        moved = self.api(path, {'playerId': first, 'assetId': upper, 'op': 'move', 'x': 0.25, 'y': 0.75})
        self.assertEqual({k: moved['tableMap']['tokens'][upper][k] for k in ('x', 'y', 'movedBy')},
                         {'x': 0.25, 'y': 0.75, 'movedBy': first})
        # Polling clients notice the change; play state is untouched.
        self.assertNotEqual(moved['save']['updated_at'], before['save']['updated_at'])
        for key in ('messages', 'players', 'checkpoint'):
            self.assertEqual(moved[key], before[key])
        self.assertEqual(moved['save']['beat'], before['save']['beat'])

        # Last committed move wins and is attributed.
        later = self.api(path, {'playerId': second, 'assetId': upper, 'op': 'move', 'x': 1, 'y': 0})
        self.assertEqual({k: later['tableMap']['tokens'][upper][k] for k in ('x', 'y', 'movedBy')},
                         {'x': 1.0, 'y': 0.0, 'movedBy': second})

        # Each map keeps its own position; switching back restores the first.
        self.reveal(save_id, first, lower)
        self.api(path, {'playerId': first, 'assetId': lower, 'op': 'select'})
        both = self.api(path, {'playerId': first, 'assetId': lower, 'op': 'move', 'x': 0.5, 'y': 0.5})
        self.assertEqual(both['tableMap']['assetId'], lower)
        self.assertEqual((both['tableMap']['tokens'][upper]['x'], both['tableMap']['tokens'][lower]['x']), (1.0, 0.5))
        # A late move for the previous map stays on that map.
        late = self.api(path, {'playerId': second, 'assetId': upper, 'op': 'move', 'x': 0.1, 'y': 0.1})
        self.assertEqual((late['tableMap']['tokens'][upper]['x'], late['tableMap']['tokens'][lower]['x']), (0.1, 0.5))
        self.assertEqual(late['tableMap']['assetId'], lower)

        # A restart keeps the shared map and both positions.
        server.initialize()
        resumed = self.api(f'/api/saves/{save_id}')['tableMap']
        self.assertEqual(resumed, late['tableMap'])

        # Visual aid only: never part of the AI-DM's context.
        with server.LOCK, server.db() as conn:
            state = server.snapshot(conn, save_id)
            for purpose in ('advance', 'ask'):
                self.assertNotIn(lower, json.dumps(ai.build_context(state, server.DATA, purpose=purpose)))

    def test_token_moves_while_the_ai_dm_is_responding(self):
        save_id, first, _, upper, _ = self.mapped_save()
        self.reveal(save_id, first, upper)
        server.GENERATING[save_id] = True
        try:
            moved = self.api(f'/api/saves/{save_id}/table-map', {'playerId': first, 'assetId': upper, 'op': 'move', 'x': 0.4, 'y': 0.6})
        finally:
            server.GENERATING.pop(save_id, None)
        self.assertEqual(moved['tableMap']['tokens'][upper]['y'], 0.6)

    def test_deleting_a_save_removes_its_map_state(self):
        save_id, first, _, upper, _ = self.mapped_save()
        self.reveal(save_id, first, upper)
        path = f'/api/saves/{save_id}/table-map'
        self.api(path, {'playerId': first, 'assetId': upper, 'op': 'select'})
        self.api(path, {'playerId': first, 'assetId': upper, 'op': 'move', 'x': 0.5, 'y': 0.5})
        self.api(f'/api/saves/{save_id}/delete', {'confirmed': True, 'confirmation': 'DELETE', 'name': 'Our game'})
        with server.db() as conn:
            self.assertIsNone(conn.execute('SELECT 1 FROM map_tokens WHERE save_id=?', (save_id,)).fetchone())


if __name__ == '__main__':
    unittest.main()
