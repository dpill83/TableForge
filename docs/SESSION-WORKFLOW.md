# TableForge v2 Session Workflow Specification

**Status:** Baseline workflow specification  
**Version:** 2  
**Working concept:** AdventureForge cartridge + TableForge save/memory card  
**Supervisory model:** Pilot Mode

---

## 1. Purpose

TableForge v2 is the shared runtime used to play an AI-assisted tabletop RPG adventure created by AdventureForge.

AdventureForge creates the adventure package. TableForge opens that package, runs the shared session, connects the players to the AI-DM, and preserves the complete play history and evolving game state.

The guiding analogy is a game console:

- **AdventureForge** creates the game.
- **Stage 2 output** is the game cartridge.
- **TableForge** is the console.
- **The TableForge save** is the memory card.
- **The AI-DM** runs the adventure.
- **Players** play their characters.
- **Pilot Mode** exposes supervisory controls to any player who wants or needs them.

The goal is not to recreate a traditional human-DM structure. The group shares responsibility for play, combat, rulings, reminders, and decision-making. The AI-DM handles narrative-DM work while humans supervise and intervene when useful.

---

## 2. Version and Terminology

The historical TableForge versions are:

- **TableForge Legacy / v0** — supervisory role called **Captain**
- **TableForge v1** — current Tampermonkey relay version, supervisory role called **Director**
- **TableForge v2** — new shared AI-DM runtime, supervisory controls called **Pilot Mode**

Although v2 is technically the third implementation of TableForge, the project will refer to it as **TableForge v2**.

### Player

A person participating in the current game session through a player character.

### Pilot Mode

A mode any player may enable locally to expose supervisory AI-DM controls.

Pilot Mode is **not a permanent role assignment**. There is no requirement to designate one person as “the Pilot” before a session begins.

Any number of players may enable Pilot Mode at the same time.

### AI-DM

The AI responsible for:

- narration
- NPC dialogue
- scene progression
- adventure structure
- rulings and rules clarification when requested
- monster motivation or tactical advice when requested
- interpreting the party's submitted actions
- resuming narration after human-run combat

### Cartridge

The AdventureForge Stage 2 output package.

The cartridge contains the authored adventure and should remain conceptually separate from TableForge's save data.

### Save / Memory Card

The persistent TableForge playthrough data associated with a cartridge.

The save contains what happened during play rather than replacing or owning the original adventure package.

---

## 3. Cartridge Model

AdventureForge produces a package containing the authored adventure.

A cartridge may initially be a ZIP archive or another simple package format.

Conceptually, it may contain files such as:

```text
module.md
run-data.json
continuity.json
cast.md
cast.json
scenes.json
music-cues.json
map-art-brief.md
assets/
```

TableForge opens or mounts the cartridge.

TableForge should not require the user to manually select the source files again every time the group plays, but the cartridge itself remains the authoritative adventure package.

The cartridge should normally be treated as read-only during play.

---

## 4. Save / Memory Card Model

A TableForge save is associated with a specific cartridge and contains the evolving state of the playthrough.

The design principle is:

> Preserve as much useful session information as practical.

The save should preserve, where possible:

- complete table-facing transcript
- all player messages
- all AI-DM responses
- Pilot-to-AI-DM messages
- corrections and rulings
- session boundaries
- Ready state history if useful
- combat handoff and resume events
- current adventure progress
- important world and NPC state
- discovered information
- triggered events
- current location
- clocks or timers
- loot and treasure changes
- combat outcomes
- open threads
- uploaded/shared images
- generated images
- other shared attachments
- AI context/checkpoints or summaries
- references needed to resume play reliably

The complete transcript is important even when structured state is also available.

Structured state provides fast, explicit facts. The transcript preserves context, nuance, table discussion, character actions, and information that was never anticipated by a fixed schema.

TableForge should not rely on an AI provider's chat history as the only permanent memory of the adventure.

---

## 5. Launch and Game Selection

### 5.1 Launch TableForge

The user launches TableForge.

TableForge starts whatever local application, service, database, or network components are required for the current architecture.

Players can connect to the active table.

### 5.2 Select a Cartridge

The group selects an AdventureForge cartridge.

TableForge identifies whether compatible save data already exists for that cartridge.

### 5.3 New Game

If no save is selected, the group may begin a new playthrough.

TableForge creates a new save associated with the selected cartridge.

### 5.4 Continue Game

If a save exists, the group may continue that playthrough.

TableForge restores:

- transcript
- game state
- session history
- attachments
- AI context needed to continue
- other persisted information

The adventure resumes from the saved point rather than replaying the Stage 3 opening sequence.

---

## 6. Players and Pilot Mode

Players join the table as their characters.

Example:

- Dan → George
- Dani → Ethereal
- Ted → Viktor

There is no required Pilot assignment.

Each client has a local control:

```text
Pilot Controls: Off / On
```

### 6.1 Pilot Controls Off

The player sees the normal play interface.

At minimum this includes:

- AI-DM/table feed
- message composer
- Ready control
- relevant shared adventure content

### 6.2 Pilot Controls On

The player also gains access to supervisory controls.

These may include:

- Ask AI-DM
- send correction/context
- inspect or choose context being sent
- Force Advance / Ready Override
- resume AI-DM after combat
- review AI-DM output
- regenerate AI-DM output
- other future supervisory controls

Pilot Mode exists primarily to prevent accidental use of supervisory controls.

It is not intended as a permissions hierarchy between trusted players.

### 6.3 Multiple Pilots

Multiple players may enable Pilot Mode simultaneously.

Pilot actions should record which player initiated them.

The system must prevent conflicting actions such as two simultaneous AI-DM generations.

If one player steps away, another player can enable Pilot Mode and continue without formally transferring ownership of the session.

---

## 7. Beginning a Session

When the group begins play, TableForge provides the AI-DM with the context required to run the adventure.

For a new game this includes the relevant Stage 3 operating instructions and cartridge material.

For a resumed game this includes the current saved state and whatever cartridge context is needed to continue accurately.

The AI-DM produces the opening or next table-facing response.

---

## 8. Normal Table Conversation

The normal shared conversation consists of:

```text
AI-DM response

Player response(s)

AI-DM response

Player response(s)

...
```

The feed should behave as a running shared conversation rather than forcing players to manually target numbered scenes.

Internally, TableForge may still use scenes, beats, message groups, IDs, or other structures as needed.

Those internal structures should not require ordinary players to manage message targeting manually.

---

## 9. Ready System

Ready is a first-class part of the TableForge v2 play loop.

Ready does **not** mean:

- the player submitted exactly one response
- the player took a turn
- the player has nothing else they are allowed to say

Ready means:

> “I am satisfied with what I have contributed to this current beat, including contributing nothing. The AI-DM does not need to wait for me.”

### 9.1 Player Contributions

During a beat, a player may submit:

- zero messages
- one message
- multiple messages
- text typed directly into TableForge
- content produced with their own ChatGPT or other writing assistant
- shared images or attachments where supported

### 9.2 Ready State

When a new AI-DM table-facing response begins the next beat, active players become **Not Ready**.

Each player may press **Ready** whenever they are done contributing.

A player may Ready without submitting a message.

### 9.3 Unready

A Ready player may become Not Ready again as long as the next AI-DM generation has not begun.

### 9.4 Editing While Ready

A player may continue editing or adding pending contributions while Ready.

If they need additional time, they may Unready.

### 9.5 Who Counts as Ready

The system should use the players currently considered part of the active session.

The exact number does not matter.

Examples:

- One active player → that player's Ready state can satisfy the table.
- Two active players → both can satisfy the table.
- Three active players → all three can satisfy the table.

If a player leaves but remains technically marked active, this should not block the session because Pilot Mode provides a Ready Override / Force Advance control.

The system does not need an elaborate presence-management system merely to solve this edge case.

---

## 10. Automatic Advance

During normal exploration, roleplay, and investigation play:

> When all active players are Ready, TableForge may automatically begin the next AI-DM generation.

At the moment generation begins:

1. TableForge snapshots the content selected for submission.
2. That snapshot becomes the AI-DM input for that advancement.
3. Ready states reset for the upcoming beat.
4. Further messages are not silently added to an AI request already in progress.

This provides a Fortnite-lobby-like readiness model: everyone signals when they are ready for the game to continue.

---

## 11. Force Advance / Ready Override

Anyone with Pilot Mode enabled may use a supervisory advance control.

Working concept:

```text
FORCE ADVANCE
```

or another intentionally prominent label.

This action means:

> Continue using the currently selected context even though one or more players are not Ready.

This control effectively overrides the remaining Ready requirements.

Because it can advance the entire table, the UI should guard against accidental activation, such as with a confirmation step.

A typical use case:

```text
George      READY
Viktor      READY
Ethereal    NOT READY
```

Ethereal says aloud that she has nothing else to add.

A player with Pilot Mode enabled may use Force Advance rather than requiring Ethereal to interact with her device.

---

## 12. Advance Payload

The default context for a normal advance should include all player messages submitted during the current beat.

However, TableForge should allow Pilot users to inspect and adjust what is being sent to the AI-DM.

The exact UI is not yet specified, but the workflow should support a context-selection area where relevant material can be checked or unchecked.

Potential selectable context may include:

- George's current-beat messages
- Viktor's current-beat messages
- Ethereal's current-beat messages
- Pilot-to-AI-DM messages
- recent AI-DM messages
- system-generated summary
- current structured game state
- combat outcome
- relevant attachments
- other context TableForge determines may be useful

### 12.1 Default Behavior

The safest default is:

- include all current-beat player messages
- include the minimum AI-DM/system context required to continue correctly
- do not require manual context management for ordinary advances

Pilot users can adjust the context when something unusual requires it.

### 12.2 Context Selection Principle

Context selection should be an override and inspection tool, not mandatory bookkeeping every time the table advances.

The normal path should remain fast.

---

## 13. Pilot-to-AI-DM Conversation

Pilot Mode provides a separate operational conversation with the AI-DM.

This is distinct from the public table-facing roleplay feed.

Examples:

- “What would Shenka reasonably do here?”
- “Viktor is actually blocking the north exit. Does that change her choice?”
- “How does this rule work?”
- “Mervin is unconscious, not dead. Correct the state.”
- “Remind us what the trap does.”
- “Would this monster flee when bloodied?”

### 13.1 Effect on Readiness

Pilot-to-AI-DM messages:

- do not automatically mark a player Ready
- do not automatically Unready a player
- do not automatically advance the scene
- do not automatically become table-facing narration

### 13.2 Visibility

Because the group plays cooperatively, Pilot-to-AI-DM exchanges may be visible to all users who have Pilot Mode enabled.

They do not need to be treated as secret DM notes.

### 13.3 Persistence

Pilot-to-AI-DM exchanges should be saved as part of the playthrough because they may contain:

- rulings
- corrections
- tactical reasoning
- state clarification
- decisions that affect future AI context

They must be labeled separately from the table-facing transcript.

---

## 14. AI-DM Generation and Review

When advancement begins, the AI-DM generates the next response.

The exact UI is not yet defined.

At minimum, TableForge should support Pilot supervision of AI-DM output.

Potential Pilot actions include:

- publish
- regenerate
- correct context and retry
- edit before publication, if later design work determines this is desirable

Only one AI-DM generation should be active at a time.

When the next table-facing response begins, the previous response window is closed and the next beat starts.

---

## 15. Combat Handoff

Combat is intentionally different from normal conversational play.

When initiative is called, TableForge enters **Combat Mode**.

The AI-DM hands mechanical battle operation to the human table according to the AdventureForge Stage 3 philosophy.

Humans may collectively handle:

- player turns
- monster turns
- damage
- HP
- conditions
- initiative
- movement
- battlefield tactics
- monster distribution among players

TableForge is not intended to become a full VTT or automated combat engine merely because combat occurs.

---

## 16. Ready During Combat

Players may still have Ready controls during Combat Mode.

Ready can indicate:

> “I am finished with what I need to do before the AI-DM resumes.”

However:

> Combat Mode must not auto-advance merely because all players become Ready.

Combat requires a deliberate supervisory handoff back to the AI-DM.

This prevents accidental narration while the humans are still:

- resolving HP
- updating conditions
- determining loot
- discussing the outcome
- finishing combat bookkeeping
- deciding exactly what happened

---

## 17. Resume AI-DM After Combat

Anyone with Pilot Mode enabled may perform the explicit combat handoff.

Working concept:

```text
RESUME AI-DM
```

Before resuming, the group may provide or select relevant combat outcome information.

Examples:

- enemies defeated
- enemies escaped
- NPC deaths
- party HP
- conditions
- resources spent
- loot obtained
- important tactical or narrative events

TableForge sends the relevant outcome/context to the AI-DM.

The AI-DM then:

1. interprets the completed combat outcome
2. updates narrative state
3. narrates the aftermath
4. resumes normal adventure play

Normal Ready-based advancement becomes active again after combat.

---

## 18. Session Continuation and Multiple Sessions

A single cartridge/playthrough may span many real-world sessions.

The save should preserve clear session boundaries.

A resumed session should not require reconstructing the previous ChatGPT conversation manually.

TableForge should restore enough state and context for the AI-DM to continue the existing adventure reliably.

The person or people using Pilot Mode may differ between sessions.

No permanent Pilot assignment is stored as a requirement for future play.

---

## 19. Ending a Session

The group deliberately ends a play session.

TableForge preserves the current save.

The end-session process should retain as much useful information as practical, including:

- complete transcript
- Pilot conversation
- current structured state
- session metadata
- current adventure position
- open threads
- unresolved actions
- shared attachments
- AI summaries/checkpoints if useful
- other information required for reliable continuation

The exact implementation of end-of-session summaries and checkpoints remains a later design decision.

---

## 20. Closing TableForge

After the session has been saved, TableForge may be closed.

The cartridge remains the original authored adventure package.

The save remains the playthrough's memory card.

On the next launch:

1. choose/open the cartridge
2. select the save
3. reconnect players
4. continue play

---

## 21. Complete High-Level Workflow

```text
Launch TableForge
        ↓
Choose AdventureForge cartridge
        ↓
New Game or Continue Save
        ↓
Players connect
        ↓
Anyone who wants supervisory controls enables Pilot Mode
        ↓
Begin / Resume
        ↓
AI-DM produces table-facing response
        ↓
New beat begins
All active players become NOT READY
        ↓
Players send 0–N messages
        ↓
Players become READY when finished
        ↓
All active players READY?
        │
        ├── Yes → snapshot selected context → AI-DM generation
        │
        └── No  → continue waiting
                    │
                    └── Pilot may FORCE ADVANCE
        ↓
AI-DM generates next response
        ↓
Pilot supervision/review as needed
        ↓
Publish
        ↓
Repeat
```

### Combat branch

```text
AI-DM calls initiative
        ↓
COMBAT MODE
        ↓
Humans run combat
        ↓
Players may Ready
        ↓
No automatic AI advance
        ↓
Pilot Mode user explicitly chooses RESUME AI-DM
        ↓
Submit combat outcome/context
        ↓
AI-DM narrates aftermath
        ↓
Return to normal Ready loop
```

---

## 22. Core Product Principles Established by This Workflow

### The adventure and the save are separate

AdventureForge creates the cartridge.

TableForge creates and maintains the memory card.

### Pilot is a mode, not a permanent role

Every trusted player may supervise the AI-DM.

Pilot Mode simply exposes the controls.

### Ready expresses completion, not a turn

Players can contribute zero, one, or many messages.

Ready only means the AI-DM no longer needs to wait for that player.

### The table controls advancement

All Ready can trigger normal advancement.

Pilot Mode can override readiness.

Combat always requires explicit human handoff back to the AI-DM.

### TableForge should preserve context generously

The transcript, Pilot messages, state, images, attachments, and other useful information should be retained whenever practical.

### TableForge should not become a VTT by default

Combat remains human-operated unless later playtesting demonstrates a clear need for additional tooling.

### The AI provider is not the permanent save system

TableForge's own save must remain authoritative so a playthrough can be resumed, archived, moved, or potentially run with a different AI provider in the future.

---

## 23. Remaining Design Work

This specification defines the session workflow.

It intentionally does **not** yet define the screen layout.

The next design task is:

> **Design the TableForge v2 interface around this workflow.**

Important UI questions will include:

- shared feed layout
- player composer
- Ready state presentation
- Pilot Mode toggle
- Force Advance control
- Pilot-to-AI-DM console
- context-selection interface
- AI-DM draft/review experience
- Combat Mode presentation
- cartridge/save selection
- attachments and images
- session-end controls

These should be designed to serve the workflow rather than determine it.
