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

## Enable the Laya service editor on Kilo

After deploying the TableForge update, run this once on Kilo between requests.

```bash
sudo bash /opt/tableforge/repo/deploy/laya/install-routing-settings.sh
```

The installer backs up the router source, gives the Laya and TableForge service accounts access to the shared routing settings file, and briefly restarts the Laya router. It verifies the new read-only settings endpoint and restores the previous source if setup fails.

Open the [TableForge routing editor](../kilo/README.md#edit-ai-routing) and choose **Laya service defaults**. Pick a model and reasoning effort for each Cheap, Standard, or Heavy tier. **Use service default** takes the model from the Laya systemd environment, and **Let Laya choose the effort** uses the Light, Normal, and Hard mapping above. Saved choices apply to every client on the next routing request.

**TableForge routing** shows this app's own overrides. An explicit TableForge model or effort takes priority for its requests. Use `--scope laya` or `--scope tableforge` to open a specific menu directly.

The optional router tests use the Laya FastAPI environment and mock the classifier calls. Run from the repository root with `python -m unittest discover -s deploy/laya`.
