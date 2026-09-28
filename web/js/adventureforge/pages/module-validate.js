import { buildSpatialFacts, missingMajorFeatures } from '../dungeon/spatial-facts.js';

/**
 * Headless module-artifact validator. Pure function — no DOM, no I/O.
 *
 * @typedef {'pass' | 'fail' | 'warn' | 'skip'} CheckStatus
 *
 * @typedef {object} CheckResult
 * @prop {string} id
 * @prop {string} name
 * @prop {CheckStatus} status
 * @prop {string[]} messages
 *
 * @typedef {object} ValidateSummary
 * @prop {number} okRooms
 * @prop {number} fails
 * @prop {number} warnings
 * @prop {number} skips
 *
 * @typedef {object} ValidateResult
 * @prop {CheckResult[]} checks
 * @prop {ValidateSummary} summary
 * @prop {boolean} ok
 * @prop {string} summaryLine
 *
 * @typedef {object} RunDataRoom
 * @prop {number} [roomNumber]
 * @prop {string} [boxedText]
 * @prop {number[]} [connectsTo]
 * @prop {object[]} [exits]
 * @prop {object} [encounter]
 * @prop {string} [lore]
 * @prop {object} [spatialFacts]
 * @prop {object[]} [doorways]
 *
 * @typedef {object} RunData
 * @prop {RunDataRoom[]} [rooms]
 * @prop {object[]} [party]
 * @prop {object} [villain]
 * @prop {object} [hook]
 * @prop {object} [openThread]
 * @prop {object[]} [statBlocks]
 *
 * @typedef {object} ValidateOptions
 * @prop {string} [moduleText]
 * @prop {object} [cast]
 * @prop {object} [scenes]
 * @prop {object} [skeleton]
 */

const PLACEHOLDER_PATTERNS = [
    /\/\*/,
    /\*\//,
    /\bTODO\b/i,
    /full entries/i,
    /matching boxedText/i,
];

const IMPASSABLE_RE = /\b(impassable|sealed|cannot (be )?(bypassed|opened|passed)|no (crawlspace|gap)|hard barrier|hard edge)\b/i;

const HARD_EDGE_TYPES = new Set([ 'secret', 'concealed' ]);

const NAME_STOP = new Set([
    'The', 'A', 'An', 'And', 'Or', 'But', 'If', 'When', 'While', 'After', 'Before',
    'She', 'He', 'They', 'It', 'We', 'You', 'His', 'Her', 'Their',
    'How', 'What', 'Why', 'Who', 'Where', 'Which',
    'Later', 'Then', 'Next', 'Soon', 'Once', 'Now',
    'Room', 'Area', 'Boxed', 'Encounter',
    'People', 'Five', 'Carrying', 'Bring', 'Let',
]);

/** Final tokens that mark place / MacGuffin phrases, not person names. */
const PLACE_LAST = new Set([
    'Barrow', 'Hill', 'Manor', 'Heart', 'Spindle', 'Grove', 'Crypt', 'Keep', 'Tower',
]);

/**
 * @param {RunData | null | undefined} runData
 * @param {ValidateOptions} [options]
 *
 * @returns {ValidateResult}
 */
export function validateModuleArtifacts(runData, options = {}) {
    const { moduleText, cast, scenes, skeleton } = options;
    const rooms = Array.isArray(runData?.rooms) ? runData.rooms : null;

    const check1 = checkStubs(rooms);
    const check2 = checkBoxedTextIdentity(rooms, moduleText);
    const check3 = checkExitConsistency(rooms);
    const check4 = checkHardEdges(rooms, moduleText);
    const check5 = checkCastCompleteness(runData, cast);
    const check6 = checkScenesCoverage(rooms, scenes);
    const check7 = checkSceneSpatialFacts(rooms, scenes, skeleton);

    const checks = [ check1, check2, check3, check4, check5, check6, check7 ];
    const fails = checks.filter((c) => c.status === 'fail').length;
    const warnings = checks.filter((c) => c.status === 'warn').length;
    const skips = checks.filter((c) => c.status === 'skip').length;
    const okRooms = rooms
        ? rooms.filter((room) => roomHasNoHardFail(room, checks)).length
        : 0;

    const summary = { okRooms, fails, warnings, skips };
    const summaryLine = formatSummaryLine(summary, rooms?.length ?? 0);

    return {
        checks,
        summary,
        ok: fails === 0,
        summaryLine,
    };
}

/**
 * @param {RunDataRoom[] | null} rooms
 *
 * @returns {CheckResult}
 */
function checkStubs(rooms) {
    const id = 'stubs';
    const name = 'Stub detection';

    if (!rooms || rooms.length === 0) {
        return fail(id, name, [ 'rooms is missing, empty, or not an array' ]);
    }

    /** @type {string[]} */
    const messages = [];

    rooms.forEach((room, index) => {
        const label = roomLabel(room, index);
        const text = room.boxedText;

        if (typeof text !== 'string' || text.trim() === '') {
            messages.push(`${label}: boxedText is missing or empty`);
            return;
        }

        if (isPlaceholderBoxedText(text)) {
            messages.push(`${label}: boxedText looks like a placeholder (${snippet(text)})`);
        }
    });

    return messages.length ? fail(id, name, messages) : pass(id, name);
}

/**
 * @param {RunDataRoom[] | null} rooms
 * @param {string | undefined} moduleText
 *
 * @returns {CheckResult}
 */
function checkBoxedTextIdentity(rooms, moduleText) {
    const id = 'boxedText';
    const name = 'Boxed text identity';

    if (moduleText == null || moduleText === '') {
        return skip(id, name, [ 'module.md not provided' ]);
    }

    if (!rooms) {
        return skip(id, name, [ 'no rooms to compare' ]);
    }

    const searchable = moduleSearchText(moduleText);
    /** @type {string[]} */
    const messages = [];

    rooms.forEach((room, index) => {
        const label = roomLabel(room, index);
        const boxed = typeof room.boxedText === 'string' ? room.boxedText : '';

        if (!boxed) {
            return;
        }

        if (searchable.includes(boxed)) {
            return;
        }

        const divergence = firstDivergence(boxed, searchable);
        messages.push(
            `${label}: run-data boxedText not found verbatim in module`
            + (divergence ? ` — first divergence at offset ${divergence.index}: `
                + `expected ${JSON.stringify(divergence.expected)} vs found ${JSON.stringify(divergence.found)}` : ''),
        );
    });

    return messages.length ? fail(id, name, messages) : pass(id, name);
}

/**
 * @param {RunDataRoom[] | null} rooms
 *
 * @returns {CheckResult}
 */
function checkExitConsistency(rooms) {
    const id = 'exits';
    const name = 'Exit edge-set consistency';

    if (!rooms) {
        return fail(id, name, [ 'rooms is missing; cannot check exits' ]);
    }

    /** @type {string[]} */
    const messages = [];
    /** @type {Map<number, RunDataRoom>} */
    const byNumber = new Map();

    rooms.forEach((room, index) => {
        const num = typeof room.roomNumber === 'number' ? room.roomNumber : index + 1;
        byNumber.set(num, room);
    });

    rooms.forEach((room, index) => {
        const label = roomLabel(room, index);
        const exits = Array.isArray(room.exits) ? room.exits : [];
        /** @type {Map<string, number>} */
        const seen = new Map();
        /** @type {Set<number>} */
        const exitDests = new Set();

        exits.forEach((exit) => {
            const direction = String(/** @type {{ direction?: unknown }} */ (exit).direction ?? '');
            const connectsTo = /** @type {{ connectsTo?: unknown }} */ (exit).connectsTo;
            const key = edgeKey(direction, connectsTo);
            const count = (seen.get(key) || 0) + 1;
            seen.set(key, count);

            if (count === 2) {
                messages.push(`${label}: duplicate exit ${key}`);
            }

            if (typeof connectsTo === 'number') {
                exitDests.add(connectsTo);
            }
        });

        const declared = new Set(
            (Array.isArray(room.connectsTo) ? room.connectsTo : [])
                .filter((n) => typeof n === 'number'),
        );

        for (const dest of exitDests) {
            if (!declared.has(dest)) {
                messages.push(
                    `${label}: exit connectsTo ${dest} missing from room.connectsTo [${[ ...declared ].join(', ')}]`,
                );
            }
        }

        for (const dest of declared) {
            if (!exitDests.has(dest)) {
                messages.push(
                    `${label}: connectsTo lists ${dest} but no matching exit`,
                );
            }
        }

        exits.forEach((exit) => {
            const direction = String(/** @type {{ direction?: unknown }} */ (exit).direction ?? '');
            const connectsTo = /** @type {{ connectsTo?: unknown }} */ (exit).connectsTo;

            if (typeof connectsTo !== 'number') {
                return;
            }

            const peer = byNumber.get(connectsTo);

            if (!peer) {
                messages.push(
                    `${label}: exit ${edgeKey(direction, connectsTo)} targets missing room ${connectsTo}`,
                );
                return;
            }

            const peerExits = Array.isArray(peer.exits) ? peer.exits : [];
            const fromNum = typeof room.roomNumber === 'number' ? room.roomNumber : index + 1;
            const hasReciprocal = peerExits.some((peerExit) => {
                const peerTo = /** @type {{ connectsTo?: unknown }} */ (peerExit).connectsTo;
                return peerTo === fromNum;
            });

            if (!hasReciprocal) {
                messages.push(
                    `${label}: exit ${edgeKey(direction, connectsTo)} has no reciprocal edge from Room ${connectsTo}`,
                );
            }
        });
    });

    return messages.length ? fail(id, name, messages) : pass(id, name);
}

/**
 * @param {RunDataRoom[] | null} rooms
 * @param {string | undefined} moduleText
 *
 * @returns {CheckResult}
 */
function checkHardEdges(rooms, moduleText) {
    const id = 'hardEdges';
    const name = 'Hard-edge integrity (heuristic)';

    if (!rooms) {
        return skip(id, name, [ 'no rooms' ]);
    }

    /** @type {string[]} */
    const messages = [];
    let candidates = 0;

    rooms.forEach((room, index) => {
        const label = roomLabel(room, index);
        const exits = Array.isArray(room.exits) ? room.exits : [];

        exits.forEach((exit) => {
            if (!isHardEdgeExit(exit)) {
                return;
            }

            candidates += 1;
            const direction = String(/** @type {{ direction?: unknown }} */ (exit).direction ?? '?');
            const flavor = String(/** @type {{ flavor?: unknown }} */ (exit).flavor ?? '');

            if (!IMPASSABLE_RE.test(flavor)) {
                messages.push(
                    `${label}: hard-edge exit ${direction} flavor does not describe impassability (heuristic warning)`,
                );
            }

            if (moduleText) {
                const section = roomModuleSection(moduleText, room.roomNumber ?? index + 1);

                if (section && !IMPASSABLE_RE.test(section)) {
                    messages.push(
                        `${label}: module text for this room does not mention impassability for hard-edge ${direction} (heuristic warning)`,
                    );
                }
            }
        });
    });

    if (candidates === 0) {
        return skip(id, name, [
            'no hard-edge candidates on run-data exits (locked/secret/hardEdge/type secret|concealed); map-art brief not checked',
        ]);
    }

    return messages.length
        ? warn(id, name, messages)
        : pass(id, name, [ `${candidates} hard-edge exit(s) checked (map-art brief not provided; skipped)` ]);
}

/**
 * @param {RunData | null | undefined} runData
 * @param {object | undefined} cast
 *
 * @returns {CheckResult}
 */
function checkCastCompleteness(runData, cast) {
    const id = 'cast';
    const name = 'Cast completeness (heuristic)';

    if (!cast) {
        return skip(id, name, [ 'cast list not provided' ]);
    }

    const members = castMembers(cast);
    const castNames = members.map((n) => n.toLowerCase());
    const partyNames = new Set(
        (Array.isArray(runData?.party) ? runData.party : [])
            .map((p) => String(/** @type {{ name?: unknown }} */ (p).name || '').toLowerCase())
            .filter(Boolean),
    );

    /** @type {string[]} */
    const messages = [];
    /** @type {Set<string>} */
    const warned = new Set();

    const villainName = typeof runData?.villain?.name === 'string'
        ? runData.villain.name.trim()
        : '';

    if (villainName && !nameInCast(villainName, castNames)) {
        messages.push(`Villain "${villainName}" not found in cast`);
        warned.add(villainName.toLowerCase());
    }

    const statBlocks = Array.isArray(runData?.statBlocks) ? runData.statBlocks : [];

    for (const entry of statBlocks) {
        const blockName = typeof /** @type {{ name?: unknown }} */ (entry).name === 'string'
            ? /** @type {{ name: string }} */ (entry).name.trim()
            : '';

        if (!blockName) {
            continue;
        }

        const key = blockName.toLowerCase();

        if (warned.has(key) || nameInCast(blockName, castNames)) {
            continue;
        }

        if ([ ...warned ].some((w) => w.includes(key) || key.includes(w))) {
            continue;
        }

        messages.push(`Stat block "${blockName}" not found in cast`);
        warned.add(key);
    }

    const corpus = structuredNameCorpus(runData);
    const candidates = collapseNameSubstrings(
        extractProperNames(corpus)
            .filter((candidate) => !partyNames.has(candidate.toLowerCase()))
            .filter((candidate) => !NAME_STOP.has(candidate))
            .filter((candidate) => !NAME_STOP.has(candidate.split(/\s+/)[0]))
            .filter((candidate) => !candidate.split(/\s+/).every((part) => NAME_STOP.has(part)))
            .filter((candidate) => !isPlacePhrase(candidate))
            .filter((candidate) => isPlausibleNpcName(candidate, corpus)),
    );

    for (const candidate of candidates) {
        const key = candidate.toLowerCase();

        if (warned.has(key) || nameInCast(candidate, castNames)) {
            continue;
        }

        // Avoid a second warning when a shorter extract is covered by the villain warning.
        if ([ ...warned ].some((w) => w.includes(key) || key.includes(w))) {
            continue;
        }

        messages.push(`Named NPC "${candidate}" not found in cast (heuristic warning)`);
        warned.add(key);
    }

    return messages.length ? warn(id, name, messages) : pass(id, name);
}

/**
 * Collect prose from structured run-data fields where plot NPCs are named.
 *
 * @param {RunData | null | undefined} runData
 *
 * @returns {string}
 */
function structuredNameCorpus(runData) {
    if (!runData || typeof runData !== 'object') {
        return '';
    }

    const hook = /** @type {{ dmSecrets?: unknown, patronFAQ?: unknown }} */ (runData.hook || {});
    const openThread = /** @type {{ summary?: unknown, seedForNext?: unknown }} */ (
        runData.openThread || {}
    );
    const faq = Array.isArray(hook.patronFAQ) ? hook.patronFAQ : [];

    /** @type {string[]} */
    const parts = [];

    if (typeof hook.dmSecrets === 'string') {
        parts.push(hook.dmSecrets);
    }

    for (const item of faq) {
        const row = /** @type {{ q?: unknown, a?: unknown }} */ (item || {});

        if (typeof row.q === 'string') {
            parts.push(row.q);
        }

        if (typeof row.a === 'string') {
            parts.push(row.a);
        }
    }

    if (typeof openThread.summary === 'string') {
        parts.push(openThread.summary);
    }

    if (typeof openThread.seedForNext === 'string') {
        parts.push(openThread.seedForNext);
    }

    return parts.join('\n');
}

/**
 * @param {string} name
 * @param {string[]} castNamesLower
 *
 * @returns {boolean}
 */
function nameInCast(name, castNamesLower) {
    const needle = name.toLowerCase();

    return castNamesLower.some((c) => c.includes(needle) || needle.includes(c));
}

/**
 * Prefer multi-word names: drop a candidate that is a substring of a longer one.
 *
 * @param {string[]} names
 *
 * @returns {string[]}
 */
function collapseNameSubstrings(names) {
    const unique = [ ...new Set(names) ];
    const lower = unique.map((n) => n.toLowerCase());

    return unique.filter((name, index) => {
        const key = lower[index];

        return !lower.some((other, otherIndex) => (
            otherIndex !== index
            && other.length > key.length
            && other.includes(key)
        ));
    });
}

/**
 * @param {string} name
 *
 * @returns {boolean}
 */
function isPlacePhrase(name) {
    const parts = name.split(/\s+/);
    const last = parts[parts.length - 1];

    return parts.length > 1 && PLACE_LAST.has(last);
}

/**
 * Single-token one-off capitals are usually not NPC names.
 * Multi-word runs and repeated single tokens are kept.
 *
 * @param {string} name
 * @param {string} corpus
 *
 * @returns {boolean}
 */
function isPlausibleNpcName(name, corpus) {
    const parts = name.split(/\s+/);

    if (parts.length > 1) {
        return true;
    }

    return countNameMentions(name, corpus) >= 2;
}

/**
 * @param {string} name
 * @param {string} corpus
 *
 * @returns {number}
 */
function countNameMentions(name, corpus) {
    const re = new RegExp(`\\b${escapeRegExp(name)}(?:['\u2019]s)?\\b`, 'gi');
    const matches = corpus.match(re);

    return matches ? matches.length : 0;
}

/**
 * @param {string} value
 *
 * @returns {string}
 */
function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * @param {RunDataRoom[] | null} rooms
 * @param {object | undefined} scenes
 *
 * @returns {CheckResult}
 */
function checkScenesCoverage(rooms, scenes) {
    const id = 'scenes';
    const name = 'Scenes coverage (heuristic)';

    if (!scenes) {
        return skip(id, name, [ 'scenes file not provided' ]);
    }

    if (!rooms) {
        return skip(id, name, [ 'no rooms' ]);
    }

    const covered = new Set(
        sceneRoomNumbers(scenes),
    );

    /** @type {string[]} */
    const messages = [];

    rooms.forEach((room, index) => {
        const monsters = /** @type {{ monsters?: unknown }} */ (room.encounter || {}).monsters;
        const hasEncounter = Array.isArray(monsters) && monsters.length > 0;

        if (!hasEncounter) {
            return;
        }

        const num = typeof room.roomNumber === 'number' ? room.roomNumber : index + 1;

        if (!covered.has(num)) {
            messages.push(
                `Room ${num}: has encounter monsters but no scenes entry (heuristic warning)`,
            );
        }
    });

    return messages.length ? warn(id, name, messages) : pass(id, name);
}

/**
 * @param {RunDataRoom[] | null} rooms
 * @param {object | undefined} scenes
 * @param {object | undefined} skeleton
 *
 * @returns {CheckResult}
 */
function checkSceneSpatialFacts(rooms, scenes, skeleton) {
    const id = 'sceneSpatial';
    const name = 'Scene spatial facts (heuristic)';

    if (!scenes) {
        return skip(id, name, [ 'scenes file not provided' ]);
    }

    const sceneList = sceneEntries(scenes);

    if (!sceneList.length) {
        return skip(id, name, [ 'no scene entries' ]);
    }

    const skeletonRooms = Array.isArray(/** @type {{ rooms?: unknown }} */ (skeleton || {}).rooms)
        ? /** @type {{ rooms: object[] }} */ (skeleton).rooms
        : [];

    const skeletonByNumber = roomsByNumber(skeletonRooms);
    const runByNumber = roomsByNumber(rooms || []);

    /** @type {string[]} */
    const messages = [];

    sceneList.forEach((scene) => {
        const num = scene.roomNumber ?? scene.room;

        if (typeof num !== 'number') {
            return;
        }

        const facts = spatialFactsForRoom(skeletonByNumber.get(num), runByNumber.get(num));

        if (!facts) {
            return;
        }

        [ [ 'reveal1', scene.reveal1 ], [ 'reveal2', scene.reveal2 ] ].forEach(([ label, reveal ]) => {
            const prompt = revealPrompt(reveal);

            if (!prompt) {
                return;
            }

            missingMajorFeatures(prompt, facts).forEach((feature) => {
                messages.push(
                    `Room ${num} ${label}: missing major ${feature.type}`,
                );
            });
        });
    });

    return messages.length ? warn(id, name, messages) : pass(id, name);
}

/**
 * @param {unknown} reveal
 *
 * @returns {string}
 */
function revealPrompt(reveal) {
    if (typeof reveal === 'string') {
        return reveal;
    }

    if (!reveal || typeof reveal !== 'object') {
        return '';
    }

    const row = /** @type {{ prompt?: unknown, description?: unknown }} */ (reveal);

    if (typeof row.prompt === 'string') {
        return row.prompt;
    }

    if (typeof row.description === 'string') {
        return row.description;
    }

    return '';
}

/**
 * @param {object} scenes
 *
 * @returns {object[]}
 */
function sceneEntries(scenes) {
    if (Array.isArray(/** @type {{ scenes?: unknown }} */ (scenes).scenes)) {
        return /** @type {{ scenes: object[] }} */ (scenes).scenes;
    }

    if (Array.isArray(scenes)) {
        return scenes;
    }

    return [];
}

/**
 * @param {object[]} rooms
 *
 * @returns {Map<number, object>}
 */
function roomsByNumber(rooms) {
    /** @type {Map<number, object>} */
    const map = new Map();

    rooms.forEach((room) => {
        const num = /** @type {{ roomNumber?: unknown }} */ (room).roomNumber;

        if (typeof num === 'number') {
            map.set(num, room);
        }
    });

    return map;
}

/**
 * Prefer skeleton layout (same bones as the battlemap), then run-data exits.
 *
 * @param {object | undefined} skeletonRoom
 * @param {object | undefined} runRoom
 *
 * @returns {object | null}
 */
function spatialFactsForRoom(skeletonRoom, runRoom) {
    const skeletonFacts = /** @type {{ spatialFacts?: import('../dungeon/spatial-facts.js').SpatialFacts }} */ (skeletonRoom || {}).spatialFacts;

    if (skeletonFacts) {
        return skeletonFacts;
    }

    if (skeletonRoom) {
        return buildSpatialFacts(skeletonRoom);
    }

    const runFacts = /** @type {{ spatialFacts?: import('../dungeon/spatial-facts.js').SpatialFacts }} */ (runRoom || {}).spatialFacts;

    if (runFacts) {
        return runFacts;
    }

    if (runRoom) {
        return buildSpatialFacts(runRoom);
    }

    return null;
}

// -- Helpers ------------------------------------------------------------------

/**
 * @param {string} text
 *
 * @returns {boolean}
 */
export function isPlaceholderBoxedText(text) {
    const trimmed = text.trim();

    if (!trimmed) {
        return true;
    }

    if (/^(\.\.\.|…|\.{3,})$/.test(trimmed)) {
        return true;
    }

    return PLACEHOLDER_PATTERNS.some((re) => re.test(trimmed));
}

/**
 * Strip markdown blockquote markers so run-data boxedText can match module body.
 *
 * @param {string} moduleText
 *
 * @returns {string}
 */
function moduleSearchText(moduleText) {
    return moduleText
        .split('\n')
        .map((line) => line.replace(/^>\s?/, ''))
        .join('\n');
}

/**
 * @param {string} expected
 * @param {string} haystack
 *
 * @returns {{ index: number, expected: string, found: string } | null}
 */
function firstDivergence(expected, haystack) {
    // Find best partial prefix match for a useful message.
    let best = 0;
    let bestAt = -1;

    for (let i = 0; i < haystack.length; i++) {
        let n = 0;

        while (
            n < expected.length
            && i + n < haystack.length
            && haystack[i + n] === expected[n]
        ) {
            n += 1;
        }

        if (n > best) {
            best = n;
            bestAt = i;
        }
    }

    if (bestAt < 0) {
        return {
            index: 0,
            expected: snippet(expected, 40),
            found: snippet(haystack, 40),
        };
    }

    return {
        index: best,
        expected: snippet(expected.slice(best), 40),
        found: snippet(haystack.slice(bestAt + best), 40),
    };
}

/**
 * @param {unknown} exit
 *
 * @returns {boolean}
 */
function isHardEdgeExit(exit) {
    const e = /** @type {{ locked?: unknown, secret?: unknown, hardEdge?: unknown, type?: unknown }} */ (exit);

    if (e.locked === true || e.secret === true || e.hardEdge === true) {
        return true;
    }

    return typeof e.type === 'string' && HARD_EDGE_TYPES.has(e.type);
}

/**
 * @param {string} moduleText
 * @param {number} roomNumber
 *
 * @returns {string}
 */
function roomModuleSection(moduleText, roomNumber) {
    const re = new RegExp(
        `(?:^|\\n)##\\s*Area\\s+${roomNumber}\\b[\\s\\S]*?(?=\\n##\\s*Area\\s+\\d+|\\n##\\s(?!#)|\n$)`,
        'i',
    );
    const match = moduleText.match(re);

    return match ? match[0] : moduleText;
}

/**
 * @param {object} cast
 *
 * @returns {string[]}
 */
function castMembers(cast) {
    const raw = /** @type {{ cast?: unknown, characters?: unknown, npcs?: unknown }} */ (cast);
    const list = Array.isArray(raw.cast)
        ? raw.cast
        : Array.isArray(raw.characters)
            ? raw.characters
            : Array.isArray(raw.npcs)
                ? raw.npcs
                : [];

    return list
        .map((m) => String(/** @type {{ name?: unknown }} */ (m).name || '').trim())
        .filter(Boolean);
}

/**
 * @param {object} scenes
 *
 * @returns {number[]}
 */
function sceneRoomNumbers(scenes) {
    const list = Array.isArray(/** @type {{ scenes?: unknown }} */ (scenes).scenes)
        ? /** @type {{ scenes: object[] }} */ (scenes).scenes
        : Array.isArray(scenes)
            ? /** @type {object[]} */ (scenes)
            : [];

    return list
        .map((s) => {
            const row = /** @type {{ roomNumber?: unknown, room?: unknown }} */ (s);
            const n = row.roomNumber ?? row.room;
            return typeof n === 'number' ? n : NaN;
        })
        .filter((n) => !Number.isNaN(n));
}

/**
 * Conservative proper-name harvest: sequences of one to three Capitalized tokens.
 *
 * @param {string} text
 *
 * @returns {string[]}
 */
function extractProperNames(text) {
    /** @type {Set<string>} */
    const found = new Set();
    const re = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b/g;
    let match;

    while ((match = re.exec(text)) !== null) {
        const name = match[1];

        if (name.split(/\s+/).every((part) => NAME_STOP.has(part))) {
            continue;
        }

        if (name.length < 3) {
            continue;
        }

        found.add(name);
    }

    return [ ...found ];
}

/**
 * @param {string} direction
 * @param {unknown} connectsTo
 *
 * @returns {string}
 */
function edgeKey(direction, connectsTo) {
    const dest = connectsTo === null || connectsTo === undefined
        ? 'null'
        : String(connectsTo);

    return `${direction}->${dest}`;
}

/**
 * @param {RunDataRoom} room
 * @param {number} index
 *
 * @returns {string}
 */
function roomLabel(room, index) {
    const num = typeof room.roomNumber === 'number' ? room.roomNumber : index + 1;
    return `Room ${num}`;
}

/**
 * @param {string} text
 * @param {number} [max]
 *
 * @returns {string}
 */
function snippet(text, max = 48) {
    const t = text.replace(/\s+/g, ' ').trim();
    return t.length <= max ? t : `${t.slice(0, max)}…`;
}

/**
 * @param {RunDataRoom} room
 * @param {CheckResult[]} checks
 *
 * @returns {boolean}
 */
function roomHasNoHardFail(room, checks) {
    const label = `Room ${room.roomNumber}`;
    return !checks.some((c) => (
        c.status === 'fail'
        && c.messages.some((m) => m.startsWith(label))
    ));
}

/**
 * @param {ValidateSummary} summary
 * @param {number} roomCount
 *
 * @returns {string}
 */
function formatSummaryLine(summary, roomCount) {
    const parts = [
        `${summary.okRooms}/${roomCount} rooms OK`,
        `${summary.fails} fail${summary.fails === 1 ? '' : 's'}`,
        `${summary.warnings} warning${summary.warnings === 1 ? '' : 's'}`,
    ];

    if (summary.skips) {
        parts.push(`${summary.skips} skip${summary.skips === 1 ? '' : 's'}`);
    }

    return parts.join(', ');
}

/**
 * @param {string} id
 * @param {string} name
 * @param {string[]} [messages]
 *
 * @returns {CheckResult}
 */
function pass(id, name, messages = []) {
    return { id, name, status: 'pass', messages };
}

/**
 * @param {string} id
 * @param {string} name
 * @param {string[]} messages
 *
 * @returns {CheckResult}
 */
function fail(id, name, messages) {
    return { id, name, status: 'fail', messages };
}

/**
 * @param {string} id
 * @param {string} name
 * @param {string[]} messages
 *
 * @returns {CheckResult}
 */
function warn(id, name, messages) {
    return { id, name, status: 'warn', messages };
}

/**
 * @param {string} id
 * @param {string} name
 * @param {string[]} messages
 *
 * @returns {CheckResult}
 */
function skip(id, name, messages) {
    return { id, name, status: 'skip', messages };
}
