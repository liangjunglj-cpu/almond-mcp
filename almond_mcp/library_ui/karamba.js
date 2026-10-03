import {finite,metricState,utilizationFor,utilizationColour,projectPoint,engineLabel,stabilityState} from './analysis-view.mjs';
const el=id=>document.getElementById(id);
const token=new URLSearchParams(location.search).get('bridge')||'';
const native=/^[a-f0-9]{32}$/.test(token) && new URLSearchParams(location.search).get('panel')==='1';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let model=null,report=null,busy=false,dirty=false,checked=false,codes=null,pending=null;   // pending: the action Rhino has not answered yet
const engine=()=>el('analysis-engine').value;
const optional=id=>{const v=el(id).value.trim();return v===''?null:Number(v);};
const settings=()=>{
  const base={
    engine:engine(),structure:el('analysis-type').value,material:el('analysis-material').value,load_kn:Number(el('analysis-load').value),
    self_weight:el('self-weight').checked,fixed_rotations:el('support-restraint').value==='fixed',
    explicit_supports:el('support-source').value==='points',
    diameter_mm:el('section-override').checked?Number(el('section-diameter').value):null,
    wall_mm:el('section-override').checked?Number(el('section-wall').value):null
  };
  if(base.engine!=='native')return base;
  return {...base,floor_imposed_kn_m2:Number(el('floor-imposed').value),floor_dead_kn_m2:Number(el('floor-dead').value),
    asset_loads:el('asset-loads').checked,connections:el('analysis-connections').value,design_basis:'en1990',
    design_code:el('analysis-code').value,uls_combination:el('analysis-uls').value||null,
    deflection_limit_ratio:optional('analysis-limit'),fabrication:el('analysis-fabrication').value,
    stability:el('analysis-stability').value,view:el('analysis-overlay').value,span_m:optional('analysis-span')};
};
// One status line under Run for everything the panel does: idle, busy, ok, warn, error or info, with an icon and colour.
// Errors carry a hint on how to fix them, so the user is never left with only the message.
const HINTS=[
  [/at most 200/i,'Join short segments into continuous curves (Almond splits them at every crossing), or check part of the structure.'],
  [/library blocks/i,'Select the structural centre lines and support points, not furniture blocks.'],
  [/finish the current rhino command|rhino was busy/i,'Press Esc in Rhino to end the running command, then try again.'],
  [/still running/i,'Wait for the current run to finish.'],
  [/document units/i,'Set standard document units in Rhino (Options > Units), then capture again.'],
  [/certificate|unknownissuer/i,'Security software or a proxy on this network inspects HTTPS. Allow uv to use the Windows certificates: in PowerShell run [Environment]::SetEnvironmentVariable("UV_NATIVE_TLS","1","User"), restart Rhino, then press Check engines.'],
  [/uv is not installed|could not start the native solver|engine unavailable/i,'Install uv (winget install astral-sh.uv), restart Rhino, then press Check engines.'],
  [/geometry changed|recapture|model changed/i,'The geometry changed after capture: click Use Rhino selection again on the Model tab.'],
  [/mechanism|unstable|singular/i,'Part of the frame can move freely: add support points, or use Fixed restraints or Rigid joints on the Supports tab.'],
  [/no (curve|structural|exported|geometry)/i,'Select the structural centre lines in Rhino, then Use Rhino selection on the Model tab.'],
  [/faces|simplify/i,'Use a simpler surface or mesh, or draw centre lines instead.'],
  [/wall thickness/i,'On the Model tab, make the CHS wall less than half its diameter.']];
function hintFor(text){const h=HINTS.find(([re])=>re.test(text||''));return h?h[1]:'Read the warnings on the Results tab, or Troubleshooting in the Almond structure tutorial.';}
function message(text,state='info',hint) {
  el('analysis-message').textContent=text;el('analysis-status').dataset.state=state;
  const tip=state==='error'?(hint??hintFor(text)):hint;
  el('analysis-hint').textContent=tip?'How to fix: '+tip:'';el('analysis-hint').hidden=!tip;
}
// A capture's answer belongs in step 01, beside the button pressed: the shared status line is at the foot of the form.
function captureNote(text,error) {const s=el('selection-summary');s.textContent=text;s.classList.toggle('error',!!error);s.classList.remove('need');}
// Design code profiles come from the solver (built-in Eurocode, a practice's National Annex files, "off").
function showCodes(list) {
  if(!list?.profiles?.length)return;
  codes=list;
  let saved=el('analysis-code').value;
  try{saved=localStorage.getItem('almond-design-code')||saved;}catch{}
  el('analysis-code').replaceChildren(...list.profiles.map(p=>{
    const o=document.createElement('option');o.value=p.id;
    o.textContent=p.name+(p.verified?'':' · unverified');return o;}));
  el('analysis-code').value=list.profiles.some(p=>p.id===saved)?saved:list.default;
  codeControls();
}
function codeControls() {
  const id=el('analysis-code').value,p=codes?.profiles?.find(x=>x.id===id),uls=el('analysis-uls');
  try{localStorage.setItem('almond-design-code',id);}catch{}
  const fixed=!p||id==='off'||p.uls_expression!=='either';
  uls.disabled=fixed;if(fixed)uls.value='';
  uls.options[0].textContent=p?'Code default · '+(id==='off'?'unfactored':p.uls_expression==='either'?p.uls_default:p.uls_expression):'Code default';
  el('analysis-limit').placeholder=p?'code: '+p.deflection_limit_ratio:'code';
  const floors=Object.entries(p?.imposed_floor_kn_m2||{}).map(([k,v])=>k.replace(/^[A-Z]+_/,'').replace(/_/g,' ')+' '+v);
  el('code-note').textContent=!p?'Load factors, material factors and the deflection limit come from the design code profile.':
    id==='off'?'No design code: characteristic G + Q, no partial factors, span/250 screen. For comparisons, not design.':
    p.basis+'.'+(floors.length?' Suggested floor loads (kN/m²): '+floors.join(', ')+'.':'')+
    (p.verified?'':' Unverified values: '+p.unverified.join(', ')+' — results are provisional.');
  advancedSummary();
}
// The Code tab holds what a first check leaves at its default. Its line names whatever differs from the default, and
// the tab shows a dot, so a changed limit or code is never hidden behind it: [control, default, how to say it].
const ADVANCED=[['analysis-code',()=>codes?.default||'eurocode',()=>el('analysis-code').selectedOptions[0]?.textContent||'code'],
  ['analysis-uls','',v=>'ULS '+v],['analysis-stability','auto',()=>'stability off'],['analysis-span','',v=>'span '+v+' m'],
  ['analysis-limit','',v=>'limit L/'+v],['support-source','auto',()=>'supports at points only'],
  ['analysis-fabrication','cold_formed',()=>'hot-finished tubes']];
function advancedSummary() {
  const nativeEngine=engine()==='native';
  const changed=ADVANCED.filter(([id,def])=>{const n=el(id);
    return !(n.closest('[data-native]')&&!nativeEngine)&&n.value!==(typeof def==='function'?def():def);}).map(([id,,say])=>say(el(id).value));
  if(nativeEngine&&el('asset-loads').checked)changed.push('placed-model loads');
  el('advanced-summary').textContent=changed.length?'Changed: '+changed.join(' · '):'All at their defaults';
  el('advanced-summary').classList.toggle('error',changed.length>0);
  el('tab-code').querySelector('.tab-dot').hidden=!changed.length;
}
// The workspace in tabs; Run and its status line stay in view below them.
const TABS=['model','loads','supports','code','results'];
function showTab(name) {
  for(const t of TABS){const on=t===name,b=el('tab-'+t);b.setAttribute('aria-selected',String(on));b.tabIndex=on?0:-1;el('pane-'+t).hidden=!on;}
  try{localStorage.setItem('almond-structure-tab',name);}catch{}
}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>showTab(b.dataset.tab)));
// In the Rhino panel the Almond header is pinned to the top as well: pin the tab bar just below it.
const masthead=document.querySelector('.masthead');
function pinTabs(){const pinned=masthead&&getComputedStyle(masthead).position==='sticky';
  document.documentElement.style.setProperty('--tabs-top',(pinned?masthead.offsetHeight:0)+'px');}
pinTabs();addEventListener('resize',pinTabs);
document.querySelector('.analysis-tabs').addEventListener('keydown',e=>{
  const i=TABS.indexOf(document.activeElement?.dataset?.tab);if(i<0)return;
  const step={ArrowRight:1,ArrowLeft:-1,Home:-i,End:TABS.length-1-i}[e.key];if(step===undefined)return;
  e.preventDefault();const next=TABS[(i+step+TABS.length)%TABS.length];showTab(next);el('tab-'+next).focus();
});
function engineControls() {
  const nativeEngine=engine()==='native';
  document.querySelectorAll('#analysis-settings [data-native]').forEach(n=>n.hidden=!nativeEngine);
  const shell=el('analysis-type').querySelector('[data-engine="karamba"]');
  shell.disabled=nativeEngine;
  if(nativeEngine&&el('analysis-type').value==='shell')el('analysis-type').value='frame';
  el('analysis-run').textContent=nativeEngine?'Run native analysis ↗':'Run Karamba analysis ↗';
  try{localStorage.setItem('almond-structure-engine',engine());}catch{}
  advancedSummary();
}
function controls() {
  const ready=renderReadiness();
  const colour=el('toggle-utilization');
  colour.disabled=!report||dirty||!report.result?.results?.utilization_available;
  if(colour.disabled)colour.checked=false;
  el('analysis-settings').disabled=busy;el('analysis-engine').disabled=busy;
  el('results-empty').hidden=!el('analysis-results').hidden;
  el('tab-results').querySelector('.tab-dot').hidden=!(report&&dirty);   // results out of date
  for(const id of ['section-diameter','section-wall'])el(id).disabled=!el('section-override').checked;
  document.querySelectorAll('[data-analysis]').forEach(b=>{
    b.disabled=!native||busy||(b.dataset.analysis==='analyze'&&!ready)||
      (['highlight','export'].includes(b.dataset.analysis)&&(!report||dirty))||
      (b.dataset.analysis==='highlight'&&!report?.result?.worst_member_guids?.length)||
      (b.dataset.analysis==='clear_view'&&!report?.native?.drawn)||
      (b.dataset.analysis==='results'&&(!report||dirty));
  });
  el('analysis-results').querySelector('[data-analysis="clear_view"]').hidden=!report?.native;
}
function request(action) {
  if(!native||busy)return;
  if(action==='analyze'&&!el('analysis-form').reportValidity())return;
  const input=settings();
  if(input.diameter_mm!==null && input.wall_mm>=input.diameter_mm/2){message('Wall thickness must be less than half the diameter.','error');return;}
  busy=true;pending=action;controls();
  if(action==='capture')captureNote('Select structural geometry in Rhino…');
  message(action==='analyze'?(input.engine==='native'?'Exporting the model from Rhino…':'Running Karamba in Rhino…'):
    action==='capture'?'Select structural geometry in Rhino…':action==='status'?'Checking engines…':'Working in Rhino…','busy');
  location.href='/almond-action/'+token+'/karamba/'+action+'?data='+encodeURIComponent(JSON.stringify(input));
}
document.querySelectorAll('[data-analysis]').forEach(b=>{if(b.dataset.analysis!=='analyze')b.addEventListener('click',()=>request(b.dataset.analysis));});
el('analysis-form').addEventListener('submit',e=>{e.preventDefault();request('analyze');});
el('analysis-code').addEventListener('change',codeControls);
el('analysis-engine').addEventListener('change',()=>{
  engineControls();
  if(report){dirty=true;el('analysis-stale').hidden=false;message('Engine changed. Run analysis again to update the results.','warn');}
  controls();draw();
});
el('analysis-form').addEventListener('input',event=>{
  if(!event.target.closest('#analysis-settings')||event.target.closest('[data-analysis-view]'))return;   // diagram toggles only redraw
  dirty=!!report;el('section-fields').hidden=!el('section-override').checked;
  el('analysis-stale').hidden=!dirty;
  if(dirty)message('Inputs changed. Run analysis again to update the results.','warn');
  controls();draw();
});
document.querySelectorAll('[data-analysis-view]').forEach(b=>b.addEventListener('change',draw));
const engineState={karamba:'Karamba not checked',native:'Native engine not checked'};
function showEngines(){
  el('engine-state').textContent=engineState.native+' · '+engineState.karamba;
  const n=engine()==='native'?engineState.native:engineState.karamba;
  el('engine-state').dataset.state=/ready|detected/i.test(n)?'ok':/starting|checking/i.test(n)?'busy':/unavailable|not installed/i.test(n)?'error':'idle';
  controls();
}
// What a run needs before it can start: a checklist beside Run, and a "!" on the tab that still needs input.
function readiness(){
  const nativeEngine=engine()==='native',n=nativeEngine?engineState.native:engineState.karamba;
  const loads=Number(el('analysis-load').value)>0||el('self-weight').checked||
    (nativeEngine&&(Number(el('floor-imposed').value)>0||Number(el('floor-dead').value)>0||el('asset-loads').checked));
  const anchors=model?.anchors?.length||0,points=el('support-source').value==='points';
  const down=/unavailable|not installed/i.test(n);
  return [
    {key:'engine',tab:null,label:'Engine',state:/ready|detected/i.test(n)?'ok':down?'error':'busy',
     tip:down?'Press Check engines; the note under the engine line says why.':'Checking the engine…'},
    {key:'model',tab:'model',label:'Structure',state:model?'ok':'need',
     tip:model?model.beams+' beams · '+model.shells+' shells':'Model tab: select in Rhino, then Use Rhino selection'},
    {key:'loads',tab:'loads',label:'Loads',state:loads?'ok':'need',tip:loads?'Loads set':'Loads tab: add a load or self-weight'},
    {key:'supports',tab:'supports',label:'Supports',state:points&&model&&!anchors?'need':'ok',
     tip:points&&model&&!anchors?'Supports tab: select support points, or allow the lowest nodes':(anchors?anchors+' support points':'Lowest nodes')}];
}
function renderReadiness(){
  const items=readiness();
  el('run-checklist').replaceChildren(...items.map(i=>{
    const n=document.createElement('li');n.dataset.state=i.state;n.title=i.tip;
    const icon=document.createElement('span');icon.className='ck-icon';icon.setAttribute('aria-hidden','true');n.append(icon,i.label);
    if(i.tab){n.tabIndex=0;n.addEventListener('click',()=>showTab(i.tab));n.addEventListener('keydown',e=>{if(e.key==='Enter')showTab(i.tab);});}
    return n;}));
  for(const i of items)if(i.tab){const need=el('tab-'+i.tab).querySelector('.tab-need');if(need)need.hidden=i.state!=='need';}
  el('loads-required').hidden=items.find(i=>i.key==='loads').state!=='need';
  return items.every(i=>i.state==='ok');
}
window.almondAnalysisReceive = payload => {
  if(payload.kind==='progress'){message(payload.message,'busy');return;}          // still busy: the solver is running
  if(payload.kind==='native_status'){
    showCodes(payload.design_codes);
    engineState.native=payload.available?'Native engine ready'+(payload.version?' · v'+payload.version:''):'Native engine unavailable';
    if(!payload.available)el('engine-detail').textContent=payload.detail||'';
    // the engine answers after the "starting" status: settle the status line with the outcome
    if(el('analysis-status').dataset.state==='busy'&&/engine/i.test(el('analysis-message').textContent))
      payload.available?message('Engines checked. Native engine ready'+(payload.version?' · v'+payload.version:'')+'.','ok'):
        message('Native engine unavailable'+(payload.detail?': '+payload.detail:'.'),'error');
    showEngines();return;
  }
  busy=false;
  const answered=pending;pending=null;
  if(payload.kind==='error'||payload.kind==='notice'){
    if(answered==='capture')captureNote(payload.message,payload.kind==='error');
    if(payload.stale && report){dirty=true;el('analysis-stale').hidden=false;}
    message(payload.message,payload.kind==='error'?'error':'ok');controls();draw();return;
  }
  if(payload.kind==='status'){
    engineState.karamba=payload.available?'Karamba detected':'Karamba not installed';
    const n=payload.native||{};
    engineState.native=n.checking?'Native engine starting…':n.available===false?'Native engine unavailable':engineState.native;
    el('engine-detail').textContent=[n.detail,payload.detail||payload.message].filter(Boolean).join(' · ');
    showEngines();
    if(n.available===false)message('Native engine unavailable'+(n.detail?': '+n.detail:'.'),'error');
    else if(n.checking)message('Starting the native engine… The first run downloads it.','busy');
    else message('Engines checked.','ok');
  }
  if(payload.kind==='capture'){
    model=payload.model;report=null;dirty=false;
    el('analysis-results').hidden=true;el('analysis-stale').hidden=true;
    message('Selection captured. Review the tabs, then Run.','ok');
  }
  if(payload.kind==='result'){
    showTab('results');
    model=payload.model;report=payload;dirty=false;el('analysis-stale').hidden=true;
    renderResult();
    resultStatus();
  }
  if(model) {
    captureNote(model.objects+' objects · '+model.beams+' beams · '+model.shells+' shells · '+model.units);
    el('section-summary').textContent=model.default_sections+' beam sections use the CHS 114.3 × 4 mm default before overrides. Shell default: 100 mm. Inferred sections need review.';
  }
  controls();draw();
};
const li=text=>{const n=document.createElement('li');n.textContent=text;return n;};
function nativeFacts(r,nat){
  const m=r.results||{},facts=[],code=r.design_code;
  if(code)facts.push('Design code: '+code.name+(code.unverified?.length?' (unverified: '+code.unverified.join(', ')+')':''));
  if(m.connections)facts.push(m.connections.mode==='simple'?'Simple connections · '+m.connections.pinned_ends+' pinned member ends':'Rigid joints');
  if(r.floor_loads)facts.push('Floor '+(r.floor_loads.imposed_kn_m2+r.floor_loads.dead_kn_m2)+' kN/m² over '+r.floor_loads.area_m2.toFixed(1)+' m² · '+r.floor_loads.total_kn.toFixed(1)+' kN');
  if(r.asset_loads)facts.push(r.asset_loads.applied+' placed model'+(r.asset_loads.applied===1?'':'s')+' as loads · '+r.asset_loads.total_kn.toFixed(1)+' kN');
  if(m.deflection_combination)facts.push('Deflection at '+m.deflection_combination+' · members checked at '+(m.combinations||[]).slice(1).map(c=>c.name).join(', '));
  if(finite(m.reactions_kn))facts.push('Support reactions '+m.reactions_kn.toFixed(1)+' kN (SLS) · '+m.nodes+' nodes · '+m.elements+' elements · '+m.solve_ms+' ms');
  if(nat.version)facts.push('Solver almond-mcp '+nat.version);
  return facts;
}
// The run's outcome in the status line: green within the checks, amber indicative, red exceeded or unstable.
function resultStatus(){
  const r=report.result||{},nat=report.native||{},s=metricState(r);
  const figures=[s.deflection!=null?s.deflection.toFixed(1)+' mm':null,s.utilization!=null?(s.utilization*100).toFixed(0)+'%':null].filter(Boolean).join(' · ');
  const outcome=el('analysis-outcome').textContent+(figures?' · '+figures:'');
  if(nat.draw_error)return message(outcome+'. The viewport overlay could not be drawn: '+nat.draw_error,'warn');
  if(r.status==='pass')return message(outcome,'ok');
  if(r.status==='indicative')return message(outcome,'warn','Concrete, timber and aluminium are not capacity-checked yet: read the forces and deflection, and have the members designed to their code.');
  if(!s.complete)return message(outcome,'error',/unstable/i.test(outcome)?hintFor('unstable'):undefined);
  return message(outcome,'error','The Results tab lists the governing member and check: try a larger section (Model tab), stiffer joints (Supports tab), or the real span (Code tab).');
}
function renderResult(){
  const r=report.result,m=r.results||{},s=metricState(r),nat=report.native,st=stabilityState(r,nat);
  el('analysis-results').hidden=false;
  el('analysis-outcome').textContent=s.complete?(r.status==='indicative'?'Indicative only · no capacity check for '+(r.material||'this material'):
    r.status==='pass'?'Within configured checks':'Configured checks exceeded'):
    nat&&r.status==='fail'?'Unstable · see the verdict':r.status==='unavailable'?'Analysis unavailable':'Results incomplete';
  el('analysis-outcome').dataset.state=s.complete||(nat&&r.status==='fail')?r.status:'incomplete';
  el('analysis-method').textContent=engineLabel(r,report.settings);
  el('deflection-value').textContent=s.deflection==null?'Unavailable':s.deflection.toFixed(2)+' mm';
  el('utilization-value').textContent=s.utilization==null?'Unavailable':(s.utilization*100).toFixed(1)+'%';
  el('deflection-basis').textContent=s.limit==null?'No limit returned':'L/'+(m.span_m?Math.round(m.span_m*1000/s.limit):250)+' limit: '+s.limit.toFixed(2)+' mm'+
    (m.span_m?' · span '+m.span_m+' m ('+m.span_basis+')':'');
  el('utilization-basis').textContent=m.utilization_combination?'Governing: '+m.utilization_combination+'. 100% is the threshold.':'100% is the configured utilization threshold.';
  el('deflection-meter').value=s.deflection!=null&&s.limit?Math.min(s.deflection/s.limit,2):0;
  el('deflection-meter').hidden=s.deflection==null||!s.limit;
  el('utilization-meter').value=s.utilization==null?0:Math.min(s.utilization,2);
  el('utilization-meter').hidden=s.utilization==null;
  el('stability-block').hidden=!st;
  if(st){el('stability-value').textContent=st.value;el('stability-basis').textContent=st.basis;}
  const facts=nat?nativeFacts(r,nat):[];
  el('native-facts').hidden=!facts.length;el('native-facts').replaceChildren(...facts.map(li));
  el('overlay-note').textContent=!nat?'Bars are capped visually at 200%; numerical values remain uncapped. Maximum deflection is shown numerically. A deformed shape is unavailable.':
    nat.draw_error?nat.draw_error:!nat.drawn?'Nothing was drawn in the viewport for this result.':
    nat.view==='buckling'?'The first buckling mode is drawn in the Rhino viewport. A mode has a shape but no size: it is normalised for display.':
    'The deflected shape (exaggerated) and member utilization are drawn in the Rhino viewport. Bars here are capped at 200%.';
  el('analysis-verdict').textContent=r.verdict||'No verdict returned.';
  el('analysis-warnings').replaceChildren(...(r.warnings||[]).map(li));
  el('analysis-suggestions').replaceChildren(...(r.suggestions||[]).map(li));
  el('analysis-snapshot').textContent='Snapshot '+new Date(report.created_at).toLocaleString()+'. Input geometry is not monitored live.';
  el('toggle-utilization').disabled=!s.complete && !m.utilization_available;
  el('toggle-utilization').checked=!!m.utilization_available;
}
const example={segments:[
  {a:[0,0,0],b:[0,0,3],guids:[]},{a:[0,0,3],b:[4,0,3],guids:[]},
  {a:[4,0,3],b:[4,0,0],guids:[]}],shell_outlines:[],anchors:[]};
function draw() {
  const source=model||example,view=el('analysis-view').value,m=report?.result?.results||{};
  const solved=report&&!dirty&&['api','native'].includes(m.analysis_method)&&Array.isArray(m.support_points_m);
  const input=report&&!dirty?report.settings:settings();
  let supports=[],loads=[];
  const segments=source.segments||[],all=segments.flatMap(s=>[s.a,s.b]).concat((source.shell_outlines||[]).flat());
  if(solved){supports=m.support_points_m||[];loads=m.loaded_points_m||[];}
  else if(all.length){
    const low=Math.min(...all.map(p=>p[2]));
    supports=input.explicit_supports?(source.anchors||[]):(source.anchors?.length?source.anchors:all.filter(p=>Math.abs(p[2]-low)<1e-6));
    if(input.load_kn>0) loads=all.filter(p=>!supports.some(s=>s.every((v,k)=>Math.abs(v-p[k])<1e-6)));
  }
  const points=all.concat(supports,loads).map(p=>projectPoint(p,view)).filter(Boolean);
  if(!points.length){el('analysis-diagram').innerHTML='<text x="20" y="50">No drawable member geometry.</text>';return;}
  const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),lo=[Math.min(...xs),Math.min(...ys)],hi=[Math.max(...xs),Math.max(...ys)];
  const scale=Math.min(260/Math.max(hi[0]-lo[0],.1),150/Math.max(hi[1]-lo[1],.1));
  const xy=p=>{const q=projectPoint(p,view);return q?[(q[0]-(lo[0]+hi[0])/2)*scale+160,(q[1]-(lo[1]+hi[1])/2)*scale+120]:null;};
  const svg=[];
  if(el('toggle-members').checked) {
    segments.forEach(s=>{const a=xy(s.a),b=xy(s.b);if(!a||!b)return;
      const value=report&&!dirty&&m.utilization_available?utilizationFor(s.guids||[],m.per_element_utilization):null;
      const colour=el('toggle-utilization').checked?utilizationColour(value):'var(--diagram-member,#333b36)';
      svg.push('<line x1="'+a[0]+'" y1="'+a[1]+'" x2="'+b[0]+'" y2="'+b[1]+'" stroke="'+colour+'" stroke-width="4"><title>'+esc(value==null?'Member axis':(value*100).toFixed(1)+'% · maximum mapped utilization')+'</title></line>');
    });
    (source.shell_outlines||[]).forEach(r=>svg.push('<polyline points="'+r.map(xy).filter(Boolean).map(p=>p.join(',')).join(' ')+'" fill="none" stroke="var(--diagram-shell,#69776e)" stroke-width="2"/>'));
  }
  const unique=ps=>[...new Map(ps.map(p=>[p.join(','),p])).values()];
  if(el('toggle-supports').checked)unique(supports).forEach(p=>{const q=xy(p);if(!q)return;const [x,y]=q;
    svg.push(input.fixed_rotations?'<path d="M '+(x-7)+' '+(y+3)+' h 14 v 7 h -14 Z" fill="var(--diagram-support,#237963)"/>':
      '<path d="M '+x+' '+(y+2)+' l -7 11 h 14 Z" fill="none" stroke="var(--diagram-support,#237963)" stroke-width="2"/>');
  });
  if(el('toggle-loads').checked)unique(loads).slice(0,80).forEach(p=>{const q=xy(p);if(!q)return;const [x,y]=q;
    svg.push('<path d="M '+x+' '+(y-27)+' v 22 m -4 -5 l 4 5 l 4 -5" fill="none" stroke="var(--diagram-load,#df432c)" stroke-width="2"/>');
  });
  el('analysis-diagram').innerHTML=svg.join('');
  el('diagram-caption').textContent=!model?'Illustrative frame · no analysis results':solved?
    'Recorded model and load/support positions'+(report.native?.drawn?' · the deformed shape is drawn in the Rhino viewport':' · no displacement field is plotted'):
    'Selection preview · support and load locations are provisional until solved';
  const extra=input.engine==='native'&&(input.floor_imposed_kn_m2||input.floor_dead_kn_m2)?' · Floor '+(input.floor_imposed_kn_m2+input.floor_dead_kn_m2)+' kN/m²':'';
  el('diagram-load-note').textContent='Total imposed load '+input.load_kn+' kN ↓'+extra+(input.asset_loads?' · Placed models':'')+
    ' · Self-weight '+(input.self_weight?'on':'off')+' · '+(input.fixed_rotations?'Fixed':'Pinned')+' supports';
  el('result-legend').hidden=!el('toggle-utilization').checked||!report||dirty;
}
try{const saved=localStorage.getItem('almond-structure-engine');if(saved==='karamba'||saved==='native')el('analysis-engine').value=saved;}catch{}
engineControls();codeControls();
el('analysis-settings').addEventListener('input',advancedSummary);
el('analysis-settings').addEventListener('change',advancedSummary);
// an invalid value on another tab would stop Run with nothing in view: show its tab
el('analysis-form').addEventListener('invalid',e=>{const pane=e.target.closest('[data-pane]');if(pane)showTab(pane.dataset.pane);},true);
let savedTab='model';try{savedTab=localStorage.getItem('almond-structure-tab')||'model';}catch{}
showTab(TABS.includes(savedTab)?savedTab:'model');
el('analysis-native-note').hidden=native;
if(!native) message('Open AlmondStructure inside Rhino to select geometry and run the solver.','info');
// check the engines once, the first time the workspace is shown (it also fetches the native solver)
function firstVisit(){if(native&&!checked&&location.hash==='#karamba'){checked=true;setTimeout(()=>{if(!busy)request('status');},300);}}
addEventListener('hashchange',firstVisit);firstVisit();
controls();draw();
