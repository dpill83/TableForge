// @ts-check

/** @typedef {import('./cast-normalize.js').CastMember} CastMember */
/** @typedef {import('./cast-normalize.js').CastTier} CastTier */

/** @typedef {'minion' | 'standard' | 'lieutenant' | 'boss'} IdentityRank */
/** @typedef {'brute' | 'soldier' | 'skirmisher' | 'artillery' | 'controller' | 'lurker' | 'leader' | ''} CombatRole */

/**
 * @typedef {object} CastIdentityV1
 * @prop {'cast-identity/v1'} schema
 * @prop {string} name
 * @prop {'npc' | 'monster'} kind
 * @prop {IdentityRank} rank
 * @prop {string} role
 * @prop {CombatRole} combatRole
 * @prop {string} look
 * @prop {string} size
 * @prop {string} type
 * @prop {string} tag
 * @prop {string} base
 * @prop {number | string} cr
 * @prop {string} ref
 * @prop {Record<string, unknown>} fixed
 * @prop {string} fixedText
 * @prop {string[]} flags
 */

const SIZES = [ 'tiny', 'small', 'medium', 'large', 'huge', 'gargantuan' ];

const TYPES = [
    'aberration', 'beast', 'celestial', 'construct', 'dragon', 'elemental',
    'fey', 'fiend', 'giant', 'humanoid', 'monstrosity', 'ooze', 'plant', 'undead',
];

const TAG_PATTERNS = [
    [ /\bgoblins?\b/i, 'goblin' ],
    [ /\bhumans?\b/i, 'human' ],
    [ /\belves\b|\belf\b/i, 'elf' ],
    [ /\bdwarves\b|\bdwarf\b/i, 'dwarf' ],
    [ /\borcs?\b/i, 'orc' ],
    [ /\bhobgoblins?\b/i, 'hobgoblin' ],
    [ /\bbugbears?\b/i, 'bugbear' ],
    [ /\bgnomes?\b/i, 'gnome' ],
    [ /\bhalflings?\b/i, 'halfling' ],
    [ /\btieflings?\b/i, 'tiefling' ],
    [ /\bdragonborn\b/i, 'dragonborn' ],
];

/**
 * True when the cast member has enough combat identity for Statblock Forge.
 *
 * @param {CastMember} member
 *
 * @returns {boolean}
 */
export function shouldShowStatblockPrompt(member) {
    const combat = member.combat;

    if (!combat) {
        return false;
    }

    if (combat.fullStatBlock || combat.statBlockRef) {
        return true;
    }

    const summary = (combat.summary || '').trim();

    if (!summary) {
        return false;
    }

    return !/^non[- ]?combat\b/i.test(summary);
}

/**
 * Single-line cast-identity/v1 JSON for Statblock Forge (AI starter or Forge load).
 *
 * @param {CastMember} member
 *
 * @returns {string}
 */
export function buildStatblockPrompt(member) {
    return JSON.stringify(buildCastIdentity(member));
}

/**
 * @param {CastMember} member
 *
 * @returns {CastIdentityV1}
 */
export function buildCastIdentity(member) {
    const summary = (member.combat?.summary || '').trim();
    const look = (member.look || '').trim();
    const corpus = `${look}\n${summary}`;
    const cr = parseCr(summary);
    const rank = mapRank(member, cr);
    const size = parseEnum(corpus, SIZES);
    const tag = parseTag(corpus);
    const type = parseType(corpus, tag, summary);
    const base = parseBase(summary);
    const ref = (member.combat?.statBlockRef || '').trim() || 'none';

    return {
        schema: 'cast-identity/v1',
        name: member.name,
        kind: member.kind,
        rank,
        role: (member.role || '').trim(),
        combatRole: '',
        look,
        size,
        type,
        tag,
        base,
        cr: cr === undefined ? '' : cr,
        ref,
        fixed: {},
        fixedText: summary,
        flags: buildFlags(member, rank, type),
    };
}

/**
 * @param {CastMember} member
 * @param {number | undefined} cr
 *
 * @returns {IdentityRank}
 */
function mapRank(member, cr) {
    if (member.kind === 'monster') {
        if (cr !== undefined && cr <= 1) {
            return 'minion';
        }

        return 'standard';
    }

    if (member.tier === 'villain') {
        return 'boss';
    }

    if (member.tier === 'lieutenant') {
        return 'lieutenant';
    }

    return 'standard';
}

/**
 * @param {string} summary
 *
 * @returns {number | undefined}
 */
function parseCr(summary) {
    const match = summary.match(/\bCR\s*([0-9]+(?:\/[0-9]+)?(?:\.[0-9]+)?)\b/i);

    if (!match) {
        return undefined;
    }

    const raw = match[1];

    if (raw.includes('/')) {
        const [ num, den ] = raw.split('/').map(Number);

        if (Number.isFinite(num) && Number.isFinite(den) && den !== 0) {
            return num / den;
        }

        return undefined;
    }

    const value = Number(raw);

    return Number.isFinite(value) ? value : undefined;
}

/**
 * @param {string} summary
 *
 * @returns {string}
 */
function parseBase(summary) {
    if (!summary) {
        return 'custom';
    }

    if (/\bcustom\b/i.test(summary) && /\bno base\b/i.test(summary)) {
        return 'custom';
    }

    const reskin = summary.match(/\breskin of\s+([^;(]+?)(?:\s*\(|\s*;|,|\s*$)/i);

    if (reskin) {
        return reskin[1].trim().toLowerCase();
    }

    return 'custom';
}

/**
 * @param {string} text
 * @param {string[]} values
 *
 * @returns {string}
 */
function parseEnum(text, values) {
    const lower = text.toLowerCase();

    for (const value of values) {
        if (new RegExp(`\\b${value}\\b`, 'i').test(lower)) {
            return value;
        }
    }

    return '';
}

/**
 * @param {string} text
 *
 * @returns {string}
 */
function parseTag(text) {
    for (const [ pattern, tag ] of TAG_PATTERNS) {
        if (pattern.test(text)) {
            return tag;
        }
    }

    return '';
}

/**
 * @param {string} corpus
 * @param {string} tag
 * @param {string} summary
 *
 * @returns {string}
 */
function parseType(corpus, tag, summary) {
    const fromText = parseEnum(corpus, TYPES);

    if (fromText) {
        return fromText;
    }

    const humanoidTags = new Set([
        'goblin', 'human', 'elf', 'dwarf', 'orc', 'hobgoblin', 'bugbear',
        'gnome', 'halfling', 'tiefling', 'dragonborn',
    ]);

    if (humanoidTags.has(tag)) {
        return 'humanoid';
    }

    if (/\b(death knight|wight|zombie|skeleton|vampire|ghoul|specter|ghost|lich)\b/i.test(summary)) {
        return 'undead';
    }

    return '';
}

/**
 * @param {CastMember} member
 * @param {IdentityRank} rank
 * @param {string} type
 *
 * @returns {string[]}
 */
function buildFlags(member, rank, type) {
    /** @type {string[]} */
    const flags = [];

    if (member.kind === 'npc') {
        flags.push('named');
    }

    if (rank !== 'boss') {
        flags.push('no-legendary');
    }

    if (type === 'undead' || type === 'construct' || type === 'fiend') {
        flags.push(type);
    }

    return flags;
}
