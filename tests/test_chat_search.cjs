const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync(require.resolve('../web/js/app.js'),'utf8');
const indexLine=source.split('\n').find(line=>line.includes('row.dataset.searchText=')&&line.includes('m.name'));
const searchLine=source.split('\n').find(line=>line.includes('const applySearch='));
assert.ok(indexLine&&searchLine,'The actual feed indexing and search handlers must exist');

function feed(messages){
  const rows=[];
  const elements={messageSearch:{value:''},searchCount:{textContent:''},feedInner:{append:row=>rows.push(row)}};
  const context=vm.createContext({$:id=>elements[id],document:{querySelectorAll:()=>rows}});
  for(const message of messages){
    const classes=new Set();
    context.m=message;
    context.row={dataset:{},classes,classList:{toggle(name,enabled){if(enabled)classes.add(name);else classes.delete(name);}}};
    vm.runInContext(indexLine,context);
  }
  vm.runInContext(searchLine+'\nthis.search=applySearch;',context);
  return {rows,search(query){elements.messageSearch.value=query;context.search();return elements.searchCount.textContent;}};
}

test('answer-only search finds the completed OOC exchange alongside normal chat',()=>{
  const f=feed([
    {name:'George',body:'Could I move away safely?',ooc:{status:'complete',answer:'Use Disengage to avoid opportunity attacks.'}},
    {name:'Ethereal',body:'I examine the door.'},
  ]);
  assert.equal(f.search('  OPPORTUNITY  '),1);
  assert.ok(f.rows[0].classes.has('search-match'));
  assert.ok(f.rows[1].classes.has('search-dim'));
  assert.equal(f.search('move away'),1);
  assert.equal(f.search('door'),1);
  assert.ok(f.rows[1].classes.has('search-match'));
  assert.ok(f.rows[0].classes.has('search-dim'));
  assert.equal(f.search('missing term'),0);
  assert.equal(f.search(''),'');
  assert.ok(f.rows.every(row=>!row.classes.has('search-match')&&!row.classes.has('search-dim')));
});

test('pending and failed exchanges do not index unpublished answer text',()=>{
  const f=feed(['pending','failed'].map(status=>({name:'George',body:'Can I try this?',ooc:{status,answer:'unpublished answer'}})));
  assert.equal(f.search('unpublished'),0);
  assert.equal(f.search('try this'),2);
});
