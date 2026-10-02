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

export function filterRows(rows, filter = 'all', query = '') {
  const q = query.trim().toLowerCase();
  return rows.filter(row => {
    if (filter === 'fail' && !(row.utilization > 1)) return false;
    if (filter === 'warn' && !(row.utilization > 0.8 && row.utilization <= 1)) return false;
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
    if (r.utilization > 1) out.fail++;
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
