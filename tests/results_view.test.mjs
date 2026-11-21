import test from 'node:test';
import assert from 'node:assert/strict';
import {fmt, utilState, memberRows, filterRows, sortRows, counts, ends, shearCell, swayText, bowText, ltbCell, restraintText} from '../almond_mcp/library_ui/results-view.mjs';

const native = {result: {members: [
  {id: 'M10', role: 'beam', section: 'CHS 219.1x8', layer: 'A07 / Structure', utilization: 0.86, source_guids: ['a']},
  {id: 'M2', role: 'column', section: 'CHS 219.1x8', utilization: 1.12, source_guids: ['b']},
  {id: 'M3', role: 'brace', section: 'CHS 114.3x4', utilization: 0.4, deflection_ratio: null, source_guids: ['c']},
]}};

test('native rows keep every field; Karamba rows carry only what Karamba reports', () => {
  const rows = memberRows(native);
  assert.equal(rows.length, 3);
  assert.equal(rows[0].layer, 'A07 / Structure');
  const k = memberRows({result: {results: {per_element_utilization: [{source_guids: ['x'], utilization: 0.5}]}}});
  assert.deepEqual([k[0].id, k[0].utilization, k[0].section, k[0].partial], ['M1', 0.5, null, true]);
  assert.deepEqual(memberRows(null), []);
});
test('filters by state, role and text', () => {
  const rows = memberRows(native);
  assert.deepEqual(filterRows(rows, 'fail').map(r => r.id), ['M2']);
  assert.deepEqual(filterRows(rows, 'warn').map(r => r.id), ['M10']);
  assert.deepEqual(filterRows(rows, 'brace').map(r => r.id), ['M3']);
  assert.deepEqual(filterRows(rows, 'all', '114').map(r => r.id), ['M3']);
  assert.deepEqual(filterRows(rows, 'all', 'structure').map(r => r.id), ['M10']);
  assert.deepEqual(counts(rows), {all: 3, fail: 1, warn: 1, column: 1, beam: 1, brace: 1});
});
test('sorts numbers, natural ids, and keeps missing values last', () => {
  const rows = memberRows(native);
  assert.deepEqual(sortRows(rows, 'utilization', -1).map(r => r.id), ['M2', 'M10', 'M3']);
  assert.deepEqual(sortRows(rows, 'id', 1).map(r => r.id), ['M2', 'M3', 'M10']);
  assert.equal(sortRows(rows, 'deflection_ratio', 1).at(-1).id, 'M3');
});
test('formatting never shows NaN', () => {
  assert.equal(fmt(-0.001, 2), '0.00'); assert.equal(fmt(-0.5, 1), '-0.5'); assert.equal(fmt(NaN), '—'); assert.equal(fmt(null), '—'); assert.equal(fmt(2.345, 2), '2.35');
  assert.deepEqual([utilState(1.2), utilState(0.9), utilState(0.2), utilState(null)], ['fail', 'warn', 'ok', 'dim']);
  assert.equal(ends({start: true, end: false}), 'pin · rigid'); assert.equal(ends(null), '—');
});
test('shear cell: V/Vpl,Rd, the 6.2.8 reduction, and webs outside the checks', () => {
  assert.deepEqual([shearCell({shear_utilization: 0.2859}).text, shearCell({shear_utilization: 0.2859}).state], ['28.6%', 'ok']);
  assert.match(shearCell({shear_utilization: 0.8, shear_rho: 0.36}).title, /ρ = 0\.360/);
  assert.equal(shearCell({shear_utilization: 0.9}).state, 'warn');
  const web = shearCell({shear_utilization: 0.1, shear_buckling: true});
  assert.deepEqual([web.text, web.state], ['10.0% · web', 'fail']);
  assert.match(web.title, /EN 1993-1-5/);
  assert.deepEqual([shearCell({}).text, shearCell({}).state], ['—', 'dim']);          // Karamba rows: no shear check
});
test('sway imperfection per direction, and older single-phi reports', () => {
  const si = {phi: 0.005, phi_x: 0.00433, phi_y: 0.005, m_x: 2, m_y: 1, h_m: 4, columns: 4};
  assert.equal(swayText(si), 'x 0.00433 (m 2) · y 0.00500 (m 1) (h 4 m, 4 column lines)');
  assert.equal(swayText({phi: 0.00395, h_m: 3.085, columns: 4}), '0.00395 (h 3.085 m, 4 column lines)');
  assert.equal(swayText(null), null);
});
test('bow imperfections: applied amplitudes and skip reasons', () => {
  const applied = [{source_guids: ['c1'], combination: 'ULS 6.10', axis: 'y', e0_over_l: '1/200'},
                   {source_guids: ['c1'], combination: 'ULS 6.10', axis: 'z', e0_over_l: '1/200'}];
  assert.equal(bowText({applied, skipped: {'no moment-resistant end': 4}}),
    '2 member axes on 1 member (e0 1/200); skipped 4 × no moment-resistant end');
  assert.equal(bowText({applied: [], skipped: {'alpha_cr >= 10: first-order, 5.3.2(6) needs no bows': 1}}),
    'none: 1 × alpha_cr >= 10: first-order, 5.3.2(6) needs no bows');
  assert.equal(bowText({applied: [], skipped: {}}), 'none');
  assert.equal(bowText(undefined), null);
});
test('members outside the checks count as failing whatever their ratio', () => {
  const rows = memberRows({result: {members: [
    {id: 'W', role: 'beam', utilization: 0.09, status: 'fail', shear_buckling: true},
    {id: 'C4', role: 'column', utilization: 0.85, status: 'fail', section_class: 4},
    {id: 'OK', role: 'beam', utilization: 0.85, status: 'warn'},
  ]}});
  assert.deepEqual(filterRows(rows, 'fail').map(r => r.id), ['W', 'C4']);
  assert.deepEqual(filterRows(rows, 'warn').map(r => r.id), ['OK']);
  assert.deepEqual([counts(rows).fail, counts(rows).warn], [2, 1]);
});
test('LTB cell: M/Mb,Rd with the segment working in the tooltip, dash when not checked', () => {
  const row = {ltb_utilization: 1.4419, m_cr_knm: 79.944, lambda_lt: 1.252, chi_lt: 0.498, ltb_curve: 'a',
    ltb_length_m: 6, ltb_ends: ['fork', 'fork'], cm_lt: 1};
  const c = ltbCell(row);
  assert.deepEqual([c.text, c.state], ['144.2%', 'fail']);
  assert.equal(c.title, 'M_Ed / M_b,Rd (6.3.2). M_cr 79.9 kNm · λ̄_LT 1.252 · χ_LT 0.498 (curve a) · segment 6.00 m, fork / fork · C_mLT 1.00');
  assert.equal(ltbCell({ltb_utilization: 0.5}).state, 'ok');
  assert.deepEqual([ltbCell({}).text, ltbCell({}).state], ['—', 'dim']);
  assert.match(ltbCell({ltb_utilization: null}).title, /lateral_restraint/);
});
test('lateral restraint mode in the settings', () => {
  assert.match(restraintText('joints'), /LTB checked/);
  assert.match(restraintText('continuous'), /no LTB check/);
  assert.equal(restraintText(undefined), null);
});
