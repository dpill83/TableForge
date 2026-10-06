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
function table(){
  const document={body:{},activeElement:null};
  const elements={};
  for(const id of ['composer','sendBtn','readyBtn','toggleComposer','play','modalRoot']){
    elements[id]={value:'',disabled:false,childElementCount:0,listeners:{},
      classList:{contains:()=>true},
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
  const state={identity:'first',composer:false,draft:null,pendingImage:null,
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
  elements.toggleComposer.onclick=()=>{state.composer=!state.composer;};
  const context=vm.createContext({state,document,field,readyButton,
    $:id=>elements[id],TableForgeMessageActions:actions,Event:class{constructor(type){this.type=type;}},
    pendingContribution,combatPending,draftStale,syncDraft,
    storeDraft:()=>{},newRequestId:()=> 'request',typingSentAt:0,suppressReadyClick:false,
    autoReadyEnabled:()=>false,setAutoReady:()=>{},render:()=>{},
    notify:error=>{throw error;},
    clearDraft:()=>{field.value='';state.draft=null;state.pendingImage=null;},
    update:async(action,payload)=>{
      requests.push({action,payload});
      if(action==='messages'){
        state.save.messages.push({kind:'player',body:payload.text,request_id:payload.requestId});
        state.save.players[0].ready=true;
      }else if(action==='ready')state.save.players[0].ready=payload.ready;
      return true;
    },
    advanceTable:async()=>{requests.push({action:'advance'});},
  });
  vm.runInContext([
    section('  const addChoiceToDraft=','  let dotCount='),
    section("  $('sendBtn').onclick=","  const readyButton="),
    section("  $('readyBtn').onclick=","  $('readyOverride').onclick="),
    section('  const sendOnEnter=',"  $('emojiBtn').onclick="),
    'this.choose=letter=>addChoiceToDraft(10,"first",letter);',
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
  return {state,field,readyButton,elements,requests,choose:context.choose,press,document};
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
    assert.equal(t.state.save.players[0].ready,true);
  }
});

test('Enter on Ready with a selected action sends it before any advancement',async()=>{
  const t=table();t.state.save.players[1].ready=true;t.choose('B');t.readyButton.focus();
  await t.press(t.readyButton);
  assert.deepEqual(t.requests.map(r=>r.action),['messages','advance']);
  assert.equal(t.requests[0].payload.text,'I discuss the blade.');
});

test('choice appends to a draft, expands the composer, and preserves an attachment',async()=>{
  const t=table();t.field.value='I greet the crew.';t.state.composer=true;
  t.state.pendingImage={mime:'image/png',data:'test-image'};t.choose('C');
  assert.equal(t.state.composer,false);
  await t.press(t.readyButton);
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
  const t=table();t.choose('A');const event=await t.press(t.readyButton,{repeat:true});
  assert.equal(event.prevented,true);assert.equal(t.requests.length,0);
});

test('stale or disabled drafts cannot become Ready through Enter',async()=>{
  for(const block of ['stale','disabled']){
    const t=table();t.choose('C');
    if(block==='stale')t.state.save.save.beat=3;
    else t.elements.sendBtn.disabled=true;
    await t.press(t.readyButton);
    assert.equal(t.requests.length,0);assert.equal(t.field.value,'I keep watch.');
    assert.equal(t.state.save.players[0].ready,false);
  }
});

test('combat Enter still marks Finished and preserves the unsent action',async()=>{
  const t=table();t.choose('A');t.state.save.save.mode='combat';t.state.save.combat={id:'combat',phase:'fighting'};
  await t.press(t.readyButton);
  assert.equal(t.requests[0].action,'ready');assert.equal(t.requests[0].payload.handoffId,'combat');
  assert.equal(t.field.value,'I help the crew.');
  await t.press(t.field);assert.equal(t.requests.length,1);
});
