/* Browser integration test: real userscript + real relay, ChatGPT DOM fixtures and GM shim.
   Run: npm install && npx playwright install chromium && npm run test:browser
   No ChatGPT account or API key is used. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const playwright = require('playwright');
const project = path.resolve(__dirname, '..');
const script = fs.readFileSync(path.join(project, 'tableforge.user.js'), 'utf8');
const richResponseFixture = fs.readFileSync(path.join(project, 'tests', 'fixtures', 'rich-response.html'), 'utf8');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'tableforge-test-'));
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const child = spawn(python, ['-u', '-c', `
import json, server, sys
db = sys.argv[1]
table = server.create_table(db, "Waterdeep test", ["George", "Viktor"])
http = server.make_server(db, port=0)
print(json.dumps({"port":http.server_port, "table":table}), flush=True)
http.serve_forever()
`, path.join(tmp, 'test.sqlite3')], { cwd: project, stdio: ['ignore', 'pipe', 'inherit'] });
const fixture = `<!doctype html><html><body style="font-family:system-ui;background:#f9fafb;padding:40px 460px 40px 40px">
<h1>ChatGPT conversation fixture</h1><main id="messages"></main>
<form id="chat-form"><div id="prompt-textarea" contenteditable="true" role="textbox" style="white-space:pre-wrap;border:1px solid #aaa;min-height:70px;padding:16px">Existing note.</div>
<button type="submit" id="chat-send">Send</button></form>
<script>window.submits=0;document.querySelector('form').onsubmit=e=>{e.preventDefault();window.submits++};</script></body></html>`;
let browser;
const errors = [];
function pass(name) { console.log('PASS ' + name); }

(async () => {
  const boot = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Relay startup timed out')), 10000);
    createInterface({ input: child.stdout }).once('line', line => { clearTimeout(timeout); resolve(JSON.parse(line)); });
    child.once('error', reject);
  });
  const url = 'http://127.0.0.1:' + boot.port;
  browser = await playwright.chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH }
      : process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {})
  });
  async function client(index, id) {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    const values = {};
    let clipboard = '';
    let loseNextPost = false;
    let requestCount = 0;
    let nextResponse = null;
    const actor = boot.table.credentials[index];
    const connection = { url, code: boot.table.table_code, key: actor.key };
    values['tableforge.v1.chat.' + id] = { config: connection };
    await page.exposeFunction('gmSave', (key, value) => { values[key] = value; });
    await page.exposeFunction('gmDelete', key => { delete values[key]; });
    await page.exposeFunction('gmCopy', text => { clipboard = text; });
    await page.exposeFunction('gmRequest', async details => {
      requestCount++;
      if (nextResponse) {
        const response = nextResponse; nextResponse = null;
        return { ...response, finalUrl: details.url };
      }
      const response = await fetch(details.url, { method: details.method, headers: details.headers, body: details.data });
      const responseText = await response.text();
      if (loseNextPost && details.method === 'POST') { loseNextPost = false; return { timeout: true }; }
      return { status: response.status, responseText, finalUrl: details.url };
    });
    await page.route('https://chatgpt.com/**', r => r.fulfill({ contentType: 'text/html', body: fixture }));
    async function inject() {
      await page.evaluate(v => {
        window.gmValueListeners = new Map();
        window.gmNextListenerId = 1;
        const notifyValueListeners = (key, oldValue, newValue, remote) => {
          for (const listener of window.gmValueListeners.values()) {
            if (listener.key === key) listener.callback(key, structuredClone(oldValue), structuredClone(newValue), remote);
          }
        };
        window.GM_getValue = (k, fallback) => structuredClone(v[k] ?? fallback);
        window.GM_setValue = (k, value) => {
          const oldValue = v[k]; v[k] = structuredClone(value); window.gmSave(k, value);
          notifyValueListeners(k, oldValue, value, false);
        };
        window.GM_deleteValue = k => {
          const oldValue = v[k]; delete v[k]; window.gmDelete(k);
          notifyValueListeners(k, oldValue, undefined, false);
        };
        window.GM_addValueChangeListener = (key, callback) => {
          const id = window.gmNextListenerId++;
          window.gmValueListeners.set(id, { key, callback });
          return id;
        };
        window.GM_removeValueChangeListener = id => window.gmValueListeners.delete(id);
        window.simulateGMRemote = (key, value) => {
          const oldValue = v[key]; v[key] = structuredClone(value); window.gmSave(key, value);
          notifyValueListeners(key, oldValue, value, true);
        };
        window.GM_setClipboard = text => window.gmCopy(text);
        window.GM_registerMenuCommand = () => {};
        window.GM_xmlhttpRequest = details => { window.gmRequest({ url: details.url, method: details.method, headers: details.headers, data: details.data }).then(r => r.timeout ? details.ontimeout() : details.onload(r)).catch(details.onerror); };
      }, values);
      await page.addScriptTag({ content: script });
    }
    await page.goto('https://chatgpt.com/c/' + id);
    await inject();
    page.on('dialog', dialog => dialog.accept());
    const el = id => page.locator('#tableforge-client').locator('#' + id);
    await el('launcher').click();
    await el('connected').waitFor({ state: 'visible' });
    return { page, el, values, connection, clipboard: () => clipboard,
      requestCount: () => requestCount,
      respondNext: (status, responseText) => { nextResponse = { status, responseText }; },
      losePost: () => { loseNextPost = true; },
      reload: async () => { await page.reload(); await inject(); await el('launcher').click(); await el('connected').waitFor({ state: 'visible' }); } };
  }
  const dm = await client(0, 'dm-chat');
  const george = await client(1, 'george-chat');
  const viktor = await client(2, 'viktor-chat');
  async function response(client, text) {
    await client.page.evaluate(text => {
      const node = document.createElement('div'); node.dataset.messageAuthorRole = 'assistant';
      const body = document.createElement('div'); body.className = 'markdown'; body.textContent = text;
      node.append(body); document.getElementById('messages').append(node);
    }, text);
    await client.page.locator('.tf-response-action').last().waitFor();
    await client.page.locator('.tf-response-action').last().click();
  }
  async function responseHTML(client, html) {
    await client.page.evaluate(html => {
      const node = document.createElement('div'); node.dataset.messageAuthorRole = 'assistant';
      const body = document.createElement('div'); body.className = 'markdown'; body.innerHTML = html;
      node.append(body); document.getElementById('messages').append(node);
    }, html);
    await client.page.locator('.tf-response-action').last().waitFor();
    await client.page.locator('.tf-response-action').last().click();
  }
  async function refresh(client) {
    await client.el('refresh').click();
    await client.page.waitForTimeout(250);
  }
  const privateDM = 'PRIVATE: the butler is a devil.';
  await response(dm, privateDM + '\n[PLAYER_VIEW]You enter the candlelit study.[/PLAYER_VIEW]\nSecret DC 20.');
  assert.equal(await dm.el('draft').inputValue(), 'You enter the candlelit study.');
  let snapshot = await (await fetch(url + '/v1/tables/' + boot.table.table_code + '/state', { headers: { Authorization: 'Bearer ' + boot.table.credentials[0].key } })).json();
  assert.equal(snapshot.scenes.length, 0, 'Response action only stages a draft');
  await dm.el('send').click();
  await dm.el('draft-area').waitFor({ state: 'hidden' });
  await refresh(george); await refresh(viktor);
  assert.equal(await george.el('scene-text').textContent(), 'You enter the candlelit study.');
  assert.ok(!(await george.el('scene-text').textContent()).includes(privateDM));
  pass('only PLAYER_VIEW shared, with explicit review before transmission');

  await george.el('insert-scene').click();
  const composer = await george.page.locator('#prompt-textarea').innerText();
  assert.ok(composer.startsWith('Existing note.'));
  assert.ok(composer.includes('You enter the candlelit study.'));
  assert.equal(await george.page.evaluate(() => window.submits), 0);
  pass('rich composer insertion preserves existing text and never submits');

  await responseHTML(george, richResponseFixture);
  assert.equal(await george.el('draft').inputValue(), 'Plan carefully:\n1. Open the oak door\n1. Check the room\n- Listen at the passage\n- Inspect the desk\nStay together.\n\nprint("ready")\nprint("steady")\nName\tAction\nGeorge\tListen');
  await george.page.evaluate(() => {
    const root = document.querySelector('#tableforge-client').shadowRoot;
    window.sceneOptionMutations = { scenes: 0, target: 0 };
    for (const id of ['scenes', 'target']) {
      new MutationObserver(records => { window.sceneOptionMutations[id] += records.length; })
        .observe(root.getElementById(id), { childList: true });
    }
  });
  await refresh(george);
  assert.deepEqual(await george.page.evaluate(() => window.sceneOptionMutations), { scenes: 0, target: 0 });
  const immediateWrites = await george.page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    window.originalGMSetValue = window.GM_setValue;
    window.persistWriteCount = 0;
    window.GM_setValue = (...args) => {
      window.persistWriteCount++;
      return window.originalGMSetValue(...args);
    };
    const root = document.querySelector('#tableforge-client').shadowRoot;
    for (const id of ['source', 'draft', 'bundle']) {
      const textarea = root.getElementById(id);
      for (const character of 'typing') {
        textarea.value += character;
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
    return window.persistWriteCount;
  });
  assert.equal(immediateWrites, 0);
  await george.page.waitForTimeout(125);
  assert.equal(await george.page.evaluate(() => window.persistWriteCount), 0);
  await george.page.waitForTimeout(200);
  assert.equal(await george.page.evaluate(() => window.persistWriteCount), 1);
  await george.page.evaluate(() => {
    window.GM_setValue = window.originalGMSetValue;
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  });
  await george.el('discard').click();
  pass('response serialization preserves list markers and code while trimming table rows');
  pass('unchanged refresh leaves both scene dropdowns intact');
  pass('textarea edits are persisted once after a 250ms debounce');

  await response(george, 'George watches the doorway.');
  george.losePost();
  await george.el('send').click();
  await george.page.waitForFunction(() => document.querySelector('#tableforge-client').shadowRoot.getElementById('status').textContent.includes('timed out'));
  await george.reload();
  assert.equal(await george.el('send').textContent(), 'Retry send');
  await george.el('send').click();
  await george.el('draft-area').waitFor({ state: 'hidden' });
  await refresh(george);
  assert.equal(await george.el('replies').locator('.reply').count(), 1);
  pass('lost POST acknowledgement survives reload and retry does not duplicate');

  await response(george, 'George checks the locked cabinet.');
  george.respondNext(409, JSON.stringify({ error: 'Request ID was already used with different content.' }));
  await george.el('send').click();
  await george.page.waitForFunction(() => document.querySelector('#tableforge-client').shadowRoot.getElementById('status').textContent.includes('Send it again to use a new request ID.'));
  assert.equal(await george.el('send').textContent(), 'Send to Table');
  assert.equal(await george.el('draft').isEnabled(), true);
  await george.el('discard').click();
  pass('request-ID conflicts preserve an editable draft without unsafe retry guidance');

  await viktor.el('source').fill('Viktor examines the grimoire.');
  await viktor.el('stage-manual').click();
  await viktor.el('send').click();
  await viktor.el('draft-area').waitFor({ state: 'hidden' });
  await refresh(dm);
  assert.equal(await dm.el('replies').locator('.reply').count(), 2);
  await dm.el('prepare-replies').click();
  const bundle = await dm.el('bundle').inputValue();
  assert.ok(bundle.includes('## George\n'));
  assert.ok(bundle.includes('## Viktor\n'));
  await dm.el('bundle').fill(bundle + '\n\nDM context: resolve George first.');
  await dm.el('insert-bundle').click();
  assert.ok((await dm.page.locator('#prompt-textarea').innerText()).includes('DM context: resolve George first.'));
  assert.equal(await dm.page.evaluate(() => window.submits), 0);
  await dm.el('mark-reviewed').click();
  await refresh(dm);
  assert.equal(await dm.el('replies').locator('input:checked').count(), 0);
  pass('full DM → two players → DM loop, grouped editable text and local review marks');

  // A new public scene must not silently retarget an already staged player response.
  await response(george, 'A later thought about the first scene.');
  const firstScene = await george.el('target').inputValue();
  await dm.el('source').fill('[PLAYER_VIEW]The door slams shut.[/PLAYER_VIEW]');
  await dm.el('stage-manual').click(); await dm.el('send').click();
  await dm.el('draft-area').waitFor({ state: 'hidden' });
  await refresh(george);
  const options = await george.el('scenes').locator('option').evaluateAll(items => items.map(i => i.value));
  assert.equal(options.length, 2);
  await george.el('scenes').selectOption(options[0]);
  await george.page.waitForTimeout(300);
  assert.equal(await george.el('target').inputValue(), firstScene);
  await george.el('send').click(); await george.el('draft-area').waitFor({ state: 'hidden' });
  await dm.el('scenes').selectOption(firstScene); await dm.page.waitForTimeout(300);
  assert.equal(await dm.el('replies').locator('.reply').count(), 3);
  pass('scene changes never silently retarget a staged reply; late replies reach original scene');

  await response(george, 'A new response after the previous reply was sent.');
  assert.equal(await george.el('target').inputValue(), options[0]);
  await george.el('discard').click();
  pass('a successful reply clears the one-use default target for the next draft');

  await response(george, 'A draft that was sent from the other tab.');
  const synchronizedScene = Number(await george.el('target').inputValue());
  const pendingDraft = {
    kind: 'reply', text: 'A draft that was sent from the other tab.', scene_id: synchronizedScene,
    pending: { request_id: 'second-tab-request', scene_id: synchronizedScene, text: 'A draft that was sent from the other tab.' }
  };
  await george.page.evaluate(({ key, config, selected, draft }) => {
    window.simulateGMRemote(key, { config, selected, draft });
  }, { key: 'tableforge.v1.chat.george-chat', config: george.connection, selected: synchronizedScene, draft: pendingDraft });
  assert.equal(await george.el('send').textContent(), 'Retry send');
  await george.page.evaluate(({ key, config, selected }) => {
    window.simulateGMRemote(key, { config, selected });
  }, { key: 'tableforge.v1.chat.george-chat', config: george.connection, selected: synchronizedScene });
  await george.el('draft-area').waitFor({ state: 'hidden' });
  pass('a second tab adopts pending and completed draft state without a stale retry');

  await dm.el('source').fill('[PLAYER_VIEW]Outer [PLAYER_VIEW]Nested[/PLAYER_VIEW][/PLAYER_VIEW]');
  await dm.el('stage-manual').click();
  assert.ok((await dm.el('status').textContent()).includes('Nested'));
  assert.equal(await dm.el('draft-area').isVisible(), false);
  await dm.el('source').fill('[PLAYER_VIEW]unfinished');
  await dm.el('stage-manual').click();
  assert.ok((await dm.el('status').textContent()).includes('incomplete'));
  pass('malformed and incomplete tags fail closed');

  await dm.page.evaluate(() => {
    window.originalExecCommand = document.execCommand;
    window.installPasteHandler = execResult => {
      document.execCommand = () => execResult;
      document.getElementById('prompt-textarea').addEventListener('paste', event => {
        event.preventDefault();
        const text = event.clipboardData.getData('text/plain').replace(/^\n+/, '');
        for (const value of text.split(/\n{2,}/)) {
          const paragraph = document.createElement('p'); paragraph.textContent = value;
          event.currentTarget.append(paragraph);
        }
      }, { once: true });
    };
    window.installPasteHandler(false);
  });
  await dm.el('bundle').fill('Paste fallback one.\n\nPaste fallback two.');
  await dm.el('insert-bundle').click();
  await dm.page.locator('#prompt-textarea p', { hasText: 'Paste fallback two.' }).waitFor();
  let pastedParagraphs = await dm.page.locator('#prompt-textarea > p').allTextContents();
  assert.deepEqual(pastedParagraphs.slice(-2), ['Paste fallback one.', 'Paste fallback two.']);

  await dm.page.evaluate(() => window.installPasteHandler(true));
  await dm.el('bundle').fill('Verification fallback one.\n\nVerification fallback two.');
  await dm.el('insert-bundle').click();
  await dm.page.locator('#prompt-textarea p', { hasText: 'Verification fallback two.' }).waitFor();
  pastedParagraphs = await dm.page.locator('#prompt-textarea > p').allTextContents();
  assert.deepEqual(pastedParagraphs.slice(-2), ['Verification fallback one.', 'Verification fallback two.']);
  assert.equal(await dm.page.evaluate(() => window.submits), 0);
  await dm.page.evaluate(() => { document.execCommand = window.originalExecCommand; });
  pass('synthetic paste preserves paragraphs after insertText failure or failed verification');

  await george.page.locator('#prompt-textarea').evaluate(el => el.remove());
  await george.el('insert-scene').click();
  assert.ok((await george.el('status').textContent()).includes('not found'));
  await george.el('copy-scene').click(); await george.page.waitForTimeout(50);
  assert.ok(george.clipboard().includes('The door slams shut.'));
  pass('missing composer leaves copy/paste fallback usable');

  await viktor.page.evaluate(() => {
    document.getElementById('prompt-textarea').remove();
    const el = document.createElement('textarea'); el.id = 'prompt-textarea'; el.value = 'Keep this note.';
    document.getElementById('chat-form').prepend(el);
  });
  await viktor.el('insert-scene').click();
  assert.ok((await viktor.page.locator('#prompt-textarea').inputValue()).startsWith('Keep this note.'));
  assert.equal(await viktor.page.evaluate(() => window.submits), 0);
  await viktor.page.evaluate(() => { const b = document.createElement('button'); b.dataset.testid = 'stop-button'; document.body.append(b); });
  await response(viktor, 'Still generating...');
  assert.ok((await viktor.el('status').textContent()).includes('Wait for ChatGPT'));
  pass('textarea adapter preserves notes; response selection blocked during generation');

  await george.page.evaluate(() => history.pushState({}, '', '/c/unbound-chat'));
  await george.page.waitForTimeout(1200);
  assert.equal(await george.el('connected').isVisible(), false);
  assert.equal(await george.page.locator('.tf-response-action').count(), 0);
  assert.equal(await george.el('key').inputValue(), '');
  await george.page.evaluate(() => history.pushState({}, '', '/c/george-chat'));
  await george.el('connected').waitFor({ state: 'visible' });
  pass('SPA navigation disconnects unbound chats and restores the original binding');

  george.respondNext(400, JSON.stringify({ error: 'Invalid JSON.' }));
  await george.el('refresh').click();
  await george.page.waitForFunction(() => document.querySelector('#tableforge-client').shadowRoot.getElementById('status').textContent === 'Invalid JSON.');
  george.respondNext(502, '<html>Bad Gateway</html>');
  await george.el('refresh').click();
  await george.page.waitForFunction(() => document.querySelector('#tableforge-client').shadowRoot.getElementById('status').textContent.includes('HTTP 502 without JSON'));
  await george.el('refresh').click();
  await george.page.waitForFunction(() => document.querySelector('#tableforge-client').shadowRoot.getElementById('status').textContent.startsWith('Connected.'));
  pass('relay JSON errors remain intact and non-JSON errors include HTTP status');

  const latestScene = await george.el('scenes').locator('option').first().getAttribute('value');
  await george.el('scenes').evaluate(select => select.add(new Option('#999999 · removed scene', '999999')));
  await george.el('scenes').selectOption('999999');
  await george.page.waitForFunction(expected => document.querySelector('#tableforge-client').shadowRoot.getElementById('scenes').value === expected, latestScene);
  assert.equal(await george.el('scene-text').textContent(), 'The door slams shut.');
  pass('missing selected scene clears the stale selection and loads the latest scene');

  await george.el('settings').evaluate(settings => { settings.open = true; });
  await george.el('key').fill('incorrect-passphrase');
  await george.el('connect').click();
  await george.page.waitForFunction(() => document.querySelector('#tableforge-client').shadowRoot.getElementById('status').textContent.includes('incorrect'));
  assert.equal(await george.el('connected').isVisible(), false);
  assert.equal(await george.el('settings').evaluate(settings => settings.open), true);
  const requestsAfterAuthFailure = george.requestCount();
  await george.page.waitForTimeout(6000);
  assert.equal(george.requestCount(), requestsAfterAuthFailure);
  await george.el('key').fill(george.connection.key);
  await george.el('connect').click();
  await george.el('connected').waitFor({ state: 'visible' });
  pass('authentication failure hides stale state, opens settings, and stops polling until reconnect');

  await george.el('close').click();
  await dm.el('source').fill('[PLAYER_VIEW]A distant bell rings.[/PLAYER_VIEW]');
  await dm.el('stage-manual').click();
  await dm.el('send').click();
  await dm.el('draft-area').waitFor({ state: 'hidden' });
  await george.el('refresh').evaluate(button => button.click());
  await george.el('attention').waitFor({ state: 'visible' });
  assert.equal(await george.el('attention').textContent(), '1');
  assert.ok((await george.el('launcher').getAttribute('title')).includes('1 new TableForge update'));
  await george.el('launcher').click();
  assert.equal(await george.el('attention').isVisible(), false);
  pass('a new scene shows a launcher badge while the player panel is closed');

  await refresh(dm);
  await dm.el('close').click();
  await response(george, 'George listens for another bell.');
  await george.el('send').click();
  await george.el('draft-area').waitFor({ state: 'hidden' });
  await dm.el('refresh').evaluate(button => button.click());
  await dm.el('attention').waitFor({ state: 'visible' });
  assert.equal(await dm.el('attention').textContent(), '1');
  await dm.el('launcher').click();
  assert.equal(await dm.el('attention').isVisible(), false);
  pass('a new player reply shows a launcher badge while the DM panel is closed');

  assert.deepEqual(errors, []);
  fs.mkdirSync(path.join(project, 'test-output'), { recursive: true });
  await dm.page.screenshot({ path: path.join(project, 'test-output', 'tableforge-dm.png'), fullPage: true });
  pass('no browser errors; fixture screenshot saved');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  child.kill();
  fs.rmSync(tmp, { recursive: true, force: true });
});
