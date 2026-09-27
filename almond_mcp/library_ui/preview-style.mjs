// Preview-only material overrides. Never export these or modify the source GLB.
const originals = new WeakMap();
export const previewStyles = new Set(['material', 'rendered', 'arctic', 'ghosted', 'shaded']);

export function applyPreviewStyle(viewer, style) {
  if (!previewStyles.has(style)) style = 'material';
  viewer.dataset.previewStyle = style;
  viewer.setAttribute('shadow-intensity', style === 'ghosted' ? '0' : style === 'arctic' ? '1' : '0.5');
  viewer.setAttribute('shadow-softness', '1');
  viewer.setAttribute('exposure', style === 'arctic' ? '1.2' : '1.1');
  for (const material of viewer.model?.materials || []) {
    const pbr = material.pbrMetallicRoughness;
    if (!originals.has(material)) originals.set(material, {
      color: [...pbr.baseColorFactor], metallic: pbr.metallicFactor,
      roughness: pbr.roughnessFactor, alpha: material.getAlphaMode(),
      doubleSided: material.getDoubleSided()
    });
    const original = originals.get(material);
    const neutral = ['arctic', 'ghosted', 'shaded'].includes(style);
    const color = style === 'arctic' ? [0.92, 0.92, 0.92, 1]
      : style === 'ghosted' ? [0.55, 0.60, 0.63, 0.32]
      : style === 'shaded' ? [0.55, 0.58, 0.60, 1] : original.color;
    material.setAlphaMode(style === 'ghosted' ? 'BLEND' : neutral ? 'OPAQUE' : original.alpha);
    material.setDoubleSided(style === 'ghosted' || original.doubleSided);
    pbr.setBaseColorFactor([...color]);
    pbr.setMetallicFactor(neutral ? 0 : original.metallic);
    pbr.setRoughnessFactor(neutral ? 0.85 : original.roughness);
  }
}

export function displayChoice(choice, viewport) {
  if (choice !== 'auto') return {style: previewStyles.has(choice) ? choice : 'material', label: choice === 'material' ? 'Material colours' : choice[0].toUpperCase() + choice.slice(1)};
  if (!viewport) return {style: 'material', label: 'Waiting for Rhino · material colours'};
  return {style: viewport.supported && previewStyles.has(viewport.style) ? viewport.style : 'material',
    label: viewport.supported ? `${viewport.name} · following viewport` : `${viewport.name} · material colour fallback`};
}
