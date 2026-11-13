# Minimal VTT exploration

**Status:** First slice implemented (shared map panel and one manually moved
party token). Later slices remain exploration only.  
**Date:** November 9, 2026 (first slice built November 13, 2026)

## Purpose

Explore a lightweight shared map within TableForge, using maps already packaged
in an AdventureForge cartridge. The first useful outcome is being able to see
where the party is and move a single party token. Eventually, the map could also
support dungeon exploration and combat positioning.

This document records an idea and a possible implementation sequence. It does
not authorize application changes, change the current combat workflow, or make
the later features requirements. Existing product guidance remains in effect
until a specific implementation scope is agreed.

## Direction from the discussion

- Prioritize getting a small, useful shared map experience working first.
- Start with one token representing the party's approximate location.
- Support moving that token manually; automatic movement is also desirable.
- Map reveal and fog of war are useful future enhancements, not prerequisites.
- Eventually consider individual pieces and battle positioning during combat.

The first slice uses manual movement only; see "First-slice decisions" below.
Automatic movement remains a candidate follow-up.

## Existing foundation

The current map viewer in `web/js/app.js` opens cartridge image assets and lets
a Pilot reveal an image to the party. That reveal exposes the whole image.
It does not currently provide a shared movable party marker.

The optional geometry contract described in `cartridge-geometry.md` supplies
room-local coordinates and connection endpoints. It does not by itself define
the transformation from those coordinates to pixels on a particular map image.
Do not assume every cartridge supplies geometry or calibrated map coordinates.

Cartridge assets remain read-only. Map selection, token placement, and other
playthrough-specific state belong to the save.

## Candidate first slice: shared map and party marker

The smallest useful workflow would be:

1. Select a cartridge map using the existing map access/reveal rules.
2. Open a view with zoom and pan, ideally usable alongside the conversation.
3. Place one clearly visible party token on the map.
4. Let trusted players drag the token to update the party's approximate position.
5. Share the committed position with other connected clients.
6. Restore the selected map and token position when the adventure is loaded.

Token movement would be a shared visual aid. It would not submit a character
action, advance narration, change Ready state, or independently change the
AI-DM's recorded adventure location. In combat, the same marker could remain
available without changing the existing human-run combat workflow.

Keep Pilot Mode for supervisory controls. Ordinary use of a map already revealed
to the party should not require a permanent map operator or new player roles.

### Candidate completion criteria

- Two clients viewing the same save see the same map and committed token position.
- Any trusted player can move the party token on an available shared map.
- Reloading or restarting preserves the committed position.
- Zooming and panning do not move the token relative to the image.
- Switching maps does not accidentally apply one map's coordinates to another.
- Conflicting moves resolve consistently without creating duplicate tokens.
- Unrevealed assets retain their existing access restrictions.
- Chat, Ready, generation, and combat behavior continue independently.

These are proposed checks for a future implementation, not tasks started by
this document.

## Automatic movement: a possible follow-up

Automatic movement could follow successful adventure-location updates already
recorded by TableForge. Each known room/location would need an anchor point on
the selected map. Entering that location would move the party token to its
anchor, representing approximate room-level position.

Possible sources for those anchors:

- A lightweight manual setup in TableForge, with anchors stored in the save.
- An optional future AdventureForge export linking location identifiers to map
  coordinates. This would be authored by AdventureForge and consumed by TableForge.

Older cartridges should remain usable through manual token placement. Missing
anchors should leave the token in place and make the lack of an automatic
update understandable; they should not cause guessed placement from narration.

Before implementing automatic movement, decide how it interacts with manual
placement. For example, a subsequent room change might move the token while
same-room narration preserves a player's more precise placement. Automatic
updates should follow committed location changes, so failed narration cannot
move the party on the shared map.

## Later possibilities

Consider these separately after the basic map proves useful:

- Shared pointer/pings.
- Individual character and creature tokens for combat positioning.
- Optional grid calibration, snapping, and distance measurement.
- Manual region reveal and persistent fog of war.
- Player-safe map variants supplied by AdventureForge.
- More detailed exploration or visibility behavior, if playtesting warrants it.

These ideas do not imply initiative tracking, HP management, dice automation,
automated monster turns, movement enforcement, or a rules engine.

## Spoiler handling

The first slice could retain today's explicit whole-image reveal. It should be
clear that choosing to reveal a map makes all markings in that image visible,
including baked-in labels or secret doors. Deferring fog of war does not imply
automatically revealing every cartridge map.

Future fog of war needs its own design. A browser overlay alone cannot protect
an unrevealed original image that the player can still download. Also, revealing
a region does not remove secret markings already drawn inside that region.
Player-safe artwork and server-side delivery of revealed content may be needed,
depending on the spoiler guarantees chosen for that feature.

## Technical considerations for a future implementation

- Extend the existing plain JavaScript/Python application where practical.
- Reference a stable cartridge asset identifier rather than copying or editing
  the source image as part of normal play.
- Store marker coordinates independently of viewport size, such as normalized
  image coordinates. Pan and zoom can remain local to each viewer.
- Keep map state scoped to the save and the specific map asset.
- Use server-authoritative committed positions and an explicit conflict policy;
  smooth live dragging across clients is optional for the first slice.
- Define behavior when an asset is missing or replaced; do not silently attach
  old positions to a different image.
- Preserve compatibility with saves that have no map state.

Exact schema, API routes, synchronization method, and screen layout are deferred
until implementation is requested.

## First-slice decisions (agreed November 12, 2026)

1. **Movement:** manual only. The token moves when a trusted player drags it.
   Automatic room-level movement is a later slice, assessed after play.
2. **Presentation:** a resizable panel beside the chat feed, so narration stays
   readable while the map is open. Closing it restores the normal layout.
3. **Maps:** the save records one current shared table map, which any trusted
   player can switch. Each map remembers its own party position, so switching
   back restores that map's token.
4. **Simultaneous moves:** the last committed move wins. Other clients update on
   their next refresh, and the save records who moved the token.
5. **Anchor setup and manual override:** deferred with automatic movement.

## Suggested sequence

1. Agree the first slice using this document (done; see "First-slice decisions").
2. Build and verify shared map viewing, one manually movable party token, and
   save/resume behavior.
3. Try it during normal play and assess whether automatic location following
   or another small usability improvement is the most useful next step.
4. Explore individual combat pieces and fog of war as separate future slices.

## First slice as built

- **Opening it:** Tools → Map toggles a resizable panel beside the chat. On
  narrow screens it covers the chat until closed. Each viewer's open/closed
  state and panel width are remembered in their own browser.
- **Choosing the map:** the panel lists only maps already revealed to the party.
  Any player can switch the shared map; Pilot Mode's GM Map dialog also offers
  "Show on table map" for revealed images. Revealing still requires Pilot Mode.
- **Token:** "Place party token" drops it in the middle of the current view.
  Drag it (or focus it and use the arrow keys, Shift for bigger steps) to move
  it. Background drag pans; wheel or pinch zooms; Fit shows the whole map.
- **Sync and storage:** `table_map.py` stores the selected map on the save and
  one normalized position per map in `map_tokens`. Moves name their map, so a
  move made as someone switches maps stays on its own map. The last committed
  move wins, records who made it, and reaches other browsers on the next
  refresh. Map selection is logged as a `table_map_selected` session event.
- **Independence:** map actions work during AI generation and combat, never
  change Ready, beats, or messages, and are not sent to the AI-DM.
- **Tests:** `tests/test_table_map.py` (server rules, restart, deletion) and
  `tests/test_table_map.cjs` (pan/zoom coordinate math).
