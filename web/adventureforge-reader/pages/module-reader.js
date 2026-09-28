// @ts-check

import { copyToClipboard, flashCopied } from '../utility/clipboard.js';
import { escapeHTML } from '../utility/escape.js';
import { parseJsonFile } from './json-file-loader.js';
import {
    mergeRunDataWithOverlay,
    parseClockSteps,
    parseModuleMarkdown,
} from './module-markdown.js';

/** @typedef {ReturnType<typeof mergeRunDataWithOverlay>} AdventureData */

/** @typedef {object} SessionState
 * @prop {number} currentRoom
 * @prop {number} clockStep
 * @prop {number[]} visitedRooms
 */

const SESSION_KEY_PREFIX = 'moduleReaderSession:';
let tableforgeSaveId = '';

const $ = (id) => document.getElementById(id);

/** @type {AdventureData | null} */
let data = null;
/** @type {ReturnType<typeof parseClockSteps>} */
let clockSteps = [];
/** @type {SessionState} */
let session = { currentRoom: 0, clockStep: 0, visitedRooms: [] };
/** @type {string} */
let activeTab = 'prep';
/** @type {boolean} */
let secretsOpen = false;
/** @type {boolean} */
let dmDetailOpen = false;
/** @type {boolean} */
let moduleLoaded = false;
/** @type {boolean} */
let moduleSkipped = false;

const dom = {
    loaders: /** @type {HTMLElement} */ ($('loaders')),
    loaderRunData: /** @type {HTMLElement} */ ($('loaderRunData')),
    loaderModule: /** @type {HTMLElement} */ ($('loaderModule')),
    statusRunData: /** @type {HTMLElement} */ ($('statusRunData')),
    statusModule: /** @type {HTMLElement} */ ($('statusModule')),
    skipModule: /** @type {HTMLButtonElement} */ ($('skipModule')),
    partyStrip: /** @type {HTMLElement} */ ($('partyStrip')),
    sessionBar: /** @type {HTMLElement} */ ($('sessionBar')),
    clockLabel: /** @type {HTMLElement} */ ($('clockLabel')),
    clockEffect: /** @type {HTMLElement} */ ($('clockEffect')),
    viewPrep: /** @type {HTMLElement} */ ($('viewPrep')),
    viewAreas: /** @type {HTMLElement} */ ($('viewAreas')),
    viewStats: /** @type {HTMLElement} */ ($('viewStats')),
    viewRef: /** @type {HTMLElement} */ ($('viewRef')),
};

wireTextLoader({
    loader: dom.loaderRunData,
    pickBtn: /** @type {HTMLElement} */ ($('pickRunData')),
    pasteBtn: /** @type {HTMLElement} */ ($('pasteRunData')),
    fileInput: /** @type {HTMLInputElement} */ ($('fileRunData')),
    pasteArea: /** @type {HTMLTextAreaElement} */ ($('pasteAreaRunData')),
    accept: '.json',
}, loadRunData);

wireTextLoader({
    loader: dom.loaderModule,
    pickBtn: /** @type {HTMLElement} */ ($('pickModule')),
    pasteBtn: /** @type {HTMLElement} */ ($('pasteModule')),
    fileInput: /** @type {HTMLInputElement} */ ($('fileModule')),
    pasteArea: /** @type {HTMLTextAreaElement} */ ($('pasteAreaModule')),
    accept: '.md',
}, loadModule);

for (const tab of document.querySelectorAll('.tab')) {
    tab.addEventListener('click', () => {
        const name = tab.getAttribute('data-tab');

        if (name) {
            setTab(name);
        }
    });
}

/** @type {HTMLElement} */ ($('clockAdvance')).addEventListener('click', advanceClock);
/** @type {HTMLElement} */ ($('sessionReset')).addEventListener('click', resetSession);
dom.skipModule.addEventListener('click', () => {
    moduleSkipped = true;
    updateLoadersVisibility();
});

// TableForge supplies the bound cartridge files to this same-origin reader.
window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin || event.source !== window.parent) return;
    const payload = event.data;
    if (payload?.type !== 'tableforge:load-module-reader') return;
    tableforgeSaveId = String(payload.saveId || '');
    moduleLoaded = false;
    moduleSkipped = false;
    data = null;
    dom.loaderRunData.classList.remove('loaded');
    dom.loaderModule.classList.remove('loaded');
    dom.statusRunData.classList.remove('ok');
    dom.statusModule.classList.remove('ok');
    dom.statusRunData.textContent = 'Drop a .json file here';
    dom.statusModule.textContent = 'Adds DM Notes & dials';
    if (typeof payload.runData === 'string') loadRunData(payload.runData);
    if (typeof payload.module === 'string') loadModule(payload.module);
});

/**
 * @param {object} opts
 * @param {HTMLElement} opts.loader
 * @param {HTMLElement} opts.pickBtn
 * @param {HTMLElement} opts.pasteBtn
 * @param {HTMLInputElement} opts.fileInput
 * @param {HTMLTextAreaElement} opts.pasteArea
 * @param {string} opts.accept
 * @param {(text: string) => void} onText
 */
function wireTextLoader(opts, onText) {
    const { loader, pickBtn, pasteBtn, fileInput, pasteArea } = opts;

    pickBtn.addEventListener('click', () => {
        if (pasteArea.classList.contains('show') && pasteArea.value.trim()) {
            onText(pasteArea.value);
        } else {
            fileInput.click();
        }
    });

    pasteBtn.addEventListener('click', () => {
        pasteArea.classList.toggle('show');
        pickBtn.textContent = pasteArea.classList.contains('show') ? 'Load pasted' : 'Choose file';

        if (pasteArea.classList.contains('show')) {
            pasteArea.focus();
        }
    });

    fileInput.addEventListener('change', (e) => {
        const file = /** @type {HTMLInputElement} */ (e.target).files?.[0];

        if (file) {
            readFileText(file).then(onText);
        }
    });

    for (const ev of ['dragenter', 'dragover']) {
        loader.addEventListener(ev, (e) => {
            e.preventDefault();
            loader.classList.add('drag');
        });
    }

    for (const ev of ['dragleave', 'drop']) {
        loader.addEventListener(ev, (e) => {
            e.preventDefault();
            loader.classList.remove('drag');
        });
    }

    loader.addEventListener('drop', (e) => {
        const file = e.dataTransfer?.files?.[0];

        if (!file) {
            return;
        }

        const name = file.name.toLowerCase();

        if (opts.accept === '.json' && !name.endsWith('.json')) {
            alert('Please drop a .json run-data file here.');
            return;
        }

        if (opts.accept === '.md' && !name.endsWith('.md')) {
            alert('Please drop a .md module file here.');
            return;
        }

        readFileText(file).then(onText);
    });
}

/**
 * @param {File} file
 *
 * @returns {Promise<string>}
 */
function readFileText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(file);
    });
}

/** @param {string} adventureName */
function sessionKey(adventureName) {
    return SESSION_KEY_PREFIX + (tableforgeSaveId ? tableforgeSaveId + ':' : '') + adventureName;
}

/** @param {string} adventureName */
function loadSession(adventureName) {
    try {
        const raw = localStorage.getItem(sessionKey(adventureName));

        if (!raw) {
            return { currentRoom: 0, clockStep: 0, visitedRooms: [] };
        }

        const parsed = JSON.parse(raw);

        return {
            currentRoom: typeof parsed.currentRoom === 'number' ? parsed.currentRoom : 0,
            clockStep: typeof parsed.clockStep === 'number' ? parsed.clockStep : 0,
            visitedRooms: Array.isArray(parsed.visitedRooms) ? parsed.visitedRooms : [],
        };
    } catch {
        return { currentRoom: 0, clockStep: 0, visitedRooms: [] };
    }
}

function saveSession() {
    if (!data?.adventureName) {
        return;
    }

    localStorage.setItem(sessionKey(data.adventureName), JSON.stringify(session));
}

/** @param {string} text */
function loadRunData(text) {
    const parsed = parseJsonFile(text, {
        arrayKey: 'rooms',
        missingMessage: 'This JSON has no "rooms" array. Make sure it\'s a run-data file from Stage 2.',
    });

    if (!parsed) {
        return;
    }

    const overlay = data?.overlay || null;

    data = mergeRunDataWithOverlay(parsed, overlay);
    clockSteps = parseClockSteps(/** @type {string} */ (data.clock || ''));

    const adventureName = data.adventureName || 'Untitled adventure';

    session = loadSession(adventureName);

    if (!session.currentRoom && sortedRooms().length) {
        session.currentRoom = sortedRooms()[0].roomNumber;
    }

    dom.loaderRunData.classList.add('loaded');
    dom.statusRunData.textContent = 'Loaded ✓';
    dom.statusRunData.classList.add('ok');

    render();
}

/** @param {string} text */
function loadModule(text) {
    const overlay = parseModuleMarkdown(text);

    if (data) {
        data = mergeRunDataWithOverlay(data, overlay);
    } else {
        data = mergeRunDataWithOverlay({ rooms: [] }, overlay);
    }

    moduleLoaded = true;
    moduleSkipped = false;

    dom.loaderModule.classList.add('loaded');
    dom.statusModule.textContent = 'Loaded ✓';
    dom.statusModule.classList.add('ok');

    if (data.rooms?.length) {
        render();
    } else {
        updateLoadersVisibility();
    }
}

function updateLoadersVisibility() {
    const hasRooms = Boolean(data?.rooms?.length);

    if (!hasRooms) {
        dom.loaders.style.display = '';
        dom.loaders.classList.remove('session-ready');
        dom.skipModule.hidden = true;
        return;
    }

    if (moduleLoaded || moduleSkipped) {
        dom.loaders.style.display = 'none';
        dom.loaders.classList.remove('session-ready');
        dom.skipModule.hidden = true;
        return;
    }

    // Session is live; keep the optional module drop zone available.
    dom.loaders.style.display = '';
    dom.loaders.classList.add('session-ready');
    dom.skipModule.hidden = false;
    dom.statusModule.textContent = 'Still optional — add now for DM Notes & dials';
}

function sortedRooms() {
    if (!data?.rooms) {
        return [];
    }

    return data.rooms.slice().sort((/** @type {{ roomNumber: number }} */ a, /** @type {{ roomNumber: number }} */ b) => a.roomNumber - b.roomNumber);
}

function render() {
    if (!data?.rooms?.length) {
        return;
    }

    const title = data.adventureName || 'Untitled adventure';

    $('advTitle').textContent = title;
    $('advLede').textContent = data.theme || 'Session reference for the human DM.';
    updateLoadersVisibility();
    dom.sessionBar.classList.add('show');
    dom.partyStrip.classList.add('show');

    renderPartyStrip();
    updateClockDisplay();
    renderPrep();
    renderAreas();
    renderStats();
    renderRef();
    setTab(activeTab);
}

function renderPartyStrip() {
    dom.partyStrip.replaceChildren();

    const party = Array.isArray(data?.party) ? data.party : [];

    for (const pc of party) {
        const chip = document.createElement('span');
        chip.className = 'pc-chip';
        chip.innerHTML =
            `<b>${escapeHTML(pc.name || '?')}</b> ` +
            `AC ${pc.ac ?? '?'} · HP ${pc.hp ?? '?'} · PP ${pc.passivePerception ?? '?'}`;
        dom.partyStrip.appendChild(chip);
    }
}

function updateClockDisplay() {
    const maxStep = clockSteps.length ? clockSteps[clockSteps.length - 1].step : 4;
    const step = session.clockStep;
    const label = step === 0 ? 'Red Bell: 0 (not started)' : `Red Bell: ${step}`;

    dom.clockLabel.textContent = label;

    if (step === 0) {
        dom.clockEffect.textContent = clockSteps[0]
            ? `Next: ${clockSteps[0].effect}`
            : (data?.clock || '').slice(0, 120);
    } else {
        const current = clockSteps.find((s) => s.step === step);

        dom.clockEffect.textContent = current?.effect || '';
    }

    const advanceBtn = /** @type {HTMLButtonElement} */ ($('clockAdvance'));

    advanceBtn.disabled = step >= maxStep;

    if (step >= maxStep) {
        advanceBtn.textContent = 'Max bell';
    } else {
        advanceBtn.textContent = '+1 Bell';
    }
}

function advanceClock() {
    const maxStep = clockSteps.length ? clockSteps[clockSteps.length - 1].step : 4;

    if (session.clockStep >= maxStep) {
        return;
    }

    if (session.clockStep === maxStep - 1) {
        const ok = confirm(`Advance to Bell ${maxStep}? This is the final clock step.`);

        if (!ok) {
            return;
        }
    }

    session.clockStep += 1;
    saveSession();
    updateClockDisplay();
}

function resetSession() {
    if (!confirm('Reset session progress? Clock and visited rooms will clear.')) {
        return;
    }

    const rooms = sortedRooms();

    session = {
        currentRoom: rooms[0]?.roomNumber || 0,
        clockStep: 0,
        visitedRooms: [],
    };

    saveSession();
    secretsOpen = false;
    dmDetailOpen = false;
    render();
}

/** @param {string} tab */
function setTab(tab) {
    activeTab = tab;

    for (const el of document.querySelectorAll('.tab')) {
        el.classList.toggle('active', el.getAttribute('data-tab') === tab);
    }

    dom.viewPrep.classList.toggle('active', tab === 'prep');
    dom.viewAreas.classList.toggle('active', tab === 'areas');
    dom.viewStats.classList.toggle('active', tab === 'stats');
    dom.viewRef.classList.toggle('active', tab === 'ref');
}

/**
 * Strip leading ("2 Goblin") or trailing ("Goblin (2)") counts for stat lookup.
 *
 * @param {string} monsterRef
 *
 * @returns {string}
 */
function monsterStatName(monsterRef) {
    return String(monsterRef || '')
        .trim()
        .replace(/^\d+\s+/, '')
        .replace(/\s*\(\d+\)\s*$/, '')
        .trim();
}

/** @param {string} monsterRef */
function jumpToStat(monsterRef) {
    const name = monsterStatName(monsterRef);

    setTab('stats');

    requestAnimationFrame(() => {
        /** @type {Element | null} */
        let el = name
            ? document.querySelector(`[data-stat-name="${cssEscape(name)}"]`)
            : null;

        if (!el && name) {
            for (const card of document.querySelectorAll('[data-stat-name]')) {
                if (monsterStatName(card.getAttribute('data-stat-name') || '') === name) {
                    el = card;
                    break;
                }
            }
        }

        if (el) {
            const target = el;
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            target.classList.add('highlight');
            setTimeout(() => target.classList.remove('highlight'), 2000);
        }
    });
}

/** @param {string} value */
function cssEscape(value) {
    return value.replace(/"/g, '\\"');
}

function renderPrep() {
    const hook = data?.hook || {};
    const villain = data?.villain || {};
    const overlay = data?.overlay;

    dom.viewPrep.replaceChildren();

    dom.viewPrep.appendChild(buildCard('Player Briefing', hook.playerBriefing, true));

    if (Array.isArray(hook.patronFAQ) && hook.patronFAQ.length) {
        const faqCard = document.createElement('div');
        faqCard.className = 'card';
        faqCard.innerHTML = '<h2>Patron FAQ</h2>';

        for (const item of hook.patronFAQ) {
            const row = document.createElement('div');
            row.className = 'faq-item';
            row.innerHTML =
                `<div class="faq-q">${escapeHTML(item.q || '')}</div>` +
                `<div class="faq-a">${escapeHTML(item.a || '')}</div>`;
            row.querySelector('.faq-q')?.addEventListener('click', () => {
                row.classList.toggle('open');
            });
            faqCard.appendChild(row);
        }

        dom.viewPrep.appendChild(faqCard);
    }

    if (hook.dmSecrets) {
        const secretsCard = document.createElement('div');
        secretsCard.className = 'card';
        secretsCard.innerHTML = '<h2>DM Secrets</h2>';

        const seal = document.createElement('div');
        seal.className = 'secrets-seal';
        seal.textContent = secretsOpen
            ? 'Hide secrets'
            : 'Reveal DM secrets (sealed = AI will not volunteer; you may unseal)';
        seal.addEventListener('click', () => {
            secretsOpen = !secretsOpen;
            renderPrep();
        });
        secretsCard.appendChild(seal);

        const body = document.createElement('div');
        body.className = 'secrets-body' + (secretsOpen ? ' show' : '');
        body.textContent = hook.dmSecrets;
        secretsCard.appendChild(body);

        dom.viewPrep.appendChild(secretsCard);
    }

    if (overlay?.approach) {
        dom.viewPrep.appendChild(buildCard('Approach & Arrival', overlay.approach));
    }

    if (overlay?.runningNotes) {
        dom.viewPrep.appendChild(buildCard('Running Notes', overlay.runningNotes));
    }

    if (villain.name || villain.motive || villain.weakness) {
        const villainCard = document.createElement('div');
        villainCard.className = 'card';
        villainCard.innerHTML = '<h2>Villain</h2>';

        if (villain.name) {
            villainCard.innerHTML += `<p><b>${escapeHTML(villain.name)}</b></p>`;
        }

        const secretBits = [];

        if (villain.motive) {
            secretBits.push(`<p class="kv"><b>Motive:</b> ${escapeHTML(villain.motive)}</p>`);
        }

        if (villain.weakness) {
            secretBits.push(`<p class="kv"><b>Weakness:</b> ${escapeHTML(villain.weakness)}</p>`);
        }

        if (secretBits.length) {
            const seal = document.createElement('div');
            seal.className = 'secrets-seal';
            seal.textContent = secretsOpen
                ? 'Hide motive & weakness'
                : 'Reveal motive & weakness (sealed = AI will not volunteer; you may unseal)';
            seal.addEventListener('click', () => {
                secretsOpen = !secretsOpen;
                renderPrep();
            });
            villainCard.appendChild(seal);

            const body = document.createElement('div');
            body.className = 'secrets-body' + (secretsOpen ? ' show' : '');
            body.innerHTML = secretBits.join('');
            villainCard.appendChild(body);
        }

        dom.viewPrep.appendChild(villainCard);
    }

    if (overlay?.villainAndClock) {
        dom.viewPrep.appendChild(buildCard('Villain & Clock (module)', overlay.villainAndClock));
    }

    if (overlay?.dungeonFlow) {
        dom.viewPrep.appendChild(buildCard('Dungeon Flow', overlay.dungeonFlow));
    }
}

function renderAreas() {
    const rooms = sortedRooms();

    dom.viewAreas.replaceChildren();

    const picker = document.createElement('div');
    picker.className = 'room-picker';

    for (const room of rooms) {
        const btn = document.createElement('button');
        btn.className = 'room-btn';
        btn.textContent = `Area ${room.roomNumber}`;
        btn.classList.toggle('current', room.roomNumber === session.currentRoom);
        btn.classList.toggle('visited', session.visitedRooms.includes(room.roomNumber));
        btn.addEventListener('click', () => selectRoom(room.roomNumber));
        picker.appendChild(btn);
    }

    dom.viewAreas.appendChild(picker);
    dom.viewAreas.appendChild(buildRoomPanel(rooms.find((r) => r.roomNumber === session.currentRoom) || rooms[0]));
}

/** @param {number} roomNumber */
function selectRoom(roomNumber) {
    session.currentRoom = roomNumber;

    if (!session.visitedRooms.includes(roomNumber)) {
        session.visitedRooms.push(roomNumber);
    }

    saveSession();
    renderAreas();
}

/** @param {Record<string, unknown>} room */
function buildRoomPanel(room) {
    const panel = document.createElement('div');
    panel.className = 'card';

    const title = room.areaName
        ? `Area ${room.roomNumber} — ${room.areaName}`
        : `Area ${room.roomNumber}`;

    panel.innerHTML = `<h2>${escapeHTML(title)}</h2>`;

    if (room.beat) {
        const badge = document.createElement('span');
        badge.className = 'beat-badge';
        badge.textContent = String(room.beat);
        panel.appendChild(badge);
    }

    if (room.boxedText) {
        const boxed = document.createElement('div');
        boxed.className = 'boxed';
        boxed.textContent = String(room.boxedText);
        panel.appendChild(boxed);

        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.textContent = 'Copy boxed text';
        copyBtn.addEventListener('click', () => {
            copyToClipboard(String(room.boxedText))
                .then(() => flashCopied(copyBtn, true))
                .catch(() => flashCopied(copyBtn, false));
        });
        panel.appendChild(copyBtn);
    }

    const encounter = /** @type {Record<string, unknown> | null} */ (room.encounter);

    if (encounter && (encounter.monsters?.length || encounter.tactics)) {
        panel.appendChild(tag('Encounter'));
        const encDiv = document.createElement('div');

        if (Array.isArray(encounter.monsters) && encounter.monsters.length) {
            const monsters = encounter.monsters.map((/** @type {string} */ m) => {
                const name = monsterStatName(m);

                return `<span class="monster-link" data-monster="${escapeHTML(name)}">${escapeHTML(m)}</span>`;
            }).join(', ');

            encDiv.innerHTML = `<p class="kv"><b>Creatures:</b> ${monsters}</p>`;
            encDiv.querySelectorAll('.monster-link').forEach((el) => {
                el.addEventListener('click', () => {
                    jumpToStat(el.getAttribute('data-monster') || '');
                });
            });
        } else {
            encDiv.innerHTML = '<p class="kv"><b>Creatures:</b> None</p>';
        }

        if (encounter.tactics) {
            encDiv.innerHTML += `<p class="kv"><b>Tactics:</b> ${escapeHTML(String(encounter.tactics))}</p>`;
        }

        if (encounter.space) {
            encDiv.innerHTML += `<p class="kv"><b>Space:</b> ${escapeHTML(String(encounter.space))}</p>`;
        }

        panel.appendChild(encDiv);
    }

    const trap = /** @type {Record<string, string> | null} */ (room.trap);

    if (trap) {
        panel.appendChild(tag(`Trap: ${trap.name || 'Hazard'}`, 'trap'));
        const trapDiv = document.createElement('div');
        trapDiv.innerHTML =
            (trap.trigger ? `<p class="kv"><b>Trigger:</b> ${escapeHTML(trap.trigger)}</p>` : '') +
            (trap.detect ? `<p class="kv"><b>Detection:</b> ${escapeHTML(trap.detect)}</p>` : '') +
            (trap.effect ? `<p class="kv"><b>Effect:</b> ${escapeHTML(trap.effect)}</p>` : '') +
            (trap.countermeasures ? `<p class="kv"><b>Countermeasures:</b> ${escapeHTML(trap.countermeasures)}</p>` : '');
        panel.appendChild(trapDiv);
    }

    if (room.lore) {
        panel.appendChild(tag('Lore'));
        const loreP = document.createElement('p');
        loreP.textContent = String(room.lore);
        panel.appendChild(loreP);
    }

    if (Array.isArray(room.treasure) && room.treasure.length) {
        panel.appendChild(tag('Treasure'));
        const list = document.createElement('ul');
        list.innerHTML = room.treasure.map((/** @type {string} */ t) => `<li>${escapeHTML(t)}</li>`).join('');
        panel.appendChild(list);
    }

    if (Array.isArray(room.exits) && room.exits.length) {
        panel.appendChild(tag('Exits'));
        const list = document.createElement('ul');
        list.innerHTML = room.exits.map((/** @type {Record<string, unknown>} */ ex) => {
            const dest = ex.connectsTo != null ? `Area ${ex.connectsTo}` : 'outside';
            const dir = ex.direction ? String(ex.direction) : '?';

            return `<li><b>${escapeHTML(dir)}</b> → ${escapeHTML(dest)}: ${escapeHTML(String(ex.flavor || ''))}</li>`;
        }).join('');
        panel.appendChild(list);
    }

    if (room.dmNotes || room.difficultyDial) {
        const toggle = document.createElement('div');
        toggle.className = 'dm-toggle' + (dmDetailOpen ? ' open' : '');
        toggle.innerHTML = '<div class="dm-toggle-head">DM detail (notes & dial)</div>';
        const body = document.createElement('div');
        body.className = 'dm-toggle-body';

        if (room.dmNotes) {
            body.innerHTML += `<p class="kv"><b>DM Notes:</b> ${escapeHTML(String(room.dmNotes))}</p>`;
        }

        if (room.difficultyDial) {
            body.innerHTML += `<p class="kv"><b>Difficulty Dial:</b> ${escapeHTML(String(room.difficultyDial))}</p>`;
        }

        toggle.appendChild(body);
        toggle.querySelector('.dm-toggle-head')?.addEventListener('click', () => {
            dmDetailOpen = !dmDetailOpen;
            toggle.classList.toggle('open', dmDetailOpen);
        });
        panel.appendChild(toggle);
    } else if (!data?.overlay) {
        const hint = document.createElement('p');
        hint.className = 'dm-hint';
        hint.textContent = 'Load module.md for DM Notes and Difficulty Dial.';
        panel.appendChild(hint);
    }

    return panel;
}

function renderStats() {
    dom.viewStats.replaceChildren();

    const intro = document.createElement('div');
    intro.className = 'card';
    intro.innerHTML =
        '<h2>Combat prep</h2>' +
        '<p class="kv">Combat-open — safe for VTT tokens and table discussion ' +
        '(AC, HP, abilities, tactics). Narrative-secret items stay under Prep ' +
        '(sealed = AI will not volunteer; captain may unseal).</p>';
    dom.viewStats.appendChild(intro);

    const rooms = sortedRooms();
    const encounterRooms = rooms.filter((room) => {
        const encounter = /** @type {Record<string, unknown> | null} */ (room.encounter);

        return encounter && (/** @type {unknown[]} */ (encounter.monsters || []).length || encounter.tactics);
    });

    if (encounterRooms.length) {
        const roster = document.createElement('div');
        roster.className = 'card';
        roster.innerHTML = '<h2>Encounter roster</h2>';

        for (const room of encounterRooms) {
            const encounter = /** @type {Record<string, unknown>} */ (room.encounter);
            const row = document.createElement('div');
            row.className = 'faq-item open';
            const areaLabel = room.areaName
                ? `Area ${room.roomNumber} — ${room.areaName}`
                : `Area ${room.roomNumber}`;
            let body =
                `<div class="faq-q">${escapeHTML(areaLabel)}</div>` +
                '<div class="faq-a">';

            if (Array.isArray(encounter.monsters) && encounter.monsters.length) {
                const monsters = encounter.monsters.map((/** @type {string} */ m) => {
                    const name = monsterStatName(m);

                    return `<span class="monster-link" data-monster="${escapeHTML(name)}">${escapeHTML(m)}</span>`;
                }).join(', ');

                body += `<p class="kv"><b>Creatures:</b> ${monsters}</p>`;
            }

            if (encounter.tactics) {
                body += `<p class="kv"><b>Tactics:</b> ${escapeHTML(String(encounter.tactics))}</p>`;
            }

            if (encounter.space) {
                body += `<p class="kv"><b>Space:</b> ${escapeHTML(String(encounter.space))}</p>`;
            }

            body += '</div>';
            row.innerHTML = body;
            row.querySelectorAll('.monster-link').forEach((el) => {
                el.addEventListener('click', () => {
                    jumpToStat(el.getAttribute('data-monster') || '');
                });
            });
            roster.appendChild(row);
        }

        dom.viewStats.appendChild(roster);
    }

    const blocks = Array.isArray(data?.statBlocks) ? data.statBlocks : [];

    if (!blocks.length) {
        dom.viewStats.appendChild(buildCard('Stat Blocks', 'No stat blocks in run-data. Load module.md or check your JSON.'));
        return;
    }

    for (const block of blocks) {
        const card = document.createElement('div');
        card.className = 'card stat-card';
        card.setAttribute('data-stat-name', block.name || '');
        card.innerHTML =
            `<h3 class="stat-name">${escapeHTML(block.name || 'Unknown')}</h3>` +
            (block.baseCreature ? `<p class="stat-base">${escapeHTML(block.baseCreature)}</p>` : '') +
            `<div class="stat-body">${escapeHTML(block.block || '')}</div>`;
        dom.viewStats.appendChild(card);
    }
}

function renderRef() {
    dom.viewRef.replaceChildren();

    if (data?.clock) {
        dom.viewRef.appendChild(buildCard('Clock rules', data.clock));
    }

    if (clockSteps.length) {
        const stepsCard = document.createElement('div');
        stepsCard.className = 'card';
        stepsCard.innerHTML = '<h2>Clock steps</h2><ul></ul>';
        const list = stepsCard.querySelector('ul');

        for (const step of clockSteps) {
            const li = document.createElement('li');
            li.innerHTML = `<b>Bell ${step.step}:</b> ${escapeHTML(step.effect)}`;
            li.style.fontWeight = session.clockStep === step.step ? '600' : 'normal';
            list?.appendChild(li);
        }

        dom.viewRef.appendChild(stepsCard);
    }

    if (data?.overlay?.treasureSummary) {
        dom.viewRef.appendChild(buildCard('Treasure Summary', data.overlay.treasureSummary));
    }

    const thread = data?.openThread || data?.overlay?.openThread;

    if (thread) {
        const text = typeof thread === 'string'
            ? thread
            : `${thread.summary || ''}\n\n${thread.seedForNext || ''}`.trim();

        dom.viewRef.appendChild(buildCard('Open Thread', text));
    }
}

/**
 * @param {string} label
 * @param {string} [kind]
 *
 * @returns {HTMLElement}
 */
function tag(label, kind = '') {
    const el = document.createElement('div');
    el.className = 'section-tag' + (kind ? ` ${kind}` : '');
    el.textContent = label;
    return el;
}

/**
 * @param {string} title
 * @param {string} [body]
 * @param {boolean} [copyable]
 *
 * @returns {HTMLElement}
 */
function buildCard(title, body, copyable = false) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `<h2>${escapeHTML(title)}</h2>`;

    if (body) {
        const p = document.createElement('p');
        p.textContent = body;
        card.appendChild(p);

        if (copyable) {
            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-btn';
            copyBtn.textContent = 'Copy briefing';
            copyBtn.addEventListener('click', () => {
                copyToClipboard(body)
                    .then(() => flashCopied(copyBtn, true))
                    .catch(() => flashCopied(copyBtn, false));
            });
            card.appendChild(copyBtn);
        }
    }

    return card;
}
