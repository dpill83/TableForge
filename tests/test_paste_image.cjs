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
const plain=value=>JSON.parse(JSON.stringify(value));
function table(){
  const elements={};
  for(const id of ['composer','attachmentInput','attachmentBtn']){
    elements[id]={id,value:'',disabled:false,listeners:{},addEventListener(type,handler){this.listeners[type]=handler;}};
  }
  // The tray renders one chip per pending image, each with its own remove button.
  const tray=elements.attachmentTray={chips:[],thumbs:[],buttons:[],classList:{hidden:true,toggle(name,on){this.hidden=on;}},
    replaceChildren(){this.chips=[];this.thumbs=[];this.buttons=[];},
    set innerHTML(html){
      this.chips=[...html.matchAll(/class=\"attachment-chip\" title=\"([^\"]*)\"/g)].map(m=>m[1]);
      this.thumbs=[...html.matchAll(/class="attachment-thumb" alt="" src="([^"]*)"/g)].map(m=>m[1]);
      this.buttons=[...html.matchAll(/data-index="(\d+)"/g)].map(m=>({dataset:{index:m[1]}}));
    },
    querySelectorAll(){return this.buttons;},
  };
  const state={pendingImages:[],draft:{requestId:'old'}},errors=[],syncs=[];
  const context=vm.createContext({state,Set,
    $:id=>elements[id],
    esc:value=>String(value),
    bytes64:async file=>`b64:${file.name}`,
    notify:error=>errors.push(error.message),
    syncDraft:()=>syncs.push(state.pendingImages.map(i=>i.name)),
  });
  vm.runInContext([
    section('  const renderPending=','  const clearPendingImage='),
    section('  // The + picker and clipboard paste share one path','  const modal='),
    'this.pastedImageName=pastedImageName;this.renderPending=renderPending;',
  ].join('\n'),context);
  const paste=async items=>{
    const event={prevented:false,preventDefault(){this.prevented=true;},
      clipboardData:{items:items.map(([kind,type,file])=>({kind,type,getAsFile:()=>file}))}};
    elements.composer.listeners.paste(event);
    await new Promise(resolve=>setImmediate(resolve));
    return event;
  };
  const pick=async files=>{
    const input=elements.attachmentInput;
    await input.onchange({target:{files,set value(v){input.value=v;}}});
  };
  const names=()=>plain(state.pendingImages.map(i=>i.name));
  return {state,elements,tray,errors,syncs,paste,pick,names,pastedImageName:context.pastedImageName,render:context.renderPending};
}
const file=(name,type,size=10)=>({name,type,size});
const png=name=>['file','image/png',file(name,'image/png')];

test('pasting an image attaches it with a readable name and resets the retry id',async()=>{
  const t=table();
  const event=await t.paste([['string','text/html',null],png('image.png')]);
  assert.equal(event.prevented,true);
  assert.equal(t.state.pendingImages.length,1);
  assert.match(t.state.pendingImages[0].name,/^Pasted image \d\d-\d\d-\d\d\.png$/);
  assert.equal(t.state.pendingImages[0].mime,'image/png');
  assert.equal(t.state.pendingImages[0].data,'b64:image.png');
  assert.equal(t.state.draft.requestId,null);
  assert.equal(t.tray.classList.hidden,false);
  assert.equal(t.syncs.length,1);
});

test('each chip shows a preview: the small thumbnail, or the image itself for older drafts',async()=>{
  const t=table();
  await t.pick([file('a.png','image/png')]);
  // No canvas in this sandbox, so no thumbnail is made and the chip uses the image data.
  assert.equal(t.state.pendingImages[0].thumb,null);
  assert.deepEqual(t.tray.thumbs,['data:image/png;base64,b64:a.png']);
  // In the browser a thumbnail is stored and preferred over the full image.
  t.state.pendingImages=[{name:'a.png',mime:'image/png',data:'aaa',thumb:'data:image/jpeg;base64,small'},
    {name:'b.png',mime:'image/png',data:'bbb'}];
  t.render();
  assert.deepEqual(t.tray.thumbs,['data:image/jpeg;base64,small','data:image/png;base64,bbb']);
});

test('pasting text is left to the browser',async()=>{
  const t=table();
  const event=await t.paste([['string','text/plain',null]]);
  assert.equal(event.prevented,false);
  assert.equal(t.state.pendingImages.length,0);
  assert.deepEqual(t.errors,[]);
});

test('later pastes and picks add images in order, up to four',async()=>{
  const t=table();
  await t.paste([png('a.png')]);
  await t.pick([file('b.jpg','image/jpeg'),file('c.webp','image/webp')]);
  await t.paste([png('d.png'),png('e.png')]);
  const names=t.names();
  assert.equal(names.length,4);
  assert.deepEqual(names.slice(1,3),['b.jpg','c.webp']);
  assert.match(names[3],/^Pasted image \d\d-\d\d-\d\d \(1\)\.png$/);
  assert.equal(t.tray.chips.length,4);
  assert.deepEqual(t.errors,['Attach up to 4 images per message.']);
});

test('each chip removes only its own image',async()=>{
  const t=table();
  await t.pick([file('a.png','image/png'),file('b.png','image/png'),file('c.png','image/png')]);
  t.state.draft.requestId='kept-until-edit';
  t.tray.buttons[1].onclick();
  assert.deepEqual(t.names(),['a.png','c.png']);
  assert.deepEqual(t.tray.chips,['a.png','c.png']);
  assert.equal(t.state.draft.requestId,null);
  t.tray.buttons[0].onclick();t.tray.buttons[0].onclick();
  assert.equal(t.state.pendingImages.length,0);
  assert.equal(t.tray.classList.hidden,true);
});

test('unsupported, oversized, or over-total images are refused; valid ones still attach',async()=>{
  const t=table();
  const gif=await t.paste([['file','image/gif',file('anim.gif','image/gif')]]);
  assert.equal(gif.prevented,true);
  await t.pick([file('huge.png','image/png',21*1024*1024),file('ok.png','image/png')]);
  assert.deepEqual(t.names(),['ok.png']);
  await t.pick([file('big1.png','image/png',20*1024*1024),file('big2.png','image/png',20*1024*1024)]);
  assert.deepEqual(t.names(),['ok.png','big1.png']);
  assert.equal(t.errors.length,3);
  assert.match(t.errors[2],/40 MB/);
});

test('overlapping attachments cannot push the message past the 40 MB total',async()=>{
  const t=table();
  await t.pick([file('ten.png','image/png',10*1024*1024)]);
  // Two additions start before either has finished reading its file.
  await Promise.all([t.pick([file('big1.png','image/png',20*1024*1024)]),t.pick([file('big2.png','image/png',20*1024*1024)])]);
  assert.deepEqual(t.names(),['ten.png','big1.png']);
  assert.equal(t.errors.length,1);
  assert.match(t.errors[0],/40 MB/);
});

test('overlapping pastes cannot push the message past four images',async()=>{
  const t=table();
  await t.pick([file('a.png','image/png'),file('b.png','image/png'),file('c.png','image/png')]);
  await Promise.all([t.paste([png('d.png')]),t.paste([png('e.png')])]);
  assert.equal(t.names().length,4);
  assert.deepEqual(t.errors,['Attach up to 4 images per message.']);
});

test('paste is ignored while attachments are disabled (combat IC, busy)',async()=>{
  const t=table();t.elements.attachmentBtn.disabled=true;
  await t.paste([png('a.png')]);
  assert.equal(t.state.pendingImages.length,0);
  assert.deepEqual(t.errors,[]);
});

test('pasted names use the image type extension and number multi-image pastes',()=>{
  const t=table(),at=new Date(2026,10,23,9,5,7);
  assert.equal(t.pastedImageName('image/jpeg',at),'Pasted image 09-05-07.jpg');
  assert.equal(t.pastedImageName('image/webp',at),'Pasted image 09-05-07.webp');
  assert.equal(t.pastedImageName('image/png',at,2),'Pasted image 09-05-07 (2).png');
});
