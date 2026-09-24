# TableForge Decisions

**Status:** Living decision log  
**Target:** TableForge v2  
**Purpose:** Record settled product and architecture decisions so they are not repeatedly reconsidered during implementation.

This document is intentionally concise compared with the detailed specifications in `docs/`.

When a future decision supersedes one here, update this file rather than leaving contradictory guidance.

---

## D-001 — Keep the Product Name TableForge

**Decision:** The product remains **TableForge**.

The new implementation is internally referred to as TableForge v2, but the user-facing product name should normally be:

```text
TableForge
```

Do not put `v2` in the main product title unless version information is specifically needed.

**Reason:** The fundamental purpose of the product has not changed. AdventureForge creates the adventure and TableForge is where the group plays it.

---

## D-002 — AdventureForge Builds, TableForge Runs

**Decision:** Adventure generation remains the responsibility of AdventureForge.

TableForge consumes AdventureForge output and runs the adventure.

Do not duplicate AdventureForge adventure-generation logic inside TableForge.

**Model:**

```text
AdventureForge
      ↓
Adventure cartridge
      ↓
TableForge
      ↓
Playthrough save
```

---

## D-003 — Use the Cartridge / Console / Memory Card Model

**Decision:** The conceptual model is:

- AdventureForge = game developer
- Stage 2 package = cartridge
- TableForge = console
- AI-DM = runtime/DM
- save = memory card
- players = players

This analogy should guide both architecture and UI.

---

## D-004 — Cartridge and Save Stay Separate

**Decision:** The adventure cartridge and playthrough save are separate artifacts.

The cartridge contains authored adventure content.

The save contains mutable playthrough state.

Normal play must not modify the cartridge.

**Implication:** Opening an adventure does not import and rewrite the adventure into the save.

---

## D-005 — Cartridge Is Read-Only During Normal Play

**Decision:** Treat cartridge content as read-only.

Changes such as:

- discovered NPCs
- revealed maps
- combat outcomes
- world-state changes
- generated images
- player portrait overrides
- transcript history

belong in the save.

---

## D-006 — Save Is the Authoritative Playthrough Record

**Decision:** TableForge's own save is authoritative.

Do not rely on ChatGPT or another AI provider's conversation history as the campaign memory.

The save should preserve enough information to resume the game independently of the provider's old chat.

---

## D-007 — Stage 2 Output Is the Cartridge Source

**Decision:** AdventureForge Stage 2 output provides the primary authored adventure content.

Current expected artifacts include:

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

Assets such as maps, portraits, scenes, and handouts may also be included.

---

## D-008 — Add a Manifest to Future Cartridges

**Decision:** Future AdventureForge cartridge export should include:

```text
manifest.json
```

The manifest should identify:

- cartridge format
- format version
- cartridge/adventure ID
- title
- adventure version
- semantic resource bindings
- asset references

Until that exists, TableForge may use conservative filename detection with manual correction.

---

## D-009 — Required vs Optional Cartridge Resources

**Decision:** The initial preferred required resources are:

```text
manifest.json
module.md
run-data.json
```

During legacy/pre-manifest support, `module.md` and `run-data.json` are the required authored resources.

Other Stage 2 files are optional enhancements.

Missing required content blocks startup.

Missing optional content produces warnings only.

---

## D-010 — Pilot Is a Mode, Not a Permanent Role

**Decision:** There is no permanently assigned Director/Pilot.

Any trusted player may enable:

```text
Pilot Mode: On
```

on their client when supervisory controls are needed.

Any number of players may have Pilot Mode enabled simultaneously.

---

## D-011 — Do Not Build a Permissions Hierarchy Around Pilot

**Decision:** Pilot Mode is primarily a UI/control mode for a cooperative trusted group.

It is not intended to establish one authoritative human DM.

Pilot actions should still record who initiated them.

The server should prevent conflicting operations.

---

## D-012 — Pilot Controls Are Hidden During Normal Player Use

**Decision:** Normal players should see a simple table interface.

Pilot Mode reveals additional controls such as:

- Ask AI-DM
- Review Context
- Force Advance
- Resume AI-DM
- generation supervision

This is progressive disclosure, not a separate application.

---

## D-013 — Ask AI-DM Is Pilot-Only Initially

**Decision:** Direct operational AI-DM questions remain Pilot-only in the initial implementation.

A player who needs this capability may enable Pilot Mode.

This can be broadened later if real play shows that the extra toggle creates friction.

---

## D-014 — Pilot-to-AI-DM Conversation Is Separate From the Public Feed

**Decision:** Operational Pilot conversation does not automatically become table narration.

Pilot conversation:

- does not affect Ready automatically
- does not auto-advance
- is saved
- may later be included selectively in AI context
- may be visible to other Pilot-enabled players

---

## D-015 — Normal Play Uses One Shared Conversation

**Decision:** The primary play experience is a continuous shared conversation.

Do not require users to navigate scenes or manually choose reply targets.

Conceptually:

```text
AI-DM
player response(s)
AI-DM
player response(s)
...
```

Internal IDs may exist but remain implementation details.

---

## D-016 — Do Not Recreate v1 Scene Targeting

**Decision:** Do not reproduce v1 concepts such as:

- selected scene
- latest scene
- context scene
- manual scene target
- reply target selector

These concepts contributed to stale/mistargeted replies.

v2 uses an open conversational beat instead.

---

## D-017 — Ready Is a First-Class Player Action

**Decision:** Each active player has Ready / Unready.

Ready means:

> I am satisfied with what I have contributed to this beat, including contributing nothing. The AI-DM does not need to wait for me.

A player may send zero, one, or multiple messages before becoming Ready.

---

## D-018 — All Ready Auto-Advances Outside Combat

**Decision:** During normal exploration, investigation, and roleplay:

```text
all active players Ready
        ↓
TableForge snapshots context
        ↓
AI-DM generation begins
```

No extra Generate button is required for the normal path.

---

## D-019 — Pilot Has Force Advance

**Decision:** Pilot Mode includes a prominent Force Advance / Ready Override action.

This allows the table to continue when, for example, a player has stepped away but is still considered active.

Force Advance should require confirmation.

---

## D-020 — Snapshot Context Before Generation

**Decision:** When generation begins, TableForge takes a context snapshot.

Messages or edits that occur afterward must not silently alter the in-flight request.

This prevents timing-dependent context ambiguity.

---

## D-021 — New AI-DM Beat Resets Ready

**Decision:** After the AI-DM publishes a new table-facing response, active players become Not Ready for the new beat.

---

## D-022 — Context Review Is an Override Tool

**Decision:** Pilot users may inspect and adjust the context sent to the AI-DM.

Possible selectable context includes:

- player messages
- recent AI-DM messages
- Pilot conversation
- system summary
- structured state
- combat outcome
- attachments

Default behavior should work without opening this panel.

Do not make context review mandatory bookkeeping every beat.

---

## D-023 — Human Table Runs Combat

**Decision:** Mechanical combat remains human-controlled.

The group handles:

- initiative
- movement
- attacks
- damage
- HP
- conditions
- monster turns
- tactics

The AI-DM remains available for rules, intent, and monster behavior questions.

---

## D-024 — Combat Disables Ready Auto-Advance

**Decision:** During Combat Mode, all players becoming Ready does not automatically trigger the AI-DM.

Combat ends only when a Pilot explicitly selects:

```text
Resume AI-DM
```

---

## D-025 — TableForge Is Not a VTT by Default

**Decision:** Do not add the following unless later requested by actual play needs:

- initiative tracker
- battle map
- character sheets
- dice roller
- HP automation
- automated monster turns
- full rules engine

TableForge's purpose is orchestration of the shared AI-assisted game, not replacing a VTT.

---

## D-026 — Optimize Combat Cognitive Load, Not Necessarily Combat Quantity

**Decision:** The group likes combat and does not want it removed simply because it consumes significant session time.

Where AdventureForge/TableForge can help, focus on:

- simpler routine monsters
- explicit monster motivation
- fewer overly elaborate custom mechanics on ordinary enemies
- clearer progress
- smoother handoff

Do not assume fewer fights is the desired solution.

---

## D-027 — UI Mental Model Is ChatGPT + Discord

**Decision:** The Play Screen should combine:

- ChatGPT-like continuous conversation
- Discord-like layout familiarity

Use:

- top bar
- collapsible left sidebar
- main conversation
- collapsible right sidebar
- bottom composer/status area

---

## D-028 — Keep the Left Sidebar Small

**Decision:** Do not create many Discord-style channels merely because the UI has a Discord-like layout.

Initial concept:

```text
# table

REFERENCE
NPCs
Locations
World Notes

TOOLS
Cast Viewer
Module Viewer
Map

+ Add
```

Additional channels/tools should appear only when there is a real use case.

---

## D-029 — Right Sidebar Is Not Pilot Mode

**Decision:** The right sidebar contains normal shared table information such as:

- players
- Ready status
- presence
- quick reference

Pilot controls are added to the right sidebar when Pilot Mode is enabled.

The right sidebar itself is not a privileged area.

---

## D-030 — Major Play Regions Are Collapsible

**Decision:** The Play Screen should allow collapsing:

- left sidebar
- right sidebar
- bottom composer/status area

This lets the user reduce the app to a near-ChatGPT-like reading view when desired.

---

## D-031 — Title Screen Is Minimal

**Decision:** The opening screen contains only:

```text
TableForge

New Adventure
Load Adventure
Options
Exit
```

No tagline.

No version number in the title.

No dashboard widgets.

Each choice opens a separate screen.

---

## D-032 — New Adventure Validates Cartridge Before Setup

**Decision:** New Adventure follows:

```text
Insert Cartridge
→ Validate
→ Correct bindings if needed
→ Adventure Setup
→ Begin Adventure
```

Use red for missing required resources.

Use amber/yellow for missing optional resources.

---

## D-033 — Adventure Setup Does Not Assign a Pilot

**Decision:** Adventure Setup includes:

- save name
- players
- characters
- cartridge resource summary

It does not include a permanent Pilot selection.

---

## D-034 — Load Adventure Is the Memory Card Browser

**Decision:** Load Adventure lists saves/playthroughs.

If a save's cartridge is missing, prompt the user to locate it.

Do not silently replace or reconstruct the cartridge.

---

## D-035 — Player Reference Views Must Be Spoiler-Safe

**Decision:** The cartridge may contain secrets that players have not discovered.

Player-facing reference tools must show only known/revealed information.

Core rule:

> The cartridge knows the whole adventure. The save knows what the party has learned.

---

## D-036 — Maps Must Respect Acquisition / Reveal State

**Decision:** A map asset existing in the cartridge does not automatically make it player-visible.

Support the distinction between:

- Pilot/GM map
- player-facing revealed/acquired map

---

## D-037 — Cartridge Portraits Are Defaults, Not Permanent Player Data

**Decision:** A cartridge may provide a default portrait.

Players may override their portrait in TableForge.

The override belongs to player/save profile data and does not modify the cartridge.

---

## D-038 — Preserve Full Transcript Where Practical

**Decision:** The save should preserve:

- player messages
- AI-DM messages
- Pilot messages
- timestamps
- sessions
- important attachments

This is both campaign history and recoverable context.

---

## D-039 — Sent History Is Append-Oriented

**Decision:** Avoid silently mutating historical sent messages.

Corrections can initially be represented as later messages/state changes.

If editing is added later, original content should remain recoverable.

---

## D-040 — Preserve Enough State for Provider-Independent Resume

**Decision:** A save should contain enough context that TableForge can resume with a different AI provider later.

Provider-specific IDs or metadata may supplement the save but cannot be the only source of continuity.

---

## D-041 — Python Server Is the Initial Backend Direction

**Decision:** The initial production architecture uses a Python backend.

The backend owns:

- saves
- cartridges
- AI access
- session state
- networking
- context assembly

---

## D-042 — Browser Is the Player Client

**Decision:** Players interact with TableForge through a browser.

One host runs the server.

Other players should eventually connect over LAN without installing the backend.

---

## D-043 — API Keys Stay Server-Side

**Decision:** Never expose AI provider API keys in browser JavaScript.

Provider configuration and calls belong on the server.

---

## D-044 — SQLite Is the Initial Persistence Direction

**Decision:** SQLite remains the preferred starting point for structured TableForge persistence.

Do not retain the v1 schema merely for compatibility.

The v2 schema should model v2 concepts such as:

- saves
- sessions
- beats
- messages
- Pilot messages
- knowledge
- checkpoints

---

## D-045 — Prefer Server Push Over Hidden-Tab Polling

**Decision:** WebSocket or equivalent server-push behavior is the preferred long-term real-time architecture.

Do not repeat the v1 dependency on polling that stops when a ChatGPT browser tab is hidden.

Temporary polling is acceptable during early prototyping if needed.

---

## D-046 — Only One Table-Advancing AI Generation at a Time

**Decision:** The server must prevent concurrent advancement generations.

This includes races between:

- all-Ready auto-advance
- Force Advance
- Resume AI-DM
- multiple Pilot actions

The browser alone must not be trusted to prevent this.

---

## D-047 — Server Owns AI Context Assembly

**Decision:** Browser clients do not construct raw AI prompts.

Clients express intent and optional context selections.

The server builds the final AI-DM request.

---

## D-048 — Preserve AI Provider Abstraction

**Decision:** The AI layer should be abstracted behind a provider/service boundary.

Do not tightly couple the save, UI, or runtime state to one provider's API shape.

---

## D-049 — Start With Vanilla Frontend Technology

**Decision:** Plain HTML/CSS/JavaScript is acceptable for the first production frontend.

Do not introduce React, Vue, or another framework solely because the application is being rebuilt.

Adopt one later only if complexity justifies it.

---

## D-050 — Prototype Before Production Frontend Conversion

**Decision:** Continue using the single-file prototype to settle major UX behavior.

Prototype files belong in:

```text
prototypes/
```

Once the overall Play Screen is approved, stop expanding the monolithic prototype and convert it into maintainable production frontend code.

---

## D-051 — Prototype Location

**Decision:** The current prototype belongs at:

```text
prototypes/TableForge-prototype-03-adventure-setup.html
```

Future prototype iterations may remain in the same directory.

---

## D-052 — Documentation Layout

**Decision:** Project documentation should use:

```text
TableForge/
├── AGENTS.md
├── README.md
├── ROADMAP.md
├── prototypes/
└── docs/
    ├── SESSION-WORKFLOW.md
    ├── UI-UX.md
    ├── CARTRIDGE-SPEC.md
    ├── SAVE-SPEC.md
    ├── ARCHITECTURE.md
    └── DECISIONS.md
```

`AGENTS.md` provides implementation-agent guidance.

The files under `docs/` provide detailed product/technical specifications.

---

## D-053 — Build Vertically

**Decision:** Implement the application in vertical slices rather than building every backend subsystem first.

Preferred progression:

```text
Title
→ New Adventure
→ Validation
→ Adventure Setup
→ Play shell
→ Messages/Ready
→ Persistence
→ Mock AI
→ Real AI
→ Pilot
→ Combat
→ Reference views
```

This keeps progress visible and validates the real workflow early.

---

## D-054 — Do Not Over-Engineer Early

**Decision:** Defer speculative infrastructure such as:

- cloud accounts
- cloud sync
- public internet hosting
- plugin architecture
- microservices
- distributed databases
- complex migrations
- marketplace features
- VTT subsystems

The immediate product is a trusted local shared table.

---

# Superseding a Decision

When a settled decision changes:

1. update the affected decision in this file
2. note the new direction clearly
3. update any detailed spec that conflicts
4. update `AGENTS.md` if implementation guidance changes
5. avoid maintaining two contradictory active rules

The newest explicit product decision from the user takes precedence over this file.

---

# Current Highest-Priority Decisions

For implementation work, the most important rules are:

1. AdventureForge builds; TableForge runs.
2. Cartridge and save stay separate.
3. Pilot is a mode, not a role.
4. Normal play is one shared conversation.
5. Ready auto-advances outside combat.
6. Pilot can Force Advance.
7. Combat is human-run and resumes explicitly.
8. TableForge is not a VTT.
9. Player reference views must be spoiler-safe.
10. The save, not the AI provider's chat, is authoritative.
11. The server owns persistence and AI context.
12. Build the Play Screen next, then convert the approved prototype into the real frontend.
