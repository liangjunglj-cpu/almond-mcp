const $ = (id) => document.getElementById(id);
// The Rhino panel uses the same catalogue and viewer in a compact workspace.
const panelMode = new URLSearchParams(location.search).get('panel') === '1';
if (panelMode) document.documentElement.classList.add('rhino-panel');
const bridge = new URLSearchParams(location.search).get('bridge') || '';
const nativePlacement = panelMode && /^[a-f0-9]{32}$/.test(bridge);
if (nativePlacement) document.documentElement.classList.add('rhino-placement');
const canPlace = a => nativePlacement && a.kind === 'model' && a.format === 'glb' && a.available;
function placementButton(a) {
  return canPlace(a) ? '<button class="place-model" data-place="' + esc(a.id) + '" aria-label="Place ' + esc(a.name) + ' in Rhino">Place ↗</button>' : '';
}
function placeModel(id, drag = false) {
  const a = data?.assets.find(a => a.id === id);
  if (!a || !canPlace(a)) return;
  if ($('object-dialog').open) $('object-dialog').close();
  const quality = $('placement-detail').value === 'original' ? 'original' : 'light';
  // Only the dock panel intercepts this navigation; no HTTP write API.
  location.href = '/almond-action/' + bridge + '/' + (drag ? 'drag' : 'place') + '/' + quality + '/' + encodeURIComponent(id);
}

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const human = (value) => String(value || '').replaceAll('_', ' ');
const external = (url) => { try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
const link = (url, title, cls = '') => url ? `<a class="download ${cls}" href="${esc(url)}?download=1" ${panelMode ? 'target="_blank" rel="noopener"' : 'download'}>${esc(title)} ↙</a>` : '';
let data, selected, currentView = '3d', filter = 'all';
let saved;
try { saved = new Set(JSON.parse(localStorage.getItem('almond.saved') || '[]')); } catch { saved = new Set(); }
const featured = ['gen-stool-bent-birch-3leg-1', 'gen-office-chair-1', 'gen-sofa-3-seat-1', 'gen-tree-conifer-1', 'gen-park-bench-1', 'gen-dining-table-rect-1', 'gen-person-standing-1', 'gen-washbasin-pedestal-1'];
const order = (a) => featured.includes(a.id) ? featured.indexOf(a.id) : 100;

function persistSaved() {
  try { localStorage.setItem('almond.saved', JSON.stringify([...saved])); } catch { /* Saving still works for this session. */ }
  $('saved-total').textContent = [...saved].filter(id => data.assets.some(a => a.id === id)).length;
}
function toggleSaved(id) {
  saved.has(id) ? saved.delete(id) : saved.add(id);
  persistSaved(); render();
  if (selected) updateSaveButton();
}
function updateSaveButton() {
  $('save-object').textContent = saved.has(selected.id) ? 'Saved to your collection −' : 'Save to your collection +';
  $('save-object').setAttribute('aria-pressed', saved.has(selected.id));
}
function render() {
  if (!data) return;
  const terms = $('search').value.toLowerCase().trim().split(/\s+/).filter(Boolean);
  let assets = data.assets.filter(a => {
    const text = [a.name, a.id, a.category, a.variant, a.metadata.render_material_id, ...a.tags, ...a.roles].join(' ').toLowerCase();
    return terms.every(t => text.includes(t)) && ($('category').value === 'all' || a.category === $('category').value)
      && (filter === 'all' || filter === a.kind || filter === 'ready' && a.drawing || filter === 'saved' && saved.has(a.id));
  });
  assets.sort((a,b) => $('sort').value === 'az' ? a.name.localeCompare(b.name) : $('sort').value === 'za' ? b.name.localeCompare(a.name) : order(a) - order(b) || a.name.localeCompare(b.name));
  $('result-count').textContent = `${String(assets.length).padStart(2,'0')} OF ${data.counts.assets} OBJECTS${filter === 'saved' ? ' / SAVED IN THIS BROWSER' : ''}`;
  $('empty').hidden = assets.length > 0;
  $('grid').innerHTML = assets.map(a => `<article class="card">
    <button class="card-save" data-save="${esc(a.id)}" aria-label="${saved.has(a.id) ? 'Unsave' : 'Save'} ${esc(a.name)}" aria-pressed="${saved.has(a.id)}">${saved.has(a.id) ? '−' : '+'}</button>
    <button class="card-open" data-open="${esc(a.id)}" aria-label="Explore ${esc(a.name)}">
      <div class="card-stage" ${canPlace(a) ? `data-drag="${esc(a.id)}" title="Drag into a Rhino viewport; Esc cancels"` : ''}><span class="card-index">${String(data.assets.indexOf(a)+1).padStart(3,'0')}</span>${a.preview ? `<img src="${esc(a.preview)}" alt="${esc(a.name)}" loading="lazy" draggable="false">` : `<div class="placeholder">${esc(a.format.toUpperCase())}<small>${a.available ? 'LOCAL FILE' : 'FILE NOT INSTALLED'}</small></div>`}<span class="card-format">${esc(a.format.toUpperCase())}</span>${a.drawing ? '<span class="card-status">DRAWING-READY</span>' : ''}</div>
      <div class="card-name"><span>${esc(a.name)}</span><span aria-hidden="true">↗</span></div><div class="card-sub"><span>${esc(human(a.category))}</span><span>${a.kind === 'model' ? 'MESHY / 3D' : 'DRAWING ELEMENT'}</span></div>
    </button>${placementButton(a)}</article>`).join('');
  $('grid').querySelectorAll('img').forEach(img => img.addEventListener('error', () => {
    img.replaceWith(Object.assign(document.createElement('span'), {className:'placeholder', textContent:'No preview'}));
  }, {once:true}));
}

function evidence(a) {
  const p = a.provenance;
  const g = p?.recorded_generation || {};
  const origin = external(a.source_url);
  const dl = (label, value) => value ? `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>` : '';
  return `<details open><summary>Source & attribution</summary><p>${esc(a.publisher)}<br>${esc(a.license)}</p>${origin ? `<p><a href="${esc(origin)}" target="_blank" rel="noopener noreferrer">${a.kind === 'model' ? 'Generation provider' : 'Original source'} ↗</a></p>` : '<p>No external source link recorded.</p>'}${p ? `<dl>${dl('Generated', g.generated_at)}${dl('Mesh model',g.mesh_model)}${dl('Mesh task ID', g.mesh_task_id)}${dl('Image provider',p.image_generation?.provider)}${dl('Image task / job ID',p.image_generation?.id)}</dl><p>${esc(p.rights_evidence)}</p>` : '<p>Representation-only element. Check the original source terms for project use. Downloaded community files are local to this installation and are excluded from the distributable plugin.</p>'}</details>
    ${p ? `<details><summary>Generation prompt & evidence gaps</summary><p>${esc(g.prompt || 'Prompt not recorded.')}</p><ul>${p.evidence_gaps.map(gap => `<li>${esc(gap)}</li>`).join('')}</ul><p>Reference directories are research leads; they are not evidence of inputs used for this model.</p></details>` : ''}
    ${a.drawing ? `<details><summary>Drawing method & limitations</summary><p>Plan, front and right silhouettes at 1:50 and 1:100. SVGs and A3 sheets carry paper scale; DXF geometry uses real-world millimetres. On-screen previews are fitted to the viewer.</p><ul>${a.drawing.source.limitations.map(s => `<li>${esc(s)}</li>`).join('')}</ul><p>Geometry fingerprint: ${esc(a.drawing.source.geometry_sha256)}</p>${link(a.drawing.record,'Drawing record')}</details>` : '<details><summary>Drawing availability</summary><p>No derived drawing package is attached to this object. For a supported GLB, the Almond MCP drawing tool can generate a new projection package.</p></details>'}
    <details><summary>Object record</summary><dl>${dl('Object ID',a.id)}${dl('MCP resource',a.uri)}${dl('Drawing roles',a.roles.map(human).join(', '))}${dl('Model SHA-256',a.metadata.sha256)}</dl><p>The record connects this object’s files, dimensions and source history.</p>${link(a.record_url,'Complete record JSON')}${link(a.contract,'Spatial contract')}</details>`;
}
function openObject(id) {
  const a = data.assets.find(a => a.id === id);
  if (!a) return;
  selected = a;
  currentView = a.format === 'glb' && a.available ? '3d' : 'preview';
  $('object-number').textContent = `OBJECT / ${String(data.assets.indexOf(a)+1).padStart(3,'0')}`;
  $('object-kind').textContent = `${a.kind === 'model' ? 'MESHY MODEL' : 'DRAWING ELEMENT'} / ${human(a.category).toUpperCase()}`;
  $('object-title').textContent = a.name;
  $('object-variant').textContent = a.variant;
  $('object-tags').innerHTML = a.tags.map(t => `<span>${esc(t)}</span>`).join('');
  $('dimensions').innerHTML = ['width','depth','height'].map(k => `<div><b>${a.dimensions_mm[k] == null ? '—' : Number(a.dimensions_mm[k]).toLocaleString('en', {maximumFractionDigits:1})}</b><span>${k.toUpperCase()} / MM</span></div>`).join('');
  $('dimension-basis').textContent = human(a.dimension_basis) + '. ' + (a.kind === 'model' ? 'Mesh dimensions; not a product specification.' : 'Verify scale before placement.');
  $('object-evidence').innerHTML = evidence(a);
  $('scale').value = '50';
  $('view-tabs').innerHTML = [[currentView, currentView === '3d' ? '3D model' : a.format === 'svg' ? '2D element' : 'File'], ...(a.drawing ? [['plan','Plan'],['front','Front'],['right','Right'],['sheet','A3 sheet']] : [])].map(([id,title]) => `<button data-view="${id}" aria-pressed="false">${title}</button>`).join('');
  updateSaveButton(); renderViewer();
  if (!$('object-dialog').open) $('object-dialog').showModal();
  $('object-dialog').scrollTop = 0;
}
function renderViewer() {
  const a = selected, scale = Number($('scale').value), viewer = $('viewer');
  const isDrawing = !['3d','preview'].includes(currentView);
  const rep = a.drawing?.views.find(v => v.view === currentView && v.scale === scale);
  const sheet = a.drawing?.sheets.find(s => s.scale === scale);
  viewer.replaceChildren();
  viewer.classList.toggle('drawing-view', isDrawing || a.format === 'svg');
  $('scale-wrap').hidden = !isDrawing;
  $('view-tabs').querySelectorAll('button').forEach(b => { b.classList.toggle('active', b.dataset.view === currentView); b.setAttribute('aria-pressed', b.dataset.view === currentView); });
  if (currentView === '3d') {
    const model = document.createElement('model-viewer');
    model.setAttribute('src',a.model); model.setAttribute('alt',`Interactive 3D model of ${a.name}`);
    model.setAttribute('camera-controls',''); model.setAttribute('touch-action','pan-y');
    model.setAttribute('shadow-intensity','0.5'); model.setAttribute('exposure','1.1');
    model.setAttribute('scale','0.001 0.001 0.001'); model.setAttribute('interaction-prompt','none');
    model.setAttribute('camera-orbit','35deg 70deg auto');
    if(a.preview) model.setAttribute('poster',a.preview);
    $('viewer-caption').textContent = 'Loading model…';
    model.addEventListener('load',() => { if(currentView === '3d') $('viewer-caption').textContent='DRAG TO ORBIT · SCROLL TO ZOOM'; },{once:true});
    model.addEventListener('error',() => { if(currentView === '3d') { const notice=document.createElement('p');notice.className='viewer-notice';notice.textContent='3D preview unavailable. You can still download the GLB.';viewer.append(notice);$('viewer-caption').textContent='Preview unavailable'; } },{once:true});
    viewer.append(model);
  } else {
    const url = isDrawing ? (currentView === 'sheet' ? sheet?.svg : rep?.svg) : a.preview;
    if(url) { const img=document.createElement('img');img.src=url;img.alt=`${a.name} — ${currentView === 'preview' ? 'drawing element' : currentView}, ${isDrawing ? '1:'+scale : ''}`;viewer.append(img); }
    else { viewer.innerHTML=`<div class="placeholder">${esc(a.format.toUpperCase())}<small>${a.available ? 'OPEN THE LOCAL FILE IN YOUR CAD APPLICATION' : 'FILE NOT INSTALLED'}</small></div>`; }
    $('viewer-caption').textContent = isDrawing ? `${currentView.toUpperCase()} / 1:${scale} · FITTED PREVIEW${rep?.method === 'raster_projection' ? ' · APPROXIMATED' : ''}` : a.preview ? 'DRAWING ELEMENT · FITTED PREVIEW' : 'No browser preview for this file.';
  }
  const drawingLinks = isDrawing ? (currentView === 'sheet' ? link(sheet?.svg,`A3 sheet 1:${scale}`,'primary') : link(rep?.svg,`${human(currentView)} SVG`,'primary')+link(rep?.dxf,`${human(currentView)} DXF`)) : '';
  $('downloads').innerHTML = placementButton(a) + drawingLinks + link(a.model,`Download ${a.format.toUpperCase()}`,isDrawing ? '' : 'primary') + link(a.record_url,'Record JSON') + (!a.available ? '<p class="small-note">Model file is not installed. See the original source below.</p>' : '');
}

function renderSources() {
  $('source-list').innerHTML = data.sources.map((s,i) => `<article class="source-row"><span>${String(i+1).padStart(2,'0')}</span><div><h2>${esc(s.title)}</h2><p class="source-meta">${esc(s.formats.join(' / ').toUpperCase())}</p></div><div><p>${esc(s.notes)}</p><p class="source-meta">ACCESS / ${esc(s.access)}<br>REUSE / ${esc(s.redistribution)}</p></div><div class="source-links">${external(s.url) ? `<a href="${esc(external(s.url))}" target="_blank" rel="noopener noreferrer">Visit source ↗</a>` : ''}${external(s.terms_url) ? `<a href="${esc(external(s.terms_url))}" target="_blank" rel="noopener noreferrer">Source terms ↗</a>` : ''}</div></article>`).join('');
}
function route() {
  if(!data) return;
  const hash = location.hash.slice(1), page = ['sources','about'].includes(hash) ? hash : 'library';
  for(const name of ['library','sources','about']) $(name+'-page').hidden = name !== page;
  document.querySelectorAll('[data-page]').forEach(a => { if(a.dataset.page === page) a.setAttribute('aria-current','page');else a.removeAttribute('aria-current'); });
  if(hash.startsWith('asset=')) { let id;try{id=decodeURIComponent(hash.slice(6));}catch{return;}openObject(id); }
  else if($('object-dialog').open) $('object-dialog').close();
  if(['library','sources','about'].includes(hash)) window.scrollTo(0,0);
}
async function load() {
  $('load-error').hidden=true;
  try {
    const response = await fetch('/api/catalogue');
    if(!response.ok) throw new Error(`Archive responded with ${response.status}.`);
    data = await response.json();
    if(data.distribution === 'rhino') document.querySelector('.technical').textContent = 'Run AlmondLibrary in Rhino to open the dockable panel, or AlmondLibraryBrowser for the browser view. Browsing the included models needs no Python or AI client. Keep Rhino open while using the archive. Saved selections are local to this browser address; the address changes when Rhino restarts.';
    $('asset-count').textContent=String(data.counts.assets).padStart(3,'0');
    $('all-total').textContent=data.counts.assets;
    $('model-count').textContent=String(data.counts.models).padStart(2,'0');
    $('element-count').textContent=String(data.counts.elements).padStart(2,'0');
    $('view-count').textContent=String(data.counts.views).padStart(2,'0');
    $('edition-version').textContent='V. '+data.version.toUpperCase();
    $('footer-version').textContent='ALMOND / '+data.version.toUpperCase();
    $('category').innerHTML='<option value="all">All categories</option>'+[...new Set(data.assets.map(a=>a.category))].sort().map(c=>`<option value="${esc(c)}">${esc(human(c))}</option>`).join('');
    $('placement-tools').hidden = !nativePlacement;
    if (panelMode) {
      $('search').placeholder = 'Search models & drawings…';
      document.querySelector('[data-filter="model"]').textContent = '3D';
      document.querySelector('[data-filter="ready"]').textContent = 'With views';
      document.querySelector('[data-filter="element"]').textContent = '2D';
    }
    persistSaved();render();renderSources();route();
  } catch(error) { $('load-error').hidden=false;$('error-message').textContent=error.message;$('result-count').textContent='Archive unavailable'; }
}
$('search').addEventListener('input',render);
$('category').addEventListener('change',render);
$('sort').addEventListener('change',render);
document.querySelector('.filters').addEventListener('click',e=> {const b=e.target.closest('[data-filter]');if(!b)return;filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',x===b);});render();});
let dragCandidate = null, suppressClickUntil = 0;
$('grid').addEventListener('pointerdown', e => {
  const target = e.target.closest('[data-drag]');
  if (e.button === 0 && target) dragCandidate = {id:target.dataset.drag,x:e.clientX,y:e.clientY};
});
document.addEventListener('pointermove', e => {
  if (!dragCandidate) return;
  if (!(e.buttons & 1)) { dragCandidate = null; return; }
  if (Math.hypot(e.clientX-dragCandidate.x,e.clientY-dragCandidate.y) < 6) return;
  const id = dragCandidate.id; dragCandidate = null; suppressClickUntil = Date.now()+800;
  e.preventDefault(); placeModel(id, true);
});
document.addEventListener('pointerup', () => { dragCandidate = null; });
document.addEventListener('pointercancel', () => { dragCandidate = null; });
$('grid').addEventListener('dragstart', e => e.preventDefault());
$('grid').addEventListener('click',e=>{
  if (Date.now() < suppressClickUntil) { e.preventDefault(); return; }
  const place=e.target.closest('[data-place]');if(place){placeModel(place.dataset.place);return;}
  const save=e.target.closest('[data-save]');if(save){toggleSaved(save.dataset.save);return;}
  const open=e.target.closest('[data-open]');if(open)location.hash='asset='+encodeURIComponent(open.dataset.open);
});
$('downloads').addEventListener('click', e => { const b=e.target.closest('[data-place]');if(b)placeModel(b.dataset.place); });
$('view-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(b){currentView=b.dataset.view;renderViewer();}});
$('scale').addEventListener('change',renderViewer);
$('save-object').addEventListener('click',()=>toggleSaved(selected.id));
$('close-dialog').addEventListener('click',()=>$('object-dialog').close());
$('object-dialog').addEventListener('close',()=>{$('viewer').replaceChildren();if(location.hash.startsWith('#asset='))history.replaceState(null,'','#library');});
$('reset-filters').addEventListener('click',()=>{$('search').value='';$('category').value='all';document.querySelector('[data-filter="all"]').click();$('search').focus();});
$('retry').addEventListener('click',load);
document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!$('object-dialog').open){e.preventDefault();location.hash='collection';$('search').focus();}});
window.addEventListener('hashchange',route);
load();
