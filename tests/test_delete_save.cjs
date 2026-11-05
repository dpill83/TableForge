const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const start=source.indexOf('  const deleteSave=save=>{');
const end=source.indexOf('  const refreshSaves=',start);
assert.ok(start>=0&&end>start);
function dialog(){
  const elements={deleteConfirmation:{value:'',focus(){}},deletePermanently:{disabled:true},
    cancelDelete:{disabled:false},deleteError:{textContent:''},modalRoot:{replaceChildren(){}}};
  const calls=[];let confirm,html,resolve,reject,refreshes=0;
  const context=vm.createContext({$:id=>elements[id],state:{save:null},esc:s=>s,
    confirmBox:(title,message,callback)=>{confirm=callback;},modal:value=>{html=value;},
    refreshSaves:async()=>{refreshes++;},leaveUnavailableSave:async()=>{},
    request:(path,payload)=>{calls.push({path,payload});return new Promise((yes,no)=>{resolve=yes;reject=no;});},
  });
  vm.runInContext(source.slice(start,end)+'\nthis.open=deleteSave;',context);
  context.open({id:'selected',name:'Test playthrough'});
  return {elements,calls,confirm:()=>confirm(),html:()=>html,refreshes:()=>refreshes,
    resolve:()=>resolve({deleted:'selected'}),reject:()=>reject(Error('Backup failed'))};
}

test('first confirmation sends nothing; second requires exact DELETE and prevents duplicate requests',async()=>{
  const t=dialog();assert.equal(t.html(),undefined);assert.equal(t.calls.length,0);
  t.confirm();assert.match(t.html(),/Test playthrough/);
  const field=t.elements.deleteConfirmation,button=t.elements.deletePermanently;
  for(const value of ['', 'delete', 'DELETE ']){
    field.value=value;field.oninput();assert.equal(button.disabled,true);
    await button.onclick();assert.equal(t.calls.length,0);
  }
  field.value='DELETE';field.oninput();assert.equal(button.disabled,false);
  const pending=button.onclick();assert.equal(button.disabled,true);
  await button.onclick();assert.equal(t.calls.length,1);
  assert.equal(t.calls[0].path,'saves/selected/delete');
  assert.deepEqual(JSON.parse(JSON.stringify(t.calls[0].payload)),{confirmed:true,confirmation:'DELETE',name:'Test playthrough'});
  t.resolve();await pending;assert.equal(t.refreshes(),1);
});

test('failure keeps the dialog usable and does not remove the save list entry',async()=>{
  const t=dialog();t.confirm();t.elements.deleteConfirmation.value='DELETE';
  t.elements.deleteConfirmation.oninput();const pending=t.elements.deletePermanently.onclick();
  t.reject();await pending;
  assert.equal(t.elements.deleteError.textContent,'Backup failed');
  assert.equal(t.elements.deleteConfirmation.disabled,false);
  assert.equal(t.elements.cancelDelete.disabled,false);
  assert.equal(t.refreshes(),0);
});

test('another browser leaves a deleted playthrough on the next table refresh',async()=>{
  const from=source.indexOf('  let refreshingTable=false;');
  const to=source.indexOf('  },2500);',from)+'  },2500);'.length;
  let poll,left=0,notification='';
  const state={save:{save:{id:'deleted'}}};
  const context=vm.createContext({state,document:{hidden:false},
    $:()=>({classList:{contains:()=>true}}),setInterval:callback=>{poll=callback;},
    request:async()=>{throw Object.assign(Error('Unavailable'),{code:'save_unavailable'});},
    leaveUnavailableSave:async()=>{left++;state.save=null;},notify:error=>{notification=error.message;},
    console,syncCombatDialog:()=>{},
  });
  vm.runInContext(source.slice(from,to),context);
  await poll();assert.equal(left,1);assert.equal(state.save,null);
  assert.match(notification,/deleted/);
});
