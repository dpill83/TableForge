# TableForge choice output format, version 1

This is an output-format instruction only. Keep the saved Stage 3 narration,
pacing, player agency, and spoiler rules. Do not create an extra decision point
or require a menu on every response.
For response formatting, this contract extends the console adapter's
location-marker-only metadata rule: the server also removes the choice block
before publishing the public narration.

When your public narration naturally offers concrete alternative actions, put
those actions in one final fenced `tableforge-choices` JSON block. Do not repeat
the option list in the prose: TableForge will append the labeled public list.
Keep the question or introduction in your narration. For example:

```tableforge-choices
{"groups":[{"playerId":"saved-player-id","options":["I lend a hand with the crew.","I keep an eye on the sea and ship."]},{"playerId":null,"options":["I suggest we explore the island.","I suggest we stay aboard."]}]}
```

Use only the exact playerId values in the supplied choice audiences. Target an
individual player's choices to that player's ID; use null only for alternatives
addressed to the whole party. Provide at most one group per audience. Use ordered
arrays of complete, short, first-person player responses, without letter labels.
All option text is public and will be shown to everyone. Include only actions
supported by the public situation, with no secrets or operational instructions.
A party-wide option expresses the selecting player's proposal, not a decision
already made by the whole group. Choices are suggestions, never exhaustive.

Omit the block when no concrete alternatives are offered. Ordinary questions,
requests for rolls or statistics, combat handoffs, and open-ended roleplay do not
need invented options. Do not put this metadata in ordinary code blocks or show
player IDs in the narration. Keep any location marker outside the choice block.
