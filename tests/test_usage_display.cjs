const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');

// Exercise the usage formatter used by Options and the Play Screen sidebar.
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const start=source.indexOf('  const tokenLabel =');
const end=source.indexOf('  const showRuntime =',start);
assert.ok(start>=0&&end>start);
const context=vm.createContext({Intl,Number});
vm.runInContext(source.slice(start,end)+'this.usageLine=usageLine;this.imageUsageLine=imageUsageLine;',context);

test('complete usage displays its total estimate',()=>{
  assert.equal(context.usageLine({totalTokens:120,estimatedCostUsd:.0004,unpricedRequests:0}),
    '120 tokens · ≈$0.0004');
});

test('an unpriced retry retains the known subtotal without claiming a complete cost',()=>{
  const line=context.usageLine({totalTokens:120,estimatedCostUsd:null,knownEstimatedCostUsd:.0004,unpricedRequests:1});
  assert.equal(line,'120 tokens · Cost unavailable · known estimate ≈$0.0004 · 1 request without cost data');
});

test('unknown costs with no known subtotal and older server fields stay unavailable',()=>{
  for(const known of [undefined,0]){
    const line=context.usageLine({totalTokens:0,estimatedCostUsd:null,knownEstimatedCostUsd:known,unpricedRequests:2});
    assert.equal(line,'0 tokens · Cost unavailable · 2 requests without cost data');
    assert.doesNotMatch(line,/≈\$0\.0000/);
  }
});

test('image usage keeps its separate known-cost summary',()=>{
  assert.equal(context.imageUsageLine({generated:1,requests:2,knownEstimatedCostUsd:.2,unpricedRequests:1}),
    '1 image / 2 requests · Known estimated cost: ≈$0.2000 · 1 request without cost data');
});
