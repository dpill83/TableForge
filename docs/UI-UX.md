# TableForge UI/UX Specification

**Status:** Draft product design specification  
**Target:** TableForge v2  
**Purpose:** Define the screen structure, navigation, interaction model, and visual behavior for the new TableForge application.

---

## 1. Design Goal

TableForge should feel familiar immediately.

The primary UI reference is:

> **ChatGPT conversation behavior + Discord layout familiarity**

The application should not feel like a dense administrative dashboard or a traditional VTT.

The interface should prioritize:

- one shared conversation
- simple player participation
- lightweight Ready controls
- optional Pilot controls
- quick access to known NPCs, locations, maps, and adventure reference material
- collapsible sidebars and bottom controls
- game-like top-level navigation

The product should feel like opening a game and then sitting down at a shared digital table.

---

## 2. Core UX Principles

### Familiarity

Use interaction patterns users already understand:

- Discord-like left/right sidebars
- ChatGPT-like scrolling conversation
- persistent bottom composer
- game-style title screen
- simple Back navigation between setup screens

### Progressive complexity

Normal players should see a simple interface.

Pilot Mode should expose additional controls without replacing the entire layout.

Do not force every user to understand AI context management, combat handoff controls, or operational messages unless they want or need them.

### One main conversation

The shared table conversation is the primary experience.

Do not divide normal play into many channels, scene cards, or manually targeted threads.

### Minimal required interaction

A normal player should be able to play using only:

- the shared feed
- message composer
- Send
- Ready / Unready

### Collapsible regions

The main Play Screen should support collapsing:

- left sidebar
- right sidebar
- bottom composer/status area

When sidebars are collapsed, the experience should approach a simple ChatGPT-like conversation view.

---

# 3. Top-Level Application Navigation

TableForge starts on a minimal title screen.

```text
TableForge

New Adventure
Load Adventure
Options
Exit
```

Do not display:

- `v2`
- a tagline
- extra explanatory text
- recent games
- news
- promotional panels

The title screen should remain intentionally sparse.

Each menu option opens a separate full screen.

---

# 4. Title Screen

## Required elements

```text
TableForge

New Adventure
Load Adventure
Options
Exit
```

### Visual direction

- centered layout
- dark fantasy-inspired background or neutral dark background
- large TableForge title
- vertically stacked menu options
- subtle hover/focus state
- no unnecessary ornamentation

The background should be decorative only.

Buttons and text should be real UI elements, not baked into an image.

### Navigation behavior

- **New Adventure** → New Adventure screen
- **Load Adventure** → Load Adventure screen
- **Options** → Options screen
- **Exit** → close application in packaged builds or show a shutdown/closed state in browser development

---

# 5. New Adventure Screen

The New Adventure screen handles cartridge selection and validation.

## Initial state

```text
← Back

New Adventure

Insert Cartridge

Drop AdventureForge cartridge here
or
[ Browse Files ] [ Browse Folder ]
```

During development, folder/file selection is acceptable.

Long term, a single cartridge package should be preferred.

## After cartridge selection

TableForge should inspect the cartridge and auto-populate resource bindings.

Example:

```text
Adventure cartridge detected

ADVENTURE
✓ Module         module.md
✓ Run Data       run-data.json

REFERENCE
✓ Cast / NPCs    cast.json
✓ Scenes         scenes.json
✓ Continuity     continuity.json

MEDIA
✓ Map            random-dungeon.png
! Music          Missing - Optional
```

### Validation colors

- green/normal success state: detected
- red: missing required resource
- amber/yellow: missing optional resource

### Required behavior

Users must be able to correct any inferred binding.

Example:

```text
Map
[ random-dungeon.png ▼ ]
```

The Start/Continue action remains disabled when required resources are missing.

Optional resources never block startup.

---

# 6. Adventure Setup Screen

After cartridge validation, show Adventure Setup.

This screen creates the new playthrough/save.

## Required fields

### Adventure title

Auto-populated from cartridge metadata when available.

### Save name

Defaults to the adventure title.

Editable.

### Players

Display a list of player-to-character assignments.

Example:

```text
Player        Character

Dan           George
Dani          Ethereal
Ted           Viktor

[ Add Player ]
```

Each row should support:

- player name
- character name
- remove row

Do not require a Pilot assignment.

### Pilot explanation

Display a short informational section:

> No Pilot is assigned. Any player may enable Pilot Mode during play.

### Cartridge resource summary

Collapsed by default or placed below the player section.

Provides confidence that TableForge loaded the expected resources.

### Primary action

```text
[ Begin Adventure ]
```

Starting the adventure creates a save/memory-card record.

The cartridge itself remains unchanged.

---

# 7. Load Adventure Screen

The Load Adventure screen represents the memory-card browser.

Example:

```text
← Back

Load Adventure

Dress Rehearsal at Hollow Well
Session 2
Beeck Vaults
Last played Sep 20
[ Continue ]

Waterdeep: Dragon Heist
Session 18
Last played Aug 29
[ Continue ]
```

Each save card/list row may show:

- adventure title
- session number
- last-played date
- current location or short resume label when available
- cartridge status
- Continue

## Missing cartridge

If the save cannot find its cartridge:

```text
Dress Rehearsal at Hollow Well

Cartridge not found.

[ Locate Cartridge ]
```

Do not silently substitute another cartridge.

---

# 8. Options Screen

Options contains application-wide settings only.

Possible categories:

- AI provider
- AI model
- API configuration
- appearance
- storage location
- LAN/network settings
- default player profile
- default portrait
- accessibility/preferences

Game-specific settings should remain inside the adventure/session.

---

# 9. Main Play Screen

The Play Screen is the primary TableForge experience.

Its mental model is:

> **Discord shell + ChatGPT conversation**

Recommended layout:

```text
┌─────────────────────────────────────────────────────────────┐
│ TOP BAR                                                     │
├──────────────┬───────────────────────────────┬──────────────┤
│ LEFT         │ MAIN                          │ RIGHT        │
│ SIDEBAR      │ SHARED CHAT                   │ SIDEBAR      │
│              │                               │              │
│              │                               │              │
├──────────────┴───────────────────────────────┴──────────────┤
│ BOTTOM COMPOSER / READY BAR                                │
└─────────────────────────────────────────────────────────────┘
```

All major regions should be independently collapsible.

---

# 10. Top Bar

The top bar provides current-session identity and high-level controls.

Possible contents:

```text
☰
Dress Rehearsal at Hollow Well
Session 2
Normal Play / Combat Mode
Pilot Mode [Off/On]
Party Sidebar
```

## Recommended information

- adventure title
- save/session identifier
- current mode
- Pilot Mode toggle
- left sidebar toggle
- right sidebar toggle

Avoid filling the top bar with minor controls.

---

# 11. Left Sidebar

The left sidebar should start intentionally small.

Do not copy Discord's channel model just because the layout resembles Discord.

Initial structure:

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

## `# table`

Represents the primary shared conversation.

There is only one required channel at launch.

Additional channels may be supported later if a real use case appears.

## Reference

Reference views are player-safe information the party is allowed to know.

### NPCs

Fast lookup for questions such as:

> What was the name of the person who sent us here?

### Locations

Known or visited locations.

### World Notes

Discovered lore, factions, terms, and other useful facts.

## Tools

May expose existing or adapted AdventureForge viewers.

Initial candidates:

- Cast Viewer
- Module Viewer
- Map

### `+ Add`

Reserved for future tools/channels.

Do not populate speculative features by default.

---

# 12. Main Shared Feed

The main area is a continuous conversation.

Example:

```text
AI-DM
The concealed slab gives one final metallic groan...

George
I raise my shield and step through.

Viktor
I follow George.

Ethereal
I check the floor and ceiling for another trap.
```

## Message presentation

Each message should clearly show:

- sender
- portrait/avatar when available
- timestamp
- message content
- attachments/images when present

AI-DM messages should be visually distinguishable without being excessively stylized.

Player messages should remain easy to scan.

## No scene targeting

Do not expose:

- scene IDs
- manual reply target selectors
- scene navigation required for normal play

Internally, TableForge may track beats/scenes/messages.

The user should experience a single current conversation.

---

# 13. Bottom Composer

The bottom area should feel familiar to Discord/ChatGPT users.

Example:

```text
[ + ]  Message #table...

                     [ Send ]

George: Not Ready     [ Ready ]
```

## Required controls

- text composer
- attachment action
- Send
- Ready / Unready

## Optional status text

Examples:

```text
Waiting for table
2 of 3 Ready
All Ready - AI-DM generating
Combat Mode - auto-advance paused
```

The bottom area should remain compact.

It should not become an AI context-management dashboard.

---

# 14. Ready / Unready UX

Ready is visible and easy to understand.

A player presses Ready when:

> “I am done contributing to this beat.”

Ready does not imply:

- they submitted exactly one message
- they took a turn
- they cannot edit further

## Behavior

A Ready player may:

- send another message
- edit pending content
- Unready

When all active players are Ready during normal play:

```text
All Ready
→ snapshot context
→ AI-DM begins generation
```

When generation begins:

- current context is frozen for that request
- Ready states reset for the upcoming beat
- later messages should not silently alter an in-flight generation

---

# 15. Right Sidebar

The right sidebar is a shared table-status area.

It is **not** itself Pilot Mode.

Initial structure:

```text
PARTY

George      Ready
Ethereal    Ready
Viktor      Not Ready

QUICK REFERENCE

NPCs
Locations
World Notes
```

Possible player details:

- portrait
- player name
- character name
- online/offline
- Ready state

---

# 16. Character Portraits

Portraits may come from two places:

1. cartridge defaults
2. player-specific override

If the cartridge provides a character portrait, use it as the default.

A player should eventually be able to change their own portrait without modifying the cartridge.

Profile editing should initially use a lightweight:

- modal
- drawer
- small settings panel

Do not create a dedicated major screen unless needed later.

---

# 17. Pilot Mode

Pilot Mode is toggled per player.

Example:

```text
Pilot Mode [ OFF / ON ]
```

Enabling it should reveal additional controls without replacing the entire screen.

## Pilot controls

Suggested right-sidebar section:

```text
PILOT CONTROLS

Ask AI-DM
Review Context
Force Advance
Combat Mode / Resume AI-DM
```

Pilot controls should be visually separated from normal party/reference controls.

---

# 18. Ask AI-DM

Initially, Ask AI-DM is Pilot-only.

The interaction opens or switches to an operational AI-DM console.

Examples:

- What would Shenka do here?
- Does Viktor blocking the exit change her move?
- What rule applies here?
- Mervin is unconscious, not dead. Correct your state.

This conversation should:

- not automatically appear in the public table feed
- not change Ready state
- not automatically advance the scene
- be saved in the playthrough

Multiple users with Pilot Mode may view/use the same operational console.

A future version may allow non-Pilot direct AI-DM questions, but this should not be included initially.

---

# 19. Review Context

Context review should be available to Pilot users but hidden during normal play.

Possible presentation:

```text
Next AI-DM Context

[x] George messages
[x] Ethereal messages
[x] Viktor messages
[ ] Pilot AI-DM conversation
[x] System summary
[x] Relevant state
```

Default behavior should require no manual changes.

Context review exists for exceptions.

Do not force the Pilot to inspect this before every advance.

---

# 20. Force Advance

Force Advance overrides remaining Ready requirements.

Example:

```text
George      Ready
Ethereal    Ready
Viktor      Not Ready

[ Force Advance ]
```

Because this affects the entire table, it should require confirmation.

Possible confirmation:

```text
Advance without waiting for all players?

[ Cancel ] [ Force Advance ]
```

Do not use confirmation for normal all-Ready auto-advance.

---

# 21. Combat Mode

When initiative is called, TableForge enters Combat Mode.

The UI should make this state obvious without transforming into a VTT.

Example status:

```text
COMBAT MODE
Auto-advance paused
```

## During combat

Players continue using their normal external/table combat process.

TableForge may show:

- player Ready states
- AI-DM operational access for Pilot users
- combat status
- Resume AI-DM control

Do not add by default:

- initiative tracker
- HP tracker
- battle map
- automated monster turns
- dice roller
- character sheet

---

# 22. Resume AI-DM

Combat never resumes automatically just because all players are Ready.

Pilot Mode must explicitly hand control back.

Example:

```text
[ Resume AI-DM ]
```

Before resume, TableForge may allow a short combat-outcome summary/context review.

Possible information:

- enemies defeated
- enemies escaped
- NPC deaths
- party condition
- important resources spent
- loot
- unusual outcomes

The AI-DM then narrates the aftermath and normal Ready behavior returns.

---

# 23. Reference Views and Party Knowledge

The cartridge may contain spoilers.

Reference views must not expose everything simply because it exists in cartridge data.

Core rule:

> **The cartridge knows the whole adventure. The save knows what the party has learned.**

Player-facing reference tools should use discovered/known information.

---

# 24. NPC Viewer

The NPC viewer should prioritize fast recall.

Example:

```text
NPCs

Sybil Peti
Known
Cheese-factor from Gillian's Hill.
Hired the party to investigate the impostors.

Lorie Eachelle
Known
Sexton of Hollow Well.
```

Useful features:

- search
- portrait
- name
- player-safe description
- location association
- last relevant interaction

Do not expose:

- secret motives
- future appearances
- hidden allegiance
- encounter statistics
- unrevealed module information

---

# 25. Locations Viewer

Example:

```text
Locations

Gillian's Hill
Visited
Market village south of Waterdeep.

Hollow Well
Visited
Small settlement with several abandoned homes.

Beeck Vaults
Current
Vault complex beneath the graveyard.
```

Useful information:

- known/visited status
- player-safe notes
- related NPCs
- maps when acquired

---

# 26. World Notes

World Notes stores discovered information that does not fit cleanly into NPCs or locations.

Examples:

- factions
- rumors
- named objects
- lore
- contracts
- discovered terminology
- unresolved mysteries

The system may derive entries from cartridge data and transcript/save state.

---

# 27. Map UX

Map visibility must respect discovery.

A map existing in the cartridge does not mean all players can see it.

Possible access:

### Pilot map

Pilot-only authored map.

May contain:

- room numbers
- secret doors
- hidden areas
- encounter labels

### Player map

Visible only after acquisition/reveal.

May be:

- a clean map
- handout
- player version
- discovered area map

The Map tool should appear disabled, hidden, or limited when no player-facing map has been acquired.

---

# 28. Module Viewer

The module viewer presents `module.md`.

This is primarily a Pilot/reference tool.

It should not automatically expose the full module to ordinary players.

Possible behavior:

- visible only in Pilot Mode
- or player mode receives only known excerpts

The exact behavior may be refined later.

---

# 29. Cast Viewer

The Cast Viewer may use:

- `cast.json`
- `cast.md`

It should distinguish:

- full authored cast
- player-known cast

Pilot Mode may access the authored cast.

Normal player views should default to known NPCs.

---

# 30. Images and Attachments

The shared feed should support images and attachments.

Examples:

- generated scene art
- maps
- screenshots
- player-created references
- handouts

Important media should be preserved in the save.

Images should remain associated with the message/session context where they were shared.

---

# 31. Collapse Behavior

The user should be able to collapse:

### Left sidebar

Leaves more space for chat.

### Right sidebar

Hides party/reference/Pilot controls.

### Bottom composer

Useful when reading history or reviewing a long AI-DM response.

### Both sidebars

Produces a simple ChatGPT-like layout.

Collapsed state should be remembered locally when practical.

---

# 32. Responsive Behavior

The primary target is desktop/laptop use.

However, the UI should degrade gracefully on smaller screens.

Possible mobile/tablet behavior:

- sidebars become drawers
- main chat stays primary
- bottom composer stays accessible
- Party/Pilot controls move behind a button
- no horizontal page scrolling

LAN-connected players should be able to use a browser without installing a separate desktop client.

---

# 33. Visual Style

The application should feel game-like without becoming ornate or hard to read.

Recommended direction:

- dark background
- subtle fantasy influence
- restrained warm accent
- modern readable typography
- clear interaction states
- low visual noise

Avoid:

- over-decorated fantasy borders
- excessive parchment textures
- glowing effects everywhere
- tiny stylized fonts
- dashboard-like card overload

The title screen may be more cinematic.

The Play Screen should prioritize readability for multi-hour sessions.

---

# 34. Accessibility

Minimum expectations:

- keyboard-focus states
- readable contrast
- buttons with text labels or accessible names
- no essential hover-only controls
- sufficiently large click targets
- clear status changes
- Ready state not communicated by color alone
- sidebar controls usable without precise mouse interaction

---

# 35. Prototype Strategy

Prototype files belong in:

```text
prototypes/
```

Current prototype:

```text
prototypes/TableForge-prototype-03-adventure-setup.html
```

The prototype may keep HTML, CSS, and JavaScript in one file while the product flow is being designed.

Do not treat the prototype as production architecture.

Once the overall UX is approved, stop expanding the monolithic prototype and convert it into a maintainable frontend.

---

# 36. Production Frontend Direction

Suggested structure:

```text
web/
├── index.html
├── styles/
│   └── app.css
├── js/
│   ├── app.js
│   ├── api.js
│   ├── state.js
│   ├── cartridge.js
│   └── screens/
│       ├── title.js
│       ├── new-adventure.js
│       ├── adventure-setup.js
│       ├── load-adventure.js
│       ├── options.js
│       └── play.js
└── assets/
```

Do not introduce a frontend framework unless the real implementation clearly benefits from one.

---

# 37. Initial Screen Map

```text
TITLE
│
├── New Adventure
│      │
│      ├── Insert Cartridge
│      ├── Validate Resources
│      └── Adventure Setup
│             │
│             └── Begin Adventure
│                    │
│                    └── PLAY
│
├── Load Adventure
│      │
│      └── Select Save
│             │
│             └── PLAY
│
├── Options
│
└── Exit
```

Inside Play:

```text
PLAY
│
├── Shared Table Feed
├── Ready System
├── Reference
│      ├── NPCs
│      ├── Locations
│      ├── World Notes
│      └── Map
├── Tools
│      ├── Cast Viewer
│      └── Module Viewer
└── Pilot Mode
       ├── Ask AI-DM
       ├── Review Context
       ├── Force Advance
       └── Combat / Resume AI-DM
```

---

# 38. Open UX Questions

These are intentionally unresolved:

1. Exact visual style of the Play Screen.
2. Whether Reference and Tools both belong in the left sidebar or some become right-sidebar quick actions.
3. Exact Player Profile / portrait editing interaction.
4. Whether the Pilot console appears as a left-sidebar item, drawer, side panel, or separate chat view.
5. Whether AI-DM drafts require explicit Pilot publish every time or publish automatically during normal play.
6. Exact attachment/image picker behavior.
7. Exact map viewer behavior.
8. Whether users may create custom channels later.
9. Whether the bottom composer can be fully collapsed during active play.
10. Exact mobile layout.

Do not resolve these by assumption during implementation if they materially change the agreed workflow.

---

# 39. UI Invariants

Unless explicitly changed later:

1. The title screen remains minimal.
2. New Adventure, Load Adventure, Options, and Exit are separate screens.
3. Normal play uses one primary shared conversation.
4. Players do not manually target scene IDs.
5. Ready is simple and always available during normal play.
6. Pilot Mode adds controls rather than replacing the whole interface.
7. The right sidebar is not synonymous with Pilot Mode.
8. The left sidebar starts small.
9. Multiple channels are not required at launch.
10. Cartridge secrets must not leak into player-facing reference views.
11. Combat does not turn TableForge into a VTT.
12. All major Play Screen regions should be collapsible.
13. The Play Screen prioritizes readability over decoration.
