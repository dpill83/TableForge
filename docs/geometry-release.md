# Bidirectional geometry implementation and rollout

## Review groups

1. **Contract and map export:** geometry v1, skeleton schema v2, paired opening
   endpoints, room outlines/features, shared pillar placement and grid scale.
   See `cartridge-geometry.md` and its JSON fixture for the wire contract.
2. **Cartridge authoring:** Stage 2 v1.4.0, Stage 3 v2.3.0, module consistency
   validation, and export-time rejection of malformed new geometry. Earlier
   versioned prompts remain available. Existing cartridge source files are not
   rewritten or automatically enriched.
3. **TableForge consumption:** `cartridge_geometry.py`, import validation,
   focused context containing both connection endpoints, and console adapter v2.
   Existing saved prompt snapshots retain their instructions and identity.
4. **Arrival persistence:** nullable `saves.arrival_connection_id`, stripped
   location/arrival metadata, atomic publication with location, session events,
   and clearing on unknown movement or Pilot corrections. The additive database
   migration initializes existing saves with unknown arrival.
5. **Verification:** shared JSON fixtures, malformed-contract tests, reverse
   traversal and multi-opening scenarios, seed/cache tests, HTTP persistence,
   failure and summary tests, and the cross-repository ZIP smoke exercise.

## Verification commands

- AdventureForge: `node --test "app/**/*.node.mjs"`.
- AdventureForge browser: serve the repo and open `/unit.html`; all assertions
  must pass, including map drawing, export, spatial facts and module validation.
- TableForge: `python -m unittest discover -s tests -q`.
- TableForge focused checks: `python -m unittest discover -s tests -p test_cartridge_geometry.py -v`.

The ZIP smoke exercise uses AdventureForge's actual `buildCartridge` with the
shared fixture and the current Stage 3 file, then imports that ZIP through
TableForge's HTTP API. A test provider narrates entry to room 4, reverse traversal
to room 9, and re-entry through the second opening. Context checks confirm the
correct endpoint after reload and transcript summarization. No paid AI request
is needed for these structural checks.

Generated AI prose still needs a live play review against the fixture map.
Test-provider prose verifies plumbing, not model adherence or narration quality.

## Release sequence

1. Review and release TableForge consumption and arrival persistence first.
   Restart its process so the new adapter/module and additive migration load.
   Verify a legacy cartridge/save and a new geometry fixture on that release.
2. Publish AdventureForge's geometry export and versioned prompts after the
   TableForge release is verified. Author and export a fresh cartridge.
3. Start a new save with that cartridge and review actual AI narration from
   both entrances, including the long room and irregular alcove.

Do not replace live cartridges, rewrite saved prompts, or retrofit existing
playthroughs as part of this rollout. No deployment is performed by these local
implementation changes.

## Local verification result (2026-11-07)

- AdventureForge: 32 Node tests passed; complete browser suite passed 4,369 assertions.
- TableForge: 270 tests completed successfully, with one skipped test.
- Export/import/reverse-traversal/save-resume ZIP smoke test passed using a test provider.
- Arrival persistence after transcript summarization and invalid/unknown metadata passed.
- Migration test now closes its fixture SQLite connection explicitly for Windows cleanup.
- Live AI narration review and production deployment remain rollout steps.
