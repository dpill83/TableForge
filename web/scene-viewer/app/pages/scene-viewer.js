// @ts-check

import { copyToClipboard, flashCopied } from '../utility/clipboard.js';
import { escapeHTML } from '../utility/escape.js';
import { parseJsonFile, wireJsonFileLoader } from './json-file-loader.js';

/** @typedef {{ roomNumber: number, name?: string, reveal1?: { prompt?: string }, reveal2?: { prompt?: string, trigger?: string } }} Scene */
/** @typedef {{ adventureName?: string, style?: string, scenes: Scene[] }} ScenesData */

/**
 * Accepts Stage 2 scenes JSON and looser author output (`room`, string reveals,
 * `reveal2.description`).
 *
 * @param {unknown} raw
 *
 * @returns {Scene}
 */
function normalizeScene(raw) {
    const scene = /** @type {Record<string, unknown>} */ (raw);
    const roomNumber = /** @type {number | undefined} */ (scene.roomNumber ?? scene.room);
    const name = typeof scene.name === 'string' ? scene.name : undefined;
    const reveal1 = normalizeReveal(scene.reveal1);
    const reveal2 = normalizeReveal(scene.reveal2);

    return {
        roomNumber: typeof roomNumber === 'number' ? roomNumber : 0,
        ...(name ? { name } : {}),
        ...(reveal1 ? { reveal1 } : {}),
        ...(reveal2 ? { reveal2 } : {}),
    };
}

/**
 * @param {unknown} raw
 *
 * @returns {{ prompt?: string, trigger?: string } | undefined}
 */
function normalizeReveal(raw) {
    if (!raw) {
        return undefined;
    }

    if (typeof raw === 'string') {
        return { prompt: raw };
    }

    if (typeof raw !== 'object') {
        return undefined;
    }

    const reveal = /** @type {Record<string, unknown>} */ (raw);
    const prompt = typeof reveal.prompt === 'string'
        ? reveal.prompt
        : typeof reveal.description === 'string'
            ? reveal.description
            : undefined;
    const trigger = typeof reveal.trigger === 'string' ? reveal.trigger : undefined;

    if (!prompt && !trigger) {
        return undefined;
    }

    return { ...(prompt ? { prompt } : {}), ...(trigger ? { trigger } : {}) };
}

/** @param {Scene} scene */
function roomLabel(scene) {
    const num = scene.roomNumber;

    return scene.name ? `Room ${num} — ${scene.name}` : `Room ${num}`;
}

const $ = (id) => document.getElementById(id);

/** @type {ScenesData | null} */
let data = null;
/** @type {Record<number, boolean>} */
const unlocked = {};
/** @type {Record<number, boolean>} */
const rv2open = {};

const dom = {
    loader: /** @type {HTMLElement} */ ($('loader')),
    styleBar: /** @type {HTMLElement} */ ($('styleBar')),
    styleVal: /** @type {HTMLElement} */ ($('styleVal')),
    progress: /** @type {HTMLElement} */ ($('progress')),
    copyMode: /** @type {HTMLElement} */ ($('copyMode')),
    rooms: /** @type {HTMLElement} */ ($('rooms')),
    styleToggle: /** @type {HTMLInputElement} */ ($('styleToggle')),
    foot: /** @type {HTMLElement} */ ($('foot')),
};

wireJsonFileLoader({
    loader: dom.loader,
    pickBtn: /** @type {HTMLElement} */ ($('pickBtn')),
    pasteBtn: /** @type {HTMLElement} */ ($('pasteBtn')),
    fileInput: /** @type {HTMLInputElement} */ ($('fileInput')),
    pasteArea: /** @type {HTMLTextAreaElement} */ ($('pasteArea')),
}, loadScenes);

const cartridge = new URLSearchParams(window.location.search);
const saveId = cartridge.get('saveId');
const playerId = cartridge.get('playerId');
if (saveId && playerId) {
    dom.loader.replaceChildren(document.createTextNode('Loading scenes from the mounted cartridge…'));
    fetch(`/api/saves/${encodeURIComponent(saveId)}/scenes?playerId=${encodeURIComponent(playerId)}&pilot=true`)
        .then(async (response) => {
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
            if (result.text === null) throw new Error('This cartridge has no scenes.json bound to the save.');
            loadScenes(result.text);
        })
        .catch((error) => {
            dom.loader.replaceChildren(document.createTextNode(error.message || 'Unable to load scenes.json from the cartridge.'));
        });
}

dom.styleToggle.addEventListener('change', () => {
    $('copyModeLabel').textContent = dom.styleToggle.checked
        ? 'Copy includes the art-style line'
        : 'Copy is the prompt only';
});

/** @param {string} text */
function loadScenes(text) {
    const parsed = parseJsonFile(text, {
        arrayKey: 'scenes',
        missingMessage: 'This JSON has no "scenes" array. Make sure it\'s a scenes file from Stage 2.',
    });

    if (!parsed) {
        return;
    }

    data = {
        .../** @type {ScenesData} */ (parsed),
        scenes: parsed.scenes.map(normalizeScene),
    };

    for (const key of Object.keys(unlocked)) {
        delete unlocked[+key];
    }

    for (const key of Object.keys(rv2open)) {
        delete rv2open[+key];
    }

    render();
}

function render() {
    if (!data) {
        return;
    }

    const scenes = sortedScenes(data.scenes);
    const title = data.adventureName || 'Untitled adventure';

    $('advTitle').textContent = title;
    $('advLede').textContent = 'Rooms stay sealed until you open them. Open each as the party arrives — surprises inside stay hidden until they spring.';
    dom.loader.style.display = 'none';

    if (data.style) {
        dom.styleVal.textContent = data.style;
        dom.styleBar.classList.add('show');
    }

    dom.copyMode.classList.add('show');
    updateProgress(scenes);

    dom.rooms.replaceChildren();

    for (const scene of scenes) {
        dom.rooms.appendChild(buildRoomCard(scene));
    }

    dom.foot.textContent = `${title} · ${scenes.length} scenes · sealed until opened`;
}

/** @param {Scene[]} scenes */
function sortedScenes(scenes) {
    return scenes.slice().sort((a, b) => (a.roomNumber || 0) - (b.roomNumber || 0));
}

/** @param {Scene[]} scenes */
function updateProgress(scenes) {
    const open = scenes.filter((scene) => unlocked[scene.roomNumber]).length;

    dom.progress.classList.add('show');
    dom.progress.innerHTML = `Rooms opened: <b>${open}</b> / ${scenes.length}`;
}

function styleLine() {
    return dom.styleToggle.checked && data?.style ? `${data.style}\n\n` : '';
}

/** @param {Scene} scene */
function buildRoomCard(scene) {
    const card = document.createElement('div');
    card.className = 'room' + (unlocked[scene.roomNumber] ? ' unlocked' : '');

    card.appendChild(buildSeal(scene, card));
    card.appendChild(buildBody(scene, card));

    return card;
}

/** @param {HTMLElement} card @param {Scene} scene */
function refreshRoom(card, scene) {
    card.replaceWith(buildRoomCard(scene));

    if (data) {
        updateProgress(sortedScenes(data.scenes));
    }
}

/** @param {Scene} scene @param {HTMLElement} card */
function buildSeal(scene, card) {
    const seal = document.createElement('div');
    seal.className = 'seal';
    seal.innerHTML =
        '<div class="seal-icon">✦</div>' +
        '<div class="seal-text">' +
            '<div class="rlabel">Sealed</div>' +
            `<div class="rhint">${escapeHTML(roomLabel(scene))}</div>` +
            '<div class="rsub">Tap to open when the party arrives</div>' +
        '</div>';

    seal.addEventListener('click', () => {
        unlocked[scene.roomNumber] = true;
        refreshRoom(card, scene);
    });

    return seal;
}

/** @param {Scene} scene @param {HTMLElement} card */
function buildBody(scene, card) {
    const body = document.createElement('div');
    body.className = 'body';

    const head = document.createElement('div');
    head.className = 'room-head';
    head.innerHTML = `<span class="room-num">${escapeHTML(roomLabel(scene))}</span>`;

    const relock = document.createElement('span');
    relock.className = 're-lock';
    relock.textContent = 'Seal again';
    relock.addEventListener('click', () => {
        unlocked[scene.roomNumber] = false;
        rv2open[scene.roomNumber] = false;
        refreshRoom(card, scene);
    });
    head.appendChild(relock);
    body.appendChild(head);

    if (scene.reveal1?.prompt) {
        body.appendChild(buildRevealBlock('one', 'Reveal 1 · on entry', scene.reveal1.prompt));
    }

    if (scene.reveal2?.prompt) {
        if (rv2open[scene.roomNumber]) {
            body.appendChild(buildRevealBlock('two', 'Reveal 2 · sprung', scene.reveal2.prompt));
        } else {
            body.appendChild(buildReveal2Seal(scene, card));
        }
    }

    return body;
}

/** @param {Scene} scene @param {HTMLElement} card */
function buildReveal2Seal(scene, card) {
    const seal2 = document.createElement('div');
    seal2.className = 'rv2-seal';
    const trigger = scene.reveal2?.trigger ? escapeHTML(scene.reveal2.trigger) : 'the surprise is revealed';

    seal2.innerHTML =
        '<span class="lock-ico">▲</span>' +
        `<span class="txt"><b>Reveal 2 — hidden.</b> Tap to show <span class="trig">${trigger}</span></span>`;

    seal2.addEventListener('click', () => {
        rv2open[scene.roomNumber] = true;
        refreshRoom(card, scene);
    });

    return seal2;
}

/** @param {'one' | 'two'} kind @param {string} tagText @param {string} promptText */
function buildRevealBlock(kind, tagText, promptText) {
    const wrap = document.createElement('div');
    wrap.className = 'reveal';

    const tag = document.createElement('div');
    tag.className = `rv-tag ${kind}`;
    tag.innerHTML = `<span class="dot"></span>${tagText}`;
    wrap.appendChild(tag);

    const prompt = document.createElement('div');
    prompt.className = 'prompt';
    prompt.textContent = promptText;
    wrap.appendChild(prompt);

    const btn = document.createElement('button');
    btn.className = 'copy-btn' + (kind === 'two' ? ' two' : '');
    btn.textContent = 'Copy prompt';
    btn.addEventListener('click', () => {
        copyToClipboard(styleLine() + promptText)
            .then(() => flashCopied(btn, true))
            .catch(() => flashCopied(btn, false));
    });

    const actions = document.createElement('div');
    actions.className = 'prompt-actions';
    actions.appendChild(btn);
    wrap.appendChild(actions);

    return wrap;
}
