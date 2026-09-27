import {applyPreviewStyle, displayChoice} from './preview-style.mjs';

const select = document.getElementById('preview-display');
const status = document.getElementById('preview-display-status');
const grid = document.getElementById('grid');
const dialog = document.getElementById('object-dialog');
const params = new URLSearchParams(location.search);
const native = params.get('panel') === '1' && /^[a-f0-9]{32}$/.test(params.get('bridge') || '');
select.value = native ? 'auto' : 'material';
select.querySelector('[value="auto"]').disabled = !native;
let viewport = null;
let current = displayChoice(select.value, viewport);
let visible = new Set();
let assets = new Map();
let frame;
const mounted = new Map();
const failed = new Set();
const maxLiveCards = 8;

function configure(model, asset) {
  model.src = asset.model;
  model.alt = `Preview of ${asset.name}`;
  model.setAttribute('scale', '0.001 0.001 0.001');
  model.setAttribute('camera-orbit', '35deg 70deg auto');
  model.setAttribute('interaction-prompt', 'none');
  model.setAttribute('loading', 'eager');
  model.setAttribute('reveal', 'auto');
}

function release(stage) {
  mounted.get(stage)?.remove();
  mounted.delete(stage);
  stage.classList.remove('live-preview-ready');
}

function updateCards() {
  // Coloured, pre-rendered thumbnails cost no GPU work. Other modes load only
  // visible cards and release them on scrolling, filtering, or opening a model.
  const styled = !['material', 'rendered'].includes(current.style);
  const candidates = styled && !dialog.open && !document.hidden
    ? [...visible].filter(stage => stage.isConnected && !failed.has(stage.dataset.assetId)).slice(0, maxLiveCards) : [];
  for (const stage of mounted.keys()) if (!candidates.includes(stage)) release(stage);
  for (const stage of candidates) {
    let model = mounted.get(stage);
    if (!model) {
      const asset = assets.get(stage.dataset.assetId);
      if (!asset) continue;
      model = document.createElement('model-viewer');
      model.className = 'card-model-preview';
      model.setAttribute('aria-hidden', 'true');
      model.setAttribute('inert', '');
      model.setAttribute('tabindex', '-1');
      configure(model, asset);
      model.addEventListener('load', () => {
        if (mounted.get(stage) !== model) return;
        applyPreviewStyle(model, current.style);
        stage.classList.add('live-preview-ready');
      }, {once: true});
      model.addEventListener('error', () => {
        failed.add(asset.id); release(stage);
        stage.title = '3D preview unavailable; showing the styled thumbnail. Placement is still available.';
      }, {once: true});
      mounted.set(stage, model);
      stage.append(model);
    }
    applyPreviewStyle(model, current.style);
  }
}

const observer = new IntersectionObserver(entries => {
  for (const entry of entries) entry.isIntersecting ? visible.add(entry.target) : visible.delete(entry.target);
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(updateCards);
}, {threshold: 0.01});

function update() {
  current = displayChoice(select.value, viewport);
  document.documentElement.dataset.previewStyle = current.style;
  status.textContent = current.label;
  const detail = document.querySelector('#viewer model-viewer');
  if (detail) applyPreviewStyle(detail, current.style);
  const note = document.getElementById('object-preview-status');
  note.textContent = `${current.label} · approximate preview`;
  updateCards();
}

window.almondDisplayReceive = message => {
  if (!native || !message || typeof message.name !== 'string') return;
  viewport = {name: message.name.slice(0, 100), style: message.style, supported: message.supported === true};
  update();
};

// The app owns catalogue/filtering and viewer creation; no duplicate fetches.
window.almondPreviewCards = records => {
  observer.disconnect();
  for (const stage of mounted.keys()) release(stage);
  visible = new Set();
  assets = new Map(records.filter(a => a.kind === 'model' && a.available && a.format === 'glb').map(a => [a.id, a]));
  for (const stage of grid.querySelectorAll('[data-asset-id]')) if (assets.has(stage.dataset.assetId)) observer.observe(stage);
};
window.almondPreviewModel = model => {
  applyPreviewStyle(model, current.style);
  model.addEventListener('load', () => applyPreviewStyle(model, current.style), {once: true});
  update();
};
select.addEventListener('change', update);
new MutationObserver(updateCards).observe(dialog, {attributes: true, attributeFilter: ['open']});
dialog.addEventListener('close', updateCards);
document.addEventListener('visibilitychange', updateCards);
window.addEventListener('pagehide', () => { observer.disconnect(); for (const stage of mounted.keys()) release(stage); });
update();
