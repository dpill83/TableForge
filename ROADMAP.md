# TableForge Roadmap

**Product:** TableForge  
**Target:** v2  
**Status:** Design and prototyping  
**Primary goal:** Build a standalone/shared runtime for playing AdventureForge-created AI-assisted tabletop RPG adventures.

---

## Guiding Model

TableForge uses a game-console model:

- **AdventureForge** creates the adventure.
- **Stage 2 output** is the **cartridge**.
- **TableForge** is the **console**.
- **The TableForge save** is the **memory card**.
- **The AI-DM** runs the adventure.
- **Players** play their characters.
- **Pilot Mode** exposes supervisory controls.

The cartridge remains separate from the save.

TableForge should not become a full VTT unless later playtesting proves that specific VTT-like features are needed.

---

# Phase 0 — Product Definition

## Status: Mostly complete

Define the product before rebuilding the application.

### Completed

- [x] Establish TableForge v2 as the new standalone/shared runtime
- [x] Standardize the supervisory concept as **Pilot Mode**
- [x] Define Pilot as a mode rather than a permanent assigned role
- [x] Define the AdventureForge cartridge model
- [x] Define the separate TableForge save / memory-card model
- [x] Define normal play as a shared continuous conversation
- [x] Define the Ready / Unready system
- [x] Define automatic advance during normal play
- [x] Define Pilot Force Advance / Ready Override
- [x] Define Pilot-to-AI-DM operational conversation
- [x] Define combat as a human-controlled mode with explicit AI-DM resume
- [x] Define the high-level title-screen application flow
- [x] Define the initial ChatGPT + Discord UI direction
- [x] Define spoiler-safe party knowledge as a future requirement
- [x] Create `AGENTS.md`
- [x] Create `README.md`
- [x] Create `CARTRIDGE-SPEC.md`
- [x] Create session workflow specification

### Remaining

- [ ] Finalize the first-pass Play Screen design
- [ ] Finalize the minimum save-state model
- [ ] Decide the first AI-provider integration
- [ ] Decide final cartridge packaging/extension

### Exit criteria

Phase 0 is complete when the Play Screen behavior and minimum save format are defined well enough to implement without inventing major product behavior during coding.

---

# Phase 1 — Static UX Prototype

## Status: In progress

Build the major screens as lightweight HTML/CSS/JavaScript prototypes before integrating them into the application.

Prototype files belong in:

```text
prototypes/
```

### Completed

- [x] Title Screen prototype
  - New Adventure
  - Load Adventure
  - Options
  - Exit
- [x] New Adventure / cartridge validation prototype
- [x] Adventure Setup prototype
  - save name
  - player list
  - character assignments
  - cartridge resource summary
  - Begin Adventure

Current prototype:

```text
prototypes/TableForge-prototype-03-adventure-setup.html
```

### Next

- [ ] Build the main Play Screen prototype

The Play Screen should include:

```text
Top bar

Collapsible left sidebar
Main shared conversation
Collapsible right sidebar
Collapsible bottom composer/status bar
```

### Left sidebar

Initial scope:

```text
# table

Reference
- NPCs
- Locations
- World Notes

Tools
- Cast Viewer
- Module Viewer
- Map

+ Add
```

Do not create multiple Discord-style channels without a real use case.

### Main area

- [ ] Continuous AI-DM / player conversation
- [ ] Player names/portraits
- [ ] AI-DM messages
- [ ] Player messages
- [ ] attachments/images
- [ ] generation state
- [ ] no manual scene-number targeting

### Right sidebar

Always-visible shared information:

- [ ] party members
- [ ] connection state
- [ ] Ready state
- [ ] quick reference

Pilot Mode adds:

- [ ] Ask AI-DM
- [ ] Review Context
- [ ] Force Advance
- [ ] Combat Mode / Resume AI-DM

### Bottom bar

- [ ] message composer
- [ ] attachment action
- [ ] Send
- [ ] Ready / Unready
- [ ] Pilot Force Advance when enabled

### Exit criteria

The prototype is complete when a user can visually walk through:

```text
Title
→ New Adventure
→ Cartridge Validation
→ Adventure Setup
→ Play Screen
```

without needing backend functionality.

---

# Phase 2 — Production Frontend Shell

## Status: Not started

Once the UX prototype is approved, stop extending the single-file prototype and build the real frontend.

Suggested structure:

```text
web/
├── index.html
├── styles/
│   └── app.css
├── js/
│   ├── app.js
│   ├── api.js
│   ├── cartridge.js
│   ├── state.js
│   └── screens/
│       ├── title.js
│       ├── new-adventure.js
│       ├── adventure-setup.js
│       ├── load-adventure.js
│       ├── options.js
│       └── play.js
└── assets/
```

Plain HTML/CSS/JavaScript is acceptable initially.

Do not introduce React, Vue, or another frontend framework unless the growing application clearly benefits from it.

### Tasks

- [ ] Create production web shell
- [ ] Implement screen routing/navigation
- [ ] Implement collapsible layout regions
- [ ] Implement reusable controls/styles
- [ ] Implement responsive behavior
- [ ] Preserve browser/LAN compatibility
- [ ] Remove prototype-only hardcoded sample data

### Exit criteria

All prototype screens exist in maintainable production frontend code and can communicate with a local backend API.

---

# Phase 3 — Cartridge Runtime

## Status: Not started

Implement the real New Adventure flow.

See:

```text
docs/CARTRIDGE-SPEC.md
```

### Initial support

- [ ] Select cartridge folder/files
- [ ] Read `manifest.json` when available
- [ ] Support legacy filename detection when no manifest exists
- [ ] Detect `module.md`
- [ ] Detect `run-data.json`
- [ ] Detect optional Stage 2 resources
- [ ] Validate JSON
- [ ] Show resource bindings
- [ ] Allow manual binding correction
- [ ] Distinguish required vs optional resources
- [ ] Block startup only when required content is missing
- [ ] Treat cartridge contents as read-only
- [ ] Prevent path traversal / unsafe package access

### AdventureForge integration

- [ ] Add cartridge manifest generation to AdventureForge
- [ ] Add a single **Export TableForge Cartridge** action
- [ ] Package Stage 2 artifacts automatically
- [ ] Include supported assets
- [ ] Version the cartridge format

### Exit criteria

A real AdventureForge Stage 2 output can be loaded into TableForge without manually reconstructing its files.

---

# Phase 4 — Save / Memory Card

## Status: Not started

Create the persistent playthrough format.

Recommended next specification:

```text
docs/SAVE-SPEC.md
```

### Minimum saved data

- [ ] cartridge ID
- [ ] cartridge/adventure version
- [ ] save/playthrough ID
- [ ] save name
- [ ] players
- [ ] character assignments
- [ ] session history
- [ ] full shared transcript
- [ ] Pilot-to-AI-DM transcript
- [ ] current adventure state
- [ ] Ready/beat state needed for recovery
- [ ] attachments
- [ ] generated/shared images
- [ ] AI resume context/checkpoint
- [ ] discovered party knowledge

### Load Adventure

- [ ] list saves
- [ ] show associated adventure
- [ ] show last-played/session information
- [ ] continue save
- [ ] detect missing cartridge
- [ ] prompt user to locate missing cartridge
- [ ] verify cartridge ID/version before loading
- [ ] do not silently substitute a different cartridge

### Exit criteria

A session can be closed, TableForge restarted, and the adventure resumed without manually rebuilding AI context.

---

# Phase 5 — Shared Table Runtime

## Status: Not started

Implement the real multiplayer/shared session loop.

### Players

- [ ] join the table
- [ ] select/receive player identity
- [ ] character identity
- [ ] connection/presence display
- [ ] portrait/avatar support
- [ ] player-specific local Pilot Mode toggle

### Shared feed

- [ ] publish AI-DM response
- [ ] post player response
- [ ] display messages live
- [ ] preserve message order
- [ ] support multiple player messages per beat
- [ ] support attachments/images
- [ ] prevent stale-target problems by using the current open beat

### Ready

- [ ] Ready
- [ ] Unready
- [ ] reset Ready on new AI-DM beat
- [ ] allow zero-message Ready
- [ ] auto-advance when all active players are Ready
- [ ] prevent duplicate generation
- [ ] Pilot Force Advance

### Networking

- [ ] local host
- [ ] LAN player access
- [ ] reconnect behavior
- [ ] resilient state synchronization
- [ ] no requirement for every player to run the Python backend

### Exit criteria

Three players can sit at the same table, connect from separate browser clients, exchange messages, Ready up, and move through beats together.

---

# Phase 6 — AI-DM Integration

## Status: Not started

Connect TableForge directly to an AI provider instead of using ChatGPT + Tampermonkey as the runtime bridge.

### Backend requirements

- [ ] API key stays server-side
- [ ] provider abstraction/interface
- [ ] model configuration in Options
- [ ] streaming responses
- [ ] one active generation at a time
- [ ] cancellation/retry behavior
- [ ] error handling
- [ ] token/context management
- [ ] TableForge save remains authoritative

### Context assembly

Conceptually:

```text
Stage 3 operating instructions
+
relevant cartridge content
+
saved state
+
selected transcript context
+
current-beat player messages
+
optional Pilot context
=
AI-DM request
```

### Pilot context review

- [ ] default all current-beat player messages to included
- [ ] expose optional context review
- [ ] allow Pilot messages to be included/excluded
- [ ] allow system summary/state to be included/excluded
- [ ] avoid requiring manual context management every beat

### AI-DM draft flow

- [ ] generate response
- [ ] Pilot supervision where appropriate
- [ ] publish response
- [ ] reset Ready
- [ ] start new beat

### Exit criteria

The full normal loop works without ChatGPT.com or the Tampermonkey userscript:

```text
AI-DM
→ players
→ Ready
→ AI-DM
```

---

# Phase 7 — Pilot Mode

## Status: Not started

Implement supervisory controls without creating a permanent DM role.

### Pilot controls

- [ ] enable/disable Pilot Mode locally
- [ ] Ask AI-DM
- [ ] correction/context message
- [ ] Review Context
- [ ] Force Advance
- [ ] generation supervision
- [ ] Combat Mode
- [ ] Resume AI-DM

### Multi-Pilot behavior

- [ ] multiple users can enable Pilot Mode
- [ ] record who initiated Pilot actions
- [ ] prevent conflicting generations
- [ ] shared Pilot console where appropriate
- [ ] no permanent Pilot assignment required

### Exit criteria

Any trusted player can temporarily take supervisory control without transferring ownership of the game.

---

# Phase 8 — Combat Handoff

## Status: Not started

Keep combat human-controlled while preserving AI-DM support.

### Combat Mode

- [ ] detect or manually trigger combat handoff
- [ ] pause normal Ready auto-advance
- [ ] preserve player Ready indicators
- [ ] keep Pilot Ask AI-DM available
- [ ] allow rulings/tactics/monster-motivation questions
- [ ] collect optional combat outcome
- [ ] explicit Resume AI-DM
- [ ] resume normal Ready loop after narration

### Do not build by default

- [ ] no initiative tracker
- [ ] no dice engine
- [ ] no character sheet
- [ ] no automated monster turns
- [ ] no VTT battlefield
- [ ] no automatic HP system

These are non-goals unless future playtesting creates a specific need.

### Exit criteria

The table can move cleanly from narrative play into human-run combat and back into AI-DM narration without losing context.

---

# Phase 9 — Reference and Party Knowledge

## Status: Not started

Turn authored adventure data into useful, spoiler-safe references.

### NPCs

- [ ] known NPC list
- [ ] name
- [ ] portrait when available
- [ ] player-safe description
- [ ] relationship/last-known context
- [ ] searchable

### Locations

- [ ] known/visited locations
- [ ] player-safe notes
- [ ] related NPCs/events where useful
- [ ] searchable

### World Notes

- [ ] discovered lore
- [ ] factions
- [ ] known facts
- [ ] searchable

### Maps

- [ ] Pilot/GM map access
- [ ] player-facing map visibility
- [ ] map acquisition/reveal state
- [ ] load cartridge image assets

### Existing AdventureForge tools

Evaluate reuse/adaptation of:

- [ ] Cast Viewer
- [ ] Module Viewer
- [ ] Map-related tools
- [ ] other AdventureForge viewers that prove useful at the table

### Core rule

> The cartridge knows the whole adventure. The save knows what the party has learned.

Player-facing tools must not expose unrevealed cartridge secrets.

### Exit criteria

A player can quickly answer questions such as:

> “What was the name of the person who sent us here?”

without opening raw module files or risking spoilers.

---

# Phase 10 — Attachments, Images, and Media

## Status: Not started

### Player/session media

- [ ] upload images
- [ ] preserve attachments in the save
- [ ] display media in conversation
- [ ] associate media with relevant transcript entries where useful

### Character portraits

- [ ] cartridge-supplied default
- [ ] player-uploaded override
- [ ] store override outside cartridge

### Adventure assets

- [ ] scene artwork
- [ ] handouts
- [ ] maps
- [ ] music cue references

### Exit criteria

Important visual/session material survives save/load and remains usable as AI and player context.

---

# Phase 11 — Session End and Resume Quality

## Status: Not started

### End Session

- [ ] deliberate End Session action
- [ ] save current transcript
- [ ] save Pilot conversation
- [ ] save current game state
- [ ] save discovered knowledge
- [ ] save attachments
- [ ] create/update AI resume checkpoint
- [ ] preserve open threads

### Resume Session

- [ ] reconstruct AI-DM context
- [ ] show current adventure state
- [ ] restore players
- [ ] allow any players to enable Pilot Mode
- [ ] continue without replaying the adventure opening

### Exit criteria

Ending and resuming feels like loading a saved game rather than reopening an old chat.

---

# Phase 12 — Packaging and Distribution

## Status: Deferred

Do this only after the web/server product works reliably.

Possible direction:

- [ ] package as a desktop application
- [ ] evaluate Tauri or similar lightweight wrapper
- [ ] one-click start
- [ ] automatic local server lifecycle
- [ ] real Exit behavior
- [ ] Windows packaging
- [ ] update mechanism

Do not let desktop packaging delay the core game runtime.

---

# Documentation Roadmap

Current / planned documentation:

```text
TableForge/
├── AGENTS.md
├── README.md
├── ROADMAP.md
├── prototypes/
│   └── TableForge-prototype-03-adventure-setup.html
└── docs/
    ├── SESSION-WORKFLOW.md
    ├── UI-UX.md
    ├── CARTRIDGE-SPEC.md
    ├── SAVE-SPEC.md
    ├── ARCHITECTURE.md
    └── DECISIONS.md
```

### Documentation status

- [x] `AGENTS.md`
- [x] `README.md`
- [x] `ROADMAP.md`
- [x] `docs/SESSION-WORKFLOW.md`
- [x] `docs/CARTRIDGE-SPEC.md`
- [ ] `docs/UI-UX.md`
- [ ] `docs/SAVE-SPEC.md`
- [ ] `docs/ARCHITECTURE.md`
- [ ] `docs/DECISIONS.md`

---

# Immediate Next Steps

Do these next, in order:

1. **Finish the Play Screen prototype**
   - collapsible left sidebar
   - shared chat feed
   - party/Ready sidebar
   - Pilot Mode controls
   - bottom composer

2. **Create `docs/UI-UX.md`**
   - capture the approved screens and interaction rules

3. **Create `docs/SAVE-SPEC.md`**
   - define the memory-card structure required for Load Adventure and AI resume

4. **Review the prototype as one complete flow**
   - Title
   - New Adventure
   - Validation
   - Setup
   - Play

5. **Begin converting the approved prototype into the real `web/` frontend**

6. **Implement real cartridge loading**

7. **Implement save creation/persistence**

8. **Implement shared table networking**

9. **Connect the AI-DM**

---

# Scope Discipline

Before adding a new feature, ask:

1. Does this solve a problem the group actually has?
2. Does it belong in TableForge rather than AdventureForge or a VTT?
3. Does it complicate normal player interaction?
4. Can it wait until after the core play loop works?
5. Does it preserve the cartridge/save boundary?
6. Does it risk exposing unrevealed adventure information?

If the answer suggests the feature is speculative, defer it.

The priority is always:

> **Get the table playing the adventure smoothly first.**
