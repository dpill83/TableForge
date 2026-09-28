// @ts-check

import { copyToClipboard, flashCopied } from '../utility/clipboard.js';
import { escapeHTML } from '../utility/escape.js';
import { normalizeCharacter } from './cast-normalize.js';
import {
    buildStatblockPrompt,
    shouldShowStatblockPrompt,
} from './cast-statblock-prompt.js';
import { wireJsonFileLoader } from './json-file-loader.js';

/** @typedef {import('./cast-normalize.js').CastTier} CastTier */
/** @typedef {import('./cast-normalize.js').CastCombat} CastCombat */
/** @typedef {import('./cast-normalize.js').CastMember} CastMember */

/** @typedef {{ adventureName?: string, style?: string, cast: CastMember[] }} CastData */

const TIER_ORDER = /** @type {Record<CastTier, number>} */ ({
    villain: 0,
    lieutenant: 1,
    minor: 2,
    monster: 3,
});

const $ = (id) => document.getElementById(id);

/** @type {CastData | null} */
let data = null;
/** @type {Record<number, boolean>} */
const revealed = {};
/** @type {Record<number, boolean>} */
const blockOpen = {};

const dom = {
    loader: /** @type {HTMLElement} */ ($('loader')),
    styleBar: /** @type {HTMLElement} */ ($('styleBar')),
    styleVal: /** @type {HTMLElement} */ ($('styleVal')),
    copyMode: /** @type {HTMLElement} */ ($('copyMode')),
    castHost: /** @type {HTMLElement} */ ($('cast')),
    styleToggle: /** @type {HTMLInputElement} */ ($('styleToggle')),
    foot: /** @type {HTMLElement} */ ($('foot')),
};

wireJsonFileLoader({
    loader: dom.loader,
    pickBtn: /** @type {HTMLElement} */ ($('pickBtn')),
    pasteBtn: /** @type {HTMLElement} */ ($('pasteBtn')),
    fileInput: /** @type {HTMLInputElement} */ ($('fileInput')),
    pasteArea: /** @type {HTMLTextAreaElement} */ ($('pasteArea')),
}, loadCast);

const cartridge = new URLSearchParams(window.location.search);
const saveId = cartridge.get('saveId');
const playerId = cartridge.get('playerId');
if (saveId && playerId) {
    dom.loader.replaceChildren(document.createTextNode('Loading cast from the mounted cartridge…'));
    fetch(`/api/saves/${encodeURIComponent(saveId)}/cast?playerId=${encodeURIComponent(playerId)}&pilot=true`)
        .then(async (response) => {
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
            if (result.text === null) throw new Error('This cartridge has no cast.json bound to the save.');
            loadCast(result.text);
        })
        .catch((error) => {
            dom.loader.replaceChildren(document.createTextNode(error.message || 'Unable to load cast.json from the cartridge.'));
        });
}

dom.styleToggle.addEventListener('change', () => {
    $('copyModeLabel').textContent = dom.styleToggle.checked
        ? 'Copy includes the art-style line'
        : 'Copy is the prompt only';
});

/**
 * @param {string} text
 *
 * @returns {CastData | null}
 */
function parseCastFile(text) {
    let parsed;

    try {
        parsed = JSON.parse(text);
    } catch {
        alert("That doesn't look like valid JSON. Check the file and try again.");
        return null;
    }

    const cast = parsed.cast ?? parsed.characters ?? parsed.npcs;

    if (!Array.isArray(cast)) {
        alert('This JSON has no "cast" array. Make sure it\'s a cast file from Stage 2.');
        return null;
    }

    return {
        .../** @type {CastData} */ (parsed),
        cast: cast.map(normalizeCharacter),
    };
}

/** @param {string} text */
function loadCast(text) {
    const parsed = parseCastFile(text);

    if (!parsed) {
        return;
    }

    data = parsed;

    for (const key of Object.keys(revealed)) {
        delete revealed[+key];
    }

    for (const key of Object.keys(blockOpen)) {
        delete blockOpen[+key];
    }

    render();
}

function render() {
    if (!data) {
        return;
    }

    const title = data.adventureName || 'Untitled adventure';
    const people = data.cast
        .map((member, index) => ({ member, index }))
        .filter(({ member }) => member.kind !== 'monster')
        .sort((a, b) => (TIER_ORDER[a.member.tier] ?? 3) - (TIER_ORDER[b.member.tier] ?? 3));
    const monsters = data.cast
        .map((member, index) => ({ member, index }))
        .filter(({ member }) => member.kind === 'monster')
        .sort((a, b) => a.member.name.localeCompare(b.member.name));

    $('advTitle').textContent = title;
    $('advLede').textContent = monsters.length
        ? 'People and monsters below. Prep every token from this list. The villain is sealed until you reveal it — safe to keep open during prep.'
        : 'Every named character below. The villain is sealed until you reveal it — safe to keep open during prep.';
    dom.loader.style.display = 'none';

    if (data.style) {
        dom.styleVal.textContent = data.style;
        dom.styleBar.classList.add('show');
    }

    dom.copyMode.classList.add('show');
    dom.castHost.replaceChildren();

    if (people.length) {
        dom.castHost.appendChild(buildSectionHeading('People'));

        for (const { member, index } of people) {
            dom.castHost.appendChild(buildCharacterCard(member, index));
        }
    }

    if (monsters.length) {
        dom.castHost.appendChild(buildSectionHeading('Monsters'));

        for (const { member, index } of monsters) {
            dom.castHost.appendChild(buildCharacterCard(member, index));
        }
    }

    const peopleCount = people.length;
    const monsterCount = monsters.length;
    const parts = [];

    if (peopleCount) {
        parts.push(`${peopleCount} named character${peopleCount === 1 ? '' : 's'}`);
    }

    if (monsterCount) {
        parts.push(`${monsterCount} monster${monsterCount === 1 ? '' : 's'}`);
    }

    dom.foot.textContent = `${title} · ${parts.join(' · ') || 'empty cast'}`;
}

/** @param {string} label */
function buildSectionHeading(label) {
    const heading = document.createElement('h2');
    heading.className = 'cast-section';
    heading.textContent = label;
    return heading;
}

function styleLine() {
    return dom.styleToggle.checked && data?.style ? `${data.style}\n\n` : '';
}

/**
 * @param {CastMember} member
 * @param {number} index
 *
 * @returns {HTMLElement}
 */
function buildCharacterCard(member, index) {
    const card = document.createElement('div');
    const isVillain = member.isVillain && member.kind !== 'monster';

    card.className = 'char'
        + (isVillain ? ' villain' : '')
        + (member.kind === 'monster' ? ' monster' : '')
        + (isVillain && !revealed[index] ? ' sealed' : '');

    if (isVillain) {
        card.appendChild(buildVillainSeal(member, index, card));
    }

    card.appendChild(buildCharacterBody(member, index, card));

    return card;
}

/**
 * @param {CastMember} member
 * @param {number} index
 * @param {HTMLElement} card
 */
function refreshCharacterCard(member, index, card) {
    card.replaceWith(buildCharacterCard(member, index));
}

/**
 * @param {CastMember} member
 * @param {number} index
 * @param {HTMLElement} card
 *
 * @returns {HTMLElement}
 */
function buildVillainSeal(member, index, card) {
    const seal = document.createElement('div');
    seal.className = 'seal';
    seal.innerHTML =
        '<div class="seal-icon">✦</div>' +
        '<div class="seal-text">' +
            '<div class="slabel">Villain — sealed</div>' +
            `<div class="shint">${escapeHTML(member.name)}</div>` +
            '<div class="ssub">Tap to reveal — hides the BBEG during prep</div>' +
        '</div>';

    seal.addEventListener('click', () => {
        revealed[index] = true;
        refreshCharacterCard(member, index, card);
    });

    return seal;
}

/**
 * @param {CastMember} member
 * @param {number} index
 * @param {HTMLElement} card
 *
 * @returns {HTMLElement}
 */
function buildCharacterBody(member, index, card) {
    const body = document.createElement('div');
    body.className = 'body';

    const badgeLabel = member.kind === 'monster' ? 'monster' : member.tier;
    const badgeClass = member.kind === 'monster' ? 'monster' : member.tier;

    const head = document.createElement('div');
    head.className = 'char-head';
    head.innerHTML =
        `<span class="cname">${escapeHTML(member.name)}</span>` +
        `<span class="tier-badge ${escapeHTML(badgeClass)}">${escapeHTML(badgeLabel)}</span>`;

    if (member.isVillain && member.kind !== 'monster') {
        const reseal = document.createElement('span');
        reseal.className = 'reseal';
        reseal.textContent = 'Seal';
        reseal.addEventListener('click', () => {
            revealed[index] = false;
            blockOpen[index] = false;
            refreshCharacterCard(member, index, card);
        });
        head.appendChild(reseal);
    }

    body.appendChild(head);

    if (member.role) {
        const role = document.createElement('p');
        role.className = 'role';
        role.textContent = member.role;
        body.appendChild(role);
    }

    if (member.look) {
        const look = document.createElement('div');
        look.className = 'look';
        look.textContent = member.look;
        body.appendChild(look);
    }

    if (member.appearsIn?.length) {
        const appears = document.createElement('p');
        appears.className = 'appears';
        appears.textContent = `Appears in room${member.appearsIn.length === 1 ? '' : 's'} ${member.appearsIn.join(', ')}`;
        body.appendChild(appears);
    }

    const combat = member.combat;

    if (combat?.summary || combat?.statBlockRef || combat?.fullStatBlock) {
        body.appendChild(buildCombatBlock(combat, index));
    }

    if (shouldShowStatblockPrompt(member)) {
        body.appendChild(buildStatblockPromptBlock(member));
    }

    if (member.portraitPrompt) {
        body.appendChild(buildPortraitBlock(member.portraitPrompt, member.kind === 'monster'));
    }

    return body;
}

/**
 * @param {CastCombat} combat
 * @param {number} index
 *
 * @returns {HTMLElement}
 */
function buildCombatBlock(combat, index) {
    const wrap = document.createElement('div');
    wrap.className = 'combat';
    wrap.innerHTML = '<p class="sec-lab combat"><span class="dot"></span>Combat</p>';

    if (combat.summary) {
        const summary = document.createElement('p');
        summary.className = 'combat-summary';
        summary.textContent = combat.summary;
        wrap.appendChild(summary);
    }

    if (combat.statBlockRef) {
        const ref = document.createElement('div');
        ref.className = 'statref';
        ref.textContent = `Full block: ${combat.statBlockRef}`;
        wrap.appendChild(ref);
    }

    if (combat.fullStatBlock) {
        const toggle = document.createElement('span');
        toggle.className = 'full-toggle';
        toggle.textContent = blockOpen[index]
            ? '▼ Hide full stat block'
            : '▶ Show full stat block';

        const blockDiv = document.createElement('div');
        blockDiv.className = 'full-block';
        blockDiv.textContent = combat.fullStatBlock;
        blockDiv.style.display = blockOpen[index] ? 'block' : 'none';

        toggle.addEventListener('click', () => {
            blockOpen[index] = !blockOpen[index];
            blockDiv.style.display = blockOpen[index] ? 'block' : 'none';
            toggle.textContent = blockOpen[index]
                ? '▼ Hide full stat block'
                : '▶ Show full stat block';
        });

        wrap.appendChild(toggle);
        wrap.appendChild(blockDiv);
    }

    return wrap;
}

/**
 * @param {CastMember} member
 *
 * @returns {HTMLElement}
 */
function buildStatblockPromptBlock(member) {
    const wrap = document.createElement('div');
    wrap.className = 'statblock-prompt';
    wrap.innerHTML = '<p class="sec-lab statblock"><span class="dot"></span>Statblock Forge identity</p>';

    const promptText = buildStatblockPrompt(member);

    const prompt = document.createElement('div');
    prompt.className = 'prompt';
    prompt.textContent = promptText;
    wrap.appendChild(prompt);

    const actions = document.createElement('div');
    actions.className = 'prompt-actions';

    const copyPrompt = document.createElement('button');
    copyPrompt.className = 'copy-btn';
    copyPrompt.type = 'button';
    copyPrompt.textContent = 'Copy for Statblock Forge';
    copyPrompt.addEventListener('click', () => {
        copyToClipboard(promptText)
            .then(() => flashCopied(copyPrompt, true))
            .catch(() => flashCopied(copyPrompt, false));
    });
    actions.appendChild(copyPrompt);

    if (member.combat?.fullStatBlock) {
        const copyBlock = document.createElement('button');
        copyBlock.className = 'copy-btn secondary';
        copyBlock.type = 'button';
        copyBlock.textContent = 'Copy full stat block';
        copyBlock.addEventListener('click', () => {
            copyToClipboard(/** @type {string} */ (member.combat?.fullStatBlock))
                .then(() => flashCopied(copyBlock, true))
                .catch(() => flashCopied(copyBlock, false));
        });
        actions.appendChild(copyBlock);
    }

    wrap.appendChild(actions);

    return wrap;
}

/**
 * @param {string} portraitPrompt
 * @param {boolean} isMonster
 */
function buildPortraitBlock(portraitPrompt, isMonster) {
    const wrap = document.createElement('div');
    wrap.className = 'portrait';
    wrap.innerHTML = isMonster
        ? '<p class="sec-lab portrait"><span class="dot"></span>Token prompt</p>'
        : '<p class="sec-lab portrait"><span class="dot"></span>Portrait prompt</p>';

    const prompt = document.createElement('div');
    prompt.className = 'prompt';
    prompt.textContent = portraitPrompt;
    wrap.appendChild(prompt);

    const actions = document.createElement('div');
    actions.className = 'prompt-actions';

    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = isMonster ? 'Copy token prompt' : 'Copy portrait prompt';
    btn.addEventListener('click', () => {
        copyToClipboard(styleLine() + portraitPrompt)
            .then(() => flashCopied(btn, true))
            .catch(() => flashCopied(btn, false));
    });

    actions.appendChild(btn);
    wrap.appendChild(actions);

    return wrap;
}
