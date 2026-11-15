const assert=require('node:assert/strict');
const {test}=require('node:test');
const layout=require('../web/js/layout.js');
const {DEFAULTS,maxWidth,isOverlay,dragStep,keyWidth,parsePrefs,serializePrefs,captureAnchor,anchorTop,FeedAnchor,createSidebar}=layout;

test('sidebar max leaves the minimum chat width and never drops below min',()=>{
  assert.equal(maxWidth(1366),400);
  assert.equal(maxWidth(760),340);// 760 - 420 chat
  assert.equal(maxWidth(500),DEFAULTS.min);
});

test('narrow windows switch to overlay below min sidebar plus min chat',()=>{
  assert.equal(isOverlay(640),false);
  assert.equal(isOverlay(639),true);
  assert.equal(isOverlay(683),false);// Half of a 1366 px laptop screen stays inline.
});

test('dragging holds at min, collapses past the travel threshold, and reopens only past min',()=>{
  const cfg={...DEFAULTS,max:400};
  assert.deepEqual(dragStep(300,cfg,false),{collapsed:false,width:300});
  assert.deepEqual(dragStep(900,cfg,false),{collapsed:false,width:400});
  // Resistance zone: hold at min.
  assert.deepEqual(dragStep(200,cfg,false),{collapsed:false,width:220});
  assert.deepEqual(dragStep(181,cfg,false),{collapsed:false,width:220});
  // Past min - travel: collapse.
  assert.equal(dragStep(179,cfg,false).collapsed,true);
  // Hysteresis: back in the resistance zone stays collapsed in the same gesture...
  assert.equal(dragStep(200,cfg,true).collapsed,true);
  assert.equal(dragStep(219,cfg,true).collapsed,true);
  // ...and reopens at min once the pointer passes the min line.
  assert.deepEqual(dragStep(220,cfg,true),{collapsed:false,width:220});
});

test('keyboard adjusts within bounds and never collapses',()=>{
  const cfg={...DEFAULTS,max:400};
  assert.equal(keyWidth('ArrowLeft',260,cfg),244);
  assert.equal(keyWidth('ArrowRight',260,cfg,true),308);
  assert.equal(keyWidth('ArrowLeft',225,cfg),220);
  assert.equal(keyWidth('Home',300,cfg),220);
  assert.equal(keyWidth('End',300,cfg),400);
  assert.equal(keyWidth('Enter',300,cfg),null);
});

test('preferences parse defensively and round-trip',()=>{
  assert.deepEqual(parsePrefs(null),{width:260,collapsed:false});
  assert.deepEqual(parsePrefs('not json'),{width:260,collapsed:false});
  assert.deepEqual(parsePrefs('{"width":0,"collapsed":true}'),{width:260,collapsed:true});
  assert.deepEqual(parsePrefs(serializePrefs({width:333.4,collapsed:true})),{width:333,collapsed:true});
});

/* Minimal fake DOM. Rects are computed from a layout function so tests can
   simulate reflow by changing what it returns. */
class FakeClassList{
  constructor(){this.set=new Set();}
  add(...names){names.forEach(n=>this.set.add(n));}
  remove(...names){names.forEach(n=>this.set.delete(n));}
  toggle(name,on){if(on===undefined)on=!this.set.has(name);if(on)this.set.add(name);else this.set.delete(name);return on;}
  contains(name){return this.set.has(name);}
}
class FakeElement{
  constructor({id='',rect=()=>({top:0,bottom:0,left:0,right:0}),children=[],blocks=[]}={}){
    this.id=id;this.rect=rect;this.children=children;this.blocks=blocks;this.attributes={};this.listeners={};
    this.classList=new FakeClassList();this.style={props:{},setProperty:(k,v)=>{this.style.props[k]=v;}};
    this.clientWidth=800;this.scrollTop=0;this.scrollHeight=5000;this.inert=false;this.title='';
  }
  getBoundingClientRect(){return this.rect();}
  setAttribute(k,v){this.attributes[k]=String(v);}
  removeAttribute(k){delete this.attributes[k];}
  getAttribute(k){return this.attributes[k];}
  addEventListener(type,fn){(this.listeners[type]||=[]).push(fn);}
  dispatch(type,event={}){for(const fn of this.listeners[type]||[])fn({preventDefault(){},button:0,pointerId:1,...event});}
  contains(other){return other===this||this.children.includes(other);}
  focus(){this.ownerDoc&&(this.ownerDoc.activeElement=this);}
  setPointerCapture(){}
}

// A feed of rows; each row has paragraph blocks of a given height. Text
// reflow is simulated by changing the per-line height factor.
function fakeFeed(rowSpecs){
  const feed=new FakeElement();feed.scrollTop=0;
  let factor=1;
  const positions=()=>{
    let y=0;const out=[];
    for(const spec of rowSpecs){
      const start=y;const blocks=[];y+=20;// row header
      for(const lines of spec.blocks){blocks.push({top:y,height:lines*20*factor});y+=lines*20*factor+10;}
      out.push({start,end:y,blocks});
    }
    return out;
  };
  const rows=rowSpecs.map((spec,r)=>{
    const row=new FakeElement({id:spec.id,rect:()=>{const p=positions()[r];return {top:p.start-feed.scrollTop,bottom:p.end-feed.scrollTop};}});
    row.blocks=spec.blocks.map((_,b)=>new FakeElement({rect:()=>{const p=positions()[r].blocks[b];return {top:p.top-feed.scrollTop,bottom:p.top+p.height-feed.scrollTop};}}));
    row.querySelectorAll=()=>row.blocks;
    return row;
  });
  feed.rect=()=>({top:0,bottom:600});
  feed.querySelectorAll=()=>rows;
  feed.querySelector=selector=>rows.find(row=>selector.includes(`"${row.id}"`))||null;
  return {feed,rows,setFactor:f=>{factor=f;}};
}

test('anchor keeps the paragraph being read at the same offset after reflow',()=>{
  const {feed,rows,setFactor}=fakeFeed([
    {id:'message-1',blocks:[3,3]},
    {id:'message-2',blocks:[10,10,10]},// A reply taller than the viewport.
    {id:'event-7',blocks:[]},
    {id:'message-3',blocks:[2]},
  ]);
  feed.scrollTop=380;// Mid-way through message-2.
  const anchor=captureAnchor(feed,false);
  assert.equal(anchor.rowId,'message-2');
  assert.equal(anchor.index,1);// First paragraph at or below the top edge, not the row.
  const before=rows[1].blocks[1].getBoundingClientRect().top;
  setFactor(1.6);// Narrower column: text wraps onto more lines.
  feed.scrollTop=anchorTop(feed,anchor);
  assert.ok(Math.abs(rows[1].blocks[1].getBoundingClientRect().top-before)<1e-9);
});

test('combat-event rows anchor by the row itself',()=>{
  const {feed,rows,setFactor}=fakeFeed([
    {id:'message-1',blocks:[5]},
    {id:'event-7',blocks:[]},
    {id:'message-2',blocks:[5]},
  ]);
  feed.scrollTop=rows[1].getBoundingClientRect().top;// event row starts at the top edge
  const anchor=captureAnchor(feed,false);
  assert.equal(anchor.rowId,'event-7');
  assert.equal(anchor.index,-1);
  const before=rows[1].getBoundingClientRect().top;
  setFactor(2);
  feed.scrollTop=anchorTop(feed,anchor);
  assert.ok(Math.abs(rows[1].getBoundingClientRect().top-before)<1e-9);
});

test('following the latest message pins to the bottom; missing rows fall back',()=>{
  const {feed}=fakeFeed([{id:'message-1',blocks:[3]},{id:'message-2',blocks:[3]}]);
  assert.deepEqual(captureAnchor(feed,true),{pinned:true});
  assert.equal(anchorTop(feed,{pinned:true}),feed.scrollHeight);
  const fallback=anchorTop(feed,{pinned:false,rowId:'message-gone',index:0,offset:0,fallbacks:[{rowId:'message-2',offset:10}]});
  assert.equal(typeof fallback,'number');
  assert.equal(anchorTop(feed,{pinned:false,rowId:'message-gone',index:0,offset:0,fallbacks:[]}),null);
});

test('FeedAnchor ignores its own restoration scroll and pauses capture while a width change is pending',()=>{
  const {feed,setFactor}=fakeFeed([{id:'message-1',blocks:[10,10,10]},{id:'message-2',blocks:[10]}]);
  const frames=[];let clock=0;
  const anchor=new FeedAnchor({feed,isFollowing:()=>false,raf:fn=>frames.push(fn),now:()=>clock});
  feed.scrollTop=250;
  anchor.prepare();// Before a controlled width change: captures a fresh anchor.
  const captured=anchor.anchor;
  assert.equal(anchor.pending,true);
  // Reflow-driven scroll while pending must not overwrite the anchor.
  feed.scrollTop=400;assert.equal(anchor.handleScroll(),false);
  frames.splice(0).forEach(fn=>fn());// capture frame skipped while pending
  assert.equal(anchor.anchor,captured);
  // The observer restores after reflow; the resulting scroll event is ours.
  setFactor(1.5);feed.clientWidth=600;anchor.resized();
  assert.equal(anchor.pending,false);
  assert.equal(anchor.handleScroll(),true);
  // A later user scroll is treated normally and refreshes the anchor.
  feed.scrollTop+=40;assert.equal(anchor.handleScroll(),false);
});

function fakeSidebarDom(viewport=1366){
  const doc={activeElement:null,documentElement:{clientWidth:viewport},body:new FakeElement(),listeners:{},
    addEventListener(type,fn){(this.listeners[type]||=[]).push(fn);},querySelector:()=>null};
  const queue=[];let ids=0;
  const win={innerWidth:viewport,listeners:{},addEventListener(type,fn){(this.listeners[type]||=[]).push(fn);},
    requestAnimationFrame:fn=>{queue.push(fn);return ++ids;},cancelAnimationFrame(){},
    flush(){while(queue.length)queue.shift()();}};
  const workarea=new FakeElement({rect:()=>({left:0,top:58})});workarea.clientWidth=viewport;
  const focusable=new FakeElement();
  const sidebar=new FakeElement({children:[focusable]});
  const toggle=new FakeElement(),divider=new FakeElement();
  for(const el of [focusable,sidebar,toggle,divider])el.ownerDoc=doc;
  const store=new Map();
  const storage={getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,v)};
  const calls={before:0};
  const make=()=>createSidebar({workarea,sidebar,toggle,divider,storage,beforeWidthChange:()=>calls.before++,win,doc});
  return {flush:()=>win.flush(),doc,win,workarea,sidebar,toggle,divider,focusable,store,storage,calls,make,
    setViewport(w){doc.documentElement.clientWidth=w;win.innerWidth=w;workarea.clientWidth=w;}};
}
const prefsOf=dom=>JSON.parse(dom.store.get('tableforge-sidebar'));

test('toggle hides and restores the last expanded width without saving zero',()=>{
  const dom=fakeSidebarDom();const api=dom.make();
  assert.equal(dom.workarea.style.props['--sidebar-w'],'260px');
  assert.equal(dom.toggle.attributes['aria-expanded'],'true');
  dom.doc.activeElement=dom.focusable;
  dom.toggle.dispatch('click');
  assert.equal(api.width(),0);
  assert.equal(dom.sidebar.inert,true);
  assert.equal(dom.toggle.attributes['aria-label'],'Show sidebar');
  assert.equal(dom.doc.activeElement,dom.toggle);// Focus leaves the hidden sidebar.
  assert.deepEqual(prefsOf(dom),{width:260,collapsed:true});
  dom.toggle.dispatch('click');
  assert.equal(api.width(),260);
  assert.equal(dom.toggle.title,'Hide sidebar');
  assert.ok(dom.calls.before>=2);// Reading anchor captured before each change.
});

test('drag-to-collapse keeps the pre-drag width; resistance release stays at min',()=>{
  const dom=fakeSidebarDom();const api=dom.make();
  dom.divider.dispatch('pointerdown',{clientX:260});
  dom.divider.dispatch('pointermove',{clientX:320});dom.flush();
  assert.equal(api.width(),320);
  dom.divider.dispatch('pointermove',{clientX:150});dom.flush();// Past min - travel: collapses live.
  assert.equal(api.width(),0);
  dom.divider.dispatch('pointermove',{clientX:205});dom.flush();// Back in resistance zone: stays collapsed.
  assert.equal(api.width(),0);
  dom.divider.dispatch('pointerup',{clientX:170});
  assert.deepEqual(prefsOf(dom),{width:260,collapsed:true});
  dom.toggle.dispatch('click');
  assert.equal(api.width(),260);

  dom.divider.dispatch('pointerdown',{clientX:260});
  dom.divider.dispatch('pointerup',{clientX:200});// Resistance zone release.
  assert.equal(api.width(),220);
  assert.deepEqual(prefsOf(dom),{width:220,collapsed:false});
});

test('cancelled drags revert; keyboard adjusts and saves',()=>{
  const dom=fakeSidebarDom();const api=dom.make();
  dom.divider.dispatch('pointerdown',{clientX:260});
  dom.divider.dispatch('pointermove',{clientX:350});dom.flush();
  dom.divider.dispatch('pointercancel',{});
  assert.equal(api.width(),260);
  dom.divider.dispatch('keydown',{key:'ArrowRight',shiftKey:false});
  assert.equal(api.width(),276);
  assert.equal(prefsOf(dom).width,276);
  assert.equal(dom.divider.attributes['aria-valuenow'],'276');
});

test('window resizing clamps for display without overwriting the remembered width',()=>{
  const dom=fakeSidebarDom();
  dom.store.set('tableforge-sidebar',JSON.stringify({width:400,collapsed:false}));
  const api=dom.make();
  assert.equal(api.width(),400);
  dom.setViewport(700);dom.win.listeners.resize.forEach(fn=>fn());dom.flush();
  assert.equal(api.width(),280);// 700 - 420 chat
  assert.equal(dom.store.get('tableforge-sidebar'),JSON.stringify({width:400,collapsed:false}));
  dom.setViewport(1366);dom.win.listeners.resize.forEach(fn=>fn());dom.flush();
  assert.equal(api.width(),400);
});

test('overlay mode starts closed, opens without taking layout space, and never writes preferences',()=>{
  const dom=fakeSidebarDom(600);const api=dom.make();
  assert.equal(api.isOverlay(),true);
  assert.equal(dom.workarea.classList.contains('sidebar-collapsed'),true);
  assert.equal(dom.sidebar.inert,true);
  dom.toggle.dispatch('click');
  assert.equal(dom.workarea.classList.contains('sidebar-collapsed'),false);
  assert.equal(api.width(),0);
  dom.doc.listeners.keydown.forEach(fn=>fn({key:'Escape',defaultPrevented:false}));
  assert.equal(dom.workarea.classList.contains('sidebar-collapsed'),true);
  assert.equal(dom.store.has('tableforge-sidebar'),false);
  dom.setViewport(1366);dom.win.listeners.resize.forEach(fn=>fn());dom.flush();
  assert.equal(api.isOverlay(),false);
  assert.equal(api.width(),260);
});
