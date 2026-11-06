"""Regression tests for the first Myrrdale narration and saved opening progress."""
import json
import sqlite3
import tempfile
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest.mock import patch

import ai
import combat
import module_context
import opening_flow
import server
import test_flow


MODULE = '''# The Second Cause
## Running notes
Play the road and patron before the mine.
## Hook
### Road scene — DM setup
Outside Myrrdale, the party sees a quarry wagon wobble at a stone culvert.
Let the players place themselves and decide whether to intervene.
### Patron FAQ
Alicia can explain who needs help.
### DM Secrets — never read aloud
The patron is concealing the insurance dispute.
## Site flow
FUTURE SITE FLOW MUST BE WITHHELD
## Player Briefing
> Alicia offers a hundred gold to investigate Hollowfells Mine.
## Approach & arrival
LATER: The half-hour climb reaches a low timbered adit breathing yellow dust.
## Areas
### Area 1 — Intake Cut
LATER: The mine contains a hidden tally board and sealed tin.
'''
RUN_DATA = {
    'schemaVersion': 1, 'adventureName': 'The Second Cause',
    'party': [{'name': 'Caravaggio', 'race': 'Tortle'},
              {'name': 'Sharghruuk', 'race': 'Half-Orc'}],
    'hook': {'dmSecrets': 'A wagon swerves in the Myrrdale lane.',
             'playerBriefing': 'Alicia offers a hundred gold to investigate Hollowfells Mine.'},
    'villain': {'name': 'A secret underwriter', 'weakness': 'FUTURE SPOILER'},
    'rooms': [{'roomNumber': 1, 'beat': 'entrance', 'connectsTo': [],
               'boxedText': 'Inside the mine is a hidden tally board.'}],
}
SKIPPED_OPENING = '''As you traverse the gravel cart track leading toward Hollowfells Mine, the sun hangs high.

Caravaggio walks alongside Sharghruuk and recalls the wagon incident from the previous day.
Sharghruuk reminisces about a journey from Chult.

At the mine, Alicia calls, “If the hill starts coughing twice, get clear of the mouth!”

With the mine looming before you, what do the two of you do?

[Opening: hook]
[Location: Approach]'''


class OpeningContextTest(unittest.TestCase):
    def setUp(self):
        self.adventure = module_context.Adventure(MODULE, RUN_DATA)

    def test_focused_opening_excludes_future_travel_rooms_and_secrets(self):
        first, report = self.adventure.opening_assemble('establishing')
        self.assertIn('quarry wagon', first)
        self.assertNotIn('hundred gold', first)
        self.assertNotIn('low timbered adit', first)
        self.assertNotIn('hidden tally board', first)
        self.assertNotIn('FUTURE SITE FLOW', first)
        self.assertEqual(report['openingStage'], 'establishing')
        self.assertNotIn('villain', self.adventure.opening_data('establishing'))
        self.assertNotIn('rooms', self.adventure.opening_data('establishing'))
        self.assertNotIn('playerBriefing', self.adventure.opening_data('establishing')['hook'])

        hook, _ = self.adventure.opening_assemble('hook')
        self.assertIn('hundred gold', hook)
        self.assertNotIn('low timbered adit', hook)
        self.assertNotIn('hidden tally board', hook)
        travel, _ = self.adventure.opening_assemble('travel')
        self.assertIn('low timbered adit', travel)
        self.assertNotIn('hidden tally board', travel)
        arrival, _ = self.adventure.opening_assemble('arrival')
        self.assertIn('hidden tally board', arrival)
        self.assertEqual(self.adventure.opening_data('arrival')['rooms'][0]['roomNumber'], 1)

    def test_bad_or_skipped_stage_markers_fail_and_do_not_leak_to_public_text(self):
        for candidate in ('[Opening: unknown]', '[Opening: travel]',
                          '[Opening: hook]\n[Opening: travel]'):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                opening_flow.prepare('Where are you today?\n' + candidate, 'establishing', first=True)
        with self.assertRaisesRegex(ValueError, 'omitted its opening-stage marker'):
            opening_flow.prepare('Where are you today?', 'establishing', first=True,
                                 require_opening_contract=True)
        with self.assertRaisesRegex(ValueError, 'continued the opening'):
            opening_flow.prepare('Where are you today?\nThe party then arrives at the mine.\n[Opening: hook]',
                                 'establishing', first=True, require_opening_contract=True)
        clean, stage = opening_flow.prepare('Where are you today?\n\n[Opening: hook]',
                                            'establishing', first=True, require_opening_contract=True)
        self.assertEqual(clean, 'Where are you today?')
        self.assertEqual(stage, 'hook')

    def test_establishing_accepts_natural_location_questions_without_accepting_job_offers(self):
        for question in (
            'Where do we find each of your characters this morning?',
            'Where are your characters as the sun rises?',
            'What are your characters doing when the day begins?',
            'Who is traveling alongside you as the scene opens?',
            'How would you like to begin the morning?',
        ):
            with self.subTest(question=question):
                clean, stage = opening_flow.prepare(
                    'A quiet lane stretches before you.\n\n' + question + '\n[Opening: hook]',
                    'establishing', first=True, require_opening_contract=True)
                self.assertIn(question, clean)
                self.assertEqual(stage, 'hook')
        for question in ('Do you accept the job?', 'Where is Hollowfells Mine?',
                         'What do you do about the runaway wagon?'):
            with self.subTest(question=question), self.assertRaisesRegex(
                    ValueError, 'skipped character establishment'):
                opening_flow.prepare(question + '\n[Opening: hook]', 'establishing',
                                     first=True, require_opening_contract=True)


class OpeningMigrationTest(unittest.TestCase):
    def test_existing_playthrough_is_not_reclassified_as_a_new_opening(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'DATA', Path(folder)):
            with sqlite3.connect(Path(folder) / 'tableforge.sqlite3') as conn:
                conn.executescript('''
                    CREATE TABLE cartridges (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                        source TEXT NOT NULL, resources TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE saves (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        cartridge_id TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'normal',
                        beat INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL);
                    INSERT INTO cartridges VALUES ('cartridge','Test','zip','{}','then');
                    INSERT INTO saves VALUES ('active','Test','cartridge','normal',3,'then','then');
                    INSERT INTO saves VALUES ('untouched','Test','cartridge','normal',1,'then','then');
                ''')
            server.initialize()
            with server.db() as conn:
                stages = dict(conn.execute('SELECT id,opening_stage FROM saves'))
            self.assertEqual(stages, {'active': 'exploration', 'untouched': 'exploration'})


class OpeningFlowTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    cartridge_zip = test_flow.FlowTest.cartridge_zip
    override = test_flow.FlowTest.override

    def new_save(self):
        cartridge = self.cartridge_zip({
            'manifest.json': json.dumps({'format': 'tableforge-adventure', 'formatVersion': 1,
                                         'title': 'The Second Cause', 'resources': {}}),
            'module.md': MODULE, 'run-data.json': json.dumps(RUN_DATA),
            'continuity.json': json.dumps({'completedAdventures': ['The Second Cause'],
                                           'openThreads': ['FUTURE THREAD']}),
        })
        return self.api('/api/saves', {'cartridgeId': cartridge['id'], 'players': [
            {'name': 'Dan', 'character': 'Caravaggio'},
            {'name': 'Dani', 'character': 'Sharghruuk'}]})

    def advance(self, save_id, text):
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(text)):
            return self.api(f'/api/saves/{save_id}/advance', self.override(save_id))

    def fail_advance(self, save_id, text):
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(text)):
            return self.api_error(f'/api/saves/{save_id}/advance', self.override(save_id))

    def test_first_request_has_no_future_scene_or_precompleted_continuity(self):
        state = self.new_save()
        self.assertEqual(state['save']['opening_stage'], 'establishing')
        context = self.api(f'/api/saves/{state["save"]["id"]}/context')
        system = context['messages'][0]['content']
        self.assertIn('quarry wagon', system)
        self.assertIn('TableForge authoritative opening state: establishing', system)
        self.assertNotIn('low timbered adit', system)
        self.assertNotIn('hidden tally board', system)
        self.assertNotIn('FUTURE SPOILER', system)
        self.assertNotIn('FUTURE THREAD', system)
        self.assertNotIn('continuity.json (authored reference', system)
        self.assertIn('continuity.json', context['report']['opening']['withheldCompanionFiles'])

    def test_hook_can_continue_with_npc_reaction_before_any_job_offer(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        self.advance(save_id, 'Where do we find your characters?\n[Opening: hook]')
        self.api(f'/api/saves/{save_id}/messages', {
            'playerId': player, 'text': 'I help Alicia clear the wagon. What did she see?'})
        response = ('Alicia steadies herself and looks at the wedged wheel. '
                    '"The brake fell just as the axle hit," she says. '
                    '"Is either of you hurt?"\n[Opening: hook]')
        result = self.advance(save_id, response)
        self.assertEqual(result['save']['opening_stage'], 'hook')
        self.assertEqual(result['messages'][-1]['body'], response.split('\n[Opening:')[0])
        system = self.api(f'/api/saves/{save_id}/context')['messages'][0]['content']
        self.assertIn('an offer is not a required ending', system.lower())
        self.assertIn('Stages are permissions'.lower(), system.lower())
        self.assertIn('The current player actions and questions lead the scene', system)

    def test_actual_skipped_opening_is_rejected_before_saving_or_changing_location(self):
        state = self.new_save()
        save_id = state['save']['id']
        failed = self.fail_advance(save_id, SKIPPED_OPENING)
        self.assertIn('skipped character establishment', failed['error'])
        unchanged = self.api(f'/api/saves/{save_id}')
        self.assertEqual(unchanged['save']['beat'], 1)
        self.assertEqual(unchanged['save']['opening_stage'], 'establishing')
        self.assertEqual(unchanged['messages'], [])

    def test_stage_progress_survives_restart_and_ready_cannot_accept_a_job(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        establishing = ('The lane is quiet for the moment. Caravaggio and Sharghruuk, '
                        'where are you as the morning begins, and what are you doing?'
                        '\n[Opening: hook]\n[Location: Approach]')
        result = self.advance(save_id, establishing)
        self.assertEqual(result['save']['opening_stage'], 'hook')
        self.assertNotIn('[Opening:', result['messages'][-1]['body'])
        server.initialize()
        self.assertEqual(self.api(f'/api/saves/{save_id}')['save']['opening_stage'], 'hook')
        self.assertIn('hundred gold', self.api(f'/api/saves/{save_id}/context')['messages'][0]['content'])

        offered = ('The wagon shudders to a halt after your warning. Alicia asks you '
                   'to investigate Hollowfells Mine. Do you accept the job?'
                   '\n[Opening: decision]\n[Location: Approach]')
        result = self.advance(save_id, offered)
        self.assertEqual(result['save']['opening_stage'], 'decision')
        self.assertNotIn('low timbered adit', self.api(f'/api/saves/{save_id}/context')['messages'][0]['content'])
        error = self.fail_advance(save_id, 'You accept and head to the mine.\n[Opening: travel]')
        self.assertIn('No player accepted', error['error'])
        self.assertEqual(self.api(f'/api/saves/{save_id}')['save']['opening_stage'], 'decision')

        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'I accept the job.'})
        result = self.advance(save_id, 'Alicia nods and prepares the cart.\n[Opening: travel]')
        self.assertEqual(result['save']['opening_stage'], 'travel')
        self.assertIn('low timbered adit', self.api(f'/api/saves/{save_id}/context')['messages'][0]['content'])
        result = self.advance(save_id, 'The cart reaches the hillside.\n[Opening: arrival]')
        self.assertEqual(result['save']['opening_stage'], 'arrival')
        error = self.fail_advance(save_id, 'You enter the mine.\n[Opening: exploration]\n[Location: Area 1]')
        self.assertIn('No player entered', error['error'])
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'I enter the mine.'})
        result = self.advance(save_id, 'You step into the intake cut.\n[Opening: exploration]\n[Location: Area 1]')
        self.assertEqual(result['save']['opening_stage'], 'exploration')
        self.assertEqual(result['save']['location'], 1)
        self.assertNotIn('authoritative opening state', self.api(
            f'/api/saves/{save_id}/context')['messages'][0]['content'])

    def test_declining_the_job_can_leave_the_scripted_opening(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        self.advance(save_id, 'Where are you this morning?\n[Opening: hook]')
        self.advance(save_id, 'Alicia offers the job. Do you accept?\n[Opening: decision]')
        self.api(f'/api/saves/{save_id}/messages', {
            'playerId': player, 'text': 'No thanks. I leave for the village instead.'})
        free = self.advance(save_id, 'You turn down the job. The road toward the village is open. '
                                   'What do you do?\n[Opening: exploration]\n[Location: Approach]')
        self.assertEqual(free['save']['opening_stage'], 'exploration')
        self.assertIsNone(free['save']['location'])
        self.assertNotIn('[Opening:', free['messages'][-1]['body'])

    def test_pilot_location_override_can_skip_the_scripted_opening(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        moved = self.api(f'/api/saves/{save_id}/location', {'playerId': player, 'location': 1})
        self.assertEqual(moved['save']['opening_stage'], 'exploration')
        self.assertEqual(moved['save']['location'], 1)
        self.assertIn('hidden tally board', self.api(
            f'/api/saves/{save_id}/context')['messages'][0]['content'])

    def arrival_combat(self):
        state = self.new_save()
        save_id, player = state['save']['id'], state['players'][0]['id']
        self.advance(save_id, 'Where do we find each of your characters this morning?\n[Opening: hook]')
        self.advance(save_id, 'Alicia offers the job. Do you accept?\n[Opening: decision]')
        self.api(f'/api/saves/{save_id}/messages', {'playerId': player, 'text': 'We accept the job.'})
        self.advance(save_id, 'Alicia gives you directions.\n[Opening: travel]')
        self.advance(save_id, 'The path reaches the mine.\n[Opening: arrival]')
        fighting = self.advance(save_id, 'Two guards rush out. Roll initiative.\n'
                                '[Opening: arrival]\n' + combat.MARKER)
        self.assertEqual(fighting['save']['opening_stage'], 'arrival')
        self.assertEqual(fighting['save']['mode'], 'combat')
        for participant in fighting['players']:
            fighting = self.api(f'/api/saves/{save_id}/ready', {
                'playerId': participant['id'], 'ready': True,
                'handoffId': fighting['combat']['id']})
        return save_id, fighting

    def test_combat_outcome_is_player_input_for_arrival_to_exploration(self):
        save_id, fighting = self.arrival_combat()
        report = 'We defeat the guards and fight our way inside Area 1.'
        provider = test_flow.FakeProvider(
            'You stand in the intake cut, with the guards behind you.\n'
            '[Opening: exploration]\n[Location: Area 1]')
        with patch.object(ai, 'current_provider', return_value=provider):
            try:
                result = self.api(f'/api/saves/{save_id}/combat-outcome', {
                    'handoffId': fighting['combat']['id'], 'requestId': str(uuid.uuid4()),
                    'playerId': fighting['players'][0]['id'], 'text': report})
            except urllib.error.HTTPError as error:
                self.fail(error.read().decode())
        self.assertEqual(result['save']['opening_stage'], 'exploration')
        self.assertEqual(result['save']['location'], 1)
        self.assertEqual(result['combat']['phase'], 'complete')
        self.assertIn(report, ai.chat_messages(provider.context)[0]['content'])
        self.assertNotIn('There are no new player contributions this beat',
                         ai.chat_messages(provider.context)[0]['content'])

    def test_skipped_combat_report_cannot_authorize_site_entry(self):
        save_id, fighting = self.arrival_combat()
        payload = {'handoffId': fighting['combat']['id'], 'requestId': str(uuid.uuid4()),
                   'playerId': fighting['players'][0]['id'], 'skip': True}
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(
                'You step into the mine.\n[Opening: exploration]\n[Location: Area 1]')):
            error = self.api_error(f'/api/saves/{save_id}/combat-outcome', payload)
        self.assertIn('No player entered the site', error['error'])
        unchanged = self.api(f'/api/saves/{save_id}')
        self.assertEqual(unchanged['save']['opening_stage'], 'arrival')
        self.assertIsNone(unchanged['save']['location'])
        self.assertEqual(unchanged['combat']['phase'], 'failed')
        provider = test_flow.FakeProvider('The mine entrance is quiet. What do you do?\n[Opening: arrival]')
        with patch.object(ai, 'current_provider', return_value=provider):
            retried = self.api(f'/api/saves/{save_id}/combat-retry', payload)
        self.assertEqual(retried['save']['opening_stage'], 'arrival')
        self.assertEqual(retried['combat']['phase'], 'complete')
        self.assertIn('There are no new player contributions this beat',
                      ai.chat_messages(provider.context)[0]['content'])


if __name__ == '__main__':
    unittest.main()
