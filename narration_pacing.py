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

# Conservative safeguard for explicit, standalone player prompts. General
# questions in NPC dialogue and rhetorical questions are not decision boundaries.
# The model prompt above, not this narrow parser, handles more subtle cases.
DECISION_LINE = re.compile(
    r'(?:what (?:do|will) (?:each of )?you (?:do|say|say or ask|try)'
    r'|how do (?:each of )?you (?:respond|react)'
    r'|what (?:is|will be) your next move'
    r'|do you (?:accept|agree to) [^?]+)\?', re.IGNORECASE,
)


def validate_public_narration(prose):
    """Reject clear decision-then-more-story replies before they're published.

    Call only after choice, combat, and location metadata have been removed.
    The rejection is recoverable: no message or beat is saved, so Pilot may retry.
    """
    lines = prose.strip().splitlines()
    for index, line in enumerate(lines):
        prompt = DECISION_LINE.match(line.strip())
        if prompt and (line.strip()[prompt.end():].strip()
                       or any(next_line.strip() for next_line in lines[index + 1:])):
            raise ValueError(
                'The AI-DM continued narrating after asking players to act. '
                'No narration was published. Retry the beat or review its context in Pilot Mode.'
            )
