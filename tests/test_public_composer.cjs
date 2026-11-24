const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const plain=value=>JSON.parse(JSON.stringify(value));
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const section=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));

function composer({fail=false,quota=false}={}){
  const elements={};
  const $=id=>elements[id]??=( {value:'',disabled:false,style:{},classList:{toggle(){},contains(){return true;},add(){}},
    replaceChildren(){},focus(){},set innerHTML(value){},addEventListener(){},querySelectorAll(){return [];}} );
  const state={identity:'one',composerMode:'ic',draft:null,pendingImages:[],
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
  return {state,$,context,requests,errors,stored};
}

test('OOC send restores the independent IC text and attachment without Ready or advance requests',async()=>{
  for(const quota of [false,true]){
    const t=composer({quota});
    t.$('composer').value='I open the door';
    const image={name:'door.png',mime:'image/png',data:'picture'};
    t.state.pendingImages=[image];t.context.sync();
    t.context.switchMode('ooc');
    assert.equal(t.$('composer').value,'');assert.deepEqual(plain(t.state.pendingImages),[]);
    t.$('composer').value='Would checking it for traps require a roll?';t.context.sync();
    await t.context.send();
    assert.equal(t.state.composerMode,'ic');
    assert.equal(t.$('composer').value,'I open the door');
    assert.deepEqual(plain(t.state.pendingImages),[image]);
    assert.deepEqual(t.state.save.players.map(p=>p.ready),[true,false]);
    assert.equal(t.requests.filter(r=>r.payload).length,1);
    assert.ok(t.requests[0].path.endsWith('/public-question'));
    assert.equal(t.requests[0].payload.images,undefined);
    assert.equal(t.requests[0].payload.autoReady,undefined);
  }
});

test('OOC network failure keeps the question, attachment, mode and request ID for retry',async()=>{
  const t=composer({fail:true});t.context.switchMode('ooc');
  t.$('composer').value='Could I open the door?';t.state.pendingImages=[{name:'map.png',mime:'image/png',data:'image'},{name:'key.png',mime:'image/png',data:'key'}];
  t.context.sync();await t.context.send();
  assert.equal(t.state.composerMode,'ooc');assert.equal(t.$('composer').value,'Could I open the door?');
  assert.deepEqual(plain(t.state.pendingImages.map(i=>i.name)),['map.png','key.png']);assert.equal(t.state.draft.requestId,'question-request');
  await t.context.send();
  assert.equal(t.requests.filter(r=>r.payload)[1].payload.requestId,'question-request');
  assert.deepEqual(plain(t.requests.filter(r=>r.payload)[1].payload.images),[{mime:'image/png',data:'image'},{mime:'image/png',data:'key'}]);
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

test('a draft saved with one image before multi-image support restores as a one-image list',()=>{
  const t=composer();
  const image={name:'old.png',mime:'image/png',data:'old'};
  t.stored.set('tableforge-draft:save:one',JSON.stringify({text:'',image,beat:3,requestId:null}));
  t.context.restore();
  assert.deepEqual(plain(t.state.pendingImages),[image]);
  assert.deepEqual(JSON.parse(t.stored.get('tableforge-draft:save:one')).images,[image]);
});
