"""Server-owned turn boundaries for public AI-DM narration.

This contract is sent independently of the saved Stage 3 prompt snapshot, so
existing playthroughs benefit without silently upgrading cartridge instructions.
"""
import re


INSTRUCTIONS = '''\n\nTableForge player-agency and turn-boundary contract (takes precedence over
conflicting opening sequences or adventure text):
- One AI-DM response is one playable beat, not an entire sequence of scenes.
- When you ask for a player action, answer, decision, or acceptance, END the
  public story there. Only required machine metadata may follow. Wait for the
  next authorized generation before narrating the result or introducing a new
  decision. Never ask what players do and then continue as though they answered.
- Do not invent player actions, reactions, consent, dialogue, or shared looks.
  Resolve only actions the players have supplied, or established consequences
  of the world acting independently. Ready without a message selects no option.
- Opening stages (establishing, hook, acceptance, travel, arrival) describe the
  order of future play, not tasks to finish in one response. Stop at the first
  meaningful player decision, even if more opening stages remain.
- Address multiple players together when appropriate, then wait for the normal
  Ready/Unready process. Do not invent an extra readiness confirmation.
'''

# Kept after cartridge/run-data references in the actual AI request so that an
# authored patron briefing cannot override how NPCs respond to live players.
# This is guidance, not a publication regex: judging social credibility from
# text patterns would reject valid scenes and waste paid model generations.
SOCIAL_SCENE_INSTRUCTIONS = '''\n\nTableForge organic roleplay contract (applies when people interact):
- The current player actions and questions lead the scene. First resolve what
  they did and answer what they asked, from the NPC's actual perspective and
  knowledge. Do not pivot directly from a rescue, greeting, or narrow question
  to a prepared adventure pitch just because the module contains one.
- NPCs have immediate concerns, reactions, motives, and limits. Convey these
  through a concrete detail or response, not a biography or obligatory small
  talk. Strangers do not become companions or jointly hired by default.
- Authored patron briefings, mysteries, payment, destinations, and transport
  arrangements are reference facts, NOT a monologue or a checklist to reveal
  as soon as the NPC appears. Share relevant details when players ask, show
  interest, encounter evidence, or when the NPC has a believable reason to
  volunteer them. Let the conversation breathe without stalling progress.
- No mandatory number of dialogue beats: urgent NPCs may make a direct offer
  when justified, and interested players can get the full terms immediately.
  Do not withhold answers, add filler, or force repeated introductions.
- If players distrust or challenge an NPC, show a credible reaction once and
  respond to their actual concern. Do not repeatedly apologize, re-sell the
  quest, or repeat all the same facts in subsequent turns.
- This does not change the optional A/B/C action-choice format or require a
  dialogue menu. Players remain free to speak and act however they choose.
'''

# Conservative safeguard for explicit, standalone player prompts. General
# questions in NPC dialogue and rhetorical questions are not decision boundaries.
# The model prompt above, not this narrow parser, handles more subtle cases.
DECISION_LINE = re.compile(
    r'(?:what (?:do|will) (?:each of )?you (?:do|say|say or ask|try)'
    r'|how do (?:each of )?you (?:respond|react)'
    r'|what (?:is|will be) your next move'
    r'|do you (?:accept|agree to) [^?]+)\?', re.IGNORECASE,
)
FOLLOWUP_QUESTION = re.compile(
    r'\s*(?:do|does|did|can|could|will|would|shall|should|is|are|was|were'
    r'|what|which|who|where|when|why|how|or)\b[^.!?]*\?', re.IGNORECASE,
)


def is_clarification(text):
    """Allow further questions or listed options without story progression.

    Ambiguous prose still fails the guard, but a question by itself never means
    the AI has chosen an answer for the players.
    """
    for line in text.splitlines():
        remaining = line.strip()
        if not remaining:
            continue
        if remaining.startswith(('- ', '* ')):
            continue
        while remaining:
            question = FOLLOWUP_QUESTION.match(remaining)
            if not question:
                return False
            remaining = remaining[question.end():].strip()
    return True


def validate_public_narration(prose):
    """Reject clear decision-then-more-story replies before they're published.

    Call only after choice, combat, and location metadata have been removed.
    The rejection is recoverable: no message or beat is saved, so Pilot may retry.
    """
    lines = prose.strip().splitlines()
    for index, line in enumerate(lines):
        prompt = DECISION_LINE.match(line.strip())
        if prompt and not is_clarification(
                '\n'.join([line.strip()[prompt.end():], *lines[index + 1:]])):
            raise ValueError(
                'The AI-DM continued narrating after asking players to act. '
                'No narration was published. Retry the beat or review its context in Pilot Mode.'
            )
