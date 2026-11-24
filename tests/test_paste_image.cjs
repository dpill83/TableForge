const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');

// Runs the real attachment and paste handlers from app.js against stub elements.
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const section=(start,end)=>{
  const from=source.indexOf(start),to=source.indexOf(end,from);
  assert.ok(from>=0&&to>from,`Missing app handler: ${start}`);
  return source.slice(from,to);
};
function table(){
  const elements={};
  for(const id of ['composer','attachmentInput','attachmentBtn','attachmentTray']){
    elements[id]={id,value:'',disabled:false,innerHTML:'',listeners:{},
      classList:{hidden:true,toggle(name,on){this.hidden=on;}},
      addEventListener(type,handler){this.listeners[type]=handler;},
      replaceChildren(){this.innerHTML='';},
    };
  }
  const state={pendingImage:null,draft:{requestId:'old'}},errors=[],syncs=[];
  const context=vm.createContext({state,
    $:id=>elements[id]||{set onclick(v){}},
    esc:value=>String(value),
    bytes64:async file=>`b64:${file.name}`,
    notify:error=>errors.push(error.message),
    syncDraft:()=>syncs.push(state.pendingImage?.name),
  });
  vm.runInContext([
    section('  const renderPending=','  const clearPendingImage='),
    section('  // The + picker and clipboard paste share one path','  const modal='),
    'this.pastedImageName=pastedImageName;',
  ].join('\n'),context);
  const paste=async items=>{
    const event={prevented:false,preventDefault(){this.prevented=true;},
      clipboardData:{items:items.map(([kind,type,file])=>({kind,type,getAsFile:()=>file}))}};
    elements.composer.listeners.paste(event);
    await new Promise(resolve=>setImmediate(resolve));
    return event;
  };
  return {state,elements,errors,syncs,paste,pastedImageName:context.pastedImageName};
}
const file=(name,type,size=10)=>({name,type,size});

test('pasting an image attaches it with a readable name and resets the retry id',async()=>{
  const t=table();
  const event=await t.paste([['string','text/html',null],['file','image/png',file('image.png','image/png')]]);
  assert.equal(event.prevented,true);
  assert.match(t.state.pendingImage.name,/^Pasted image \d\d-\d\d-\d\d\.png$/);
  assert.equal(t.state.pendingImage.mime,'image/png');
  assert.equal(t.state.pendingImage.data,'b64:image.png');
  assert.equal(t.state.draft.requestId,null);
  assert.equal(t.elements.attachmentTray.classList.hidden,false);
  assert.doesNotMatch(t.elements.attachmentTray.innerHTML,/Replaced/);
  assert.equal(t.syncs.length,1);
});

test('pasting text is left to the browser',async()=>{
  const t=table();
  const event=await t.paste([['string','text/plain',null]]);
  assert.equal(event.prevented,false);
  assert.equal(t.state.pendingImage,null);
  assert.deepEqual(t.errors,[]);
});

test('a second image replaces the first and says so',async()=>{
  const t=table();
  await t.paste([['file','image/png',file('a.png','image/png')]]);
  await t.paste([['file','image/jpeg',file('b.jpg','image/jpeg')]]);
  assert.match(t.state.pendingImage.name,/\.jpg$/);
  assert.match(t.elements.attachmentTray.innerHTML,/Replaced the previous image/);
});

test('unsupported or oversized images are refused without attaching',async()=>{
  const t=table();
  const gif=await t.paste([['file','image/gif',file('anim.gif','image/gif')]]);
  assert.equal(gif.prevented,true);
  await t.paste([['file','image/png',file('huge.png','image/png',21*1024*1024)]]);
  assert.equal(t.state.pendingImage,null);
  assert.equal(t.errors.length,2);
});

test('paste is ignored while attachments are disabled (combat IC, busy)',async()=>{
  const t=table();t.elements.attachmentBtn.disabled=true;
  await t.paste([['file','image/png',file('a.png','image/png')]]);
  assert.equal(t.state.pendingImage,null);
  assert.deepEqual(t.errors,[]);
});

test('the + picker uses the same path and keeps the file name',async()=>{
  const t=table();
  const input=t.elements.attachmentInput;input.value='C:\\fakepath\\map.webp';
  await input.onchange({target:{files:[file('map.webp','image/webp')],get value(){return input.value;},set value(v){input.value=v;}}});
  assert.equal(t.state.pendingImage.name,'map.webp');
});

test('pasted names use the image type extension',()=>{
  const t=table(),at=new Date(2026,10,23,9,5,7);
  assert.equal(t.pastedImageName('image/jpeg',at),'Pasted image 09-05-07.jpg');
  assert.equal(t.pastedImageName('image/webp',at),'Pasted image 09-05-07.webp');
  assert.equal(t.pastedImageName('image/png',at),'Pasted image 09-05-07.png');
});
