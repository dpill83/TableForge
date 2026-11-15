# Single-sidebar play layout

Status: Implemented on branch `codex/single-sidebar` (based on `origin/main` at 20d2d07). Decisions 1–4 are accepted and implemented. See **Implementation notes** at the end for where the build differs from this plan and the Decision 5 measurement.

## Goal and visual direction

Retire the right sidebar and bring party information and Pilot controls into one resizable, collapsible left sidebar. Keep the shared conversation as the main focus.

Use the user's Photoshop mockups as the layout reference: compact bordered party rows directly below `# table`, existing Reference and Tools navigation, and existing Pilot controls beneath them. Use the generated mockup as inspiration for the upper-left toggle and subdued dark scrollbars. Do not treat its larger icons, unboxed party rows, or changed button styling as requirements.

Preserve TableForge's current dark theme, restrained gold AI-DM accents, message appearance, and familiar controls. The product remains named TableForge.

## Decisions to confirm

Each item lists the recommended resolution first. The rest of this plan is written assuming the recommendation.

1. **Composer placement — accepted (recommended option).** Today the composer is a full-width footer row under all three columns, centered on the whole window, while the chat is centered on the main column only. With one left sidebar the two would be offset by half the sidebar width.
   - *Recommended:* the sidebar runs the full height below the header, and the composer moves into the main column beside it (Discord-style), centered on the same axis as the conversation.
   - *Alternative:* keep the full-width composer row and shift its centering by the sidebar width through a shared CSS variable.
2. **Header brand width — accepted (recommended option).** `.app-brand` is a fixed 230 px with a right border so it lines up with today's 230 px left column. A resizable sidebar breaks that alignment.
   - *Recommended:* decouple the header from the sidebar. The brand takes its natural width with the toggle beside it and no border pretending to continue the sidebar edge. The header does not change when the sidebar resizes or collapses.
   - *Alternative:* drive the brand width from the same sidebar-width variable, and define its collapsed appearance.
3. **Scene-image usage with Pilot off — accepted (recommended option).** The in-game Options dialog already shows current-session and playthrough text usage, and that access is preserved, so text totals stay available with Pilot off. Scene-image session/playthrough totals, however, currently appear only in the persistent right-sidebar panel; in-game Options shows text usage only. Removing the panel would make per-adventure image totals reachable only through Pilot.
   - *Recommended:* add the existing scene-image session/playthrough lines (including missing-cost notices) to the in-game Options usage block, so everything the persistent panel showed stays reachable with Pilot off.
   - *Alternative:* accept image totals as Pilot-only.
4. **Narrow windows — accepted (recommended option).** The current 900 px breakpoint turns the sidebars into fixed overlays. It existed to fit two sidebars; a half-snapped 1366 px laptop window (≈683 px) would fall into overlay mode.
   - *Recommended:* replace the 900 px rule with one derived from the layout: use the inline layout whenever the viewport fits the minimum sidebar width plus a minimum chat width (provisionally 220 + 420 = 640 px). Below that, use the overlay behavior described under **Narrow windows**.
   - *Alternative:* keep the 900 px breakpoint.
5. **Pilot reachability on short laptop screens.** Independent sidebar scrolling is already accepted, so Pilot controls sitting below a sidebar scroll is not by itself a problem. The full-height sidebar (Decision 1) also gains the height beside the composer, so earlier estimates based on the current layout do not apply.
   - *Recommended:* keep the agreed order (party, Reference, Tools, Pilot). After the full-height layout is built, measure the actual sidebar height and content at 1366×768 with four and six party members. Reconsider Pilot placement only if that measurement shows a real problem; if so, raise it as a separate decision. AGENTS.md already describes a Pilot-only Force Advance in the bottom bar, which would be the natural candidate.
   - *Alternative:* place the Pilot block directly below the party rows while Pilot Mode is on.

## Agreed layout

- Header: full width. Persistent sidebar toggle at the upper left beside the TableForge name; adventure title; existing session, search, Options, and Pilot Mode controls. The brand area has no fixed width tied to the sidebar (Decision 2).
- Left sidebar: runs the full height below the header, beside both the conversation and the composer (Decision 1). Contents: `# table`, compact party rows without a separate Party heading, Reference, Tools, then Pilot.
- Party rows: preserve portraits, character names, player names, Ready/combat states, current-player indication, and access to editing one's portrait.
- Reference and Tools: preserve existing entries and their visibility rules, including Pilot-only cartridge viewers. Preserve Add as currently implemented; do not invent behavior for it.
- Pilot: visible only while the local client's Pilot Mode is enabled. Preserve the party-location selector and all existing actions, including conditional Correct combat outcome. Add AI Usage.
- Main column: the conversation and the composer, to the right of the sidebar.
  - Conversation: continuous chat, centered within the main column at its existing comfortable maximum reading width (900 px). Retiring the sidebar does not mean stretching text across the screen.
  - Tool viewer frames (Cast, Module, Scene) continue to fill the whole conversation area, not the reading width.
  - Composer: moves from the full-width footer row into the main column and is centered on the same axis as the conversation. Preserve existing controls, drafts, status notices, and combat reporting.
- Remove the right sidebar and both floating arrow handles completely, including unused layout space.

Collapsing the sidebar intentionally hides party readiness. Do not add a duplicate Ready count or another persistent party display. Laptop use is the priority; a mobile redesign is outside this change.

## Sidebar interaction

1. Drag the sidebar's right divider to resize it. Show a horizontal resize cursor and subtle hover/drag emphasis, with a forgiving hit target around a thin visible line.
2. Clamp expansion to a maximum that always leaves at least the minimum chat width (provisionally 420 px).
3. When dragging left, hold at the minimum usable width. Additional leftward travel beyond a small distance threshold collapses the sidebar. This is resistance based on drag distance, not a timed pause.
4. Collapse happens live during the drag, with hysteresis so one gesture cannot flicker:
   - crossing the collapse threshold (minimum width minus the collapse travel) hides the sidebar immediately;
   - while still dragging, moving back right past the minimum-width line restores it at the minimum width;
   - releasing commits whatever state is showing. Releasing in the resistance zone leaves the sidebar at its minimum width.
5. When collapsed there is no divider and no edge-drag discovery. The upper-left toggle stays outside the hideable sidebar and remains available in both states. It hides the sidebar or restores its last expanded width.
6. Remember expanded width and collapsed state per browser (localStorage, wrapped in try/catch like the existing preference keys), separately from campaign saves and shared player state. One global key, not per save. A collapse must not overwrite the remembered expanded width.
7. Recheck bounds when the window changes size. Clamp a remembered width to the current viewport without trapping the user or removing the toggle. Clamping for display does not overwrite the remembered width.

Provisional tuning values for implementation review: default width 260 px, minimum 220 px, maximum 400 px subject to the minimum chat width, approximately 40 px of additional travel past the minimum to collapse, and a 420 px minimum chat width. These are starting values, not approved pixel specifications; assess them on actual laptop viewports with the existing party cards and labels.

### Accessibility and robustness

- The toggle is a button with `aria-expanded` and `aria-controls`, and its tooltip/accessibility label switches between Show sidebar and Hide sidebar.
- The divider is a focusable `role="separator"` with `aria-orientation="vertical"` and current/min/max values. Left/Right arrows adjust the width in steps, and Home/End jump to minimum/maximum. Arrow keys never collapse; the toggle is the keyboard collapse control.
- A collapsed sidebar is made `inert` (or equivalent) so its controls cannot receive focus. If focus is inside the sidebar when it collapses, move focus to the toggle.
- Use pointer capture on the divider so release outside it, release over the embedded viewer iframes, and `pointercancel`/`lostpointercapture` all end the drag cleanly. The Ready button's hold handling already uses this pattern. Prevent text selection while dragging.
- Apply width changes at most once per animation frame.

### Reading position during resize

Narrowing or widening the main column (dragging, collapsing, restoring, window resizing, crossing the narrow-window threshold) can reflow the conversation once the column is narrower than the 900 px reading width plus padding. The current feed code preserves a numeric `scrollTop` across renders, which does not keep the reader on the same paragraph when text reflows. This needs new, explicit anchoring:

A resize observer runs only after layout has changed, so it cannot capture where the paragraph was before reflow. The anchor must already exist before the width changes. Capture and restore are therefore separate steps:

**What the anchor is**

- Candidate rows are the feed's top-level rows: message rows (`#message-<id>`) and combat-event rows (`.message.combat-event`, `#event-<id>`).
- Within the topmost visible row, the anchor is the first block-level element (paragraph, list item, image, heading) whose top is at or below the feed's top edge. Long AI-DM replies can be taller than the viewport, so anchoring to the row alone is not enough. Fall back to the row itself if no block qualifies, which is the normal case for short combat-event rows.
- Store the anchor as data, not a DOM reference: the row ID, the block's index within that row, and the block's offset from the feed's top edge. Routine renders may rebuild feed DOM, so the anchor is re-resolved by ID and index when it is used.
- If the reader is following the latest message, the anchor is simply "pinned to bottom".

**Keeping the anchor current**

- Update the saved anchor during normal scrolling, at most once per animation frame, from the feed's scroll handler.
- Update it after any render that changes feed content, so a stale anchor never survives new messages.

**Capturing before controlled sidebar changes**

- Before every width change TableForge itself initiates (drag start and each batched drag frame, toggle collapse/restore, keyboard divider adjustment, overlay open/close), capture a fresh anchor synchronously, before the width is applied.
- Window resizing is not initiated by TableForge, so it relies on the anchor maintained by scrolling.

**Restoring after reflow**

- A resize observer on the feed restores the saved anchor after reflow, batched to one adjustment per frame, so every width-change path, including window resizing, uses the same restore logic.
- Restoration sets an absolute `scrollTop` computed from the anchor's new position, so it gives the same result whether or not the browser's native scroll anchoring has already moved the feed.
- While a width change is pending restoration, scroll events must not overwrite the saved anchor. Reflow can clamp `scrollTop` or trigger native scroll anchoring, and those scroll events reflect post-reflow positions. Resume normal anchor updates after the restore has run.
- If the anchor's row or block no longer exists, fall back to the nearest surviving row, then to the numeric scroll position.

**Unchanged behavior**

- Anchor capture and restoration do not show or hide Jump to latest or change follow-latest state.
- Routine state-refresh behavior stays as it is unless testing shows the same reflow problem there.

## Narrow windows

Below the inline-layout threshold (Decision 4: minimum sidebar width plus minimum chat width, 640 px with the provisional 220 + 420 values; the threshold follows those values if tuning changes them):

- The sidebar opens as an overlay over the main column at its minimum width, and starts collapsed on load.
- The toggle opens and closes it; Escape closes it.
- Dragging is disabled in overlay mode.
- Overlay use never writes the remembered expanded width or collapsed state, so returning to a wider window restores the desktop layout as it was.

This keeps the existing small-screen behavior workable without a mobile redesign. Players who keep the overlay closed will not see who is not Ready; that follows from the agreed "collapsing hides readiness" decision.

## AI Usage on demand

Add an AI Usage button under Pilot that opens a dialog with the information currently displayed persistently:

- Text AI usage: session and playthrough totals, input/output tokens, estimated cost where available, and pricing reference.
- Scene-image usage: separate session and playthrough image/request totals, known estimated costs, and missing-cost-data notices.

Keep the distinction between text and image usage. Preserve unavailable-data messaging rather than displaying unknown costs as zero. Keep AI Request Log as a separate detailed inspection tool. Do not move image generation or image history into the usage dialog.

The dialog should reflect current totals when opened and stay current while open. Update it from the existing render path when save state refreshes, without resetting its scroll position or stealing focus. Closing it must not affect usage collection.

Preserve the existing usage access in Options: the title-screen Options view (all-adventure totals) and the in-game Options dialog (current-session and playthrough text usage). With Pilot off, players can still see text session/playthrough totals through in-game Options. Add the existing scene-image session/playthrough lines, including missing-cost notices, to the in-game Options usage block (Decision 3), so everything the persistent panel showed remains reachable with Pilot off.

Switching Pilot Mode off must close the usage dialog. The Pilot-off handler clears dialogs from an explicit list of Pilot-only dialog IDs, so add the usage dialog's ID to that list.

## Dark scrollbars

Replace the bright white conversation scrollbar with a narrow muted-gray rounded thumb on a dark or transparent track, without arrow buttons or a white gutter. The thumb should be visible at rest and more distinct on hover without competing with the chat.

Apply consistent styling to the chat feed, sidebar, and application-owned scrolling dialogs. Keep sidebar and conversation scrolling independent. Respect browser and forced-colors accessibility behavior; never remove the ability to scroll. Embedded viewers may own their own styles, so inspect those separately before claiming application-wide coverage.

Choose the CSS approach deliberately. In Chromium 121+, setting the standard `scrollbar-width`/`scrollbar-color` properties disables `::-webkit-scrollbar` styling on that element, and Firefox supports only the standard properties. Do not layer both and assume both apply. Verify the result (arrow buttons, at-rest visibility, hover) in the browsers the group actually uses.

## Implementation sequence

1. **Isolated base:** the owning files (`web/index.html`, `web/styles/app.css`, `web/js/app.js`) currently carry substantial uncommitted, unrelated changes. Implement this change on an isolated base (for example its own branch or worktree) so its diff can be reviewed on its own and the unrelated work is left untouched. Finishing or landing that unrelated work is not a prerequisite. If the chosen base lacks in-progress changes that this layout depends on, note the dependency and the expected merge order instead of absorbing that work.
2. Once this plan is approved, update the layout descriptions in AGENTS.md and docs/UI-UX.md first, replacing the right-sidebar direction and the "left sidebar intentionally light" guidance. This prevents the implementation from contradicting the project's source-of-truth instructions mid-change.
3. Move the existing party and Pilot elements into the left sidebar, preserving element identities, event handlers, state updates, and conditional visibility. Add the usage dialog (including the Pilot-off close list), add scene-image session/playthrough lines to the in-game Options usage block (Decision 3), and remove the persistent usage display.
4. Replace the three-column shell with the full-height sidebar plus main column (conversation and composer). Decouple the header brand width. Remove right-sidebar state, arrow handlers, the old 900 px two-sidebar rules, and obsolete collapse rules. Preserve tool viewers, header actions, composer behavior, and chat reading position.
5. Implement the persistent header toggle, divider resizing, minimum-width resistance with hysteresis, collapse behavior, local preference storage, and narrow-window overlay mode.
6. Implement reading-position anchoring for width changes.
7. Apply dark scrollbar styling and check laptop-height overflow, long names, and Pilot controls. Take the Decision 5 measurement on the built layout.
8. Validate the complete layout and interactions before proposing any deployment.

A small focused sidebar module may be appropriate if the resize logic would otherwise crowd app.js. Backend, database, cartridge, save-format, AI-prompt, and game-rule changes are not expected.

## Verification and acceptance

- With Pilot off, the party appears directly under `# table`; Reference and Tools retain their current behavior. No right sidebar, arrow handles, or permanent usage panel remains.
- With Pilot on, all existing Pilot actions remain reachable, including location correction, cartridge viewers, and conditional combat controls. Switching Pilot off hides them, closes the usage dialog, and retains existing spoiler-safety cleanup.
- Party Ready/combat indicators synchronize as before; portrait editing still works. Hiding the sidebar has no effect on readiness or game state.
- The composer is centered on the same axis as the conversation at the default, minimum, and maximum sidebar widths and when collapsed. Tool viewers still fill the conversation area.
- The header does not shift when the sidebar resizes or collapses.
- Test minimum, maximum, resistance-zone release, drag-to-collapse, drag-back-to-restore within one gesture, toggle-to-hide/show, refresh restoration, browser-window resizing, and canceled drags (including release over an embedded viewer). Collapsing never loses the saved expanded width.
- Check typical laptop sizes, including 1366×768, a half-snapped 1366 window, and 1920×1080, at normal browser zoom, with long player names and enough party members to require sidebar scrolling. Check the inline/overlay threshold in both directions, and that overlay use does not change the remembered desktop layout.
- On the built full-height layout, record the measured sidebar height and whether Pilot controls fit without sidebar scrolling at 1366×768 with four and six party members (Decision 5).
- While scrolled up in a long transcript, including mid-way through a reply taller than the viewport, dragging the divider, collapsing/restoring, and resizing the window keep the same paragraph at the same position. The same holds when a combat-event row is at the top of the view. When following the latest message, the feed stays pinned to the bottom.
- With Pilot off, in-game Options still shows current-session and playthrough text usage and scene-image session/playthrough totals, kept separate from text usage and with missing-cost notices rather than zero costs.
- The header toggle remains visible and usable when collapsed. Keyboard focus and divider adjustment work; hidden controls cannot receive focus; focus moves to the toggle when collapsing from inside the sidebar.
- The usage dialog shows text and image totals separately, handles unavailable costs, updates while open, and does not change tracking or initiate AI activity.
- Scrollbars blend into the dark theme while remaining usable in the browsers checked. Jump to latest and follow-latest state are unaffected by sidebar drags, collapses, and routine state refreshes.
- Opening viewers, private Pilot conversations, context review, Ready Override, and combat reporting still work without losing unsent composer drafts.
- Run the existing frontend and relevant UI regression checks. Add focused tests for resize thresholds and hysteresis, saved-width restoration, the narrow-window threshold, and visibility where they protect actual interaction behavior; do not add backend tests for a presentation-only change.

## Documentation follow-through

AGENTS.md and docs/UI-UX.md are updated at the start of implementation (step 2), after this plan and its decisions are approved. When implementation is complete, recheck those documents against what shipped and update any directly affected architecture or usage instructions. This draft records the proposed change without rewriting those existing documents yet.

## Implementation notes

Recorded after implementation on `codex/single-sidebar`.

**Base changed since the plan was written.** The plan was reviewed against an older local checkout. Current `main` had already:

- removed the persistent right-sidebar usage panel and placed text *and* scene-image session/playthrough usage in the in-game Options dialog for every player (so Decision 3 was already satisfied);
- moved AI Request Log and End Session out of the Pilot panel into Options (Pilot-gated there);
- added a resizable shared table map panel beside the chat.

Consequences:

- **No Pilot "AI Usage" button was added.** Options already shows exactly the information the dialog was meant to hold, for everyone, so a Pilot button would duplicate it. Adding one is a small follow-up if still wanted.
- **Table map:** the map panel now sits to the right of the chat column, full height. Its resize limit leaves the minimum chat width beside the current sidebar width, and the sidebar's maximum likewise accounts for an open map. Opening, closing, and resizing the map also use the reading-position anchor. Below 900 px the map still covers the chat column (not the sidebar or composer).

**What was built**

- `web/js/layout.js`: pure helpers (limits, overlay threshold, drag resistance with hysteresis, keyboard steps, preference parsing, anchor capture/restore), the `FeedAnchor` class, and the sidebar controller. Loaded before `app.js`.
- Preferences are stored under the browser key `tableforge-sidebar` as `{width, collapsed}`; overlay use never writes them.
- A cancelled drag (`pointercancel` or lost capture) reverts to the pre-drag state; only a normal release commits.
- Collapsed sidebars are `inert` and `aria-hidden`; the divider is a focusable `role="separator"` with min/max/now values.
- Scrollbars use the `::-webkit-scrollbar` pseudo-elements, with the standard properties applied only where those are unsupported (Firefox), and nothing applied under forced colors. The feed uses a symmetric `scrollbar-gutter` so the reading column and composer share one center.
- Docs updated: AGENTS.md, docs/UI-UX.md, docs/DECISIONS.md (D-027, D-029, D-030 revised in place), and README layout/usage text.

**Verification performed**

- `node --test tests/*.cjs`: 89 passing, including 14 new tests in `tests/test_layout.cjs` (thresholds, hysteresis, saved-width restoration, cancel, keyboard, window-resize clamping, overlay mode, anchor restoration for paragraphs and combat-event rows, restoration-scroll suppression).
- Python suite: 291 passed, 1 skipped.
- Browser check at 1366×680 (a 1366×768 screen minus browser chrome) against a mock-AI preview server: composer and reading column centered on the same axis; real mouse drag widens, saves, and collapses while keeping the pre-drag width; toggle restores; a paragraph mid-way through a long reply stayed at the same offset through widen, max clamp, live collapse, and restore; 600 px window uses the overlay (starts closed, Escape closes, preferences untouched); map panel and sidebar limits keep chat ≥ 420 px; no horizontal page scroll; Pilot off hides Pilot controls and cartridge viewers.
- Not checked: Firefox and Safari scrollbar rendering, 1920×1080, browser zoom other than 100%, and real multi-player sessions.

**Decision 5 measurement.** At 1366×680 with five party members and Pilot Mode on, the sidebar is 622 px tall and its content is 1068 px. Ready Override's bottom edge is at about 1013 px, so it needs a sidebar scroll; with four members it would still be about 970 px. Independent sidebar scrolling works, so this is within the accepted behavior, but Pilot users on 768-high laptops will routinely scroll the sidebar to reach Ready Override. Whether to move it (for example, to the bottom bar as AGENTS.md already describes) is left as a separate decision.
