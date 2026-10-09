/* Audit metadata only. Full payloads are optional, temporary Pilot captures. */
const TableForgeRequestLog = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const available = value => value == null ? 'Unavailable' : String(value);
  const flag = value => value == null ? 'Unknown' : String(value);
  const cost = value => typeof value === 'number' && Number.isFinite(value)
    ? `$${value.toFixed(8).replace(/0+$/, '').replace(/\.$/, '.00')} estimated` : 'Cost unavailable';
  const render = (entry, when = value => value || 'Unavailable') => {
    const route = entry.routing;
    const tableforgeFallback = route?.tableforgeRouterFallbackUsed ?? route?.fallback;
    const tableforgeReason = route?.tableforgeRouterFallbackReason ?? route?.fallbackReason;
    const internalFallback = route?.routerInternalFallbackUsed;
    const tier = ['cheap', 'standard', 'heavy'].includes(route?.tier) ? route.tier : null;
    const routeLabel = route?.enabled === false
      ? 'Routing disabled' : tier || (tableforgeFallback === true ? 'No router decision'
        : route?.enabled ? 'Routed' : 'Routing unknown');
    const badge = tier || 'unknown';
    const fallbackLabel = [internalFallback === true ? 'Laya/router fallback' : '',
      tableforgeFallback === true ? 'TableForge router fallback' : ''].filter(Boolean).join(' · ');
    const purpose = {advance: 'Table advance', ask: 'Pilot Ask', summary: 'Campaign summary'}[entry.purpose] || entry.purpose;
    const row = (label, value) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`;
    const scores = route?.scores && Object.entries(route.scores)
      .filter(([key, value]) => ['cheap', 'standard', 'heavy'].includes(key) && typeof value === 'number' && Number.isFinite(value))
      .map(([key, value]) => `${key}: ${value}`).join(' · ');
    const requested = entry.requestedModel ?? (entry.legacy ? null : entry.model);
    return `<details class="context-message ai-request" data-request-id="${esc(entry.id)}">
      <summary><strong>${esc(purpose)}</strong> · <span class="route-badge route-${badge}">${esc(routeLabel)}</span> · ${esc(entry.status)} · ${esc(requested || entry.model || 'Model unavailable')}${route?.requestedEffort ? ` · ${esc(route.requestedEffort)} effort` : ''}
        ${fallbackLabel ? `<span class="route-badge route-fallback">${esc(fallbackLabel)}</span>` : ''}
        <span class="request-meta">${esc(entry.provider)} · Session ${esc(entry.sessionNumber ?? '?')} · ${esc(when(entry.startedAt))} · Input ${esc(available(entry.inputTokens))} / Output ${esc(available(entry.outputTokens))} / Total ${esc(available(entry.totalTokens))} tokens · ${esc(cost(entry.estimatedCostUsd))}</span>
      </summary>
      <div class="request-details"><dl>
        ${row('Purpose', available(entry.purpose))}
        ${row('Router enabled', flag(route?.enabled))}
        ${row('Router contacted', flag(route?.routerContacted))}
        ${row('Selected tier', available(route?.tier))}
        ${row('Router-selected model', available(route?.model))}
        ${row('Router-selected reasoning effort', route?.routerSelectedEffort ?? 'Not recorded / supplied')}
        ${row('Router reason', available(route?.reason))}
        ${row('Router scores', scores || 'Unavailable')}
        ${row('Laya/router fallback', flag(internalFallback))}
        ${row('Laya/router fallback reason', available(route?.routerInternalFallbackReason))}
        ${row('TableForge router fallback', flag(tableforgeFallback))}
        ${row('TableForge router fallback reason', available(tableforgeReason))}
        ${row('Configured default / fallback model', available(entry.configuredModel))}
        ${row(entry.provider === 'mock' ? 'Mock request model' : 'Model requested from OpenAI', available(requested))}
        ${row('Configured default reasoning effort', route?.configuredEffort ?? 'Not recorded / configured')}
        ${row('Reasoning effort requested from OpenAI', route?.requestedEffort ?? (route?.effortSource === 'provider default' ? 'Provider default (not sent)' : 'Not recorded / sent'))}
        ${row('Reasoning effort source', route?.effortSource ?? 'Not recorded')}
        ${row('Router effort reason', route?.effortReason ?? 'Not recorded / supplied')}
        ${row('Router effort scores', route?.effortScores ? Object.entries(route.effortScores).map(([key, value]) => `${key}: ${value}`).join(' · ') : 'Not recorded / supplied')}
        ${row('Router effort fallback', flag(route?.effortFallbackUsed))}
        ${route?.effortNotice ? row('Reasoning effort note', route.effortNotice) : ''}
        ${row('Model reported by OpenAI', available(entry.reportedModel))}
        ${row('OpenAI service tier', available(entry.serviceTier))}
        ${entry.legacy ? row('Metered model (legacy)', available(entry.model)) : ''}
        ${row('Input tokens', available(entry.inputTokens))}
        ${row('Cached input tokens (included in input)', available(entry.cachedInputTokens))}
        ${row('Cache write tokens (included in input)', available(entry.cacheWriteTokens))}
        ${row('Output tokens', available(entry.outputTokens))}
        ${row('Reasoning tokens (included in output)', available(entry.reasoningTokens))}
        ${row('Total tokens', available(entry.totalTokens))}
        ${row('Estimated request cost', cost(entry.estimatedCostUsd))}
        ${row('Finished', entry.finishedAt ? when(entry.finishedAt) : 'Unavailable')}
      </dl>
      <p class="muted">Output tokens include billed reasoning; reasoning tokens are not added again. Each attempt, including a retry or failed response with reported usage, has its own cost.</p>
      ${fallbackLabel ? '<p class="request-fallback">Fallback layer is separate from the provider generation status above.</p>' : ''}
      ${route && (route.routerContacted == null || internalFallback == null) ? '<p class="muted">Unknown means this fallback layer or router contact status was not recorded or reported.</p>' : ''}
      ${entry.legacy ? '<p class="muted">Older record: routing and distinct provider models were not recorded.</p>' : ''}
      ${entry.error ? `<p class="binding-issue" role="alert">${esc(entry.error)}</p>` : ''}
      ${entry.payload ? `<details class="request-payload"><summary>Temporary provider request payload</summary><pre>${esc(entry.payload)}</pre></details>` : '<p class="muted">Full payload unavailable (temporary capture only).</p>'}
      </div></details>`;
  };
  return {render};
})();

if (typeof module !== 'undefined') module.exports = TableForgeRequestLog;
