let strategyCatalog=[],activeStrategy=null,activeModule=null;
async function loadStrategies(){
 if(!strategyCatalog.length)strategyCatalog=await api('/api/strategies');
 $('#strategy-packages').innerHTML=strategyCatalog.map((s,i)=>`<button class="strategy-package" data-package="${i}"><span class="micro accent">STRATEGY PACKAGE · v${esc(s.version)}</span><h2>${esc(s.name)}</h2><p>${esc(s.description)}</p><span class="small subtle">${s.modules.length} modules · ${s.approval?'APPROVED VERSION':'NOT APPROVED FOR RUNS'} · ${esc(s.sha256.slice(0,12))}</span></button>`).join('');
 $$('[data-package]').forEach(b=>b.onclick=()=>showStrategy(Number(b.dataset.package)));
 if(activeStrategy===null)showStrategy(0);
 const versions=strategyCatalog.filter(s=>!s.prompt_builder).map(s=>s.version);
 for(const id of ['diff-before','diff-after']){$('#'+id).innerHTML=versions.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');$('#'+id).onchange=()=>loadStrategyDiff().catch(e=>notify(e.message,true));}
 $('#diff-before').value=versions[1]||versions[0];$('#diff-after').value=versions[0];
 await loadStrategyDiff();

}
function showStrategy(index){
 activeStrategy=strategyCatalog[index];$('#strategy-workspace').hidden=false;
 $('#strategy-goal').textContent=activeStrategy.goal;
 $('#strategy-title').textContent=activeStrategy.name+' / '+activeStrategy.version;
 $('#strategy-hash').textContent='Packet SHA-256 '+activeStrategy.sha256;
 $('#strategy-router').innerHTML=activeStrategy.selection_order.map((label,i)=>`<div class="route-node"><span class="micro accent">0${i+1}</span><strong>${esc(label)}</strong><small>First matching rule wins</small></div>`).join('<span class="route-arrow" aria-hidden="true">→</span>');
 const advice=activeStrategy.character_advice?.ironclad;let panel=$('#potion-priorities');if(!panel){panel=document.createElement('div');panel.id='potion-priorities';$('#strategy-router').after(panel)}panel.innerHTML=advice?'<details class="mt-3" open><summary>Ironclad potion priorities · conditional advice</summary><p>'+esc(advice.potion_policy)+'</p><table class="table"><thead><tr><th>Priority / situation</th><th>Potions</th><th>Advice</th></tr></thead><tbody>'+advice.groups.map(g=>'<tr><td>'+g.priority+' · '+esc(g.when)+'</td><td>'+esc(g.ids.join(', '))+'</td><td>'+esc(g.advice)+'</td></tr>').join('')+'</tbody></table><p class="small subtle">Only advice for held potions is sent during combat. These are situational priorities, not unconditional rankings.</p></details>':'';
 const groups={};
 for(const m of activeStrategy.modules){const category=m.category||(m.match.room?.includes('Boss')?'Boss prompts':m.match.room?.includes('Elite')?'Elite prompts':'Other decisions');const act=m.act?'Act '+m.act:'All acts / fallback';(groups[category]??={})[act]??=[];groups[category][act].push(m)}
 $('#strategy-modules').innerHTML=Object.entries(groups).map(([type,acts])=>`<details open><summary>${esc(type)} · ${Object.values(acts).flat().length}</summary>${Object.entries(acts).sort(([a],[b])=>a.localeCompare(b)).map(([act,modules])=>`<details><summary>${esc(act)} · ${modules.length}</summary>${modules.map(m=>`<button class="module-choice" data-module="${esc(m.id)}"><span>${esc(m.name)}</span><small>${esc(m.region||'')} · v${esc(m.version)}</small></button>`).join('')}</details>`).join('')}</details>`).join('');
 $$('[data-module]').forEach(b=>b.onclick=()=>showModule(b.dataset.module));
 showModule(activeStrategy.modules[0].id);
 $('#strategy-associated').innerHTML=runs.filter(r=>r.strategy_packet_sha256===activeStrategy.sha256).map(r=>`<button class="btn btn-sm btn-outline-primary" data-strategy-run="${esc(r.id)}">${esc(r.id)}</button>`).join('')||'<span class="subtle">No runs use this exact packet yet. Earlier runs retain their original prompts and are labeled legacy.</span>';
 $$('[data-strategy-run]').forEach(b=>b.onclick=()=>{view('runs');inspect(b.dataset.strategyRun).catch(e=>notify(e.message,true))});
}
function showModule(id){
 activeModule=activeStrategy.modules.find(m=>m.id===id);
 $$('[data-module]').forEach(b=>b.classList.toggle('active',b.dataset.module===id));
 const selected=$$('[data-module]').find(b=>b.dataset.module===id);if(selected){let parent=selected.parentElement;while(parent){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement}}
 $('#module-title').textContent=activeModule.name;
 $('#module-id').textContent=activeModule.id+' · v'+activeModule.version+' · priority '+activeModule.priority;
 $('#module-match').textContent=Object.keys(activeModule.match).length?json(activeModule.match):'Any supported decision not matched above';
 $('#module-prompt').textContent=activeModule.prompt;
 $('#module-why').textContent=activeModule.rationale;
 $('#module-assembled').textContent=activeStrategy.goal+'\n'+activeModule.prompt;
 showContextOptions().catch(e=>notify(e.message,true));
}
async function openRecordedStrategy(){
 const frozen=detail.strategy_packet;if(!frozen)return;
 await loadStrategies();const index=strategyCatalog.findIndex(s=>s.sha256===frozen.sha256);
 const entry={...frozen.packet,sha256:frozen.sha256,selection_order:strategyCatalog[0].selection_order};delete entry.prompt_builder;
 if(index<0)strategyCatalog.push(entry);
 view('strategies');showStrategy(index<0?strategyCatalog.length-1:index);
 $('#strategy-title').textContent+=' · recorded for '+detail.summary.id;
}

let contextCatalog=null,contextVersion=null;
async function showContextOptions(){
 const moduleId=activeModule.id;
 if(!contextCatalog||contextVersion!==activeStrategy.version){contextVersion=activeStrategy.version;contextCatalog=await api('/api/context-contracts/'+contextVersion);}
 if(activeModule.id!==moduleId)return;
 const kinds=activeModule.match.kind||Object.keys(contextCatalog);
 $('#context-kind').innerHTML=kinds.flatMap(k=>k==='card_selection'||k==='simple_select'?[k,k+':combat']:[k]).filter(k=>contextCatalog[k]).map(k=>`<option value="${esc(k)}">${esc(k.replace(':combat',' (in combat)'))}</option>`).join('');
 $('#context-kind').onchange=showContext;showContext();
}
function showContext(){
 const c=contextCatalog[$('#context-kind').value];if(!c)return;
 $('#context-fields').innerHTML='<div class="muted-box"><p><code>state.strategy</code> ← global goal + this encounter prompt</p><p><code>state.decision.state</code> ← the fields below, read fresh after each action</p><p><code>state.card_definitions</code> ← deduplicated card text, cost, and available card details</p><p><code>questions.action.criteria</code> ← legal actions, targets and offered choices</p></div><table class="table mt-3"><thead><tr><th>Game-state field</th><th>What is sent</th></tr></thead><tbody>'+c.fields.map(f=>`<tr><td class="context-path">${esc(f.name)}</td><td>${esc(f.description)}</td></tr>`).join('')+'</tbody></table><p class="small subtle">'+esc(c.notes)+'</p><p class="small subtle">Jev receives this structured request. Bifrost and CLI adapters carry the same context and choices in messages, with an added JSON response instruction. They do not receive the entire dashboard or raw observation.</p>';
 const request=structuredClone(c.example);request.state.strategy=activeStrategy.goal+'\n'+activeModule.prompt;
 $('#context-request').textContent=json(request);
 if(activeStrategy.prompt_format==='decision-v3')$('#context-fields').innerHTML='<div class="muted-box"><p><code>state.strategy</code>: goal + encounter advice + conditional Ironclad potion advice.</p><p><code>state.state</code>: compact combat text; structured deck/context for other decisions.</p><p><code>state.cards</code>: full effects for hand and action cards. Combat pile cards use unordered name/count summaries.</p><p><code>questions.action.criteria</code>: exact legal choices, with compact hand/enemy references.</p></div><p class="small subtle mt-3">'+esc(c.notes)+'</p>';
}

async function loadStrategyDiff(){
 const before=$('#diff-before').value,after=$('#diff-after').value;
 const result=await api('/api/strategy-diff/'+before+'/'+after);
 const target=strategyCatalog.find(s=>s.version===after);
 $('#diff-approval').textContent=target.approval?'Approved version: '+target.approval.reason:'Not approved for a new run. Review this diff and authorize it in the conversation.';
 if($('#diff-before').value!==before||$('#diff-after').value!==after)return;
 const labels={prompt:'Strategy prompt',rationale:'Reason for change',match:'Routing rule',version:'Module version',description:'Description',goal:'Global goal'};
 const render=(parts,side)=>parts.some(p=>p.text)?parts.map(p=>p.changed?`<${side==='old'?'del':'ins'}>${esc(p.text)}</${side==='old'?'del':'ins'}>`:esc(p.text)).join(''):'<span class="diff-empty">Not present in this version</span>';
 $('#strategy-diff').innerHTML=`<div class="diff-overview"><span>${result.sections.filter(s=>!s.metadata).length} changed modules · ${result.unchanged_modules} unchanged hidden</span><span class="diff-legend removed">− Removed</span><span class="diff-legend added">+ Added</span></div>`+result.sections.map(s=>`<details class="diff-section ${s.metadata?'metadata':''}" ${s.metadata?'':'open'}><summary>${esc(s.name)}<small>${esc(s.status)} · ${esc(s.id)}</small></summary><div class="diff-scroll"><div class="diff-columns"><div class="diff-headers"><div>− Before · ${esc(before)}</div><div>+ After · ${esc(after)}</div></div>${s.fields.map(f=>`<div class="diff-field">${esc(labels[f.field]||f.field)}</div><div class="diff-row"><div class="diff-cell old">${render(f.left,'old')}</div><div class="diff-cell new">${render(f.right,'new')}</div></div>`).join('')}</div></div></details>`).join('')+(result.sections.length?'':'<p>No differences between these versions.</p>');
}
