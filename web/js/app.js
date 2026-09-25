(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const avatar = (player, className, fallback) => `<div class="${className}">${esc(fallback ?? player?.character?.[0] ?? '?')}${player?.portraitUrl?`<img src="${esc(player.portraitUrl)}" alt="">`:''}</div>`;
  const screens = [...document.querySelectorAll('.screen')];
  const state = {cartridge:null, save:null, identity:sessionStorage.getItem('tableforge-player'), pilot:false, left:false, right:false, composer:false, draft:null, generating:false, asking:false, updating:false, bindingRequest:0};
  $('appVersion').textContent = 'v2.0';
  const request = async (path, body) => {
    const response = await fetch('/api/' + path, {method:body === undefined ? 'GET':'POST', headers:{'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
    if(response.status===404&&path.endsWith('/portrait')) throw Error('Portraits need the updated TableForge server. Restart the server and refresh this page.');
    const result = await response.json();
    if(!response.ok) throw Object.assign(Error(result.error || `Request failed (${response.status})`), {code:result.code});
    return result;
  };
  const notify = error => alert(error.message || String(error));
  const runtimeLabel = info => (info.provider === 'openai' ? 'OpenAI' : 'Mock AI') + ' · ' + info.model;
  const tokenLabel = value => new Intl.NumberFormat().format(value || 0);
  const costLabel = usage => {
    if(usage.unpricedRequests) return 'Cost unavailable';
    const value=Number(usage.estimatedCostUsd || 0);
    return value>0 && value<0.0001?'≈<$0.0001':`≈$${value.toFixed(4)}`;
  };
  const usageLine = usage => `${tokenLabel(usage.totalTokens)} tokens · ${costLabel(usage)}`;
  const showRuntime = async () => {
    const info = await request('runtime');
    $('runtimeProvider').textContent = info.provider === 'openai' ? 'OpenAI' : 'Mock AI';
    $('runtimeModel').textContent = info.model;
    return info;
  };
  const showUsage = async () => {
    try {
      const result=await request('usage');
      $('globalUsage').innerHTML=`<strong>All saved adventures</strong><div>${esc(usageLine(result.usage))}</div><div>${tokenLabel(result.usage.inputTokens)} input · ${tokenLabel(result.usage.outputTokens)} output · ${result.usage.requests} AI requests</div><div class="muted">${result.usage.unmeteredRequests?'Some requests did not return token counts. ':''}Tracked requests only; earlier activity is unavailable. Costs are estimates using standard text rates from ${esc(result.pricingAsOf)}. <a href="${esc(result.pricingUrl)}" target="_blank" rel="noopener">Pricing</a></div>`;
    } catch(error) { $('globalUsage').textContent='Restart the TableForge server to enable AI usage tracking.'; }
  };
  const show = async id => {
    screens.forEach(el => el.classList.toggle('active', el.id === id));
    if(id === 'load') await refreshSaves();
    if(id === 'options') {await showRuntime();await showUsage();}
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
    if(items.length!==1 || !/\.zip$/i.test(items[0].name)) return notify(Error('Choose one ZIP cartridge containing all adventure files.'));
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
  $('filesInput').onchange = event => {selectedFiles(event.target.files);event.target.value='';};
  $('removeCartridge').onclick = () => {state.cartridge=null; state.bindingRequest++; renderCartridge();};
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
    const manifestPath=c.manifest || c.files.find(path=>path.split('/').at(-1).toLowerCase()==='manifest.json');
    const manifestIssue=c.invalid?.['manifest.json'];
    const manifestMissing=c.missing.includes('manifest.json') || !manifestPath;
    $('manifestBinding').className='binding '+(manifestIssue||manifestMissing?'bad':'ok');
    $('manifestBinding').innerHTML=`<div class="row"><strong>manifest.json · required</strong><span>${manifestIssue?'Invalid':manifestMissing?'Missing':'Found'}</span></div><div class="muted">${esc(manifestPath || 'No manifest.json in this ZIP')}</div>${manifestIssue?`<span class="binding-issue">${esc(manifestIssue)}</span>`:manifestMissing?'<span class="binding-issue">Add manifest.json to the ZIP before starting an adventure.</span>':''}`;
    $('cartridgeFiles').innerHTML=c.files.map(path=>`<li>${esc(path)}</li>`).join('');
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
    next.disabled=!!(c.validating || c.validationError || manifestMissing || c.missing.length || Object.keys(c.invalid || {}).length);
    card.querySelector('.pill').textContent=c.validating?'Checking bindings':c.validationError?'Validation failed':manifestMissing||c.missing.length?'Required content missing':Object.keys(c.invalid || {}).length?'Invalid binding':'Ready';
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
    if(!state.cartridge || state.cartridge.validating || state.cartridge.validationError ||
       !state.cartridge.files.some(path=>path.split('/').at(-1).toLowerCase()==='manifest.json') ||
       state.cartridge.missing.length || Object.keys(state.cartridge.invalid || {}).length) return notify(Error('Choose a playable cartridge first'));
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
      button.innerHTML=`${avatar(player,'party-avatar')}<div><strong>${esc(player.character)}</strong><span>${esc(player.name)}</span></div><span class="pill">Join</span>`;
      button.onclick=async()=>{
        button.disabled=true;
        try{
          if(state.save.sessions.at(-1)?.ended_at) state.save=await request('saves/'+state.save.save.id+'/start-session',{playerId:player.id});
          state.identity=player.id;sessionStorage.setItem('tableforge-player',player.id);render();await show('play');
        }catch(error){notify(error);button.disabled=false;}
      };wrap.append(button);
    });
  };
  const update=async (action,body,onError) => {
    if(state.updating || state.generating) return false;
    state.updating=true;
    render();
    try {state.save=await request('saves/'+state.save.save.id+'/'+action,body);return true;}
    catch(error){if(!onError?.(error))notify(error);return false;}
    finally {state.updating=false;render();}
  };
  const fillPilotThread = () => {
    const thread=$('pilotThread');
    if(!thread||!state.save) return;
    const atBottom=thread.scrollHeight-thread.scrollTop-thread.clientHeight<48;
    thread.replaceChildren();
    if(!state.save.pilot?.length){
      const empty=document.createElement('div');
      empty.className='muted';
      empty.textContent='Ask a question about the adventure, rules, or what happens next.';
      thread.append(empty);
    }
    for(const m of state.save.pilot||[]){
      const row=document.createElement('div');
      row.className='pilot-line'+(m.kind==='ai'?' ai':'');
      const name=document.createElement('strong');
      name.textContent=m.name;
      const body=document.createElement('div');
      body.className='markdown-body';
      body.innerHTML=TableForgeMarkdown.render(m.body);
      row.append(name, body);
      thread.append(row);
    }
    if(atBottom) thread.scrollTop=thread.scrollHeight;
    const send=$('pilotSend'), field=$('pilotAsk');
    const busy=state.asking||state.generating||!!state.save.activity?.aiDm;
    if(send) send.disabled=!state.identity||!state.pilot||busy;
    if(field) field.disabled=busy;
  };
  // Presence comes from the server so every browser sees the AI-DM and other players typing.
  const aiDmBusy=purpose=>(purpose==='advance'&&state.generating)||(purpose==='ask'&&state.asking)||state.save?.activity?.aiDm===purpose;
  let dotCount=1;
  const dots=()=>`<span class="typing-dots">${'.'.repeat(dotCount)}</span>`;
  const renderActivity=()=>{
    const s=state.save,el=$('typingIndicator');if(!s||!el)return;
    const names=s.players.filter(p=>p.id!==state.identity&&s.activity?.typing?.includes(p.id)).map(p=>p.character);
    const who=aiDmBusy('advance')?'AI-DM':names.length>2?'Several players':names.join(' and ');
    const text=who?`${who} ${names.length>1&&who!=='AI-DM'?'are':'is'} typing`:'';
    if(el.dataset.text!==text){
      el.dataset.text=text;
      el.classList.toggle('ai',who==='AI-DM');
      el.innerHTML=text?`<strong>${esc(who)}</strong>${esc(text.slice(who.length))} ${dots()}`:'';
    }
    $('tableStatus').textContent=aiDmBusy('advance')?'The AI-DM is typing':`Session ${s.sessions.at(-1)?.number || 1} · ${s.save.mode==='combat'?'Combat Mode · ':''}${s.players.filter(p=>p.ready).length} of ${s.players.length} Ready`;
    const status=$('pilotAskStatus');
    if(status) status.innerHTML=aiDmBusy('ask')?'The AI-DM is typing '+dots():'';
  };
  const render=()=>{
    const s=state.save;if(!s)return;
    $('play').querySelector('.top-title strong').textContent=s.cartridge.title;
    $('partyList').innerHTML=s.players.map(p=>`<div class="party-card" style="${p.id===state.identity?'border-color:var(--accent2)':''}"><div class="party-top">${p.id===state.identity?`<button class="portrait-button" type="button" title="Edit ${esc(p.character)} portrait" aria-label="Edit ${esc(p.character)} portrait">${avatar(p,'party-avatar')}</button>`:avatar(p,'party-avatar')}<div class="party-name"><strong>${esc(p.character)}</strong><span>${esc(p.name)}</span></div><span class="ready-badge ${p.ready?'ready':''}">${p.ready?'Ready':'Not Ready'}</span></div></div>`).join('');
    $('partyList').querySelector('.portrait-button')?.addEventListener('click',openPortraitEditor);
    $('usageSummary').innerHTML=s.usage?`<strong>AI usage</strong><div>This session: ${esc(usageLine(s.usage.session))}</div><div>Playthrough: ${esc(usageLine(s.usage.save))}</div><div>${tokenLabel(s.usage.save.inputTokens)} input · ${tokenLabel(s.usage.save.outputTokens)} output</div><div>Estimated USD · <a href="${esc(s.usage.pricingUrl)}" target="_blank" rel="noopener">rates ${esc(s.usage.pricingAsOf)}</a></div>`:'<strong>AI usage</strong><div>Restart the TableForge server to enable tracking.</div>';
    $('feedInner').replaceChildren();
    for(const m of s.messages){
      const row=document.createElement('div');row.className='message '+(m.kind==='ai'?'ai':'player');
      row.innerHTML=`${avatar(s.players.find(p=>p.id===m.player_id),'avatar',m.kind==='ai'?'AI':m.name[0])}<div><div class="message-head"><strong>${esc(m.name)}</strong><span class="time">${new Date(m.created_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}</span></div><div class="message-body"></div><div class="message-actions"><button class="copy-message">Copy</button></div></div>`;
      row.querySelector('.message-body').innerHTML=TableForgeMarkdown.render(m.body);
      row.querySelector('.message-body').classList.add('markdown-body');
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
    $('combatToggle').classList.toggle('hidden',s.save.mode==='combat');
    $('resumeCombat').classList.toggle('hidden',s.save.mode!=='combat');
    $('combatToggle').disabled=state.generating||state.updating;
    $('resumeCombat').disabled=state.generating||state.updating;
    $('endSession').disabled=state.generating||state.updating;
    renderDraft();
    fillPilotThread();
    renderActivity();
  };
  // A draft belongs to the beat it was started in. If the table moves on, keep the
  // text but hold it until the player confirms it still fits the new beat.
  const draftStale=()=>!!state.draft&&!!state.save&&(state.draft.saveId!==state.save.save.id||state.draft.beat!==state.save.save.beat);
  const syncDraft=()=>{
    if(!$('composer').value.trim()) state.draft=null;
    else if(!state.draft&&state.save) state.draft={saveId:state.save.save.id,beat:state.save.save.beat};
    renderDraft();
  };
  const renderDraft=()=>{
    const stale=draftStale();
    $('draftNotice').classList.toggle('hidden',!stale);
    $('composerWrap').classList.toggle('draft-stale',stale);
  };
  $('keepDraft').onclick=()=>{state.draft=null;syncDraft();$('composer').focus();};
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
    syncDraft();
    if(draftStale()) return;
    const staleBeat=error=>{
      if(error.code!=='stale_beat') return false;
      // The server saw the table advance first; the render after this refresh shows the review notice.
      request('saves/'+state.save.save.id).then(next=>{state.save=next;render();}).catch(console.error);
      return true;
    };
    if(await update('messages',{playerId:state.identity,text:body,beat:state.draft.beat},staleBeat)) {
      field.value='';resize();typingSentAt=0;state.draft=null;renderDraft();
      if(state.save.save.mode==='normal' && state.save.players.every(p=>p.ready)) await advanceTable();
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
  field.addEventListener('input',()=>{resize();syncDraft();});
  // Heartbeat while composing; the server forgets a typist after a few quiet seconds.
  let typingSentAt=0;
  const sendTyping=typing=>{if(!state.save||!state.identity)return;typingSentAt=typing?Date.now():0;request('saves/'+state.save.save.id+'/typing',{playerId:state.identity,typing}).catch(()=>{});};
  field.addEventListener('input',()=>{const typing=!!field.value.trim();if(typing&&Date.now()-typingSentAt>2500)sendTyping(true);else if(!typing&&typingSentAt)sendTyping(false);});
  field.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('sendBtn').click();}});
  $('emojiBtn').onclick=()=>{field.value+=' 🙂';resize();field.focus();};
  // Attachments are intentionally disabled until byte storage is implemented.
  $('attachmentBtn').onclick=()=>modal('<h3>Attachments</h3><p>File attachments are coming in a later build.</p><div class="actions"><button class="btn" data-close>Close</button></div>');
  const modal=html=>{const root=$('modalRoot');root.innerHTML=`<div class="overlay"><div class="modal">${html}</div></div>`;root.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>root.replaceChildren());root.querySelector('.overlay').onclick=e=>{if(e.target.classList.contains('overlay'))root.replaceChildren();};};
  const openPortraitEditor=()=>{
    const player=state.save?.players.find(p=>p.id===state.identity);
    if(!player)return;
    const supported=Object.hasOwn(player,'portraitUrl');
    modal(`<h3>${esc(player.character)} portrait</h3><p>Click the square to choose an image. Drag to position it, then use Zoom to select your crop.</p>${supported?'':'<p class="binding-issue">Restart the TableForge server, then refresh this page to enable portrait uploads.</p>'}<canvas id="portraitCrop" class="portrait-crop empty" width="320" height="320" tabindex="0" role="button" aria-label="Choose portrait image"></canvas><div id="portraitCropTools" class="hidden"><label class="portrait-zoom">Zoom<input id="portraitZoom" type="range" min="1" max="4" step="0.01" value="1"></label></div><input id="portraitInput" class="hidden" type="file" accept="image/png,image/jpeg,image/webp"><div class="actions"><button class="btn" data-close>Cancel</button>${player.portraitUrl?'<button class="btn warn" id="removePortrait">Remove portrait</button>':''}<button class="btn primary" id="savePortrait" disabled>Save portrait</button></div>`);
    const root=$('modalRoot'),canvas=$('portraitCrop'),context=canvas.getContext('2d');
    const zoomInput=$('portraitZoom'),saveButton=$('savePortrait'),playerId=player.id;
    let image=null,centerX=0,centerY=0,zoom=1,pointer=null,dragged=false,loadVersion=0,saving=false;
    const close=()=>{
      if(saving)return;
      loadVersion++;
      image?.close();
      root.replaceChildren();
    };
    root.querySelector('[data-close]').onclick=close;
    root.querySelector('.overlay').onclick=event=>{if(event.target.classList.contains('overlay'))close();};
    const draw=()=>{
      context.clearRect(0,0,canvas.width,canvas.height);
      if(!image){
        context.fillStyle='#9ca8b5';context.font='14px sans-serif';context.textAlign='center';
        context.fillText('Choose an image to preview',canvas.width/2,canvas.height/2);
        return;
      }
      const scale=Math.max(canvas.width/image.width,canvas.height/image.height)*zoom;
      const half=canvas.width/(2*scale);
      centerX=Math.max(half,Math.min(image.width-half,centerX));
      centerY=Math.max(half,Math.min(image.height-half,centerY));
      context.drawImage(image,canvas.width/2-centerX*scale,canvas.height/2-centerY*scale,image.width*scale,image.height*scale);
    };
    const loadImage=async source=>{
      const version=++loadVersion;
      const blob=source instanceof Blob?source:await fetch(source).then(response=>{
        if(!response.ok)throw Error('Could not load the current portrait.');
        return response.blob();
      });
      const loaded=await createImageBitmap(blob);
      if(version!==loadVersion||!canvas.isConnected){loaded.close();return;}
      image?.close();image=loaded;
      centerX=image.width/2;centerY=image.height/2;zoom=1;zoomInput.value='1';
      canvas.classList.remove('empty');
      canvas.setAttribute('aria-label','Portrait crop preview. Click or press Enter to choose another image; drag or use arrow keys to position it.');
      $('portraitCropTools').classList.remove('hidden');saveButton.disabled=!supported;
      draw();
    };
    draw();
    if(player.portraitUrl)loadImage(player.portraitUrl).catch(notify);
    const chooseImage=()=>{
      if(!supported||saving)return;
      $('portraitInput').value='';$('portraitInput').click();
    };
    canvas.onclick=()=>{if(!dragged)chooseImage();dragged=false;};
    canvas.onkeydown=event=>{
      if(event.key==='Enter'||event.key===' '){event.preventDefault();chooseImage();return;}
      if(!image||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
      event.preventDefault();
      const scale=Math.max(canvas.width/image.width,canvas.height/image.height)*zoom;
      const step=(event.shiftKey?32:8)/scale;
      if(event.key==='ArrowLeft')centerX-=step;
      if(event.key==='ArrowRight')centerX+=step;
      if(event.key==='ArrowUp')centerY-=step;
      if(event.key==='ArrowDown')centerY+=step;
      draw();
    };
    $('portraitInput').onchange=event=>{
      const file=event.target.files[0];
      if(!file)return;
      if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>20*1024*1024){
        notify(Error('Choose a PNG, JPEG, or WebP image up to 20 MB.'));
        return;
      }
      loadImage(file).catch(()=>notify(Error('This image could not be opened.')));
    };
    zoomInput.oninput=()=>{zoom=Number(zoomInput.value);draw();};
    canvas.onpointerdown=event=>{
      if(!image)return;
      pointer={id:event.pointerId,x:event.clientX,y:event.clientY,startX:event.clientX,startY:event.clientY};
      dragged=false;
      canvas.setPointerCapture(event.pointerId);canvas.classList.add('dragging');
    };
    canvas.onpointermove=event=>{
      if(!pointer||pointer.id!==event.pointerId||!image)return;
      if(Math.hypot(event.clientX-pointer.startX,event.clientY-pointer.startY)>4)dragged=true;
      const scale=Math.max(canvas.width/image.width,canvas.height/image.height)*zoom;
      const displayScale=canvas.width/canvas.getBoundingClientRect().width;
      centerX-=(event.clientX-pointer.x)*displayScale/scale;
      centerY-=(event.clientY-pointer.y)*displayScale/scale;
      pointer.x=event.clientX;pointer.y=event.clientY;draw();
    };
    const stopDrag=()=>{pointer=null;canvas.classList.remove('dragging');};
    canvas.onpointerup=stopDrag;canvas.onpointercancel=()=>{stopDrag();dragged=false;};
    saveButton.onclick=async()=>{
      if(!image||saving)return;
      saving=true;saveButton.disabled=true;
      try{
        const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',0.9));
        if(!blob)throw Error('Could not prepare the portrait.');
        if(await update('players/'+playerId+'/portrait',{mime:blob.type,data:await bytes64(blob)})){
          saving=false;close();return;
        }
      }catch(error){notify(error);}
      saving=false;saveButton.disabled=false;
    };
    if($('removePortrait'))$('removePortrait').onclick=async()=>{
      if(saving)return;
      saving=true;
      if(await update('players/'+playerId+'/portrait',{remove:true})){
        saving=false;close();return;
      }
      saving=false;
    };
  };
  const confirmBox=(title,message,callback)=>{modal(`<h3>${esc(title)}</h3><p>${esc(message)}</p><div class="actions"><button class="btn" data-close>Cancel</button><button class="btn warn" id="confirmAction">Continue</button></div>`);$('confirmAction').onclick=()=>{$('modalRoot').replaceChildren();callback();};};
  $('optionsGear').onclick=async()=>{
    try {
      const info = await showRuntime();
      const usage=state.save?.usage;
      modal(`<h3>Options</h3><p>${esc(runtimeLabel(info))} · Local saves · TableForge v2.0</p>${usage?`<p>AI usage this session: ${esc(usageLine(usage.session))}<br>Playthrough: ${esc(usageLine(usage.save))}<br>Estimates use <a href="${esc(usage.pricingUrl)}" target="_blank" rel="noopener">standard text rates</a> from ${esc(usage.pricingAsOf)}. Earlier activity is unavailable.</p>`:''}<div class="actions"><button class="btn" data-close>Close</button></div>`);
    } catch(error) { notify(error); }
  };
  $('pilotToggle').onclick=()=>{state.pilot=!state.pilot;$('pilotToggle').textContent='Pilot Mode: '+(state.pilot?'On':'Off');$('pilotPanel').classList.toggle('hidden',!state.pilot);};
  $('askAi').onclick=()=>{
    if(!state.pilot||!state.save||!state.identity)return;
    modal('<h3>Ask AI-DM</h3><p>Pilot conversation is saved separately from the table chat. Asking does not change Ready or advance the table.</p><div id="pilotThread" class="pilot-chat-log" role="log" aria-label="Pilot conversation"></div><div id="pilotAskStatus" class="muted" role="status" aria-live="polite"></div><label>Question<textarea id="pilotAsk" rows="4" maxlength="20000" placeholder="Ask the AI-DM a question"></textarea></label><div class="actions"><button class="btn" data-close>Close</button><button class="btn primary" id="pilotSend">Send question</button></div>');
    fillPilotThread();renderActivity();
    const field=$('pilotAsk');
    const send=async()=>{
      const body=field.value.trim();
      if(!body)return notify(Error('Enter a question for the AI-DM.'));
      if(state.asking||state.generating||state.save.activity?.aiDm)return;
      const previousId=state.save.pilot?.at(-1)?.id||0;
      state.asking=true;render();
      try{
        state.save=await request('saves/'+state.save.save.id+'/ask',{playerId:state.identity,text:body});
        field.value='';
      }catch(error){
        try{
          const latest=await request('saves/'+state.save.save.id);
          if(latest.pilot.some(m=>m.id>previousId&&m.player_id===state.identity&&m.body===body))field.value='';
          state.save=latest;
        }catch(refreshError){console.error(refreshError);}
        notify(error);
      }finally{state.asking=false;render();field.focus();}
    };
    $('pilotSend').onclick=send;
    field.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}});
    field.focus();
  };
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
  // Typing dots cycle . .. ... together wherever they appear.
  setInterval(()=>{dotCount=dotCount%3+1;document.querySelectorAll('.typing-dots').forEach(el=>el.textContent='.'.repeat(dotCount));},450);
  // Simple polling synchronizes browsers while WebSocket transport is pending.
  setInterval(async()=>{if(!state.save || !$('play').classList.contains('active'))return;try{const next=await request('saves/'+state.save.save.id);if(next.save.updated_at!==state.save.save.updated_at){state.save=next;render();}else if(JSON.stringify(next.activity)!==JSON.stringify(state.save.activity)){state.save.activity=next.activity;fillPilotThread();renderActivity();}}catch(error){console.error(error);}},2500);
})();
