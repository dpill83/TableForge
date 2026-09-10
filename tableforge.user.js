// ==UserScript==
// @name         TableForge
// @namespace    tableforge.local
// @version      1.0.0
// @description  A human-controlled D&D relay between existing ChatGPT conversations.
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @run-at       document-idle
// @noframes
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_deleteValue
// @grant        GM_xmlhttpRequest
// @grant        GM_setClipboard
// @grant        GM_registerMenuCommand
// @connect      *
// ==/UserScript==

(() => {
  'use strict';
  // Expose only pure helpers to Node's test runner; this branch never runs in Tampermonkey.
  if (typeof document === 'undefined' && typeof module === 'object') {
    module.exports = { extractPlayerView, formatReplies, validURL };
    return;
  }
  if (document.getElementById('tableforge-client')) return;
  const VERSION = 1;
  const MAX_TEXT = 50000;
  const PREFIX = 'tableforge.v1.';
  const uuid = () => crypto.randomUUID();
  const chatId = () => location.pathname.match(/\/c\/([A-Za-z0-9-]+)/)?.[1] || null;
  const storageKey = (id) => PREFIX + 'chat.' + id;
  let route = chatId();
  let epoch = 0;
  let config = null;
  let saved = {};
  let state = null;
  let selected = null;
  let refreshing = false;
  let sending = false;
  let failures = 0;
  let nextPoll = 0;
  let inboxFingerprint = '';
  let controls = new Map();
  let scanned = new WeakMap();
  const host = document.createElement('div');
  host.id = 'tableforge-client';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
    <style>
      :host{all:initial;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#ecedf0;font-size:14px;line-height:1.45;color-scheme:dark}
      *{box-sizing:border-box} [hidden]{display:none!important}
      button,input,textarea,select{font:inherit}button{cursor:pointer;border:1px solid #455062;background:#273143;color:#f5f5f5;border-radius:7px;padding:7px 10px}
      button:hover{background:#354158}button:disabled{opacity:.45;cursor:default}button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:2px solid #dfb878;outline-offset:2px}
      #launcher{position:fixed;bottom:18px;right:22px;z-index:2147483646;background:#192230;border:1px solid #b89b69;box-shadow:0 5px 24px #0005;padding:10px 16px;border-radius:25px;color:#f0d5a6;font-weight:650}
      #panel{position:fixed;right:18px;bottom:70px;width:min(410px,calc(100vw - 24px));max-height:calc(100vh - 100px);z-index:2147483646;background:#141c28;border:1px solid #465063;border-radius:13px;box-shadow:0 16px 70px #0007;overflow:auto}
      header{padding:15px 16px 12px;border-bottom:1px solid #354052;display:flex;justify-content:space-between;align-items:center}
      header strong{font-family:Georgia,serif;font-size:22px;color:#e4c693;letter-spacing:.4px}#identity{color:#b6c1ce;font-size:12px;max-width:300px;overflow-wrap:anywhere}
      .section{padding:13px 16px;border-bottom:1px solid #354052}h3{font-size:13px;text-transform:uppercase;letter-spacing:1.1px;color:#dfc394;margin:0 0 9px}p{margin:6px 0}
      .muted,small{color:#aebaca;font-size:12px}label{display:block;color:#c3ccda;font-size:12px;margin:8px 0 4px}input,textarea,select{width:100%;border:1px solid #445066;border-radius:6px;background:#0e1621;color:#edf1f5;padding:8px}
      textarea{resize:vertical;min-height:100px;line-height:1.5}input[type=checkbox]{width:auto;margin:0 8px 0 0;accent-color:#d7b477}
      .row{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:9px}.primary{background:#d9b779;color:#181e28;border-color:#d9b779;font-weight:650}.primary:hover{background:#eccf99}
      summary{cursor:pointer;color:#c3ccda;font-size:13px}.notice{font-size:12px;margin:9px 16px;color:#b7c7d8;white-space:pre-wrap;overflow-wrap:anywhere}.notice.error{color:#ffbcaa}
      pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;font-size:13px;background:#0e1621;border:1px solid #333f52;border-radius:7px;padding:10px;margin:9px 0;max-height:190px;overflow:auto}
      .reply{border-bottom:1px solid #333f52;padding:8px 0}.reply label{font-size:13px;display:flex;align-items:center}.reply pre{max-height:130px}.stamp{font-size:11px;color:#9dadc0}.caption{display:flex;justify-content:space-between;gap:10px}
      #connection{padding-top:0}#close{padding:3px 8px}#draft-caption{font-size:12px;color:#dfc394;margin:6px 0}#local-note{padding:10px 16px;margin:0;color:#9dadc0;font-size:11px}
    </style>
    <button id="launcher" type="button" aria-expanded="false">TableForge</button>
    <section id="panel" aria-label="TableForge relay" hidden>
      <header><div><strong>TableForge</strong><div id="identity">Connect this conversation</div></div><button id="close" type="button" aria-label="Close TableForge">×</button></header>
      <p id="status" class="notice" role="status" aria-live="polite"></p>
      <details id="settings" class="section" open><summary>Connection for this chat</summary>
        <form id="connection">
          <label for="url">Relay URL</label><input id="url" type="url" placeholder="https://tableforge.example.com" required autocomplete="off">
          <label for="code">Table code</label><input id="code" required autocomplete="off" spellcheck="false">
          <label for="key">Your participant key</label><input id="key" type="password" required autocomplete="off">
          <div class="row"><button class="primary" type="submit" id="connect">Connect this chat</button><button type="button" id="disconnect">Disconnect</button></div>
          <p class="muted">Open an existing conversation first. Its connection and drafts stay with this chat.</p>
        </form>
      </details>
      <div id="connected" hidden>
        <section class="section">
          <div class="caption"><h3>At the table</h3><span id="sync" class="stamp"></span></div>
          <label for="scenes">Scene · recent 50</label><select id="scenes"></select>
          <div class="row"><button id="refresh" type="button">Refresh</button><span id="new-scene" class="muted"></span></div>
          <pre id="scene-text">No scene shared yet.</pre>
          <div class="row" id="scene-actions"><button id="insert-scene" type="button">Insert scene</button><button id="copy-scene" type="button">Copy scene</button></div>
          <p class="muted">Insert appends to your composer. You edit and press Send yourself.</p>
          <div id="reply-area"><h3 style="margin-top:16px">Player replies</h3><div id="replies"></div>
            <div id="dm-actions" class="row"><button id="prepare-replies" type="button">Prepare selected replies</button><button id="mark-reviewed" type="button">Mark selected reviewed</button></div>
          </div>
        </section>
        <section class="section">
          <h3>Review before sending</h3>
          <p id="draft-hint" class="muted"></p>
          <div id="manual"><label for="source">Manual fallback: paste an assistant response</label><textarea id="source" placeholder="Paste the chosen response here."></textarea><div class="row"><button id="stage-manual" type="button">Review pasted response</button></div></div>
          <div id="draft-area" hidden>
            <p id="draft-caption"></p>
            <label for="target" id="target-label">Reply to scene</label><select id="target"></select>
            <label for="draft">Text to share</label><textarea id="draft"></textarea>
            <div class="row"><button class="primary" id="send" type="button">Send to Table</button><button id="copy-draft" type="button">Copy draft</button><button id="discard" type="button">Discard draft</button></div>
          </div>
        </section>
        <section class="section" id="bundle-area" hidden>
          <h3>For the AI-DM composer</h3><label for="bundle">Review or add context</label><textarea id="bundle"></textarea>
          <div class="row"><button class="primary" id="insert-bundle" type="button">Insert grouped replies</button><button id="copy-bundle" type="button">Copy grouped replies</button></div>
          <p class="muted">Preparing or inserting does not mark replies reviewed. Mark them when you are finished.</p>
        </section>
      </div>
      <p id="local-note">Nothing is sent to ChatGPT automatically. Only text you confirm is sent to the relay.</p>
    </section>`;
  document.documentElement.append(host);
  const $ = id => root.getElementById(id);
  const say = (message, error = false) => { $('status').textContent = message; $('status').classList.toggle('error', error); };
  const show = () => { $('panel').hidden = false; $('launcher').setAttribute('aria-expanded', 'true'); };
  const hide = () => { $('panel').hidden = true; $('launcher').setAttribute('aria-expanded', 'false'); };
  function persist() { if (route) GM_setValue(storageKey(route), { ...saved, config }); }
  function assertChat() {
    if (!route || chatId() !== route) throw new Error('Open and connect the intended conversation first.');
  }
  function clearActions() {
    document.querySelectorAll('.tf-response-action').forEach(e => e.remove());
    scanned = new WeakMap();
  }
  function loadRoute() {
    epoch++;
    saved = route ? GM_getValue(storageKey(route), {}) : {};
    config = saved.config || null;
    state = null; selected = saved.selected || null;
    refreshing = false; sending = false; failures = 0; nextPoll = 0;
    inboxFingerprint = ''; controls.clear(); clearActions();
    $('url').value = config?.url || '';
    $('code').value = config?.code || '';
    $('key').value = config?.key || '';
    $('source').value = saved.source || '';
    $('bundle').value = saved.bundle || '';
    $('bundle-area').hidden = !saved.bundle;
    $('connected').hidden = true;
    $('settings').open = !config;
    $('identity').textContent = 'Connect this conversation';
    $('connect').disabled = !route;
    say(route ? 'Connect this chat using your relay URL, table code and key.' : 'Open an existing ChatGPT conversation to connect TableForge.');
    renderDraft();
    if (config) refresh();
  }

  function validURL(raw) {
    const url = new URL(raw.trim());
    if (url.username || url.password || url.search || url.hash) throw new Error('Use a relay URL without credentials, query or fragment.');
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
      throw new Error('Use HTTPS for a shared relay. HTTP is allowed only on localhost.');
    }
    return url.href.replace(/\/+$/, '');
  }
  function request(cfg, method, path, body) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method, url: cfg.url + '/v1/tables/' + encodeURIComponent(cfg.code) + path,
        headers: { 'Authorization': 'Bearer ' + cfg.key, 'Accept': 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
        data: body ? JSON.stringify(body) : undefined,
        timeout: 15000, anonymous: true, redirect: 'error',
        onload(response) {
          try {
            if (response.finalUrl && new URL(response.finalUrl).origin !== new URL(cfg.url).origin) throw new Error('Unexpected relay redirect. Use its final HTTPS URL.');
            const data = JSON.parse(response.responseText);
            if (response.status < 200 || response.status >= 300) throw new Error(data.error || 'Relay returned HTTP ' + response.status);
            resolve(data);
          } catch (error) { reject(new Error(error.message.includes('JSON') ? 'Relay did not return JSON. Check its URL and proxy.' : error.message)); }
        },
        ontimeout: () => reject(new Error('Relay timed out. Any send is saved for a manual retry.')),
        onerror: () => reject(new Error('Cannot reach relay. Check its URL, server and Tampermonkey connection permission.')),
        onabort: () => reject(new Error('Request was interrupted.'))
      });
    });
  }
  async function refresh(manual = false) {
    if (!config || refreshing || chatId() !== route) return;
    const myEpoch = epoch;
    const wanted = selected;
    refreshing = true;
    try {
      const data = await request(config, 'GET', '/state' + (wanted ? '?scene_id=' + wanted : ''));
      if (myEpoch !== epoch || chatId() !== route || wanted !== selected) return;
      if (data.api_version !== VERSION || !['dm', 'player'].includes(data.actor?.role)) throw new Error('Relay API version or role is incompatible.');
      const first = !state;
      state = data;
      selected = data.scene?.id || null;
      saved.selected = selected; persist();
      failures = 0; nextPoll = Date.now() + 5000;
      renderState(); scanResponses();
      $('sync').textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      if (first || manual) say(saved.draft?.pending ? 'An unconfirmed send is saved. Use Retry send to check it without creating a duplicate.' : 'Connected. Review text before sharing or inserting.');
    } catch (error) {
      if (myEpoch !== epoch || chatId() !== route) return;
      failures++;
      nextPoll = Date.now() + Math.min(60000, 5000 * 2 ** Math.min(failures, 4));
      $('sync').textContent = 'Offline · saved view';
      say(error.message, true);
    } finally { if (myEpoch === epoch) refreshing = false; }
  }

  function sceneOptions(select, current, includeDraft = false) {
    select.replaceChildren();
    const options = [...(state?.scenes || [])];
    if (state?.scene && !options.some(s => s.id === state.scene.id)) options.push({ ...state.scene, preview: state.scene.text.slice(0, 90) });
    if (includeDraft && current && !options.some(s => s.id === current)) options.push({ id: current, preview: 'Previously selected scene' });
    if (!options.length) select.add(new Option('No scenes yet', ''));
    for (const scene of options) select.add(new Option('#' + scene.id + ' · ' + scene.preview.replace(/\s+/g, ' ').slice(0, 65) + (scene.reply_count != null ? ` (${scene.reply_count} replies)` : ''), scene.id));
    select.value = current ? String(current) : '';
  }
  function renderState() {
    const isDM = state.actor.role === 'dm';
    $('connected').hidden = false;
    $('identity').textContent = state.table.name + ' · ' + state.actor.name + (isDM ? ' · DM' : ' · Player');
    sceneOptions($('scenes'), selected);
    $('scene-text').textContent = state.scene?.text || 'No scene shared yet. The DM can share a tagged assistant response.';
    $('scene-actions').hidden = !state.scene;
    $('new-scene').textContent = state.scenes[0] && state.scenes[0].id !== selected ? 'A newer scene is available above.' : '';
    $('draft-hint').textContent = isDM ? 'Use “Share PLAYER_VIEW” on an assistant response, or paste below. Only complete tagged sections enter the draft.' : 'Use “Send to Table” on your chosen assistant response, or paste below. Check the scene number before sending.';
    $('dm-actions').hidden = !isDM;
    const fingerprint = JSON.stringify([selected, state.replies, saved.reviewed || [], isDM]);
    if (fingerprint !== inboxFingerprint) {
      const prior = new Map([...controls].map(([id, cb]) => [id, cb.checked]));
      controls.clear(); $('replies').replaceChildren();
      if (!state.replies.length) $('replies').textContent = isDM ? 'No player replies for this scene yet.' : 'Your sent replies will appear here.';
      for (const reply of state.replies) {
        const card = document.createElement('div'); card.className = 'reply';
        const label = document.createElement('label');
        if (isDM) {
          const check = document.createElement('input'); check.type = 'checkbox';
          check.checked = prior.has(reply.id) ? prior.get(reply.id) : !(saved.reviewed || []).includes(reply.id);
          controls.set(reply.id, check); label.append(check);
        }
        label.append(document.createTextNode(reply.name + ' · reply #' + reply.id + ((saved.reviewed || []).includes(reply.id) ? ' · reviewed' : '')));
        const stamp = document.createElement('div'); stamp.className = 'stamp'; stamp.textContent = new Date(reply.created_at).toLocaleString();
        const text = document.createElement('pre'); text.textContent = reply.text;
        card.append(label, stamp, text); $('replies').append(card);
      }
      inboxFingerprint = fingerprint;
    }
    renderDraft();
  }
  function renderDraft() {
    const draft = saved.draft;
    $('scenes').disabled = sending;
    $('draft-area').hidden = !draft;
    $('manual').hidden = !!draft;
    if (!draft) return;
    const player = draft.kind === 'reply';
    $('draft').value = draft.text;
    $('draft').disabled = !!draft.pending;
    $('target').hidden = $('target-label').hidden = !player;
    sceneOptions($('target'), draft.scene_id, true);
    $('target').disabled = !!draft.pending;
    $('draft-caption').textContent = player ? 'Player reply · scene #' + (draft.scene_id || 'choose below') : 'Player-safe scene · extracted from PLAYER_VIEW';
    $('send').textContent = draft.pending ? 'Retry send' : player ? 'Send to Table' : 'Share scene';
    $('send').disabled = sending || !state;
  }

  // Reject malformed or nested tags instead of risking accidental disclosure of DM text.
  function extractPlayerView(text) {
    const tokens = /\[\/?PLAYER_VIEW\]/g;
    const blocks = [];
    let start = null;
    let match;
    while ((match = tokens.exec(text))) {
      if (match[0] === '[PLAYER_VIEW]') {
        if (start !== null) throw new Error('Nested PLAYER_VIEW tags. Correct the text and try again.');
        start = tokens.lastIndex;
      } else {
        if (start === null) throw new Error('Closing PLAYER_VIEW tag without an opening tag.');
        const block = text.slice(start, match.index).trim();
        if (block) blocks.push(block);
        start = null;
      }
    }
    if (start !== null) throw new Error('PLAYER_VIEW is incomplete. Wait for the response to finish or close the tag manually.');
    if (!blocks.length) throw new Error('No complete, nonempty [PLAYER_VIEW]...[/PLAYER_VIEW] section found. Nothing was shared.');
    return blocks.join('\n\n');
  }
  function stage(text, sourceId = null) {
    assertChat();
    if (sending) throw new Error('Wait for the current send to finish.');
    if (!state) throw new Error('Connect to the relay first.');
    if (saved.draft && !confirm('Replace the current draft? If its send is unconfirmed, retry it first to avoid sending it twice.')) return;
    const isDM = state.actor.role === 'dm';
    const value = isDM ? extractPlayerView(text) : text.trim();
    if (!value || value.length > MAX_TEXT) throw new Error('Choose text between 1 and 50,000 characters.');
    saved.draft = { kind: isDM ? 'scene' : 'reply', text: value, scene_id: isDM ? null : (saved.contextScene || selected), sourceId, pending: null };
    saved.source = ''; $('source').value = '';
    persist(); renderDraft(); show();
    say(isDM ? 'Review the player-safe text, then click Share scene.' : 'Review the reply and its scene number, then click Send to Table.');
  }
  async function sendDraft() {
    assertChat();
    const draft = saved.draft;
    if (!draft || !state || sending) return;
    if (!draft.text.trim() || draft.text.length > MAX_TEXT) throw new Error('Text must contain 1–50,000 characters.');
    if (draft.kind === 'reply' && !draft.scene_id) throw new Error('Choose the scene this reply belongs to.');
    if (!draft.pending) draft.pending = { request_id: uuid(), text: draft.text, ...(draft.kind === 'reply' ? { scene_id: draft.scene_id } : {}) };
    // Persist before the network call. Reloads and timeouts retry this exact immutable payload.
    persist();
    const myEpoch = epoch;
    const path = draft.kind === 'scene' ? '/scenes' : '/replies';
    sending = true; renderDraft();
    try {
      const result = await request(config, 'POST', path, draft.pending);
      if (myEpoch !== epoch || chatId() !== route) return;
      saved.draft = null;
      if (result.kind === 'scene') { selected = result.id; saved.selected = result.id; }
      persist(); renderDraft();
      say((result.replayed ? 'Already received by the table' : 'Sent to the table') + ' · ' + result.kind + ' #' + result.id + '.');
      nextPoll = 0; refresh();
    } catch (error) {
      if (myEpoch === epoch && chatId() === route) say(error.message + ' The exact send is saved; Retry send is safe.', true);
    } finally {
      if (myEpoch === epoch) { sending = false; renderDraft(); }
    }
  }
  const chosenReplies = () => {
    assertChat();
    if (state?.actor.role !== 'dm' || state.scene?.id !== selected) throw new Error('Refresh the selected scene before preparing replies.');
    return state.replies.filter(r => controls.get(r.id)?.checked);
  };
  function prepareReplies() {
    assertChat();
    const replies = chosenReplies();
    if (!replies.length) throw new Error('Select at least one player reply.');
    if (saved.bundle && !confirm('Replace the prepared reply text and any edits you made to it?')) return;
    saved.bundle = formatReplies(selected, replies);
    persist(); $('bundle').value = saved.bundle; $('bundle-area').hidden = false;
    say('Grouped replies are ready below. Edit or add context, then insert or copy.');
  }
  function formatReplies(sceneId, replies) {
    const groups = new Map();
    for (const r of replies) {
      if (!groups.has(r.actor_id)) groups.set(r.actor_id, { name: r.name, replies: [] });
      groups.get(r.actor_id).replies.push(r);
    }
    return 'TABLEFORGE · PLAYER RESPONSES · SCENE #' + sceneId + '\nTreat the following as player contributions to this scene.\n\n' +
      [...groups.values()].map(g => '## ' + g.name + '\n' + g.replies.map(r => '[Reply #' + r.id + ']\n' + r.text).join('\n\n')).join('\n\n');
  }

  // Keep ChatGPT DOM assumptions in this adapter. Manual paste/copy bypasses all of them.
  const adapter = {
    responses: () => [...document.querySelectorAll('[data-message-author-role="assistant"]')],
    streaming: () => !!document.querySelector('[data-testid="stop-button"],button[aria-label="Stop streaming"],button[aria-label="Stop generating"],[data-is-streaming="true"]'),
    text(node) {
      const blocks = [...node.querySelectorAll('.markdown')];
      const read = el => {
        if (el.nodeType === Node.TEXT_NODE) return el.textContent;
        if (el.nodeType !== Node.ELEMENT_NODE || el.matches('button,svg,script,style,[aria-hidden="true"],.tf-response-action')) return '';
        if (el.tagName === 'BR') return '\n';
        const value = [...el.childNodes].map(read).join('');
        if (['TD', 'TH'].includes(el.tagName)) return value + '\t';
        return value + (['P', 'DIV', 'PRE', 'LI', 'H1', 'H2', 'H3', 'H4', 'TR', 'BLOCKQUOTE'].includes(el.tagName) ? '\n' : '');
      };
      return (blocks.length ? blocks.map(read).join('\n\n') : read(node)).replace(/\n{3,}/g, '\n\n').trim();
    },
    composer() {
      const candidates = [...document.querySelectorAll('#prompt-textarea[contenteditable="true"],textarea#prompt-textarea,textarea[data-testid="prompt-textarea"],textarea[name="prompt-textarea"]')];
      return candidates.find(el => el.getClientRects().length && !el.disabled && !el.readOnly && el.getAttribute('aria-disabled') !== 'true') || null;
    },
    async insert(text) {
      assertChat();
      if (adapter.streaming()) throw new Error('ChatGPT is generating. Wait, or copy the prepared text for later.');
      const el = adapter.composer();
      if (!el) throw new Error('ChatGPT composer was not found. Use Copy, then paste it yourself.');
      const textarea = el.tagName === 'TEXTAREA';
      const before = textarea ? el.value : el.innerText;
      const addition = (before.trim() ? '\n\n' : '') + text;
      el.focus();
      if (textarea) {
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, before + addition);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.setSelectionRange(el.value.length, el.value.length);
      } else {
        // insertText keeps editor input handling and undo history where supported.
        // Do not directly replace a rich editor's HTML when this mechanism breaks.
        const selection = window.getSelection();
        const range = document.createRange(); range.selectNodeContents(el); range.collapse(false);
        selection.removeAllRanges(); selection.addRange(range);
        if (!document.execCommand('insertText', false, addition)) throw new Error('Composer insertion is unavailable. Use Copy and paste manually.');
      }
      const myRoute = route;
      await new Promise(resolve => setTimeout(resolve, 150));
      if (chatId() !== myRoute) throw new Error('Conversation changed. Check the original composer before retrying.');
      const after = textarea ? el.value : el.innerText;
      const normalize = s => s.replace(/\s+/g, ' ').trim();
      if (!el.isConnected || !normalize(after).endsWith(normalize(text))) throw new Error('Insertion could not be verified. Check the composer, or use Copy.');
      say('Appended to your composer. Review it, then press Send when ready.');
    }
  };
  function scanResponses() {
    if (!state || !route || chatId() !== route) return;
    const label = state.actor.role === 'dm' ? 'Share PLAYER_VIEW' : 'Send to Table';
    for (const response of adapter.responses()) {
      const existing = scanned.get(response);
      if (existing?.isConnected) continue;
      const button = document.createElement('button');
      button.className = 'tf-response-action'; button.type = 'button'; button.textContent = label;
      button.style.cssText = 'font:12px system-ui;margin:8px 0;padding:5px 10px;border-radius:6px;border:1px solid #80704e;background:#192230;color:#e4c693;cursor:pointer;';
      button.title = 'Open an editable TableForge draft. Nothing is sent yet.';
      const boundEpoch = epoch;
      button.addEventListener('click', () => safe(() => {
        if (boundEpoch !== epoch) throw new Error('Conversation changed. Use the action in the current chat.');
        if (adapter.streaming()) throw new Error('Wait for ChatGPT to finish before choosing a response. You can also paste completed text manually.');
        stage(adapter.text(response), response.getAttribute('data-message-id'));
      }));
      response.insertAdjacentElement('afterend', button); scanned.set(response, button);
    }
  }
  function copy(text) {
    if (!text?.trim()) throw new Error('There is no text to copy yet.');
    try { GM_setClipboard(text, 'text'); say('Copied. Paste into the intended composer and review before sending.'); }
    catch { throw new Error('Clipboard access failed. Select the visible text and copy it manually.'); }
  }
  async function safe(fn) {
    try { await fn(); }
    catch (error) { show(); say(error.message, true); }
  }
  function on(id, fn) { $(id).addEventListener('click', () => safe(fn)); }
  on('launcher', () => $('panel').hidden ? show() : hide()); on('close', hide);
  $('connection').addEventListener('submit', event => {
    event.preventDefault();
    safe(async () => {
      assertChat();
      const candidate = { url: validURL($('url').value), code: $('code').value.trim().toLowerCase(), key: $('key').value.trim() };
      if (!/^[a-f0-9]{10}$/.test(candidate.code) || !candidate.key) throw new Error('Enter the table code and participant key printed by the server.');
      if (sending) throw new Error('Wait for the current send to finish.');
      const changed = config && JSON.stringify(candidate) !== JSON.stringify(config);
      if (changed && !confirm('Changing this connection clears this chat’s local drafts and review marks. Continue?')) return;
      epoch++; refreshing = false;
      config = candidate;
      if (changed) { saved = {}; selected = null; $('source').value = ''; $('bundle').value = ''; $('bundle-area').hidden = true; }
      state = null; clearActions(); inboxFingerprint = ''; controls.clear();
      persist(); $('connected').hidden = true; $('settings').open = false;
      await refresh(true);
      if (!state) $('settings').open = true;
    });
  });
  on('disconnect', () => {
    assertChat();
    if (sending) throw new Error('Wait for the current send to finish.');
    if (!confirm('Remove this chat’s connection, drafts and local review marks? Relay history stays saved.')) return;
    GM_deleteValue(storageKey(route)); loadRoute();
  });
  on('refresh', () => refresh(true));
  $('scenes').addEventListener('change', () => safe(async () => {
    if (sending) { $('scenes').value = String(selected); throw new Error('Wait for the current send to finish.'); }
    selected = Number($('scenes').value) || null;
    // Invalidate any request for the previous scene, without changing the outgoing draft target.
    epoch++; refreshing = false; sending = false;
    saved.selected = selected; persist(); clearActions();
    $('scene-actions').hidden = true;
    $('scene-text').textContent = 'Loading selected scene…';
    $('replies').replaceChildren(); controls.clear(); inboxFingerprint = '';
    await refresh(true);
  }));
  function sceneText() {
    if (!state?.scene || state.scene.id !== selected) throw new Error('Refresh the selected scene first.');
    return 'TABLEFORGE · SCENE #' + selected + '\n\n' + state.scene.text;
  }
  on('copy-scene', () => { const text = sceneText(); copy(text); saved.contextScene = selected; persist(); });
  on('insert-scene', async () => { const id = selected; const currentEpoch = epoch; await adapter.insert(sceneText()); if (epoch === currentEpoch) { saved.contextScene = id; persist(); } });
  on('stage-manual', () => stage($('source').value));
  $('source').addEventListener('input', () => { saved.source = $('source').value; persist(); });
  $('draft').addEventListener('input', () => { if (saved.draft && !saved.draft.pending) { saved.draft.text = $('draft').value; persist(); } });
  $('target').addEventListener('change', () => { if (saved.draft && !saved.draft.pending) { saved.draft.scene_id = Number($('target').value) || null; persist(); renderDraft(); } });
  on('send', sendDraft);
  on('copy-draft', () => copy(saved.draft?.text));
  on('discard', () => {
    if (sending) throw new Error('Wait for the current send to finish.');
    if (!confirm(saved.draft?.pending ? 'This send may already be on the server. Retry is safer. Discard its retry record anyway?' : 'Discard this draft?')) return;
    saved.draft = null; persist(); renderDraft();
  });
  on('prepare-replies', prepareReplies);
  on('mark-reviewed', () => {
    const replies = chosenReplies();
    if (!replies.length) throw new Error('Select the replies you have finished handling.');
    saved.reviewed = [...new Set([...(saved.reviewed || []), ...replies.map(r => r.id)])];
    for (const r of replies) controls.get(r.id).checked = false;
    persist(); renderState(); say('Selected replies marked reviewed in this chat. You can still select and reuse them.');
  });
  $('bundle').addEventListener('input', () => { saved.bundle = $('bundle').value; persist(); });
  on('copy-bundle', () => copy($('bundle').value));
  on('insert-bundle', () => { if (!$('bundle').value.trim()) throw new Error('Prepare some replies first.'); return adapter.insert($('bundle').value); });
  GM_registerMenuCommand('Open TableForge', show);
  let scanTimer;
  new MutationObserver(records => {
    if (records.every(r => host.contains(r.target) || r.target === host)) return;
    if (!scanTimer) scanTimer = setTimeout(() => { scanTimer = null; scanResponses(); }, 350);
  }).observe(document.body, { childList: true, subtree: true });
  setInterval(() => {
    const current = chatId();
    if (current !== route) { route = current; loadRoute(); return; }
    if (!document.hidden && config && Date.now() >= nextPoll) refresh();
  }, 1000);
  loadRoute();
})();
