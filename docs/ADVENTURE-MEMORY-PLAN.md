# TableForge adventure memory plan

Keep the AI-DM's memory of the adventure current without anyone pressing a button, and give players a readable record of the story.

## The problem

The AI-DM remembers nothing between turns. Each Advance sends a fresh packet: instructions, the relevant module material, a "story so far" summary if one exists, recent chat, and the current beat. Recent chat had a 40,000-character budget. When chat outgrew it, TableForge dropped the oldest messages. A summary was meant to cover them, but summaries were only written when a Pilot clicked **Summarize** and then **Save summary**.

At Bloodspear Hold nobody had, so 64 messages (24,788 characters, about two hours of play) were left out with no summary. That was the **Review Context · 1 omission** badge. Locations, the sabotaged drum, and the pending ogre bargain could all have been in that stretch.

## Decisions

- **Automatic.** TableForge writes and saves the catch-up itself. Pilots may edit it but never have to approve it. Automatic summaries are attributed to "TableForge (automatic)".
- **Never drop without a recap.** Raw chat leaves the AI-DM packet only after a saved summary covers it. Humans always see the full chat.
- **Limits.** 40k characters of unsummarized chat is the soft limit: condense in the background at the next clean break. 60k is the normal cap: an Advance at or past it summarizes first, showing **Summarizing the adventure…**. If that summary fails, the Advance still sends everything up to a 120k ceiling. Past the ceiling, the table waits and any player can **Retry**.
- **Clean breaks only.** Condense at beat boundaries: after narration is published, when combat starts, after combat aftermath, when the party changes location, or when a Pilot presses **End chapter**. Never mid-beat.
- **Chapters.** Adventures run roughly prologue → exploring → middle/climax → finale/epilogue. Prologue → Chapter 2 switches automatically when the opening flow reaches exploration. Later chapters: the AI-DM suggests a break, a Pilot confirms, and a Pilot may end a chapter at any time. Each finished chapter becomes one locked recap.
- **Facts ledger.** Where each character is, open promises and bargains, important item locations, conditions in free text, unresolved hooks. No HP. The summarizer may add, update with a reason, or resolve entries, but never silently delete or reword them. Pilot-edited entries are protected from the summarizer.
- **Player journal.** Left sidebar **Journal** with **Story so far** (chapter recaps) and **Facts** (the ledger), visible to every player.
- **Spoiler safety.** Recaps and facts come only from shared table chat and recorded combat reports. The summarizer never sees the module, private Pilot conversations, or cartridge secrets. Public OOC questions are hypothetical and are never recorded as facts.
- **Combat reports** stay verbatim in the packet until a summary covers them, replacing the fixed latest-five window.
- **Gauge.** Pilot-only colour on the Review Context button: green below 40k, yellow from 40k, red from 60k.

## Build order

1. **Safety net** (implemented). 40k/60k/120k limits, automatic background summaries at beat boundaries, the Advance-time fallback with its waiting status, and the Pilot gauge.
2. **Facts ledger** (implemented). Storage, summarizer rules, protected Pilot edits, and the Journal's Facts section.
3. **Chapters** (implemented). Boundaries, recaps, **End chapter**, AI-DM suggestions, and the Journal's Story so far section.
4. **Combat reports** (implemented) carried verbatim until a summary covers them.

## Verify

- Reproduce the 64-message gap: one Advance saves a summary and produces exactly one narration, with no omission.
- A turn under 60k proceeds without waiting even when a summary is due.
- A failed summary leaves the previous summary, Ready states, and any submitted combat outcome intact, and nothing is dropped below the ceiling.
- A background summary that loses a race with a Pilot edit or a newer summary is discarded, not written.
