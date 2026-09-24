# AGENTS.md

## Project

**TableForge v2**

TableForge is a shared runtime for playing AI-assisted tabletop RPG adventures created by AdventureForge.

This is the next major TableForge implementation. Historical naming:

- TableForge Legacy / v0: supervisory role was **Captain**
- TableForge v1: current Tampermonkey relay; supervisory role is **Director**
- TableForge v2: new standalone/shared runtime; supervisory controls are **Pilot Mode**

Do not label the product UI as “TableForge v2” unless specifically requested. The product name shown to users is simply **TableForge**.

---

## Product Model

Use the game-console analogy as the primary architectural model:

- **AdventureForge** creates the adventure.
- **AdventureForge Stage 2 output** is the **cartridge**.
- **TableForge** is the **console**.
- **The TableForge save** is the **memory card**.
- **The AI-DM** runs the adventure.
- **Players** play their characters.
- **Pilot Mode** exposes supervisory controls.

The cartridge and save are separate.

### Cartridge

The cartridge is the AdventureForge-authored adventure package.

It should be treated as read-only during normal play.

Expected Stage 2 artifacts currently include:

- `module.md`
- `run-data.json`
- `continuity.json`
- `cast.md`
- `cast.json`
- `scenes.json`
- `music-cues.json`
- `map-art-brief.md`
- map/image assets such as `random-dungeon.png`

A future cartridge may be a `.zip` or dedicated package format containing a manifest.

TableForge should open/mount the cartridge, not permanently absorb or mutate it.

### Save / Memory Card

The save contains what happened during play.

Preserve as much useful context as practical, including:

- full table transcript
- player messages
- AI-DM messages
- Pilot-to-AI-DM messages
- session boundaries
- adventure progress
- discovered information
- NPC and location knowledge
- combat outcomes
- current world state
- open threads
- images and attachments
- AI summaries/checkpoints where useful

Do not rely on an AI provider's chat history as the permanent campaign record.

---

## Current Product Direction

TableForge v2 is a standalone/shared web application rather than a Tampermonkey UI embedded in ChatGPT.

Initial architecture direction:

```text
Browser UI
    |
Python server
    |
SQLite / save data
    |
AI provider
```

The host runs TableForge locally. Other players may eventually connect over LAN using their browsers.

Do not prematurely introduce a large frontend framework unless the project actually needs one. Plain HTML/CSS/JavaScript is acceptable for the initial implementation.

The current prototype screens are intentionally simple.

---

## Top-Level Application Flow

The application starts at a game-like title screen.

```text
TableForge

New Adventure
Load Adventure
Options
Exit
```

Each choice opens a separate screen.

### New Adventure

The user inserts/selects an AdventureForge cartridge.

TableForge should:

1. inspect the package
2. detect known Stage 2 artifacts
3. auto-populate resource bindings
4. show missing required resources clearly
5. show missing optional resources without blocking play
6. allow incorrect bindings to be corrected manually
7. create a new save only when the user starts the adventure

Use:

- **red** for missing required content
- **amber/yellow** for missing optional content
- normal/success state for correctly detected content

A future manifest should make this deterministic instead of relying on filename guessing.

### Load Adventure

This is the memory-card/save browser.

A save should identify the cartridge it belongs to.

If the cartridge cannot be found, prompt the user to locate the cartridge rather than silently reconstructing or copying it.

### Options

Application-wide configuration belongs here, such as:

- AI provider/model
- API configuration
- appearance
- storage location
- network/LAN settings
- default player profile

Game-specific settings belong with the adventure/session instead.

### Exit

In a normal browser prototype, Exit may only show a closed/shutdown state.

If TableForge is later packaged as a desktop application, Exit may close the application normally.

---

## Adventure Setup

After cartridge validation, show an Adventure Setup screen before entering play.

Initial setup should support:

- save/playthrough name
- detected adventure title
- player list
- player-to-character assignments
- adding/removing players
- cartridge resource summary
- Begin Adventure

Do **not** require choosing a permanent Pilot.

---

## Pilot Mode

Pilot is a **mode**, not a permanent role.

Every trusted player may enable or disable Pilot Mode on their own client.

Any number of players may have Pilot Mode enabled simultaneously.

Pilot Mode exposes supervisory controls such as:

- Ask AI-DM
- provide correction/context
- review context being sent
- Force Advance / Ready Override
- resume AI-DM after combat
- review/regenerate AI-DM output

Pilot Mode is primarily a UI safety measure so players do not accidentally use supervisory controls.

It is not intended to create a permissions hierarchy among the trusted group.

Record which player initiated Pilot actions.

Prevent conflicting actions such as two simultaneous generations.

---

## Play Screen UX

The intended play-screen mental model is:

**ChatGPT conversation behavior + Discord layout familiarity**

Use:

- top menu/header bar
- collapsible left sidebar
- main shared chat area
- collapsible right sidebar
- collapsible bottom composer/status bar

Do not make the UI a dashboard full of unrelated cards.

### Main Area

The main area is a continuous shared conversation.

Do not require players to manually navigate or target numbered scenes during normal play.

The normal visible flow is:

```text
AI-DM
player response(s)
AI-DM
player response(s)
...
```

Internal scene/message IDs may exist, but ordinary users should not manage them.

### Left Sidebar

Keep this intentionally light.

Initial useful content may include:

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

Do not invent multiple Discord-like channels without a real use case.

Additional channels/tools may be added later.

AdventureForge viewer concepts may be reused when useful.

### Right Sidebar

The right sidebar is **not** Pilot Mode.

It should contain normal shared table information, such as:

- party members
- connection/presence
- Ready state
- quick reference controls

When Pilot Mode is enabled, add Pilot Controls to this sidebar.

### Bottom Bar

The bottom bar contains:

- message composer
- attachments
- Send
- Ready / Unready
- Pilot-only Force Advance when Pilot Mode is enabled

---

## Ready System

Ready is a first-class part of normal play.

Ready means:

> “I am satisfied with what I have contributed to this beat, including contributing nothing. The AI-DM does not need to wait for me.”

A player may:

- send zero messages
- send one message
- send multiple messages
- Ready without sending anything
- Unready before generation begins
- continue editing/adding pending contributions while Ready

When a new AI-DM beat begins, active players become Not Ready.

### Automatic Advance

During normal exploration, investigation, and roleplay:

- when all active players are Ready, TableForge may automatically advance to AI-DM generation

The number of active players does not matter.

One player can satisfy readiness if only one player is active.

If a disconnected player remains marked active, Pilot Mode provides the override. Do not build an elaborate presence system solely for this edge case.

### Force Advance

Pilot Mode exposes a prominent Force Advance / Ready Override control.

It means:

> Continue using the currently selected context without waiting for every remaining Ready state.

Guard this action against accidental activation.

---

## Advance Context

Default behavior should be simple:

- include all current-beat player messages
- include the minimum system/AI context needed to continue correctly

Pilot users should be able to inspect and adjust what is sent.

Possible context items:

- player messages
- Pilot-to-AI-DM conversation
- system summary
- relevant structured game state
- combat outcome
- attachments
- recent AI-DM context

Context review is an override/inspection tool, not mandatory bookkeeping every turn.

---

## Pilot-to-AI-DM Conversation

Pilot Mode includes a separate operational conversation with the AI-DM.

Examples:

- rules question
- monster behavior question
- correction
- state clarification
- reminder
- tactical intent question

This conversation:

- does not automatically advance the table
- does not affect Ready state
- does not automatically become public roleplay narration
- should be saved
- may be visible to other users who also have Pilot Mode enabled

Initially, direct Ask AI-DM access remains Pilot-only.

Do not expand it to all players unless later playtesting justifies it.

---

## Combat

Combat intentionally changes the control model.

When initiative is called, TableForge enters Combat Mode.

Humans run combat.

TableForge should not become a full VTT by default.

Do not add initiative tracking, automated monster turns, character-sheet management, dice engines, HP automation, or tactical automation unless specifically requested later.

During combat:

- players may still use Ready
- all Ready must **not** auto-advance
- AI-DM remains available to Pilot Mode for rulings, tactics, and monster motivation
- Pilot explicitly resumes the AI-DM after combat

On resume, send the relevant combat outcome/context and let the AI-DM narrate the aftermath.

---

## Party Knowledge / Spoiler Safety

The cartridge may contain information the players have not discovered.

Do not expose raw cartridge knowledge directly to ordinary players.

TableForge should eventually distinguish:

- what the cartridge knows
- what the save says the party has learned

Reference views such as NPCs, Locations, World Notes, Maps, Items, etc. should show player-safe discovered information.

Example:

```text
NPC: Sybil Peti
Known

Cheese-factor from Gillian's Hill.
Hired the party to stop impostors using their names.
```

Do not expose secret module notes, future appearances, hidden motives, encounter data, or unrevealed DCs.

### Maps

A map asset existing in the cartridge does not automatically mean players can see it.

Support the distinction between:

- Pilot/GM map from the cartridge
- player-facing map acquired/revealed during play

Player-facing maps should appear only when the save indicates they have been acquired or revealed.

---

## Player Profiles and Portraits

Player/character portraits may come from:

1. cartridge defaults
2. player-specific overrides

A player should eventually be able to upload/change their portrait without modifying the cartridge.

Use cartridge artwork as the default when available.

Keep profile editing lightweight, such as a modal or drawer, unless the feature grows enough to justify a dedicated screen.

---

## Existing v1 Lessons

Do not reproduce v1's scene-targeting complexity in the new UI.

Known v1 problems included:

- selected scene could differ from latest scene
- reply target could differ from what the player thought was current
- direct-entry replies could inherit stale context
- users had to reason about scene IDs and reply targeting

v2 should avoid this entire class of problem by using a current open response window / beat rather than manual scene targeting.

Keep sent history durable and append-oriented unless a later design explicitly changes this.

---

## AI-DM / AdventureForge Relationship

AdventureForge Stage 3 already defines the general AI-DM philosophy.

TableForge should consume that philosophy rather than re-inventing it.

Important behavior:

- AI-DM handles narration and NPCs
- humans run combat
- AI-DM can answer rules/tactics questions
- the table can collectively control monsters fairly
- AI-DM resumes narration after combat
- declared actions should not be repeatedly re-confirmed
- certain unopposed outcomes should be resolved rather than stretched across repeated checks

Do not duplicate AdventureForge adventure-generation logic inside TableForge.

AdventureForge builds adventures.

TableForge runs them.

---

## Non-Goals

Unless explicitly requested, do not turn TableForge into:

- a VTT
- a character-sheet manager
- a dice roller
- an initiative tracker
- an encounter builder
- a rules compendium
- a replacement for AdventureForge
- a traditional hidden-information adversarial DM tool

The group deliberately plays cooperatively and openly.

Players may remind one another of triggers, help make tactical decisions, and collectively operate monsters.

Design for that style.

---

## Development Principles

1. Prefer the simplest implementation that supports the agreed workflow.
2. Build one vertical slice at a time.
3. Do not add speculative features merely because there is empty UI space.
4. Keep ordinary player interaction simpler than Pilot interaction.
5. Preserve cartridge/save separation.
6. Preserve full session history where practical.
7. Keep AI-provider concerns behind server-side interfaces.
8. Never expose API keys in client-side code.
9. Avoid silent AI actions that bypass human intent.
10. Avoid destructive mutation of historical messages unless explicitly designed later.
11. Prefer explicit, understandable state transitions over clever automation.
12. Keep the UI familiar and game-like without over-gamifying core chat interaction.

---

## Current Implementation Milestones

The current design/prototype sequence is:

1. **Title Screen**
   - New Adventure
   - Load Adventure
   - Options
   - Exit

2. **New Adventure / Cartridge Validation**
   - select/drop cartridge files
   - auto-detect known Stage 2 resources
   - flag missing required/optional resources
   - allow manual correction

3. **Adventure Setup**
   - save name
   - player/character assignments
   - resource summary
   - Begin Adventure

4. **Play Screen**
   - collapsible shell
   - shared AI-DM feed
   - left reference/tools sidebar
   - right party/Pilot sidebar
   - bottom composer
   - Ready system

5. **Pilot Controls**
   - Ask AI-DM
   - context review
   - Force Advance
   - combat handoff/resume

6. **Save / Resume**
   - memory-card persistence
   - Load Adventure
   - reliable AI context restoration

Do not skip ahead and build a large backend or framework before the current vertical slice is understood.

---

## Source of Truth

When product behavior conflicts with older TableForge v1 assumptions, use the current v2 workflow decisions in this file unless the user explicitly changes them.

When implementation details are unclear:

1. inspect the actual repository
2. preserve existing working behavior when compatible
3. ask before making a product decision that changes the agreed workflow
4. do not invent requirements merely to complete a screen

The primary objective is to build the agreed TableForge experience, not to preserve legacy architecture for its own sake.
