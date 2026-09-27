// Presentation of recorded results only. No solver or invented displacement field.
export function finite(value) { return typeof value === 'number' && Number.isFinite(value); }
export function metricState(result) {
  const m = result?.results || {};
  const api = m.analysis_method === 'api';
  return {
    deflection: api && m.displacement_available === true && finite(m.max_deflection_mm) ? m.max_deflection_mm : null,
    utilization: api && m.utilization_available === true && finite(m.utilization_ratio) ? m.utilization_ratio : null,
    limit: finite(m.deflection_limit_mm) && m.deflection_limit_mm > 0 ? m.deflection_limit_mm : null,
    complete: api && m.displacement_available === true && m.utilization_available === true &&
      finite(m.max_deflection_mm) && finite(m.utilization_ratio) && ['pass','fail'].includes(result?.status)
  };
}
export function utilizationFor(guids, entries) {
  const matches = (entries || []).filter(e => (e.source_guids || []).some(g => guids.includes(g)) && finite(e.utilization));
  return matches.length ? Math.max(...matches.map(e => e.utilization)) : null;
}
export function utilizationColour(value) {
  return value == null ? '#93958b' : value > 1 ? '#d33926' : value > .8 ? '#ab6b11' : '#237963';
}
export function projectPoint(p, view = 'axon') {
  if (!Array.isArray(p) || p.length !== 3 || !p.every(finite)) return null;
  if (view === 'front') return [p[0], -p[2]];
  if (view === 'top') return [p[0], -p[1]];
  return [(p[0]-p[1])*.8660254, (p[0]+p[1])*.5-p[2]];
}
