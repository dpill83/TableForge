(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const screens = [...document.querySelectorAll('.screen')];
  const state = {cartridge:null, save:null, identity:sessionStorage.getItem('tableforge-player'), pilot:false, left:false, right:false, composer:false, generating:false, asking:false, updating:false, bindingRequest:0};
  $('appVersion').textContent = 'v2.0';
  const request = async (path, body) => {
    const response = await fetch('/api/' + path, {method:body === undefined ? 'GET':'POST', headers:{'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
    const result = await response.json();
    if(!response.ok) throw Error(result.error || `Request failed (${response.status})`);
    return result;
  };
  const notify = error => alert(error.message || String(error));
  const runtimeLabel = info => (info.provider === 'openai' ? 'OpenAI' : 'Mock AI') + ' · ' + info.model;
  const showRuntime = async () => {
    const info = await request('runtime');
    $('runtimeProvider').textContent = info.provider === 'openai' ? 'OpenAI' : 'Mock AI';
    $('runtimeModel').textContent = info.model;
    return info;
  };
  const show = async id => {
    screens.forEach(el => el.classList.toggle('active', el.id === id));
    if(id === 'load') await refreshSaves();
    if(id === 'options') await showRuntime();
    if(id === 'play') $('feed').scrollTop = $('feed').scrollHeight;
  };
  document.querySelectorAll('[data-go]').forEach(btn => btn.onclick = () => show(btn.dataset.go).catch(notify));

  // Cartridge selection happens on the server; no file is assumed valid by its name.
  const bytes64 = async file => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let out = '';
    for(let i=0;i<bytes.length;i+=8192) out += String.fromCharCode(...bytes.subarray(i,i+8192));
    return btoa(out);
  };
  const cartridgePayload = async items => items.length === 1 && /\.zip$/i.test(items[0].name)
    ? {kind:'zip', data:await bytes64(items[0])}
    : {kind:'files', files:await Promise.all(items.map(async file => ({name:file.webkitRelativePath || file.name,data:await bytes64(file)})))};
  const selectedFiles = async files => {
    const items = [...files];
    if(!items.length) return;
    const upload=++state.bindingRequest;
    state.cartridge=null;
    renderCartridge();
    try {
      const cartridge = await request('cartridges', await cartridgePayload(items));
      if(upload!==state.bindingRequest) return;
      state.cartridge = cartridge;
      $('setupSaveName').value=state.cartridge.title;
      renderCartridge();
    } catch(error) { if(upload===state.bindingRequest) notify(error); }
  };
  $('browseFiles').onclick = () => $('filesInput').click();
  $('browseFolder').onclick = () => $('folderInput').click();
  $('filesInput').onchange = event => selectedFiles(event.target.files);
  $('folderInput').onchange = event => selectedFiles(event.target.files);
  $('removeCartridge').onclick = () => {state.cartridge=null; state.bindingRequest++; renderCartridge();};
  $('demoCartridge').onclick = async event => {
    event.preventDefault();
    const upload=++state.bindingRequest;
    state.cartridge=null;
    renderCartridge();
    try {
      const moduleText = '# Dress Rehearsal at Hollow Well\n\nExample cartridge for testing the TableForge interface.';
      const runData = JSON.stringify({title:'Dress Rehearsal at Hollow Well', sample:true});
      const cartridge = await request('cartridges', {kind:'files', files:[
        {name:'module.md', data:btoa(moduleText)},
        {name:'run-data.json', data:btoa(runData)}
      ]});
      if(upload!==state.bindingRequest) return;
      state.cartridge=cartridge;
      $('setupSaveName').value=state.cartridge.title;
      renderCartridge();
    } catch(error) { if(upload===state.bindingRequest) notify(error); }
  };
  const drop = $('dropZone');
  drop.ondragover = event => {event.preventDefault(); drop.classList.add('dragover');};
  drop.ondragleave = () => drop.classList.remove('dragover');
  drop.ondrop = event => {event.preventDefault(); drop.classList.remove('dragover'); selectedFiles(event.dataTransfer.files);};
  const renderCartridge = () => {
    const c=state.cartridge;
    $('cartridgeSummary').classList.toggle('hidden', !c);
    if(!c) return;
    const card=$('cartridgeSummary');
    card.querySelector('strong').textContent=c.title;
    const grid=card.querySelector('.grid');
    grid.innerHTML=Object.entries(c.resources).map(([label,file]) => {
      const issue=c.invalid?.[label];
      const required=c.missing.includes(label);
      const status=issue?'Invalid':required?'Required':file?'Found':'Optional';
      const tone=issue||required?'bad':file?'ok':'warn';
      const missingOption=file && !c.files.includes(file) ? `<option value="${esc(file)}">Missing: ${esc(file)}</option>` : '';
      return `<label class="binding ${tone}"><div class="row"><strong>${esc(label)}</strong><span>${status}</span></div><select data-resource="${esc(label)}"><option value="">${required?'Select required file':'Not selected'}</option>${missingOption}${c.files.map(path=>`<option value="${esc(path)}">${esc(path)}</option>`).join('')}</select>${issue?`<span class="binding-issue">${esc(issue)}</span>`:''}</label>`;
    }).join('');
    grid.querySelectorAll('select[data-resource]').forEach(select=>{
      select.value=c.resources[select.dataset.resource] || '';
      select.onchange=async()=>{
        const current=state.cartridge;
        current.resources[select.dataset.resource]=select.value || null;
        current.validating=true;
        current.validationError=null;
        const sequence=++state.bindingRequest;
        card.querySelector('[data-go="setup"]').disabled=true;
        card.querySelector('.pill').textContent='Checking bindings';
        try {
          const previousTitle=current.title;
          const result=await request('cartridges/'+current.id+'/validate',{resources:current.resources});
          if(state.cartridge!==current || sequence!==state.bindingRequest) return;
          Object.assign(current,result);
          if($('setupSaveName').value===previousTitle) $('setupSaveName').value=current.title;
        } catch(error) {
          if(state.cartridge!==current || sequence!==state.bindingRequest) return;
          current.validationError=error.message;
          notify(error);
        } finally {
          if(state.cartridge===current && sequence===state.bindingRequest) {
            current.validating=false;
            renderCartridge();
          }
        }
      };
    });
    const next=card.querySelector('[data-go="setup"]');
    next.disabled=!!(c.validating || c.validationError || c.missing.length || Object.keys(c.invalid || {}).length);
    card.querySelector('.pill').textContent=c.validating?'Checking bindings':c.validationError?'Validation failed':c.missing.length?'Required content missing':Object.keys(c.invalid || {}).length?'Invalid binding':'Ready';
    $('setupAdventureTitle').textContent=c.title;
    $('setupResourceSummary').innerHTML=Object.entries(c.resources).map(([label,file])=>`<div class="binding ${c.invalid?.[label]||c.missing.includes(label)?'bad':file?'ok':'warn'}"><strong>${esc(label)}</strong><div class="muted">${esc(file || 'Not selected')}</div></div>`).join('');
  };
  // The setup retains the approved player list, but never writes it until Begin Adventure.
  const rows=$('playerRows');
  const addRow=(name='',character='')=>{
    const row=document.createElement('div'); row.className='player-row';
    row.innerHTML='<label>Player<input placeholder="Player name"></label><label>Character<input placeholder="Character name"></label><button class="btn" type="button" title="Remove">×</button>';
    row.querySelectorAll('input')[0].value=name;
    row.querySelectorAll('input')[1].value=character;
    row.querySelector('button').onclick=()=>row.remove(); rows.append(row);
  };
  [['Dan','George'],['Dani','Ethereal'],['Ted','Viktor']].forEach(pair=>addRow(...pair));
  $('addPlayer').onclick=()=>addRow();
  $('beginAdventure').onclick=async()=>{
    if(!state.cartridge || state.cartridge.validating || state.cartridge.validationError || state.cartridge.missing.length || Object.keys(state.cartridge.invalid || {}).length) return notify(Error('Choose a playable cartridge first'));
    const players=[...rows.querySelectorAll('.player-row')].map(row=>{
      const inputs=row.querySelectorAll('input');
      return {name:inputs[0].value.trim(),character:inputs[1].value.trim()};
    });
    try {state.save=await request('saves',{cartridgeId:state.cartridge.id,resources:state.cartridge.resources,name:$('setupSaveName').value,players});state.identity=null;renderJoin();show('join');}
    catch(error){notify(error);}
  };
  const refreshSaves=async()=>{
    const result=await request('saves');
    const panel=$('load').querySelector('.card'); panel.replaceChildren();
    if(!result.saves.length){panel.textContent='No saved adventures yet.'; return;}
    result.saves.forEach(save=>{
      const row=document.createElement('div');row.className='binding '+(save.cartridgeAvailable?'ok':'bad');
      const session=save.session_ended_at?`Session ${save.session_number} ended · Next: Session ${save.session_number+1}`:`Session ${save.session_number} open`;
      row.innerHTML=`<div class="row"><div><strong>${esc(save.name)}</strong><div class="muted">${esc(save.title)} · ${esc(session)} · ${new Date(save.updated_at).toLocaleString()}</div>${save.cartridgeAvailable?'':'<div class="binding-issue">Cartridge missing. Locate the original package to continue.</div>'}</div><div class="actions" style="margin-top:0"><button class="btn primary continue-save" ${save.cartridgeAvailable?'':'disabled'}>Continue</button>${save.cartridgeAvailable?'':'<button class="btn locate-zip">Locate ZIP</button><button class="btn locate-folder">Locate Folder</button>'}</div></div>`;
      row.querySelector('.continue-save').onclick=async()=>{try{state.save=await request('saves/'+save.id);renderJoin();show('join');}catch(error){notify(error);}};
      if(!save.cartridgeAvailable){
        for(const [selector,folder] of [['.locate-zip',false],['.locate-folder',true]]){
          const input=document.createElement('input');input.type='file';input.className='hidden';
          if(folder){input.multiple=true;input.setAttribute('webkitdirectory','');}else input.accept='.zip';
          row.append(input);
          row.querySelector(selector).onclick=()=>input.click();
          input.onchange=async()=>{
            const items=[...input.files];if(!items.length)return;
            row.querySelectorAll('button').forEach(button=>button.disabled=true);
            try{await request('saves/'+save.id+'/locate-cartridge',await cartridgePayload(items));await refreshSaves();}
            catch(error){notify(error);row.querySelectorAll('button').forEach(button=>button.disabled=false);}
          };
        }
      }
      panel.append(row);
    });
  };
  const renderJoin=()=>{
    const wrap=$('identityChoices');wrap.replaceChildren();
    state.save?.players.forEach(player=>{
      const button=document.createElement('button');button.className='identity-choice';
      button.innerHTML=`<div class="party-avatar">${esc(player.character[0])}</div><div><strong>${esc(player.character)}</strong><span>${esc(player.name)}</span></div><span class="pill">Join</span>`;
      button.onclick=async()=>{
        button.disabled=true;
        try{
          if(state.save.sessions.at(-1)?.ended_at) state.save=await request('saves/'+state.save.save.id+'/start-session',{playerId:player.id});
          state.identity=player.id;sessionStorage.setItem('tableforge-player',player.id);render();await show('play');
        }catch(error){notify(error);button.disabled=false;}
      };wrap.append(button);
    });
  };
  const update=async (action,body) => {
    if(state.updating || state.generating) return false;
    state.updating=true;
    render();
    try {state.save=await request('saves/'+state.save.save.id+'/'+action,body);return true;}
    catch(error){notify(error);return false;}
    finally {state.updating=false;render();}
  };
  const fillPilotThread = () => {
    const thread=$('pilotThread');
    if(!thread||!state.save) return;
    const atBottom=thread.scrollHeight-thread.scrollTop-thread.clientHeight<48;
    thread.replaceChildren();
    for(const m of state.save.pilot||[]){
      const row=document.createElement('div');
      row.className='pilot-line'+(m.kind==='ai'?' ai':'');
      const name=document.createElement('strong');
      name.textContent=m.name;
      const body=document.createElement('div');
      body.textContent=m.body;
      row.append(name, body);
      thread.append(row);
    }
    if(atBottom) thread.scrollTop=thread.scrollHeight;
    const send=$('pilotSend'), field=$('pilotAsk'), status=$('pilotAskStatus');
    if(send) send.disabled=!state.identity||state.asking||state.generating;
    if(field) field.disabled=!!(state.asking||state.generating);
    if(status) status.textContent=state.asking?'The AI-DM is responding…':'';
  };
  const render=()=>{
    const s=state.save;if(!s)return;
    $('play').querySelector('.top-title strong').textContent=s.cartridge.title;
    $('partyList').innerHTML=s.players.map(p=>`<div class="party-card" style="${p.id===state.identity?'border-color:var(--accent2)':''}"><div class="party-top"><div class="party-avatar">${esc(p.character[0])}</div><div class="party-name"><strong>${esc(p.character)}</strong><span>${esc(p.name)}</span></div><span class="ready-badge ${p.ready?'ready':''}">${p.ready?'Ready':'Not Ready'}</span></div></div>`).join('');
    $('feedInner').replaceChildren();
    for(const m of s.messages){
      const row=document.createElement('div');row.className='message '+(m.kind==='ai'?'ai':'player');
      row.innerHTML=`<div class="avatar">${esc(m.kind==='ai'?'AI':m.name[0])}</div><div><div class="message-head"><strong>${esc(m.name)}</strong><span class="time">${new Date(m.created_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}</span></div><div class="message-body"></div><div class="message-actions"><button class="copy-message">Copy</button></div></div>`;
      row.querySelector('.message-body').textContent=m.body;
      row.querySelector('.message-body').style.whiteSpace='pre-wrap';
      row.querySelector('.copy-message').onclick=async event=>{await navigator.clipboard.writeText(m.body);event.target.textContent='Copied';setTimeout(()=>event.target.textContent='Copy',1200);};
      row.dataset.searchText=(m.name+' '+m.body).toLowerCase();$('feedInner').append(row);
    }
    applySearch();$('feed').scrollTop=$('feed').scrollHeight;
    const current=s.players.find(p=>p.id===state.identity);
    $('readyBtn').disabled=!current||state.generating||state.updating;
    $('sendBtn').disabled=!current||state.generating||state.updating;
    $('composer').disabled=state.generating||state.updating;
    $('readyBtn').querySelector('.ready-label').textContent=current?.ready?'Unready':'Ready';
    $('readyBtn').classList.toggle('ready',!!current?.ready);
    $('tableStatus').textContent=state.generating?'The AI-DM is responding…':`Session ${s.sessions.at(-1)?.number || 1} · ${s.save.mode==='combat'?'Combat Mode · ':''}${s.players.filter(p=>p.ready).length} of ${s.players.length} Ready`;
    $('combatToggle').classList.toggle('hidden',s.save.mode==='combat');
    $('resumeCombat').classList.toggle('hidden',s.save.mode!=='combat');
    $('combatToggle').disabled=state.generating||state.updating;
    $('resumeCombat').disabled=state.generating||state.updating;
    $('endSession').disabled=state.generating||state.updating;
    fillPilotThread();
  };
  const advanceTable = async (extra={}) => {
    if(state.generating || state.updating || state.asking) return;
    state.generating = true;
    render();
    try {
      state.save = await request('saves/'+state.save.save.id+'/advance', {beat:state.save.save.beat, ...extra});
    } catch(error) { notify(error); }
    finally {
      state.generating = false;
      if(state.save) render();
    }
  };
  $('sendBtn').onclick=async()=>{
    const field=$('composer'),body=field.value.trim();if(!body)return;
    if(await update('messages',{playerId:state.identity,text:body})) {
      field.value='';resize();
    }
  };
  $('readyBtn').onclick=async()=>{
    const current=state.save.players.find(p=>p.id===state.identity);
    if(!current) return;
    if(await update('ready',{playerId:state.identity,ready:!current.ready}) &&
       state.save.save.mode==='normal' && state.save.players.every(p=>p.ready)) await advanceTable();
  };
  $('readyOverride').onclick=()=>confirmBox('Ready Override','Advance the table without waiting for every player?',()=>advanceTable({override:true}));
  $('combatToggle').onclick=()=>update('mode',{mode:'combat',playerId:state.identity});
  $('resumeCombat').onclick=()=>{
    modal('<h3>Resume AI-DM</h3><p>Summarize the combat outcome. It will be saved and included when the AI-DM next advances.</p><label>Combat outcome<textarea id="combatOutcome" rows="5" maxlength="20000" placeholder="What happened in combat?"></textarea></label><div class="actions"><button class="btn" data-close>Cancel</button><button class="btn good" id="submitCombatOutcome">Save outcome</button></div>');
    $('submitCombatOutcome').onclick=async()=>{
      const outcome=$('combatOutcome').value.trim();if(!outcome)return notify(Error('Enter a combat outcome.'));
      if(await update('combat-outcome',{playerId:state.identity,text:outcome})) $('modalRoot').replaceChildren();
    };
  };
  $('endSession').onclick=()=>{
    modal('<h3>End Session</h3><p>Save a checkpoint and close this session. Continuing later opens the next session.</p><label>Session note (optional)<textarea id="sessionNote" rows="4" maxlength="10000" placeholder="Where did the table leave off?"></textarea></label><div class="actions"><button class="btn" data-close>Cancel</button><button class="btn warn" id="submitEndSession">End Session</button></div>');
    $('submitEndSession').onclick=async()=>{
      const note=$('sessionNote').value.trim();
      if(await update('end-session',{playerId:state.identity,note})){$('modalRoot').replaceChildren();await show('load');}
    };
  };
  const field=$('composer');
  function resize(){field.style.height='auto';field.style.height=(field.value?Math.min(Math.max(field.scrollHeight,48),184):48)+'px';field.style.overflowY=field.scrollHeight>184?'auto':'hidden';}
  field.addEventListener('input',resize);
  field.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('sendBtn').click();}});
  $('emojiBtn').onclick=()=>{field.value+=' 🙂';resize();field.focus();};
  // Attachments are intentionally disabled until byte storage is implemented.
  $('attachmentBtn').onclick=()=>modal('<h3>Attachments</h3><p>File attachments are coming in a later build.</p><div class="actions"><button class="btn" data-close>Close</button></div>');
  const modal=html=>{const root=$('modalRoot');root.innerHTML=`<div class="overlay"><div class="modal">${html}</div></div>`;root.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>root.replaceChildren());root.querySelector('.overlay').onclick=e=>{if(e.target.classList.contains('overlay'))root.replaceChildren();};};
  const confirmBox=(title,message,callback)=>{modal(`<h3>${esc(title)}</h3><p>${esc(message)}</p><div class="actions"><button class="btn" data-close>Cancel</button><button class="btn warn" id="confirmAction">Continue</button></div>`);$('confirmAction').onclick=()=>{$('modalRoot').replaceChildren();callback();};};
  $('optionsGear').onclick=async()=>{
    try {
      const info = await showRuntime();
      modal(`<h3>Options</h3><p>${esc(runtimeLabel(info))} · Local saves · TableForge v2.0</p><div class="actions"><button class="btn" data-close>Close</button></div>`);
    } catch(error) { notify(error); }
  };
  $('pilotToggle').onclick=()=>{state.pilot=!state.pilot;$('pilotToggle').textContent='Pilot Mode: '+(state.pilot?'On':'Off');$('pilotPanel').classList.toggle('hidden',!state.pilot);};
  $('askAi').onclick=()=>modal('<h3>Ask AI-DM</h3><p>Operational AI questions need a provider connection. This build uses mock narration.</p><div class="actions"><button class="btn" data-close>Close</button></div>');
  $('reviewContext').onclick=()=>modal('<h3>Review Context</h3><p>Saved transcript and cartridge bindings are available for the future AI-DM runtime.</p><div class="actions"><button class="btn" data-close>Close</button></div>');
  $('pilotMap').onclick=()=>modal('<h3>GM Map</h3><p>Map viewing will be connected to validated cartridge assets.</p><div class="actions"><button class="btn" data-close>Close</button></div>');
  document.querySelectorAll('.ref-open').forEach(b=>b.onclick=()=>modal(`<h3>${esc(b.textContent)}</h3><p>Player-safe reference entries will appear here after discovery tracking is built.</p><div class="actions"><button class="btn" data-close>Close</button></div>`));
  const toggle=(id,css,key,other,symbols)=>{state[key]=!state[key];$(other).classList.toggle('collapsed',state[key]);$(id).textContent=state[key]?symbols[1]:symbols[0];if(css)$('workarea').classList.toggle(css,state[key]);};
  $('toggleLeft').onclick=()=>toggle('toggleLeft','left-collapsed','left','leftSidebar',['‹','›']);
  $('toggleRight').onclick=()=>toggle('toggleRight','right-collapsed','right','rightSidebar',['›','‹']);
  $('toggleComposer').onclick=()=>toggle('toggleComposer',null,'composer','composerWrap',['↓','↑']);
  const applySearch=()=>{const q=$('messageSearch').value.trim().toLowerCase();let hits=0;document.querySelectorAll('#feedInner .message').forEach(el=>{const found=!!q&&el.dataset.searchText.includes(q);hits+=Number(found);el.classList.toggle('search-dim',!!q&&!found);el.classList.toggle('search-match',found);});$('searchCount').textContent=q?hits:'';};
  $('messageSearch').oninput=applySearch;
  $('messageSearch').onkeydown=e=>{if(e.key==='Escape'){$('messageSearch').value='';applySearch();}if(e.key==='Enter')document.querySelector('.search-match')?.scrollIntoView({block:'center'});};
  // Simple polling synchronizes browsers while WebSocket transport is pending.
  setInterval(async()=>{if(!state.save || !$('play').classList.contains('active'))return;try{const next=await request('saves/'+state.save.save.id);if(next.save.updated_at!==state.save.save.updated_at){state.save=next;render();}}catch(error){console.error(error);}},2500);
})();
