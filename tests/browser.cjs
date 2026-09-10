/* Browser integration test: real userscript + real relay, ChatGPT DOM fixtures and GM shim.
   Run: npm install && npx playwright install chromium && npm run test:browser
   No ChatGPT account or API key is used. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
let playwright;
try { playwright = require('playwright'); }
catch { playwright = require(require.resolve('playwright', { paths: [process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES].filter(Boolean) })); }
const project = path.resolve(__dirname, '..');
const script = fs.readFileSync(path.join(project, 'tableforge.user.js'), 'utf8');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'tableforge-test-'));
const child = spawn('python3', ['-u', '-c', `
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
  browser = await playwright.chromium.launch({ headless: true });
  async function client(index, id) {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    const values = {};
    let clipboard = '';
    let loseNextPost = false;
    const actor = boot.table.credentials[index];
    const connection = { url, code: boot.table.table_code, key: actor.key };
    values['tableforge.v1.chat.' + id] = { config: connection };
    await page.exposeFunction('gmSave', (key, value) => { values[key] = value; });
    await page.exposeFunction('gmDelete', key => { delete values[key]; });
    await page.exposeFunction('gmCopy', text => { clipboard = text; });
    await page.exposeFunction('gmRequest', async details => {
      const response = await fetch(details.url, { method: details.method, headers: details.headers, body: details.data });
      const responseText = await response.text();
      if (loseNextPost && details.method === 'POST') { loseNextPost = false; return { timeout: true }; }
      return { status: response.status, responseText, finalUrl: details.url };
    });
    await page.route('https://chatgpt.com/**', r => r.fulfill({ contentType: 'text/html', body: fixture }));
    async function inject() {
      await page.evaluate(v => {
        window.GM_getValue = (k, fallback) => structuredClone(v[k] ?? fallback);
        window.GM_setValue = (k, value) => { v[k] = structuredClone(value); window.gmSave(k, value); };
        window.GM_deleteValue = k => { delete v[k]; window.gmDelete(k); };
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

  await dm.el('source').fill('[PLAYER_VIEW]Outer [PLAYER_VIEW]Nested[/PLAYER_VIEW][/PLAYER_VIEW]');
  await dm.el('stage-manual').click();
  assert.ok((await dm.el('status').textContent()).includes('Nested'));
  assert.equal(await dm.el('draft-area').isVisible(), false);
  await dm.el('source').fill('[PLAYER_VIEW]unfinished');
  await dm.el('stage-manual').click();
  assert.ok((await dm.el('status').textContent()).includes('incomplete'));
  pass('malformed and incomplete tags fail closed');

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

  assert.deepEqual(errors, []);
  fs.mkdirSync(path.join(project, 'test-output'), { recursive: true });
  await dm.page.screenshot({ path: path.join(project, 'test-output', 'tableforge-dm.png'), fullPage: true });
  pass('no browser errors; fixture screenshot saved');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  child.kill();
  fs.rmSync(tmp, { recursive: true, force: true });
});
