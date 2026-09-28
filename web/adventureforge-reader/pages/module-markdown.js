// @ts-check

/**
 * @typedef {object} ModuleAreaOverlay
 * @prop {number} roomNumber
 * @prop {string} [name]
 * @prop {string} [beat]
 * @prop {string} [dmNotes]
 * @prop {string} [difficultyDial]
 */

/**
 * @typedef {object} ModuleStatBlock
 * @prop {string} name
 * @prop {string} body
 */

/**
 * @typedef {object} ModuleOverlay
 * @prop {string} [runningNotes]
 * @prop {string} [approach]
 * @prop {string} [dungeonFlow]
 * @prop {string} [villainAndClock]
 * @prop {string} [treasureSummary]
 * @prop {string} [openThread]
 * @prop {Record<number, ModuleAreaOverlay>} areas
 * @prop {ModuleStatBlock[]} statBlocks
 */

/**
 * @typedef {object} ClockStep
 * @prop {number} step
 * @prop {string} effect
 */

/**
 * @param {string} text
 *
 * @returns {Record<string, string>}
 */
function splitTopSections(text) {
    /** @type {Record<string, string>} */
    const sections = {};

    for (const part of text.split(/\n(?=## )/)) {
        const match = part.match(/^## ([^\n]+)\n([\s\S]*)/);

        if (match) {
            sections[match[1].trim()] = match[2].trim();
        }
    }

    return sections;
}

/**
 * @param {string} body
 *
 * @returns {Record<string, string>}
 */
function splitSubsections(body) {
    /** @type {Record<string, string>} */
    const subsections = {};

    for (const part of body.split(/\n(?=### )/)) {
        const match = part.match(/^### ([^\n]+)\n([\s\S]*)/);

        if (match) {
            subsections[match[1].trim()] = match[2].trim();
        }
    }

    return subsections;
}

/**
 * @param {string} text
 *
 * @returns {string}
 */
function extractBlockquote(text) {
    const lines = text.split('\n').filter((line) => line.startsWith('>'));

    if (!lines.length) {
        return text.trim();
    }

    return lines
        .map((line) => line.replace(/^>\s?/, ''))
        .join('\n')
        .trim();
}

/**
 * @param {string} body
 *
 * @returns {ModuleAreaOverlay | null}
 */
function parseAreaSection(body) {
    const beatMatch = body.match(/^\*\*Beat:\*\*\s*(.+)$/m);
    const subsections = splitSubsections(body);

    return {
        dmNotes: subsections['DM Notes']?.trim(),
        difficultyDial: subsections['Difficulty Dial']?.trim(),
        ...(beatMatch ? { beat: beatMatch[1].trim() } : {}),
    };
}

/**
 * @param {string} text
 *
 * @returns {ModuleOverlay}
 */
export function parseModuleMarkdown(text) {
    const sections = splitTopSections(text);
    /** @type {Record<number, ModuleAreaOverlay>} */
    const areas = {};
    /** @type {ModuleStatBlock[]} */
    const statBlocks = [];

    for (const [title, body] of Object.entries(sections)) {
        const areaMatch = title.match(/^Area (\d+):\s*(.*)/);

        if (areaMatch) {
            const roomNumber = parseInt(areaMatch[1], 10);
            const parsed = parseAreaSection(body);

            areas[roomNumber] = {
                roomNumber,
                name: areaMatch[2].trim() || undefined,
                ...parsed,
            };
        }
    }

    const statBody = sections['Stat Blocks'];

    if (statBody) {
        for (const part of statBody.split(/\n(?=### )/)) {
            const match = part.match(/^### ([^\n]+)\n([\s\S]*)/);

            if (match) {
                statBlocks.push({
                    name: match[1].trim(),
                    body: match[2].trim(),
                });
            }
        }
    }

    return {
        runningNotes: sections['Running Notes'],
        approach: sections['Approach & Arrival'],
        dungeonFlow: sections['Dungeon Flow'],
        villainAndClock: sections['Villain and Clock'] || sections['Villain'],
        treasureSummary: sections['Treasure Summary'],
        openThread: sections['Open Thread'],
        areas,
        statBlocks,
    };
}

/**
 * @param {string} clockProse
 *
 * @returns {ClockStep[]}
 */
export function parseClockSteps(clockProse) {
    if (!clockProse || typeof clockProse !== 'string') {
        return [];
    }

    /** @type {ClockStep[]} */
    const steps = [];
    const regex = /(?:At )?Bell (\d+)[,:]?\s*([^]+?)(?=\.\s*(?:At )?Bell \d+|$)/gi;
    let match;

    while ((match = regex.exec(clockProse)) !== null) {
        steps.push({
            step: parseInt(match[1], 10),
            effect: match[2].trim().replace(/\.\s*$/, ''),
        });
    }

    return steps.sort((a, b) => a.step - b.step);
}

/**
 * @param {object} runData
 * @param {ModuleOverlay | null} overlay
 *
 * @returns {object}
 */
export function mergeRunDataWithOverlay(runData, overlay) {
    const rooms = Array.isArray(runData.rooms) ? runData.rooms : [];

    return {
        ...runData,
        overlay,
        rooms: rooms.map((/** @type {Record<string, unknown>} */ room) => {
            const roomNumber = /** @type {number} */ (room.roomNumber);
            const area = overlay?.areas?.[roomNumber];

            return {
                ...room,
                areaName: area?.name,
                dmNotes: area?.dmNotes,
                difficultyDial: area?.difficultyDial,
            };
        }),
        statBlocks: runData.statBlocks?.length
            ? runData.statBlocks
            : (overlay?.statBlocks || []).map((block) => ({
                name: block.name,
                baseCreature: '',
                block: block.body,
                cr: 0,
            })),
    };
}
