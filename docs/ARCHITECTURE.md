# TableForge Architecture

**Status:** Draft architecture specification  
**Target:** TableForge v2  
**Purpose:** Define the initial technical architecture for the standalone/shared TableForge application.

---

## 1. Architectural Goal

TableForge should become a standalone/shared runtime for playing AdventureForge-created adventures without depending on ChatGPT.com or the current Tampermonkey relay.

The intended high-level architecture is:

```text
Player Browsers
      |
      | HTTP / WebSocket
      v
TableForge Server
      |
      +-- Application API
      +-- Session Runtime
      +-- Cartridge Manager
      +-- Save Manager
      +-- AI-DM Service
      +-- Knowledge / Reference Service
      |
      v
Local Persistent Storage
      |
      +-- SQLite
      +-- Save attachments
      +-- Generated/shared images
      |
      v
AI Provider API
```

The host machine runs TableForge.

Other players connect to the host over the local network using a browser.

---

# 2. Architectural Principles

## 2.1 Keep the cartridge separate from the save

AdventureForge creates the cartridge.

TableForge mounts the cartridge and writes all mutable playthrough data to the save.

Normal play must not mutate the cartridge.

## 2.2 The save is authoritative

The save is the authoritative record of:

- transcript
- sessions
- player activity
- Pilot activity
- discovered knowledge
- current state
- attachments
- AI resume context

The AI provider's conversation history is not authoritative.

## 2.3 The server owns sensitive operations

The browser must not contain:

- AI API keys
- filesystem access
- save-file write logic
- cartridge extraction logic
- provider secrets

Those belong on the server.

## 2.4 Keep the client thin

The browser client should primarily handle:

- rendering
- user input
- local UI preferences
- Ready state interaction
- Pilot Mode visibility
- live updates

Game state and persistence belong on the server.

## 2.5 Avoid unnecessary framework complexity

The first production frontend may use:

- HTML
- CSS
- vanilla JavaScript

A framework should be introduced only if the application grows enough to justify it.

## 2.6 Preserve provider independence

The AI provider should sit behind a service/interface.

TableForge should be able to change providers later without rewriting:

- cartridge format
- save format
- player UI
- transcript model

---

# 3. Major Components

Recommended initial structure:

```text
TableForge/
├── AGENTS.md
├── README.md
├── ROADMAP.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CARTRIDGE-SPEC.md
│   ├── SAVE-SPEC.md
│   ├── SESSION-WORKFLOW.md
│   └── UI-UX.md
├── prototypes/
│   └── TableForge-prototype-03-adventure-setup.html
├── server/
│   ├── app.py
│   ├── api/
│   ├── services/
│   ├── models/
│   ├── storage/
│   └── ai/
├── web/
│   ├── index.html
│   ├── styles/
│   ├── js/
│   └── assets/
├── data/
│   ├── saves/
│   └── cache/
└── tests/
```

The exact filenames may change during implementation.

The separation of responsibilities should remain.

---

# 4. Frontend

The frontend is the TableForge browser UI.

It should implement the screens defined in `UI-UX.md`.

## Primary screens

```text
Title
New Adventure
Adventure Setup
Load Adventure
Options
Play
```

## Frontend responsibilities

The frontend should:

- render application screens
- render shared transcript
- collect player messages
- show party members
- show Ready states
- toggle Ready / Unready
- expose Pilot Mode controls
- display reference views
- upload attachments
- display live AI generation
- collapse/expand UI regions
- show connection/error state

The frontend should not be responsible for authoritative game state.

---

# 5. Frontend State

Frontend state may include:

```text
current screen
current player identity
local Pilot Mode toggle
sidebar collapse state
composer draft
selected reference panel
connection state
current server snapshot
```

Local-only preferences may be stored in browser storage when appropriate.

Examples:

- left sidebar collapsed
- right sidebar collapsed
- Pilot Mode UI visibility
- preferred theme

Do not store authoritative transcript or save state only in browser storage.

---

# 6. Server

The server is the authoritative TableForge runtime.

Initial implementation direction:

```text
Python
```

The current v1 Python experience can inform implementation, but v2 should not preserve legacy architecture merely for compatibility.

## Server responsibilities

The server should own:

- application API
- session state
- cartridge loading
- cartridge validation
- save creation/loading
- transcript persistence
- Ready state
- Pilot actions
- context assembly
- AI provider calls
- AI streaming
- attachment storage
- party knowledge
- reference data
- session end/resume
- LAN client synchronization

---

# 7. HTTP API

The application should expose a simple local API.

Possible initial route groups:

```text
/api/app
/api/cartridges
/api/saves
/api/session
/api/messages
/api/ready
/api/pilot
/api/ai
/api/reference
/api/attachments
```

Exact endpoints should be defined during implementation.

Avoid mirroring the v1 API merely because it already exists.

Design the API around v2 concepts:

- save
- session
- beat
- message
- Ready
- Pilot action
- cartridge resource
- reference knowledge

---

# 8. Live Updates

TableForge should not rely on frequent browser polling as the primary real-time mechanism.

Recommended direction:

```text
WebSocket
```

or another server-push mechanism.

Use live updates for:

- new messages
- Ready changes
- player joins/leaves
- AI generation chunks
- mode changes
- Pilot actions
- attachment availability
- session transitions

HTTP remains appropriate for ordinary request/response operations such as:

- loading saves
- uploading cartridges
- settings
- querying references

If WebSocket complexity becomes a blocker, short polling may be used temporarily during early implementation, but it should not become the long-term architecture by accident.

---

# 9. Cartridge Manager

The Cartridge Manager implements `CARTRIDGE-SPEC.md`.

Responsibilities:

- accept selected cartridge/folder/package
- parse `manifest.json`
- support legacy known-file detection
- validate required resources
- validate optional resources
- prevent unsafe paths
- expose resource bindings
- expose cartridge metadata
- provide read-only file access to other services
- verify cartridge identity when loading a save

Conceptual interface:

```text
CartridgeManager
    open()
    validate()
    get_manifest()
    get_resource(role)
    list_assets()
    verify_identity()
```

The rest of TableForge should request semantic resources such as:

```text
module
runData
cast
map
```

rather than hard-coding filenames.

---

# 10. Cartridge Mounting

A cartridge should be treated as mounted for the active playthrough.

TableForge may:

- read directly from an unpacked directory
- extract a ZIP to a temporary/cache directory
- use a safe archive abstraction

The implementation must preserve read-only semantics.

Temporary extraction should not be confused with copying the adventure into the save.

---

# 11. Save Manager

The Save Manager implements `SAVE-SPEC.md`.

Responsibilities:

- create new save
- open save
- verify cartridge association
- persist session state
- persist messages
- persist Pilot messages
- persist knowledge/state
- persist attachments
- manage checkpoints
- close/end session
- recover after unexpected shutdown
- export/import later

Conceptual interface:

```text
SaveManager
    create_save()
    open_save()
    append_message()
    append_pilot_message()
    update_state()
    update_knowledge()
    create_session()
    end_session()
    create_checkpoint()
```

---

# 12. Persistence Strategy

SQLite remains a good fit for structured runtime data.

Recommended storage model:

```text
data/
└── saves/
    └── <save-id>/
        ├── save.sqlite3
        ├── attachments/
        └── generated/
```

This keeps each save portable and isolated.

An alternative is one global SQLite database plus save folders.

The per-save database model better matches the memory-card metaphor and simplifies export.

This should be validated during implementation.

---

# 13. Suggested Initial Database Model

Do not create every future table on day one.

A minimal practical schema could begin with:

```text
saves
sessions
players
messages
beats
pilot_messages
attachments
checkpoints
state
```

Later additions may include:

```text
known_npcs
known_locations
known_notes
map_state
```

## `saves`

Possible fields:

```text
id
name
cartridge_id
cartridge_version
created_at
updated_at
```

## `sessions`

```text
id
save_id
number
started_at
ended_at
```

## `players`

```text
id
save_id
display_name
character_id
character_name
portrait_path
```

## `messages`

```text
id
save_id
session_id
beat_id
sender_type
sender_id
text
created_at
published
```

## `beats`

```text
id
save_id
session_id
opened_by_message_id
opened_at
closed_at
advance_reason
```

## `pilot_messages`

```text
id
save_id
session_id
player_id
sender_type
text
created_at
```

## `attachments`

```text
id
save_id
message_id
path
filename
mime_type
created_at
```

## `checkpoints`

```text
id
save_id
session_id
summary
state_json
created_at
```

## `state`

May initially be a small key/value or JSON-backed table rather than many specialized state tables.

Do not prematurely normalize unknown future requirements.

---

# 14. Shared Session Runtime

The Session Runtime owns the currently active game session.

Conceptual state:

```text
ActiveSession
    save
    cartridge
    players
    currentBeat
    readyStates
    mode
    activeGeneration
```

Possible modes:

```text
normal
combat
paused
```

The session runtime should be reconstructable from the save after restart.

Do not rely on in-memory state alone.

---

# 15. Player Connections

Each connected browser should identify:

- player ID
- save/session
- character assignment

Authentication can remain lightweight initially because the primary use case is a trusted local group.

Do not over-engineer user accounts before they are needed.

Initial options may include:

- session invite code
- player selection
- locally persisted participant token

Security should still prevent one browser from trivially impersonating another once the session is active.

---

# 16. Pilot Mode Architecture

Pilot Mode is primarily a client capability state, not a permanent database role.

A player may enable Pilot Mode locally.

The server still needs to validate Pilot-only operations.

Because this is a trusted table, initial authorization may be lightweight.

Pilot actions should record:

- player
- action
- timestamp

Examples:

```text
force advance
ask AI-DM
resume combat
regenerate AI response
modify advance context
```

Multiple Pilot-enabled players may coexist.

The server must serialize conflicting operations.

---

# 17. Concurrency

The most important concurrency rule is:

> Only one AI-DM generation may advance the table at a time.

The server should maintain an active-generation lock/state.

Examples of conflicts to prevent:

- two users triggering Force Advance simultaneously
- all-Ready auto-advance firing while a Pilot presses Force Advance
- two Pilots pressing Resume AI-DM
- a second generation starting before the first finishes

The server, not the browser, must enforce this.

---

# 18. Beat State Machine

Normal play should follow an explicit state machine.

Conceptually:

```text
AI RESPONSE PUBLISHED
        |
        v
COLLECTING PLAYER INPUT
        |
        +-- player message
        +-- Ready / Unready
        +-- Pilot operational messages
        |
        v
ADVANCE TRIGGER
        |
        +-- all players Ready
        +-- Force Advance
        |
        v
CONTEXT SNAPSHOT
        |
        v
AI GENERATING
        |
        v
AI RESPONSE PUBLISHED
```

Once context is snapshotted, new player messages must not silently modify the in-flight AI request.

They should belong to the next beat or be explicitly handled.

---

# 19. Ready Service

Ready state belongs on the server.

Responsibilities:

- track active players
- set Ready
- unset Ready
- determine whether all active players are Ready
- request advance when conditions are met
- reset state for new beat

The Ready service should not directly call the AI provider.

It should signal the Session Runtime that advancement conditions were met.

This separation helps prevent duplicate generation.

---

# 20. Advance Service

The Advance Service coordinates:

```text
Ready/Pilot trigger
→ context selection
→ context snapshot
→ AI request
→ streamed response
→ publish
→ new beat
```

It should be the single path for normal table advancement.

This prevents different UI buttons from creating subtly different AI workflows.

Possible advance reasons:

```text
all-ready
force-advance
combat-resume
manual
```

---

# 21. Context Assembly

Context Assembly is a core backend responsibility.

Default normal advance context may include:

- Stage 3 runtime instructions
- relevant cartridge data
- current structured save state
- latest checkpoint
- recent transcript
- current-beat player messages
- required system information

Optional Pilot-selected context may include:

- Pilot conversation
- additional transcript history
- attachments
- specific cartridge resources
- additional notes

The context system should work with semantic units rather than exposing raw internal database formatting to the AI provider layer.

---

# 22. Context Selection Model

The UI may present checkboxes such as:

```text
[x] George messages
[x] Ethereal messages
[x] Viktor messages
[ ] Pilot conversation
[x] System summary
[x] Relevant state
```

The server should translate these selections into a context request.

Example conceptual model:

```json
{
  "includeCurrentPlayerMessages": true,
  "includePilotConversation": false,
  "includeCheckpoint": true,
  "includeStructuredState": true
}
```

Do not make frontend clients assemble raw prompts.

The server owns prompt/context construction.

---

# 23. AI Provider Layer

AI integration should sit behind a provider abstraction.

Conceptually:

```text
AIProvider
    generate()
    stream()
    cancel()
```

Potential implementations may include:

```text
OpenAIProvider
OtherProvider
```

The rest of TableForge should not depend directly on one provider's request format.

---

# 24. AI-DM Service

The AI-DM Service sits above the raw provider.

Responsibilities:

- Stage 3/runtime instructions
- context formatting
- provider calls
- response streaming
- generation state
- cancellation
- retry/regeneration
- operational Pilot questions
- table-facing generation

Conceptually:

```text
AIDMService
    advance_table()
    ask_pilot_question()
    regenerate()
    resume_after_combat()
```

Pilot operational questions and table advancement should be separate methods/workflows even if they use the same provider.

---

# 25. AI Streaming

Table-facing responses should stream to clients when supported.

Flow:

```text
server starts generation
        |
        v
provider streams tokens/chunks
        |
        v
server broadcasts draft chunks
        |
        v
clients render live response
        |
        v
generation completes
        |
        v
canonical published message saved
```

The canonical save should not rely solely on incomplete streamed fragments.

Persist the finalized published message.

---

# 26. AI Draft / Publish Model

This remains partly a UX decision.

The architecture should support both:

```text
generate → auto-publish
```

and:

```text
generate → Pilot review → publish
```

Do not hard-code the database/API so tightly that only one flow is possible.

At minimum, distinguish:

- in-progress generation
- completed draft
- published canonical message

Whether normal play automatically publishes can be decided later.

---

# 27. Pilot AI-DM Console

Pilot operational conversation should be a separate logical channel.

It may use the same provider/service but should have:

- separate message history
- separate UI
- no automatic effect on Ready state
- no automatic public publication
- optional inclusion in future table context

The console should be shared among Pilot-enabled users where appropriate.

---

# 28. Combat Mode

Combat Mode belongs to the Session Runtime.

When activated:

```text
mode = combat
```

Effects:

- disable normal all-Ready auto-advance
- keep Ready indicators available
- keep Pilot AI-DM questions available
- expose Resume AI-DM to Pilot users

TableForge does not need to model initiative or individual combat turns.

---

# 29. Combat Resume

Resume AI-DM should route through the same Advance Service with a different context source.

Conceptually:

```text
combat outcome
+
relevant state
+
Pilot notes
+
recent transcript
→ AI-DM
```

The resulting AI-DM aftermath response reopens normal play.

---

# 30. Reference / Knowledge Service

The Reference Service should provide player-safe views.

Responsibilities:

- known NPCs
- known locations
- world notes
- revealed maps
- related player-safe information

It must combine:

```text
cartridge authored information
+
save knowledge/reveal state
```

and return only what the requesting client is permitted to see.

Do not let the frontend read raw `run-data.json` and decide what is safe.

Spoiler filtering belongs on the server.

---

# 31. Pilot Reference Access

Pilot Mode may request richer cartridge information.

Possible Pilot-only resources:

- full Module Viewer
- full Cast Viewer
- GM map
- hidden authored notes

Authorization logic should remain explicit.

Do not use the same player-safe endpoint and simply rely on hidden UI buttons.

---

# 32. Attachments Service

Attachments may include:

- uploaded images
- screenshots
- handouts
- generated images
- documents

The server should:

- validate type/size
- generate stable IDs
- store files in the save
- associate them with messages
- serve them to connected clients
- include them in AI context only when intentionally selected/relevant

Do not rely on temporary browser blob URLs for saved media.

---

# 33. Static Assets vs Save Attachments

Differentiate:

### Cartridge assets

Authored by AdventureForge.

Examples:

```text
map
NPC portrait
scene artwork
handout
```

Read-only.

### Save attachments

Created or added during play.

Examples:

```text
player upload
generated image
screenshot
custom portrait override
```

Mutable and owned by the save.

---

# 34. Character Portrait Resolution

Recommended priority:

```text
player save/profile override
        ↓
cartridge character portrait
        ↓
generated initials/default avatar
```

The resolved portrait is returned to the client by the server/API.

Do not modify cartridge art when a user uploads a replacement.

---

# 35. Options / Configuration

Application-level configuration should be separate from saves.

Possible storage:

```text
config/
    settings.json
```

or equivalent.

Settings may include:

- provider
- model
- API key reference
- server host/port
- LAN exposure
- storage path
- appearance defaults

Sensitive keys should not be stored in files intended for easy sharing/export unless explicitly protected.

Environment variables or OS-secure storage may be considered later.

---

# 36. LAN Hosting

Initial local-network model:

```text
Host PC
  TableForge server
       |
       +-- localhost for host
       +-- LAN address for other players
```

Example:

```text
http://192.168.1.50:8765
```

The server should display the join address somewhere convenient.

Do not require each player to install Python or run a backend.

---

# 37. Networking Security

Because the primary use case is trusted LAN play, initial security can remain practical rather than enterprise-level.

Minimum expectations:

- random session/join token or equivalent
- participant identity token
- no API key exposure
- no arbitrary filesystem browsing
- safe attachment handling
- no remote cartridge path access
- explicit LAN bind option

Do not expose TableForge publicly to the internet by default.

---

# 38. API Errors

Errors should be explicit and recoverable.

Examples:

```text
cartridge invalid
save missing
cartridge mismatch
AI provider unavailable
AI generation failed
attachment rejected
session disconnected
generation already in progress
```

The frontend should receive structured error responses rather than parse server log text.

---

# 39. Logging

Server logging should help diagnose failures without becoming invasive telemetry.

Useful logs:

- server start/stop
- save opened
- cartridge validation failure
- AI provider error
- generation started/completed
- database error
- attachment error
- client connection/disconnection

Avoid recording secrets.

Do not log full AI prompts or private player content by default unless debug mode explicitly enables it.

---

# 40. Testing Strategy

Prioritize tests around state transitions and persistence.

## Unit tests

- cartridge validation
- manifest parsing
- save association
- Ready calculation
- context selection
- knowledge filtering
- state transitions
- provider abstraction

## Integration tests

- New Adventure → create save
- join players
- send messages
- Ready all
- AI generation
- publish
- crash/restart
- resume
- combat handoff
- Pilot Force Advance

## Browser tests

- navigation
- sidebar collapse
- Ready UX
- Pilot Mode visibility
- message composer
- live updates
- reference views

---

# 41. Migration from TableForge v1

v2 is a redesign.

Do not force v2 to maintain the v1 Tampermonkey interaction model.

Potential reusable concepts:

- Python server experience
- SQLite experience
- table/player identity concepts
- append-oriented message history
- idempotent write lessons
- session analytics lessons

Concepts not worth preserving merely for compatibility:

- ChatGPT DOM integration
- scene navigation as the primary UI
- `contextScene`
- manual scene targeting
- Tampermonkey-specific state
- copy/insert workflows

If v1 data import is desired later, build an explicit migration/import tool.

Do not distort the v2 architecture around automatic backward compatibility.

---

# 42. Deployment Phases

## Development

```text
python server
browser frontend
local filesystem
SQLite
```

## LAN testing

```text
host server on LAN
multiple browsers
```

## Later packaged desktop build

Possible wrapper:

```text
Tauri
```

or another lightweight desktop shell.

The packaged app may:

- launch the Python/runtime server
- open the frontend
- manage shutdown
- provide real Exit behavior

Packaging is not required for the first functional product.

---

# 43. Recommended Build Order

Build architecture vertically rather than layer-by-layer.

### Vertical Slice 1

```text
Title
→ New Adventure
→ cartridge validation
→ create empty save
→ Adventure Setup
→ Play shell
```

No AI required yet.

### Vertical Slice 2

```text
Play shell
→ player messages
→ Ready state
→ live synchronization
→ persistence
```

### Vertical Slice 3

```text
all Ready
→ context snapshot
→ mocked AI-DM response
→ publish
→ next beat
```

### Vertical Slice 4

Replace mocked AI with real provider.

### Vertical Slice 5

Pilot Mode and operational console.

### Vertical Slice 6

Combat handoff.

### Vertical Slice 7

Reference/knowledge views.

This order proves the full game loop early.

---

# 44. Avoid Premature Complexity

Do not begin with:

- plugin architecture
- cloud accounts
- cloud sync
- internet hosting
- VTT features
- full D&D rules engine
- microservices
- event buses
- complex frontend framework
- advanced save migration
- distributed databases

The initial product is a trusted local shared table.

Use simple architecture until real requirements demand more.

---

# 45. Initial Architectural Decisions

Unless later changed:

1. **Python server** remains the initial backend direction.
2. **Browser clients** provide the player UI.
3. **SQLite** is the preferred initial structured persistence technology.
4. **Attachments live alongside save data.**
5. **Cartridges remain separate and read-only.**
6. **The save is authoritative.**
7. **The server assembles AI context.**
8. **API keys stay server-side.**
9. **WebSocket/server push is the preferred real-time direction.**
10. **Pilot is a mode, not a permanent server role.**
11. **One AI advancement may execute at a time.**
12. **Normal play is modeled as beats rather than manually targeted scenes.**
13. **Player-safe knowledge filtering happens server-side.**
14. **Combat Mode disables normal auto-advance.**
15. **Desktop packaging is deferred until the web/server runtime works.**

---

# 46. Open Architecture Questions

These are intentionally unresolved:

1. Flask, FastAPI, or another Python web server.
2. Exact WebSocket implementation.
3. One SQLite database per save vs a global database.
4. Exact frontend module structure.
5. Exact participant authentication/token flow.
6. Exact AI provider abstraction.
7. Auto-publish vs Pilot review for ordinary AI-DM responses.
8. Exact save checkpoint generation strategy.
9. Exact party-knowledge extraction/update method.
10. Exact attachment limits.
11. Exact LAN discovery/join UX.
12. Whether a future desktop wrapper embeds Python or replaces some backend pieces.
13. Whether provider streaming should be persisted incrementally or only finalized on completion.

Do not resolve these solely for theoretical elegance.

Choose the simplest option that supports the next vertical slice and preserves the established product invariants.

---

# 47. Architecture Invariants

Unless explicitly changed:

1. AdventureForge builds adventures; TableForge runs them.
2. Cartridge and save remain separate.
3. Normal play does not mutate cartridge data.
4. The server owns authoritative game/session state.
5. The save is authoritative over provider chat history.
6. Browsers never receive provider API secrets.
7. Players do not manually target scene IDs.
8. Pilot Mode is optional and may be enabled by multiple players.
9. The server prevents duplicate/conflicting AI advancement.
10. Player-facing references are spoiler-safe.
11. Combat remains human-operated by default.
12. TableForge should remain usable without becoming a VTT.
13. The architecture should support LAN browser clients.
14. Provider-specific implementation details should remain behind an abstraction.
15. Build the simplest architecture that supports the agreed play workflow.
