"""The AI-DM must wait for player decisions before narrating their outcomes."""
import json
import unittest
from unittest.mock import patch

import ai
import narration_pacing
import server
import test_flow


MYRRDALE_FAILED_OPENING = '''As the sun rises over the foothills surrounding Myrrdale, Caravaggio walks downhill past a wagon crossing, while Sharghruuk approaches from the far verge, seeking paid work. The air is crisp, and the faint sound of chirping birds fills the morning stillness.

Suddenly, both characters notice the ground shudder as an empty quarry wagon lurches sideways. Its axle becomes lodged in the stone culvert lip, and the dropped iron brake shoe wedges beneath the rear wheel. In this very moment, Caravaggio has a clear view of the precarious situation with the axle, while Sharghruuk catches sight of the brake shoe just in time to react.

What do each of you do?

---

After a brief moment to gather themselves and react, the wagon indeed comes to a stop, barely avoiding disaster. Shaken but safe, the two witnesses find themselves sharing an understanding look. This moment is a catalyst for their destinies.

Standing nearby, a mud-spattered woman with an indigo thumbprint on her jaw, Alicia Cioffred, approaches. "You both saw what happened to that wagon," she says with urgency in her voice. "A warning came from Hollowfells Mine with three names on it, and none of those hands came home by the road. I need you both to find out where they are and stop whatever is sending the mine’s blows uphill. The mine pays a hundred gold to each of you now and three hundred more for a true report."

She gestures toward her cart, which awaits at the northern road. "You are welcome to ride along to Kingsbay when this is done."

What do you say or ask in response? Do you accept the job?'''


class PacingGuardTest(unittest.TestCase):
    def test_original_myrrdale_failure_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'continued narrating after asking players to act'):
            narration_pacing.validate_public_narration(MYRRDALE_FAILED_OPENING)

    def test_one_open_decision_is_allowed(self):
        original = MYRRDALE_FAILED_OPENING.split('\n\n---')[0]
        narration_pacing.validate_public_narration(original)

    def test_other_explicit_decision_phrases_are_guarded(self):
        for question in ('What do you do?', 'How do you respond?', 'What is your next move?',
                         'Do you accept the job?'):
            with self.subTest(question=question), self.assertRaises(ValueError):
                narration_pacing.validate_public_narration('The bridge is failing.\n\n' + question
                                                            + '\n\nYou save everyone and head to town.')

    def test_continuation_on_same_line_is_guarded(self):
        with self.assertRaises(ValueError):
            narration_pacing.validate_public_narration(
                'The wagon skids.\n\nWhat do you do? The crew immediately saves it.'
            )

    def test_followup_questions_are_allowed_on_same_or_separate_lines(self):
        for suffix in (
            ' Do you rush across or look for another route?',
            '\nDo you rush across or look for another route?',
            '\n\nDo you rush across? Or do you look for another route?',
            '\n\n- Rush across\n- Look for another route',
        ):
            with self.subTest(suffix=suffix):
                narration_pacing.validate_public_narration('The wagon skids.\n\nWhat do you do?' + suffix)

    def test_followup_questions_then_story_are_still_guarded(self):
        for suffix in (
            ' Do you rush across? The wagon then stops on its own.',
            '\nDo you rush across?\n\nThe wagon then stops on its own.',
        ):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                narration_pacing.validate_public_narration('The wagon skids.\n\nWhat do you do?' + suffix)

    def test_npc_dialogue_and_rhetorical_questions_are_not_boundaries(self):
        narration_pacing.validate_public_narration(
            'The guard asks, "What do you do?" and then lowers his lantern.\n\n'
            'The path is still open. How do you proceed?'
        )


class PacingFlowTest(unittest.TestCase):
    setUp = test_flow.FlowTest.setUp
    tearDown = test_flow.FlowTest.tearDown
    api = test_flow.FlowTest.api
    api_error = test_flow.FlowTest.api_error
    ready_save = test_flow.FlowTest.ready_save
    override = test_flow.FlowTest.override

    def test_bad_reply_keeps_open_beat_and_good_retry_can_publish(self):
        save_id = self.ready_save()
        before = self.api(f'/api/saves/{save_id}')
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(MYRRDALE_FAILED_OPENING)):
            error = self.api_error(f'/api/saves/{save_id}/advance', self.override(save_id))
        self.assertIn('No narration was published', error['error'])
        unchanged = self.api(f'/api/saves/{save_id}')
        self.assertEqual(unchanged['save']['beat'], before['save']['beat'])
        self.assertEqual(unchanged['messages'], before['messages'])
        self.assertEqual(unchanged['players'], before['players'])
        self.assertFalse(server.GENERATING)

        expected = MYRRDALE_FAILED_OPENING.split('\n\n---')[0]
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(expected)):
            result = self.api(f'/api/saves/{save_id}/advance', self.override(save_id))
        self.assertEqual(result['messages'][-1]['body'], expected)
        self.assertEqual(result['save']['beat'], before['save']['beat'] + 1)
        self.assertFalse(any(player['ready'] for player in result['players']))

    def test_choice_footer_does_not_count_as_story_after_decision(self):
        save_id = self.ready_save()
        player_id = self.api(f'/api/saves/{save_id}')['players'][0]['id']
        text = ('The wagon skids.\n\nWhat do you do?\n\n```tableforge-choices\n'
                + json.dumps({'groups': [{'playerId': player_id, 'options': ['I inspect the brake shoe.']}]})
                + '\n```')
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(text)):
            result = self.api(f'/api/saves/{save_id}/advance', self.override(save_id))
        self.assertIn('What do you do?', result['messages'][-1]['body'])
        self.assertIsNotNone(result['messages'][-1]['choices'])

    def test_social_scene_guidance_follows_cartridge_and_preserves_choices(self):
        save_id = self.ready_save('# A wagon crossing\nAlicia has work to offer.')
        context = self.api(f'/api/saves/{save_id}/context')
        system = context['messages'][0]['content']
        self.assertIn('TableForge organic roleplay contract', system)
        self.assertIn('The current player actions and questions lead the scene', system)
        self.assertIn('NOT a monologue or a checklist', system)
        self.assertIn('No mandatory number of dialogue beats', system)
        self.assertGreater(system.index('TableForge organic roleplay contract'),
                           system.index('Alicia has work to offer'))
        # The model still receives the existing optional A/B/C choice contract.
        self.assertIn('```tableforge-choices', system)
        self.assertIn('This does not change the optional A/B/C action-choice format', system)

    def test_followup_question_publishes_without_a_rejected_generation(self):
        save_id = self.ready_save()
        text = ('The quarry wagon skids sideways.\n\n'
                'What do you do? Do you rush to the axle or inspect the brake shoe?')
        with patch.object(ai, 'current_provider', return_value=test_flow.FakeProvider(text)):
            result = self.api(f'/api/saves/{save_id}/advance', self.override(save_id))
        self.assertEqual(result['messages'][-1]['body'], text)
        self.assertEqual(result['save']['beat'], 2)
