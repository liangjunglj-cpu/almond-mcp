import {finite, fmt, utilState, memberRows, filterRows, sortRows, counts, ends} from './results-view.mjs';
import {engineLabel, stabilityState} from './analysis-view.mjs';

const el = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
const token = params.get('bridge') || '';
const native = /^[a-f0-9]{32}$/.test(token) && params.get('panel') === '1';
let report = null, rows = [], sortKey = 'utilization', sortDir = -1, filter = 'all';

const td = (text, cls = '') => { const c = document.createElement('td'); if (cls) c.className = cls; c.textContent = text; return c; };
const li = text => { const n = document.createElement('li'); n.textContent = text; return n; };
function facts(target, pairs) {
  target.replaceChildren(...pairs.filter(p => p[1] !== null && p[1] !== undefined && p[1] !== '').flatMap(([k, v]) => {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = k; dd.textContent = v; return [dt, dd];
  }));
}
function head(table, cols, sortable = false) {
  const tr = document.createElement('tr');
  for (const c of cols) {
    const th = document.createElement('th');
    th.scope = 'col';
    if (c.left) th.className = 'l';
    th.textContent = c.label;
    if (c.unit) { const s = document.createElement('small'); s.textContent = c.unit; th.append(s); }
    if (sortable && c.key) {
      th.classList.add('sortable'); th.tabIndex = 0;
      if (c.key === sortKey) th.setAttribute('aria-sort', sortDir < 0 ? 'descending' : 'ascending');
      const go = () => { sortDir = sortKey === c.key ? -sortDir : (c.left ? 1 : -1); sortKey = c.key; renderMembers(); };
      th.addEventListener('click', go);
      th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    }
    tr.append(th);
  }
  table.tHead.replaceChildren(tr);
}
function notice(text) { el('notice').textContent = text || ''; }
window.almondResultsNotice = notice;
function act(action, data) {
  if (!native) { notice('Open AlmondResults inside Rhino to use this.'); return; }
  location.href = '/almond-action/' + token + '/results/' + action + (data ? '?data=' + encodeURIComponent(JSON.stringify(data)) : '');
}

// ------------------------------------------------------------------ members
const MEMBER_COLS = [
  {key: 'id', label: 'Member', left: true},
  {key: 'role', label: 'Role', left: true},
  {key: 'section', label: 'Section', left: true},
  {key: 'length_m', label: 'Length', unit: 'm'},
  {key: 'utilization', label: 'Utilization', unit: 'ULS'},
  {key: 'governing_check', label: 'Check', left: true},
  {key: 'governing_combination', label: 'Combination', left: true},
  {key: 'n_tension_kn', label: 'N⁺', unit: 'kN'},
  {key: 'n_compression_kn', label: 'N⁻', unit: 'kN'},
  {key: 'v_max_kn', label: 'V', unit: 'kN'},
  {key: 'm_max_knm', label: 'M', unit: 'kNm'},
  {key: 't_max_knm', label: 'T', unit: 'kNm'},
  {key: 'max_stress_mpa', label: 'σ', unit: 'MPa'},
  {key: 'slenderness', label: 'λ̄', unit: 'buckling'},
  {key: 'chi', label: 'χ', unit: 'buckling'},
  {key: 'deflection_mm', label: 'δ', unit: 'mm SLS'},
  {key: 'deflection_ratio', label: 'L/δ', unit: 'span'},
  {key: 'max_displacement_mm', label: 'Moves', unit: 'mm SLS'},
  {key: 'pinned', label: 'Ends', left: true},
];
function renderMembers() {
  const table = el('members');
  head(table, MEMBER_COLS, true);
  const shown = sortRows(filterRows(rows, filter, el('search').value), sortKey, sortDir);
  const body = shown.map(r => {
    const tr = document.createElement('tr');
    tr.tabIndex = 0;
    const name = td(r.id, 'l');
    if (r.layer) { const s = document.createElement('small'); s.textContent = r.layer; name.append(s); }
    const u = document.createElement('td');
    const state = utilState(r.utilization);
    u.innerHTML = '<span class="util"><span class="track"><span class="fill ' + state + '"></span></span><span class="' + state + '"></span></span>';
    u.querySelector('.fill').style.width = Math.min(100, (r.utilization || 0) * 100) + '%';
    u.querySelector('.util > span:last-child').textContent = finite(r.utilization) ? (r.utilization * 100).toFixed(1) + '%' : '—';
    tr.append(name, td(r.role || '—', 'l'), td(r.section || '—', 'l'), td(fmt(r.length_m, 2)), u,
      td(r.governing_check || '—', 'l'), td(r.governing_combination || '—', 'l'),
      td(fmt(r.n_tension_kn, 1)), td(fmt(r.n_compression_kn, 1)), td(fmt(r.v_max_kn, 1)), td(fmt(r.m_max_knm, 2)),
      td(fmt(r.t_max_knm, 2)), td(fmt(r.max_stress_mpa, 1)), td(fmt(r.slenderness, 2)), td(fmt(r.chi, 2)),
      td(fmt(r.deflection_mm, 1)), td(finite(r.deflection_ratio) ? 'L/' + r.deflection_ratio : '—'),
      td(fmt(r.max_displacement_mm, 1)), td(ends(r.pinned_ends), 'l'));
    const select = () => r.source_guids?.length && act('select', r.source_guids);
    tr.addEventListener('click', select);
    tr.addEventListener('keydown', e => { if (e.key === 'Enter') select(); });
    tr.title = 'Select ' + r.id + ' in Rhino';
    return tr;
  });
  table.tBodies[0].replaceChildren(...(body.length ? body : [rowNote('No members match this filter.', MEMBER_COLS.length)]));
  const c = counts(rows);
  document.querySelectorAll('[data-filter]').forEach(b => {
    const n = c[b.dataset.filter];
    b.querySelector('.n')?.remove();
    const s = document.createElement('span'); s.className = 'n'; s.textContent = n ?? ''; b.append(s);
    b.setAttribute('aria-pressed', String(b.dataset.filter === filter));
  });
  el('members-note').textContent = (rows.some(r => r.partial) ?
    'Karamba reports utilization per member only; run the native engine for forces, checks and deflections. ' : '') +
    'Showing ' + shown.length + ' of ' + rows.length + ' members.';
}

// ------------------------------------------------------------------ supports
function renderSupports() {
  const r = report.result, supports = r.supports || [];
  const combos = supports.length ? ['SLS', ...Object.keys(supports[0].uls || {})] : [];
  const sel = el('support-combo'), keep = sel.value;
  sel.replaceChildren(...combos.map(c => { const o = document.createElement('option'); o.value = c;
    o.textContent = c === 'SLS' ? (r.results?.deflection_combination || 'SLS characteristic') : c; return o; }));
  if (combos.includes(keep)) sel.value = keep;
  const DOF = ['Fx', 'Fy', 'Fz', 'Mx', 'My', 'Mz'];
  head(el('supports'), [{label: 'Node', left: true}, {label: 'x', unit: 'm'}, {label: 'y', unit: 'm'}, {label: 'z', unit: 'm'},
    {label: 'Restraint', left: true}, ...DOF.map(d => ({label: d, unit: d[0] === 'F' ? 'kN' : 'kNm'}))]);
  if (!supports.length) {
    el('supports').tBodies[0].replaceChildren(rowNote('No support reactions recorded for this result.', 11));
    el('supports').tFoot.replaceChildren(); return;
  }
  const pick = s => sel.value === 'SLS' ? s.sls : s.uls[sel.value];
  el('supports').tBodies[0].replaceChildren(...supports.map(s => {
    const tr = document.createElement('tr'), f = pick(s) || {};
    tr.append(td('N' + s.node, 'l'), ...s.position_m.map(v => td(fmt(v, 3))), td(s.restraint, 'l'), ...DOF.map(d => td(fmt(f[d], 2))));
    return tr;
  }));
  const tot = DOF.slice(0, 3).map(d => supports.reduce((a, s) => a + ((pick(s) || {})[d] || 0), 0));
  const tf = document.createElement('tr');
  tf.append(td('Sum', 'l'), td(''), td(''), td(''), td(''), ...tot.map(v => td(fmt(v, 2))), td(''), td(''), td(''));
  el('supports').tFoot.replaceChildren(tf);
}
function rowNote(text, span) {
  const tr = document.createElement('tr'), c = td(text, 'l dim'); c.colSpan = span; tr.append(c); return tr;
}

// ------------------------------------------------------------------ combinations, stability
function renderCombinations() {
  const m = report.result.results || {}, combos = m.combinations || [];
  head(el('combinations'), [{label: 'Combination', left: true}, {label: 'Factors', left: true}, {label: 'Max deflection', unit: 'mm'},
    {label: 'Max utilization', unit: 'ULS'}, {label: 'Vertical reactions', unit: 'kN'}, {label: 'Governing sway', left: true}]);
  el('combinations').tBodies[0].replaceChildren(...(combos.length ? combos.map(c => {
    const tr = document.createElement('tr');
    const factors = Object.entries(c.factors || {}).map(([k, v]) => v + k).join(' + ');
    tr.append(td(c.name, 'l'), td(factors || '—', 'l'), td(fmt(c.max_deflection_mm, 2)),
      td(finite(c.max_utilization) ? (c.max_utilization * 100).toFixed(1) + '%' : '—', utilState(c.max_utilization)),
      td(fmt(c.reactions_kn, 1)), td(c.governing_variant || '—', 'l'));
    return tr;
  }) : [rowNote('This engine reports no load combinations.', 6)]));
  const st = m.stability, b = report.native?.buckling;
  const alphas = st?.alpha_cr ? Object.entries(st.alpha_cr).map(([k, v]) => k + ': ' + (v ?? 'no compression')).join(' · ') : null;
  facts(el('stability'), st ? [
    ['Method', st.method], ['αcr', alphas], ['Lowest αcr', finite(st.min_alpha_cr) ? st.min_alpha_cr.toFixed(2) : null],
    ['Sway imperfection φ', st.sway_imperfection ? st.sway_imperfection.phi.toFixed(5) + ' (h ' + st.sway_imperfection.h_m +
      ' m, ' + st.sway_imperfection.columns + ' columns)' : null],
    ['Second-order combinations', st.second_order?.length ? st.second_order.join(', ') : 'none'],
    ['P-Δ iterations', st.iterations], ['Elements per compression member', st.elements_per_member],
    ['Buckling view', b ? 'αcr ' + b.alpha_cr + ' under ' + b.combination : null],
  ] : [['Stability', 'Not checked by this engine.']]);
}

// ------------------------------------------------------------------ loads and settings
function renderLoads() {
  const s = report.settings || {}, r = report.result, code = r.design_code;
  facts(el('settings'), [
    ['Engine', s.engine === 'karamba' ? 'Karamba3D' : 'Almond native'], ['Design code', code?.name],
    ['ULS expression', code?.uls_expression], ['Structure', s.structure], ['Material', s.material],
    ['Imposed point load', finite(s.load_kn) ? s.load_kn + ' kN over the free nodes' : null],
    ['Floor load', s.floor_imposed_kn_m2 || s.floor_dead_kn_m2 ? s.floor_imposed_kn_m2 + ' imposed + ' + s.floor_dead_kn_m2 + ' build-up kN/m²' : 'none'],
    ['Placed models as loads', s.asset_loads ? 'yes' : 'no'], ['Self-weight', s.self_weight ? 'included' : 'excluded'],
    ['Supports', (s.fixed_rotations ? 'fixed' : 'pinned') + (s.explicit_supports ? ', selected points only' : '')],
    ['Connections', s.connections], ['Stability', s.stability],
    ['Section override', finite(s.diameter_mm) ? 'CHS ' + s.diameter_mm + ' × ' + s.wall_mm + ' mm' : 'inferred sections'],
    ['Deflection limit', finite(r.results?.deflection_limit_mm) ? fmt(r.results.deflection_limit_mm, 2) + ' mm over ' +
      r.results.span_m + ' m (' + r.results.span_basis + ')' : null],
  ]);
  const floor = r.floor_loads;
  el('floor-block').hidden = !floor;
  if (floor) {
    head(el('floor'), [{label: 'Level', unit: 'z m'}, {label: 'Bays'}, {label: 'Area', unit: 'm²'}, {label: 'Bearing walls'}]);
    el('floor').tBodies[0].replaceChildren(...(floor.levels || []).map(l => {
      const tr = document.createElement('tr');
      tr.append(td(fmt(l.z_m, 2)), td(String(l.bays)), td(fmt(l.area_m2, 1)), td(String(l.bearing_walls)));
      return tr;
    }));
    const tf = document.createElement('tr');
    tf.append(td('Total'), td(''), td(fmt(floor.area_m2, 1)), td(fmt(floor.total_kn, 1) + ' kN (' + fmt(floor.imposed_kn, 1) + ' Q + ' + fmt(floor.dead_kn, 1) + ' G)'));
    el('floor').tBodies[0].append(tf);
  }
  const assets = r.asset_loads;
  el('asset-block').hidden = !assets;
  if (assets) {
    head(el('assets'), [{label: 'Item', left: true}, {label: 'Category', left: true}, {label: 'Weight', unit: 'G kN'},
      {label: 'In use', unit: 'Q kN'}, {label: 'Level', unit: 'm'}, {label: 'Carried by', left: true}, {label: 'Use', left: true}]);
    el('assets').tBodies[0].replaceChildren(...(assets.placements || []).map(p => {
      const tr = document.createElement('tr');
      const by = (p.carried_by || []).map(c => Math.round(c.share * 100) + '% ' + (c.source_guids || []).join(' ').slice(0, 8)).join(', ');
      tr.append(td(p.name || p.asset_id, 'l'), td(p.category || '—', 'l'), td(fmt(p.dead_kn, 2)), td(fmt(p.imposed_kn, 2)),
        td(fmt(p.level_m, 2)), td(by || p.skipped_reason || 'not applied', 'l'), td(p.use || '—', 'l'));
      return tr;
    }));
    el('asset-basis').textContent = assets.applied + ' applied, ' + assets.skipped + ' skipped · ' + fmt(assets.total_kn, 2) + ' kN in total. ' + (assets.basis || '');
  }
}

function renderNotes() {
  const r = report.result;
  el('verdict-text').textContent = r.verdict || 'No verdict returned.';
  el('suggest-block').hidden = !(r.suggestions || []).length;
  el('suggestions').replaceChildren(...(r.suggestions || []).map(li));
  el('warnings').replaceChildren(...((r.warnings || []).length ? r.warnings : ['None.']).map(li));
  el('assumptions').replaceChildren(...(r.assumptions || []).map(li));
  el('limits').textContent = report.limits || '';
}

function renderSummary() {
  const r = report.result, m = r.results || {}, st = stabilityState(r, report.native), c = counts(rows);
  const pass = r.status === 'pass';
  el('method').textContent = engineLabel(r, report.settings) + (report.native?.version ? ' · almond-mcp ' + report.native.version : '');
  el('verdict').textContent = pass ? 'Pass' : r.status === 'fail' ? 'Fail' : 'Incomplete';
  el('verdict').parentElement.dataset.state = pass ? 'pass' : r.status === 'fail' ? 'fail' : '';
  el('verdict-note').textContent = pass ? 'Within the configured checks' : r.status === 'fail' ? 'Configured checks exceeded' : (r.verdict || '');
  el('sum-defl').textContent = finite(m.max_deflection_mm) ? fmt(m.max_deflection_mm, 1) + ' mm' : '—';
  el('sum-defl-note').textContent = finite(m.deflection_limit_mm) ? 'limit ' + fmt(m.deflection_limit_mm, 1) + ' mm' : '';
  el('sum-util').textContent = finite(m.utilization_ratio) ? (m.utilization_ratio * 100).toFixed(1) + '%' : '—';
  el('sum-util').className = utilState(m.utilization_ratio);
  el('sum-util-note').textContent = m.utilization_combination || '';
  el('sum-alpha').textContent = st ? st.value.replace('αcr = ', '') : '—';
  el('sum-alpha-note').textContent = m.stability?.method || (st ? '' : 'not checked');
  el('sum-count').textContent = String(c.all);
  el('sum-count-note').textContent = c.fail + ' over 100% · ' + c.warn + ' at 80–100%';
  el('snapshot').textContent = 'Analysed ' + new Date(report.created_at).toLocaleString() + '. Results do not follow later edits in Rhino: run the analysis again after changing the model.';
}

function render() {
  el('empty').hidden = !!report;
  el('report').hidden = !report;
  el('export').disabled = !native || !report?.result?.members?.length;
  if (!report) return;
  rows = memberRows(report);
  renderSummary(); renderMembers(); renderSupports(); renderCombinations(); renderLoads(); renderNotes();
}

window.almondResultsReceive = payload => {
  report = payload && payload.result ? payload : null;
  notice(report ? '' : '');
  render();
};

document.querySelectorAll('[role=tab]').forEach(tab => tab.addEventListener('click', () => {
  document.querySelectorAll('[role=tab]').forEach(t => {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    el(t.getAttribute('aria-controls')).hidden = !on;
  });
}));
document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => { filter = b.dataset.filter; renderMembers(); }));
el('search').addEventListener('input', () => report && renderMembers());
el('support-combo').addEventListener('change', renderSupports);
el('refresh').addEventListener('click', () => act('refresh'));
el('export').addEventListener('click', () => act('export_csv'));
if (!native) notice('This page shows results inside Rhino: run AlmondResults there.');
render();
