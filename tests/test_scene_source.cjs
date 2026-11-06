const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const markdown=require('../web/js/markdown.js');

const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const start=source.indexOf('  const openSceneSource=');
const end=source.indexOf('\n  };',start)+5;
assert.ok(start>=0&&end>start);
function dialog(messages){
  const body={};
  const calls=[];
  const context=vm.createContext({state:{save:{messages}},$:()=>body,
    TableForgeMarkdown:markdown,modal:(html,size)=>calls.push({html,size})});
  vm.runInContext(source.slice(start,end)+'\nthis.open=openSceneSource;',context);
  return {body,calls,open:context.open};
}

test('source dialog shows the original narration even after newer beats',()=>{
  const t=dialog([{id:1,kind:'ai',body:'The **old road**.'},{id:2,kind:'ai',body:'A later scene.'}]);
  t.open(1);
  assert.equal(t.calls.length,1);
  assert.equal(t.calls[0].size,'wide');
  assert.match(t.calls[0].html,/Source narration/);
  assert.match(t.calls[0].html,/data-close/);
  assert.match(t.body.innerHTML,/<strong>old road<\/strong>/);
  assert.doesNotMatch(t.body.innerHTML,/later scene/);
});

test('source narration renders raw HTML safely',()=>{
  const t=dialog([{id:1,kind:'ai',body:'<img src=x onerror=alert(1)>'}]);
  t.open(1);
  assert.doesNotMatch(t.body.innerHTML,/<img/);
  assert.match(t.body.innerHTML,/&lt;img/);
});

test('missing or non-narration source gives visible feedback',()=>{
  for(const messages of [[],[{id:1,kind:'player',body:'Not narration'}]]){
    const t=dialog(messages);t.open(1);
    assert.equal(t.body.textContent,'The source narration is unavailable in this save.');
  }
});
