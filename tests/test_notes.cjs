const {test}=require('node:test');
const assert=require('node:assert/strict');
const {NotesSession}=require('../web/js/notes.js');

const memory=()=>({value:null,getItem(){return this.value;},setItem(k,v){this.value=v;}});
function setup(extra={}){
  let serial=0;const storage=extra.storage||memory(),calls=[],notes=[];
  const send=async op=>{
    calls.push({...op});
    let n=notes.find(n=>op.id?n.id===op.id:n.client_key===op.clientKey);
    if(n&&n.mutation===op.mutationId)return {notes};
    if(n&&n.revision!==op.revision)throw Object.assign(Error('Changed'),{code:'note_conflict'});
    if(!n){n={id:notes.length+1,client_key:op.clientKey,revision:0};notes.push(n);}
    Object.assign(n,{title:op.title,body:op.body,revision:n.revision+1,mutation:op.mutationId});
    return {notes};
  };
  const opts={storage,key:'drafts',send,uuid:()=>`id-${++serial}`,delay:100000,retry:100000,...extra};
  const session=new NotesSession(opts);
  return {storage,calls,notes,session,opts,cleanup:()=>{for(const timer of session.timers.values())clearTimeout(timer);}};
}

test('titles and body autosave after typing pauses without a Save action',async()=>{
  const t=setup({delay:5});
  try{
    const d=t.session.edit();t.session.input(d,'Loot','42 gold');
    await new Promise(resolve=>setTimeout(resolve,25));
    assert.equal(d.status,'Saved');assert.equal(t.notes[0].body,'42 gold');
    t.session.input(d,'Shared loot','43 gold');await t.session.flush(d);
    assert.equal(t.notes[0].title,'Shared loot');assert.equal(t.notes[0].body,'43 gold');
    assert.equal(JSON.parse(t.storage.value).length,0);
  }finally{t.cleanup();}
});

test('closed dialog and reload retain draft; lost create acknowledgement retries without duplication',async()=>{
  const t=setup();const original=t.opts.send;let fail=true;
  t.session.send=async op=>{const result=await original(op);if(fail){fail=false;throw Error('Disconnected');}return result;};
  const d=t.session.edit();t.session.input(d,'Loot','42 gold');await t.session.flush(d);
  assert.equal(d.status,'Couldn’t save');assert.equal(t.notes.length,1);t.cleanup();
  const restored=new NotesSession(t.opts);
  const [draft]=restored.drafts.values();assert.equal(draft.body,'42 gold');
  await restored.flush(draft);
  assert.equal(draft.status,'Saved');assert.equal(t.notes.length,1);
  assert.equal(t.calls[0].mutationId,t.calls[1].mutationId);
  for(const timer of restored.timers.values())clearTimeout(timer);
});

test('typing during an update survives acknowledgement and is saved next',async()=>{
  const t=setup();
  try{
    const d=t.session.edit();t.session.input(d,'Loot','first');await t.session.flush(d);
    const original=t.session.send;let release;
    t.session.send=op=>new Promise(resolve=>{release=async()=>resolve(await original(op));});
    t.session.input(d,'Loot','second');const pending=t.session.flush(d);
    t.session.input(d,'Loot','third');await release();await pending;
    assert.equal(d.body,'third');assert.equal(d.dirty,true);
    t.session.send=original;await t.session.flush(d);
    assert.equal(t.notes[0].body,'third');assert.equal(d.status,'Saved');
  }finally{t.cleanup();}
});

test('concurrent edits retain both versions and resolve by saving a separate note',async()=>{
  const t=setup();
  try{
    const d=t.session.edit();t.session.input(d,'Loot','original');await t.session.flush(d);
    t.notes[0].body='another player';t.notes[0].revision++;
    t.session.input(d,'Loot','my draft');await t.session.flush(d);
    assert.equal(d.conflict,true);assert.equal(d.body,'my draft');assert.equal(t.notes[0].body,'another player');
    const restored=new NotesSession(t.opts);assert.equal([...restored.drafts.values()][0].body,'my draft');
    const copy=t.session.copy(d);await t.session.flush(copy);
    assert.deepEqual(t.notes.map(n=>n.body),['another player','my draft']);
  }finally{t.cleanup();}
});

test('lost update acknowledgement with newer typing survives a reload',async()=>{
  const t=setup();
  try{
    const d=t.session.edit();t.session.input(d,'Loot','first');await t.session.flush(d);
    const original=t.session.send;
    t.session.send=async op=>{await original(op);t.session.input(d,'Loot','third');throw Error('Lost reply');};
    t.session.input(d,'Loot','second');await t.session.flush(d);t.cleanup();
    const restored=new NotesSession(t.opts),[draft]=restored.drafts.values();
    await restored.flush(draft);await restored.flush(draft);
    assert.equal(t.notes[0].body,'third');assert.equal(draft.status,'Saved');
    for(const timer of restored.timers.values())clearTimeout(timer);
  }finally{t.cleanup();}
});
