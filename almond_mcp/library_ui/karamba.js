import {finite,metricState,utilizationFor,utilizationColour,projectPoint} from './analysis-view.mjs';
const el=id=>document.getElementById(id);
const token=new URLSearchParams(location.search).get('bridge')||'';
const native=/^[a-f0-9]{32}$/.test(token) && new URLSearchParams(location.search).get('panel')==='1';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let model=null,report=null,busy=false,dirty=false;
const settings=()=>({
  structure:el('analysis-type').value,material:el('analysis-material').value,load_kn:Number(el('analysis-load').value),
  self_weight:el('self-weight').checked,fixed_rotations:el('support-restraint').value==='fixed',
  explicit_supports:el('support-source').value==='points',
  diameter_mm:el('section-override').checked?Number(el('section-diameter').value):null,
  wall_mm:el('section-override').checked?Number(el('section-wall').value):null
});
function message(text) {el('analysis-message').textContent=text;}
function controls() {
  const colour=el('toggle-utilization');
  colour.disabled=!report||dirty||!report.result?.results?.utilization_available;
  if(colour.disabled)colour.checked=false;
  el('analysis-settings').disabled=busy;
  for(const id of ['section-diameter','section-wall'])el(id).disabled=!el('section-override').checked;
  document.querySelectorAll('[data-analysis]').forEach(b=>{
    b.disabled=!native||busy||(b.dataset.analysis==='analyze'&&!model)||
      (['highlight','export'].includes(b.dataset.analysis)&&(!report||dirty))||
      (b.dataset.analysis==='highlight'&&!report?.result?.worst_member_guids?.length);
  });
}
function request(action) {
  if(!native||busy)return;
  if(!el('analysis-form').reportValidity())return;
  const input=settings();
  if(input.diameter_mm!==null && input.wall_mm>=input.diameter_mm/2){message('Wall thickness must be less than half the diameter.');return;}
  busy=true;controls();
  message(action==='analyze'?'Running Karamba in Rhino…':action==='capture'?'Select structural geometry in Rhino…':'Working in Rhino…');
  location.href='/almond-action/'+token+'/karamba/'+action+'?data='+encodeURIComponent(JSON.stringify(input));
}
document.querySelectorAll('[data-analysis]').forEach(b=>{if(b.dataset.analysis!=='analyze')b.addEventListener('click',()=>request(b.dataset.analysis));});
el('analysis-form').addEventListener('submit',e=>{e.preventDefault();request('analyze');});
el('analysis-form').addEventListener('input',event=>{
  if(!event.target.closest('#analysis-settings'))return;
  dirty=!!report;el('section-fields').hidden=!el('section-override').checked;
  el('analysis-stale').hidden=!dirty;
  if(dirty)message('Inputs changed. Run analysis again to update the results.');
  controls();draw();
});
document.querySelectorAll('[data-analysis-view]').forEach(b=>b.addEventListener('change',draw));
window.almondAnalysisReceive = payload => {
  busy=false;
  if(payload.kind==='error'||payload.kind==='notice'){
    if(payload.stale && report){dirty=true;el('analysis-stale').hidden=false;}
    message(payload.message);controls();draw();return;
  }
  if(payload.kind==='status'){
    el('engine-state').textContent=payload.available?'Karamba detected':'Karamba unavailable';
    el('engine-detail').textContent=payload.detail||payload.message;message(payload.message);
  }
  if(payload.kind==='capture'){
    model=payload.model;report=null;dirty=false;
    el('analysis-results').hidden=true;el('analysis-stale').hidden=true;
    message('Selection captured. Review the assumptions and run analysis.');
  }
  if(payload.kind==='result'){
    model=payload.model;report=payload;dirty=false;el('analysis-stale').hidden=true;
    renderResult();message('Analysis snapshot recorded. Recapture if Rhino geometry changes.');
  }
  if(model) {
    el('selection-summary').textContent=model.objects+' objects · '+model.beams+' beams · '+model.shells+' shells · '+model.units;
    el('section-summary').textContent=model.default_sections+' beam sections use the CHS 114.3 × 4 mm default before overrides. Shell default: 100 mm. Inferred sections need review.';
  }
  controls();draw();
};
function renderResult(){
  const r=report.result,m=r.results||{},s=metricState(r);
  el('analysis-results').hidden=false;
  el('analysis-outcome').textContent=s.complete?(r.status==='pass'?'Within configured checks':'Configured checks exceeded'):
    r.status==='unavailable'?'Analysis unavailable':'Results incomplete';
  el('analysis-outcome').dataset.state=s.complete?r.status:'incomplete';
  el('analysis-method').textContent=m.analysis_method==='api'?'Karamba · first-order analysis':'No completed Karamba analysis';
  el('deflection-value').textContent=s.deflection==null?'Unavailable':s.deflection.toFixed(2)+' mm';
  el('utilization-value').textContent=s.utilization==null?'Unavailable':(s.utilization*100).toFixed(1)+'%';
  el('deflection-basis').textContent=s.limit==null?'No limit returned':'L/250 screen: '+s.limit.toFixed(2)+' mm';
  el('deflection-meter').value=s.deflection!=null&&s.limit?Math.min(s.deflection/s.limit,2):0;
  el('deflection-meter').hidden=s.deflection==null||!s.limit;
  el('utilization-meter').value=s.utilization==null?0:Math.min(s.utilization,2);
  el('utilization-meter').hidden=s.utilization==null;
  el('analysis-verdict').textContent=r.verdict||'No verdict returned.';
  el('analysis-warnings').replaceChildren(...(r.warnings||[]).map(t=>{const li=document.createElement('li');li.textContent=t;return li;}));
  el('analysis-suggestions').replaceChildren(...(r.suggestions||[]).map(t=>{const li=document.createElement('li');li.textContent=t;return li;}));
  el('analysis-snapshot').textContent='Snapshot '+new Date(report.created_at).toLocaleString()+'. Input geometry is not monitored live.';
  el('toggle-utilization').disabled=!s.complete && !m.utilization_available;
  el('toggle-utilization').checked=!!m.utilization_available;
}
const example={segments:[
  {a:[0,0,0],b:[0,0,3],guids:[]},{a:[0,0,3],b:[4,0,3],guids:[]},
  {a:[4,0,3],b:[4,0,0],guids:[]}],shell_outlines:[],anchors:[]};
function draw() {
  const source=model||example,view=el('analysis-view').value,m=report?.result?.results||{};
  const input=report&&!dirty?report.settings:settings();
  let supports=[],loads=[];
  const segments=source.segments||[],all=segments.flatMap(s=>[s.a,s.b]).concat((source.shell_outlines||[]).flat());
  if(report&&!dirty && m.analysis_method==='api'){supports=m.support_points_m||[];loads=m.loaded_points_m||[];}
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
  el('diagram-caption').textContent=!model?'Illustrative frame · no analysis results':report&&!dirty&&m.analysis_method==='api'?
    'Recorded model and load/support positions · no displacement field is plotted':'Selection preview · support and load locations are provisional until solved';
  el('diagram-load-note').textContent='Total imposed load '+input.load_kn+' kN ↓ · Self-weight '+(input.self_weight?'on':'off')+' · '+(input.fixed_rotations?'Fixed':'Pinned')+' supports';
  el('result-legend').hidden=!el('toggle-utilization').checked||!report||dirty;
}
el('analysis-native-note').hidden=native;
if(!native) message('Open AlmondKaramba inside Rhino to select geometry and run the solver.');
controls();draw();
