import test from 'node:test';
import assert from 'node:assert/strict';
import {metricState, utilizationFor, utilizationColour, projectPoint, engineLabel, stabilityState} from '../almond_mcp/library_ui/analysis-view.mjs';

test('missing and estimated metrics cannot appear as a completed Karamba check', () => {
  for (const result of [undefined, {}, {status:'pass', results:{}},
    {status:'pass', results:{analysis_method:'rule_based', max_deflection_mm:0, utilization_ratio:0}}]) {
    const state=metricState(result);
    assert.equal(state.complete, false);
    assert.equal(state.deflection, null);
    assert.equal(state.utilization, null);
  }
});
test('zero is a valid measured value only with explicit availability', () => {
  const result={status:'pass',results:{analysis_method:'api', displacement_available:true,
    utilization_available:true, max_deflection_mm:0, utilization_ratio:0, deflection_limit_mm:20}};
  assert.deepEqual(metricState(result), {complete:true,deflection:0,utilization:0,limit:20});
  for (const value of [undefined, NaN, Infinity]) {
    assert.equal(metricState({...result,results:{...result.results,max_deflection_mm:value}}).complete,false);
  }
  assert.equal(metricState({...result,status:'incomplete'}).complete,false);
  assert.equal(metricState({...result,results:{...result.results,utilization_available:false}}).utilization,null);
});
test('split member colouring uses the largest mapped utilization; absent data stays neutral', () => {
  const entries=[{source_guids:['a'],utilization:.3},{source_guids:['a','b'],utilization:1.2},
    {source_guids:['a'],utilization:NaN}];
  assert.equal(utilizationFor(['a'],entries),1.2);
  assert.equal(utilizationFor(['c'],entries),null);
  assert.equal(utilizationColour(utilizationFor(['c'],entries)),'#93958b');
  assert.notEqual(utilizationColour(.3),utilizationColour(1.2));
});
test('diagram views preserve coordinates and reject nonfinite geometry', () => {
  assert.deepEqual(projectPoint([2,3,4],'front'),[2,-4]);
  assert.deepEqual(projectPoint([2,3,4],'top'),[2,-3]);
  assert.equal(projectPoint([2,Infinity,4]),null);
  assert.equal(projectPoint([2,3]),null);
});
test('the native engine counts as a completed analysis; estimates still do not', () => {
  const result={status:'fail',results:{analysis_method:'native', displacement_available:true,
    utilization_available:true, max_deflection_mm:25.9, utilization_ratio:.98, deflection_limit_mm:24.8,
    design_basis:'en1990', stability:{mode:'auto', method:'first-order', min_alpha_cr:126.1}}};
  assert.deepEqual(metricState(result), {complete:true,deflection:25.9,utilization:.98,limit:24.8});
  assert.equal(engineLabel(result,{uls_combination:'6.10'}),'Almond native · first-order · EN 1990');
  assert.equal(engineLabel({results:{analysis_method:'api'}}),'Karamba · first-order analysis');
  assert.equal(engineLabel({results:{analysis_method:'rule_based'}}),'No completed analysis');
});
test('stability reads alpha_cr against the EN 1993 thresholds', () => {
  const at=(alpha,method='first-order')=>stabilityState({results:{stability:{mode:'auto',method,min_alpha_cr:alpha}}});
  assert.match(at(126.1).basis,/adequate/);
  assert.match(at(5.97,'second-order (P-Delta)').basis,/second-order/);
  assert.equal(at(null,'unstable').value,'Unstable');
  assert.equal(stabilityState({results:{stability:{mode:'off'}}}),null);
  assert.equal(stabilityState({results:{}}),null);
  assert.equal(stabilityState({results:{}},{buckling:{alpha_cr:5.966,combination:'ULS 6.10'}}).value,'αcr = 5.97');
});
