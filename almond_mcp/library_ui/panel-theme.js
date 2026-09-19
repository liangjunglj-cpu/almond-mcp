// Apply the host palette before the first paint; browser pages keep the archive style.
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
  const light = {paper:'#f0f0f0', ink:'#202020', control:'#e5e5e5', field:'#ffffff', line:'#b5b5b5', hover:'#d7e7f7'};
  const dark = {paper:'#333333', ink:'#eeeeee', control:'#414141', field:'#272727', line:'#656565', hover:'#4e5964'};
  window.almondThemeReceive = input => {
    const value = input && typeof input === 'object' ? input : {};
    const valid = v => typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v);
    const base = valid(value.paper) ? (luminance(value.paper) < .3 ? dark : light) : light;
    const palette = Object.fromEntries(Object.keys(base).map(k => [k, valid(value[k]) ? value[k] : base[k]]));
    // Custom Rhino themes occasionally contain unset or unreadable colour pairs.
    if (contrast(palette.paper, palette.ink) < 4.5) palette.ink = luminance(palette.paper) < .18 ? '#ffffff' : '#171717';
    for (const key of ['control', 'field', 'hover']) {
      if (contrast(palette[key], palette.ink) < 4.5) palette[key] = palette.paper;
    }
    let muted = mix(palette.paper, palette.ink, .7);
    if (contrast(muted, palette.paper) < 4.5) muted = palette.ink;
    const isDark = luminance(palette.paper) < .3;
    Object.entries({...palette, muted, panel:mix(palette.paper, palette.ink, .045),
      preview:isDark?'#a5a9ad':'#e2e3e4', 'preview-ink':'#252729',
      red:isDark?'#ff806a':'#b82f1c', 'diagram-member':palette.ink,
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
