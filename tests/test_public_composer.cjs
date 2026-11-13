const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const section=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));

function composer({fail=false,quota=false}={}){
  const elements={};
  const $=id=>elements[id]??=( {value:'',disabled:false,style:{},classList:{toggle(){},contains(){return true;},add(){}},
    replaceChildren(){},focus(){},set innerHTML(value){},addEventListener(){}} );
  const state={identity:'one',composerMode:'ic',draft:null,pendingImage:null,
    save:{save:{id:'save',beat:3,mode:'normal'},messages:[],players:[{id:'one',ready:true},{id:'two',ready:false}]}};
  const stored=new Map(),requests=[],errors=[];
  const context=vm.createContext({state,$,Map,console:{error(){}},esc:x=>x,resize(){},render(){},
    refreshChoiceButtons(){},combatPending:()=>state.save.save.mode==='combat',
    localStorage:{getItem:key=>stored.get(key),setItem:(key,value)=>{if(quota)throw Error('quota');stored.set(key,value);},removeItem:key=>stored.delete(key)},
    newRequestId:()=> 'question-request',notify:error=>errors.push(error),
    request:async(path,payload)=>{requests.push({path,payload});if(fail&&payload)throw Error('timeout');return state.save;},
  });
  vm.runInContext(section('  const draftStale=','  $(\'keepDraft\').onclick=')+
    '\nthis.switchMode=switchComposerMode;this.send=sendPublicQuestion;this.sync=syncDraft;this.restore=restoreDraft;',context);
  return {state,$,context,requests,errors};
}

test('OOC send restores the independent IC text and attachment without Ready or advance requests',async()=>{
  for(const quota of [false,true]){
    const t=composer({quota});
    t.$('composer').value='I open the door';
    const image={name:'door.png',mime:'image/png',data:'picture'};
    t.state.pendingImage=image;t.context.sync();
    t.context.switchMode('ooc');
    assert.equal(t.$('composer').value,'');assert.equal(t.state.pendingImage,null);
    t.$('composer').value='Would checking it for traps require a roll?';t.context.sync();
    await t.context.send();
    assert.equal(t.state.composerMode,'ic');
    assert.equal(t.$('composer').value,'I open the door');
    assert.equal(t.state.pendingImage,image);
    assert.deepEqual(t.state.save.players.map(p=>p.ready),[true,false]);
    assert.equal(t.requests.filter(r=>r.payload).length,1);
    assert.ok(t.requests[0].path.endsWith('/public-question'));
    assert.equal(t.requests[0].payload.image,undefined);
    assert.equal(t.requests[0].payload.autoReady,undefined);
  }
});

test('OOC network failure keeps the question, attachment, mode and request ID for retry',async()=>{
  const t=composer({fail:true});t.context.switchMode('ooc');
  t.$('composer').value='Could I open the door?';t.state.pendingImage={name:'map.png',mime:'image/png',data:'image'};
  t.context.sync();await t.context.send();
  assert.equal(t.state.composerMode,'ooc');assert.equal(t.$('composer').value,'Could I open the door?');
  assert.equal(t.state.pendingImage.name,'map.png');assert.equal(t.state.draft.requestId,'question-request');
  await t.context.send();
  assert.equal(t.requests.filter(r=>r.payload)[1].payload.requestId,'question-request');
});

test('prefix alone cannot be sent and OOC sending during combat does not unlock the IC draft',async()=>{
  const t=composer();t.$('composer').value='I attack';t.context.sync();
  t.state.save.save.mode='combat';t.context.switchMode('ooc');
  t.$('composer').value='OOC:';await t.context.send();assert.equal(t.requests.length,0);
  t.$('composer').value='Can I disengage?';t.context.sync();await t.context.send();
  assert.equal(t.state.save.save.mode,'combat');assert.equal(t.$('composer').value,'I attack');
  assert.ok(t.requests[0].path.endsWith('/public-question'));
});

test('advancing while asking preserves the old IC beat so it requires review',async()=>{
  const t=composer();t.$('composer').value='I open the door';t.context.sync();
  t.context.switchMode('ooc');t.state.save.save.beat=4;
  t.$('composer').value='Could I open it?';t.context.sync();await t.context.send();
  assert.equal(t.state.draft.beat,3);assert.equal(t.$('composer').value,'I open the door');
});
