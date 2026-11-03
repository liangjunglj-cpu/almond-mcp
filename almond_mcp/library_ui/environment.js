// Environment workspace: site, rooms, constructions, study, results. Data and diagrams come from the
// environment engine (almond-mcp environment) through the Rhino panel; the catalogue is a static file.
const el=id=>document.getElementById(id);
const token=new URLSearchParams(location.search).get('bridge')||'';
const native=/^[a-f0-9]{32}$/.test(token) && new URLSearchParams(location.search).get('panel')==='1';
const TABS=['site','rooms','constructions','study','results'];
const COUNTRIES=['at','be','bg','cy','cz','de','dk','ee','es','fi','fr','gr','hr','hu','ie','it','lt','lu','lv','mt','nl','pl','pt','ro','se','si','sk','uk'];
const DE_BANDS=['<=1918','1919-1948','1949-1957','1958-1968','1969-1978','1979-1983','1984-1994','1995-2001','>=2002'];
let cat=null,state={epw:'',site:null,rooms:null,result:null},busy=false,active='site';

function svgInto(id,svg){const n=el(id);if(!n)return;n.innerHTML=svg||'';}       // engine SVG only: names are XML-escaped there
function text(id,s){const n=el(id);if(n)n.textContent=s;}
function message(s,kind='info'){text('env-message',s);el('env-status').dataset.state=kind;}
function li(list,items){const n=el(list);n.replaceChildren(...items.map(s=>{const i=document.createElement('li');i.textContent=s;return i;}));}

function showTab(name){
  active=name;
  for(const t of TABS){
    const tab=el('etab-'+t),pane=el('epane-'+t),on=t===name;
    tab.setAttribute('aria-selected',on);tab.tabIndex=on?0:-1;pane.hidden=!on;
  }
  if(cat)svgInto('env-strip',cat.steps[name]);
  try{localStorage.setItem('almond-env-tab',name);}catch{}
}
document.querySelectorAll('[data-etab]').forEach(b=>b.addEventListener('click',()=>showTab(b.dataset.etab)));
document.querySelector('.env-tabs').addEventListener('keydown',e=>{
  const i=TABS.indexOf(active),step=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0;
  if(!step)return;e.preventDefault();const next=TABS[(i+step+TABS.length)%TABS.length];showTab(next);el('etab-'+next).focus();
});

function option(value,label){const o=document.createElement('option');o.value=value;o.textContent=label;return o;}
function fillConstructions(){
  if(!cat)return;
  const kind=el('env-kind').value,region=el('env-region').value,keep=el('env-construction').value;
  const list=cat.constructions.filter(c=>(!kind||c.kind===kind)&&(!region||c.regions.includes(region)||c.regions.includes('any')));
  el('env-construction').replaceChildren(...list.map(c=>option(c.id,`${c.name} · U ${c.u_value.toFixed(2)}`+(c.kind==='window'?` · g ${c.g_value.toFixed(2)}`:''))));
  if(list.some(c=>c.id===keep))el('env-construction').value=keep;else if(list.length)el('env-construction').selectedIndex=0;
  showSection();
}
function showSection(){const id=el('env-construction').value;svgInto('env-section',id&&cat?.sections?.[id]||'');}
function fillPackOptions(){
  const pack=el('env-pack').value,sel=el('env-pack-opt');
  const opts=pack==='sg_bca'?[['ettv','ETTV · non-residential'],['retv','RETV · residential']]:
    pack==='uk_adl_2021'?[['dwelling','Dwellings'],['other','Buildings other than dwellings']]:
    pack==='de_banz_2020'?DE_BANDS.map(b=>[b,b]):pack==='eu_hotmaps'?COUNTRIES.map(c=>[c,c.toUpperCase()]):[];
  sel.replaceChildren(...opts.map(([v,l])=>option(v,l)));
  el('env-pack-opt-label').hidden=!opts.length;
  const p=cat?.packs?.find(x=>x.pack===pack);
  text('env-pack-note',p?`${p.relation==='method'?'Method implemented by Almond':'Bundled values'} · ${p.licence}. ${p.attribution||''}`:'');
}
function packOptions(){
  const pack=el('env-pack').value,v=el('env-pack-opt').value;
  return pack==='sg_bca'?{residential:v==='retv'}:pack==='uk_adl_2021'?{dwelling:v!=='other'}:
    pack==='de_banz_2020'?{age_band:v}:pack==='eu_hotmaps'?{country:v}:{};
}
function studyControls(){
  const s=el('env-study').value;
  document.querySelectorAll('#epane-study [data-for]').forEach(n=>n.hidden=n.dataset.for!==s);
  if(cat)svgInto('env-study-diagram',cat.study[s]);
  checklist();
}

async function loadCatalogue(){
  try{
    const r=await fetch('/api/environment');if(!r.ok)throw new Error(r.status);
    cat=await r.json();
  }catch(e){message('The environment catalogue could not load: '+e.message,'error');return;}
  el('env-room-use').replaceChildren(...Object.keys(cat.uses).map(u=>option(u,u[0].toUpperCase()+u.slice(1))));
  el('env-room-set').append(...cat.sets.map(s=>option(s.id,s.name)));
  el('env-pack').append(...cat.packs.map(p=>option(p.pack,{sg_bca:'Singapore · ETTV / RETV',uk_adl_2021:'England · Approved Document L',de_banz_2020:'Germany · age-band U-values',eu_hotmaps:'EU · stock U-values'}[p.pack]||p.pack)));
  li('env-sources',cat.sources.map(s=>`${s.title} — ${s.licence}`));
  fillConstructions();fillPackOptions();studyControls();
  let saved='site';try{saved=localStorage.getItem('almond-env-tab')||'site';}catch{}
  showTab(TABS.includes(saved)?saved:'site');
}

function checklist(){
  const study=el('env-study').value;
  const items=[
    {label:'Weather file',ok:!!state.epw||study==='daylight'&&el('env-daylight').value==='daylight_factor',tab:'site'},
    {label:'Rooms checked',ok:!!state.rooms?.length,tab:'rooms'},
    {label:'Constructions',ok:!!state.rooms?.some(r=>r.constructions_on_boundary.length||r.construction_set),tab:'constructions',optional:true}];
  el('env-checklist').replaceChildren(...items.map(i=>{
    const n=document.createElement('li');n.dataset.state=i.ok?'ok':i.optional?'info':'need';
    const ic=document.createElement('span');ic.className='ck-icon';ic.setAttribute('aria-hidden','true');n.append(ic,i.label);
    n.tabIndex=0;n.addEventListener('click',()=>showTab(i.tab));return n;}));
  el('etab-site').querySelector('.tab-need').hidden=items[0].ok;
  el('etab-rooms').querySelector('.tab-need').hidden=items[1].ok;
  el('env-run').disabled=busy||!items[0].ok||!items[1].ok||!native;
}

function request(action,input={}){
  if(!native){message('Open AlmondEnvironment in Rhino to use this workspace with your model.','info');return;}
  if(busy)return;
  busy=true;checklist();
  message({run:'Exporting the model…',rooms:'Checking rooms…',define_room:'Select the room in Rhino…',assign:'Select elements in Rhino…'}[action]||'Working in Rhino…','busy');
  location.href='/almond-action/'+token+'/environment/'+action+'?data='+encodeURIComponent(JSON.stringify(input));
}
function settings(){
  const blinds=el('env-blinds').checked;
  return {construction:el('env-preset').value,schedule:'residential',natural_ventilation_ach:Number(el('env-nv').value)||0,
    shading_g_factor:blinds?0.15:1,shading_min_outdoor_c:blinds?12:null,cooling:el('env-cooling').checked,heat_recovery:Math.min(Math.max((Number(el('env-hr').value)||0)/100,0),0.95),daylight_study:el('env-daylight').value,
    quality:el('env-quality').value,spacing_m:Number(el('env-spacing').value)||0.5};
}
document.querySelectorAll('[data-env]').forEach(b=>b.addEventListener('click',()=>{
  const a=b.dataset.env;
  if(a==='define_room'){
    if(!el('env-room-name').value.trim()){message('Name the room first.','error');el('env-room-name').focus();return;}
    request(a,{name:el('env-room-name').value.trim(),use:el('env-room-use').value,construction_set:el('env-room-set').value,
      height_m:el('env-room-height').value,heating_setpoint_c:el('env-room-heat').value,cooling_setpoint_c:el('env-room-cool').value});
  }else if(a==='assign'){
    if(!el('env-construction').value){message('Pick a construction.','error');return;}
    request(a,{construction:el('env-construction').value});
  }else if(a==='run'){
    request('run',{study:el('env-study').value,settings:settings(),envelope_pack:el('env-pack').value,pack_options:packOptions()});
  }else request(a,{});
}));
['env-kind','env-region'].forEach(id=>el(id).addEventListener('change',fillConstructions));
el('env-construction').addEventListener('change',showSection);
el('env-pack').addEventListener('change',fillPackOptions);
el('env-study').addEventListener('change',studyControls);
el('env-daylight').addEventListener('change',checklist);

function showRooms(p){
  state.rooms=p.rooms;
  svgInto('env-room-plan',p.svg);
  const tb=el('env-room-table');tb.hidden=!p.rooms.length;
  tb.tBodies[0].replaceChildren(...p.rooms.map(r=>{
    const tr=document.createElement('tr');
    const label={enclosed:'Enclosed',semi_open:'Semi-open',open:'Open'}[r.enclosure.state];
    for(const v of [r.room,r.use,r.floor_area_m2.toFixed(1)+' m²',label+(r.enclosure.state!=='enclosed'?` · ${Math.round(100*r.enclosure.open_fraction)} % open`:'')]){
      const td=document.createElement('td');td.textContent=v;tr.append(td);}
    const td=document.createElement('td'),b=document.createElement('button');b.type='button';b.className='env-link';b.textContent='Select';
    b.addEventListener('click',()=>request('select_room',{room:r.room}));td.append(b);tr.append(td);
    tr.dataset.state=r.enclosure.state;return tr;}));
  li('env-room-warnings',p.warnings||[]);
}
function showResult(p){
  const res=p.result;state.result=res;
  el('env-results-empty').hidden=true;
  svgInto('env-tiles',p.tiles_svg);svgInto('env-result-plan',p.svg);
  const t=el('env-result-table');t.hidden=false;
  const daylight=res.study!=='rooms_thermal';
  const head=daylight?['Room','sDA','ASE','DF']:['Room','Method','Heating','Cooling','h > 26 °C','Comfort'];
  t.tHead.replaceChildren((()=>{const tr=document.createElement('tr');for(const h of head){const th=document.createElement('th');th.textContent=h;tr.append(th);}return tr;})());
  const rows=(res.rooms||[]).map(r=>{
    if(daylight)return [r.room,r.sda_pct!=null?r.sda_pct+' %':'—',r.ase_pct!=null?r.ase_pct+' %':'—',r.average_df_pct!=null?r.average_df_pct+' %':'—'];
    if(r.method==='semi_outdoor')return [r.room,'Open · semi-outdoor','—','—','—',`SET* ${r.comfort.set_c.mean_occupied} °C · ${r.comfort.hours_set_above[Object.keys(r.comfort.hours_set_above)[0]]} h hot`];
    const th=r.thermal;
    return [r.room,r.method,th.heating_kwh_m2+' kWh/m²',th.cooling_kwh_m2+' kWh/m²',String(th.hours_above_26c_occupied),
      th.tm52?(th.tm52.pass?'TM52 pass':'TM52 fail'):(th.adaptive_ashrae55?th.adaptive_ashrae55.comfortable_80_pct+' % comfortable':'')];
  });
  t.tBodies[0].replaceChildren(...rows.map(cells=>{const tr=document.createElement('tr');for(const c of cells){const td=document.createElement('td');td.textContent=c;tr.append(td);}return tr;}));
  li('env-notes',[...(res.notes||[]),...(p.draw_error?['Viewport: '+p.draw_error]:[])]);
  const ec=res.envelope_check;el('env-envelope').hidden=!ec;
  if(ec){
    const lines=[];
    if(ec.index)lines.push(`${ec.index} ${ec.overall_w_m2} W/m² (limit ${ec.limit_w_m2}) — ${ec.passes?'meets':'exceeds'} the limit`,...ec.facades.map(f=>`${f.orientation}: ${f.value_w_m2} W/m² · WWR ${Math.round(100*f.wwr)} % · CF ${f.cf}`));
    if(ec.elements)lines.push(...ec.elements.map(e=>`${e.element}: U ${e.u_value} vs ${e.limit} — ${e.passes?'pass':'fail'}`));
    if(ec.opaque)lines.push(...Object.values(ec.opaque).slice(0,8).map(o=>`${o.name}: U ${o.u}`));
    if(ec.u_values_by_age)lines.push(...Object.entries(ec.u_values_by_age).map(([a,v])=>`${a}: wall ${v.wall} · roof ${v.roof} · window ${v.window}`));
    if(ec.note)lines.push(ec.note);
    if(ec.provenance)lines.push(`${ec.provenance.relation} · ${ec.provenance.licence}`);
    const ul=document.createElement('ul');ul.append(...lines.map(s=>{const i=document.createElement('li');i.textContent=s;return i;}));
    el('env-envelope-body').replaceChildren(ul);
  }
  showTab('results');
}
window.almondEnvironmentReceive=p=>{
  if(p.kind==='progress'){message(p.message,'busy');return;}
  if(p.kind==='epw'){state.epw=p.epw_path;text('env-epw',p.epw_path);el('env-epw').classList.remove('need');checklist();return;}
  busy=false;
  if(p.kind==='error'){message(p.message,'error');checklist();return;}
  if(p.kind==='notice'){message(p.message,'ok');checklist();if(p.refresh==='rooms')request('rooms',{});return;}
  if(p.kind==='site'){
    state.site=p.site;state.epw=state.epw||p.site.location;svgInto('env-site-diagram',p.svg);
    el('env-epw').classList.remove('need');if(el('env-epw').classList.contains('need')||!state.epw.includes('.epw'))text('env-epw',p.site.location);
    const dl=el('env-site-facts');dl.hidden=false;
    dl.replaceChildren(...[['Location',p.site.location],['Latitude',p.site.latitude.toFixed(2)+'°'],['Mean air',p.site.dry_bulb_mean_c+' °C'],
      ['Range',`${p.site.dry_bulb_min_c} – ${p.site.dry_bulb_max_c} °C`],['Global radiation',p.site.ghi_kwh_m2+' kWh/m²']].flatMap(([k,v])=>{
        const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;return [dt,dd];}));
    message('Weather loaded: '+p.site.location+'.','ok');checklist();return;
  }
  if(p.kind==='construction'){svgInto('env-section',p.svg);message(`${p.construction.name}: U ${p.construction.u_value} W/m²K.`,'ok');checklist();return;}
  if(p.kind==='rooms'){showRooms(p);message(`${p.rooms.length} room(s) checked.`,'ok');checklist();return;}
  if(p.kind==='result'){showResult(p);message(p.result.headline||'Study complete.','ok');checklist();return;}
  checklist();
};
if(native)el('env-native-note').hidden=true;
loadCatalogue();
