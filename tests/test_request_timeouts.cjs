const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const section=source.slice(source.indexOf('  const request = async (path, body) => {'),source.indexOf('}finally{clearTimeout(timer);}',source.indexOf('  const request = async'))+'}finally{clearTimeout(timer);}'.length)+'\n  };';

// Runs the real request() helper and reports the abort timeout it scheduled.
async function timeoutFor(path,body){
  const delays=[];
  const context=vm.createContext({
    AbortController,JSON,Error,Object,
    setTimeout:(fn,ms)=>{delays.push(ms);return 1;},clearTimeout:()=>{},
    fetch:async()=>({ok:true,status:200,json:async()=>({})}),
  });
  vm.runInContext(section+'\nthis.request=request;',context);
  await context.request(path,body);
  return delays[0];
}

test('Start Adventure waits as long as other AI generation requests', async()=>{
  assert.equal(await timeoutFor('saves/s/start',{playerId:'p',notes:''}),210000);
  assert.equal(await timeoutFor('saves/s/advance',{beat:1}),210000);
});

test('ordinary requests keep the short timeout', async()=>{
  assert.equal(await timeoutFor('saves/s/ready',{ready:true}),15000);
  assert.equal(await timeoutFor('saves/s'),15000);
});
