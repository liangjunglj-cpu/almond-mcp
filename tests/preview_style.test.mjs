import {test} from 'node:test';
import assert from 'node:assert/strict';
import {applyPreviewStyle, displayChoice} from '../almond_mcp/library_ui/preview-style.mjs';

function fixture() {
  const pbr = {baseColorFactor: [0.35, 0.16, 0.06, 1], metallicFactor: 0.7, roughnessFactor: 0.3,
    setBaseColorFactor(v) {this.baseColorFactor = v;}, setMetallicFactor(v) {this.metallicFactor = v;}, setRoughnessFactor(v) {this.roughnessFactor = v;}};
  const material = {pbrMetallicRoughness: pbr, alpha: 'OPAQUE', doubleSided: false,
    getAlphaMode() {return this.alpha;}, setAlphaMode(v) {this.alpha=v;},
    getDoubleSided() {return this.doubleSided;}, setDoubleSided(v) {this.doubleSided=v;}};
  return {dataset: {}, attributes: {}, model: {materials: [material]}, setAttribute(k,v) {this.attributes[k]=v;}};
}
test('switching ghosted/arctic/shaded back to rendered restores source material exactly', () => {
  const viewer = fixture(), m = viewer.model.materials[0], pbr = m.pbrMetallicRoughness;
  for (let i=0; i<3; i++) {
    applyPreviewStyle(viewer, 'ghosted');
    assert.equal(m.alpha, 'BLEND'); assert.equal(pbr.baseColorFactor[3], 0.32);
    applyPreviewStyle(viewer, 'arctic');
    assert.equal(m.alpha, 'OPAQUE'); assert.equal(pbr.baseColorFactor[0], pbr.baseColorFactor[2]);
    assert.equal(pbr.baseColorFactor[3], 1);
    applyPreviewStyle(viewer, 'shaded');
    applyPreviewStyle(viewer, 'rendered');
    assert.deepEqual(pbr.baseColorFactor, [0.35, 0.16, 0.06, 1]);
    assert.equal(pbr.metallicFactor, 0.7); assert.equal(pbr.roughnessFactor, 0.3);
    assert.equal(m.alpha, 'OPAQUE'); assert.equal(m.doubleSided, false);
  }
});
test('separate models retain their own originals; unloaded models are safe', () => {
  const a=fixture(), b=fixture();
  b.model.materials[0].pbrMetallicRoughness.baseColorFactor=[0,1,0,1];
  applyPreviewStyle(a,'ghosted'); applyPreviewStyle(b,'arctic');
  applyPreviewStyle(b,'material');
  assert.deepEqual(b.model.materials[0].pbrMetallicRoughness.baseColorFactor,[0,1,0,1]);
  const pending=fixture(); delete pending.model; applyPreviewStyle(pending,'arctic');
});
test('auto follows supported viewport modes, while explicit override and custom fallback remain honest', () => {
  assert.equal(displayChoice('auto',null).style,'material');
  const viewport={style:'ghosted',name:'Ghosted',supported:true};
  assert.equal(displayChoice('auto',viewport).style,'ghosted');
  assert.equal(displayChoice('arctic',viewport).style,'arctic');
  assert.match(displayChoice('auto',{style:'wireframe',name:'Wireframe',supported:false}).label,/fallback/);
  assert.equal(displayChoice('auto',{style:'unknown',name:'Custom',supported:false}).style,'material');
});
