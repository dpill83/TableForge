/* Play-screen layout: the single resizable, collapsible left sidebar, and
   keeping the reader's paragraph in place when the chat column changes width.
   Sidebar width and collapsed state are per-browser preferences, separate
   from saves and shared player state. */
(function(root){
  // Provisional tuning values (see docs/SINGLE-SIDEBAR-PLAN.md).
  const DEFAULTS={width:260,min:220,max:400,collapseTravel:40,chatMin:420,keyStep:16};
  const STORAGE_KEY='tableforge-sidebar';
  const clamp=(value,low,high)=>Math.min(high,Math.max(low,value));

  // Widest sidebar that still leaves chatMin for the conversation; never below min.
  const maxWidth=(available,config=DEFAULTS)=>Math.max(config.min,Math.min(config.max,available-config.chatMin));
  // Below min sidebar + min chat, the sidebar floats over the chat instead.
  const isOverlay=(viewportWidth,config=DEFAULTS)=>viewportWidth<config.min+config.chatMin;

  // One drag position. `raw` is the width the pointer asks for. Past min the
  // sidebar holds at min until it has travelled collapseTravel further, then
  // collapses. Once collapsed in a gesture it only reopens when the pointer
  // comes back past the min line, so one gesture cannot flicker.
  const dragStep=(raw,{min,max,collapseTravel},collapsed)=>{
    if(raw>=min)return {collapsed:false,width:Math.min(raw,Math.max(min,max))};
    if(collapsed||raw<min-collapseTravel)return {collapsed:true,width:min};
    return {collapsed:false,width:min};
  };

  // Keyboard adjustment of the divider. Arrow keys never collapse.
  const keyWidth=(key,width,{min,max,keyStep},large=false)=>{
    const step=keyStep*(large?3:1);
    if(key==='ArrowLeft')return clamp(width-step,min,max);
    if(key==='ArrowRight')return clamp(width+step,min,max);
    if(key==='Home')return min;
    if(key==='End')return max;
    return null;
  };

  const parsePrefs=(text,config=DEFAULTS)=>{
    try{
      const value=JSON.parse(text);
      const width=Number(value?.width);
      return {width:Number.isFinite(width)&&width>0?Math.round(width):config.width,collapsed:value?.collapsed===true};
    }catch{return {width:config.width,collapsed:false};}
  };
  const serializePrefs=prefs=>JSON.stringify({width:Math.round(prefs.width),collapsed:!!prefs.collapsed});

  /* Reading-position anchor. Stored as data (row ID, block index, offset from
     the feed's top edge) because routine renders may rebuild the feed DOM. */
  const ROW_SELECTOR='.feed-inner > .message[id]';
  const BLOCK_SELECTOR='p,li,h1,h2,h3,h4,h5,h6,pre,blockquote,table,img';
  const FALLBACK_ROWS=3;
  const rowById=(feed,id)=>feed.querySelector(`[id="${String(id).replace(/["\\]/g,'\\$&')}"]`);
  const captureAnchor=(feed,following)=>{
    if(following)return {pinned:true};
    const feedTop=feed.getBoundingClientRect().top;
    const rows=[...feed.querySelectorAll(ROW_SELECTOR)];
    const first=rows.findIndex(row=>row.getBoundingClientRect().bottom>feedTop);
    if(first<0)return {pinned:false,rowId:null,index:-1,offset:0,fallbacks:[]};
    const row=rows[first];
    // Long AI-DM replies can be taller than the viewport, so prefer the first
    // paragraph-level block at or below the top edge over the row itself.
    const blocks=[...row.querySelectorAll(BLOCK_SELECTOR)];
    const index=blocks.findIndex(block=>block.getBoundingClientRect().top>=feedTop-0.5);
    const element=index>=0?blocks[index]:row;
    return {
      pinned:false,rowId:row.id,index,offset:element.getBoundingClientRect().top-feedTop,
      fallbacks:rows.slice(first+1,first+1+FALLBACK_ROWS).map(next=>({rowId:next.id,offset:next.getBoundingClientRect().top-feedTop}))
    };
  };
  // The absolute scrollTop that puts the anchor back at its offset, or null
  // when nothing survives (the numeric position is then left alone).
  const anchorTop=(feed,anchor)=>{
    if(!anchor)return null;
    if(anchor.pinned)return feed.scrollHeight;
    if(!anchor.rowId)return null;
    const feedTop=feed.getBoundingClientRect().top;
    const place=(element,offset)=>feed.scrollTop+(element.getBoundingClientRect().top-feedTop)-offset;
    const row=rowById(feed,anchor.rowId);
    if(row){
      const element=anchor.index>=0?row.querySelectorAll(BLOCK_SELECTOR)[anchor.index]:row;
      if(element)return place(element,anchor.offset);
    }
    for(const fallback of anchor.fallbacks||[]){
      const next=rowById(feed,fallback.rowId);
      if(next)return place(next,fallback.offset);
    }
    return null;
  };

  /* Keeps an anchor current while the reader scrolls, takes a fresh one before
     TableForge itself changes the chat width, and restores it after reflow.
     A resize observer only runs after layout, so it never captures. */
  class FeedAnchor{
    constructor({feed,isFollowing,raf=root.requestAnimationFrame?.bind(root),now=()=>Date.now()}){
      this.feed=feed;this.isFollowing=isFollowing;this.raf=raf||(fn=>setTimeout(fn,16));this.now=now;
      this.anchor=null;this.pending=false;this.pendingToken=0;this.expected=null;this.frame=false;
      this.lastWidth=feed.clientWidth;
      if(typeof root.ResizeObserver==='function')new root.ResizeObserver(()=>this.resized()).observe(feed);
    }
    capture(){
      if(!this.feed.clientWidth)return;// Hidden screen: keep the last good anchor.
      this.anchor=captureAnchor(this.feed,this.isFollowing());
    }
    // Call synchronously before applying a width change TableForge initiates.
    prepare(){
      if(!this.pending)this.capture();
      this.pending=true;
      // If the width did not actually change, no resize follows; stop
      // suppressing scroll updates after the next frames regardless.
      const token=++this.pendingToken;
      this.raf(()=>this.raf(()=>{if(this.pendingToken===token)this.pending=false;}));
    }
    resized(){
      const width=this.feed.clientWidth;
      if(!width||width===this.lastWidth)return;// Height-only changes keep today's behavior.
      this.lastWidth=width;
      this.restore();
    }
    restore(){
      const top=anchorTop(this.feed,this.anchor);
      if(top!==null){
        this.feed.scrollTop=top;
        this.expected={top:this.feed.scrollTop,at:this.now()};
      }
      this.pending=false;
    }
    /* Call first from the feed's scroll listener. Returns true when the event
       came from restoration, so follow-latest and Jump to latest stay as they
       were. Otherwise refreshes the anchor (once per frame) unless a width
       change is pending, when reflow-driven scrolls must not overwrite it. */
    handleScroll(){
      const expected=this.expected;this.expected=null;
      if(expected&&this.now()-expected.at<500&&Math.abs(this.feed.scrollTop-expected.top)<1)return true;
      if(!this.pending&&!this.frame){
        this.frame=true;
        this.raf(()=>{this.frame=false;if(!this.pending)this.capture();});
      }
      return false;
    }
  }

  /* Sidebar controller. beforeWidthChange runs synchronously before every
     width change TableForge initiates; mapWidth reports space the table map
     takes from the chat column. */
  function createSidebar({workarea,sidebar,toggle,divider,storage,beforeWidthChange=()=>{},mapWidth=()=>0,config=DEFAULTS,win=root,doc=root.document}){
    let prefs={width:config.width,collapsed:false};
    try{prefs=parsePrefs(storage?.getItem(STORAGE_KEY),config);}catch{/* Defaults. */}
    let overlay=false,overlayOpen=false,displayWidth=prefs.width,drag=null,frame=0;
    const save=()=>{try{storage?.setItem(STORAGE_KEY,serializePrefs(prefs));}catch{/* Not remembered. */}};
    const viewportWidth=()=>doc.documentElement.clientWidth||win.innerWidth||0;
    const currentMax=()=>maxWidth((workarea.clientWidth||viewportWidth())-mapWidth(),config);
    const collapsed=()=>drag?drag.collapsed:overlay?!overlayOpen:prefs.collapsed;
    const effectiveWidth=()=>collapsed()||overlay?0:displayWidth;

    const render=()=>{
      const hidden=collapsed();
      workarea.classList.toggle('sidebar-overlay',overlay);
      workarea.classList.toggle('sidebar-collapsed',hidden);
      workarea.classList.toggle('sidebar-resizing',!!drag);
      workarea.style.setProperty('--sidebar-w',`${effectiveWidth()}px`);
      workarea.style.setProperty('--sidebar-overlay-w',`${config.min}px`);
      sidebar.inert=hidden;
      if(hidden)sidebar.setAttribute('aria-hidden','true');else sidebar.removeAttribute('aria-hidden');
      const label=hidden?'Show sidebar':'Hide sidebar';
      toggle.setAttribute('aria-expanded',String(!hidden));
      toggle.setAttribute('aria-label',label);toggle.title=label;
      const max=currentMax();
      divider.setAttribute('aria-valuemin',String(config.min));
      divider.setAttribute('aria-valuemax',String(max));
      divider.setAttribute('aria-valuenow',String(Math.round(displayWidth)));
    };
    // Recheck bounds (window resize, map changes). Clamping for display never
    // overwrites the remembered width.
    const refresh=()=>{
      const wasOverlay=overlay;
      overlay=isOverlay(viewportWidth(),config);
      if(overlay&&!wasOverlay)overlayOpen=false;// Overlay starts closed.
      if(!drag)displayWidth=clamp(prefs.width,config.min,currentMax());
      render();
    };
    const focusToggleIfInside=()=>{if(sidebar.contains(doc.activeElement))toggle.focus();};

    toggle.addEventListener('click',()=>{
      const hiding=!collapsed();
      beforeWidthChange();
      if(hiding)focusToggleIfInside();
      if(overlay)overlayOpen=!overlayOpen;
      else{prefs.collapsed=hiding;save();}
      refresh();
    });
    doc.addEventListener('keydown',event=>{
      if(event.key!=='Escape'||!overlay||!overlayOpen||event.defaultPrevented)return;
      if(doc.querySelector('#modalRoot .overlay'))return;// Let dialogs handle Escape.
      beforeWidthChange();focusToggleIfInside();overlayOpen=false;render();
    });

    const workareaLeft=()=>workarea.getBoundingClientRect().left;
    const step=clientX=>{
      if(!drag)return;
      const result=dragStep(clientX-workareaLeft()-drag.grab,{...config,max:currentMax()},drag.collapsed);
      beforeWidthChange();
      drag.collapsed=result.collapsed;
      if(!result.collapsed)displayWidth=result.width;
      render();
    };
    const endDrag=commit=>{
      if(!drag)return;
      const gesture=drag;drag=null;
      if(frame){win.cancelAnimationFrame?.(frame);frame=0;}
      divider.classList.remove('active');doc.body.classList.remove('sidebar-dragging');
      beforeWidthChange();
      if(commit){
        // A collapse keeps the width from before the drag; release in the
        // resistance zone leaves the sidebar at min.
        if(gesture.collapsed){prefs.collapsed=true;displayWidth=gesture.startWidth;}
        else{prefs.collapsed=false;prefs.width=Math.round(displayWidth);}
        save();
      }else displayWidth=gesture.startWidth;
      refresh();
      if(prefs.collapsed&&commit)toggle.focus();
    };
    divider.addEventListener('pointerdown',event=>{
      if(event.button!==0||overlay||collapsed())return;
      event.preventDefault();
      try{divider.setPointerCapture(event.pointerId);}catch{/* Still resizes over the divider. */}
      drag={pointerId:event.pointerId,startWidth:displayWidth,grab:event.clientX-(workareaLeft()+displayWidth),collapsed:false,x:event.clientX};
      divider.classList.add('active');doc.body.classList.add('sidebar-dragging');
      render();
    });
    divider.addEventListener('pointermove',event=>{
      if(!drag||event.pointerId!==drag.pointerId)return;
      drag.x=event.clientX;
      if(!frame)frame=win.requestAnimationFrame(()=>{frame=0;if(drag)step(drag.x);});
    });
    divider.addEventListener('pointerup',event=>{
      if(!drag||event.pointerId!==drag.pointerId)return;
      step(event.clientX);endDrag(true);
    });
    divider.addEventListener('pointercancel',event=>{if(drag&&event.pointerId===drag.pointerId)endDrag(false);});
    divider.addEventListener('lostpointercapture',event=>{if(drag&&event.pointerId===drag.pointerId)endDrag(false);});
    divider.addEventListener('keydown',event=>{
      if(overlay||collapsed())return;
      const next=keyWidth(event.key,displayWidth,{...config,max:currentMax()},event.shiftKey);
      if(next===null)return;
      event.preventDefault();
      beforeWidthChange();
      prefs.width=next;displayWidth=next;save();refresh();
    });
    win.addEventListener('resize',()=>{if(!frame)frame=win.requestAnimationFrame(()=>{frame=0;if(drag)step(drag.x);else refresh();});});

    refresh();
    return {
      refresh,
      // Width the sidebar currently takes from the layout (0 when hidden or floating).
      width:effectiveWidth,
      isOverlay:()=>overlay,
      config,
    };
  }

  const api={DEFAULTS,STORAGE_KEY,maxWidth,isOverlay,dragStep,keyWidth,parsePrefs,serializePrefs,captureAnchor,anchorTop,FeedAnchor,createSidebar};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.TableForgeLayout=api;
})(typeof window==='undefined'?globalThis:window);
