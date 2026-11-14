const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const section=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));

function client(pilot=false){
  const nodes={optionsGear:{},modalRoot:{replaceChildren(){clear();}}};
  const clear=()=>{for(const key of Object.keys(nodes))if(!['optionsGear','modalRoot'].includes(key))delete nodes[key];};
  let markup='',logOpened=0;
  const calls=[];
  const state={pilot,identity:'player',generating:false,updating:false,save:{
    save:{id:'save/id',name:'Our game'},sessions:[{number:3}],
    usage:{session:{totalTokens:12},save:{totalTokens:34,inputTokens:20,outputTokens:14},pricingUrl:'https://example.com/rates',pricingAsOf:'today'},
    imageUsage:{session:{label:'session images'},save:{label:'all images'}},
  }};
  const context=vm.createContext({state,$:id=>nodes[id],
    showRuntime:async()=>({}),esc:String,runtimeLabel:()=> 'Mock',
    usageLine:usage=>`${usage.totalTokens} tokens`,tokenLabel:String,imageUsageLine:usage=>usage.label,
    modal:html=>{clear();markup=html;for(const [,id] of html.matchAll(/id="([^"]+)"/g))nodes[id]={value:'',disabled:new RegExp(`id="${id}" disabled`).test(html)};},
    renderAINotificationOption(){},notify(error){throw error;},
    openAIRequestLog(){logOpened++;},update:async(action,payload)=>{calls.push({action,payload});return true;},
    show:async(screen)=>calls.push({screen}),
  });
  vm.runInContext(section('  const openEndSession=()=>{','  const field=')+
    section("  $('optionsGear').onclick=async()=>{","  document.addEventListener('change'"),context);
  return {state,nodes,calls,open:()=>nodes.optionsGear.onclick(),html:()=>markup,logOpened:()=>logOpened};
}

test('Options exposes public utilities and all usage details without Pilot controls',async()=>{
  const c=client();await c.open();
  assert.match(c.html(),/<h4>Preferences<\/h4>/);
  assert.match(c.html(),/<h4>Session<\/h4>/);
  assert.match(c.html(),/Our game · Session 3/);
  assert.match(c.html(),/href="\/api\/saves\/save%2Fid\/chat.md" download/);
  assert.match(c.html(),/12 tokens/);assert.match(c.html(),/34 tokens/);
  assert.match(c.html(),/20 input · 14 output/);
  assert.match(c.html(),/session images/);assert.match(c.html(),/all images/);
  assert.ok(c.nodes.aiMessageNotifications);
  assert.equal(c.nodes.endSession,undefined);assert.equal(c.nodes.aiRequestLog,undefined);
});

test('Pilot utilities bind each time Options opens and End Session requires confirmation',async()=>{
  const c=client(true);await c.open();
  assert.match(c.html(),/<h4>Advanced<\/h4>/);
  c.nodes.aiRequestLog.onclick();assert.equal(c.logOpened(),1);
  c.nodes.endSession.onclick();assert.equal(c.calls.length,0);
  c.nodes.sessionNote.value='We reached the gate.';
  await c.nodes.submitEndSession.onclick();
  assert.equal(c.calls[0].action,'end-session');
  assert.equal(c.calls[0].payload.playerId,'player');
  assert.equal(c.calls[0].payload.note,'We reached the gate.');
  assert.equal(c.calls[1].screen,'load');
  await c.open();assert.equal(typeof c.nodes.endSession.onclick,'function');
});

test('busy state and a later Pilot toggle cannot end a session from an old dialog',async()=>{
  const c=client(true);c.state.generating=true;await c.open();
  assert.equal(c.nodes.endSession.disabled,true);
  c.nodes.endSession.onclick();assert.equal(c.nodes.submitEndSession,undefined);
  c.state.generating=false;await c.open();c.nodes.endSession.onclick();
  c.state.pilot=false;await c.nodes.submitEndSession.onclick();
  assert.equal(c.calls.length,0);
});

test('Options without a save omits session-specific controls',async()=>{
  const c=client(true);c.state.save=null;await c.open();
  assert.ok(c.nodes.aiMessageNotifications);
  assert.doesNotMatch(c.html(),/Download Chat|End Session|AI Request Log|<h4>Session/);
});
