# Model tier and reasoning effort

This optional update is based on the inspected Kilo router. It keeps the existing
heavy >= 0.33 threshold and cheap >= 0.48 with a >= 0.05 lead over standard.
Model selection still defaults to standard when neither alternative qualifies.

| Tier | Light | Normal | Hard |
| --- | --- | --- | --- |
| Cheap | gpt-6-luna / low | gpt-6-luna / medium | gpt-6-luna / xhigh |
| Standard | gpt-6.1-sol / low | gpt-6.1-sol / medium | gpt-6.1-sol / xhigh |
| Heavy | gpt-6-astra / low | gpt-6-astra / medium | gpt-6-astra / xhigh |

The router sends two questions in one Laya request. The independent effort question
chooses the highest scoring Light/Normal/Hard category. A tied, missing, or invalid
effort answer uses Normal/medium and reports `effort_fallback_used: true` and a reason.
This effort fallback does not imply a model-tier or OpenAI generation failure.
An unavailable/invalid model classification retains the standard safe fallback,
reports router-internal fallback explicitly, and uses medium effort.
No prompts or exception bodies are logged or returned with failures.

The response adds `reasoning_effort`, `effortLevel`, `effort_reason`, `effort_scores`,
and `effort_fallback_used`. TableForge validates effort, sends `reasoning_effort` in
Chat Completions, and persists selected/requested effort and diagnostics in routing JSON.

## Applying on Kilo

Deploy the TableForge provider update to the actual host first. Old TableForge code
ignores router effort. These files have not been installed on the running router.

Between AI requests, back up `/opt/laya/router_service.py` to a new dated filename,
then copy both `router_service.py` and `router_policy.py` from this directory into
`/opt/laya/`. Preserve the existing virtual environment and service settings.
The optional `test_router_service.py` can be run with that virtual environment
before restarting; it mocks all Laya HTTP calls and covers all nine combinations.
Check the configured `LAYA_URL` if Laya runs at a different address; this bundle
retains the inspected router's LAN endpoint as its default.

Review `/etc/systemd/system/laya-router.service.d/override.conf`: if the models were
temporarily changed to Luna/Luna/Sol, restore the three model settings in
`override.conf.example` to activate the requested matrix. Preserve unrelated overrides.

Run `sudo systemctl daemon-reload` if the override changed, then
`sudo systemctl restart laya-router`. Confirm `/health` reports version `0.2.0`,
then check a synthetic routing request and the next real AI Request Log entry.
This restarts only the router, but requests made during restart can use TableForge's
configured fallback. No TableForge generations are required for a router smoke test.

Roll back by restoring the backed-up service source and original override and
restarting the router. Old router responses remain compatible with new TableForge.
