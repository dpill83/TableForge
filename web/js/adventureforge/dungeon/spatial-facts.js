// @ts-check

import { cellFeet } from './grid.js';

/** @typedef {import('./map.js').Door} Door */
/** @typedef {import('./grid.js').Rectangle} Rectangle */
/** @typedef {import('../item/generate.js').Item} Item */
/** @typedef {import('../item/generate.js').Container} Container */

/**
 * @typedef {object} SpatialConnector
 * @prop {string} direction
 * @prop {string} type
 * @prop {boolean} [locked]
 * @prop {Rectangle} [rectangle]
 */

/**
 * @typedef {object} SpatialExit
 * @prop {string} wall
 * @prop {string} type
 * @prop {boolean} [locked]
 */

/**
 * @typedef {object} SpatialFeature
 * @prop {string} type
 * @prop {string} [shape]
 * @prop {string} [wall]
 * @prop {string} [position]
 * @prop {'major' | 'minor'} prominence
 * @prop {number} [count]
 * @prop {string} [size]
 */

/**
 * @typedef {object} SpatialViewpoint
 * @prop {string} from
 * @prop {string} looking
 * @prop {string} description
 */

/**
 * @typedef {object} SpatialFacts
 * @prop {number} roomNumber
 * @prop {{ widthFt: number, lengthFt: number }} [dimensions]
 * @prop {string} [shape]
 * @prop {SpatialViewpoint} [viewpoint]
 * @prop {SpatialExit[]} exits
 * @prop {SpatialFeature[]} floorFeatures
 * @prop {SpatialFeature[]} wallFeatures
 * @prop {SpatialFeature[]} obstacles
 * @prop {SpatialFeature[]} dressing
 * @prop {SpatialExit[]} hiddenExits
 */

/** Rooms this large (cells on both axes) get corner pillars on the map. */
export const pillarGridThreshold = 6;

const hiddenConnectorTypes = new Set([ 'secret', 'concealed' ]);

/** @type {Record<string, string>} */
const oppositeWall = {
    north: 'south',
    south: 'north',
    east : 'west',
    west : 'east',
};

const largeItemSizes = new Set([ 'large', 'massive' ]);

/** @type {Record<string, string[]>} */
const majorFeatureTokens = {
    hole   : [ 'hole', 'shaft', 'pit' ],
    pillars: [ 'pillar', 'pillars' ],
    stairs : [ 'stair', 'stairs', 'staircase' ],
};

// -- Private Functions --------------------------------------------------------

/**
 * @param {{ size?: number[], rectangle?: Rectangle }} room
 *
 * @returns {number[] | undefined}
 */
function getRoomSize(room) {
    if (Array.isArray(room.size) && room.size.length >= 2) {
        return [ room.size[0], room.size[1] ];
    }

    if (room.rectangle) {
        return [ room.rectangle.width, room.rectangle.height ];
    }
}

/**
 * @param {string} type
 *
 * @returns {string}
 */
function visibleExitType(type) {
    if (type === 'passageway') {
        return 'open passage';
    }

    return type;
}

/**
 * @param {number} [roomNumber]
 * @param {Door[]} [roomDoors]
 * @param {{ doorways?: object[], exits?: object[] }} room
 *
 * @returns {SpatialConnector[]}
 */
function collectConnectors(roomNumber, roomDoors, room) {
    if (Array.isArray(roomDoors) && roomDoors.length && roomNumber !== undefined) {
        /** @type {SpatialConnector[]} */
        let fromDoors = [];

        roomDoors.forEach((door) => {
            let connection = door.connect?.[roomNumber];

            if (!connection) {
                return;
            }

            fromDoors.push({
                direction: connection.direction,
                type     : door.type,
                locked   : Boolean(door.locked),
                ...(door.rectangle && { rectangle: door.rectangle }),
            });
        });

        return fromDoors;
    }

    let listed = room.doorways || room.exits || [];

    return listed.map((entry) => ({
        direction: String(entry.direction || ''),
        type     : String(entry.type || ''),
        locked   : Boolean(entry.locked),
        ...(entry.position && { rectangle: entry.position }),
        ...(entry.rectangle && { rectangle: entry.rectangle }),
    })).filter((entry) => entry.direction && entry.type);
}

/**
 * @param {Rectangle} roomRect
 * @param {Rectangle} doorRect
 * @param {string} direction
 *
 * @returns {string}
 */
function positionOnWall(roomRect, doorRect, direction) {
    let alongAxis = direction === 'north' || direction === 'south' ? 'x' : 'y';
    let spanAxis  = alongAxis === 'x' ? 'width' : 'height';
    let roomSpan  = Math.max(1, roomRect[spanAxis] - (doorRect[spanAxis] || 1));
    let ratio     = (doorRect[alongAxis] - roomRect[alongAxis]) / roomSpan;

    let alongLabel = alongAxis === 'x'
        ? (ratio < 1 / 3 ? 'west' : ratio > 2 / 3 ? 'east' : 'center')
        : (ratio < 1 / 3 ? 'north' : ratio > 2 / 3 ? 'south' : 'center');

    return `${direction}-${alongLabel}`;
}

/**
 * @param {SpatialConnector[]} visible
 *
 * @returns {SpatialViewpoint | undefined}
 */
function chooseViewpoint(visible) {
    if (!visible.length) {
        return;
    }

    let preferred = visible.find((entry) => entry.direction === 'south') || visible[0];
    let from = preferred.direction;
    let looking = oppositeWall[from] || from;

    return {
        from,
        looking,
        description: `View from the ${from} end looking ${looking}.`,
    };
}

/**
 * @param {{ itemSet?: { items?: (Item | Container)[], containers?: (Item | Container)[] }, items?: { items?: (Item | Container)[], containers?: (Item | Container)[] } }} room
 *
 * @returns {SpatialFeature[]}
 */
function dressingFromContents(room) {
    let itemSet = room.itemSet || room.items;
    let entries = [
        ...(itemSet?.containers ?? []),
        ...(itemSet?.items ?? []),
    ];

    return entries
        .filter((item) => largeItemSizes.has(item.size))
        .map((item) => ({
            type      : item.name,
            size      : item.size,
            prominence: /** @type {const} */ ('minor'),
        }));
}

// -- Public Functions ---------------------------------------------------------

/**
 * Builds the per-room spatial model used by both map export and scene prompts.
 * Geometry comes from the same room size, doors, and pillar threshold as the
 * battlemap — not from adventure prose.
 *
 * @param {{
 *   roomNumber?: number,
 *   size?: number[],
 *   rectangle?: Rectangle,
 *   doorways?: object[],
 *   exits?: object[],
 *   itemSet?: object,
 *   items?: object,
 * }} room
 * @param {Door[]} [roomDoors]
 * @param {number} [feetPerCell]
 *
 * @returns {SpatialFacts}
 */
export function buildSpatialFacts(room, roomDoors, feetPerCell = cellFeet) {
    let roomNumber = typeof room.roomNumber === 'number' ? room.roomNumber : 0;
    let size = getRoomSize(room);
    let connectors = collectConnectors(roomNumber, roomDoors, room);

    /** @type {SpatialExit[]} */
    let exits = [];
    /** @type {SpatialExit[]} */
    let hiddenExits = [];
    /** @type {SpatialFeature[]} */
    let floorFeatures = [];
    /** @type {SpatialConnector[]} */
    let visibleConnectors = [];

    connectors.forEach((connector) => {
        let { direction, type, locked } = connector;

        if (hiddenConnectorTypes.has(type)) {
            hiddenExits.push({ wall: direction, type });
            return;
        }

        visibleConnectors.push(connector);

        /** @type {SpatialExit} */
        let exit = {
            wall: direction,
            type: visibleExitType(type),
            ...(locked && { locked: true }),
        };

        exits.push(exit);

        if (type === 'hole') {
            /** @type {SpatialFeature} */
            let hole = {
                type      : 'hole',
                shape     : 'circular',
                wall      : direction,
                prominence: 'major',
            };

            if (room.rectangle && connector.rectangle) {
                hole.position = positionOnWall(room.rectangle, connector.rectangle, direction);
            } else {
                hole.position = direction;
            }

            floorFeatures.push(hole);
        }
    });

    /** @type {SpatialFeature[]} */
    let obstacles = [];

    if (size && size[0] >= pillarGridThreshold && size[1] >= pillarGridThreshold) {
        obstacles.push({
            type      : 'pillars',
            count     : 4,
            prominence: 'major',
        });
    }

    /** @type {SpatialFacts} */
    let facts = {
        roomNumber,
        exits,
        floorFeatures,
        wallFeatures: [],
        obstacles,
        dressing    : dressingFromContents(room),
        hiddenExits,
    };

    if (size) {
        facts.dimensions = {
            widthFt : size[0] * feetPerCell,
            lengthFt: size[1] * feetPerCell,
        };
        facts.shape = 'rectangular';
    }

    let viewpoint = chooseViewpoint(visibleConnectors);

    if (viewpoint) {
        facts.viewpoint = viewpoint;
    }

    return facts;
}

/**
 * Major features that a first-person scene prompt must mention.
 *
 * @param {SpatialFacts} spatialFacts
 *
 * @returns {{ type: string, tokens: string[] }[]}
 */
export function majorFeatures(spatialFacts) {
    /** @type {Map<string, string[]>} */
    let byType = new Map();

    let candidates = [
        ...(spatialFacts.floorFeatures ?? []),
        ...(spatialFacts.wallFeatures ?? []),
        ...(spatialFacts.obstacles ?? []),
        ...(spatialFacts.exits ?? []).map((exit) => ({
            type      : exit.type === 'hole' ? 'hole' : '',
            prominence: exit.type === 'hole' ? /** @type {const} */ ('major') : /** @type {const} */ ('minor'),
        })),
    ];

    candidates.forEach((feature) => {
        if (feature.prominence !== 'major' || !feature.type) {
            return;
        }

        if (!byType.has(feature.type)) {
            byType.set(feature.type, majorFeatureTokens[feature.type] || [ feature.type ]);
        }
    });

    return [ ...byType.entries() ].map(([ type, tokens ]) => ({ type, tokens }));
}

/**
 * Returns major spatial features whose required tokens are absent from a prompt.
 *
 * @param {string} promptText
 * @param {SpatialFacts} spatialFacts
 *
 * @returns {{ type: string, tokens: string[] }[]}
 */
export function missingMajorFeatures(promptText, spatialFacts) {
    let haystack = String(promptText || '').toLowerCase();

    return majorFeatures(spatialFacts).filter(({ tokens }) => {
        return !tokens.some((token) => haystack.includes(token.toLowerCase()));
    });
}

export {
    hiddenConnectorTypes as testHiddenConnectorTypes,
    majorFeatureTokens   as testMajorFeatureTokens,
};
