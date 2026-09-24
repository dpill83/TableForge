# TableForge Cartridge Specification

**Status:** Draft product/format specification  
**Target:** TableForge v2  
**Purpose:** Define the AdventureForge → TableForge adventure-package boundary.

---

## 1. Definition

A **TableForge cartridge** is the portable adventure package produced by AdventureForge and opened by TableForge to begin or resume play.

The intended mental model is a game cartridge:

- AdventureForge authors the adventure.
- The cartridge contains the authored adventure and supporting assets.
- TableForge mounts/opens the cartridge.
- TableForge does **not** treat the cartridge as the mutable campaign save.
- Playthrough progress is stored separately in a TableForge **save / memory card**.

The cartridge should normally be treated as **read-only** during play.

---

## 2. Design Goals

The cartridge format should be:

- portable
- human-inspectable where practical
- easy for AdventureForge to generate
- easy for TableForge to validate
- explicit enough to avoid filename guessing
- versioned
- extensible
- safe from accidental mutation during play
- usable independently from any specific AI provider

A cartridge should contain enough information for TableForge to initialize an AI-DM session without requiring the user to manually reconstruct the AdventureForge workflow.

---

## 3. Initial Package Format

The first implementation may use a standard ZIP archive.

Example:

```text
Dress-Rehearsal-at-Hollow-Well.tableforge.zip
```

A plain `.zip` is also acceptable during early development.

TableForge should not depend on the file extension alone. The internal manifest determines whether the package is a valid TableForge cartridge.

---

## 4. Cartridge Structure

Recommended structure:

```text
manifest.json

module.md
run-data.json
continuity.json

cast.md
cast.json
scenes.json
music-cues.json
map-art-brief.md

assets/
    maps/
    portraits/
    scenes/
    handouts/
    audio/
    other/
```

The current AdventureForge Stage 2 output already produces the core authored files. TableForge should support those files directly.

The `assets/` directories are a forward-compatible convention. Empty asset directories are not required.

---

## 5. Required vs Optional Content

### Required

A cartridge should not be considered playable without:

```text
manifest.json
module.md
run-data.json
```

`manifest.json` identifies the package and its resource bindings.

`module.md` is the human-readable authored module.

`run-data.json` is the structured runtime adventure data used by the AI-DM.

### Optional

The following resources enhance TableForge but should not prevent an adventure from starting if absent:

```text
continuity.json
cast.md
cast.json
scenes.json
music-cues.json
map-art-brief.md
maps
portraits
scene artwork
handouts
audio
other assets
```

Missing optional resources should be shown as warnings rather than errors.

---

## 6. Legacy / Pre-Manifest Support

Current AdventureForge Stage 2 output may not yet include `manifest.json`.

During the transition, TableForge should support **legacy cartridge detection**.

For a selected folder, file collection, or ZIP without a manifest, TableForge may look for known filenames:

```text
module.md
run-data.json
continuity.json
cast.md
cast.json
scenes.json
music-cues.json
map-art-brief.md
```

It may also attempt conservative asset detection, for example:

```text
*map*.png
*map*.jpg
*dungeon*.png
```

Legacy detection is a convenience feature only.

TableForge must show the inferred bindings to the user before starting the adventure so they can correct incorrect guesses.

Once `manifest.json` becomes standard, manifest-driven loading should be preferred.

---

## 7. Manifest

Recommended filename:

```text
manifest.json
```

Initial conceptual shape:

```json
{
  "format": "tableforge-adventure",
  "formatVersion": 1,

  "id": "dress-rehearsal-at-hollow-well",
  "title": "Dress Rehearsal at Hollow Well",
  "adventureVersion": "1.0.0",

  "generator": {
    "name": "AdventureForge",
    "version": "unknown"
  },

  "resources": {
    "module": "module.md",
    "runData": "run-data.json",
    "continuity": "continuity.json",
    "castMarkdown": "cast.md",
    "cast": "cast.json",
    "scenes": "scenes.json",
    "musicCues": "music-cues.json",
    "mapArtBrief": "map-art-brief.md"
  },

  "assets": {
    "maps": [],
    "portraits": [],
    "scenes": [],
    "handouts": [],
    "audio": [],
    "other": []
  }
}
```

This is a draft schema, not yet a locked implementation contract.

---

## 8. Manifest Fields

### `format`

Required.

Must be:

```text
tableforge-adventure
```

This prevents TableForge from mistaking an unrelated ZIP file for a cartridge.

### `formatVersion`

Required integer.

Example:

```json
"formatVersion": 1
```

This versions the cartridge specification itself.

TableForge should reject unsupported future format versions with a clear message rather than attempting unsafe interpretation.

### `id`

Required stable cartridge/adventure identifier.

This is used to associate saves with the correct cartridge.

It should remain stable across compatible revisions of the same adventure.

Example:

```text
dress-rehearsal-at-hollow-well
```

A future UUID is also acceptable.

### `title`

Required display title.

Example:

```text
Dress Rehearsal at Hollow Well
```

### `adventureVersion`

Recommended.

Tracks revisions to the adventure content independently from the cartridge format.

Example:

```text
1.0.0
```

The exact versioning policy can be finalized later.

### `generator`

Optional but recommended.

Records which tool produced the cartridge.

Example:

```json
{
  "name": "AdventureForge",
  "version": "1.2.0"
}
```

### `resources`

Maps semantic TableForge roles to files inside the cartridge.

This is the main reason for having a manifest.

TableForge should not need to guess whether `cast.json` is the cast list or whether `module.md` is the module if the manifest already specifies it.

### `assets`

Optional collections of media and supporting files.

Asset entries may initially be simple paths. They can later become structured objects if metadata is needed.

---

## 9. Resource Bindings

TableForge should think in terms of **resource roles**, not filenames.

Example:

```text
Module View  → module.md
Run Data     → run-data.json
Cast / NPCs  → cast.json
Scenes       → scenes.json
Continuity   → continuity.json
Music        → music-cues.json
Map Brief    → map-art-brief.md
```

This allows a future AdventureForge version to rename files without breaking TableForge, provided the manifest binding remains correct.

The New Adventure screen should display these bindings and allow manual correction before creating a save.

---

## 10. New Adventure Validation

When the user chooses **New Adventure** and inserts a cartridge, TableForge should:

1. open the package
2. locate and parse `manifest.json` when present
3. verify the cartridge format/version
4. resolve each resource path
5. verify required resources exist
6. enumerate optional resources
7. display detected bindings
8. flag missing required content in red
9. flag missing optional content in amber/yellow
10. allow the user to correct bindings before continuing

Example:

```text
ADVENTURE
✓ Title          Dress Rehearsal at Hollow Well
✓ Module         module.md
✓ Run Data       run-data.json

REFERENCE
✓ Cast           cast.json
✓ Scenes         scenes.json
✓ Continuity     continuity.json

MEDIA
✓ Map            assets/maps/hollow-well.png
! Music          Not found - Optional
```

---

## 11. Validation Severity

### Error

Use when the cartridge cannot reliably start.

Examples:

- manifest is malformed
- unsupported cartridge format
- required resource is missing
- required JSON is invalid
- resource path points outside the package

Errors should block **Start Adventure**.

### Warning

Use when an optional feature will be unavailable.

Examples:

- no cast file
- no map
- no music cues
- no scene images
- no continuity file

Warnings should not block play.

### Information

Use for non-problem status.

Examples:

- 14 NPCs detected
- 2 maps available
- 8 scene images available

---

## 12. Path Rules

All manifest paths should be package-relative.

Valid:

```text
module.md
assets/maps/hollow-well.png
```

Invalid:

```text
C:\Users\Dan\Desktop\module.md
../../secret.txt
https://example.com/module.md
```

TableForge should reject path traversal outside the cartridge.

Remote URLs should not be required for a valid cartridge.

---

## 13. Read-Only Behavior

Opening a cartridge must not silently modify it.

During play, TableForge should write changes only to the associated save.

Examples of data that belong in the save, not the cartridge:

- NPC discovered
- location visited
- map revealed
- combat result
- item obtained
- player-uploaded portrait
- generated scene image
- table transcript
- Pilot conversation
- AI summary
- current adventure state

If a future editing workflow is added, it should be explicit and separate from normal play.

---

## 14. Party Knowledge

The cartridge may contain secret information.

Therefore:

> Existence in the cartridge does not imply visibility to players.

Examples:

- `cast.json` may contain NPCs the party has not met.
- `module.md` may contain hidden motives.
- `run-data.json` may contain traps, DCs, secret rooms, and encounter information.
- a map may reveal areas the party has not discovered.

TableForge must not expose raw cartridge content indiscriminately through player-facing reference tools.

The save should track what has been discovered/revealed.

Player-facing NPC, Location, World Notes, Items, and Maps views should be built from player-safe knowledge.

Pilot Mode may expose additional authored information when appropriate.

---

## 15. Maps

Maps require explicit visibility handling.

A cartridge may contain:

- a Pilot/GM map
- a player-facing map
- a map that becomes available only after being acquired
- multiple maps for different locations

The initial manifest may list map paths simply.

A future structured map entry may look like:

```json
{
  "id": "beeck-vaults",
  "path": "assets/maps/beeck-vaults.png",
  "title": "Beeck Vaults",
  "visibility": "pilot"
}
```

Possible future visibility values:

```text
pilot
player
acquired
```

Do not lock this schema until the map workflow is implemented.

For the initial version, it is acceptable for TableForge to treat cartridge maps as Pilot-only unless explicitly marked/revealed to players through save state.

---

## 16. Cast / NPC Data

When `cast.json` exists, TableForge may use it as the authoritative authored cast source.

Possible TableForge uses include:

- NPC reference viewer
- portrait lookup
- names and descriptions
- AI-DM context
- player-safe discovered NPC list

Do not assume every NPC in `cast.json` is player-known.

`cast.md` may remain useful as a human-readable viewer even when `cast.json` provides the structured source.

---

## 17. Locations and World Notes

The current Stage 2 artifact set does not necessarily provide dedicated `locations.json` or `world-notes.json` files.

TableForge may derive location/world-reference information from available authored sources such as:

- `run-data.json`
- `module.md`
- `scenes.json`
- `continuity.json`

However, derived reference entries must respect player knowledge and spoiler safety.

If AdventureForge later produces dedicated location or world-note files, the manifest can add resource bindings without changing the cartridge model.

---

## 18. Scene Data

`scenes.json` may be used for:

- authored scene references
- scene artwork association
- AI context
- module browsing
- future scene-reference tooling

It should not force the TableForge play UI back into manual scene-number targeting.

The live TableForge conversation remains a continuous shared feed.

---

## 19. Music Cues

`music-cues.json` is optional.

Initial TableForge may only expose it through a viewer or reference tool.

Automatic playback is not required by the cartridge specification.

If audio assets are included in the future, manifest paths should remain package-relative.

---

## 20. AI-DM Initialization

The cartridge provides authored adventure context.

TableForge provides runtime/session context.

Conceptually:

```text
Stage 3 operating instructions
        +
Cartridge adventure material
        +
TableForge save/current state
        +
Current player messages
        =
AI-DM request
```

The cartridge should not contain API keys, provider credentials, or user-specific runtime secrets.

AI-provider configuration belongs in TableForge Options/server configuration.

---

## 21. Save Association

Every TableForge save should record enough cartridge identity to verify that it is being opened with the correct adventure.

At minimum:

```text
cartridge format
cartridge ID
adventure version
```

Potential future additions:

```text
content hash
manifest hash
cartridge filename
generator/version
```

When loading a save:

- if the expected cartridge is available, mount it
- if it is missing, ask the user to locate it
- if the ID does not match, warn/block as appropriate
- if the adventure version differs, do not silently assume compatibility

Detailed compatibility/migration rules belong in `SAVE-SPEC.md`.

---

## 22. Cartridge Updates

A later AdventureForge revision may produce an updated cartridge for the same adventure.

Do not silently replace the cartridge associated with an existing save.

Potential future behavior:

```text
This save was created with:
Dress Rehearsal at Hollow Well 1.0.0

Selected cartridge:
Dress Rehearsal at Hollow Well 1.1.0

[Use Original] [Review Update] [Cancel]
```

Exact migration behavior is deferred.

---

## 23. Security and Robustness

TableForge cartridge loading should:

- treat package contents as untrusted input
- prevent path traversal
- limit unreasonable decompression sizes
- reject malformed JSON cleanly
- validate expected types before use
- never execute arbitrary code contained in a cartridge
- never load scripts from cartridge assets
- avoid trusting HTML embedded in Markdown without sanitization
- keep API credentials outside the cartridge

Images, text, JSON, audio, and similar content are data, not executable plugins.

A future plugin system would require a separate security design.

---

## 24. Cartridge Creation in AdventureForge

Long term, AdventureForge should provide a single export action such as:

```text
Export TableForge Cartridge
```

That process should:

1. gather the Stage 2 artifacts
2. generate `manifest.json`
3. gather referenced assets
4. validate required files
5. package everything
6. produce one cartridge file

The user should not normally need to hand-build the package.

During development, TableForge may continue accepting a folder or multi-file selection.

---

## 25. Suggested Initial `manifest.json`

For the current AdventureForge output:

```json
{
  "format": "tableforge-adventure",
  "formatVersion": 1,
  "id": "dress-rehearsal-at-hollow-well",
  "title": "Dress Rehearsal at Hollow Well",
  "adventureVersion": "1.0.0",
  "generator": {
    "name": "AdventureForge"
  },
  "resources": {
    "module": "module.md",
    "runData": "run-data.json",
    "continuity": "continuity.json",
    "castMarkdown": "cast.md",
    "cast": "cast.json",
    "scenes": "scenes.json",
    "musicCues": "music-cues.json",
    "mapArtBrief": "map-art-brief.md"
  },
  "assets": {
    "maps": [],
    "portraits": [],
    "scenes": [],
    "handouts": [],
    "audio": [],
    "other": []
  }
}
```

This example defines the initial direction only.

Do not treat every field shown here as permanently frozen until implementation validates the shape.

---

## 26. Initial Implementation Scope

For the first real cartridge implementation, keep the scope small.

### Must support

- select a folder or cartridge package
- read manifest if present
- legacy filename detection if absent
- detect `module.md`
- detect `run-data.json`
- detect optional Stage 2 files
- show validation results
- allow manual binding correction
- prevent start when required content is missing
- create a new save without modifying the cartridge

### Nice to support

- ZIP package
- manifest generation in AdventureForge
- basic image/map enumeration
- cast counts
- metadata preview

### Defer

- cartridge migration
- remote cartridges
- executable plugins
- automatic updates
- advanced asset metadata
- encryption
- marketplace/distribution features
- complex dependency systems

---

## 27. Open Questions

These are intentionally not yet locked:

1. Final cartridge extension (`.zip`, `.tableforge`, `.tfadventure`, etc.).
2. Whether `module.md` and `run-data.json` remain the only required authored resources.
3. Exact `manifest.json` schema.
4. Exact adventure-version compatibility rules.
5. Whether asset metadata belongs directly in the manifest or separate index files.
6. How AdventureForge identifies player-safe versus Pilot-only maps.
7. Whether locations/world notes eventually become dedicated Stage 2 artifacts.
8. Whether portraits are indexed by `cast.json` or the manifest.
9. Whether a cartridge should include the exact Stage 3 prompt or TableForge should own the Stage 3 runtime instructions.

Until those decisions are made, implementation should preserve flexibility rather than hard-code assumptions unnecessarily.

---

## 28. Core Invariants

These should remain true unless explicitly changed:

1. **AdventureForge creates the cartridge.**
2. **TableForge opens the cartridge.**
3. **The cartridge is separate from the save.**
4. **Normal play does not mutate the cartridge.**
5. **Required resources block startup when missing.**
6. **Optional resources do not block startup.**
7. **The manifest is the preferred source of resource bindings.**
8. **Legacy filename detection is a fallback.**
9. **Player-facing views must not expose unrevealed cartridge secrets.**
10. **AI-provider credentials never belong in the cartridge.**
11. **Cartridge contents are data, not executable code.**
