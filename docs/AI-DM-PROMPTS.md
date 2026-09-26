# AI-DM prompt integration

Stage 3 belongs to the **adventure cartridge**. AdventureForge's cartridge exporter
loads its current versioned Stage 3 prompt, copies the bytes unchanged into the ZIP,
and declares the file in the manifest. TableForge does not bundle a default Stage 3
source or require an AdventureForge checkout at runtime.

## Cartridge contract

```json
{
  "format": "tableforge-adventure",
  "formatVersion": 1,
  "title": "My adventure",
  "resources": {
    "module": "module.md",
    "runData": "run-data.json",
    "stage3Prompt": "stage3-run-prompt-v2.1.1.md"
  }
}
```

The example version is not hardcoded in TableForge. Newer adventures can carry
newer prompts without a TableForge release. The prompt must be full UTF-8 Markdown
with its `promptVersion` banner. TableForge records the version from the content.
The unversioned AdventureForge pointer file is not a runnable prompt.

An explicit `resources.stage3Prompt` binding is authoritative; nested paths work
like other resources. Without one, TableForge detects a single
`stage3-run-prompt.md` or `stage3-run-prompt-vX.Y.Z.md`. Multiple candidates require
an explicit binding or manual selection; TableForge does not guess which is latest.
The resource appears as `stage3-run-prompt.md` in the setup bindings. A missing or
invalid prompt blocks **new** saves, with the error shown during cartridge review.

AdventureForge uses `stage3PromptFilename()` and `STAGE3_PROMPT_VERSION` to select
its current source. Export fetches that file with cache revalidation, verifies its
version, includes it unchanged, and refuses export if it cannot be loaded. A stale
Stage 3 file dropped alongside Stage 2 files is not substituted for the current
source. Existing exported ZIPs do not update themselves: re-export to package a
newer source. Updating AdventureForge's normal version pointer is sufficient for
future exports; there is no separate TableForge Stage 3 version constant to update.

## TableForge integration

The console owns only the small versioned
[`tableforge-integration-v1.md`](../prompts/tableforge-integration-v1.md) adapter.
It precedes the complete cartridge prompt and explicitly overrides conflicting
runtime assumptions while preserving Stage 3's narration and pacing philosophy:

- Captain/Director means trusted players using Pilot Mode.
- Narration goes directly to the shared feed without relay opt-in, PLAYER_VIEW
  tags, Cartographer cues, secret footers, or continuity-file output. The existing
  server-stripped location marker remains supported.
- Opening uses saved character assignments and available run-data. It skips the
  version/party-sheet confirmation ritual, while preserving the establishing
  round, hook acceptance, travel/arrival, clock rules, and meaningful choices.
- Humans roll dice and run combat. Pilot controls and recorded combat outcomes
  govern resumption; the prompt adds no combat automation.
- Ready controls when generation happens. History comes from the save; the AI
  cannot assume private provider memory or access to absent optional resources.

Save creation makes no provider call. The first authorized advance sends an
explicit opening request, including existing player contributions. Later advances
continue the current situation instead of restarting the opening.

Narration receives selected module context, saved transcript/summary/checkpoint,
recent combat outcomes, and player/character assignments. Stage 3 saves also get
global run-data fields (party, hook, clock, source version), plus rooms/stat blocks
matching the existing module focus. Unstructured cartridges use full run-data with
the existing full-module fallback. Optional cast, scenes, and continuity files are
not newly wired into requests by this integration.

Ask AI-DM retains its separate operational prompt and existing module/table/Pilot
context. Summaries retain their history-only prompt. Neither receives Stage 3's
opening or public-narration instructions.

## Saves and existing adventures

At Begin Adventure, TableForge snapshots the selected cartridge prompt plus the
adapter into `narration_prompts`: exact effective instructions, source version,
integration version, source SHA-256, and effective SHA-256. Each save selects its
snapshot through `saves.narration_prompt_id` and preserves the cartridge resource
binding. Snapshots are deduplicated; old snapshots remain after explicit switches.
Whole-database backups include them. The cartridge stays read-only.

Existing saves keep their exact saved instructions, including saves created with
the former bundled Stage 3 source. Pre-integration saves retain `legacy-1`, the
original minimal narration prompt. Old cartridges without Stage 3 can still be
located and resumed with those snapshots; there is no silent prompt substitution.
Missing or corrupt **saved** instructions block narration with a recovery error.

**Pilot Mode → Review Context** identifies the saved version and displays the exact
next narration payload. If the mounted cartridge supplies different instructions,
it offers the full candidate for review and **Use cartridge instructions for this
save…**. The candidate may be newer or older; the table chooses explicitly.
Missing cartridge prompts produce an explanatory message while saved instructions
remain usable. This action cannot attach a different adventure to an existing save.

Switching requires an open session, a valid initiating player, Pilot confirmation,
and matching current/target hashes. Generation blocks a concurrent switch. The
save records the initiator and old/new identities in a `prompt_upgrade` event.
History, Ready, and beat state are preserved. Other saves keep their instructions.

To change console adaptations, add a new adapter version, update its version and
UTF-8/LF-normalized digest in `runtime_prompts.py`, and test compatibility with the
cartridge sources. A new adapter does not silently alter existing saves.

## Verification

Run `python -m unittest discover -s tests -v` in TableForge. AdventureForge's focused
export tests run with `node --test app/pages/test/tests.cartridge-stage3.node.mjs`.
The old v2.1.1 source under TableForge's `tests/fixtures/` is test input only; runtime
code never loads it. No provider call is needed to inspect or select instructions.
