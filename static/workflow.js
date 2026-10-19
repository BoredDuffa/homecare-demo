/* Address lookup and the review-before-apply Excel workflow. */
let editorLookupMap=null;
function lookupPanel(value=''){
  return `<div class="address-lookup"><div class="lookup-heading"><h3>Find an address or Eircode</h3>${tag('PUBLIC DEMO')}</div>${field('Address / Eircode','address_lookup',value,'text','Try Trinity College Dublin or D02 PN40. Review the selected point; complete Eircode coverage is not configured.','maxlength="250"')}<button type="button" class="button secondary" data-action="find-address">⌕ Find on Dublin map</button><p class="lookup-note">Public-place demo searches use the bundled gazetteer or Photon / OpenStreetMap. Only the search text is sent; no care records are sent.</p><div id="lookup-results" aria-live="polite"></div><div id="lookup-map" class="lookup-map" hidden></div></div>`;
}
function showLookupMap(candidate){
  if(editorLookupMap){editorLookupMap.remove();editorLookupMap=null;}
  const node=$('#lookup-map');if(!node||typeof L==='undefined')return;
  node.hidden=false;editorLookupMap=L.map(node,{scrollWheelZoom:false}).setView([candidate.lat,candidate.lng],15);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'}).addTo(editorLookupMap);
  L.circleMarker([candidate.lat,candidate.lng],{radius:8,color:'#fff',weight:2,fillColor:'#217467',fillOpacity:1}).addTo(editorLookupMap);
}
async function findAddress(){
  const edit=state.edit,query=$('#f-address_lookup').value.trim(),box=$('#lookup-results');
  if(edit.loading)return;
  edit.loading=true;edit.selectedLocation=null;edit.lookedUpQuery=query;
  box.innerHTML='<p class="lookup-note">Looking up the public address…</p>';
  try{
    const r=await api('/api/geocode',{query,public_demo:true});
    if(state.edit!==edit||!$('#editor').open)return;
    edit.candidates=r.candidates;
    box.innerHTML=r.candidates.length?r.candidates.map((c,i)=>`<div class="lookup-candidate"><div><strong>${esc(c.name)}</strong><p>${esc(c.label)}</p><small>${esc(c.precision)} · ${esc(c.provider)}</small></div><button type="button" class="button secondary small" data-action="pick-address" data-index="${i}">Select & review</button></div>`).join(''):`<p class="lookup-error">${esc(r.notice)}</p>`;
  }catch(err){if(state.edit===edit)box.innerHTML=`<p class="lookup-error">${esc(err.message)}</p>`;}
  finally{edit.loading=false;}
}
function pickAddress(index){
  const edit=state.edit,c=edit.candidates?.[index];if(!c)return;
  edit.selectedLocation=clone(c);
  $('#lookup-results').innerHTML=`<div class="lookup-selected"><strong>Selected: ${esc(c.label)}</strong><p>${esc(c.precision)}</p><small>${esc(c.provider)} · Check the map before saving.</small></div>`;
  if($('#f-lat'))$('#f-lat').value=c.lat;if($('#f-lng'))$('#f-lng').value=c.lng;
  if(edit.type==='location'&&!$('#f-name').value.trim())$('#f-name').value=c.name;
  showLookupMap(c);
}
function selectedAddress(){
  const e=state.edit,q=$('#f-address_lookup')?.value.trim()||'';
  if(e.selectedLocation&&q===e.lookedUpQuery)return e.selectedLocation;
  if(q!==e.originalQuery&&q)throw Error('Find the address and select a result, or use an existing location.');
  return null;
}
function candidateFields(c){return {lat:c.lat,lng:c.lng,address:c.address||c.label,eircode:c.eircode||'',geocode_source:c.provider,geocode_label:c.label};}
function locationForCandidate(p,c,name){
  const existing=p.locations.find(l=>Math.abs((l.lat??999)-c.lat)<.000001&&Math.abs((l.lng??999)-c.lng)<.000001);
  if(existing)return existing.id;
  if(p.locations.length>=30)throw Error('This demo supports at most 30 locations.');
  const id=uid('home');p.locations.push({id,name:name+' · home',x:50,y:50,...candidateFields(c)});
  p.travel_matrix.forEach(row=>row.push(0));p.travel_matrix.push(p.locations.map(()=>0));return id;
}
async function automaticRoadTimes(){
  state.problem.routing={kind:'pending',provider:'Locations changed; road times pending',live_traffic:false};
  state.result=null;state.comparison=null;state.busy='roads';persist();render();
  try{const r=await api('/api/road-matrix',state.problem);Object.assign(state.problem,r);state.roadError=null;persist();toast('Location saved and road travel times calculated.');}
  catch(err){state.roadError='Location saved, but road times could not update. '+err.message;persist();}
  finally{state.busy=false;render();}
}
function excelView(){
  const preview=state.excelPreview;
  return `<p class="section-intro">One row per record. Stable IDs connect the sheets. Importing shows a preview first; applying replaces the current draft and calculates road travel times.</p><div class="excel-cards"><section class="panel"><div class="panel-head"><div><h2>1. Get the framework</h2><p>A filled example you can edit in Excel.</p></div></div><div class="panel-body"><p class="section-intro">Six input sheets, consistent headers, real Excel times and example rows. No coordinates are required when an address can be resolved.</p><a class="button secondary" href="/api/excel/template" download>↓ Download Excel template</a></div></section><section class="panel"><div class="panel-head"><div><h2>2. Import & review</h2><p>Your current roster stays intact until Apply.</p></div></div><div class="panel-body"><p class="section-intro">Use .xlsx, up to 5 MB. Input cells accept values; paste formula results as values before importing.</p><button class="button primary" data-action="import-excel">↑ Choose Excel workbook</button></div></section><section class="panel"><div class="panel-head"><div><h2>3. Export your work</h2><p>Inputs plus verified results when available.</p></div></div><div class="panel-body"><p class="section-intro">Export the current inputs, or include the roster, routes and continuity summary after generating.</p><button class="button secondary" data-action="export-excel-inputs">↓ Export inputs</button> <button class="button secondary" data-action="export-excel-results" ${accepted()?'':'disabled'}>↓ Export roster</button></div></section></div>
  ${state.excelError?`<div class="notice error"><div><strong>Workbook could not be imported</strong>${esc(state.excelError)}</div></div>`:''}
  ${preview?excelPreviewView(preview):''}
  <section class="panel"><div class="panel-head"><div><h2>The simple framework</h2><p>Keep sheet names and row 1 headers unchanged. Add new rows below the example records.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Sheet</th><th>One row represents</th><th>What you enter</th></tr></thead><tbody>${[
    ['Settings','A planning setting','Week starting, timezone, continuity cap and preferences'],['Clients','A client','ID, name and either location ID or address/Eircode; optional continuity override'],['Carers','A carer','ID, name, skills, weekly hours, days off and certification expiry'],['Availability','One availability range on one day','Carer ID, day, times, start/end location IDs and optional break'],['Visits','A recurring visit rule','Client ID, days, earliest start, latest finish, duration and skills'],['Locations','A shared place or depot','ID, name, address/Eircode; coordinates are optional']].map(r=>`<tr>${r.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section><div class="side-tip"><strong>Address lookup is a demo feature.</strong>Bundled Eircode examples: D02 PN40 (Trinity), D02 XN27 (Dublin Castle), D08 VF8H (Guinness Storehouse). Other public addresses can be searched through Photon. Coverage is incomplete; every unresolved or ambiguous location needs review.</div>`;
}
function excelPreviewView(p){
  const unresolved=p.draft?p.draft.locations.filter(l=>l.lat===null||l.lng===null):[];
  return `<section class="panel"><div class="panel-head"><div><h2>Import preview · ${esc(p.filename||'workbook')}</h2><p>${p.counts.clients||0} clients · ${p.counts.carers||0} carers · ${p.counts.visits||0} individual visits · ${unresolved.length} unresolved locations</p></div><button class="button primary" data-action="apply-excel" ${p.draft&&!p.issues.length&&!unresolved.length?'':'disabled'}>Apply & calculate travel</button></div><div class="panel-body"><p class="section-intro">This replaces the current draft only when you click Apply. Existing generated results are not imported as verified schedules.</p>${p.issues.length?`<div class="notice error"><div><strong>${p.issues.length} input issue${p.issues.length===1?'':'s'} to fix in Excel</strong>${p.issues.map(i=>`<div>${esc(i.sheet)} · row ${i.row} · ${esc(i.field)}: ${esc(i.message)}</div>`).join('')}</div>`:'<p class="section-intro">Input tables passed validation.</p>'}${unresolved.map(l=>{const origin=p.unresolved.find(x=>x.location_id===l.id);return `<div class="lookup-candidate"><div><strong>${esc(l.name)}</strong><p>${esc(l.address||'No address entered')}</p><small>${esc(origin?.sheet||'Locations')} · row ${origin?.row||'—'} · Select a map location before applying.</small></div><button class="button secondary small" data-action="resolve-excel-location" data-id="${esc(l.id)}">Review location</button></div>`;}).join('')}${p.draft?`<details class="advanced-coordinates"><summary>Review all ${p.draft.locations.length} imported locations</summary><div class="table-wrap"><table class="data-table"><thead><tr><th>Location</th><th>Address / matched label</th><th>Source</th></tr></thead><tbody>${p.draft.locations.map(l=>`<tr><td>${esc(l.name)}</td><td>${esc(l.geocode_label||l.address||'Coordinates supplied')}</td><td>${esc(l.geocode_source||(l.lat===null?'Unresolved':'Workbook coordinates'))}</td></tr>`).join('')}</tbody></table></div></details>`:''}${p.draft&&!unresolved.length&&!p.issues.length?'<div class="notice"><div><strong>Ready to apply</strong>All locations have coordinates. Road times will be calculated before the imported draft replaces your current one.</div></div>':''}</div></section>`;
}
async function chooseExcel(){
  const input=document.createElement('input');input.type='file';input.accept='.xlsx';input.onchange=async()=>{
    if(!input.files?.[0])return;
    state.busy='excel';state.excelError=null;render();
    try{const f=new FormData();f.append('file',input.files[0]);const response=await fetch('/api/excel/import',{method:'POST',body:f}),data=await response.json();if(!response.ok)throw Error(data.detail||'Import failed.');state.excelPreview={...data,filename:input.files[0].name};}
    catch(err){state.excelError=err.message;}
    finally{state.busy=false;render();}
  };input.click();
}
function openExcelLocation(id){
  const l=state.excelPreview.draft.locations.find(x=>x.id===id);state.edit={scope:'excel',location_id:id,originalQuery:l.address||'',candidates:[]};
  $('#editor').classList.remove('wide');$('#modal-title').textContent='Review imported location';$('#modal-error').textContent='';
  $('#modal-body').innerHTML=`<p class="section-intro">${esc(l.name)}. This changes only the import preview.</p>${lookupPanel(l.address||'')}<details class="advanced-coordinates"><summary>Advanced: enter coordinates manually</summary><div class="fields-row">${field('Latitude','lat','','number','','min="53.15" max="53.65" step="any"')}${field('Longitude','lng','','number','','min="-6.65" max="-5.95" step="any"')}</div></details>`;
  $('#editor').showModal();
}
function commitExcelLocation(){
  const e=state.edit,c=e.selectedLocation,query=$('#f-address_lookup').value.trim();
  let values;
  if(c&&query===e.lookedUpQuery)values=candidateFields(c);
  else{const lat=$('#f-lat').value,lng=$('#f-lng').value;if(!lat||!lng)throw Error('Find and select a result, or enter both coordinates.');values={lat:+lat,lng:+lng,address:query,geocode_source:'Manual coordinates'};}
  if(!(values.lat>=53.15&&values.lat<=53.65&&values.lng>=-6.65&&values.lng<=-5.95))throw Error('Use coordinates inside the Dublin demo area.');
  Object.assign(state.excelPreview.draft.locations.find(l=>l.id===e.location_id),values);$('#editor').close();render();
}
async function applyExcel(){
  const preview=state.excelPreview;if(!preview?.draft||preview.issues.length)return;
  state.busy='roads';render();
  try{
    const next=await api('/api/excel/prepare',preview.draft);
    state.problem=next;state.example='custom';state.disrupted=false;state.result=null;state.comparison=null;state.error=null;state.roadError=null;state.excelPreview=null;persist();toast('Workbook applied. Road times are ready; generate your roster.');
  }catch(err){state.excelError='Import was not applied. '+err.message;}
  finally{state.busy=false;render();}
}
async function exportExcel(withResults){
  if(withResults&&!accepted())return;
  state.busy='excel';render();
  try{const r=await fetch('/api/excel/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({problem:state.problem,result:withResults?state.result:null})});if(!r.ok){const data=await r.json();throw Error(data.detail||'Excel export failed.');}download(withResults?'HomeCare-roster.xlsx':'HomeCare-scenario.xlsx',await r.blob(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');}
  catch(err){toast(err.message);}
  finally{state.busy=false;render();}
}
document.addEventListener('click',async e=>{
  const el=e.target.closest('[data-action]');if(!el||el.disabled)return;
  const action=el.dataset.action;
  try{
    if(action==='refresh-simulation')await refreshSimulationStatus();if(action==='find-address')await findAddress();if(action==='pick-address')pickAddress(+el.dataset.index);
    if(action==='import-excel')await chooseExcel();if(action==='apply-excel')await applyExcel();
    if(action==='resolve-excel-location')openExcelLocation(el.dataset.id);
    if(action==='export-excel-inputs')await exportExcel(false);if(action==='export-excel-results')await exportExcel(true);
  }catch(err){toast(err.message);}
});
document.addEventListener('submit',e=>{
  if(e.target.id==='edit-form'&&state.edit?.scope==='excel'){
    e.preventDefault();e.stopImmediatePropagation();try{commitExcelLocation();}catch(err){$('#modal-error').textContent=err.message;}
  }
});
document.addEventListener('change',e=>{
  if(e.target.name==='location'&&$('#editor').open){const l=state.problem.locations.find(l=>l.id===e.target.value);if(l&&$('#f-address_lookup')){$('#f-address_lookup').value=l.address||l.name;state.edit.originalQuery=$('#f-address_lookup').value;state.edit.selectedLocation=null;$('#lookup-results').innerHTML='';if(editorLookupMap){editorLookupMap.remove();editorLookupMap=null;}$('#lookup-map').hidden=true;}}
});
document.getElementById('editor').addEventListener('close',()=>{if(editorLookupMap){editorLookupMap.remove();editorLookupMap=null;}});

async function refreshSimulationStatus(){
  if(state.simulationLoading)return;
  state.simulationLoading=true;
  try{state.simulation=await api('/api/simulation');state.simulationError=null;}
  catch(err){state.simulationError=err.message;}
  finally{state.simulationLoading=false;if(state.view==='simulation')render();}
}
function simulationView(){
  const s=state.simulation;
  if(state.simulationError)return `<div class="notice error"><div><strong>Simulation status unavailable</strong>${esc(state.simulationError)}</div></div>`;
  if(!s)return '<p class="section-intro">Reading the local simulation checkpoint…</p>';
  if(!s.available)return '<div class="notice"><div><strong>No simulation has been started.</strong>Local stress runs save checkpoints and reports independently of this browser.</div></div>';
  const date=x=>new Date(x).toLocaleString('en-IE',{timeZone:'Europe/Dublin',dateStyle:'medium',timeStyle:'medium'});
  const c=s.counts,progress=Math.min(100,s.elapsed_seconds/s.duration_seconds*100);
  const active=s.in_flight?.profile;
  const statuses={running:'Running locally',completed:'Run ended',failed:'Stopped after a failure',interrupted:'Interrupted — resume available',paused_at_case_limit:'Smoke test paused',code_changed:'Stopped: source changed',runner_error:'Runner error'};
  return `<div class="notice ${c.failures?'error':''}"><div><strong>${esc(statuses[s.status]||s.status)}</strong>${esc(s.run_id)} · ${esc(s.solver_revision||'baseline')} · ${progress.toFixed(1)}% of the wall-clock window${s.status==='running'&&active?' · Current case: '+esc(active):''}</div><a class="button secondary small" href="/api/simulation/report" download>↓ Download report</a></div>
  <p class="section-intro">Started ${esc(date(s.started_at))}. Deadline ${esc(date(s.deadline_at))} Dublin time. Updated ${esc(date(s.updated_at))}. Auto-refreshes every 15 seconds while this view is open.</p>
  <section class="stats" aria-label="Simulation metrics">${[
    ['Completed cases',s.completed_cases,'Saved after each case'],['Verified rosters',c.accepted||0,'Every emitted roster checked'],['Proven infeasible',c.infeasible||0,'Impossible cases kept explicit'],['Failures',c.failures||0,'Stops on a correctness/runtime failure']
  ].map(([label,value,note])=>`<div class="stat"><div class="stat-label">${esc(label)}</div><div class="stat-value">${value}</div><div class="stat-foot">${esc(note)}</div></div>`).join('')}</section>
  <div class="side-tip"><strong>Local CPU work · no AI calls or paid API requests.</strong>Fictional clients and the cached Dublin road matrix. One solver worker per case. ${c.unknown||0} searches ended without a roster; ${c.timeouts||0} cases hit the outer time limit. Both are inconclusive. ${c.mutations_rejected||0} deliberately damaged schedules were rejected by independent checks. This is test evidence, not a production safety guarantee.</div>
  <section class="panel" style="margin-top:24px"><div class="panel-head"><div><h2>Scenario coverage</h2><p>Up to 200 weekly visits, 50 clients and 16 carers. Known-feasible generated cases have a separately checked witness schedule.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Profile</th><th>Cases</th><th>Verified</th><th>Infeasible</th><th>Unknown</th><th>Timeouts</th><th>Failures</th></tr></thead><tbody>${Object.entries(s.profiles).map(([name,r])=>`<tr><td>${esc(name.replaceAll('_',' '))}</td>${['cases','accepted','infeasible','unknown','timeouts','failures'].map(k=>`<td>${r[k]||0}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>
  <p class="section-intro">Checkpoints resume at case boundaries with the same seed and original deadline. An interrupted CP-SAT search is rerun; its internal search state is not restored. The worker continues if this tab closes. Closing the laptop or restarting it may interrupt progress.</p>`;
}
setInterval(()=>{if(state.view==='simulation'&&!document.hidden)refreshSimulationStatus();},15000);
