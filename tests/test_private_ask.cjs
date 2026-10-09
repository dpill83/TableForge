const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const markdown=require('../web/js/markdown.js');

// Exercise the actual dialog renderer and asynchronous refresh guards.
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const start=source.indexOf('  let askDialog=null;');
const end=source.indexOf('  // Presence comes from the server',start);
assert.ok(start>=0&&end>start);
function dialog(){
  const element=tag=>({tag,children:[],textContent:'',scrollHeight:0,scrollTop:0,clientHeight:0,
    append(...items){this.children.push(...items);},replaceChildren(){this.children=[];}});
  const elements={pilotThread:element('div'),pilotSend:element('button'),pilotAsk:element('textarea'),askHistoryError:element('div')};
  const state={pilot:true,identity:'dan',save:{save:{id:'save'},activity:{}}};
  let resolve,reject;
  const calls=[];
  const context=vm.createContext({state,Date,Number,encodeURIComponent,
    document:{createElement:element},$:id=>elements[id],TableForgeMarkdown:markdown,
    request:path=>{calls.push(path);return new Promise((yes,no)=>{resolve=yes;reject=no;});},
  });
  vm.runInContext(source.slice(start,end)+`
    this.open=messages=>askDialog={saveId:'save',playerId:'dan',thread:$('pilotThread'),messages,loaded:true,loading:false,revision:0};
    this.render=renderAskThread;this.refresh=refreshAskThread;
  `,context);
  return {state,elements,calls,open:context.open,render:context.render,refresh:context.refresh,
    resolve:value=>resolve(value),reject:value=>reject(value)};
}

test('Ask rows show player names, local time, and the full date tooltip for both sides',()=>{
  const t=dialog();
  const stamp='2026-10-06T05:00:00+00:00';
  t.open([{name:'Dan',body:'My question',created_at:stamp},{name:'AI-DM',body:'An **answer**',created_at:stamp}]);
  t.render();
  assert.equal(t.elements.pilotThread.children.length,2);
  for(const [index,name] of ['Dan','AI-DM'].entries()){
    const header=t.elements.pilotThread.children[index].children[0];
    assert.equal(header.children[0].textContent,name);
    const time=header.children[1];
    assert.equal(time.tag,'time');assert.equal(time.dateTime,stamp);
    assert.equal(time.textContent,new Date(stamp).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}));
    assert.equal(time.title,new Date(stamp).toLocaleString());
  }
  assert.match(t.elements.pilotThread.children[1].children[1].innerHTML,/<strong>answer<\/strong>/);
});

test('switching profile or disabling Pilot Mode clears the visible private thread',()=>{
  for(const change of ['identity','pilot','save']){
    const t=dialog();t.open([{name:'Dan',body:'Private',created_at:'invalid'}]);t.render();
    t.elements.pilotAsk.value='Private unsent draft';
    if(change==='identity')t.state.identity='dani';else if(change==='pilot')t.state.pilot=false;else t.state.save=null;
    t.render();assert.equal(t.elements.pilotThread.children.length,0);
    assert.equal(t.elements.pilotAsk.value,'');
    assert.equal(t.elements.pilotSend.disabled,true);
  }
});

test('a late history response cannot populate a different profile or reopened window',async()=>{
  for(const change of ['identity','reopen']){
    const t=dialog();const original=t.open([]);const pending=t.refresh();
    assert.equal(t.calls[0],'saves/save/ask?playerId=dan&pilot=true');
    if(change==='identity')t.state.identity='dani';else t.open([]);
    t.resolve({pilot:[{name:'Dan',body:'Private'}]});await pending;
    assert.equal(original.messages.length,0);
    assert.equal(t.elements.pilotThread.children.length,0);
  }
});

test('an older poll cannot overwrite a freshly submitted question and reply',async()=>{
  const t=dialog();const current=t.open([]);const pending=t.refresh();
  current.revision++;current.messages=[{name:'Dan',body:'New question'},{name:'AI-DM',body:'New reply'}];
  t.resolve({pilot:[]});await pending;
  assert.equal(current.messages.length,2);
});

test('history load failures are visible and can be retried',async()=>{
  const t=dialog();const current=t.open([]);const pending=t.refresh();
  t.reject(Error('Connection lost'));await pending;
  assert.equal(t.elements.askHistoryError.textContent,'Connection lost');
  assert.equal(current.loading,false);
  const retry=t.refresh();t.resolve({pilot:[]});await retry;
  assert.equal(t.elements.askHistoryError.textContent,'');
  assert.equal(current.loaded,true);
});

test('Send waits for history loading so failure recovery can identify new questions',async()=>{
  const t=dialog();const current=t.open([]);current.loaded=false;
  t.render();assert.equal(t.elements.pilotSend.disabled,true);
  const pending=t.refresh();t.resolve({pilot:[]});await pending;
  assert.equal(t.elements.pilotSend.disabled,false);
});
