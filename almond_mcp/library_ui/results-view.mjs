// Pure helpers for the results page: no DOM, no Rhino. Tested by tests/results_view.test.mjs.
export const finite = v => typeof v === 'number' && Number.isFinite(v);

export function fmt(value, digits = 1) {
  if (!finite(value)) return '—';
  const text = value.toFixed(digits);
  return Number(text) === 0 ? text.replace('-', '') : text;   // never "-0.00"
}

export function utilState(u) {
  return !finite(u) ? 'dim' : u > 1 ? 'fail' : u > 0.8 ? 'warn' : 'ok';
}

// Rows for the member table. The native engine reports full rows; Karamba reports utilization per
// member only, so those rows carry what exists and nothing is invented.
export function memberRows(report) {
  const r = report?.result || {};
  if (Array.isArray(r.members) && r.members.length) {
    return r.members.map((m, i) => ({...m, order: i}));
  }
  const per = r.results?.per_element_utilization || [];
  return per.map((e, i) => ({
    id: 'M' + (i + 1), source_guids: e.source_guids || [], role: null, section: null, length_m: null,
    utilization: finite(e.utilization) ? e.utilization : null, status: utilState(e.utilization),
    governing_combination: e.combination || null, order: i, partial: true,
  }));
}

// Failing members: over 100%, or outside the checks (Class 4, a web that buckles in shear) whatever the ratio.
export const failing = row => row.utilization > 1 || row.status === 'fail';

export function filterRows(rows, filter = 'all', query = '') {
  const q = query.trim().toLowerCase();
  return rows.filter(row => {
    if (filter === 'fail' && !failing(row)) return false;
    if (filter === 'warn' && !(row.utilization > 0.8 && !failing(row))) return false;
    if (['column', 'beam', 'brace'].includes(filter) && row.role !== filter) return false;
    if (!q) return true;
    return [row.id, row.section, row.layer, row.role, row.material, ...(row.source_guids || [])]
      .some(v => typeof v === 'string' && v.toLowerCase().includes(q));
  });
}

// Natural sort for ids ("M2" before "M10"); missing values always last.
export function sortRows(rows, key, dir = -1) {
  const collator = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
  const value = row => key === 'pinned' ? (row.pinned_ends?.start ? 1 : 0) + (row.pinned_ends?.end ? 1 : 0) : row[key];
  return [...rows].sort((a, b) => {
    const va = value(a), vb = value(b);
    const ma = va === null || va === undefined || (typeof va === 'number' && !Number.isFinite(va));
    const mb = vb === null || vb === undefined || (typeof vb === 'number' && !Number.isFinite(vb));
    if (ma || mb) return ma === mb ? a.order - b.order : ma ? 1 : -1;
    const c = typeof va === 'number' && typeof vb === 'number' ? va - vb : collator.compare(String(va), String(vb));
    return c === 0 ? a.order - b.order : c * dir;
  });
}

export function counts(rows) {
  const out = {all: rows.length, fail: 0, warn: 0, column: 0, beam: 0, brace: 0};
  for (const r of rows) {
    if (failing(r)) out.fail++;
    else if (r.utilization > 0.8) out.warn++;
    if (r.role in out) out[r.role]++;
  }
  return out;
}

export function ends(pinned) {
  if (!pinned) return '—';
  const one = v => v ? 'pin' : 'rigid';
  return one(pinned.start) + ' · ' + one(pinned.end);
}

// Shear cell, EN 1993-1-1 6.2.6 / 6.2.8: utilization V_Ed / V_pl,Rd, a web too slender for these checks
// (hw/tw > 72 eps / eta, shear buckling to EN 1993-1-5) fails whatever the ratio.
export function shearCell(row) {
  const u = row?.shear_utilization;
  const text = finite(u) ? (u * 100).toFixed(1) + '%' : '—';
  if (row?.shear_buckling) return {text: text + ' · web', state: 'fail',
    title: 'Web slenderness hw/tw above 72ε/η: shear buckling (EN 1993-1-5) is not covered by these checks.'};
  const rho = row?.shear_rho;
  const title = finite(rho) && rho > 0 ? 'V_Ed above half V_pl,Rd: bending resistance reduced by ρ = ' + rho.toFixed(3) + ' (6.2.8).'
    : finite(u) ? 'V_Ed / V_pl,Rd (6.2.6).' : 'No shear check for this member.';
  return {text, state: finite(u) ? utilState(u) : 'dim', title};
}

// Sway imperfection per direction (5.3.2(3)); older reports carry one phi only.
export function swayText(si) {
  if (!si || !finite(si.phi)) return null;
  const where = ' (h ' + si.h_m + ' m, ' + si.columns + ' column lines)';
  if (!finite(si.phi_x) || !finite(si.phi_y)) return si.phi.toFixed(5) + where;
  const one = (axis, phi, m) => axis + ' ' + phi.toFixed(5) + (finite(m) ? ' (m ' + m + ')' : '');
  return one('x', si.phi_x, si.m_x) + ' · ' + one('y', si.phi_y, si.m_y) + where;
}

// Local bow imperfections (5.3.2(6)): what was applied, and why the rest was not.
export function bowText(bi) {
  if (!bi) return null;
  const applied = bi.applied || [];
  const skipped = Object.entries(bi.skipped || {}).map(([why, n]) => n + ' × ' + why);
  if (!applied.length) return 'none' + (skipped.length ? ': ' + skipped.join('; ') : '');
  const members = new Set(applied.map(b => (b.source_guids || []).join(',') + '|' + b.combination)).size;
  const amps = [...new Set(applied.map(b => b.e0_over_l))].sort().join(', ');
  return applied.length + ' member ' + (applied.length === 1 ? 'axis' : 'axes') + ' on ' + members + ' member' +
    (members === 1 ? '' : 's') + ' (e0 ' + amps + ')' + (skipped.length ? '; skipped ' + skipped.join('; ') : '');
}
