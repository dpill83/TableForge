/* Choice eligibility and draft text shared by chat controls and their tests. */
const TableForgeMessageActions = (() => {
  const copyIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"></rect><path d="M16 8V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4"></path></svg>';
  const checkIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"></path></svg>';
  const errorIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"></path></svg>';
  const groupsFor=(choices,playerId)=>playerId?(choices?.groups||[]).filter(group=>group.playerId===null||group.playerId===playerId):[];
  const canChoose=(state,message,staleDraft=false)=>{
    const table=state.save,session=table?.sessions?.at(-1);
    return !!(table&&message?.kind==='ai'&&message.choices&&
      table.players.some(player=>player.id===state.identity)&&
      !state.generating&&!state.updating&&!table.activity?.aiDm&&!staleDraft&&
      session&&!session.ended_at&&message.session_id===session.id&&
      table.messages.findLast(item=>item.kind==='ai')?.id===message.id&&
      message.choices.beat===table.save.beat);
  };
  const appendText=(draft,text)=>draft?draft+(draft.endsWith('\n')?'':'\n')+text:text;
  return {copyIcon,checkIcon,errorIcon,groupsFor,canChoose,appendText};
})();
if(typeof module!=='undefined')module.exports=TableForgeMessageActions;
