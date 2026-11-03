# AI-DM Knowledge Base — Working Notes (2026-11-03)

Status: idea / not started. Not an agreed design decision yet.

## Question

Can the AI-DM keep its own notes on the server instead of having everything
re-sent in the prompt each turn?

## What the code does today

- The AI-DM has no scratchpad and no general way to write to the server. Every
  request is rebuilt from the SQLite save (`ai.py`: `build_context`, `chat_messages`).
- The only structured output the server reads from DM replies and saves:
  - location markers (`module_context.take_marker` → `set_location` in `server.py`)
  - `tableforge-choices` blocks (`narration_choices.extract`)
  - the combat/initiative signal
- Memory between turns:
  - **Rolling summary** (`SUMMARY_PROMPT`, `build_summary_context`): the server has
    the AI fold older transcript into a cumulative summary. The DM can't add to it directly.
  - **Checkpoints**: written by people.
  - **Party notes** (NPCs / Locations / World Notes; `party_notes` table, `save_note`
    in `server.py`): written by people, and **never sent to the AI-DM**.
- Each turn re-sends:
  - the narration prompt
  - module text near the current location (capped)
  - up to 60k characters of companion files
  - the summary and run-data
  - the recent transcript
- Caching: usage is recorded in `ai_usage`, including cached tokens. Location-dependent
  module text comes early in the system prompt, so the cached (discounted) portion
  of the prompt is probably short. Moving the parts that never change to the
  front may lower cost.

## Idea

Work like a personal knowledge base (github.com/dpill83/personal-knowledge-base):
the AI looks things up when it needs them and updates them when told. Example:
Ted's character backstory.

## Proposed plan (smallest first)

1. **DM reads party notes.** Send the relevant notes to the AI-DM, picked the same
   way module text is picked. Don't send every note every turn.
2. **DM proposes updates, a Pilot approves them.** The DM suggests a note update
   (a fenced block, like the choices block), and a Pilot accepts or edits it. Also
   allow "remember that…" via Ask AI-DM. No silent AI edits (AGENTS.md principle 9).
3. **Later: player-profile knowledge.** Character backstories that carry across
   adventures belong on the player profile, not per save.

Spoiler rule: notes players can see stay spoiler-free. Any private DM notes are
visible only in Pilot Mode, never in the normal reference sidebar.

## Token measurement (not done yet)

The KILO database at `/var/lib/tableforge/tableforge.sqlite3` is empty
(0 saves, messages and requests). Next, check whether KILO stores data elsewhere:

```
sudo grep TABLEFORGE_DATA /etc/tableforge/tableforge.env; sudo find / -name tableforge.sqlite3 -not -path '*/proc/*' 2>/dev/null
```

Otherwise run this on whichever machine has the play data (probably the old Windows install):

```
sqlite3 -header -column tableforge.sqlite3 "select purpose, count(*) n, round(avg(input_tokens)) avg_in, round(avg(cached_tokens)) avg_cached, round(avg(output_tokens)) avg_out, round(sum(estimated_cost_usd),3) cost from ai_usage group by purpose;"
```

## Next action

Start step 1. It doesn't depend on the measurement.
