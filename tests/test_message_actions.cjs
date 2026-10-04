const assert=require('node:assert/strict');
const {test}=require('node:test');
const {groupsFor,canChoose,appendText}=require('../web/js/message-actions.js');

const choices={beat:2,groups:[
  {playerId:'first',options:[{letter:'A',text:'I help the crew.'}]},
  {playerId:'second',options:[{letter:'A',text:'I inspect the blade.'}]},
  {playerId:null,options:[{letter:'A',text:'I suggest we stay aboard.'}]},
]};
const message={id:10,session_id:'session',kind:'ai',choices};
const makeState=()=>({identity:'first',generating:false,updating:false,save:{
  save:{beat:2},players:[{id:'first'},{id:'second'}],sessions:[{id:'session',ended_at:null}],
  messages:[message],activity:{aiDm:null},
}});

test('only the selected character and party-wide groups are clickable',()=>{
  assert.deepEqual(groupsFor(choices,'first').map(group=>group.playerId),['first',null]);
  assert.deepEqual(groupsFor(choices,'second').map(group=>group.playerId),['second',null]);
  assert.deepEqual(groupsFor(choices,null),[]);
});

test('choices expire when the beat, session, generation, or draft changes',()=>{
  assert.equal(canChoose(makeState(),message),true);
  assert.equal(canChoose(makeState(),message,true),false);
  for(const change of [
    s=>s.generating=true,s=>s.updating=true,s=>s.save.activity.aiDm='advance',
    s=>s.save.activity.aiDm='ask',s=>s.save.save.beat=3,s=>s.identity=null,
    s=>s.identity='unknown',s=>s.save.sessions[0].ended_at='ended',
    s=>s.save.sessions.push({id:'new-session',ended_at:null}),
    s=>s.save.messages.push({id:11,kind:'ai'}),
  ]){
    const state=makeState();change(state);assert.equal(canChoose(state,message),false);
  }
});

test('shared illustrations do not expire the latest narration choices',()=>{
  const state=makeState();state.save.messages.push({id:11,kind:'image'});
  assert.equal(canChoose(state,message),true);
});

test('appending preserves draft text and does not mutate the save or Ready',()=>{
  const state=makeState(),before=JSON.stringify(state);
  assert.equal(appendText('','I keep watch.'),'I keep watch.');
  assert.equal(appendText('I talk with the crew.','I keep watch.'),'I talk with the crew.\nI keep watch.');
  assert.equal(appendText('I talk with the crew.\n','I keep watch.'),'I talk with the crew.\nI keep watch.');
  assert.equal(JSON.stringify(state),before);
});
