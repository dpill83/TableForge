# TableForge

A Tampermonkey client and a small persistent relay for collaborative D&D using **existing ChatGPT conversations**. No OpenAI API key, Discord bot, extra website, or campaign manager is required.

Every handoff is human-controlled. Selecting an assistant response opens an editable draft. Sharing sends only that draft to the relay. Inserting incoming text appends it to ChatGPT's composer; **TableForge never submits the composer**.

## 1. Start the relay

Requires Python 3.10 or newer. The server has no third-party dependencies.

Extract this folder and run:

```bash
cd tableforge
python3 server.py create --name "Waterdeep" --players "George" "Viktor" "Ethereal"
python3 server.py serve
```

The first command prints the table code, an **AI-DM key**, and a different key for each named player. Keep these somewhere private; keys are printed once and stored only as hashes in the database. Give each participant the relay URL, table code, and **their own key**. Do not distribute the DM key to players.

The second command starts the relay at `http://127.0.0.1:8787`. The SQLite database is created in this folder. Keep using the same database when restarting. Do not run `create` again to resume the same table.

For participants on other computers, place the relay behind your HTTPS reverse proxy, forwarding the entire path to `http://127.0.0.1:8787`. Use a dedicated hostname such as `https://tableforge.example.com`. That hostname must be reachable from every participant's computer. Do not use `localhost` on players' computers unless each has a tunnel to the actual relay.

The userscript accepts HTTP only on loopback addresses. Shared relays require HTTPS. It uses Tampermonkey's cross-origin requests, so the relay does not need permissive CORS or access to ChatGPT cookies. Configure the proxy to preserve `Authorization` and avoid redirects on API routes. Use its normal connection/request limits; this small standard-library HTTP server is intended for a trusted small group behind a proxy, not direct public exposure.

For an existing Caddy installation, the complete site block is:

```caddyfile
tableforge.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

Replace the hostname and configure DNS/TLS as appropriate for your proxy. Do not publish the sample hostname literally. `GET /health` is an unauthenticated health check.

## 2. Install the client

1. Install or open Tampermonkey in your browser.
2. Choose **Create a new script**, replace the template with all of `tableforge.user.js`, and save. Alternatively, open an HTTPS URL serving that file as a userscript.
3. Reload ChatGPT and open the **existing conversation** used by that participant. The script intentionally does not bind a blank/new chat.
4. Click **TableForge** in the lower-right corner. Enter the relay URL, table code, and your participant key, then **Connect this chat**.
5. If Tampermonkey asks to allow a connection to your relay, allow that hostname. The role and player name come from the key automatically.

The connection is saved separately for each ChatGPT conversation. DM and player chats can be open in the same browser without sharing their connection settings. Navigation to an unbound chat disconnects the panel until you bind it. Use one active tab per bound conversation: concurrent tabs for the same conversation share draft storage and are not coordinated.

If the script does not run at all, check that it is enabled and that your browser permits userscripts. Current browser-specific instructions are in the [Tampermonkey FAQ](https://www.tampermonkey.net/faq.php). Its network and storage APIs are documented in the [Tampermonkey documentation](https://www.tampermonkey.net/documentation.php).

## 3. Play one round

**AI-DM:** Ask the existing DM chat to put everything players may see inside these exact, case-sensitive tags:

```text
Keep private DM notes outside the player-view tags. Put only the narration,
dialogue, and information all players may know in a complete block:

[PLAYER_VIEW]
The characters enter a candlelit study. An open crimson book rests on the desk.
[/PLAYER_VIEW]
```

After generation finishes, click **Share PLAYER_VIEW** beside the chosen assistant response. Review or edit the extracted public text and click **Share scene**. Multiple complete sections are joined in order. Nested, unmatched, or incomplete tags stop extraction. Text outside the tags is excluded.

**Each player:** The new scene appears in the TableForge panel. Click **Insert scene** to append it to the player's existing ChatGPT composer. Edit or add context and submit it yourself. After the player AI responds, click **Send to Table** beside the chosen response, review the draft and target scene, and then click **Send to Table** inside the panel.

**AI-DM:** Select the scene in the panel. Player replies appear with names and checkboxes. Select the contributions you want, click **Prepare selected replies**, and edit the grouped text or add your own context. Click **Insert grouped replies** and submit in ChatGPT yourself. Once handled, use **Mark selected reviewed**. Inserting alone does not mark anything reviewed or delete any relay history.

You can start the next scene whenever you choose. There is no automatic wait for all players and no enforced turn order. Players see public scenes and their own replies; only the DM can see all player replies.

## Manual fallbacks and recovery

| Situation | What to do |
| --- | --- |
| Assistant response buttons disappear | Copy the response yourself, paste into **Manual fallback**, and click **Review pasted response**. DM text still needs the tags. |
| ChatGPT composer cannot be found or insertion fails | Use **Copy scene** or **Copy grouped replies**, then paste manually. If clipboard permission also fails, select and copy the visible text. |
| Rich-text insertion appears partial | Check the composer before retrying. Copy/paste the prepared text if necessary. Automatic insertion is never retried in the background. |
| Relay is unavailable | Your draft stays saved in Tampermonkey. Restore connectivity and click **Retry send** yourself. |
| A send times out after reaching the server | **Retry send** reuses the same request ID and exact payload, even after reload. The server returns the original receipt rather than storing a duplicate. |
| A newer scene appears while you are responding | The scene view stays on your current scene. A staged reply retains its target even if you change the view. Check **Reply to scene** before sending. |
| An old response needs a different scene | Change **Reply to scene** while reviewing, before the first send attempt. Pending retries are immutable. |
| A reply arrives late | It remains under its original scene. The scene menu shows reply counts, including late replies to recent scenes. |
| You need to reuse reviewed replies | Select their checkboxes again and prepare another group. Reviewed marks are local to the DM's browser and chat. |

Copying or inserting a scene remembers it as the default target for the next player draft. The target is always visible and editable before sending. TableForge cannot infer which scene an arbitrary historical assistant response belongs to; choose the right scene yourself.

Nothing is automatically transmitted on reload. Polling only reads relay state: normally every five seconds while the tab is visible, with backoff up to a minute after failures. **Refresh** allows a manual check. Messages are immutable in the relay; to correct a sent response, send a clearly labeled correction.

## Persistence and administration

The server stores tables, participant identities, public scenes, replies, and deduplication receipts in SQLite. It has no ChatGPT integration, model calls, transcript scraper, or background game logic. Conversation URLs and private assistant text outside extracted tags are not sent to it. Manually pasted sources, drafts, credentials, and review marks are stored in Tampermonkey for the bound chat; use **Disconnect** to remove that local state.

History is retained until you delete the database. The client lists the **50 most recent scenes**, while previously selected older scenes remain retrievable by ID through the API. All replies for the selected scene are returned. There is no campaign archive UI. Text is limited to 50,000 characters per message. Each key identifies its holder; TableForge does not independently verify who is using a shared or stolen key.

To replace a lost or disclosed key without losing history:

```bash
python3 server.py rotate-key --table YOUR_TABLE_CODE --name "George"
```

Use `"AI-DM"` for the DM key. The old key immediately stops working. Reconnect that participant's chat using the new key. Save any local draft first: changing the connection clears local drafts and review marks.

For another database location, put the option **before** the subcommand:

```bash
python3 server.py --db /path/to/tableforge.sqlite3 serve
```

Back up using SQLite's online backup API, or stop the server before copying the database. Do not copy only a live `.sqlite3` file while omitting its active WAL data. An optional Linux service template is included in `deploy/tableforge.service`. Adjust its user and paths before installing it. The database path used for table creation must match the service's path.

The userscript has `@connect *` because each host chooses its own relay URL. It makes requests only to the configured relay. You may replace `*` with your relay hostname for a narrower installation. Treat participant keys as passwords; drafts and relay messages are not end-to-end encrypted and can be read by the relay administrator.

## API contract

All table endpoints require `Authorization: Bearer PARTICIPANT_KEY`. Request and response bodies are JSON. Version is `1`. The client can be used with another backend implementing this contract.

| Method and endpoint | Access | Behavior |
| --- | --- | --- |
| `GET /health` | Public | Returns service name and `api_version`. |
| `GET /v1/tables/{code}/state` | Either key | Returns actor identity, table, 50 recent scene summaries, latest scene, and permitted replies. |
| `GET /v1/tables/{code}/state?scene_id=123` | Either key | Same response, selecting an exact scene belonging to that table. |
| `POST /v1/tables/{code}/scenes` | DM | Body: `{"request_id":"unique-request-id-123","text":"Public scene"}`. |
| `POST /v1/tables/{code}/replies` | Player | Body: `{"request_id":"unique-request-id-124","scene_id":123,"text":"Player action"}`. |

State response fields: `api_version`, `table: {code,name}`, `actor: {id,name,role}`, `scenes: [{id,preview,created_at,reply_count}]`, `scene: {id,table_code,text,created_at} | null`, `replies: [{id,scene_id,actor_id,name,text,created_at}]`. Scene summaries are newest first; replies are oldest first. Player counts and replies are restricted to that player's key.

Successful writes return `{id,kind,created_at,replayed}` plus `scene_id` for a reply. IDs are server-generated integers. Dates are UTC ISO 8601 strings. Reusing a request ID with the same payload returns the original receipt; different content returns `409`. IDs are scoped to the participant for deduplication. Errors use `{error:"message"}` with an appropriate non-2xx status. Table creation and key rotation are local CLI operations, not public API routes.

## Development and validation

```bash
node --test tests/client.test.cjs
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm install
npx playwright install chromium
npm run test:browser
```

Node is needed for the client helper tests, and Playwright is needed for browser tests. Neither is a runtime dependency of the client or relay. `tests/browser.cjs` is an integration harness for the actual userscript against a real local relay using controlled ChatGPT DOM fixtures and a Tampermonkey API shim. It is designed to exercise the complete round trip, privacy extraction, draft review, grouping, composer insertion, retry after a lost acknowledgement and reload, scene targeting, malformed tags, clipboard fallbacks, and SPA navigation. The Python suite covers permissions, table isolation, validation, concurrent retries, late replies, and restart persistence.

**Validation for this delivery:** all six Python integration tests and all six JavaScript helper tests passed. Both JavaScript files passed syntax checks. The browser harness could not run because Chromium was absent and the browser download timed out in the build environment. Therefore composer behavior, rendered panel layout, SPA navigation, and live Tampermonkey behavior remain unverified in a real browser.

These fixtures do **not** certify the current live ChatGPT DOM or the actual Tampermonkey permission flow. Make one live smoke-test round after installation. ChatGPT selectors are concentrated in `adapter` in the userscript. The rich composer adapter uses `execCommand('insertText')` where supported to preserve editor handling and undo; this is deprecated and may break, as described in [MDN's documentation](https://developer.mozilla.org/en-US/docs/Web/API/Document/execCommand). It checks insertion, reports failure, and leaves the manual copy/paste path available. There are no private ChatGPT API calls or stable DOM guarantees.

Licensed under MIT. See `LICENSE`.
