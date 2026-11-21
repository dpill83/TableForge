const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const start=source.indexOf('  const request = async ');
const end=source.indexOf('  const notify = ',start);

test('ZIP uploads send original bytes with a longer deadline; JSON requests keep their deadline',async()=>{
  const calls=[],timers=[],cleared=[];
  const context=vm.createContext({Blob,AbortController,Error,JSON,
    setTimeout:(fn,ms)=>{timers.push(ms);return timers.length;},
    clearTimeout:id=>cleared.push(id),
    fetch:async(url,options)=>{calls.push({url,...options});return {ok:true,status:200,json:async()=>({id:'cartridge'})};},
  });
  vm.runInContext(source.slice(start,end)+';this.request=request;',context);
  const zip=new Blob(['zip bytes']);
  await context.request('cartridges',zip);
  await context.request('saves/save/locate-cartridge',zip);
  await context.request('saves',{name:'Test'});
  assert.equal(calls[0].body,zip);
  assert.equal(calls[1].body,zip);
  assert.equal(calls[0].headers['Content-Type'],'application/zip');
  assert.equal(calls[2].body,'{"name":"Test"}');
  assert.deepEqual(timers,[300000,300000,15000]);
  assert.deepEqual(cleared,[1,2,3]);
});

test('proxy size rejection gives a readable error even when its response is HTML',async()=>{
  const context=vm.createContext({Blob,AbortController,Error,JSON,setTimeout:()=>1,clearTimeout:()=>{},
    fetch:async()=>({status:413,json:async()=>{throw Error('Unexpected HTML');}}),
  });
  vm.runInContext(source.slice(start,end)+';this.request=request;',context);
  await assert.rejects(context.request('cartridges',new Blob(['zip'])),/upload is too large/);
});
