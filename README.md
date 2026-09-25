# TableForge

TableForge is a shared runtime for playing AI-assisted tabletop RPG adventures created by AdventureForge.

## Run the first application build

Requires Python 3.10 or newer. From this repository:

```bash
python3 server.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in a browser. On Windows, `py server.py` also works. Use **New Adventure → Load ZIP** to select one cartridge containing `manifest.json`, `module.md`, and `run-data.json`. Review the files and bindings, add players, begin, choose your identity, and send a message. Sending marks that player Ready; players can still Ready without sending or Unready before generation. When everyone is Ready, the table advances in normal play. Without `TABLEFORGE_OPENAI_API_KEY`, the server uses a local mock AI-DM. Set `TABLEFORGE_OPENAI_API_KEY` on the host to use OpenAI; `TABLEFORGE_MODEL` defaults to `gpt-4o-mini`. The key stays on the server. **Load Adventure** restores the saved transcript and Ready state after restart. Data is stored in `data/` and excluded from Git.

New Adventure requires `manifest.json` with a title and reads its resource paths. It detects known filenames for undeclared roles, lists every file in the ZIP, and lets each resource selector correct a missing or mistaken path. Missing required resources and invalid selections block Begin Adventure. The selected bindings are saved with that playthrough, leaving the cartridge and other saves unchanged. Previously created saves can still locate their original pre-manifest cartridges.

For local network testing, launch with `python3 server.py --host 0.0.0.0` and use the host computer's LAN address. This initial server has no login or access control, so only expose it on a trusted network.

The current build provides real cartridge validation, SQLite saves, messages, Ready, Load Adventure, AI-DM advance (mock or OpenAI), and basic Pilot/Combat controls. In Pilot Mode, **Ask AI-DM** opens a saved operational conversation that does not appear in the public chat or change Ready. **End Session** records a checkpoint and closes the current session. Continue on an ended save starts the next session when a player joins; an open save resumes the same session after a restart. **Resume AI-DM** in Combat Mode asks for a short outcome note, saves it, and includes it in later AI context. If a cartridge is missing, Load Adventure offers **Locate ZIP** or **Locate Folder** and checks its contents against the original before restoring access. Attachments, spoiler-safe references and map rendering are still pending. The visual shell follows the approved Play Screen prototype; the older standalone prototypes remain in `prototypes/`.

Each player can click their portrait in the Party list to open the editor, then click its square preview to choose an image. Drag to position it and zoom before saving a square crop. PNG, JPEG, and WebP source images up to 20 MB are supported; the saved crop is a 320 × 320 image. The same preview can be clicked again to replace the image, and the editor can remove a saved portrait. Portraits are stored with the playthrough in `data/tableforge.sqlite3` (or the configured `TABLEFORGE_DATA` directory), and appear in the join screen, Party list, and table chat.

The Play Screen sidebar shows reported OpenAI tokens and an estimated USD cost for the current session and playthrough. Options shows totals across saved adventures. Tracking begins with requests made after this update; earlier API activity cannot be reconstructed from the save. Estimates use standard text prices dated 2026-09-25 in `metering.py`. Models without a known rate still show tokens, with cost marked unavailable. The OpenAI billing dashboard remains the source of truth for charges.

Run the HTTP workflow tests with `python3 -m unittest discover -s tests -v`.

The core model is simple:

- **AdventureForge** creates the adventure.
- **AdventureForge Stage 2 output** becomes the **cartridge**.
- **TableForge** is the **console**.
- **The TableForge save** is the **memory card**.
- **The AI-DM** runs the adventure.
- **Players** play their characters.
- **Pilot Mode** exposes supervisory controls when needed.

TableForge is designed for a cooperative table where the AI handles most narrative-DM work while the players collectively handle play, combat, rulings, reminders, and tactical decisions.

---

## Current Status

TableForge v2 is currently in design/prototyping.

The current direction is a standalone/shared web application rather than a Tampermonkey userscript embedded in ChatGPT.

The intended architecture is:

```text
Browser UI
    |
Python server
    |
SQLite / save data
    |
AI provider
```

The host runs TableForge locally, and other players may eventually connect over LAN through their browsers.

---

## Application Flow

TableForge starts like a game console:

```text
TableForge

New Adventure
Load Adventure
Options
Exit
```

### New Adventure

The user selects an AdventureForge cartridge.

TableForge validates the package, detects known Stage 2 resources, allows incorrect bindings to be fixed, and creates a new save when the adventure begins.

### Load Adventure

Loads an existing TableForge save and reconnects it to the cartridge it belongs to.

### Options

Application-wide settings such as:

- AI provider/model
- API configuration
- appearance
- storage
- LAN/network settings
- default player profile

### Exit

Closes the application in a packaged desktop build or returns to a shutdown state in the browser prototype.

---

## Cartridge Model

A cartridge is the authored adventure package produced by AdventureForge.

Current Stage 2 artifacts include:

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

The cartridge may also contain assets such as:

```text
assets/
    maps/
    portraits/
    scenes/
    handouts/
    audio/
```

TableForge should treat the cartridge as read-only during normal play.

The long-term goal is for AdventureForge to export one package such as:

```text
Dress-Rehearsal-at-Hollow-Well.tableforge.zip
```

with a `manifest.json` describing the resources inside.

See:

```text
docs/CARTRIDGE-SPEC.md
```

---

## Save / Memory Card

The save contains what happened during play.

It should preserve as much useful context as practical, including:

- full shared transcript
- player messages
- AI-DM messages
- Pilot-to-AI-DM messages
- session boundaries
- current adventure progress
- discovered NPCs and locations
- revealed maps
- combat outcomes
- current world state
- open threads
- images and attachments
- AI summaries/checkpoints where useful

The cartridge and save remain separate.

TableForge should not rely on an AI provider's chat history as the only campaign memory.

---

## Pilot Mode

Pilot is a **mode**, not a permanent role.

Any trusted player may enable Pilot Mode on their own client.

Any number of players may have Pilot Mode enabled at the same time.

Pilot Mode exposes controls such as:

- Ask AI-DM
- provide corrections/context
- review the context being sent
- Force Advance / Ready Override
- resume AI-DM after combat
- review/regenerate AI-DM output

Pilot Mode exists mainly to prevent accidental use of supervisory controls.

It is not intended as a strict permissions hierarchy.

---

## Ready System

Ready is a first-class part of normal play.

Ready means:

> I am satisfied with what I have contributed to this beat, including contributing nothing. The AI-DM does not need to wait for me.

A player may:

- send zero messages
- send one message
- send multiple messages
- Ready without sending anything
- Unready before generation begins
- continue editing or adding pending contributions while Ready

During normal exploration, investigation, and roleplay:

```text
all active players Ready
        ↓
TableForge snapshots the selected context
        ↓
AI-DM generates the next response
```

Pilot Mode provides a **Force Advance** control when the table wants to continue without waiting for every Ready state.

---

## Combat

Combat intentionally changes the control model.

When initiative is called:

```text
AI-DM
   ↓
Combat Mode
   ↓
Humans run combat
```

The table collectively handles:

- player turns
- monster turns
- damage
- HP
- conditions
- movement
- tactics
- monster behavior

TableForge is not intended to become a full VTT by default.

During combat:

- Ready may still be used
- all Ready does **not** auto-advance
- Pilot Mode may ask the AI-DM for rulings, tactics, or monster motivation
- a Pilot explicitly resumes the AI-DM after combat

The AI-DM then narrates the aftermath and normal play resumes.

---

## Play Screen UX

The intended play-screen design is:

**ChatGPT conversation behavior + Discord layout familiarity**

The main shell includes:

```text
Top bar
Left sidebar
Main shared conversation
Right sidebar
Bottom composer / Ready bar
```

All major regions should be collapsible.

### Main Area

A continuous shared conversation:

```text
AI-DM
player response(s)
AI-DM
player response(s)
...
```

Players should not manually manage scene IDs or reply targets.

### Left Sidebar

Keep this light.

Initial concepts:

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

Do not add multiple Discord-like channels without a real use case.

### Right Sidebar

Shared table information such as:

- party members
- connection state
- Ready state
- quick reference controls

When Pilot Mode is enabled, Pilot controls appear here as an additional section.

### Bottom Bar

Contains:

- message composer
- attachments
- Send
- Ready / Unready
- Pilot-only Force Advance

---

## Party Knowledge and Spoiler Safety

The cartridge may contain information the players have not discovered.

TableForge must distinguish between:

- what the cartridge knows
- what the save says the party has learned

Player-facing reference views should only show known information.

Examples:

- NPCs the party has met
- locations they know about
- world notes they have discovered
- maps that have been acquired or revealed

Raw module secrets, hidden motives, encounter data, unrevealed maps, and future content should not be exposed to ordinary player views.

Pilot Mode may expose additional authored information where appropriate.

---

## Reference Views

TableForge may surface AdventureForge resources through useful reference tools.

Examples:

### NPCs

Built from `cast.json`, `cast.md`, transcript knowledge, and save-state discovery.

### Locations

Derived from `run-data.json`, `module.md`, `scenes.json`, or future dedicated location data.

### World Notes

Derived from authored module information and what the party has actually learned.

### Module Viewer

Human-readable access to `module.md`, primarily for Pilot use.

### Cast Viewer

Uses the authored cast data.

### Map

Loads map assets from the cartridge.

Player-facing map visibility depends on whether the map has actually been acquired/revealed in the save.

---

## Development Principles

1. Build one vertical slice at a time.
2. Prefer simple implementations over speculative complexity.
3. Do not add features just because there is empty UI space.
4. Keep normal player interaction simpler than Pilot interaction.
5. Keep cartridge and save data separate.
6. Preserve session history where practical.
7. Keep AI-provider configuration server-side.
8. Never expose API keys in browser code.
9. Avoid silent AI actions that bypass human intent.
10. Avoid destructive mutation of historical messages unless explicitly designed later.
11. Keep the UI familiar and game-like without turning it into a full VTT.
12. AdventureForge builds adventures. TableForge runs them.

---

## Non-Goals

Unless later requirements change, TableForge is **not** intended to become:

- a VTT
- a character-sheet manager
- a dice roller
- an initiative tracker
- an encounter builder
- a rules compendium
- a replacement for AdventureForge
- a traditional adversarial hidden-information DM tool

The table is cooperative and may openly share monster information, remind one another of triggers, help make tactical decisions, and collectively operate monsters.

---

## Current Milestones

### 1. Title Screen

```text
New Adventure
Load Adventure
Options
Exit
```

### 2. New Adventure / Cartridge Validation

- select/drop cartridge files
- auto-detect Stage 2 resources
- flag missing required and optional resources
- allow manual correction

### 3. Adventure Setup

- save/playthrough name
- player list
- character assignments
- cartridge summary
- Begin Adventure

### 4. Play Screen

- collapsible app shell
- shared AI-DM feed
- reference/tools sidebar
- party/Pilot sidebar
- composer
- Ready system

### 5. Pilot Controls

- Ask AI-DM
- context review
- Force Advance
- combat handoff/resume

### 6. Save / Resume

- memory-card persistence
- Load Adventure
- reliable AI context restoration

---

## Project Documentation

Recommended project structure:

```text
TableForge/
├── AGENTS.md
├── README.md
├── ROADMAP.md
└── docs/
    ├── SESSION-WORKFLOW.md
    ├── UI-UX.md
    ├── CARTRIDGE-SPEC.md
    ├── SAVE-SPEC.md
    ├── ARCHITECTURE.md
    └── DECISIONS.md
```

Current key documents:

- `AGENTS.md` — coding-agent guidance and product invariants
- `docs/SESSION-WORKFLOW.md` — agreed play-session behavior
- `docs/CARTRIDGE-SPEC.md` — cartridge/package boundary and validation rules

---

## Historical Versions

For clarity:

- **TableForge Legacy / v0** — supervisory role called **Captain**
- **TableForge v1** — Tampermonkey relay version; supervisory role called **Director**
- **TableForge v2** — new standalone/shared runtime; supervisory controls called **Pilot Mode**

The product UI should normally display simply:

```text
TableForge
```

not `TableForge v2`.
