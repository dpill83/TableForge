const {test}=require('node:test');
const assert=require('node:assert/strict');
const {fitView,toImage,toStage,zoomAt}=require('../web/js/table-map.js');

const close=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-9,`${actual} != ${expected}`);

test('fit centers the whole map inside the panel',()=>{
  const view=fitView(800,400,1000,1000);
  close(view.scale,0.38);
  close(view.x,(800-380)/2);close(view.y,(400-380)/2);
  assert.deepEqual(fitView(0,400,1000,1000),{scale:1,x:0,y:0});
});

test('token coordinates are the same at any pan or zoom',()=>{
  const point={x:0.3,y:0.8};
  for(const view of [{scale:1,x:0,y:0},{scale:0.25,x:-40,y:90},{scale:3.5,x:-1200,y:-600}]){
    const stage=toStage(view,640,480,point),back=toImage(view,640,480,stage.x,stage.y);
    close(back.x,point.x);close(back.y,point.y);
  }
});

test('dragging past the edge keeps the token on the map',()=>{
  const view={scale:1,x:10,y:10};
  assert.deepEqual(toImage(view,100,100,-50,500),{x:0,y:1});
});

test('zooming keeps the spot under the cursor in place and respects limits',()=>{
  const view={scale:1,x:20,y:30},image=toImage(view,1000,1000,300,200);
  const zoomed=zoomAt(view,300,200,2,0.5,4);
  close(zoomed.scale,2);
  const after=toImage(zoomed,1000,1000,300,200);
  close(after.x,image.x);close(after.y,image.y);
  close(zoomAt(view,0,0,100,0.5,4).scale,4);
  close(zoomAt(view,0,0,0.01,0.5,4).scale,0.5);
});
