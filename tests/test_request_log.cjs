const assert = require('node:assert/strict');
const {test} = require('node:test');
const {render} = require('../web/js/request-log.js');

const entry = {
  id: 'test', purpose: 'advance', provider: 'openai', sessionNumber: 1, status: 'complete',
  configuredModel: 'default-model', requestedModel: 'requested-model', reportedModel: 'reported-snapshot',
  serviceTier: 'default', inputTokens: 100, outputTokens: 20, totalTokens: 120,
  estimatedCostUsd: 0.00002,
  routing: {enabled: true, tier: 'cheap', model: 'router-model', reason: 'Confidence threshold cleared',
    routerContacted: true, routerInternalFallbackUsed: false, routerInternalFallbackReason: null,
    tableforgeRouterFallbackUsed: false, tableforgeRouterFallbackReason: null,
    scores: {cheap: 0.49, standard: 0.42, heavy: 0.09}, fallback: false, fallbackReason: null}
};

test('compact collapsed entries have tier, status, token and cost summaries', () => {
  for (const tier of ['cheap', 'standard', 'heavy']) {
    const html = render({...entry, routing: {...entry.routing, tier}});
    assert.match(html, new RegExp(`route-${tier}`));
    assert.match(html, /complete/);
    assert.match(html, /Input 100 \/ Output 20 \/ Total 120 tokens/);
    assert.match(html, /\$0\.00002 estimated/);
    assert.doesNotMatch(html, /<details[^>]*\sopen[\s>]/);
    assert.doesNotMatch(html.split('</summary>')[0], /route-fallback/);
  }
});

test('router, requested, reported and configured models are separately labeled', () => {
  const html = render(entry);
  for (const [label, value] of [
    ['Router-selected model', 'router-model'], ['Model requested from OpenAI', 'requested-model'],
    ['Model reported by OpenAI', 'reported-snapshot'], ['Configured default / fallback model', 'default-model'],
    ['Router enabled', 'true'], ['Router contacted', 'true'], ['Laya/router fallback', 'false'],
    ['TableForge router fallback', 'false'], ['OpenAI service tier', 'default']
  ]) assert.ok(html.includes(`<dt>${label}</dt><dd>${value}</dd>`));
  assert.match(html, /cheap: 0\.49 · standard: 0\.42 · heavy: 0\.09/);
});

test('TableForge router fallback is distinct from successful generation', () => {
  const html = render({...entry, routing: {...entry.routing, fallback: true, tier: null, model: null,
    routerContacted: false, routerInternalFallbackUsed: null,
    tableforgeRouterFallbackUsed: true, tableforgeRouterFallbackReason: 'Router timed out'}});
  assert.match(html, /route-fallback/);
  assert.match(html, /TableForge router fallback/);
  assert.match(html.split('</summary>')[0], /No router decision/);
  assert.doesNotMatch(html.split('</summary>')[0], /Routed/);
  assert.match(html, /Router contacted<\/dt><dd>false/);
  assert.match(html, /Laya\/router fallback<\/dt><dd>Unknown/);
  assert.match(html, /complete/);
  assert.match(html, /Router timed out/);
  assert.doesNotMatch(html, /role="alert"/);
});

test('router-internal fallback retains the tier badge and gets its own indicator', () => {
  const reason = 'Laya unavailable, using safe fallback';
  const html = render({...entry, routing: {...entry.routing, routerInternalFallbackUsed: true,
    routerInternalFallbackReason: reason, reason}});
  const summary = html.split('</summary>')[0];
  assert.match(summary, /route-cheap/);
  assert.match(summary, /route-fallback[^>]*>Laya\/router fallback/);
  assert.doesNotMatch(summary, /TableForge router fallback/);
  assert.match(html, /Laya\/router fallback<\/dt><dd>true/);
  assert.match(html, /Laya\/router fallback reason<\/dt><dd>Laya unavailable, using safe fallback/);
  assert.match(html, /TableForge router fallback<\/dt><dd>false/);
  assert.doesNotMatch(html, /<dt>Fallback used<\/dt>/);
  assert.doesNotMatch(html, /role="alert"/);
});

test('legacy generic fallback is labeled TableForge while router-internal state stays unknown', () => {
  for (const fallback of [true, false]) {
    const html = render({...entry, routing: {enabled: true, fallback,
      fallbackReason: fallback ? 'Router unavailable' : null,
      reason: 'Laya unavailable, using safe fallback'}});
    assert.match(html, /Router contacted<\/dt><dd>Unknown/);
    assert.match(html, /Laya\/router fallback<\/dt><dd>Unknown/);
    assert.ok(html.includes(`TableForge router fallback</dt><dd>${fallback}`));
    const summary = html.split('</summary>')[0];
    assert.equal(summary.includes('route-fallback'), fallback);
    assert.doesNotMatch(summary, /Laya\/router fallback/);
    assert.doesNotMatch(html, /<dt>Fallback used<\/dt>/);
  }
});

test('explicit layer fields override legacy aliases for the compact indicator', () => {
  const html = render({...entry, routing: {...entry.routing, fallback: true}});
  assert.doesNotMatch(html.split('</summary>')[0], /route-fallback/);
  assert.match(html, /TableForge router fallback<\/dt><dd>false/);
  const both = render({...entry, routing: {...entry.routing,
    routerInternalFallbackUsed: true, tableforgeRouterFallbackUsed: true}});
  assert.match(both.split('</summary>')[0], /Laya\/router fallback · TableForge router fallback/);
});

test('disabled routing, missing model response, and unknown cost remain readable', () => {
  const html = render({...entry, routing: {enabled: false, fallback: false}, reportedModel: null, estimatedCostUsd: null});
  assert.match(html, /Routing disabled/);
  assert.match(html, /Model reported by OpenAI<\/dt><dd>Unavailable/);
  assert.match(html, /Cost unavailable/);
  assert.match(html, /Total 120 tokens/);
  assert.match(render({...entry, estimatedCostUsd: 0}), /\$0\.00 estimated/);
});

test('legacy records do not fabricate routes or reported models', () => {
  const html = render({id: 'old', legacy: true, purpose: 'summary', model: 'legacy-model', totalTokens: 15});
  assert.match(html, /Campaign summary/);
  assert.match(html, /Routing unknown/);
  assert.match(html, /Router enabled<\/dt><dd>Unknown/);
  assert.match(html, /Metered model \(legacy\)<\/dt><dd>legacy-model/);
  assert.match(html, /Model reported by OpenAI<\/dt><dd>Unavailable/);
  assert.match(html, /Full payload unavailable/);
});

test('untrusted routing, provider and payload strings are escaped', () => {
  const unsafe = '<img src=x onerror=alert(1)>';
  const html = render({...entry, id: unsafe, reportedModel: unsafe, error: unsafe, payload: unsafe,
    routing: {...entry.routing, tier: unsafe, reason: unsafe,
      routerInternalFallbackReason: unsafe, tableforgeRouterFallbackReason: unsafe}});
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  assert.match(html, /Temporary provider request payload/);
  assert.match(html, /role="alert"/);
});
