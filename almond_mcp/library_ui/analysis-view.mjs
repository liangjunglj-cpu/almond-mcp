// Presentation of recorded results only. No solver or invented displacement field.
const SOLVED = ['api', 'native'];   // Karamba ("api") or Almond's native frame solver
export function finite(value) { return typeof value === 'number' && Number.isFinite(value); }
export function metricState(result) {
  const m = result?.results || {};
  const solved = SOLVED.includes(m.analysis_method);
  return {
    deflection: solved && m.displacement_available === true && finite(m.max_deflection_mm) ? m.max_deflection_mm : null,
    utilization: solved && m.utilization_available === true && finite(m.utilization_ratio) ? m.utilization_ratio : null,
    limit: finite(m.deflection_limit_mm) && m.deflection_limit_mm > 0 ? m.deflection_limit_mm : null,
    complete: solved && m.displacement_available === true && m.utilization_available === true &&
      finite(m.max_deflection_mm) && finite(m.utilization_ratio) && ['pass','fail','indicative'].includes(result?.status)
  };
}
export function engineLabel(result, settings) {
  const m = result?.results || {};
  if (m.analysis_method === 'api') return 'Karamba · first-order analysis';
  if (m.analysis_method !== 'native') return 'No completed analysis';
  const code = result?.design_code;
  const basis = code ? (code.id === 'off' ? 'unfactored G + Q' : code.name + ' · ULS ' + (code.uls_expression || '6.10')) :
    m.design_basis === 'unfactored' ? 'unfactored G + Q' :
    settings?.uls_combination === '6.10ab' ? 'EN 1990 6.10a/b' : 'EN 1990';
  const method = m.stability?.method || 'first-order';
  return 'Almond native · ' + method + ' · ' + basis;
}
// alpha_cr: >= 10 first order is adequate, 1-10 second-order (P-Delta) was used, <= 1 unstable (EN 1993-1-1 5.2.1)
export function stabilityState(result, native) {
  const st = result?.results?.stability;
  const mode = native?.buckling;
  if (mode && finite(mode.alpha_cr)) {
    return {value: 'αcr = ' + mode.alpha_cr.toFixed(2), basis: 'First buckling mode under ' + mode.combination +
      ': the loads may grow ' + mode.alpha_cr.toFixed(1) + '× before the frame buckles.'};
  }
  if (!st || st.mode === 'off') return null;
  if (st.method === 'unstable') return {value: 'Unstable', basis: 'αcr ≤ 1: the frame buckles before it reaches the design loads.'};
  if (!finite(st.min_alpha_cr)) return {value: 'No compression', basis: 'Nothing is in compression: there is no buckling mode.'};
  return {value: 'αcr = ' + st.min_alpha_cr.toFixed(2), basis: st.min_alpha_cr >= 10 ?
    'At least 10: first-order analysis is adequate (sway imperfections included).' :
    'Below 10: second-order (P-Δ) analysis with sway imperfections was used for the member checks.'};
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
