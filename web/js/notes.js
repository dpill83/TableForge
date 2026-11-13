/* Durable, revision-checked autosave. Kept independent of dialog lifetime. */
(function(root){
  class NotesSession {
    constructor({storage,key,send,uuid,changed=()=>{},delay=650,retry=3000}){
      Object.assign(this,{storage,key,send,uuid,changed,delay,retry});
      this.drafts=new Map();this.timers=new Map();this.running=new Set();
      try{for(const d of JSON.parse(storage.getItem(key)||'[]'))this.drafts.set(d.key,d);}
      catch{this.storageError=true;}
    }
    persist(){
      try{
        this.storage.setItem(this.key,JSON.stringify([...this.drafts.values()].filter(d=>d.dirty||d.op||d.conflict)));
        this.storageError=false;
      }catch{this.storageError=true;}
      this.changed();
    }
    edit(note){
      const key=note?.id?String(note.id):this.uuid();
      if(!this.drafts.has(key))this.drafts.set(key,{key,id:note?.id,clientKey:note?.client_key||this.uuid(),
        revision:note?.revision,title:note?.title||'',body:note?.body||'',dirty:false,status:note?'Saved':'',version:0});
      return this.drafts.get(key);
    }
    input(d,title,body){
      Object.assign(d,{title,body,dirty:true,version:d.version+1,status:'Saving…'});
      this.persist();this.schedule(d,this.delay);
    }
    schedule(d,delay){
      clearTimeout(this.timers.get(d.key));
      this.timers.set(d.key,setTimeout(()=>{this.timers.delete(d.key);this.flush(d);},delay));
    }
    async flush(d){
      clearTimeout(this.timers.get(d.key));
      this.timers.delete(d.key);
      if(this.running.has(d.key)||d.conflict||(!d.dirty&&!d.op))return;
      if(!d.op){
        if(!d.title.trim()||d.title.trim().length>200||d.body.length>10000){
          d.status='Couldn’t save';d.error='Use a title of 1–200 characters and text of at most 10,000 characters.';
          this.persist();return;
        }
        d.op={id:d.id,clientKey:d.clientKey,revision:d.revision,category:'world',title:d.title.trim(),body:d.body,mutationId:this.uuid()};
        d.sentVersion=d.version;
      }
      this.running.add(d.key);d.status='Saving…';d.error='';this.persist();
      try{
        const result=await this.send(d.op);
        const saved=result.notes.find(n=>d.op.id?n.id===d.op.id:n.client_key===d.clientKey);
        if(!saved)throw Object.assign(Error('This note was deleted. Your draft has been kept.'),{code:'note_conflict'});
        d.id=saved.id;d.revision=saved.revision;
        d.dirty=d.version!==d.sentVersion;
        if(!d.dirty){d.title=saved.title;d.body=saved.body;}
        d.op=null;d.status=d.dirty?'Saving…':'Saved';
      }catch(error){
        d.status='Couldn’t save';d.error=error.message;
        if(error.code==='note_conflict')d.conflict=true;
      }finally{
        this.running.delete(d.key);this.persist();
        if((d.dirty||d.op)&&!d.conflict)this.schedule(d,this.retry);
      }
    }
    resume(){for(const d of this.drafts.values())if((d.dirty||d.op)&&!d.conflict&&!this.timers.has(d.key))this.flush(d);}
    discard(d){clearTimeout(this.timers.get(d.key));this.drafts.delete(d.key);this.persist();}
    copy(d){
      const copy=this.edit();
      this.input(copy,d.title,d.body);this.discard(d);return copy;
    }
  }
  if(typeof module!=='undefined')module.exports={NotesSession};
  else root.TableForgeNotes={NotesSession};
})(globalThis);
