(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const avatar = (player, className, fallback) => `<div class="${className}">${esc(fallback ?? player?.character?.[0] ?? '?')}${player?.portraitUrl?`<img src="${esc(player.portraitUrl)}" alt="">`:''}</div>`;
  const screens = [...document.querySelectorAll('.screen')];
  const state = {cartridge:null, save:null, identity:sessionStorage.getItem('tableforge-player'), pilot:false, left:false, right:false, composer:false, draft:null, locations:[], generating:false, asking:false, updating:false, bindingRequest:0};
  $('appVersion').textContent = 'v2.0';
  const request = async (path, body) => {
    const controller=new AbortController();
    const generating=body!==undefined&&/\/(images|advance|ask|summary-draft)$/.test(path);
    const timer=setTimeout(()=>controller.abort(),generating?210000:15000);
    try{
      const response = await fetch('/api/' + path, {method:body === undefined ? 'GET':'POST', signal:controller.signal, headers:{'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
      if(response.status===404&&path.endsWith('/portrait')) throw Error('Portraits need the updated TableForge server. Restart the server and refresh this page.');
      const result = await response.json();
      if(!response.ok) throw Object.assign(Error(result.error || `Request failed (${response.status})`), {code:result.code});
      return result;
    }catch(error){
      if(error.name==='AbortError')throw Error(body===undefined?'The server is taking too long to respond.':'The request timed out. The server may still be working; check its status before retrying.');
      throw error;
    }finally{clearTimeout(timer);}
  };
  const notify = error => alert(error.message || String(error));
  // Request IDs let the server recognize a retry of something it already did.
  const newRequestId = () => typeof crypto.randomUUID==='function'?crypto.randomUUID():'10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(Number(c)^crypto.getRandomValues(new Uint8Array(1))[0]&15>>Number(c)/4).toString(16));
  const runtimeLabel = info => (info.provider === 'openai' ? 'OpenAI' : 'Mock AI') + ' · ' + info.model;
  const tokenLabel = value => new Intl.NumberFormat().format(value || 0);
  const costLabel = usage => {
    if(usage.unpricedRequests) return 'Cost unavailable';
    const value=Number(usage.estimatedCostUsd || 0);
    return value>0 && value<0.0001?'≈<$0.0001':`≈$${value.toFixed(4)}`;
  };
  const usageLine = usage => `${tokenLabel(usage.totalTokens)} tokens · ${costLabel(usage)}`;
  const imageUsageLine = usage => {
    const count=`${usage.generated} image${usage.generated===1?'':'s'} / ${usage.requests} request${usage.requests===1?'':'s'}`;
    const known=usage.knownEstimatedCostUsd ?? usage.estimatedCostUsd;
    const cost=known==null?'Refresh after restarting the server to see known costs':
      `${usage.unpricedRequests?'Known estimated cost: ':'Estimated cost: '}${costLabel({estimatedCostUsd:known})}`;
    const missing=usage.unpricedRequests?` · ${usage.unpricedRequests} request${usage.unpricedRequests===1?'':'s'} without cost data`:'';
    return `${count} · ${cost}${missing}`;
  };
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
      if(result.imageUsage) $('globalUsage').insertAdjacentHTML('beforeend',`<p><strong>Scene images (separate)</strong><br>${esc(imageUsageLine(result.imageUsage))}</p>`);
    } catch(error) { $('globalUsage').textContent='Restart the TableForge server to enable AI usage tracking.'; }
  };
  // Backups copy the whole save database on the host; restore always backs up the current data first.
  const byteLabel = n => n<1024*1024?`${Math.max(1,Math.round(n/1024))} KB`:`${(n/1024/1024).toFixed(1)} MB`;
  const backupCounts = c => [[c.saves,'save'],[c.messages,'message'],[c.portraits,'portrait'],[c.images,'illustration'],[c.notes,'party note']].map(([n,word])=>`${tokenLabel(n)} ${word}${n===1?'':'s'}`).join(' · ');
  const showBackups = async () => {
    const list=$('backupList');
    let result;
    try{result=await request('backups');}
    catch(error){list.textContent='Restart the TableForge server to enable backups.';return;}
    list.innerHTML=(result.backups.length?result.backups.map(b=>`<div class="backup-row"><div><strong>${esc(b.name)}</strong><div class="muted">${new Date(b.modifiedAt).toLocaleString()} · ${byteLabel(b.bytes)}</div></div><div class="actions" style="margin-top:0"><a class="btn small" href="/api/backups/${encodeURIComponent(b.name)}" download>Download</a><button class="btn small warn restore-backup" data-name="${esc(b.name)}">Restore…</button></div></div>`).join(''):'<p class="muted">No backups yet.</p>')+
      `<div class="muted backup-folder">Stored on the host in ${esc(result.folder)}. To restore a downloaded backup, copy it into that folder and reopen Options.</div>`;
    list.querySelectorAll('.restore-backup').forEach(button=>button.onclick=()=>restoreBackup(button.dataset.name));
  };
  const restoreBackup = async name => {
    let details;
    try{details=await request('backups/'+encodeURIComponent(name)+'/verify',{});}
    catch(error){return notify(error);}
    const missing=details.missingCartridges.length;
    const saves=details.saves.map(s=>`<li>${esc(s.name)}${s.title&&s.title!==s.name?` <span class="muted">· ${esc(s.title)}</span>`:''}${s.cartridgeAvailable?'':' <span class="binding-issue">cartridge missing</span>'}</li>`).join('');
    modal(`<h3>Restore backup</h3><p><strong>${esc(name)}</strong> passed its integrity check.</p><p>${esc(backupCounts(details.counts))}</p><ul class="backup-saves">${saves||'<li>No saves</li>'}</ul>${missing?`<p class="binding-issue">${missing} cartridge${missing===1?' is':'s are'} not on this host. Those saves will ask you to locate the original package.</p>`:''}<p>Restoring replaces <strong>every</strong> save on this host with this backup. Your current data is backed up first, so this can be undone.</p><div class="actions"><button class="btn" data-close>Cancel</button><button class="btn warn" id="confirmRestore">Restore</button></div>`);
    $('confirmRestore').onclick=async()=>{
      $('confirmRestore').disabled=true;
      try{
        const result=await request('backups/'+encodeURIComponent(name)+'/restore',{});
        state.save=null;state.feedKey=null;state.draft=null;
        $('modalRoot').replaceChildren();
        $('backupStatus').textContent=`Restored ${result.restored} and verified it (${backupCounts(result.live.counts)}). The previous data was saved as ${result.safetyBackup}.`;
        await showBackups();
      }catch(error){$('confirmRestore').disabled=false;notify(error);}
    };
  };
  $('createBackup').onclick=async()=>{
    const button=$('createBackup');button.disabled=true;$('backupStatus').textContent='Backing up…';
    try{
      const result=await request('backups',{});
      $('backupStatus').textContent=`Saved and verified ${result.name} (${backupCounts(result.counts)}).`;
      await showBackups();
    }catch(error){$('backupStatus').textContent='';notify(error);}
    finally{button.disabled=false;}
  };
  const show = async id => {
    screens.forEach(el => el.classList.toggle('active', el.id === id));
    if(id === 'load') await refreshSaves();
    if(id === 'options') {await showRuntime();await showUsage();await showBackups();}
    if(id === 'play') scrollFeedToLatest();
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
          state.identity=player.id;sessionStorage.setItem('tableforge-player',player.id);restoreDraft();render();await show('play');
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
  const feedAtBottom=()=>{const feed=$('feed');return feed.scrollHeight-feed.scrollTop-feed.clientHeight<48;};
  const scrollFeedToLatest=()=>{$('feed').scrollTop=$('feed').scrollHeight;state.followLatest=true;$('jumpLatest').classList.add('hidden');};
  const render=()=>{
    const s=state.save;if(!s)return;
    $('play').querySelector('.top-title strong').textContent=s.cartridge.title;
    $('partyList').innerHTML=s.players.map(p=>`<div class="party-card" style="${p.id===state.identity?'border-color:var(--accent2)':''}"><div class="party-top">${p.id===state.identity?`<button class="portrait-button" type="button" title="Edit ${esc(p.character)} portrait" aria-label="Edit ${esc(p.character)} portrait">${avatar(p,'party-avatar')}</button>`:avatar(p,'party-avatar')}<div class="party-name"><strong>${esc(p.character)}</strong><span>${esc(p.name)}</span></div><span class="ready-badge ${p.ready?'ready':''}">${p.ready?'Ready':'Not Ready'}</span></div></div>`).join('');
    $('partyList').querySelector('.portrait-button')?.addEventListener('click',openPortraitEditor);
    $('usageSummary').innerHTML=s.usage?`<strong>AI usage</strong><div>This session: ${esc(usageLine(s.usage.session))}</div><div>Playthrough: ${esc(usageLine(s.usage.save))}</div><div>${tokenLabel(s.usage.save.inputTokens)} input · ${tokenLabel(s.usage.save.outputTokens)} output</div><div>Estimated USD · <a href="${esc(s.usage.pricingUrl)}" target="_blank" rel="noopener">rates ${esc(s.usage.pricingAsOf)}</a></div>`:'<strong>AI usage</strong><div>Restart the TableForge server to enable tracking.</div>';
    if(s.imageUsage) $('usageSummary').insertAdjacentHTML('beforeend',`<div class="image-usage"><strong>Scene images (separate)</strong><div>Session: ${esc(imageUsageLine(s.imageUsage.session))}</div><div>Playthrough: ${esc(imageUsageLine(s.imageUsage.save))}</div></div>`);
    $('illustrateScene').disabled=!state.identity||!s.messages.some(m=>m.kind==='ai');
    // Rebuild the feed only when its content changes, so Ready/typing updates keep the reading position.
    const feed=$('feed'),feedKey=JSON.stringify([s.save.id,s.messages.map(m=>[m.id,m.body.length,m.image_id,!!s.images?.some(i=>i.id===m.image_id)]),s.players.map(p=>[p.id,p.character,p.portraitUrl])]);
    const feedChanged=feedKey!==state.feedKey,previousIds=new Set(state.feedKey?[...$('feedInner').children].map(el=>el.id):[]);
    const followLatest=state.followLatest!==false;
    if(feedChanged){
    state.feedKey=feedKey;
    const top=feed.scrollTop;
    $('feedInner').replaceChildren();
    const overrides=new Map();
    for(const e of s.events||[]){
      if(e.kind!=='ready_override')continue;
      try{const detail=JSON.parse(e.body);overrides.set(detail.messageId,{...detail,playerId:e.player_id});}catch(error){console.error(error);}
    }
    const character=id=>s.players.find(p=>p.id===id)?.character||'A player';
    for(const m of s.messages){
      const row=document.createElement('div');row.className='message '+(m.kind==='ai'?'ai':'player');
      row.innerHTML=`${avatar(s.players.find(p=>p.id===m.player_id),'avatar',m.kind==='ai'?'AI':m.name[0])}<div><div class="message-head"><strong>${esc(m.name)}</strong><span class="time">${new Date(m.created_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}</span></div><div class="message-body"></div><div class="message-actions"><button class="copy-message">Copy</button></div></div>`;
      row.querySelector('.message-body').innerHTML=TableForgeMarkdown.render(m.body);
      row.querySelector('.message-body').classList.add('markdown-body');
      row.id='message-'+m.id;
      const override=overrides.get(m.id);
      if(override){
        const note=document.createElement('div');note.className='override-note';
        note.textContent=`${character(override.playerId)} used Ready Override`+
          (override.waitingOn?.length?` · not Ready: ${override.waitingOn.map(character).join(', ')}`:' · everyone was Ready');
        row.querySelector('.message-head').after(note);
      }
      if(m.kind==='image'){
        const record=s.images?.find(i=>i.id===m.image_id);
        if(record){
          const link=document.createElement('a');
          link.href=`/api/saves/${encodeURIComponent(s.save.id)}/images/${encodeURIComponent(record.id)}`;
          link.target='_blank';link.rel='noopener';
          const img=document.createElement('img');img.src=link.href;img.alt='Scene illustration';
          img.className='scene-image';img.loading='lazy';link.append(img);
          img.addEventListener('load',()=>{if(state.followLatest!==false)$('feed').scrollTop=$('feed').scrollHeight;});
          row.querySelector('.message-body').prepend(link);
          const source=document.createElement('button');source.className='btn small';source.textContent='View source narration';
          source.onclick=()=>document.getElementById('message-'+record.source_message_id)?.scrollIntoView({block:'center'});
          row.querySelector('.message-actions').append(source);
        }
      }
      row.querySelector('.copy-message').onclick=async event=>{await navigator.clipboard.writeText(m.body);event.target.textContent='Copied';setTimeout(()=>event.target.textContent='Copy',1200);};
      row.dataset.searchText=(m.name+' '+m.body).toLowerCase();$('feedInner').append(row);
    }
    applySearch();
    const added=s.messages.filter(m=>!previousIds.has('message-'+m.id));
    if(followLatest||!previousIds.size||added.some(m=>m.player_id&&m.player_id===state.identity&&m.kind!=='ai')) scrollFeedToLatest();
    else{feed.scrollTop=top;if(added.length)$('jumpLatest').classList.remove('hidden');}
    }
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
    renderLocation();
    refreshContextFlag();
    fillPilotThread();
    renderActivity();
  };
  // A draft belongs to the beat it was started in. If the table moves on, keep the
  // text but hold it until the player confirms it still fits the new beat.
  const draftStale=()=>!!state.draft&&!!state.save&&(state.draft.saveId!==state.save.save.id||state.draft.beat!==state.save.save.beat);
  const syncDraft=()=>{
    if(!$('composer').value.trim()) state.draft=null;
    else if(!state.draft&&state.save) state.draft={saveId:state.save.save.id,beat:state.save.save.beat,requestId:null};
    storeDraft();
    renderDraft();
  };
  // Drafts survive a refresh in this browser, keyed by save and player. The stored beat
  // keeps the review requirement: a draft from an earlier beat comes back held for review.
  const draftKey=()=>state.save&&state.identity?`tableforge-draft:${state.save.save.id}:${state.identity}`:null;
  const storeDraft=()=>{
    const key=draftKey();if(!key)return;
    try{
      if(state.draft&&state.draft.saveId===state.save.save.id)
        localStorage.setItem(key,JSON.stringify({text:$('composer').value,beat:state.draft.beat,requestId:state.draft.requestId}));
      else localStorage.removeItem(key);
    }catch(error){console.error(error);}
  };
  const restoreDraft=()=>{
    const key=draftKey();if(!key)return;
    let saved=null;
    try{saved=JSON.parse(localStorage.getItem(key)||'null');}catch(error){console.error(error);}
    // A send whose reply was lost may have landed; the save is the record of what was sent.
    if(saved?.requestId&&state.save.messages.some(m=>m.request_id===saved.requestId)) saved=null;
    const usable=saved&&typeof saved.text==='string'&&saved.text.trim()&&Number.isInteger(saved.beat);
    $('composer').value=usable?saved.text:'';
    state.draft=usable?{saveId:state.save.save.id,beat:saved.beat,requestId:saved.requestId||null}:null;
    storeDraft();resize();renderDraft();
  };
  const clearDraft=()=>{$('composer').value='';state.draft=null;storeDraft();resize();renderDraft();};
  const renderDraft=()=>{
    const stale=draftStale();
    $('draftNotice').classList.toggle('hidden',!stale);
    $('composerWrap').classList.toggle('draft-stale',stale);
  };
  $('keepDraft').onclick=()=>{state.draft=null;syncDraft();$('composer').focus();};  const advanceTable = async (extra={}) => {
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
  $('feed').addEventListener('scroll',()=>{state.followLatest=feedAtBottom();if(state.followLatest)$('jumpLatest').classList.add('hidden');},{passive:true});
  $('jumpLatest').onclick=()=>$('feed').scrollTo({top:$('feed').scrollHeight,behavior:'smooth'});
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
    const saveId=state.save.save.id;
    // One ID per contribution, kept with the draft until it is sent, so any retry is recognized.
    state.draft.requestId||=newRequestId();storeDraft();
    const requestId=state.draft.requestId;
    const landed=error=>{
      if(staleBeat(error)) return true;
      // The reply may be lost after the server saved the message; check before telling the player it failed.
      request('saves/'+saveId).then(next=>{
        if(state.save?.save.id!==saveId) return;
        state.save=next;
        const sent=next.messages.some(m=>m.request_id===requestId);
        if(sent&&state.draft?.requestId===requestId)clearDraft();
        render();
        if(!sent) notify(error);
        else if(next.save.mode==='normal'&&next.players.every(p=>p.ready)) advanceTable();
      }).catch(()=>notify(error));
      return true;
    };
    try {
      if(await update('messages',{playerId:state.identity,text:body,beat:state.draft.beat,requestId},landed)) {
        typingSentAt=0;
        if(state.draft?.requestId===requestId) clearDraft();
        if(state.save.save.mode==='normal' && state.save.players.every(p=>p.ready)) await advanceTable();
      }
    } finally {
      // Sending and automatic advancement disable the field, which drops focus.
      if(state.save?.save.id===saveId && $('play').classList.contains('active') &&
         !$('modalRoot').childElementCount && !field.disabled &&
         [document.body,field,$('sendBtn')].includes(document.activeElement)) field.focus();
    }
  };
  $('readyBtn').onclick=async()=>{
    const current=state.save.players.find(p=>p.id===state.identity);
    if(!current) return;
    if(await update('ready',{playerId:state.identity,ready:!current.ready}) &&
       state.save.save.mode==='normal' && state.save.players.every(p=>p.ready)) await advanceTable();
  };
  $('readyOverride').onclick=()=>{
    const waiting=state.save.players.filter(p=>!p.ready).map(p=>p.character);
    const who=state.save.players.find(p=>p.id===state.identity)?.character||'you';
    confirmBox('Ready Override',`${waiting.length?`Advance without waiting for ${waiting.join(', ')}?`:'Advance the table now?'} The table will see that ${who} used Ready Override.`,
      ()=>advanceTable({override:true,playerId:state.identity}));
  };
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
  // Editing makes it a different contribution, so a later send gets a fresh request ID.
  field.addEventListener('input',()=>{if(state.draft)state.draft.requestId=null;resize();syncDraft();});
  // Heartbeat while composing; the server forgets a typist after a few quiet seconds.
  let typingSentAt=0;
  const sendTyping=typing=>{if(!state.save||!state.identity)return;typingSentAt=typing?Date.now():0;request('saves/'+state.save.save.id+'/typing',{playerId:state.identity,typing}).catch(()=>{});};
  field.addEventListener('input',()=>{const typing=!!field.value.trim();if(typing&&Date.now()-typingSentAt>2500)sendTyping(true);else if(!typing&&typingSentAt)sendTyping(false);});
  field.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('sendBtn').click();}});
  $('emojiBtn').onclick=()=>{field.value+=' 🙂';resize();field.focus();};
  // Attachments are intentionally disabled until byte storage is implemented.
  $('attachmentBtn').onclick=()=>modal('<h3>Attachments</h3><p>File attachments are coming in a later build.</p><div class="actions"><button class="btn" data-close>Close</button></div>');
  const modal=(html,size='')=>{const root=$('modalRoot');root.innerHTML=`<div class="overlay"><div class="modal ${size}">${html}</div></div>`;root.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>root.replaceChildren());root.querySelector('.overlay').onclick=e=>{if(e.target.classList.contains('overlay'))root.replaceChildren();};};
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
  $('pilotToggle').onclick=()=>{state.pilot=!state.pilot;$('pilotToggle').textContent='Pilot Mode: '+(state.pilot?'On':'Off');$('pilotPanel').classList.toggle('hidden',!state.pilot);refreshContextFlag();if(!state.pilot&&$('sceneImageDialog'))$('modalRoot').replaceChildren();};
  let sceneDialog=null;
  const imageDialogActive = dialog => sceneDialog===dialog&&!!$('sceneImageDialog')&&state.pilot&&state.save?.save.id===dialog.saveId;
  const renderSceneImages = dialog => {
    if(!imageDialogActive(dialog))return;
    const busy=dialog.submitting||dialog.images.some(i=>i.status==='generating');
    const enabled=state.save.imageSettings?.enabled;
    $('generateScene').disabled=busy||!enabled||!!state.save.sessions.at(-1)?.ended_at;
    $('sceneDirection').disabled=dialog.submitting;
    $('sceneImageStatus').textContent=!enabled?'Configure the OpenAI API key on the host, then restart the server.':busy?'Generating a draft… You can close this window and keep playing. Reopen Illustrate Scene to review it.':'One low-quality landscape image per click. Each generation is a paid API request.';
    const latest=state.save.messages.findLast(m=>m.kind==='ai');
    $('sceneSourceNotice').textContent=latest?.id!==dialog.sourceId?'The story has moved on. This request still uses the narration shown below. Reopen this window to use the latest narration.':'';
    const rows=dialog.images.filter(i=>['draft','generating','failed'].includes(i.status));
    const key=JSON.stringify(rows)+String(latest?.id)+String(state.save.sessions.at(-1)?.ended_at);
    if(dialog.rendered===key)return;
    dialog.rendered=key;
    const previews=$('sceneImagePreviews');previews.replaceChildren();
    for(const item of rows.slice().reverse()){
      const source=state.save.messages.find(m=>m.id===item.source_message_id);
      const player=state.save.players.find(p=>p.id===item.player_id);
      const card=document.createElement('section');card.className='scene-preview';
      const heading=document.createElement('strong');heading.textContent=`${item.status==='draft'?'Draft illustration':item.status==='failed'?'Image request failed':'Generating illustration'} · ${player?.character||'Player'}`;card.append(heading);
      const note=document.createElement('p');note.textContent=`Source narration: ${source?new Date(source.created_at).toLocaleString():'earlier narration'}${latest?.id!==item.source_message_id?' · The story has moved on.':''}`;card.append(note);
      if(item.status==='draft'){
        const img=document.createElement('img');img.className='scene-image';img.alt='Draft scene illustration';
        img.src=`/api/saves/${dialog.saveId}/images/${item.id}?playerId=${encodeURIComponent(state.identity)}`;card.append(img);
      }
      if(item.error){const error=document.createElement('p');error.className='binding-issue';error.textContent=item.error;card.append(error);}
      if(item.status==='draft'||item.status==='failed'){
        const actions=document.createElement('div');actions.className='actions';
        for(const action of (item.status==='draft'?['share','discard']:['discard'])){
          const button=document.createElement('button');button.className='btn'+(action==='share'?' primary':'');
          button.textContent=action==='share'?'Share with Table':'Discard';
          button.disabled=action==='share'&&!!state.save.sessions.at(-1)?.ended_at;
          button.onclick=async()=>{
            if(!imageDialogActive(dialog))return;
            actions.querySelectorAll('button').forEach(b=>b.disabled=true);
            try{
              await request(`saves/${dialog.saveId}/images/${item.id}/${action}`,{playerId:state.identity,pilot:true});
              await refreshSceneImages(dialog);
              const updated=await request('saves/'+dialog.saveId);
              if(state.save?.save.id===dialog.saveId){state.save=updated;render();}
            }catch(error){if(imageDialogActive(dialog)){$('sceneImageError').textContent=error.message;dialog.rendered=null;renderSceneImages(dialog);}}
          };actions.append(button);
        }card.append(actions);
      }
      previews.append(card);
    }
  };
  const refreshSceneImages = async dialog => {
    if(!imageDialogActive(dialog))return;
    const result=await request(`saves/${dialog.saveId}/images?playerId=${encodeURIComponent(state.identity)}`);
    if(!imageDialogActive(dialog))return;
    dialog.images=result.images;renderSceneImages(dialog);
  };
  $('illustrateScene').onclick=async()=>{
    if(!state.pilot||!state.identity||!state.save)return;
    const source=state.save.messages.findLast(m=>m.kind==='ai');if(!source)return;
    const dialog={saveId:state.save.save.id,sourceId:source.id,images:[],submitting:false,polling:false,rendered:null};sceneDialog=dialog;
    modal(`<div id="sceneImageDialog"><h3>Illustrate Scene</h3><p id="sceneSourceNotice" class="binding-issue"></p><details><summary>Source: latest AI-DM narration</summary><div class="scene-source"></div></details><label>Visual direction (optional)<textarea id="sceneDirection" rows="3" maxlength="2000" placeholder="Show the ruined courtyard from the party's viewpoint."></textarea></label><p id="sceneImageStatus" role="status" aria-live="polite"></p><p id="sceneImageError" class="binding-issue" role="alert"></p><div class="actions"><button class="btn" data-close>Close</button><button class="btn primary" id="generateScene" disabled>Generate Draft</button></div><div id="sceneImagePreviews"></div></div>`,'wide');
    $('sceneImageDialog').querySelector('.scene-source').textContent=source.body;
    $('generateScene').onclick=async()=>{
      if(!imageDialogActive(dialog)||dialog.submitting)return;
      dialog.submitting=true;const direction=$('sceneDirection').value;
      $('sceneImageError').textContent='';renderSceneImages(dialog);
      try{
        const requestId=newRequestId();
        await request('saves/'+dialog.saveId+'/images',{playerId:state.identity,pilot:true,requestId,sourceMessageId:dialog.sourceId,direction});
      }catch(error){if(imageDialogActive(dialog))$('sceneImageError').textContent=error.message;}
      finally{
        dialog.submitting=false;
        if(imageDialogActive(dialog)){try{await refreshSceneImages(dialog);}catch(error){$('sceneImageError').textContent=error.message;}renderSceneImages(dialog);}
      }
    };
    try{await refreshSceneImages(dialog);}catch(error){if(imageDialogActive(dialog))$('sceneImageError').textContent=error.message;}
  };
  setInterval(async()=>{
    const dialog=sceneDialog;if(document.hidden||!dialog||!imageDialogActive(dialog)||dialog.polling)return;
    dialog.polling=true;
    try{await refreshSceneImages(dialog);}catch(error){if(imageDialogActive(dialog))$('sceneImageError').textContent=error.message;}
    finally{dialog.polling=false;}
  },2500);
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
  // Review Context shows the exact provider payload for the next advance and everything left out of it.
  const count=value=>new Intl.NumberFormat().format(value||0);
  const plural=(n,word)=>`${count(n)} ${word}${n===1?'':'s'}`;
  const when=value=>value?new Date(value).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'';
  const contextFlags=report=>{
    const flags=[],module=report.module,transcript=report.transcript,outcomes=report.combatOutcomes;
    if(module.truncated){
      const later=module.omittedSections;
      flags.push({level:'warn',text:`Module cut off: ${count(module.sentChars)} of ${count(module.chars)} characters sent.${module.cutSection?` The cut falls inside “${module.cutSection}”.`:''}${later.length?` ${plural(later.length,'later section')} not sent: ${later.slice(0,8).join(', ')}${later.length>8?', …':''}`:''}`});
    }
    if(transcript.omitted) flags.push({level:'warn',text:`${plural(transcript.omitted,'older message')} (${count(transcript.omittedChars)} characters, ${when(transcript.omittedFrom)} – ${when(transcript.omittedThrough)}) are not sent and not covered by a summary.`});
    if(outcomes?.omitted) flags.push({level:'warn',text:`${plural(outcomes.omitted,'older combat outcome')} not sent; only the latest ${count(outcomes.total-outcomes.omitted)} are included.`});
    if(transcript.currentBeatOverBudget) flags.push({level:'info',text:`The current beat is ${count(transcript.currentBeatChars)} characters, over the ${count(transcript.cap)}-character transcript budget. It is still sent in full.`});
    if(transcript.summarized) flags.push({level:'info',text:`${plural(transcript.summarized,'earlier message')} are represented by the saved summary instead of verbatim.`});
    if(module.staleLocation) flags.push({level:'warn',text:'The saved party location no longer exists in this cartridge. Approach is used until a Pilot picks the right area.'});
    if(!flags.some(flag=>flag.level==='warn')) flags.unshift({level:'ok',text:module.mode==='focused'?'Nothing is unexpectedly omitted. Module sections outside the current focus are left out by design; see Module focus below.':'Nothing is omitted. The full module and every unsummarized message are sent.'});
    return flags;
  };
  const contextKey=()=>state.save?state.save.save.id+'|'+state.save.save.updated_at:'';
  let contextFlagKey='';
  const refreshContextFlag=async()=>{
    const button=$('reviewContext'),key=contextKey();
    if(!state.pilot||!key||key===contextFlagKey||!state.save.cartridge.available)return;
    contextFlagKey=key;
    try{
      const preview=await request('saves/'+state.save.save.id+'/context');
      state.locations=preview.report.locations||[];renderLocation();
      const warnings=contextFlags(preview.report).filter(flag=>flag.level==='warn').length;
      button.classList.toggle('flagged',!!warnings);
      button.textContent=warnings?`Review Context · ${plural(warnings,'omission')}`:'Review Context';
    }catch(error){contextFlagKey='';console.error(error);}
  };
  const renderLocation=()=>{
    const wrap=$('pilotLocationWrap'),select=$('pilotLocation');
    wrap.classList.toggle('hidden',!state.locations.length);
    if(!state.locations.length||!state.save)return;
    const options=state.locations.map(item=>`<option value="${item.value??''}">${esc(item.label)}</option>`).join('');
    if(select.dataset.options!==options){select.innerHTML=options;select.dataset.options=options;}
    select.value=String(state.save.save.location??'');
    select.disabled=!state.identity||state.generating||state.updating;
  };
  $('pilotLocation').onchange=async event=>{
    const value=event.target.value;
    await update('location',{playerId:state.identity,location:value===''?null:Number(value)});
    renderLocation();
  };
  const moduleFocus=module=>{
    if(module.mode!=='focused') return `<p>${module.roomsInRunData?'run-data.json lists rooms, but module.md has no matching “### Area N” headings under “## Areas”, so':'run-data.json has no rooms, so'} the full module is sent every time.</p>`;
    const included=module.included.filter(item=>item.chars>20);
    const rows=included.map(item=>`<li><span>${esc(item.title.replace(/\s*\*\(.*\)\*\s*$/,''))}</span><span class="muted">${esc(item.reason)} · ${count(item.chars)}</span></li>`).join('');
    const skipped=module.excluded.map(title=>`<li>${esc(title.replace(/\s*\*\(.*\)\*\s*$/,''))}</li>`).join('');
    return `<p>Focused on <strong>${esc(module.locationLabel)}</strong>: sending ${count(module.sentChars)} of ${count(module.fullChars)} module characters. The core is always sent; areas and stat blocks follow the party and the subjects of current contributions. This count covers module text only.</p>
      <ul class="context-sections">${rows}</ul>
      ${skipped?`<details class="context-message"><summary>Not sent this turn · ${plural(module.excluded.length,'section')}</summary><ul class="context-skipped">${skipped}</ul></details>`:''}`;
  };
  const openContextReview=async()=>{
    if(!state.pilot||!state.save)return;
    modal('<h3>Review Context</h3><p>Loading the next AI-DM request…</p>','wide');
    let preview;
    try{preview=await request('saves/'+state.save.save.id+'/context');}
    catch(error){$('modalRoot').querySelector('.modal p').textContent=error.message;return;}
    const {report,summary,messages,runtime}=preview,total=messages.reduce((sum,m)=>sum+m.content.length,0);
    const prompt=report.narrationPrompt,upgrade=preview.promptUpdate;
    const promptLabel=p=>p.kind==='legacy'?'Legacy AI-DM instructions':`AdventureForge Stage 3 ${p.version} · TableForge integration ${p.integrationVersion}`;
    const promptInfo=`<div class="context-section"><div class="section-title">AI-DM instructions</div><p>${esc(promptLabel(prompt))}</p>
      ${upgrade?`<p>This cartridge provides different instructions. Review them before changing future narration in this save. History and Ready states are preserved.</p><details class="context-message"><summary>Review cartridge ${esc(promptLabel(upgrade))}</summary><pre>${esc(upgrade.instructions)}</pre></details><div class="actions"><button class="btn" id="upgradeNarrationPrompt"${state.identity&&!state.save.activity.aiDm?'':' disabled'}>Use cartridge instructions for this save…</button></div>`:''}
      ${preview.promptUpdateError?`<p class="muted">${esc(preview.promptUpdateError)} The saved instructions remain in use.</p>`:''}</div>`;
    const flags=contextFlags(report).map(flag=>`<li class="context-flag ${flag.level}">${esc(flag.text)}</li>`).join('');
    const summaryBlock=summary?`<div class="context-summary"><div class="muted">Saved by ${esc(summary.player_character||'a Pilot')} · ${esc(when(summary.created_at))}</div><div class="markdown-body">${TableForgeMarkdown.render(summary.body)}</div></div>`:'<p>No summary saved yet.</p>';
    const canSummarize=report.summaryAvailable>0;
    const payload=messages.map((m,i)=>`<details class="context-message"${i===messages.length-1?' open':''}><summary><strong>${esc(m.role)}</strong> · ${count(m.content.length)} characters</summary><pre>${esc(m.content)}</pre></details>`).join('');
    modal(`<h3>Review Context</h3>
      <p>${esc(runtime.provider==='openai'?`Exactly what the next advance sends to ${runtimeLabel(runtime)}, as the table stands right now.`:'Mock AI is active, so nothing leaves this machine. This is exactly what a live provider would receive for the next advance.')}</p>
      <ul class="context-flags">${flags}</ul>
      ${promptInfo}
      <div class="context-section"><div class="section-title">Module focus</div>${moduleFocus(report.module)}</div>
      <div class="context-section"><div class="section-title">Continuity summary</div>${summaryBlock}
        <div id="summaryDraft"></div>
        <div class="actions"><button class="btn" id="draftSummary"${canSummarize?'':' disabled'}>${canSummarize?`Summarize ${plural(report.summaryAvailable,'older message')}`:'Recent history fits; nothing to summarize yet'}</button></div>
      </div>
      <div class="context-section"><div class="section-title">Request · ${plural(messages.length,'message')} · ${count(total)} characters</div>${payload}</div>
      <div class="actions"><button class="btn" data-close>Close</button></div>`,'wide');
    $('draftSummary').onclick=()=>draftSummary(report.summaryAvailable);
    $('upgradeNarrationPrompt')?.addEventListener('click',async()=>{
      if(!confirm(`Use ${promptLabel(upgrade)} for future narration in this save? This does not generate a reply or restart the adventure.`))return;
      try{
        state.save=await request('saves/'+state.save.save.id+'/narration-prompt',{
          playerId:state.identity,pilot:true,confirm:true,fromSha256:prompt.sha256,toSha256:upgrade.sha256});
        render();await openContextReview();
      }catch(error){notify(error);}
    });
  };
  const draftSummary=async size=>{
    const button=$('draftSummary'),target=$('summaryDraft');
    button.disabled=true;button.textContent='Drafting summary…';
    let draft;
    try{draft=await request('saves/'+state.save.save.id+'/summary-draft',{playerId:state.identity});}
    catch(error){button.disabled=false;button.textContent=`Summarize ${plural(size,'older message')}`;return notify(error);}
    button.classList.add('hidden');
    target.innerHTML=`<label>Draft summary · replaces the saved summary and covers ${plural(draft.messageCount,'more message')}. Edit anything that is wrong before saving.<textarea id="summaryText" rows="10" maxlength="20000"></textarea></label><div class="actions"><button class="btn" id="discardSummary">Discard draft</button><button class="btn good" id="saveSummary">Save summary</button></div>`;
    $('summaryText').value=draft.draft;
    $('discardSummary').onclick=openContextReview;
    $('saveSummary').onclick=async()=>{
      const text=$('summaryText').value.trim();if(!text)return notify(Error('The summary cannot be empty.'));
      try{state.save=await request('saves/'+state.save.save.id+'/summaries',{playerId:state.identity,text,basedOn:draft.basedOn,throughMessageId:draft.throughMessageId});render();await openContextReview();}
      catch(error){notify(error);}
    };
  };
  $('reviewContext').onclick=openContextReview;
  $('pilotMap').onclick=()=>modal('<h3>GM Map</h3><p>Map viewing will be connected to validated cartridge assets.</p><div class="actions"><button class="btn" data-close>Close</button></div>');
  // Party knowledge: only what a Pilot writes down as known to the party. Nothing is read from the cartridge.
  const noteCategories={npcs:['npc','NPCs','NPC'],locations:['location','Locations','location'],notes:['world','World Notes','note']};
  const openNotes=(ref,editing=null)=>{
    const [category,heading,noun]=noteCategories[ref];
    const s=state.save;if(!s)return;
    const notes=(s.notes||[]).filter(n=>n.category===category);
    const character=id=>s.players.find(p=>p.id===id)?.character||'a Pilot';
    const canEdit=state.pilot&&!!state.identity;
    const saveNote=async body=>{
      try{state.save=await request('saves/'+s.save.id+'/notes',{playerId:state.identity,pilot:true,...body});render();openNotes(ref);}
      catch(error){notify(error);}
    };
    const form=editing?`<div class="note-form"><label>Name<input id="noteTitle" maxlength="200"></label><label>Known to the party<textarea id="noteBody" rows="5" maxlength="10000" placeholder="Only what the party has learned in play."></textarea></label><div class="actions"><button class="btn" id="noteCancel">Cancel</button><button class="btn good" id="noteSave">Save</button></div></div>`:'';
    const list=notes.map(n=>`<section class="note-card" data-note="${n.id}"><div class="row"><strong>${esc(n.title)}</strong>${canEdit&&!editing?'<span class="note-actions"><button class="btn small note-edit">Edit</button><button class="btn small warn note-remove">Remove</button></span>':''}</div><div class="markdown-body">${TableForgeMarkdown.render(n.body||'')}</div><div class="muted note-meta">Known · written by ${esc(character(n.updated_by||n.created_by))} · ${esc(when(n.updated_at))}</div></section>`).join('');
    modal(`<h3>${esc(heading)}</h3><p class="muted">Known to the party. Pilots add what the table has learned in play.</p>${editing?.id?'':form}<div class="note-list">${list||(editing?'':`<p>No ${esc(heading==='NPCs'?heading:heading.toLowerCase())} recorded yet.${canEdit?'':' Pilots can add entries in Pilot Mode.'}</p>`)}</div><div class="actions">${canEdit&&!editing?`<button class="btn primary" id="noteAdd">Add ${esc(noun)}</button>`:''}<button class="btn" data-close>Close</button></div>`,'wide');
    if(editing?.id) $('modalRoot').querySelector(`[data-note="${editing.id}"]`).innerHTML=form;
    $('noteAdd')?.addEventListener('click',()=>openNotes(ref,{}));
    $('modalRoot').querySelectorAll('.note-edit').forEach(button=>button.onclick=()=>openNotes(ref,notes.find(n=>n.id===Number(button.closest('[data-note]').dataset.note))));
    $('modalRoot').querySelectorAll('.note-remove').forEach(button=>button.onclick=async()=>{
      const note=notes.find(n=>n.id===Number(button.closest('[data-note]').dataset.note));
      if(!confirm(`Remove “${note.title}” from ${heading}? It stays in the save history.`))return;
      await saveNote({id:note.id,remove:true});
    });
    if(editing){
      $('noteTitle').value=editing.title||'';$('noteBody').value=editing.body||'';$('noteTitle').focus();
      $('noteCancel').onclick=()=>openNotes(ref);
      $('noteSave').onclick=async()=>{
        const title=$('noteTitle').value.trim();if(!title)return notify(Error(`Give the ${noun} a name.`));
        await saveNote({id:editing.id,category,title,body:$('noteBody').value});
      };
    }
  };
  document.querySelectorAll('.ref-open').forEach(b=>b.onclick=()=>noteCategories[b.dataset.ref]?openNotes(b.dataset.ref):modal(`<h3>${esc(b.textContent)}</h3><p>Player-safe reference entries will appear here after discovery tracking is built.</p><div class="actions"><button class="btn" data-close>Close</button></div>`));
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
  let refreshingTable=false;
  setInterval(async()=>{
    if(refreshingTable||document.hidden||!state.save||!$('play').classList.contains('active'))return;
    const saveId=state.save.save.id;refreshingTable=true;
    try{
      const next=await request('saves/'+saveId);
      if(state.save?.save.id!==saveId)return;
      if(next.save.updated_at!==state.save.save.updated_at){state.save=next;render();}
      else if(JSON.stringify(next.activity)!==JSON.stringify(state.save.activity)){state.save.activity=next.activity;fillPilotThread();renderActivity();}
    }catch(error){console.error(error);}
    finally{refreshingTable=false;}
  },2500);
})();
