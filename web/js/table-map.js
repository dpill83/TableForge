/* Shared table map viewer: pan/zoom an image and drag one party token.
   Pan and zoom stay local to each viewer. The token position is reported in
   normalized image coordinates (0..1), so every screen agrees on it. */
(function(root){
  const clamp=(value,low,high)=>Math.min(high,Math.max(low,value));
  // A view maps image pixels to stage pixels: stage = image*scale + offset.
  const fitView=(stageW,stageH,imageW,imageH)=>{
    if(!(stageW>0&&stageH>0&&imageW>0&&imageH>0))return {scale:1,x:0,y:0};
    const scale=Math.min(stageW/imageW,stageH/imageH)*0.95;
    return {scale,x:(stageW-imageW*scale)/2,y:(stageH-imageH*scale)/2};
  };
  const toImage=(view,imageW,imageH,stageX,stageY)=>({
    x:clamp((stageX-view.x)/(view.scale*imageW),0,1),
    y:clamp((stageY-view.y)/(view.scale*imageH),0,1)});
  const toStage=(view,imageW,imageH,point)=>({x:view.x+point.x*imageW*view.scale,y:view.y+point.y*imageH*view.scale});
  // Zoom around a stage point so the spot under the cursor stays put.
  const zoomAt=(view,stageX,stageY,factor,minScale,maxScale)=>{
    const scale=clamp(view.scale*factor,minScale,maxScale),ratio=scale/view.scale;
    return {scale,x:stageX-(stageX-view.x)*ratio,y:stageY-(stageY-view.y)*ratio};
  };

  class TableMapView {
    constructor({stage,layer,image,token,onMove,onViewChange=()=>{}}){
      Object.assign(this,{stage,layer,image,token,onMove,onViewChange});
      this.view={scale:1,x:0,y:0};this.position=null;this.dragging=false;this.pointers=new Map();
      this.image.addEventListener('load',()=>{this.fit();});
      stage.addEventListener('pointerdown',event=>this.pointerDown(event));
      stage.addEventListener('pointermove',event=>this.pointerMove(event));
      for(const type of ['pointerup','pointercancel'])stage.addEventListener(type,event=>this.pointerUp(event));
      stage.addEventListener('wheel',event=>{
        if(!this.ready())return;event.preventDefault();
        const box=stage.getBoundingClientRect();
        this.setView(zoomAt(this.view,event.clientX-box.left,event.clientY-box.top,Math.exp(-event.deltaY*0.0015),...this.limits()));
      },{passive:false});
      token.addEventListener('keydown',event=>this.key(event));
      if(typeof ResizeObserver==='function')new ResizeObserver(()=>this.paint()).observe(stage);
    }
    ready(){return this.image.naturalWidth>0&&!!this.image.getAttribute('src');}
    size(){return {w:this.image.naturalWidth,h:this.image.naturalHeight};}
    limits(){const fit=fitView(this.stage.clientWidth,this.stage.clientHeight,this.size().w,this.size().h).scale;return [fit*0.5,Math.max(fit*8,2)];}
    setImage(url){
      if(this.image.getAttribute('src')===url)return;
      this.cancelDrag();this.position=null;
      if(url)this.image.setAttribute('src',url);else this.image.removeAttribute('src');
      this.paint();
    }
    fit(){if(!this.ready())return;this.setView(fitView(this.stage.clientWidth,this.stage.clientHeight,this.size().w,this.size().h));}
    setView(view){this.view=view;this.paint();this.onViewChange(view);}
    // Server positions never override a drag in progress.
    setPosition(point){if(!this.dragging){this.position=point?{x:point.x,y:point.y}:null;this.paint();}}
    center(){
      if(!this.ready())return null;
      return toImage(this.view,this.size().w,this.size().h,this.stage.clientWidth/2,this.stage.clientHeight/2);
    }
    focusToken(){
      if(!this.ready()||!this.position)return;
      const at=toStage(this.view,this.size().w,this.size().h,this.position);
      this.setView({...this.view,x:this.view.x+this.stage.clientWidth/2-at.x,y:this.view.y+this.stage.clientHeight/2-at.y});
    }
    paint(){
      const ready=this.ready();
      this.layer.style.transform=`translate(${this.view.x}px,${this.view.y}px) scale(${this.view.scale})`;
      this.token.classList.toggle('hidden',!ready||!this.position);
      if(ready&&this.position){
        const at=toStage(this.view,this.size().w,this.size().h,this.position);
        this.token.style.left=`${at.x}px`;this.token.style.top=`${at.y}px`;
      }
    }
    local(event){const box=this.stage.getBoundingClientRect();return {x:event.clientX-box.left,y:event.clientY-box.top};}
    pointerDown(event){
      if(!this.ready()||event.button>0)return;
      try{this.stage.setPointerCapture(event.pointerId);}catch{/* Dragging still works inside the stage. */}
      this.pointers.set(event.pointerId,this.local(event));
      if(this.pointers.size===1&&this.token.contains(event.target)&&this.position){
        this.dragging=true;this.moved=false;this.before={...this.position};this.token.classList.add('dragging');
      }else if(this.pointers.size===2){this.cancelDrag();this.pinch=this.pinchState();}
      event.preventDefault();
    }
    pointerMove(event){
      if(!this.pointers.has(event.pointerId))return;
      const last=this.pointers.get(event.pointerId),now=this.local(event);this.pointers.set(event.pointerId,now);
      if(this.dragging){
        this.position=toImage(this.view,this.size().w,this.size().h,now.x,now.y);this.moved=true;this.paint();
      }else if(this.pointers.size===2&&this.pinch){
        const next=this.pinchState(),zoomed=zoomAt(this.view,next.x,next.y,next.distance/this.pinch.distance,...this.limits());
        this.setView({...zoomed,x:zoomed.x+next.x-this.pinch.x,y:zoomed.y+next.y-this.pinch.y});this.pinch=next;
      }else if(this.pointers.size===1){
        this.setView({...this.view,x:this.view.x+now.x-last.x,y:this.view.y+now.y-last.y});
      }
    }
    pointerUp(event){
      if(!this.pointers.delete(event.pointerId))return;
      this.pinch=null;
      if(this.dragging){
        this.dragging=false;this.token.classList.remove('dragging');
        if(this.moved)this.onMove({...this.position},{...this.before});
      }
    }
    pinchState(){
      const [a,b]=[...this.pointers.values()];
      return {x:(a.x+b.x)/2,y:(a.y+b.y)/2,distance:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y))};
    }
    cancelDrag(){
      if(this.dragging){this.position=this.before;this.dragging=false;this.token.classList.remove('dragging');}
    }
    key(event){
      const steps={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
      if(!steps||!this.position||this.dragging)return;
      event.preventDefault();
      const step=event.shiftKey?0.05:0.01,before={...this.position};
      this.position={x:clamp(before.x+steps[0]*step,0,1),y:clamp(before.y+steps[1]*step,0,1)};
      this.paint();this.onMove({...this.position},before);
    }
  }
  const api={TableMapView,fitView,toImage,toStage,zoomAt};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.TableForgeMap=api;
})(typeof window==='undefined'?globalThis:window);
