// ==UserScript==
// @name         TableForge
// @namespace    tableforge.local
// @version      1.2.5
// @description  A human-controlled D&D relay between existing ChatGPT conversations.
// @updateURL    https://raw.githubusercontent.com/dpill83/TableForge/main/tableforge.user.js
// @downloadURL  https://raw.githubusercontent.com/dpill83/TableForge/main/tableforge.user.js
// @supportURL   https://github.com/dpill83/TableForge/issues
// @icon         https://raw.githubusercontent.com/dpill83/TableForge/main/tableforge-icon.svg
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @run-at       document-idle
// @noframes
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_deleteValue
// @grant        GM_addValueChangeListener
// @grant        GM_removeValueChangeListener
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
  const API_VERSION = 1;
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
  let persistTimer = null;
  let valueListener = null;
  let attentionCount = 0;
  let sceneFingerprint = '';
  let targetFingerprint = '';
  let inboxFingerprint = '';
  let controls = new Map();
  let scanned = new WeakMap();
  const host = document.createElement('div');
  host.id = 'tableforge-client';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
    <style>
      :host{all:initial;font-family:'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',sans-serif;color:#ececf1;font-size:13px;line-height:1.5;color-scheme:dark}
      *{box-sizing:border-box}[hidden]{display:none!important}button,input,textarea,select{font:inherit}button{cursor:pointer;border:1px solid #34343c;background:#1c1c20;color:#c9c9d2;border-radius:8px;padding:7px 10px}button:hover{background:#29292f;color:#fff}button:disabled{opacity:.4;cursor:default}button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid #b7a5ff;outline-offset:2px}
      #launcher{position:fixed;bottom:18px;right:22px;z-index:2147483646;background:#18181b;border-color:#655738;box-shadow:0 5px 24px #0005;padding:10px 17px;border-radius:25px;color:#e6d3a3;font-family:Georgia,serif;font-size:16px}#attention{position:absolute;top:-8px;right:-8px;min-width:22px;padding:1px 5px;border:2px solid #18181b;border-radius:12px;background:#7957ef;color:white;font:11px/16px system-ui}
      #launcher.has-reply-alert{border-color:#b7a5ff;background:#302344;color:#fff;box-shadow:0 0 0 3px #9974ff55,0 0 24px #9974ff66;animation:reply-pulse 2s ease-in-out infinite}
      @keyframes reply-pulse{0%,100%{box-shadow:0 0 0 2px #9974ff33,0 0 12px #9974ff44}50%{box-shadow:0 0 0 7px #9974ff55,0 0 30px #9974ff99}}
      #scene-next.has-newer-scene{border-color:#b7a5ff;background:#302344;color:#fff;box-shadow:0 0 12px #9974ff66;animation:reply-pulse 2s ease-in-out infinite}
      @media(prefers-reduced-motion:reduce){#launcher.has-reply-alert,#scene-next.has-newer-scene{animation:none}}
      #panel{position:fixed;right:18px;bottom:70px;width:min(380px,calc(100vw - 24px));height:min(760px,calc(100dvh - 94px));z-index:2147483646;background:#141416;border:1px solid #2a2a2f;border-radius:14px;box-shadow:0 30px 80px #0008;overflow:hidden;display:flex;flex-direction:column}
      header{display:flex;align-items:center;gap:9px;padding:12px 14px;border-bottom:1px solid #232328;background:#18181b;flex:none}.brand-mark{display:grid;place-items:center;width:24px;height:24px;flex:none;background:#c9a961;border-radius:6px;color:#1a1408;font:bold 15px Georgia,serif}.brand{flex:1;min-width:0}header strong{color:#e6d3a3;font:600 17px Georgia,serif}#identity{font-size:11px;color:#9a9aa5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}#close,#refresh{padding:3px 7px}#connection-state{font-size:11px;border-radius:99px;padding:3px 8px;color:#aaaab5;white-space:nowrap}#connection-state[data-live=true]{color:#7fd6a3;background:#15271c;border-color:#24503a}
      #panel-scroll{flex:1;min-height:0;overflow:auto;scrollbar-width:thin;scrollbar-color:#34343a transparent}.section{padding:12px}.muted,small{color:#9a9aa5;font-size:11px}p{margin:6px 0}h3,.eyebrow{font:10px/1.5 'IBM Plex Mono',Consolas,monospace;letter-spacing:.12em;text-transform:uppercase;color:#92929e;margin:0 0 8px}.caption{display:flex;justify-content:space-between;gap:8px}.stamp{color:#92929e;font:10px/1.5 Consolas,monospace}.row{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:9px}.primary{background:#6d4df6;border-color:#6d4df6;color:white;font-weight:600}.primary:hover{background:#8064ff;border-color:#8064ff}
      label{display:block;font-size:12px;color:#bcbcc6;margin:9px 0 4px}input,textarea,select{width:100%;border:1px solid #36363f;background:#111114;color:#ececf1;border-radius:7px;padding:8px}textarea{min-height:125px;resize:vertical;line-height:1.6}input[type=checkbox]{width:auto;margin:0 8px 0 0;accent-color:#8567ff}.passphrase-field{display:flex;gap:7px}.passphrase-field input{flex:1;min-width:0}.passphrase-field button{flex:none;min-width:60px}summary{cursor:pointer;color:#c9c9d2;font-size:12px}details.section{margin:10px 12px;padding:10px 12px;border:1px solid #29292f;border-radius:10px}#settings:not([open]){display:none}
      #step-rail{display:flex;gap:4px;padding:10px 12px 0}.step{flex:1;border-bottom:2px solid #2a2a2f;padding:0 0 8px;font:10px/1.5 Consolas,monospace;letter-spacing:.1em;color:#92929e}.step[aria-current=step]{color:#c9a961;border-color:#c9a961}
      #scene-nav{display:flex;gap:8px;align-items:center;padding:12px}#scene-nav button{height:32px}#scene-position{flex:1;text-align:center;min-width:0}#scene-count{font:11px Consolas,monospace;color:#aaaab5}#scene-preview{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}#scene-picker{margin:0 12px 12px;padding:10px;border:1px solid #34343c;border-radius:10px}#scenes{margin-top:8px}#new-scene:empty{display:none}#new-scene{padding:0 12px;color:#c9a961}
      #scene-card{background:#191a1d;border:1px solid #29292f;border-radius:12px;padding:14px 15px}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:15px/1.65 'Spectral',Georgia,serif;color:#dcdce2}#scene-text{min-height:140px}#scene-content{padding-top:0}.reply{border:1px solid #29292f;border-radius:10px;background:#151517;padding:10px 12px;margin:9px 0}.reply pre{font-size:13.5px;color:#b8b8c2;margin-top:5px}.reply label{display:flex;align-items:center;margin:0;color:#aaaab5;font-size:11px}#reply-area{margin-top:16px}#reply-log{margin-top:10px}#draft-area,#bundle-area{margin:12px;padding:12px;border:1px solid #443565;border-radius:10px;background:#19171f}#draft-caption{font-size:12px;color:#cabafa}#draft-hint{margin:8px 0}#manual{margin-top:0}#manual summary{padding:2px 0}#manual summary small{display:block;padding-left:14px;margin-top:2px}
      #status{font-size:11px;color:#b6b6c1;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:8px 12px;border-bottom:1px solid #232328;max-height:80px;overflow:auto}#status:empty{display:none}#status.error{color:#ffbcaa;background:#281e1c}#scene-actions{flex:none;padding:12px;border-top:1px solid #232328;background:#18181b}#scene-actions .row{margin:0;flex-wrap:nowrap}#insert-scene{flex:1;min-height:40px}#copy-scene{width:40px;height:40px;font-size:18px}#local-note{font-size:10px;line-height:1.5;color:#9a9aa5;text-align:center;margin:8px 0 0}
      @media(max-width:440px){#panel{right:12px;bottom:62px;height:calc(100dvh - 78px)}#launcher{right:14px;bottom:12px}}
      #panel.reviewing-scene #scene-nav,#panel.reviewing-scene #scene-picker,#panel.reviewing-scene #new-scene,#panel.reviewing-scene #scene-content,#panel.reviewing-scene #bundle-area{display:none}
      #panel.reviewing-scene #draft-area{border-color:#8c70cc;background:#201a2c;padding:16px;margin-top:14px}
      #panel.reviewing-scene #draft-heading{font:24px/1.25 Georgia,serif;letter-spacing:0;text-transform:none;color:#eee5ff;margin-bottom:10px}
      #panel.reviewing-scene #draft{min-height:220px;height:32dvh;font:15px/1.65 Georgia,serif}
      #scene-actions #draft-buttons{flex-wrap:wrap}#scene-actions #draft-buttons #send{flex:1 0 100%;min-height:44px;font-size:15px}#scene-actions #copy-draft,#scene-actions #discard{flex:1}
    </style>
    <button id="launcher" type="button" aria-expanded="false" aria-controls="panel">TableForge<span id="attention" hidden></span></button>
    <section id="panel" aria-label="TableForge relay" hidden>
      <header><span class="brand-mark" aria-hidden="true">T</span><div class="brand"><strong>TableForge</strong><div id="identity">Connect this conversation</div></div><button id="connection-state" type="button" aria-label="Connection settings" aria-controls="settings">Setup</button><button id="refresh" type="button" title="Refresh table" aria-label="Refresh table">↻</button><button id="close" type="button" aria-label="Close TableForge">−</button></header>
      <p id="status" role="status" aria-live="polite"></p>
      <div id="panel-scroll">
        <details id="settings" class="section" open><summary>Connection for this chat</summary><form id="connection">
          <label for="url">Relay URL</label><input id="url" type="url" placeholder="http://192.168.1.10:8787" required autocomplete="off">
          <label for="code">Table code</label><input id="code" required autocomplete="off" spellcheck="false">
          <label for="key">Participant passphrase</label><div class="passphrase-field"><input id="key" type="text" required autocomplete="off" spellcheck="false"><button id="toggle-key" type="button" aria-controls="key" aria-label="Hide participant passphrase" title="Hide participant passphrase">Hide</button></div>
          <div class="row"><button class="primary" type="submit" id="connect">Connect this chat</button><button type="button" id="disconnect">Disconnect</button></div><p class="muted">Connection and drafts are saved for this conversation.</p>
        </form></details>
        <div id="connected" hidden>
          <div id="step-rail" aria-label="Relay progress"><span id="step-scene" class="step" aria-current="step">1 · SCENE</span><span id="step-reply" class="step">2 · REPLY</span><span id="step-send" class="step">3 · SEND</span></div>
          <nav id="scene-nav" aria-label="Scene navigation"><button id="scene-prev" type="button" aria-label="Previous scene">‹</button><div id="scene-position"><div id="scene-count">NO SCENES</div><div id="scene-preview">Waiting for the DM</div></div><button id="scene-next" type="button" aria-label="Next scene">›</button><button id="scene-all" type="button" aria-expanded="false" aria-controls="scene-picker">All</button></nav>
          <div id="scene-picker" hidden><label for="scene-search">Find a scene · recent 50</label><input id="scene-search" type="search" placeholder="Search scene text or number"><label for="scenes">Choose scene</label><select id="scenes"></select></div>
          <p id="new-scene" class="muted"></p>
          <section id="scene-content" class="section"><div id="scene-card"><div class="caption"><h3>At the table</h3><span id="sync" class="stamp"></span></div><pre id="scene-text">No scene shared yet.</pre></div>
            <div id="reply-area"><h3 id="reply-heading">Player replies</h3><div id="last-reply" hidden><pre id="last-reply-text" class="reply"></pre></div><details id="reply-log" open><summary id="reply-summary">Reply log</summary><div id="replies"></div><div id="dm-actions" class="row"><button id="prepare-replies" type="button" disabled>Prepare selected replies</button></div></details></div>
          </section>
          <details id="manual" class="section"><summary>Paste a response manually<small>Share with the table if the response button is missing</small></summary><p id="draft-hint" class="muted"></p><label for="source">Assistant response</label><textarea id="source" placeholder="Paste a response to share with the other participants."></textarea><div class="row"><button id="stage-manual" type="button">Review pasted response</button></div></details>
          <section id="draft-area" aria-labelledby="draft-heading" hidden><h3 id="draft-heading">Review before sending</h3><p id="draft-caption"></p><label for="target" id="target-label">Reply to scene</label><select id="target"></select><label for="draft">Text to share</label><textarea id="draft"></textarea><div id="draft-buttons" class="row"><button class="primary" id="send" type="button">Send to Table</button><button id="copy-draft" type="button">Copy draft</button><button id="discard" type="button">Discard draft</button></div></section>
          <section id="bundle-area" hidden><h3>For the AI-DM composer</h3><label for="bundle">Review or add context</label><textarea id="bundle"></textarea><p class="muted">Use Insert grouped replies below when ready.</p></section>
        </div>
      </div>
      <footer id="scene-actions" hidden><div class="row" id="player-composer-actions"><button class="primary" id="insert-scene" type="button">Insert scene into composer</button><button id="copy-scene" type="button" title="Copy scene" aria-label="Copy scene">⧉</button></div><div class="row" id="dm-composer-actions" hidden><button class="primary" id="prepare-footer" type="button" style="flex:1;min-height:40px">Prepare selected replies</button><button class="primary" id="insert-bundle" type="button" style="flex:1;min-height:40px" hidden>Insert grouped replies</button><button id="copy-bundle" type="button" title="Copy grouped replies" aria-label="Copy grouped replies" hidden>⧉</button></div><p id="local-note">Appends to your composer. You review and press Send.</p></footer>
    </section>`;
  document.documentElement.append(host);
  const $ = id => root.getElementById(id);
  const say = (message, error = false) => {
    $('status').textContent = message;
    $('status').classList.toggle('error', error);
    $('status').hidden = !error && message.startsWith('Connected.');
    const live = !!state && failures === 0;
    $('connection-state').dataset.live = String(live);
    $('connection-state').textContent = live ? '● Live' : config ? 'Offline' : 'Setup';
    renderComposerActions();
  };
  function renderAttention() {
    $('launcher').classList.toggle('has-reply-alert', attentionCount > 0 && state?.actor.role === 'dm');
    $('attention').hidden = !attentionCount;
    $('attention').textContent = attentionCount > 99 ? '99+' : String(attentionCount);
    $('launcher').title = attentionCount ? `${attentionCount} new TableForge update${attentionCount === 1 ? '' : 's'}` : 'TableForge';
    $('launcher').setAttribute('aria-label', $('launcher').title);
  }
  function clearAttention() { attentionCount = 0; renderAttention(); }
  function addAttention(count) { attentionCount += count; renderAttention(); }
  const show = () => { $('panel').hidden = false; $('launcher').setAttribute('aria-expanded', 'true'); if (!saved.draft) $('panel-scroll').scrollTop = 0; clearAttention(); };
  const hide = () => { $('panel').hidden = true; $('launcher').setAttribute('aria-expanded', 'false'); };
  function storeCurrent() { if (route) GM_setValue(storageKey(route), { ...saved, config }); }
  function cancelPendingPersist() {
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = null;
  }
  function persist() {
    cancelPendingPersist();
    storeCurrent();
  }
  function persistSoon() {
    cancelPendingPersist();
    persistTimer = setTimeout(() => { persistTimer = null; storeCurrent(); }, 250);
  }
  function flushPersist() {
    if (!persistTimer) return;
    cancelPendingPersist();
    storeCurrent();
  }
  function assertChat() {
    if (!route || chatId() !== route) throw new Error('Open and connect the intended conversation first.');
  }
  function clearActions() {
    document.querySelectorAll('.tf-response-action').forEach(e => e.remove());
    scanned = new WeakMap();
  }
  function applyRemoteSaved(value) {
    cancelPendingPersist();
    const incoming = value || {};
    const previousConfig = config;
    const previousSelected = selected;
    const previousDraft = saved.draft;
    const configChanged = JSON.stringify(previousConfig) !== JSON.stringify(incoming.config || null);
    const selectionChanged = previousSelected !== (incoming.selected || null);
    const draftCleared = !!previousDraft && !incoming.draft;
    if (configChanged || selectionChanged || (draftCleared && sending)) {
      epoch++; refreshing = false; sending = false;
    }
    saved = incoming;
    config = saved.config || null;
    selected = saved.selected || null;
    $('url').value = config?.url || '';
    $('code').value = config?.code || '';
    $('key').value = config?.key || '';
    $('source').value = saved.source || '';
    $('bundle').value = saved.bundle || '';
    $('bundle-area').hidden = !saved.bundle;
    if (configChanged || selectionChanged) sceneFingerprint = '';
    if (configChanged || selectionChanged) targetFingerprint = '';
    if (configChanged || selectionChanged) inboxFingerprint = '';
    if (!config) {
      state = null; nextPoll = Infinity; clearActions();
      $('connected').hidden = true; $('settings').open = true;
      $('identity').textContent = 'Connect this conversation';
      say('This chat was disconnected in another tab.');
      return;
    }
    if (configChanged) {
      state = null; nextPoll = 0; clearActions();
      $('connected').hidden = true; $('settings').open = false;
      $('identity').textContent = 'Reconnecting…';
      say('Connection updated in another tab. Reconnecting…');
    } else if (selectionChanged) {
      state = null;
      $('scene-actions').hidden = true;
      $('scene-text').textContent = 'Loading the scene selected in another tab…';
      $('replies').replaceChildren(); controls.clear();
    } else if (state) {
      renderState();
    } else {
      renderDraft();
    }
    if (configChanged || selectionChanged || draftCleared) {
      nextPoll = 0;
      refresh();
    }
    if (draftCleared) say('Draft completed or discarded in another tab. This tab is now synchronized.');
  }
  function bindStorageListener() {
    if (valueListener !== null) GM_removeValueChangeListener(valueListener);
    valueListener = null;
    if (!route) return;
    const key = storageKey(route);
    valueListener = GM_addValueChangeListener(key, (name, oldValue, newValue, remote) => {
      if (remote && name === key && route && storageKey(route) === key) applyRemoteSaved(newValue);
    });
  }
  function loadRoute() {
    $('scene-search').value = '';
    $('scene-picker').hidden = true;
    $('scene-all').setAttribute('aria-expanded', 'false');
    $('manual').open = false;
    cancelPendingPersist();
    clearAttention();
    epoch++;
    saved = route ? GM_getValue(storageKey(route), {}) : {};
    config = saved.config || null;
    bindStorageListener();
    state = null; selected = saved.selected || null;
    refreshing = false; sending = false; failures = 0; nextPoll = 0;
    sceneFingerprint = ''; targetFingerprint = ''; inboxFingerprint = '';
    controls.clear(); clearActions();
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
    const octets = url.hostname.split('.').map(Number);
    const privateLAN = /^\d+\.\d+\.\d+\.\d+$/.test(url.hostname) && octets.every(n => n >= 0 && n <= 255) &&
      (octets[0] === 10 || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
       (octets[0] === 192 && octets[1] === 168));
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' &&
        (privateLAN || ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)))) {
      throw new Error('Use HTTPS, or HTTP with a localhost or private LAN IP address.');
    }
    return url.href.replace(/\/+$/, '');
  }
  function request(cfg, method, path, body) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method, url: cfg.url + '/v1/tables/' + encodeURIComponent(cfg.code) + path,
        headers: { 'Authorization': 'Bearer ' + cfg.key, 'Accept': 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
        data: body ? JSON.stringify(body) : undefined,
        timeout: 15000, anonymous: true,
        onload(response) {
          if (response.finalUrl && new URL(response.finalUrl).origin !== new URL(cfg.url).origin) {
            const error = new Error('Unexpected relay redirect. Use its final HTTPS URL.');
            error.status = response.status;
            reject(error);
            return;
          }
          let data;
          try { data = JSON.parse(response.responseText); }
          catch {
            const error = new Error('Relay returned HTTP ' + response.status + ' without JSON. Check its URL and proxy.');
            error.status = response.status;
            reject(error);
            return;
          }
          if (response.status < 200 || response.status >= 300) {
            const error = new Error(data.error || 'Relay returned HTTP ' + response.status);
            error.status = response.status;
            reject(error);
            return;
          }
          resolve(data);
        },
        ontimeout: () => reject(new Error('Relay timed out. Any send is saved for a manual retry.')),
        onerror: () => reject(new Error('Cannot reach relay. Check its URL, server and Tampermonkey connection permission.')),
        onabort: () => reject(new Error('Request was interrupted.'))
      });
    });
  }
  function stopForAccessFailure(error) {
    if (![401, 403].includes(error.status)) return false;
    failures = 0; nextPoll = Infinity; state = null;
    clearActions();
    $('connected').hidden = true;
    $('settings').open = true;
    $('identity').textContent = 'Connection needs attention';
    $('sync').textContent = '';
    say(error.message + ' Check the table code and participant passphrase, then connect again.', true);
    return true;
  }
  function newActivityCount(previous, current) {
    const priorScenes = new Map(previous.scenes.map(scene => [scene.id, scene]));
    let count = current.scenes.filter(scene => !priorScenes.has(scene.id)).length;
    if (current.actor.role === 'dm') {
      for (const scene of current.scenes) {
        const prior = priorScenes.get(scene.id);
        if (prior) count += Math.max(0, (scene.reply_count || 0) - (prior.reply_count || 0));
      }
    }
    return count;
  }
  async function refresh(manual = false) {
    if (!config || refreshing || chatId() !== route) return;
    const myEpoch = epoch;
    const wanted = selected;
    let reloadLatest = false;
    refreshing = true;
    try {
      const data = await request(config, 'GET', '/state' + (wanted ? '?scene_id=' + wanted : ''));
      if (myEpoch !== epoch || chatId() !== route || wanted !== selected) return;
      if (data.api_version !== API_VERSION || !['dm', 'player'].includes(data.actor?.role)) throw new Error('Relay API version or role is incompatible.');
      const first = !state;
      const activity = first ? 0 : newActivityCount(state, data);
      state = data;
      selected = data.scene?.id || null;
      if ((saved.selected || null) !== selected) {
        saved.selected = selected;
        persist();
      }
      failures = 0; nextPoll = Date.now() + 5000;
      renderState(); scanResponses();
      if (activity && $('panel').hidden) addAttention(activity);
      $('sync').textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      if (first || manual) say(saved.draft?.pending ? 'An unconfirmed send is saved. Use Retry send to check it without creating a duplicate.' : 'Connected. Review text before sharing or inserting.');
    } catch (error) {
      if (myEpoch !== epoch || chatId() !== route) return;
      if (stopForAccessFailure(error)) return;
      if (error.status === 404 && wanted) {
        selected = null;
        sceneFingerprint = '';
        saved.selected = null; persist();
        nextPoll = 0; reloadLatest = true;
        say('The selected scene is no longer available. Loading the latest scene…');
        return;
      }
      failures++;
      nextPoll = Date.now() + Math.min(60000, 5000 * 2 ** Math.min(failures, 4));
      $('sync').textContent = 'Offline · saved view';
      say(error.message, true);
    } finally {
      if (myEpoch === epoch) {
        refreshing = false;
        if (reloadLatest) refresh(manual);
      }
    }
  }

  function sceneOptions(select, current, includeDraft = false) {
    select.replaceChildren();
    const options = [...(state?.scenes || [])];
    if (state?.scene && !options.some(s => s.id === state.scene.id)) options.push({ ...state.scene, preview: state.scene.text.slice(0, 90) });
    if (includeDraft && current && !options.some(s => s.id === current)) options.push({ id: current, preview: 'Previously selected scene' });
    if (!options.length) select.add(new Option('No scenes yet', ''));
    const query = select.id === 'scenes' ? $('scene-search').value.trim().toLowerCase() : '';
    for (const scene of options) {
      if (query && !('#' + scene.id + ' ' + scene.preview).toLowerCase().includes(query)) continue;
      select.add(new Option('#' + scene.id + ' · ' + scene.preview.replace(/\s+/g, ' ').slice(0, 65) + (scene.reply_count != null ? ` (${scene.reply_count} replies)` : ''), scene.id));
    }
    if (!select.options.length) select.add(new Option('No matching scenes', ''));
    select.value = current ? String(current) : '';
  }
  function renderSceneNavigation() {
    const scenes = state?.scenes || [];
    const index = scenes.findIndex(scene => scene.id === selected);
    $('scene-count').textContent = index >= 0 ? 'SCENE ' + (scenes.length - index) + ' / ' + scenes.length : selected ? 'SCENE #' + selected : 'NO SCENES';
    $('scene-preview').textContent = state?.scene?.text.replace(/\s+/g, ' ').slice(0, 100) || 'Waiting for the DM';
    $('scene-prev').disabled = sending || index < 0 || index >= scenes.length - 1;
    const newer = !!selected && !!scenes.length && scenes[0].id !== selected;
    $('scene-next').disabled = sending || !newer;
    $('scene-next').classList.toggle('has-newer-scene', newer);
    $('scene-next').title = newer ? 'A newer scene is available — open next scene' : 'Next scene';
    $('scene-next').setAttribute('aria-label', $('scene-next').title);
    $('scene-all').disabled = sending || !scenes.length;
  }
  function sceneOptionsFingerprint(current, includeDraft = false) {
    const scenes = state?.scenes || [];
    const selectedScene = state?.scene && !scenes.some(scene => scene.id === state.scene.id)
      ? [state.scene.id, state.scene.text.slice(0, 90)] : null;
    return JSON.stringify([
      current || null,
      includeDraft,
      scenes.map(scene => [scene.id, scene.preview, scene.reply_count]),
      selectedScene
    ]);
  }
  function renderState() {
    const isDM = state.actor.role === 'dm';
    $('connection-state').dataset.live = String(failures === 0);
    $('connection-state').textContent = failures === 0 ? '● Live' : 'Offline';
    $('connected').hidden = false;
    $('identity').textContent = state.table.name + ' · ' + state.actor.name + (isDM ? ' · DM' : ' · Player');
    const nextSceneFingerprint = sceneOptionsFingerprint(selected);
    if (nextSceneFingerprint !== sceneFingerprint) {
      sceneOptions($('scenes'), selected);
      sceneFingerprint = nextSceneFingerprint;
    }
    $('scene-text').textContent = state.scene?.text || 'No scene shared yet. The DM can share a tagged assistant response.';
    $('scene-actions').hidden = !state.scene;
    $('new-scene').textContent = state.scenes[0] && state.scenes[0].id !== selected ? 'A newer scene is available. Use › or All to open it.' : '';
    $('draft-hint').textContent = isDM ? 'Use “Share PLAYER_VIEW” on an assistant response, or paste below. Only complete tagged sections enter the draft.' : 'Use “Send to Table” on your chosen assistant response, or paste below. Check the scene number before sending.';
    $('dm-actions').hidden = !isDM;
    $('reply-heading').textContent = isDM ? 'Player replies' : 'Your last reply · this scene';
    $('last-reply').hidden = isDM || !state.replies.length;
    $('last-reply-text').textContent = state.replies.at(-1)?.text || '';
    if ($('reply-log').dataset.role !== state.actor.role) {
      $('reply-log').open = isDM;
      $('reply-log').dataset.role = state.actor.role;
    }
    $('reply-summary').textContent = 'Reply log · ' + state.replies.length;
    const fingerprint = JSON.stringify([selected, state.replies, isDM]);
    if (fingerprint !== inboxFingerprint) {
      const prior = new Map([...controls].map(([id, cb]) => [id, cb.checked]));
      controls.clear(); $('replies').replaceChildren();
      if (!state.replies.length) $('replies').textContent = isDM ? 'No player replies for this scene yet.' : 'Your sent replies will appear here.';
      for (const reply of state.replies) {
        const card = document.createElement('div'); card.className = 'reply';
        const label = document.createElement('label');
        if (isDM) {
          const check = document.createElement('input'); check.type = 'checkbox';
          check.checked = prior.has(reply.id) ? prior.get(reply.id) : true;
          check.addEventListener('change', renderComposerActions);
          controls.set(reply.id, check); label.append(check);
        }
        label.append(document.createTextNode(reply.name + ' · reply #' + reply.id));
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
    const sceneReview = draft?.kind === 'scene';
    $('panel').classList.toggle('reviewing-scene', sceneReview);
    if (sceneReview) {
      if ($('draft-area').nextElementSibling !== $('scene-nav')) $('connected').insertBefore($('draft-area'), $('scene-nav'));
      if ($('draft-buttons').parentElement !== $('scene-actions')) $('scene-actions').insertBefore($('draft-buttons'), $('player-composer-actions'));
    } else {
      if ($('draft-area').nextElementSibling !== $('bundle-area')) $('connected').insertBefore($('draft-area'), $('bundle-area'));
      if ($('draft-buttons').parentElement !== $('draft-area')) $('draft-area').append($('draft-buttons'));
    }
    renderComposerActions();
    if (!draft && !$('draft-area').hidden) $('panel-scroll').scrollTop = 0;
    renderSceneNavigation();
    const active = draft ? 'send' : saved.contextScene || saved.bundle ? 'reply' : 'scene';
    for (const step of ['scene', 'reply', 'send']) {
      if (step === active) $('step-' + step).setAttribute('aria-current', 'step');
      else $('step-' + step).removeAttribute('aria-current');
    }
    $('scenes').disabled = sending;
    $('draft-area').hidden = !draft;
    $('manual').hidden = !!draft;
    if (!draft) return;
    const player = draft.kind === 'reply';
    $('draft').value = draft.text;
    $('draft').disabled = !!draft.pending;
    $('target').hidden = $('target-label').hidden = !player;
    const nextTargetFingerprint = sceneOptionsFingerprint(draft.scene_id, true);
    if (nextTargetFingerprint !== targetFingerprint) {
      sceneOptions($('target'), draft.scene_id, true);
      targetFingerprint = nextTargetFingerprint;
    }
    $('target').disabled = !!draft.pending;
    $('draft-heading').textContent = player ? 'Review before sending' : 'Review new scene';
    $('draft-caption').textContent = player ? 'Player reply · scene #' + (draft.scene_id || 'choose below') : 'Player-safe text from PLAYER_VIEW. Review what everyone at the table will see.';
    $('send').textContent = draft.pending ? 'Retry send' : player ? 'Send to Table' : 'Share new scene';
    $('send').disabled = sending || !state;
  }

  function renderComposerActions() {
    const dm = state?.actor.role === 'dm';
    const current = !!state?.scene && state.scene.id === selected;
    const prepared = !!saved.bundle;
    const sceneReview = saved.draft?.kind === 'scene';
    $('scene-actions').hidden = !state || (!sceneReview && !dm && !current);
    $('player-composer-actions').hidden = dm || sceneReview;
    $('dm-composer-actions').hidden = !dm || sceneReview;
    $('prepare-footer').hidden = prepared;
    const canPrepare = dm && current && state.replies.some(reply => controls.get(reply.id)?.checked);
    $('prepare-footer').disabled = !canPrepare;
    $('prepare-replies').disabled = !canPrepare;
    $('insert-bundle').hidden = !prepared;
    $('copy-bundle').hidden = !prepared;
    $('local-note').textContent = sceneReview ? 'Creates a new scene visible to all players.' : dm && !prepared
      ? 'Select player replies, then prepare them for review.'
      : dm ? 'Inserts replies above your composer notes. You review and press Send.'
      : 'Appends to your composer. You review and press Send.';
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
  function stage(text) {
    assertChat();
    if (sending) throw new Error('Wait for the current send to finish.');
    if (!state) throw new Error('Connect to the relay first.');
    if (saved.draft && !confirm('Replace the current draft? If its send is unconfirmed, retry it first to avoid sending it twice.')) return;
    const isDM = state.actor.role === 'dm';
    const value = isDM ? extractPlayerView(text) : text.trim();
    if (!value || value.length > MAX_TEXT) throw new Error('Choose text between 1 and 50,000 characters.');
    saved.draft = { kind: isDM ? 'scene' : 'reply', text: value, scene_id: isDM ? null : (saved.contextScene || selected), pending: null };
    saved.source = ''; $('source').value = '';
    $('manual').open = false;
    persist(); renderDraft(); show();
    if (isDM) $('panel-scroll').scrollTop = 0;
    else $('draft-area').scrollIntoView({ block: 'nearest' });
    say(isDM ? 'Review the player-safe text, then click Share new scene.' : 'Review the reply and its scene number, then click Send to Table.');
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
      if (result.kind === 'scene') {
        selected = result.id; saved.selected = result.id;
        delete saved.bundle;
        $('bundle').value = '';
        $('bundle-area').hidden = true;
      }
      else delete saved.contextScene;
      persist(); renderDraft();
      say((result.replayed ? 'Already received by the table' : 'Sent to the table') + ' · ' + result.kind + ' #' + result.id + '.');
      nextPoll = 0; refresh();
    } catch (error) {
      if (myEpoch === epoch && chatId() === route && !stopForAccessFailure(error)) {
        if (error.status === 409) {
          draft.pending = null;
          persist(); renderDraft();
          say(error.message + ' The draft is saved. Send it again to use a new request ID.', true);
        } else {
          say(error.message + ' The exact send is saved; Retry send is safe.', true);
        }
      }
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
    renderDraft();
    $('bundle-area').scrollIntoView({ block: 'nearest' });
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
        if (el.tagName === 'PRE') {
          const code = el.querySelector('code');
          return code ? code.textContent + '\n' : '';
        }
        const value = [...el.childNodes].map(read).join('');
        if (['TD', 'TH'].includes(el.tagName)) return value + '\t';
        if (el.tagName === 'TR') return value.trimEnd() + '\n';
        if (el.tagName === 'LI') return (el.parentElement?.tagName === 'OL' ? '1. ' : '- ') + value.trim() + '\n';
        return value + (['P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'BLOCKQUOTE'].includes(el.tagName) ? '\n' : '');
      };
      return (blocks.length ? blocks.map(read).join('\n\n') : read(node)).replace(/\n{3,}/g, '\n\n').trim();
    },
    composer() {
      const candidates = [...document.querySelectorAll('#prompt-textarea[contenteditable="true"],textarea#prompt-textarea,textarea[data-testid="prompt-textarea"],textarea[name="prompt-textarea"]')];
      return candidates.find(el => el.getClientRects().length && !el.disabled && !el.readOnly && el.getAttribute('aria-disabled') !== 'true') || null;
    },
    async insert(text, { prepend = false } = {}) {
      assertChat();
      if (adapter.streaming()) throw new Error('ChatGPT is generating. Wait, or copy the prepared text for later.');
      const el = adapter.composer();
      if (!el) throw new Error('ChatGPT composer was not found. Use Copy, then paste it yourself.');
      const textarea = el.tagName === 'TEXTAREA';
      const before = textarea ? el.value : el.innerText;
      const separator = before.trim() ? '\n\n' : '';
      const addition = prepend ? text + separator : separator + text;
      const expected = prepend ? addition + before : before + addition;
      const myRoute = route;
      const normalize = value => value.replace(/\s+/g, ' ').trim();
      const verify = async () => {
        await new Promise(resolve => setTimeout(resolve, 150));
        if (chatId() !== myRoute) throw new Error('Conversation changed. Check the original composer before retrying.');
        const after = textarea ? el.value : el.innerText;
        return el.isConnected && normalize(after) === normalize(expected);
      };
      el.focus();
      if (textarea) {
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, expected);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.setSelectionRange(el.value.length, el.value.length);
      } else {
        const moveCursorToInsertionPoint = () => {
          el.focus();
          const selection = window.getSelection();
          const range = document.createRange(); range.selectNodeContents(el); range.collapse(prepend);
          selection.removeAllRanges(); selection.addRange(range);
        };
        moveCursorToInsertionPoint();
        try { document.execCommand('insertText', false, addition); } catch { /* Try paste below. */ }
        let verified = await verify();
        if (!verified) {
          // Do not insert a second copy if the editor partly inserted text or the user kept typing.
          if (el.innerText !== before) throw new Error('Insertion could not be verified. Check the composer before inserting again.');
          moveCursorToInsertionPoint();
          try {
            const clipboard = new DataTransfer();
            clipboard.setData('text/plain', addition);
            el.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: clipboard }));
          } catch { /* Verification below preserves the manual-copy fallback. */ }
          verified = await verify();
        }
        if (!verified) throw new Error('Insertion could not be verified. Check the composer, or use Copy.');
      }
      if (textarea && !await verify()) throw new Error('Insertion could not be verified. Check the composer, or use Copy.');
      say((prepend ? 'Inserted above your composer notes.' : 'Appended to your composer.') + ' Review it, then press Send when ready.');
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
      button.style.cssText = 'font:12px system-ui;margin:8px 0;padding:6px 11px;border-radius:7px;border:1px solid #675298;background:#211c30;color:#d4c7ff;cursor:pointer;';
      button.title = 'Open an editable TableForge draft. Nothing is sent yet.';
      const boundEpoch = epoch;
      button.addEventListener('click', () => safe(() => {
        if (boundEpoch !== epoch) throw new Error('Conversation changed. Use the action in the current chat.');
        if (adapter.streaming()) throw new Error('Wait for ChatGPT to finish before choosing a response. You can also paste completed text manually.');
        stage(adapter.text(response));
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
  on('connection-state', () => {
    $('settings').open = !$('settings').open;
    if ($('settings').open) $('settings').scrollIntoView({ block: 'nearest' });
  });
  on('scene-all', () => {
    $('scene-picker').hidden = !$('scene-picker').hidden;
    $('scene-all').setAttribute('aria-expanded', String(!$('scene-picker').hidden));
    if (!$('scene-picker').hidden) $('scene-search').focus();
  });
  $('scene-search').addEventListener('input', () => sceneOptions($('scenes'), selected));
  $('scene-picker').addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      $('scene-picker').hidden = true;
      $('scene-all').setAttribute('aria-expanded', 'false');
      $('scene-all').focus();
    }
  });
  on('scene-prev', () => stepScene(1));
  on('scene-next', () => stepScene(-1));
  on('toggle-key', () => {
    const visible = $('key').type === 'password';
    $('key').type = visible ? 'text' : 'password';
    $('toggle-key').textContent = visible ? 'Hide' : 'Show';
    $('toggle-key').setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} participant passphrase`);
    $('toggle-key').title = `${visible ? 'Hide' : 'Show'} participant passphrase`;
  });
  $('connection').addEventListener('submit', event => {
    event.preventDefault();
    safe(async () => {
      assertChat();
      const candidate = { url: validURL($('url').value), code: $('code').value.trim().toLowerCase(), key: $('key').value.trim() };
      if (!/^(?:[a-z]+|[a-f0-9]{10})$/.test(candidate.code) || !candidate.key) throw new Error('Enter the table code and participant passphrase printed by the server.');
      if (sending) throw new Error('Wait for the current send to finish.');
      const changed = config && JSON.stringify(candidate) !== JSON.stringify(config);
      if (changed && !confirm('Changing this connection clears this chat’s local drafts. Continue?')) return;
      epoch++; refreshing = false;
      nextPoll = 0;
      config = candidate;
      if (changed) { saved = {}; selected = null; $('source').value = ''; $('bundle').value = ''; $('bundle-area').hidden = true; }
      state = null; clearActions(); sceneFingerprint = ''; targetFingerprint = ''; inboxFingerprint = ''; controls.clear();
      persist(); $('connected').hidden = true; $('settings').open = false;
      await refresh(true);
      if (!state) $('settings').open = true;
    });
  });
  on('disconnect', () => {
    assertChat();
    if (sending) throw new Error('Wait for the current send to finish.');
    if (!confirm('Remove this chat’s connection and drafts? Relay history stays saved.')) return;
    GM_deleteValue(storageKey(route)); loadRoute();
  });
  on('refresh', () => refresh(true));
  function stepScene(direction) {
    const index = state?.scenes.findIndex(scene => scene.id === selected) ?? -1;
    const scene = index >= 0 ? state.scenes[index + direction] : direction === -1 ? state?.scenes.at(-1) : null;
    if (scene) return selectScene(scene.id);
  }
  async function selectScene(id) {
    if (sending) { $('scenes').value = String(selected); throw new Error('Wait for the current send to finish.'); }
    if (!id) return;
    selected = id;
    $('scene-picker').hidden = true;
    $('scene-all').setAttribute('aria-expanded', 'false');
    $('scene-search').value = '';
    sceneFingerprint = '';
    // Invalidate any request for the previous scene, without changing the outgoing draft target.
    epoch++; refreshing = false; sending = false;
    saved.selected = selected; persist(); clearActions();
    $('scene-actions').hidden = true;
    $('scene-text').textContent = 'Loading selected scene…';
    $('replies').replaceChildren(); controls.clear(); inboxFingerprint = '';
    await refresh(true);
  }
  $('scenes').addEventListener('change', () => safe(() => selectScene(Number($('scenes').value) || null)));
  function sceneText() {
    if (!state?.scene || state.scene.id !== selected) throw new Error('Refresh the selected scene first.');
    return 'TABLEFORGE · SCENE #' + selected + '\n\n' + state.scene.text;
  }
  on('copy-scene', () => { const text = sceneText(); copy(text); saved.contextScene = selected; persist(); renderDraft(); });
  on('insert-scene', async () => { const id = selected; const currentEpoch = epoch; await adapter.insert(sceneText()); if (epoch === currentEpoch) { saved.contextScene = id; persist(); renderDraft(); } });
  on('stage-manual', () => stage($('source').value));
  $('source').addEventListener('input', () => { saved.source = $('source').value; persistSoon(); });
  $('draft').addEventListener('input', () => { if (saved.draft && !saved.draft.pending) { saved.draft.text = $('draft').value; persistSoon(); } });
  $('target').addEventListener('change', () => { if (saved.draft && !saved.draft.pending) { saved.draft.scene_id = Number($('target').value) || null; persist(); renderDraft(); } });
  on('send', sendDraft);
  on('copy-draft', () => copy(saved.draft?.text));
  on('discard', () => {
    if (sending) throw new Error('Wait for the current send to finish.');
    if (!confirm(saved.draft?.pending ? 'This send may already be on the server. Retry is safer. Discard its retry record anyway?' : 'Discard this draft?')) return;
    saved.draft = null; persist(); renderDraft();
  });
  on('prepare-replies', prepareReplies);
  on('prepare-footer', prepareReplies);
  $('bundle').addEventListener('input', () => { saved.bundle = $('bundle').value; persistSoon(); });
  on('copy-bundle', () => copy($('bundle').value));
  on('insert-bundle', () => { if (!$('bundle').value.trim()) throw new Error('Prepare some replies first.'); return adapter.insert($('bundle').value, { prepend: true }); });
  GM_registerMenuCommand('Open TableForge', show);
  let scanTimer;
  new MutationObserver(() => {
    if (!scanTimer) scanTimer = setTimeout(() => { scanTimer = null; scanResponses(); }, 350);
  }).observe(document.body, { childList: true, subtree: true });
  window.addEventListener('pagehide', flushPersist);
  setInterval(() => {
    const current = chatId();
    if (current !== route) { flushPersist(); route = current; loadRoute(); return; }
    if (!document.hidden && config && Date.now() >= nextPoll) refresh();
  }, 1000);
  loadRoute();
})();
