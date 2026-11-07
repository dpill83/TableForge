# Cartridge geometry v1

`geometryVersion: 1` enables this optional contract in skeletons and run-data.
Skeleton `schemaVersion` is 2. Older cartridges without geometry remain valid.
The executable example is [fixtures/bidirectional-geometry.json](fixtures/bidirectional-geometry.json).

## Coordinates and rooms

All points have finite `xFt` and `yFt` in room-local feet. The origin is the
northwest of the room; east increases X and south increases Y. Generator room
rectangles describe interior floor cells; wall cells are outside that rectangle.
Door centers are projected onto the interior boundary, excluding wall thickness.
Opening widths measure along that boundary. Distances are spatial separations,
not guaranteed walking routes or visibility through walls and obstacles.

Each room has `geometry: { outline, features }`. The outline is an ordered,
closed, simple polygon of named segments `{ id, from, to }`; adjacent segments
share endpoints. Rectangular rooms use north/east/south/west IDs. Authored
irregular rooms use additional meaningful IDs such as alcove-east. Segment IDs
are identifiers; they need not be compass bearings. Features have unique `id`,
`type`, and optional `position` or polygon `footprint`. Omit unknown locations;
do not invent them from prose. Map-derived pillars and holes have positions.
Feature placement does not by itself make a feature player-visible.

## Connections

Top-level `connections` contains `{ id, endpoints: [endpoint, endpoint] }` per
physical opening, independently of direction of travel. IDs remain stable for
an unchanged map; generated IDs use opening grid coordinates, independent of
room numbering, RNG, locks, and export iteration order.

A room endpoint contains `roomNumber`, `boundaryId`, `position`, `widthFt`, and
a readable `description`. Its position is the opening midpoint on its boundary;
the full width must fit on that segment. An outside endpoint is exactly
`{ "roomNumber": null, "outside": true }`. Both endpoints are always included.

Each room exit/doorway contains the same `connectionId`, plus the existing
`direction`, `connectsTo`, `exitsDungeon`, and condition/type fields. Each physical
opening has one exit per room endpoint, even when two openings lead to the same
room. Outside `connectsTo` may retain legacy 0/null; `exitsDungeon` identifies it.
Spatial-facts visible and hidden exits also reference `connectionId`. Global
door records reference it for type/lock conditions. Geometry never contains
door state. Runtime state changes reference IDs without altering the cartridge.

Stage 2 copies top-level connections and room geometry verbatim. When source
skeleton data is supplied, validation checks preservation. Module validation and
ZIP export reject malformed geometry; geometry-free legacy cartridges pass.

## Narration and arrival

Room numbers never imply exploration order. Follow connectivity in either
direction. Use the actual arrival endpoint, preserving compass orientation,
instead of assuming a scene image or boxed-text viewpoint is the entrance.
Precise geometry takes precedence over older spatial-facts summaries and prose
for physical shape and placement; prose still supplies encounter fiction.
Unknown arrival means no invented near/far or left/right relationships. Do not
expose hidden openings, unseen destinations, or internal identifiers to players.

TableForge's stripped location marker may include the arrival connection:
`[Location: Area 4; Arrival: south-east-opening]`. `Arrival: unknown` explicitly
clears it; ordinary `[Location: Area 4]` markers remain valid. Save location and
arrival atomically on successful narration. Staying in a room preserves arrival
unless explicitly replaced/cleared; moving without valid arrival clears it.
Pilot location corrections and Approach clear arrival. Save/resume preserves it.
Existing saved prompt snapshots are not rewritten; new games use the new prompts.

## Release order

Ship TableForge compatibility first, then the AdventureForge exporter/prompts.
Do not retrofit live cartridges or existing saves. Verify using the shared fixture,
legacy tests, malformed-contract cases, and an export/import/play/resume workflow.
AI prose still requires a manual review against the source map.
