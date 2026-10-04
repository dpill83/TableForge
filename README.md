# TableForge

TableForge is a shared runtime for playing AI-assisted tabletop RPG adventures created by AdventureForge.

## Run the first application build

Requires Python 3.10 or newer. From this repository:

```bash
python3 server.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in a browser. On Windows, `py server.py` also works. Use **New Adventure → Load ZIP** to select one cartridge containing `manifest.json`, `module.md`, and `run-data.json`. Review the files and bindings, add players, begin, choose your identity, and send a message. Sending marks that player Ready; players can still Ready without sending or Unready before generation. When everyone is Ready, the table advances in normal play. Without `TABLEFORGE_OPENAI_API_KEY`, the server uses a local mock AI-DM. Set `TABLEFORGE_OPENAI_API_KEY` on the host to use OpenAI; `TABLEFORGE_AIDM_MODEL` defaults to `gpt-4o-mini`. The key stays on the server. **Load Adventure** restores the saved transcript and Ready state after restart. Data is stored in `data/` and excluded from Git.

New Adventure requires `manifest.json` with a title and reads its resource paths. It detects known filenames for undeclared roles, lists every file in the ZIP, and lets each resource selector correct a missing or mistaken path. Missing required resources and invalid selections block Begin Adventure. The selected bindings are saved with that playthrough, leaving the cartridge and other saves unchanged. Previously created saves can still locate their original pre-manifest cartridges.

### AI-DM runtime instructions

New adventures use the **Stage 3 prompt supplied by their cartridge**, with a
small TableForge integration layer for Pilot Mode and the shared conversation.
AdventureForge's exporter includes its current prompt and binds it through
`resources.stage3Prompt` in `manifest.json`. New saves require this resource.
The first authorized AI-DM advance starts the opening sequence; later advances
continue it. Each save retains its exact instructions across restarts and updates.
Older saves keep their previous instructions until a player explicitly upgrades
them through **Pilot Mode → Review Context → Use cartridge instructions for this save…**.
See [AI-DM prompt integration](docs/AI-DM-PROMPTS.md) for source provenance,
context behavior, save migration, and the upgrade procedure.

### Keep your API key between restarts

Create a `.env` file alongside `server.py` (copy `.env.example` if needed), then enter your key locally:

```dotenv
TABLEFORGE_OPENAI_API_KEY=your-api-key-here
```

TableForge loads this file at startup, including when launched from another working directory. Restart the server after editing it. The same key is used for narration and scene images. Optional settings are `TABLEFORGE_AIDM_MODEL`, `TABLEFORGE_ROUTER_URL`, `TABLEFORGE_IMAGE_MODEL`, and `TABLEFORGE_DATA`; examples are in `.env.example`.

Variables already set in the launching terminal take precedence over `.env`, including empty values. To use the file instead of a previously entered PowerShell key, remove the terminal override with `Remove-Item Env:TABLEFORGE_OPENAI_API_KEY -ErrorAction SilentlyContinue`, or launch from a new terminal.

`TABLEFORGE_MODEL` is still accepted as a legacy fallback. If both model settings are nonempty, `TABLEFORGE_AIDM_MODEL` wins. Browse the [OpenAI model catalog](https://developers.openai.com/api/docs/models) for narration models and the [image model guide](https://developers.openai.com/api/docs/guides/image-prompting) for image models. Copy the API model ID into the appropriate setting and restart TableForge. Narration currently uses Chat Completions, so choose a text-output model that supports that endpoint; images use the Image API.

The `.env` file is plain text, excluded from Git, and outside the browser-served `web/` directory. Keep it private. The loader supports `KEY=value`, optional quotes, and comments; values are literal, so Windows paths work without escaping backslashes. Do not paste PowerShell assignment commands into `.env`.

### Optional LAN model routing

Set `TABLEFORGE_ROUTER_URL=http://10.0.0.22:8001/route` in `.env` and restart to route OpenAI text requests. An unset or blank value preserves the configured model and existing behavior. The router receives `POST {"prompt":"..."}` containing a task description capped at 2,400 characters: purpose (`advance`, `ask`, or `summary`), bounded recent player/Pilot requests, and brief relevant reply/combat context. It receives no cartridge, full transcript, API key, or generation prompt. These snippets can contain private Pilot information, so use a trusted router.

The returned `model` selects the Chat Completions model for that request. A failed request, 4-second socket timeout, malformed/oversized response, or missing/invalid model falls back to `TABLEFORGE_AIDM_MODEL` (then legacy `TABLEFORGE_MODEL`, then the existing default). No retries are made. Mock narration and image generation are unaffected. Routing metadata is attached to `GeneratedText.routing`: `enabled`, `tier`, router-selected `model`, `reason`, numeric `scores`, and separate fallback layers:

- `routerContacted`: whether an HTTP response was reached. A malformed response or HTTP error can mean contact succeeded but the decision was unusable.
- `routerInternalFallbackUsed` / `routerInternalFallbackReason`: the router used its safe/default decision. Router-supplied boolean `router_internal_fallback_used` (or camelCase) takes precedence; `fallback_used`, `fallbackUsed`, and `fallback` are also accepted from the router response. Matching reason fields are accepted, with the router reason as the default explanation. The exact reason-only reply `Laya unavailable, using safe fallback` is recognized for new requests. Other replies without an explicit flag leave this state unknown.
- `tableforgeRouterFallbackUsed` / `tableforgeRouterFallbackReason`: TableForge could not use the router decision and used its configured model. Legacy `fallback` / `fallbackReason` aliases retain this TableForge-only meaning in stored records.

Disabled and failed routing have no router-selected model. Router-internal fallback still uses the model returned by the router. The `ai` logger emits concise decisions at INFO and TableForge fallbacks at WARNING without logging prompts, router reason text, or exception bodies. Enable INFO logging in the host's Python logging configuration to see successful decisions.

Request capture uses the selected model, and metering uses OpenAI's reported model, falling back to the selected model if absent. The router must return accessible text models supporting Chat Completions; an invalid/unavailable OpenAI model is a generation error, not a router transport failure. GPT-6 Astra supports this endpoint. OpenAI [recommends Responses for new projects](https://developers.openai.com/api/docs/guides/migrate-to-responses), but this existing text-only provider does not require an API migration for routing. Responses can be evaluated separately if tool use or a Responses-only model is added.

In Pilot Mode, **AI Request Log** shows compact request entries with colored cheap/standard/heavy badges, separate Laya/router or TableForge fallback indicators, generation status, tokens, and estimated cost. Expand an entry to see purpose, router enabled/contacted state, tier, router-selected model, reason, scores, both fallback states/reasons, configured default model, model requested from OpenAI, model reported by OpenAI, and service tier. Either fallback is distinct from a failed OpenAI request. Unknown pricing shows **Cost unavailable** while retaining usage. Advance, Ask, and summary requests are included across the save's sessions.

Audit metadata is stored in SQLite `ai_requests`, linked to `ai_usage.request_id`, and survives reloads, restarts, and backups. Startup adds the table and nullable usage link automatically; older usage rows remain visible with unknown routing and separate provider models, without guessing from today's configuration. Interrupted requests are marked on restart. Full provider payloads remain temporary Pilot-only captures for advance/Ask, cleared at session end or restart; summary payloads are not captured. No prompts, transcripts, cartridge content, API keys, or arbitrary exception bodies are added to the durable audit records.

Both fallback layers use the existing routing JSON column; no additional database migration is required. Older routing records map their original generic fallback field only to the TableForge layer. Router contact and internal fallback remain unknown, even when an old reason mentions Laya fallback; historical records are not rewritten or reclassified from text.

For local network testing, launch with `python3 server.py --host 0.0.0.0` and use the host computer's LAN address. This initial server has no login or access control, so only expose it on a trusted network.

The current build provides real cartridge validation, SQLite saves, messages, Ready, Load Adventure, AI-DM advance (mock or OpenAI), and basic Pilot/Combat controls. In Pilot Mode, **Ask AI-DM** opens a saved operational conversation that does not appear in the public chat or change Ready. **End Session** records a checkpoint and closes the current session. Continue on an ended save starts the next session when a player joins; an open save resumes the same session after a restart. **Combat Mode** activates on an explicit AI-DM handoff signal or manual Pilot entry. The composer pauses and Ready becomes **Combat Finished**. When everyone finishes, everyone receives a dismissible optional outcome dialog; any player can send one report or skip it to request aftermath narration. Pilot **Resume AI-DM** can bypass waiting. Reports are saved and visible in shared history; failed aftermath offers **Retry aftermath**, including after a restart. If a cartridge is missing, Load Adventure offers **Locate ZIP** or **Locate Folder** and checks its contents against the original before restoring access. Other file attachments, spoiler-safe references and map rendering are still pending. The visual shell follows the approved Play Screen prototype; the older standalone prototypes remain in `prototypes/`.

In Pilot Mode, **Module Viewer** opens AdventureForge's Module Reader inside TableForge and loads `run-data.json` and `module.md` from the current save's cartridge bindings. Reader progress is stored in the browser for that save.

Each player can click their portrait in the Party list to open the editor, then click its square preview to choose an image. Drag to position it and zoom before saving a square crop. PNG, JPEG, and WebP source images up to 20 MB are supported; the saved crop is a 320 × 320 image. The same preview can be clicked again to replace the image, and the editor can remove a saved portrait. Portraits are stored with the playthrough in `data/tableforge.sqlite3` (or the configured `TABLEFORGE_DATA` directory), and appear in the join screen, Party list, and table chat.

Players can attach one PNG, JPEG, or WebP image (up to 20 MB) from the composer **+** control. The picture is stored with the playthrough and shown in the table feed. A caption is optional. Image-only shares stay on the table; the AI-DM sees caption text only.

The Play Screen sidebar shows reported OpenAI tokens and an estimated USD cost for the current session and playthrough. Options shows totals across saved adventures. Tracking begins with requests made after this update; earlier API activity cannot be reconstructed from the save. Estimates use standard text prices dated 2026-09-25 in `metering.py`. Models without a known rate still show tokens, with cost marked unavailable. The OpenAI billing dashboard remains the source of truth for charges.

### Illustrate Scene (experimental)

After an AI-DM narration, enable **Pilot Mode → Illustrate Scene**. Review the source narration, optionally add visual direction, and choose **Generate Draft**. The server uses the existing `TABLEFORGE_OPENAI_API_KEY` with the OpenAI Image API. `TABLEFORGE_IMAGE_MODEL` defaults to `gpt-image-2.5-flare`, independently of the narration model. Each explicit request generates one low-quality 1536 × 1024 JPEG. Your API project must have image-model access and billing enabled; organization verification may be required. See the [OpenAI image guide](https://developers.openai.com/api/docs/guides/image-generation).

Generation uses only the selected public narration and visual direction, without cartridge secrets, summaries, or Pilot conversations. The request keeps its original narration even if play moves on. It runs independently of narration, Ready, and Combat Mode. Only one image request can run per save at a time. Close the dialog to keep playing; reopen it to review saved drafts. Choose **Share with Table** to append the illustration to chat, or **Discard** to remove the draft image. A shared illustration links back to its source narration and is excluded from AI-DM context and campaign summaries.

Image bytes and request metadata are stored with the save in `tableforge.sqlite3`, following the existing portrait storage approach. Shared images and unreviewed drafts survive reloads and server restarts. Discard removes the image bytes while retaining request metadata and usage. Pilot Mode remains a UI safety measure for the trusted table, not an authentication boundary. Any trusted player in Pilot Mode can review a draft.

Image requests and estimated costs appear separately from text usage in the sidebar and Options. The Flare estimate uses reported text input and image output tokens at the [model's rates](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare), dated 2026-09-25. Unknown models, missing usage, and failed or interrupted requests show cost unavailable. Discarding an image does not refund its generation. Requests can take up to a few minutes; failures and interrupted requests are never automatically retried. Check provider usage before explicitly retrying an uncertain request.

### Drafts, retries, and Ready Override

An unsent message is kept in this browser (per save and player) and comes back when you rejoin the table. If the AI-DM advanced while it was away, it returns held for review, the same as a draft that goes stale while you type. Each send carries a request ID, so retrying after a lost reply never posts the contribution twice. A **Ready Override** records which player used it, the beat, and who was not Ready; the table sees this on the AI-DM reply it produced.

### AI-DM action choices

When the AI-DM offers concrete alternatives, its message lists lettered actions
and shows compact **A / B / C** buttons beside the overlapping-pages Copy icon.
Your client shows buttons for your character and any party-wide choices; the
whole table can read every option in the narration. Clicking a letter appends
the full action to your composer, preserving existing text and attachments.
Edit it if desired, then **Send**. Choosing a button does not change Ready.
Old choices become inactive when the table advances. A stale draft must be
reviewed before adding a current choice.

Choices are optional suggestions. Free-text replies remain available. Existing
saves receive the output-format instruction on future narration requests without
replacing their saved Stage 3 instructions or changing historical messages.

### Party knowledge

**NPCs**, **Locations**, and **World Notes** in the left sidebar show only what Pilots have written down as known to the party. Nothing is read from the cartridge, and these notes are not sent to the AI-DM. In Pilot Mode, add, edit, or remove entries; removed entries stay in the save history.

### Backups

**Options → Backups → Back up now** copies the whole save database (transcripts, portraits, illustrations, party notes) into `data/backups/` using SQLite's online backup and verifies the copy before listing it. Cartridges are not copied; they stay in `data/cartridges/`, and a restored save whose cartridge is missing asks you to locate it. **Restore…** checks the backup's integrity, shows what it contains, backs up the current data first, then replaces it and confirms the result matches. To restore a downloaded backup, copy it into `data/backups/` first. Restore is refused while the AI-DM or a scene illustration is generating.

Run the HTTP workflow tests with `python3 -m unittest discover -s tests -v`.
Run frontend tests with `node --test tests/*.cjs` and syntax checks with `node --check web/js/app.js` and `node --check web/js/request-log.js`.

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

- readiness resets and Ready becomes Combat Finished / Undo Finished
- normal composer, Send, attachments, and auto-ready pause; drafts remain available for later review
- all Finished offers everyone an optional outcome dialog; it does not generate narration by itself
- any player may submit a report or skip it to resume narration once
- Pilot Mode may ask the AI-DM questions in the separate operational conversation or override waiting
- accepted reports appear in shared history, and failed aftermath can be retried

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
