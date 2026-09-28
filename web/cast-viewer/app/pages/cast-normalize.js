// @ts-check

/** @typedef {'npc' | 'monster'} CastKind */
/** @typedef {'villain' | 'lieutenant' | 'minor' | 'monster'} CastTier */

/**
 * @typedef {object} CastCombat
 * @prop {string} [summary]
 * @prop {string} [statBlockRef]
 * @prop {string} [fullStatBlock]
 */

/**
 * @typedef {object} CastMember
 * @prop {string} name
 * @prop {CastKind} kind
 * @prop {string} [role]
 * @prop {CastTier} tier
 * @prop {boolean} isVillain
 * @prop {string} [look]
 * @prop {number[]} [appearsIn]
 * @prop {CastCombat} [combat]
 * @prop {string} [portraitPrompt]
 */

/**
 * Accepts Stage 2 cast JSON and looser author output (flat combat fields,
 * `description`/`portrait` aliases, tier inferred from role).
 *
 * @param {unknown} raw
 *
 * @returns {CastMember}
 */
export function normalizeCharacter(raw) {
    const character = /** @type {Record<string, unknown>} */ (raw);
    const combatRaw = character.combat && typeof character.combat === 'object'
        ? /** @type {Record<string, unknown>} */ (character.combat)
        : {};
    const kind = normalizeKind(character.kind, character.tier, character.role);
    const tier = kind === 'monster'
        ? /** @type {CastTier} */ ('monster')
        : normalizeTier(character.tier, character.role, character.isVillain);
    const name = pickString(character.name, character.characterName) || 'Unnamed';
    const look = pickString(character.look, character.description, character.appearance);
    const portraitPrompt = pickString(
        character.portraitPrompt,
        character.portrait,
        character.portrait_prompt,
        character.tokenPrompt,
        character.token_prompt,
    );
    const combat = normalizeCombat(character, combatRaw);
    const appearsIn = normalizeAppearsIn(character.appearsIn, character.appears_in);

    return {
        name,
        kind,
        ...(pickString(character.role) ? { role: pickString(character.role) } : {}),
        tier,
        isVillain: kind === 'monster'
            ? false
            : character.isVillain === true || tier === 'villain',
        ...(look ? { look } : {}),
        ...(appearsIn.length ? { appearsIn } : {}),
        ...(combat ? { combat } : {}),
        ...(portraitPrompt ? { portraitPrompt } : {}),
    };
}

/**
 * @param {unknown} kind
 * @param {unknown} tier
 * @param {unknown} role
 *
 * @returns {CastKind}
 */
function normalizeKind(kind, tier, role) {
    const kindText = typeof kind === 'string' ? kind.toLowerCase() : '';

    if (kindText === 'monster' || kindText === 'combatant' || kindText === 'creature') {
        return 'monster';
    }

    if (kindText === 'npc' || kindText === 'character' || kindText === 'person') {
        return 'npc';
    }

    const tierText = typeof tier === 'string' ? tier.toLowerCase() : '';

    if (tierText.includes('monster') || tierText === 'combatant') {
        return 'monster';
    }

    const roleText = typeof role === 'string' ? role.toLowerCase() : '';

    if (roleText === 'combatant' || roleText.includes('monster')) {
        return 'monster';
    }

    return 'npc';
}

/**
 * @param {unknown} tier
 * @param {unknown} role
 * @param {unknown} isVillain
 *
 * @returns {CastTier}
 */
function normalizeTier(tier, role, isVillain) {
    if (isVillain === true) {
        return 'villain';
    }

    const tierText = typeof tier === 'string' ? tier.toLowerCase() : '';

    if (tierText.includes('villain') || tierText === 'bbeg') {
        return 'villain';
    }

    if (tierText.includes('lieutenant')) {
        return 'lieutenant';
    }

    if (tierText.includes('minor')) {
        return 'minor';
    }

    const roleText = typeof role === 'string' ? role.toLowerCase() : '';

    if (roleText.includes('villain') || roleText.includes('bbeg')) {
        return 'villain';
    }

    if (roleText.includes('lieutenant')) {
        return 'lieutenant';
    }

    return 'minor';
}

/**
 * @param {unknown} appearsIn
 * @param {unknown} appearsInAlt
 *
 * @returns {number[]}
 */
function normalizeAppearsIn(appearsIn, appearsInAlt) {
    const raw = Array.isArray(appearsIn)
        ? appearsIn
        : Array.isArray(appearsInAlt)
            ? appearsInAlt
            : [];

    /** @type {number[]} */
    const rooms = [];

    for (const value of raw) {
        const num = typeof value === 'number' ? value : Number(value);

        if (Number.isFinite(num) && !rooms.includes(num)) {
            rooms.push(num);
        }
    }

    return rooms.sort((a, b) => a - b);
}

/**
 * @param {Record<string, unknown>} character
 * @param {Record<string, unknown>} combatRaw
 *
 * @returns {CastCombat | undefined}
 */
function normalizeCombat(character, combatRaw) {
    const summary = pickString(
        combatRaw.summary,
        character.combatSummary,
        character.combat_summary,
        character.baseCreature,
        character.base_creature,
    );
    const statBlockRef = pickString(
        combatRaw.statBlockRef,
        character.statBlockRef,
        character.stat_block_ref,
    );
    const fullStatBlock = pickString(
        combatRaw.fullStatBlock,
        combatRaw.statBlock,
        combatRaw.full_stat_block,
        character.fullStatBlock,
        character.statBlock,
        character.full_stat_block,
    );

    if (!summary && !statBlockRef && !fullStatBlock) {
        return undefined;
    }

    return {
        ...(summary ? { summary } : {}),
        ...(statBlockRef ? { statBlockRef } : {}),
        ...(fullStatBlock ? { fullStatBlock } : {}),
    };
}

/**
 * @param {...unknown} values
 *
 * @returns {string | undefined}
 */
function pickString(...values) {
    for (const value of values) {
        if (typeof value === 'string' && value.trim()) {
            return value;
        }
    }

    return undefined;
}
