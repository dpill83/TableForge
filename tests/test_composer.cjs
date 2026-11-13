const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const actions=require('../web/js/message-actions.js');

// Exercise the actual app handlers without starting a browser or touching a save.
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const section=(start,end)=>{
  const from=source.indexOf(start),to=source.indexOf(end,from);
  assert.ok(from>=0&&to>from,`Missing app handler: ${start}`);
  return source.slice(from,to);
};
function table({autoReady=false}={}){
  const document={body:{},activeElement:null};
  const elements={};
  for(const id of ['composer','sendBtn','readyBtn','play','modalRoot']){
    elements[id]={value:'',disabled:false,childElementCount:0,listeners:{},
      classList:{contains:()=>true,add:()=>{},remove:()=>{}},
      style:{setProperty:()=>{},removeProperty:()=>{}},setPointerCapture:()=>{},
      addEventListener(type,handler){this.listeners[type]=handler;},
      dispatchEvent(event){event.currentTarget=this;this.listeners[event.type]?.(event);},
      focus(){document.activeElement=this;},
      setSelectionRange(start,end){this.selection=[start,end];},
      click(){if(!this.disabled)this.pending=Promise.resolve(this.onclick?.());},
    };
  }
  const field=elements.composer,readyButton=elements.readyBtn,requests=[];
  const message={id:10,kind:'ai',session_id:'session',choices:{beat:2,groups:[
    {playerId:'first',options:[
      {letter:'A',text:'I help the crew.'},
      {letter:'B',text:'I discuss the blade.'},
      {letter:'C',text:'I keep watch.'},
    ]},
  ]}};
  const state={identity:'first',draft:null,pendingImage:null,
    save:{save:{id:'save',beat:2,mode:'normal'},sessions:[{id:'session',ended_at:null}],
      players:[{id:'first',ready:false},{id:'second',ready:false}],messages:[message],activity:{}},
  };
  const pendingContribution=()=>!!field.value.trim()||!!state.pendingImage;
  const combatPending=()=>state.save.save.mode==='combat'||!!(state.save.combat&&state.save.combat.phase!=='complete');
  const draftStale=()=>!!state.draft&&state.draft.beat!==state.save.save.beat;
  const syncDraft=()=>{
    if(!pendingContribution())state.draft=null;
    else state.draft||={saveId:'save',beat:2,requestId:null};
  };
  field.addEventListener('input',syncDraft);
  const storage=new Map(autoReady?[["tableforge-auto-ready:v2:save:first",'true']]:[]);
  const context=vm.createContext({state,document,field,
    localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    performance:{now:()=>100},requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{},
    $:id=>elements[id],TableForgeMessageActions:actions,Event:class{constructor(type){this.type=type;}},
    pendingContribution,combatPending,draftStale,syncDraft,
    storeDraft:()=>{},newRequestId:()=> 'request',typingSentAt:0,
    render:()=>{},
    notify:error=>{throw error;},
    clearDraft:()=>{field.value='';state.draft=null;state.pendingImage=null;},
    update:async(action,payload)=>{
      requests.push({action,payload});
      if(action==='messages'){
        state.save.messages.push({kind:'player',body:payload.text,request_id:payload.requestId});
        if(payload.autoReady===true)state.save.players[0].ready=true;
      }else if(action==='ready')state.save.players[0].ready=payload.ready;
      return true;
    },
    advanceTable:async()=>{requests.push({action:'advance'});},
  });
  vm.runInContext([
    section('  const autoReadyKey=',"  const aiNotificationKey="),
    section('  const addChoiceToDraft=','  let dotCount='),
    section("  $('sendBtn').onclick=","  const readyButton="),
    section("  const readyButton=","  $('readyOverride').onclick="),
    section('  const sendOnEnter=',"  $('emojiBtn').onclick="),
    'this.choose=letter=>addChoiceToDraft(10,"first",letter);this.autoReadyEnabled=autoReadyEnabled;this.holdTick=updateReadyHold;',
  ].join('\n'),context);
  const press=async(target,extra={})=>{
    const event={type:'keydown',key:'Enter',shiftKey:false,isComposing:false,repeat:false,
      prevented:false,preventDefault(){this.prevented=true;},...extra};
    target.dispatchEvent(event);
    // Browser button activation is the path that used to mark Ready on Enter.
    if(!event.prevented&&event.key==='Enter'&&target!==field)target.click();
    await target.pending;await elements.sendBtn.pending;
    return event;
  };
  return {state,field,readyButton,elements,requests,choose:context.choose,press,document,autoReadyEnabled:context.autoReadyEnabled,holdTick:context.holdTick};
}

test('each choice stays local, focuses the composer, and Enter sends its full action',async()=>{
  for(const [letter,text] of [['A','I help the crew.'],['B','I discuss the blade.'],['C','I keep watch.']]){
    const t=table();t.choose(letter);
    assert.equal(t.document.activeElement,t.field);
    assert.equal(t.field.value,text);
    assert.equal(t.requests.length,0);
    assert.equal(t.state.save.players[0].ready,false);
    await t.press(t.document.activeElement);
    assert.equal(t.requests[0].action,'messages');
    assert.equal(t.requests[0].payload.text,text);
    assert.equal(t.requests[0].payload.beat,2);
    assert.equal(t.requests[0].payload.requestId,'request');
    assert.equal(t.field.value,'');
    assert.equal(t.state.save.players[0].ready,false);
  }
});

test('Enter on Ready readies without sending or discarding a draft',async()=>{
  const t=table();t.state.save.players[1].ready=true;t.choose('B');t.readyButton.focus();
  await t.press(t.readyButton);
  assert.deepEqual(t.requests.map(r=>r.action),['ready','advance']);
  assert.equal(t.field.value,'I discuss the blade.');
});

test('choice appends to a draft and preserves an attachment',async()=>{
  const t=table();t.field.value='I greet the crew.';
  t.state.pendingImage={mime:'image/png',data:'test-image'};t.choose('C');
  await t.press(t.field);
  assert.equal(t.requests[0].payload.text,'I greet the crew.\nI keep watch.');
  assert.equal(t.requests[0].payload.image.data,'test-image');
});

test('Ready remains usable without a contribution, by keyboard or ordinary click',async()=>{
  const t=table();await t.press(t.readyButton);
  assert.equal(t.requests[0].action,'ready');
  const withDraft=table();withDraft.choose('A');withDraft.readyButton.click();await withDraft.readyButton.pending;
  assert.equal(withDraft.requests[0].action,'ready');
  assert.equal(withDraft.field.value,'I help the crew.');
});

test('Shift+Enter and IME Enter keep editing; held Enter cannot send repeatedly',async()=>{
  for(const extra of [{shiftKey:true},{isComposing:true},{repeat:true}]){
    const t=table();t.choose('A');await t.press(t.field,extra);
    assert.equal(t.requests.length,0);assert.equal(t.field.value,'I help the crew.');
  }
  const t=table();t.choose('A');const event=await t.press(t.field,{repeat:true});
  assert.equal(event.prevented,true);assert.equal(t.requests.length,0);
});

test('stale or disabled drafts cannot send or become Ready through composer Enter',async()=>{
  for(const block of ['stale','disabled']){
    const t=table();t.choose('C');
    if(block==='stale')t.state.save.save.beat=3;
    else t.elements.sendBtn.disabled=true;
    await t.press(t.field);
    assert.equal(t.requests.length,0);assert.equal(t.field.value,'I keep watch.');
    assert.equal(t.state.save.players[0].ready,false);
  }
});

test('combat Enter preserves the unsent action without marking Ready',async()=>{
  const t=table();t.choose('A');t.state.save.save.mode='combat';t.state.save.combat={id:'combat',phase:'fighting'};
  await t.press(t.readyButton);
  assert.equal(t.requests.length,0);
  assert.equal(t.field.value,'I help the crew.');
  await t.press(t.field);assert.equal(t.requests.length,0);
});

test('AUTO send marks Ready and advances only when everyone is Ready',async()=>{
  const t=table({autoReady:true});t.state.save.players[1].ready=true;t.choose('A');
  await t.press(t.field);
  assert.equal(t.requests[0].payload.autoReady,true);
  assert.equal(t.state.save.players[0].ready,true);
  assert.deepEqual(t.requests.map(r=>r.action),['messages','advance']);
});

test('sending with AUTO off preserves an explicit Ready',async()=>{
  const t=table();t.state.save.players[0].ready=true;t.choose('A');await t.press(t.field);
  assert.equal(t.requests[0].payload.autoReady,false);
  assert.equal(t.state.save.players[0].ready,true);
});

test('Ready and Unready remain independent of AUTO without sending',async()=>{
  const t=table({autoReady:true});
  await t.press(t.readyButton);
  assert.equal(t.state.save.players[0].ready,true);
  assert.equal(t.autoReadyEnabled(),true);
  await t.press(t.readyButton);
  assert.equal(t.state.save.players[0].ready,false);
  assert.equal(t.autoReadyEnabled(),true);
  assert.deepEqual(t.requests.map(r=>r.action),['ready','ready']);
});

test('holding toggles AUTO both ways without changing readiness or sending drafts',async()=>{
  for(const ready of [false,true]){
    const t=table();t.state.save.players[0].ready=ready;t.choose('A');
    for(const enabled of [true,false]){
      t.readyButton.dispatchEvent({type:'pointerdown',button:0,pointerId:1});
      t.holdTick(899);assert.equal(t.autoReadyEnabled(),!enabled);
      t.holdTick(900);assert.equal(t.autoReadyEnabled(),enabled);
      t.readyButton.dispatchEvent({type:'pointerup',pointerId:1});
      t.readyButton.click();await t.readyButton.pending;
      assert.equal(t.state.save.players[0].ready,ready);
      assert.equal(t.requests.length,0);assert.equal(t.field.value,'I help the crew.');
    }
    t.readyButton.click();await t.readyButton.pending;
    assert.equal(t.state.save.players[0].ready,!ready);
  }
});

test('AUTO preference is scoped to player and save and suspended during combat',()=>{
  const t=table({autoReady:true});assert.equal(t.autoReadyEnabled(),true);
  t.state.identity='second';assert.equal(t.autoReadyEnabled(),false);t.state.identity='first';
  t.state.save.save.id='other';assert.equal(t.autoReadyEnabled(),false);t.state.save.save.id='save';
  t.state.save.save.mode='combat';assert.equal(t.autoReadyEnabled(),false);
  t.state.save.save.mode='normal';assert.equal(t.autoReadyEnabled(),true);
});

test('short holds, canceled gestures, disabled controls and combat cannot toggle AUTO',()=>{
  for(const block of ['short','cancel','lost','disabled','combat']){
    const t=table({autoReady:true});
    if(block==='disabled')t.readyButton.disabled=true;
    if(block==='combat')t.state.save.save.mode='combat';
    t.readyButton.dispatchEvent({type:'pointerdown',button:0,pointerId:1});
    if(block==='short')t.readyButton.dispatchEvent({type:'pointerup',pointerId:1});
    if(block==='cancel')t.readyButton.dispatchEvent({type:'pointercancel',pointerId:1});
    if(block==='lost')t.readyButton.dispatchEvent({type:'lostpointercapture',pointerId:1});
    t.holdTick(1000);t.state.save.save.mode='normal';
    assert.equal(t.autoReadyEnabled(),true);assert.equal(t.requests.length,0);
  }
});

test('silent Ready with AUTO advances when the other player is already Ready',async()=>{
  const t=table({autoReady:true});t.state.save.players[1].ready=true;
  t.readyButton.click();await t.readyButton.pending;
  assert.deepEqual(t.requests.map(r=>r.action),['ready','advance']);
  assert.equal(t.autoReadyEnabled(),true);
});
