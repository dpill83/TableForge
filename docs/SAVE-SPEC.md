# TableForge Save / Memory Card Specification

**Status:** Draft product/format specification  
**Target:** TableForge v2  
**Purpose:** Define the persistent playthrough data stored by TableForge separately from the AdventureForge cartridge.

---

## 1. Definition

A **TableForge save** is the persistent playthrough record associated with an AdventureForge cartridge.

The intended mental model is a console memory card:

- **AdventureForge** creates the cartridge.
- **TableForge** opens the cartridge.
- **The save** records what happened while playing it.

The save must remain separate from the cartridge.

The cartridge is authored adventure data.

The save is mutable playthrough data.

---

## 2. Core Principles

A TableForge save should:

- preserve the full play history where practical
- preserve enough structured state to resume reliably
- remain portable
- remain understandable independently of a specific AI provider
- associate itself with the correct cartridge
- never require the cartridge itself to be modified
- preserve player-facing discoveries separately from hidden cartridge knowledge
- preserve Pilot operational context
- preserve important attachments and generated/shared media
- support multiple real-world sessions inside one playthrough
- remain recoverable after TableForge is closed and reopened

The save should be the authoritative record of the playthrough.

The AI provider's conversation history is not the authoritative save.

---

## 3. Save vs Cartridge

### Cartridge contains

Authored adventure content, such as:

- module text
- runtime adventure structure
- NPC definitions
- encounter information
- scenes
- continuity
- music cues
- maps
- portraits
- handouts
- other authored assets

### Save contains

Mutable playthrough information, such as:

- session history
- player messages
- AI-DM messages
- Pilot-to-AI-DM messages
- current adventure progress
- discovered NPCs
- known locations
- revealed maps
- combat outcomes
- loot changes
- world-state changes
- player portrait overrides
- generated/shared images
- AI checkpoints/summaries
- current beat state
- Ready state when needed for recovery

---

## 4. Save Identity

Each save should have its own stable identifier.

Recommended metadata:

```json
{
  "format": "tableforge-save",
  "formatVersion": 1,
  "saveId": "uuid-or-stable-id",
  "name": "Dress Rehearsal at Hollow Well",
  "createdAt": "2026-09-20T23:30:00Z",
  "updatedAt": "2026-09-21T06:42:00Z"
}
```

### Required fields

- save format
- save format version
- save ID
- save name
- created timestamp
- updated timestamp

The exact serialization format may change during implementation.

---

## 5. Cartridge Association

Every save must identify the cartridge it belongs to.

Recommended metadata:

```json
{
  "cartridge": {
    "format": "tableforge-adventure",
    "id": "dress-rehearsal-at-hollow-well",
    "adventureVersion": "1.0.0",
    "title": "Dress Rehearsal at Hollow Well",
    "manifestHash": "optional-future-value"
  }
}
```

At minimum, persist:

- cartridge ID
- cartridge format/version
- adventure version when available
- adventure title

Possible future additions:

- cartridge content hash
- manifest hash
- original cartridge filename
- generator/version

When loading a save, TableForge should verify that the selected cartridge matches the save.

---

## 6. Save Location / Container

The exact physical save format is not yet locked.

Possible initial implementation:

```text
saves/
    dress-rehearsal-at-hollow-well/
        save.json
        transcript.jsonl
        pilot.jsonl
        attachments/
        generated/
```

A later portable single-file format may be:

```text
Dress-Rehearsal-at-Hollow-Well.tableforge-save
```

or:

```text
Dress-Rehearsal-at-Hollow-Well.save.zip
```

The internal model matters more than the final extension.

---

## 7. Session Model

One playthrough may contain many real-world sessions.

Example:

```text
Playthrough
├── Session 1
├── Session 2
├── Session 3
└── ...
```

Each session should record:

- session ID
- session number
- start time
- end time
- participating players
- messages/events created during that session
- session summary/checkpoint if generated
- current location/state at session end

Example:

```json
{
  "sessionId": "session-002",
  "number": 2,
  "startedAt": "2026-09-20T23:30:52Z",
  "endedAt": "2026-09-21T06:42:58Z",
  "participants": ["dan", "dani", "ted"]
}
```

---

## 8. Players and Characters

The save should record player identity separately from character identity.

Example:

```json
{
  "players": [
    {
      "playerId": "dan",
      "displayName": "Dan",
      "characterId": "george",
      "characterName": "George"
    }
  ]
}
```

This distinction allows:

- a player to change characters later
- different players to join different sessions
- the same character to remain part of the playthrough
- player-specific preferences to remain separate from cartridge data

Do not store a permanent Pilot assignment.

Pilot Mode is enabled locally/session-by-session.

---

## 9. Player Profiles

Player-specific data may include:

- display name
- character assignment
- portrait override
- local UI preferences
- preferred Pilot Mode default
- other lightweight profile settings

Character portraits may originate from the cartridge but may be overridden by the player.

The override belongs in save/profile data, not the cartridge.

---

## 10. Shared Transcript

The complete table-facing transcript should be preserved.

This includes:

- AI-DM messages
- player messages
- message timestamps
- sender identity
- session association
- attachments
- edits/drafts only when explicitly part of the product model

Example event:

```json
{
  "type": "message",
  "messageId": "msg-00421",
  "sessionId": "session-002",
  "channel": "table",
  "senderType": "player",
  "senderId": "george",
  "text": "I raise my shield and enter.",
  "createdAt": "2026-09-21T01:23:10Z"
}
```

The transcript should remain append-oriented where practical.

Do not silently rewrite historical messages.

---

## 11. Beat / Response Window Model

Normal play should be grouped internally into conversational beats.

A beat begins when the AI-DM publishes a table-facing response.

A beat ends when TableForge advances to the next AI-DM request.

Recommended saved metadata:

```json
{
  "beatId": "beat-014",
  "openedByMessageId": "msg-00410",
  "openedAt": "2026-09-21T01:20:00Z",
  "closedAt": "2026-09-21T01:24:30Z",
  "advanceReason": "all-ready"
}
```

Possible `advanceReason` values:

```text
all-ready
force-advance
combat-resume
manual
```

Players should not need to see or manage beat IDs.

They exist to make save/resume and context assembly reliable.

---

## 12. Ready State

Ready is normally transient, but enough state should be persisted to recover cleanly after an unexpected restart.

Possible stored state:

```json
{
  "currentBeat": {
    "beatId": "beat-014",
    "ready": {
      "dan": true,
      "dani": false,
      "ted": true
    }
  }
}
```

On deliberate session end, TableForge may normalize/reset Ready state.

On crash recovery, preserving it may help restore the table accurately.

Ready history does not need to become a detailed analytics log unless later needed.

---

## 13. Pilot-to-AI-DM Transcript

Pilot operational conversation should be stored separately from the public table feed.

Examples include:

- rules questions
- corrections
- monster behavior questions
- state clarification
- context instructions
- tactical questions

Example:

```json
{
  "type": "pilot-message",
  "messageId": "pilot-0018",
  "sessionId": "session-002",
  "senderPlayerId": "dani",
  "text": "Would Shenka try to escape if Viktor blocks the north opening?",
  "createdAt": "2026-09-21T04:02:00Z"
}
```

AI-DM replies to Pilot messages should also be saved.

These exchanges may later be selectively included in AI context.

---

## 14. AI-DM Messages

AI-DM outputs should be saved before or when published.

Recommended distinctions:

- generated draft
- published message
- rejected/regenerated draft

The first implementation may keep only published output plus minimal generation metadata.

If draft history is retained, it should be clearly separated from the canonical table transcript.

Canonical play history should represent what players actually saw.

---

## 15. AI Context Checkpoints

The save should preserve enough context to resume without depending on a provider-side chat.

Possible checkpoint contents:

- current adventure location
- current objective
- important active NPC state
- current clock/timer state
- unresolved hooks
- recent combat result
- relevant inventory/loot changes
- party knowledge changes
- concise summary of recent events

A checkpoint is supplemental to the full transcript.

It should not replace the transcript.

Example:

```json
{
  "checkpointId": "checkpoint-002",
  "sessionId": "session-002",
  "summary": "The party defeated Shenka and the false three...",
  "createdAt": "2026-09-21T06:40:00Z"
}
```

The exact checkpoint schema may evolve.

---

## 16. Structured Adventure State

TableForge should preserve useful structured state when practical.

Possible categories:

```text
current location
visited locations
active objectives
resolved objectives
NPC state
world flags
adventure clocks
revealed secrets
loot changes
combat outcomes
open threads
```

Do not attempt to model every D&D rule mechanically.

Structured state exists to help resume and context retrieval, not to become a full rules engine.

---

## 17. Party Knowledge

The save is authoritative for what the party has learned.

Examples:

```json
{
  "knowledge": {
    "npcs": {
      "sybil-peti": {
        "known": true,
        "firstDiscoveredAt": "msg-00020"
      }
    },
    "locations": {
      "hollow-well": {
        "known": true,
        "visited": true
      }
    }
  }
}
```

Possible knowledge categories:

- NPCs
- locations
- maps
- world notes
- factions
- items
- rumors
- secrets
- other discovered facts

Player-facing reference views should derive from this knowledge layer rather than directly exposing the cartridge.

---

## 18. NPC State

The save may track mutable NPC state separately from authored cast data.

Examples:

```text
met
alive
dead
missing
rescued
hostile
friendly
location
relationship notes
last seen
```

Example:

```json
{
  "npcState": {
    "gerta-hanfurd": {
      "status": "dead",
      "lastKnownLocation": "Beeck Vaults",
      "updatedAt": "2026-09-21T04:05:00Z"
    }
  }
}
```

Do not copy the full authored NPC definition into the save unless necessary.

Prefer storing changed/playthrough-specific state.

---

## 19. Location State

Possible location state:

```text
known
visited
current
map acquired
notes discovered
cleared
changed/destroyed
```

Example:

```json
{
  "locationState": {
    "hollow-well": {
      "known": true,
      "visited": true
    },
    "beeck-vaults": {
      "known": true,
      "visited": true,
      "current": true
    }
  }
}
```

---

## 20. Map State

Maps should be tracked independently from the existence of map assets in the cartridge.

Example:

```json
{
  "maps": {
    "beeck-vaults": {
      "cartridgeAsset": "assets/maps/beeck-vaults.png",
      "playerVisible": false,
      "acquired": false
    }
  }
}
```

When revealed:

```json
{
  "playerVisible": true,
  "acquired": true,
  "revealedAt": "msg-00510"
}
```

Pilot access may remain available separately.

---

## 21. World Notes

World Notes may be saved as structured discovered entries.

Example:

```json
{
  "worldNotes": [
    {
      "id": "note-highsun",
      "title": "Highsun",
      "text": "The impostor attacks began around Highsun.",
      "known": true,
      "sourceMessageId": "msg-00040"
    }
  ]
}
```

Some notes may be generated automatically.

Others may be manually created or edited by players/Pilots later.

Exact authoring behavior is deferred.

---

## 22. Open Threads

The save should support unresolved narrative threads.

Example:

```json
{
  "openThreads": [
    {
      "id": "thread-muxus",
      "title": "Who is Muxus?",
      "status": "open",
      "createdAt": "2026-09-21T01:25:00Z"
    }
  ]
}
```

Threads may come from:

- AdventureForge continuity
- AI-DM summaries
- explicit TableForge state
- manual Pilot notes

Do not require players to manage these manually during ordinary play.

---

## 23. Combat Outcomes

TableForge does not need to store every combat turn.

It should preserve meaningful outcomes reported back to the AI-DM.

Possible data:

```text
combat started
combat ended
enemies defeated
enemies fled
NPC casualties
party condition
important resources spent
loot acquired
notable narrative events
```

Example:

```json
{
  "combatId": "combat-003",
  "sessionId": "session-002",
  "result": {
    "enemiesDefeated": ["Muxus"],
    "npcDeaths": [],
    "notes": "The party broke the play and freed the remaining hostages."
  }
}
```

Detailed initiative/turn logs are not required.

---

## 24. Attachments

The save should preserve important uploaded/shared attachments.

Possible types:

- images
- screenshots
- handouts
- generated artwork
- player-created maps
- reference documents

Recommended storage:

```text
attachments/
    attachment-id.ext
```

Metadata example:

```json
{
  "attachmentId": "att-0042",
  "filename": "villains-door.webp",
  "mimeType": "image/webp",
  "messageId": "msg-00500"
}
```

Do not depend on external temporary URLs for long-term persistence when the file can be stored locally.

---

## 25. Generated Images

Generated/shared AI artwork should be treated like attachments.

Possible metadata:

- image ID
- local path
- source/provider if useful
- associated message
- session
- caption/description
- created timestamp

If a generated image becomes important to the adventure, it should remain accessible after resume.

---

## 26. Message Editing

The initial design should remain conservative.

Recommended rule:

> Sent messages are historical records.

If edits are supported later, preserve:

- original content
- edited content
- edit timestamp

Do not silently rewrite history.

For the first implementation, append-only corrections are acceptable and simpler.

---

## 27. Deletion

Do not prioritize deletion of canonical transcript entries.

If deletion becomes necessary for privacy or accidental uploads, define explicit behavior later.

Do not design the first save format around destructive message mutation.

---

## 28. Session End

A deliberate **End Session** action should create a clean checkpoint.

Recommended sequence:

1. finish current in-flight AI generation
2. persist transcript
3. persist Pilot conversation
4. persist structured state
5. persist party knowledge
6. persist attachments
7. create/update session summary/checkpoint
8. record session end time
9. mark save as cleanly closed

The exact summary may be AI-generated, deterministic, or hybrid.

---

## 29. Unexpected Shutdown / Crash Recovery

TableForge should write important state incrementally rather than only at End Session.

At minimum, persist promptly:

- sent player messages
- published AI-DM messages
- Pilot messages
- attachments
- major state transitions
- current beat
- Ready state when practical

This allows recovery after:

- browser crash
- server crash
- power loss
- accidental close

A clean End Session remains useful for generating a better resume checkpoint.

---

## 30. Resume Flow

When loading a save:

1. verify save format
2. locate associated cartridge
3. verify cartridge identity/version
4. load save metadata
5. restore session/playthrough state
6. restore transcript
7. restore party knowledge
8. restore attachments
9. restore current location/objectives
10. prepare AI-DM resume context
11. reconnect players
12. begin a new real-world session

Do not replay the Stage 3 adventure opening for an existing playthrough.

---

## 31. AI-DM Resume Context

TableForge should assemble resume context from its own save.

Potential sources:

```text
cartridge runtime data
current structured state
latest checkpoint
recent transcript
relevant older transcript
Pilot corrections/rulings
current player context
```

The exact context-window strategy may change based on provider/model limits.

The save format should preserve enough source data to rebuild context differently later.

Do not permanently bake one provider's prompt format into the save.

---

## 32. Provider Independence

Avoid storing provider-specific state as the only way to resume.

Provider metadata may be recorded for debugging, such as:

```text
provider
model
request ID
token counts
```

But the canonical save should remain understandable without them.

A future playthrough should be able to switch providers without losing the campaign record.

---

## 33. Save Versioning

Recommended root metadata:

```json
{
  "format": "tableforge-save",
  "formatVersion": 1
}
```

When the save schema changes:

- increment format version when necessary
- migrate explicitly
- do not silently reinterpret incompatible data

Migration tooling can be added once real version changes exist.

Do not over-engineer migrations before v1 of the save format is implemented.

---

## 34. Cartridge Version Mismatch

If a save expects:

```text
Adventure 1.0.0
```

but the user selects:

```text
Adventure 1.1.0
```

TableForge should warn rather than silently continue.

Possible future options:

```text
Use original cartridge
Review update
Cancel
```

Exact migration/compatibility behavior is deferred.

---

## 35. Save Backups

Recommended future behavior:

- atomic writes
- backup before migration
- periodic rolling backup
- optional manual export

Initial implementation should at minimum avoid corrupting the only copy during save writes.

---

## 36. Portability

A playthrough should eventually be exportable.

Possible package:

```text
Hollow-Well-Playthrough.tableforge-save.zip
```

It may contain:

```text
save.json
transcript.jsonl
pilot.jsonl
attachments/
generated/
```

A future **Export Complete Game** option may bundle:

```text
cartridge/
save/
```

This is optional and separate from the core save format.

---

## 37. Privacy

The save may contain:

- private Pilot discussion
- player-written content
- uploaded files
- generated images
- AI responses

Treat it as user-owned local game data.

Do not upload save contents to unrelated services.

Only send AI context needed for the current provider request.

---

## 38. Security

Save loading should:

- validate JSON/types
- reject unsafe paths
- treat attachment metadata as untrusted
- prevent path traversal
- avoid executing stored scripts/code
- sanitize rendered Markdown/HTML
- keep API keys outside save data

The save is data, not executable code.

---

## 39. Suggested Initial Storage Model

A practical first implementation can remain simple:

```text
saves/
└── <save-id>/
    ├── save.json
    ├── transcript.jsonl
    ├── pilot.jsonl
    ├── attachments/
    └── generated/
```

### `save.json`

Contains:

- metadata
- cartridge association
- players
- sessions
- current state
- party knowledge
- maps
- NPC/location state
- open threads
- latest checkpoint

### `transcript.jsonl`

One table-facing event per line.

### `pilot.jsonl`

One Pilot/AI-DM operational event per line.

This is an implementation recommendation, not a permanent requirement.

SQLite may also remain an appropriate internal storage layer.

If SQLite is used, export/import should still map cleanly to the conceptual save model.

---

## 40. SQLite Compatibility

TableForge v1 already uses SQLite.

v2 may continue using SQLite internally.

If so, the schema should represent the save concepts rather than merely preserving v1 tables for compatibility.

Potential tables:

```text
saves
sessions
players
characters
messages
beats
pilot_messages
knowledge_npcs
knowledge_locations
knowledge_notes
map_state
attachments
checkpoints
state
```

Do not create all tables up front unless the implementation needs them.

Prefer a minimal schema that can grow safely.

---

## 41. Initial Implementation Scope

### Must support

- create save for a validated cartridge
- save metadata
- associate save with cartridge
- save players/character assignments
- persist table transcript
- persist Pilot conversation
- persist sessions
- persist current beat
- persist basic Ready recovery state
- persist a minimal structured state/checkpoint
- close and reopen the save
- resume without provider-side chat history

### Nice to support

- attachments
- generated images
- known NPC/location state
- revealed map state
- AI-generated session summary
- export/import

### Defer

- advanced migration
- cloud sync
- collaborative remote hosting
- save branching
- multiple simultaneous timelines
- encrypted saves
- complex diff/history UI
- automatic cartridge updates

---

## 42. Open Questions

These remain intentionally unresolved:

1. Final physical save format.
2. SQLite-only vs SQLite + export package.
3. Exact checkpoint schema.
4. Exact structured state schema.
5. How much state should be AI-generated versus deterministically derived.
6. Whether Ready history beyond the current beat is useful.
7. Whether draft/regenerated AI-DM outputs should be retained.
8. Exact message edit/delete policy.
9. Exact backup policy.
10. Whether profile data belongs inside each save or partly in application-level settings.
11. How party knowledge is automatically updated.
12. Whether Pilot messages are visible to all Pilot-enabled clients by default.
13. Exact attachment size/storage limits.
14. Exact save/cartridge version compatibility policy.

Implementation should preserve flexibility around these questions.

---

## 43. Core Invariants

Unless explicitly changed later:

1. **The save is separate from the cartridge.**
2. **Normal play does not modify the cartridge.**
3. **The save is authoritative for the playthrough.**
4. **The AI provider's chat history is not the save.**
5. **The full transcript should be preserved where practical.**
6. **Pilot operational messages are preserved separately from the public feed.**
7. **The save tracks what the party has learned.**
8. **Player-facing reference views must respect party knowledge.**
9. **A save must identify the cartridge it belongs to.**
10. **Resuming should not require reconstructing the old ChatGPT conversation manually.**
11. **Provider-specific metadata may supplement but not replace portable save state.**
12. **Combat outcomes matter more than detailed turn-by-turn combat logs.**
13. **Attachments important to the playthrough should survive save/load.**
14. **Sent history should not be silently rewritten.**
15. **Unexpected shutdown should not erase the night's play.**
