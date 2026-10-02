import test from 'node:test';
import assert from 'node:assert/strict';
import {fmt, utilState, memberRows, filterRows, sortRows, counts, ends} from '../almond_mcp/library_ui/results-view.mjs';

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
  assert.equal(fmt(NaN), '—'); assert.equal(fmt(null), '—'); assert.equal(fmt(2.345, 2), '2.35');
  assert.deepEqual([utilState(1.2), utilState(0.9), utilState(0.2), utilState(null)], ['fail', 'warn', 'ok', 'dim']);
  assert.equal(ends({start: true, end: false}), 'pin · rigid'); assert.equal(ends(null), '—');
});
