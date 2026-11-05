// Environment workspace: site, rooms, constructions, study, results, compare. Data and diagrams come from the
// environment engine (almond-mcp environment) through the Rhino panel; the catalogue is a static file.
const el=id=>document.getElementById(id);
const token=new URLSearchParams(location.search).get('bridge')||'';
const native=/^[a-f0-9]{32}$/.test(token) && new URLSearchParams(location.search).get('panel')==='1';
const TABS=['site','rooms','constructions','study','results','compare'];
const COUNTRIES=['at','be','bg','cy','cz','de','dk','ee','es','fi','fr','gr','hr','hu','ie','it','lt','lu','lv','mt','nl','pl','pt','ro','se','si','sk','uk'];
const DE_BANDS=['<=1918','1919-1948','1949-1957','1958-1968','1969-1978','1979-1983','1984-1994','1995-2001','>=2002'];
const MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const STUDY_NAMES={rooms_thermal:'Thermal',rooms_daylight:'Daylight',rooms_view_out:'View out'};
let cat=null,state={epw:'',site:null,rooms:null,result:null,climate:null,cases:[]},busy=false,active='site';

function svgInto(id,svg){const n=el(id);if(!n)return;n.innerHTML=svg||'';}       // engine SVG only: names are XML-escaped there
function text(id,s){const n=el(id);if(n)n.textContent=s;}
function message(s,kind='info'){text('env-message',s);el('env-status').dataset.state=kind;}
function li(list,items){const n=el(list);n.replaceChildren(...items.map(s=>{const i=document.createElement('li');i.textContent=s;return i;}));}
function cells(tr,values,tag='td'){for(const v of values){const c=document.createElement(tag);c.textContent=v;tr.append(c);}return tr;}
function facts(id,pairs){const dl=el(id);dl.hidden=!pairs.length;
  dl.replaceChildren(...pairs.flatMap(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;return [dt,dd];}));}
function store(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{}}
function recall(key,fallback){try{const v=JSON.parse(localStorage.getItem(key));return v??fallback;}catch{return fallback;}}

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
function monthSelect(id,blank,value){const s=el(id);s.replaceChildren(...(blank?[option('',blank)]:[]),...MONTHS.map((m,i)=>option(String(i+1),m)));s.value=value;}
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
function toggles(){document.querySelectorAll('[data-when]').forEach(n=>n.hidden=!el(n.dataset.when).checked);}

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

function epwOptional(){
  const study=el('env-study').value;
  return study==='view_out'||study==='daylight'&&el('env-daylight').value==='daylight_factor';
}
function checklist(){
  const items=[
    {label:'Weather file',ok:!!state.epw||epwOptional(),tab:'site'},
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
  message({run:'Exporting the model…',rooms:'Checking rooms…',define_room:'Select the room in Rhino…',assign:'Select elements in Rhino…',
    climate:'Reading the weather file…',compare:'Comparing cases…'}[action]||'Working in Rhino…','busy');
  location.href='/almond-action/'+token+'/environment/'+action+'?data='+encodeURIComponent(JSON.stringify(input));
}
function num(id){const v=el(id).value.trim();return v===''?null:Number(v);}
function season(prefix){                                   // [from, to] selects -> month list (wrapping the year end), null = all year
  const a=Number(el(prefix+'-0').value),b=Number(el(prefix+'-1').value);
  if(!a||!b)return null;
  const out=[];for(let m=a;;m=m%12+1){out.push(m);if(m===b||out.length===12)break;}
  return out;
}
function settings(){
  const blinds=el('env-blinds').checked;
  const s={construction:el('env-preset').value,schedule:'residential',natural_ventilation_ach:Number(el('env-nv').value)||0,
    shading_g_factor:blinds?0.15:1,shading_min_outdoor_c:blinds?12:null,shading_on_above_w_m2:blinds?(num('env-shade-on')??300):300,
    cooling:el('env-cooling').checked,heat_recovery:Math.min(Math.max((Number(el('env-hr').value)||0)/100,0),0.95),
    daylight_study:el('env-daylight').value,quality:el('env-quality').value,spacing_m:Number(el('env-spacing').value)||0.5,
    people_per_m2:num('env-people'),metabolic_rate:num('env-met')??1.2,ventilation_l_s_person:num('env-vent-person'),ventilation_l_s_m2:num('env-vent-area'),
    heating_setpoint:num('env-heat'),cooling_setpoint:num('env-cool'),heating_setback:num('env-heat-back'),cooling_setback:num('env-cool-back'),
    heating_months:season('env-m-heat'),cooling_months:season('env-m-cool'),ventilation_months:season('env-m-vent'),
    natural_ventilation_months:season('env-m-nv'),comfort_months:season('env-m-comfort'),export_csv:el('env-csv').checked,
    balance_room:el('env-chart-room').value||''};
  const study=el('env-study').value;
  if(study==='view_out')Object.assign(s,{view_height_m:Number(el('env-view-h').value)||1.2,spacing_m:Number(el('env-view-spacing').value)||0.6});
  if(study==='sunlight')Object.assign(s,{month:Number(el('env-sl-month').value),day:Number(el('env-sl-day').value)||21,
    min_altitude_deg:num('env-sl-alt')??10,date_range:el('env-sl-range').checked?[[2,1],[3,21]]:null});
  for(const k of Object.keys(s))if(s[k]===null)delete s[k];
  return s;
}
function shadowSettings(){
  const times=el('env-sun-times').value.split(',').map(t=>t.trim()).filter(Boolean);
  return {month:Number(el('env-sun-month').value),day:Number(el('env-sun-day').value)||20,times};
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
  }else if(a==='shadows'){
    if(!state.epw){message('Choose a weather file first.','error');return;}
    request('run',{study:'shadows',settings:shadowSettings()});
  }else if(a==='setpoints'){
    request(a,{met:el('env-pmv-met').value,clo_heating:el('env-pmv-clo-w').value,clo_cooling:el('env-pmv-clo-s').value,category:el('env-pmv-cat').value});
  }else if(a==='open_folder'){
    const id=b.dataset.run==='climate'?state.climate?.run_id:state.result?.run_id;
    if(id)request(a,{run_id:id});
  }else if(a==='keep')keepCase();
  else if(a==='compare'){
    if(!state.cases.length){message('Keep a result as a case first.','error');return;}
    request(a,{cases:state.cases.map(c=>({name:c.name,run_id:c.run_id})),room:el('env-compare-room').value});
  }else if(a==='clear_cases'){state.cases=[];store('almond-env-cases',[]);showCases();}
  else request(a,{});
}));
['env-kind','env-region'].forEach(id=>el(id).addEventListener('change',fillConstructions));
el('env-construction').addEventListener('change',showSection);
el('env-pack').addEventListener('change',fillPackOptions);
el('env-study').addEventListener('change',studyControls);
el('env-daylight').addEventListener('change',checklist);
el('env-blinds').addEventListener('change',toggles);
el('env-chart-room').addEventListener('change',()=>{
  if(state.result?.study==='rooms_thermal')request('charts',{run_id:state.result.run_id,room:el('env-chart-room').value});
});

function showRooms(p){
  state.rooms=p.rooms;
  svgInto('env-room-plan',p.svg);
  const tb=el('env-room-table');tb.hidden=!p.rooms.length;
  tb.tBodies[0].replaceChildren(...p.rooms.map(r=>{
    const tr=document.createElement('tr');
    const label={enclosed:'Enclosed',semi_open:'Semi-open',open:'Open'}[r.enclosure.state];
    cells(tr,[r.room,r.use,r.floor_area_m2.toFixed(1)+' m²',label+(r.enclosure.state!=='enclosed'?` · ${Math.round(100*r.enclosure.open_fraction)} % open`:'')]);
    const td=document.createElement('td'),b=document.createElement('button');b.type='button';b.className='env-link';b.textContent='Select';
    b.addEventListener('click',()=>request('select_room',{room:r.room}));td.append(b);tr.append(td);
    tr.dataset.state=r.enclosure.state;return tr;}));
  li('env-room-warnings',p.warnings||[]);
  const rooms=p.rooms.map(r=>r.room);
  el('env-compare-room').replaceChildren(option('','All rooms'),...rooms.map(r=>option(r,r)));
}
function showCharts(ch){
  const box=el('env-charts');box.hidden=!ch||!ch.warmest_week;
  if(box.hidden)return;
  const sel=el('env-chart-room');
  sel.replaceChildren(...(ch.rooms||[]).map(r=>option(r,r)));sel.value=ch.room;
  svgInto('env-chart-warm',ch.warmest_week);svgInto('env-chart-cold',ch.coldest_week);
  svgInto('env-chart-hot',ch.balance_hottest_day);svgInto('env-chart-cday',ch.balance_coldest_day);
}
function resultRows(res){
  if(res.study==='rooms_view_out')return {head:['Room','≥ minimum','≥ medium','High','Sight angle'],
    rows:res.rooms.map(r=>[r.room,r.minimum+' %',r.medium+' %',r.high+' %',r.sight_angle_mean_deg+'°'])};
  if(res.study==='en17037_sunlight')return {head:['Window','Sun','Level'].concat(res.range?['Best day']:[]),
    rows:res.windows.map(w=>[w.window,w.sun_hours+' h',w.level].concat(res.range?[`${res.range.best_day_hours[w.window]} h`]:[]))};
  if(res.study==='rooms_daylight')return {head:['Room','sDA','ASE','DF'],
    rows:res.rooms.map(r=>[r.room,r.sda_pct!=null?r.sda_pct+' %':'—',r.ase_pct!=null?r.ase_pct+' %':'—',r.average_df_pct!=null?r.average_df_pct+' %':'—'])};
  return {head:['Room','Method','Heating','Cooling','h > 26 °C','Adaptive II','Comfort'],rows:(res.rooms||[]).map(r=>{
    if(r.method==='semi_outdoor')return [r.room,'Open · semi-outdoor','—','—','—','—',`SET* ${r.comfort.set_c.mean_occupied} °C · ${r.comfort.hours_set_above[Object.keys(r.comfort.hours_set_above)[0]]} h hot`];
    const th=r.thermal,ad=th.adaptive_en16798_hours?.II;
    return [r.room,r.method,th.heating_kwh_m2+' kWh/m²',th.cooling_kwh_m2+' kWh/m²',String(th.hours_above_26c_occupied),
      ad?`${ad.too_warm_h} h warm · ${ad.too_cool_h} h cool`:'—',
      th.tm52?(th.tm52.pass?'TM52 pass':'TM52 fail'):(th.adaptive_ashrae55?th.adaptive_ashrae55.comfortable_80_pct+' % comfortable':'')];
  })};
}
function showResult(p){
  const res=p.result;
  if(res.study==='shadow_study'){showShadows(p);return;}
  state.result=res;
  el('env-results-empty').hidden=true;
  svgInto('env-tiles',p.tiles_svg);svgInto('env-result-plan',p.svg);
  const t=el('env-result-table');t.hidden=false;
  const {head,rows}=resultRows(res);
  t.tHead.replaceChildren(cells(document.createElement('tr'),head,'th'));
  t.tBodies[0].replaceChildren(...rows.map(r=>cells(document.createElement('tr'),r)));
  const b=res.building;el('env-building').hidden=!(b&&b.heating_kwh_m2!=null);
  if(b&&b.heating_kwh_m2!=null)text('env-building',`Whole building, ${b.floor_area_m2} m²: heating ${b.heating_kwh_m2} · cooling ${b.cooling_kwh_m2}`+
    (b.lighting_kwh_m2!=null?` · lighting ${b.lighting_kwh_m2}`:'')+' kWh/m²·a');
  showCharts(p.charts&&p.charts.warmest_week?p.charts:null);
  svgInto('env-chart-sun',p.charts?.sunlight||'');
  el('env-keep').hidden=!STUDY_NAMES[res.study];
  el('env-case-name').value=`ID${state.cases.filter(c=>c.study===res.study).length}`;
  el('env-open-run').hidden=!res.run_id;
  li('env-notes',[...(res.notes||[]),...(p.csv_dir?['Hourly CSV files: '+p.csv_dir]:[]),...(p.draw_error?['Viewport: '+p.draw_error]:[])]);
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
function showShadows(p){
  const res=p.result,img=el('env-shadow-img');
  img.src=p.image;img.hidden=false;el('env-sun').open=true;
  const t=el('env-shadow-table');t.hidden=false;
  t.tBodies[0].replaceChildren(...res.shots.map(s=>cells(document.createElement('tr'),[s.time,s.solar_time,`${Math.round(s.altitude)}° alt · ${Math.round(s.azimuth)}° az`,s.shadow_share_of_ground_pct+' %'])));
  showTab('site');
}
function showClimate(p){
  state.climate={run_id:(p.run_dir||'').split(/[\\/]/).pop()};
  el('env-climate').hidden=false;
  const w=p.weeks,ww=w.warmest_week,cw=w.coldest_week;
  facts('env-weeks',[['Warmest week',`${ww.start} – ${ww.end} · mean ${ww.mean_dry_bulb_c} °C`],
    ['Hottest day',`${ww.hottest_day.date} · ${ww.hottest_day.max_dry_bulb_c} °C`],
    ['Coldest week',`${cw.start} – ${cw.end} · mean ${cw.mean_dry_bulb_c} °C`],
    ['Coldest day',`${cw.coldest_day.date} · ${cw.coldest_day.min_dry_bulb_c} °C`]]);
  li('env-periods',(w.file_periods||[]).map(x=>`File period “${x.name}”: ${x.start} – ${x.end}`+(x.days?` (${x.days} days)`:'')+(x.note?` — ${x.note}`:'')));
  svgInto('env-diurnal',p.svg);
}
function showSetpoints(p){
  const s=p.setpoints;
  el('env-heat').value=s.heating_setpoint_c;el('env-cool').value=s.cooling_setpoint_c;
  text('env-pmv-out',`Category ${s.category} (PMV ${s.pmv_range[0]} to +${s.pmv_range[1]}): heating ${s.heating_setpoint_c} °C, cooling ${s.cooling_setpoint_c} °C operative — filled in above for all rooms. ${s.method}`);
}

function keepCase(){
  const r=state.result;if(!r||!STUDY_NAMES[r.study])return;
  const name=el('env-case-name').value.trim()||`ID${state.cases.length}`;
  if(state.cases.some(c=>c.name===name)){message(`A case is already called ${name}.`,'error');return;}
  if(state.cases.length>=12){message('At most 12 cases: forget one first.','error');return;}
  state.cases.push({name,run_id:r.run_id,study:r.study,label:r.label||'',kept:new Date().toLocaleString()});
  store('almond-env-cases',state.cases);showCases();message(`Kept as case ${name}.`,'ok');
}
function showCases(){
  el('env-cases-empty').hidden=!!state.cases.length;
  el('env-case-table').hidden=!state.cases.length;
  el('env-case-table').tBodies[0].replaceChildren(...state.cases.map((c,i)=>{
    const tr=cells(document.createElement('tr'),[c.name,STUDY_NAMES[c.study]||c.study,c.kept]);
    const td=document.createElement('td'),b=document.createElement('button');b.type='button';b.className='env-link';b.textContent='Forget';
    b.addEventListener('click',()=>{state.cases.splice(i,1);store('almond-env-cases',state.cases);showCases();});td.append(b);tr.append(td);return tr;}));
}
function showCompare(p){
  const t=el('env-compare-table');t.hidden=false;
  const figs=p.figures.filter(([k])=>p.rows.some(r=>r[k]!=null));
  t.tHead.replaceChildren(cells(document.createElement('tr'),['Case',...figs.map(([,l,u])=>`${l} (${u})`)],'th'));
  t.tBodies[0].replaceChildren(...p.rows.map(r=>cells(document.createElement('tr'),[r.case,...figs.map(([k])=>r[k]??'—')])));
  const bars=el('env-compare-bars');bars.replaceChildren(...Object.values(p.bars).map(svg=>{const d=document.createElement('div');d.className='env-diagram';d.innerHTML=svg;return d;}));
  svgInto('env-compare-warm',p.warmest_week||'');svgInto('env-compare-cold',p.coldest_week||'');
  showTab('compare');
}

window.almondEnvironmentReceive=p=>{
  if(p.kind==='progress'){message(p.message,'busy');return;}
  if(p.kind==='epw'){state.epw=p.epw_path;text('env-epw',p.epw_path);el('env-epw').classList.remove('need');checklist();return;}
  busy=false;
  if(p.kind==='error'){message(p.message,'error');checklist();return;}
  if(p.kind==='notice'){message(p.message,'ok');checklist();if(p.refresh==='rooms')request('rooms',{});return;}
  if(p.kind==='site'){
    state.site=p.site;state.epw=state.epw||p.site.location;svgInto('env-site-diagram',p.svg);
    el('env-epw').classList.remove('need');if(!state.epw.includes('.epw'))text('env-epw',p.site.location);
    facts('env-site-facts',[['Location',p.site.location],['Latitude',p.site.latitude.toFixed(2)+'°'],['Mean air',p.site.dry_bulb_mean_c+' °C'],
      ['Range',`${p.site.dry_bulb_min_c} – ${p.site.dry_bulb_max_c} °C`],['Global radiation',p.site.ghi_kwh_m2+' kWh/m²']]);
    message('Weather loaded: '+p.site.location+'. Reading its climate…','ok');checklist();request('climate',{});return;
  }
  if(p.kind==='climate'){showClimate(p);message('Climate read: extreme weeks and daily averages are on the Site tab.','ok');checklist();return;}
  if(p.kind==='setpoints'){showSetpoints(p);message('Set-points found from PMV.','ok');checklist();return;}
  if(p.kind==='construction'){svgInto('env-section',p.svg);message(`${p.construction.name}: U ${p.construction.u_value} W/m²K.`,'ok');checklist();return;}
  if(p.kind==='rooms'){showRooms(p);message(`${p.rooms.length} room(s) checked.`,'ok');checklist();return;}
  if(p.kind==='charts'){showCharts(p.charts);message(`Charts for ${p.charts.room}.`,'ok');checklist();return;}
  if(p.kind==='compare'){showCompare(p);message(`${p.rows.length} case(s) compared.`,'ok');checklist();return;}
  if(p.kind==='result'){showResult(p);message(p.result.headline||'Study complete.','ok');checklist();return;}
  checklist();
};
for(const id of ['env-sun-month','env-sl-month'])monthSelect(id,'',id==='env-sun-month'?'3':'3');
for(const [k,a,b] of [['heat','',''],['cool','',''],['vent','',''],['nv','',''],['comfort','','']]){monthSelect(`env-m-${k}-0`,'All year',a);monthSelect(`env-m-${k}-1`,'—',b);}
state.cases=recall('almond-env-cases',[]).filter(c=>c&&c.run_id&&c.name);showCases();toggles();
if(native)el('env-native-note').hidden=true;
loadCatalogue();
