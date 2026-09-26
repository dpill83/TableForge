# AI-DM prompt integration

New saves use AdventureForge **Stage 3 v2.1.1** with **TableForge integration v1**.
The upstream source is bundled unchanged at
[`prompts/stage3-run-prompt-v2.1.1.md`](../prompts/stage3-run-prompt-v2.1.1.md).
It came from the local AdventureForge checkout at commit
`d2e42f4e88d91853ec5b7b2a1c2aeb200f729c5b`; both its unversioned pointer and
`STAGE3_PROMPT_VERSION` selected v2.1.1 when integrated. The supplied campaign's
v2.0.2 is older: v2.1.1 adds the relay contract, decisive resolution, and combined
parallel-action pacing. TableForge does not need an AdventureForge checkout at runtime.

## Effective narration instructions

[`tableforge-integration-v1.md`](../prompts/tableforge-integration-v1.md) precedes
the complete Stage 3 source and explicitly takes precedence where they conflict:

- Captain/Director becomes trusted players using Pilot Mode.
- Narration goes directly to the shared feed: no relay opt-in, PLAYER_VIEW tags,
  Cartographer cues, secret footers, or continuity-file output. The existing
  server-stripped location marker remains supported.
- The opening uses saved character assignments and available run-data details.
  It skips version/party-sheet confirmation rituals and does not demand missing
  statistics before they are needed. Establishing round, hook acceptance,
  travel/arrival, spoiler safety, clock rules, and meaningful choices remain.
- Humans roll dice and run combat. Existing Pilot combat/resume controls and
  recorded outcomes govern resumption; the prompt does not add combat automation.
- Ready controls generation timing. The save supplies durable history; the AI
  must not rely on private provider memory or claim to have read absent resources.

Creating a save does **not** make a provider call. Its first authorized advance
(all Ready or Pilot Ready Override) sends an explicit opening request, including
any contributions already sent. Subsequent advances continue the current situation,
including an unfinished opening. Ending/resuming a session does not restart play.

Narration receives the selected module context, saved transcript/summary/checkpoint,
recent combat outcomes, and saved player/character assignments. Stage 3 saves also
receive global run-data fields (including party, hook, clock, and source version),
plus rooms and stat blocks matching the existing module focus. An unstructured
cartridge uses full run-data with the existing full-module fallback. Optional cast,
scene, and continuity files are not newly wired into AI requests by this change.

**Ask AI-DM** retains its separate operational prompt and existing module/table/Pilot
context. It does not receive Stage 3's narration, opening, relay, or handoff contract.
The existing operational scope covers Pilot questions without producing a public
beat or altering Ready. **Summaries** retain their separate history-only prompt;
they receive neither Stage 3 nor the cartridge. This integration changes narration.

## Save persistence and upgrades

The database stores the exact effective instruction text, source version,
integration version, source SHA-256, and effective SHA-256 in `narration_prompts`.
Each save selects a snapshot through `saves.narration_prompt_id`. Shared snapshots
are stored once; previous snapshots remain after upgrades. Whole-database backups
include them automatically. Cartridge files and resource bindings are unchanged.

The one-time schema migration pins pre-existing saves to `legacy-1`: the exact
previous short narration instructions. Their existing request behavior stays in
place until explicitly upgraded. Startup never substitutes the latest default for
a saved prompt, including after a backup restore. Missing/corrupt saved instructions
block narration with a recovery error rather than selecting a different prompt.

To upgrade an existing save:

1. Join the save, start a session if needed, and enable **Pilot Mode**.
2. Open **Review Context**. The AI-DM instructions section identifies the current
   version. Expand the offered upgrade to inspect its full instructions.
3. Choose **Use these instructions for this save…** and confirm.

The server requires a valid initiating player, explicit Pilot confirmation, and
matching current/target hashes. It refuses upgrades during AI generation. The action
records the initiator and old/new prompt identities as a `prompt_upgrade` session
event. It changes future instructions only: no generation, transcript editing,
Ready reset, or opening restart. Other saves retain their versions.

Review Context displays the exact effective narration payload, including the saved
instructions. A missing bundled default prevents new saves/upgrades but does not
stop existing saves with intact snapshots from continuing.

## Updating the bundled default

1. Check AdventureForge's current version pointer and compare the new source with
   TableForge's workflow. Copy the versioned source unchanged into `prompts/`.
2. If adaptations change, add a new integration version rather than rewriting the
   existing versioned asset. Keep the upstream philosophy in the source.
3. Update `STAGE3_VERSION`, `INTEGRATION_VERSION`, and expected asset SHA-256 values
   in `runtime_prompts.py`. Hash decoded UTF-8 text with LF newlines, so Windows
   checkout line endings do not affect verification. Record provenance here.
4. Run `python -m unittest discover -s tests -v` and the JavaScript checks. Verify
   first narration, continuation, migration, explicit upgrade, and preview behavior.
5. New saves select the new default. Existing saves continue with their exact saved
   instructions until their table explicitly upgrades them.

The default loader checks both assets for integrity and never silently falls back
to the minimal prompt. No model call is needed to load, inspect, or upgrade prompts.
