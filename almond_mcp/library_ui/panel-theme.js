// Apply the host palette before the first paint; browser pages keep the archive style.
// Inside Rhino every Almond page takes Rhino's own colours: no brand palette, Rhino's accent for selection.
(() => {
  const params = new URLSearchParams(location.search);
  if (params.get('panel') !== '1') return;
  const root = document.documentElement;
  root.classList.add('rhino-panel');
  const rgb = hex => hex.slice(1).match(/../g).map(n => parseInt(n, 16));
  const luminance = hex => rgb(hex).map(n => {
    n /= 255; return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
  }).reduce((v, n, i) => v + n * [.2126, .7152, .0722][i], 0);
  const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
  const mix = (a, b, weight) => '#' + rgb(a).map((n, i) => Math.round(n * (1 - weight) + rgb(b)[i] * weight).toString(16).padStart(2, '0')).join('');
  const light = {paper:'#f0f0f0', ink:'#202020', control:'#e5e5e5', field:'#ffffff', line:'#b5b5b5', hover:'#d7e7f7', accent:'#2f74c0', tab:'#e1e1e1'};
  const dark = {paper:'#333333', ink:'#eeeeee', control:'#414141', field:'#272727', line:'#656565', hover:'#4e5964', accent:'#5c9ee0', tab:'#2a2a2a'};
  window.almondThemeReceive = input => {
    const value = input && typeof input === 'object' ? input : {};
    const valid = v => typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v);
    const base = valid(value.paper) ? (luminance(value.paper) < .3 ? dark : light) : light;
    const palette = Object.fromEntries(Object.keys(base).map(k => [k, valid(value[k]) ? value[k] : base[k]]));
    // Custom Rhino themes occasionally contain unset or unreadable colour pairs.
    if (contrast(palette.paper, palette.ink) < 4.5) palette.ink = luminance(palette.paper) < .18 ? '#ffffff' : '#171717';
    for (const key of ['control', 'field', 'hover', 'tab']) {
      if (contrast(palette[key], palette.ink) < 4.5) palette[key] = palette.paper;
    }
    // Rhino's highlight colour marks selection and focus; it must stay visible on the panel.
    if (contrast(palette.accent, palette.paper) < 3) palette.accent = base.accent;
    // Rhino's dark theme paints hover in the panel colour itself: lift it so hover stays visible.
    if (contrast(palette.hover, palette.paper) < 1.15) palette.hover = mix(palette.paper, palette.ink, .12);
    let muted = mix(palette.paper, palette.ink, .7);
    if (contrast(muted, palette.paper) < 4.5) muted = palette.ink;
    const isDark = luminance(palette.paper) < .3;
    Object.entries({...palette, muted, panel:mix(palette.paper, palette.ink, .045),
      preview:isDark?'#a5a9ad':'#e2e3e4', 'preview-ink':'#252729',
      red:palette.accent, busy:palette.accent, ok:isDark?'#5cc29f':'#1f7a52', warn:isDark?'#e3b341':'#8a5a00',
      err:isDark?'#ff7a63':'#c42b1c', 'diagram-member':palette.ink,
      'diagram-shell':muted, 'diagram-support':isDark?'#67c7a7':'#237963',
      'diagram-load':isDark?'#ff806a':'#c23220'
    }).forEach(([key, value]) => root.style.setProperty('--' + key, value));
    root.style.colorScheme = isDark ? 'dark' : 'light';
    root.dataset.rhinoTheme = isDark ? 'dark' : 'light';
    // Font names are data, never arbitrary CSS.
    root.style.setProperty('--ui-font', typeof value.font === 'string' && /^[\p{L}\p{N} _-]{1,80}$/u.test(value.font) ? '"' + value.font + '"' : '"Segoe UI"');
  };
  let palette;
  try { palette = JSON.parse(params.get('palette') || 'null'); } catch { /* Use system fallback outside Rhino. */ }
  const system = matchMedia('(prefers-color-scheme: dark)');
  const fallback = () => window.almondThemeReceive(params.get('theme') === 'dark' ? dark : params.get('theme') === 'light' ? light : system.matches ? dark : light);
  if (palette) window.almondThemeReceive(palette); else fallback();
  if (!palette && !params.has('theme')) system.addEventListener('change', fallback);
})();
