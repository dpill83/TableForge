const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const section=source.slice(source.indexOf('  let outcomeEditor='),source.indexOf("  $('combatRetry').onclick="));
function client(){
  const nodes={};const listeners={};let overlay={};
  const element=()=>({value:'',textContent:'',disabled:false,replaceChildren(){for(const key of Object.keys(nodes))if(!['modalRoot','combatOutcomeOpen','combatTakeover','correctCombat'].includes(key))delete nodes[key];},querySelector(){return overlay;}});
  for(const id of ['modalRoot','combatOutcomeOpen','combatTakeover','correctCombat'])nodes[id]=element();
  let saved={save:{id:'save',mode:'combat'},combat:{id:'fight',phase:'reporting',reporter_id:'p1',editor_token:'token',revision:1,draft:''},activity:{}};
  const state={save:structuredClone(saved),identity:'p1',generating:false};
  const calls=[];let gate=null,fail=false;
  const context=vm.createContext({state,$:id=>nodes[id],document:{addEventListener:(name,fn)=>listeners[name]=fn},setTimeout,clearTimeout,console,
    combatToken:()=> 'token',ownsCombat:()=>state.save.combat.phase==='reporting'&&state.save.combat.reporter_id==='p1'&&state.save.combat.editor_token==='token',
    newRequestId:()=> 'request',notify:()=>{},render:()=>{},
    modal:html=>{nodes.modalRoot.replaceChildren();for(const [,id] of html.matchAll(/id="([^"]+)"/g))nodes[id]=element();overlay={};},
    request:async(path,body)=>{
      calls.push({path,body:structuredClone(body)});
      if(!body)return structuredClone(saved);
      if(body.action==='draft'&&gate)await gate;
      if(fail)throw Error('offline');
      const h=saved.combat;
      if(h.editor_token!==body.editorToken||h.revision!==body.revision)throw Error('draft changed');
      if(path.endsWith('combat-outcome')){h.outcome=body.text;h.phase='complete';saved.save.mode='normal';}
      else{h.draft=body.text;h.revision++;if(body.action==='return'){h.phase='fighting';h.editor_token=null;}}
      return structuredClone(saved);
    },
  });
  vm.runInContext(section+'\nthis.open=openCombatOutcome;this.flush=saveOutcomeDraft;this.editor=()=>outcomeEditor;',context);
  const input=text=>{nodes.combatOutcome.value=text;nodes.combatOutcome.oninput();};
  return {context,state,nodes,calls,listeners,input,setGate:value=>gate=value,setFail:value=>fail=value,saved:()=>saved};
}

test('autosave shows success; Close and Escape preserve reporting and saved text',async()=>{
  const c=client();c.context.open();c.input('We won; the door is still shut.');
  await c.context.flush();assert.equal(c.nodes.combatOutcomeSave.textContent,'Saved');
  c.nodes.closeCombatOutcome.onclick();await c.context.flush();assert.equal(c.nodes.combatOutcomeDialog,undefined);
  assert.equal(c.saved().combat.phase,'reporting');
  c.context.open();assert.equal(c.nodes.combatOutcome.value,'We won; the door is still shut.');
  c.listeners.keydown({key:'Escape',preventDefault(){}});assert.equal(c.nodes.combatOutcomeDialog,undefined);
});

test('submit waits for autosave and sends the latest edit exactly once',async()=>{
  const c=client();c.context.open();let release;
  c.setGate(new Promise(resolve=>release=resolve));c.input('First draft.');
  const saving=c.context.flush();c.input('Latest edit: the ogre fled, loot undecided.');
  const sending=c.nodes.submitCombatOutcome.onclick();
  assert.equal(c.nodes.combatOutcome.disabled,true);
  c.setGate(null);release();await Promise.all([saving,sending]);
  const submissions=c.calls.filter(call=>call.path.endsWith('combat-outcome'));
  assert.equal(submissions.length,1);assert.equal(submissions[0].body.text,'Latest edit: the ogre fled, loot undecided.');
  assert.equal(c.saved().combat.outcome,submissions[0].body.text);
});

test('autosave failure is visible and prevents submission until saving succeeds',async()=>{
  const c=client();c.context.open();c.input('We escaped.');c.setFail(true);
  assert.equal(await c.context.flush(),false);
  assert.match(c.nodes.combatOutcomeSave.textContent,/Not saved: offline/);
  await c.nodes.submitCombatOutcome.onclick();
  assert.equal(c.calls.filter(call=>call.path.endsWith('combat-outcome')).length,0);
  c.setFail(false);await c.context.flush();assert.equal(c.nodes.combatOutcomeSave.textContent,'Saved');
});

test('Return to combat flushes current text and releases ownership',async()=>{
  const c=client();c.context.open();c.input('Still deciding the surrender terms.');
  await c.nodes.returnCombat.onclick();assert.equal(c.saved().combat.phase,'fighting');
  assert.equal(c.saved().combat.draft,'Still deciding the surrender terms.');assert.equal(c.saved().combat.editor_token,null);
});
