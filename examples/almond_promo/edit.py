"""Almond promo edit: cybercore / neo-swiss, 1920x1080 @30 fps, 150 BPM grid (beat = 12 f, bar = 48 f).

python edit.py [--preview] [--from F --to F] [--stills f1,f2,...]
Sections (frames): 0 BOOT 0-96 | 1 GENERATE 96-480 | 2 LIBRARY 480-864 | 3 LIGHT+MATERIAL 864-1248 |
4 RENDER 1248-1536 | 5 WORLD 1536-1920 | 6 END 1920-2016
"""
import math, os, re, subprocess, sys, glob, json
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30          # layout (design) units
S = int(os.environ.get('PROMO_SCALE', '2'))   # 2 -> 3840x2160 output
PW, PH = W * S, H * S
BLW, BLH = 3840, 2160                 # Blender lookdev source frames
BEAT, BAR = 12, 48
TOTAL = 52 * BAR   # ends on the splat flythrough
WORK = r"C:\Users\liang\Documents\almond_promo"
FONTS = r"C:\Windows\Fonts"
RED = (233, 68, 43)
CYAN = (0, 229, 255)
MAG = (255, 43, 214)
WHITE = (240, 240, 236)
INK = (10, 10, 12)

S_BOOT, S_GEN, S_LIB, S_PHYS, S_LIGHT, S_REND, S_WORLD, S_GINKGO, S_END = 0, 96, 480, 864, 1440, 1728, 2112, 2496, 2784

_fonts = {}


def F(name, size):
    key = (name, size)
    if key not in _fonts:
        path = {'bold': 'arialbd.ttf', 'narrow': 'ARIALN.TTF', 'narrowb': 'ARIALNB.TTF', 'reg': 'arial.ttf',
                'din': 'bahnschrift.ttf', 'ocr': 'OCRAEXT.TTF', 'mono': 'consola.ttf', 'monob': 'consolab.ttf',
                'impact': 'impact.ttf'}[name]
        f = ImageFont.truetype(os.path.join(FONTS, path), size)
        if name == 'din':
            try:
                f.set_variation_by_name('Bold')
            except Exception:
                pass
        _fonts[key] = f
    return _fonts[key]


# ------------------------------------------------------------------ easing + utils
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def smooth(x): x = clamp(x); return x * x * (3 - 2 * x)
def ease_out(x, p=3): x = clamp(x); return 1 - (1 - x) ** p
def ease_in(x, p=3): x = clamp(x); return x ** p
def ease_io(x): x = clamp(x); return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2
def lerp(a, b, t): return a + (b - a) * t


def lerp_rect(r0, r1, t):
    return tuple(lerp(a, b, t) for a, b in zip(r0, r1))


def keyed(keys, t, ease=ease_io):
    """keys: [(t, value_tuple)], piecewise eased interpolation."""
    if t <= keys[0][0]: return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return lerp_rect(v0, v1, ease((t - t0) / max(1e-6, t1 - t0)))
    return keys[-1][1]


def view(src, rect, out=(W, H), interp=cv2.INTER_LINEAR):
    """Render source rect (x, y, w, h) (float) to an out-sized frame; rect aspect is forced to out aspect about its centre."""
    x, y, w, h = rect
    ow, oh = int(out[0] * S), int(out[1] * S)
    cx, cy = x + w / 2, y + h / 2
    if w / h > ow / oh: h = w * oh / ow
    else: w = h * ow / oh
    s = ow / w
    if s < 0.7:  # pre-shrink big sources to avoid aliasing
        k = max(1, int(0.9 / s))
        k = min(k, 4)
        if k > 1:
            src = cv2.resize(src, (src.shape[1] // k, src.shape[0] // k), interpolation=cv2.INTER_AREA)
            cx, cy, w, s = cx / k, cy / k, w / k, s * k
            h = w * oh / ow
    M = np.float32([[s, 0, ow / 2 - s * cx], [0, s, oh / 2 - s * cy]])
    if s > 1.02 and interp == cv2.INTER_LINEAR: interp = cv2.INTER_CUBIC
    return cv2.warpAffine(src, M, (ow, oh), flags=interp, borderMode=cv2.BORDER_CONSTANT, borderValue=(10, 10, 12))


_cache = {}


def load(path, size=None, px=None):
    key = (path, size, px)
    if key not in _cache:
        im = cv2.imread(path, cv2.IMREAD_COLOR)
        if im is None: raise FileNotFoundError(path)
        im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        tgt = px or ((int(size[0] * S), int(size[1] * S)) if size else None)
        if tgt and (im.shape[1], im.shape[0]) != tgt:
            up = tgt[0] > im.shape[1]
            im = cv2.resize(im, tgt, interpolation=cv2.INTER_CUBIC if up else cv2.INTER_AREA)
        if len(_cache) > 24: _cache.clear()
        _cache[key] = im
    return _cache[key]


# ------------------------------------------------------------------ FX
rng = np.random.default_rng(3)
YY, XX = np.mgrid[0:PH, 0:PW].astype(np.float32)
VIG = None


def rgb_split(img, px):
    if px == 0: return img
    px = int(px)
    out = img.copy()
    out[:, :, 0] = np.roll(img[:, :, 0], px, axis=1)
    out[:, :, 2] = np.roll(img[:, :, 2], -px, axis=1)
    return out


def glitch_blocks(img, seed, n=10, amp=120):
    r = np.random.default_rng(seed)
    out = img.copy()
    for _ in range(n):
        h = int(r.integers(6, 70)); y = int(r.integers(0, H - h))
        dx = int(r.integers(-amp, amp))
        out[y:y + h] = np.roll(out[y:y + h], dx, axis=1)
        if r.random() < 0.3:
            c = r.integers(0, 3); out[y:y + h, :, c] = 255 - out[y:y + h, :, c]
    return out


def flash(img, a, col=(255, 255, 255)):
    if a <= 0: return img
    return (img * (1 - a) + np.array(col) * a).astype(np.uint8)


def finish(img, f, glitch=0.0):
    return img  # user asked for no filter (grain, scanlines, vignette) and no glitch FX
    x = img.astype(np.float32)
    g = GRAIN[f % 6]
    g = cv2.resize(g, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]
    x = x * SCAN * VIG + g
    x = np.clip(x, 0, 255).astype(np.uint8)
    # glitch FX (RGB split / block displacement) removed at the user's request; `glitch` is ignored
    return x


# ------------------------------------------------------------------ typography layer
def _sp(pts):
    return [(x * S, y * S) for (x, y) in pts]


class Layer:
    """Overlay in layout units; everything is drawn natively at S x resolution (vector-sharp at 4K)."""
    def __init__(self):
        self.im = Image.new('RGBA', (PW, PH), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def text(self, xy, s, font='bold', size=40, fill=WHITE, alpha=1.0, anchor='la', track=0, reveal=1.0):
        if alpha <= 0 or not s: return
        if font == 'ocr':
            s = s.replace('·', '/').replace('→', '>').replace('×', 'x').replace('°', '').replace('—', '-')
        n = int(round(len(s) * clamp(reveal)))
        s = s[:n]
        if not s: return
        f = F(font, int(round(size * S)))
        col = (*fill, int(255 * clamp(alpha)))
        xy = (xy[0] * S, xy[1] * S); track = track * S
        if track == 0:
            self.d.text(xy, s, font=f, fill=col, anchor=anchor)
        else:
            x, y = xy
            total = sum(self.d.textlength(ch, font=f) + track for ch in s) - track
            if anchor[0] == 'r': x -= total
            elif anchor[0] == 'm': x -= total / 2
            for ch in s:
                self.d.text((x, y), ch, font=f, fill=col, anchor='l' + anchor[1])
                x += self.d.textlength(ch, font=f) + track

    def grad(self, h, a, w=W):
        hp = int(h * S)
        for y in range(0, hp, 2):
            self.d.rectangle((0, y, w * S, y + 1), fill=(*INK, int(255 * a * (1 - y / hp) ** 1.5)))

    def rect(self, box, fill=None, outline=None, width=1, alpha=1.0):
        a = int(255 * clamp(alpha))
        x0, y0, x1, y1 = [v * S for v in box]
        self.d.rectangle((x0, y0, max(x0, x1 - 1) if S > 1 else x1, max(y0, y1 - 1) if S > 1 else y1),
                         fill=(*fill, a) if fill else None, outline=(*outline, a) if outline else None, width=width * S)

    def line(self, pts, fill=WHITE, width=1, alpha=1.0):
        self.d.line(_sp(pts), fill=(*fill, int(255 * clamp(alpha))), width=width * S)

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.d.ellipse([v * S for v in box], fill=fill, outline=outline, width=width * S)

    def polygon(self, pts, fill=None, outline=None):
        self.d.polygon(_sp(pts), fill=fill, outline=outline)

    def brackets(self, box, L=26, fill=WHITE, width=2, alpha=1.0):
        x0, y0, x1, y1 = box
        for (x, y, dx, dy) in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
            self.line([(x, y), (x + dx * L, y)], fill, width, alpha)
            self.line([(x, y), (x, y + dy * L)], fill, width, alpha)

    def comp(self, img):
        base = Image.fromarray(img).convert('RGBA')
        base.alpha_composite(self.im)
        return np.asarray(base.convert('RGB'))


def tc(f):
    s = f / FPS
    return '%02d:%02d:%02d' % (int(s // 60), int(s % 60), f % FPS)


def hud(L, f, section, name, dark=True):
    """Persistent cyber frame: brackets, timecode, REC, section index."""
    a = 0.75
    L.brackets((28, 28, W - 28, H - 28), 34, WHITE, 2, a)
    L.text((52, H - 58), tc(f), 'ocr', 22, WHITE, a)
    L.text((230, H - 58), 'ALMOND//MCP', 'ocr', 22, RED, a)
    L.text((W - 52, H - 58), 'F %04d/%04d' % (f, TOTAL), 'ocr', 22, WHITE, a, anchor='ra')
    if (f // 15) % 2 == 0:
        L.ellipse((W - 128, 44, W - 112, 60), fill=(*RED, 230))
    L.text((W - 102, 42), 'REC', 'ocr', 20, WHITE, a)
    # section ticks along bottom
    x0, x1, y = 560, W - 560, H - 46
    L.line([(x0, y), (x1, y)], WHITE, 1, 0.35)
    for i, b in enumerate([S_GEN, S_LIB, S_PHYS, S_LIGHT, S_REND, S_WORLD]):
        x = x0 + (x1 - x0) * b / TOTAL
        L.line([(x, y - 6), (x, y + 6)], WHITE, 1, 0.5)
    xp = x0 + (x1 - x0) * f / TOTAL
    L.rect((xp - 3, y - 3, xp + 3, y + 3), fill=RED)


def section_title(L, t, num, title, sub, x=80, y=90, col=WHITE):
    """Neo-swiss header: huge red numeral + bold title + mono subtitle; animated in over ~10 frames."""
    k = ease_out(t / 10)
    if k <= 0: return
    L.text((x - 30 * (1 - k), y - 18), num, 'bold', 150, RED, k)
    L.text((x + 205, y + 14), title, 'bold', 64, col, k, track=2, reveal=clamp(t / 8))
    L.text((x + 208, y + 92), sub, 'ocr', 20, col, 0.85 * k, reveal=clamp((t - 6) / 18))
    L.rect((x + 205, y + 84, x + 205 + 520 * k, y + 87), fill=RED)


def slam(L, t, s, xy, size=140, font='bold', col=WHITE, anchor='la', track=0):
    """Hard in-cut word with a 3-frame overshoot."""
    if t < 0: return
    L.text(xy, s, font, size, col, clamp((t + 1) / 4), anchor=anchor, track=track)   # soft fade-in, no zoom pop


# ------------------------------------------------------------------ metadata panels (real Almond data)
PKG = "C:/Users/liang/AppData/Roaming/McNeel/Rhinoceros/packages/8.0/almondbridge"
PKG += "/" + open(PKG + "/manifest.txt").read().strip()   # active version (Rhino prunes the others)
ARCHIVE = PKG + "/archive/api/assets"
STAGE_SAMPLES = json.load(open(os.path.join(WORK, 'stage_samples.json'), encoding='utf-8'))
GREY = (150, 150, 158)


def meta_panel(L, box, title, rows, t, accent=RED, alpha=0.82, size=19, keyw=230, stagger=3):
    """Neo-swiss data card: accent rule, OCR title, mono key/value rows typed in."""
    x0, y0, x1, y1 = box
    L.rect(box, fill=INK, alpha=alpha)
    L.rect((x0, y0, x1, y0 + 3), fill=accent)
    L.text((x0 + 18, y0 + 14), title, 'ocr', 18, accent, reveal=t / 8)
    y = y0 + 48
    for i, (k, v) in enumerate(rows):
        r = clamp((t - 2 - i * stagger) / 5)
        if r <= 0: break
        L.text((x0 + 18, y), k, 'mono', size, GREY, r)
        L.text((x0 + 18 + keyw, y), v, 'mono', size, WHITE, 1.0, reveal=r)
        y += int(size * 1.5)


_pp = {}


def passport(asset_id):
    if asset_id not in _pp:
        a = json.load(open(os.path.join(ARCHIVE, asset_id + '.json'), encoding='utf-8'))
        d = a['dimensions_mm']; pv = a['provenance']; sha = pv['model_sha256']
        rg = pv.get('recorded_generation', {})
        _pp[asset_id] = [('asset_id', asset_id), ('license', a['license']),
                         ('dims_mm', '%d x %d x %d' % (d['width'], d['depth'], d['height'])),
                         ('sha256', sha[:10] + '...' + sha[-6:]),
                         ('mesh', (rg.get('mesh_model', '') or '').split(' (')[0] + '  ' + rg.get('generated_at', '')),
                         ('roles', ' / '.join({'plan': 'plan', 'section': 'section', 'elevation': 'elev', 'interior_axonometric': 'axo', 'interior_perspective': 'persp'}.get(r, r[:6]) for r in a['roles']))]
    return _pp[asset_id]


# ------------------------------------------------------------------ SOURCES
GEN = sorted(glob.glob(os.path.join(WORK, 'rhino_gen', 'f_*.jpg')))
SCREEN_CROP_Y = 90                # drop Rhino title bar + Windows taskbar -> 2560x1440
VP169 = (184, 300, 1831, 1030)     # Rhino viewport's central 16:9 in cropped coords == Blender camera frame
FULLUI = (0, 0, 2560, 1440)


def screen(path):
    im = load(path)
    return im[SCREEN_CROP_Y:SCREEN_CROP_Y + 1440]


# stage schedule of the build replay (frames of rhino_gen)
STAGES = [("ENVELOPE", 3), ("FLOORS", 28), ("PARTITIONS", 4), ("STAIR + GALLERY", 22), ("DETAILS", 10),
          ("KITCHEN", 8), ("BATHROOM", 6), ("STUDY + BEDROOM", 8), ("FURNITURE", 6), ("LIGHTING", 6),
          ("OBJECTS + GRAPHICS", 18)]
STAGE_OBJ = [3, 408, 7, 162, 135, 76, 54, 67, 24, 50, 468]
_st = []
c = 10
for i, (n, k) in enumerate(STAGES):
    _st.append((c, c + k + 1, i)); c += k + 1


def stage_at(idx):
    for a, b, i in _st:
        if a <= idx < b: return i, (idx - a) / max(1, (b - a - 1))
    return (len(STAGES) - 1, 1.0) if idx >= 10 else (-1, 0)


# ------------------------------------------------------------------ S0 BOOT
BOOT = ["> ALMOND_MCP v0.6.0 ........................ BOOT",
        "> RHINO 8 // ALMOND BRIDGE  127.0.0.1:5000 .. OK",
        "> GENERATED LIBRARY  57 OBJECTS / CC BY 4.0 . OK",
        "> METADATA  1,670/1,689 OBJECTS TAGGED ...... OK",
        "> BLENDER 5.1 // CYCLES OPTIX ............... OK",
        "> RENDER // WORLD PIPELINE .................. OK"]


def s_boot(t, f):
    img = np.full((PH, PW, 3), INK, np.uint8)
    # moving grid
    g = Layer()
    off = (t * 3) % 80
    for x in range(-80, W + 80, 80):
        g.line([(x + off, 0), (x + off, H)], (40, 40, 46), 1)
    for y in range(0, H, 80):
        g.line([(0, y), (W, y)], (40, 40, 46), 1)
    for i, s in enumerate(BOOT):
        st = 4 + i * 8
        g.text((110, 150 + i * 40), s, 'ocr', 26, RED if s.endswith('BOOT') else WHITE, 1.0, reveal=(t - st) / 6)
    if t >= 52:
        k = t - 52
        g.rect((110, 470, 110 + 150, 470 + 150), fill=RED, alpha=ease_out(k / 4))
        g.text((110 + 180, 440), 'ALMOND', 'bold', 210, WHITE, 1.0, track=-4)
        g.text((116 + 180, 668), 'AI-DRIVEN ARCHITECTURE  //  RHINO  ·  LIBRARY  ·  BLENDER  ·  RENDER  ·  WORLD', 'ocr', 22, WHITE, clamp((k - 6) / 8), reveal=(k - 6) / 20)
    hud(g, f, 0, 'BOOT')
    img = g.comp(img)
    gl = 0.9 if 52 <= t < 55 else (0.5 if t >= 90 else 0)
    return img, gl


# ------------------------------------------------------------------ S1 GENERATE (Rhino UI build replay)
def gen_index(t):
    if t < 24: return min(9, t // 3)
    nb = (384 - 36 - 24) / BEAT
    b = (t - 24) / BEAT
    k = math.floor(b) + smooth(min(1, (b % 1) * 1.8))
    return int(min(151, 10 + round(141 * min(1, k / nb))))


def s_gen(t, f):
    idx = gen_index(t)
    src = screen(GEN[idx])
    keys = [(0, FULLUI), (40, FULLUI), (170, (110, 200, 2050, 1153)), (300, (150, 250, 1920, 1080)), (383, VP169)]
    r = keyed(keys, t)
    bump = 1.0   # beat zoom-bumps removed (too strobing)
    cx, cy = r[0] + r[2] / 2, r[1] + r[3] / 2
    r = (cx - r[2] / bump / 2, cy - r[3] / bump / 2, r[2] / bump, r[3] / bump)
    img = view(src, r)
    L = Layer()
    # darken band under header for legibility
    L.grad(250, 0.7 * ease_out(t / 8))
    section_title(L, t, '01', 'GENERATE', 'RHINO 8  ·  ALMOND BRIDGE  ·  C# OVER MCP  ·  BUILD REPLAY')
    si, sp = stage_at(idx)
    if si >= 0:
        x0, y0 = W - 700, H - 250
        L.rect((x0, y0, W - 70, H - 90), fill=INK, alpha=0.78)
        L.rect((x0, y0, x0 + 6, H - 90), fill=RED)
        L.text((x0 + 28, y0 + 18), 'STAGE %02d/11' % (si + 1), 'ocr', 22, RED)
        L.text((x0 + 28, y0 + 50), STAGES[si][0], 'bold', 48 if len(STAGES[si][0]) < 14 else 40, WHITE, track=1)
        done = sum(STAGE_OBJ[:si]) + int(STAGE_OBJ[si] * sp)
        L.text((x0 + 28, y0 + 112), 'OBJECTS %05d   LAYER A07/%02d' % (done, si + 1), 'mono', 22, WHITE, 0.85)
        pw = (W - 70 - 28) - (x0 + 28)
        L.rect((x0 + 28, y0 + 142, x0 + 28 + pw, y0 + 146), fill=(70, 70, 76))
        L.rect((x0 + 28, y0 + 142, x0 + 28 + pw * (idx - 10) / 141, y0 + 146), fill=RED)
    # kinetic headline, bars 6-8 of the section
    if 192 <= t < 288:
        k = t - 192
        words = ['PROMPT', 'TO', 'PLAN', 'TO', 'BUILD']
        wi = min(len(words) - 1, k // 12)
        L.rect((80, 380, 80 + 900, 580), fill=INK, alpha=0.6)
        slam(L, k - wi * 12, words[wi], (110, 390), 150, 'bold', RED if words[wi] in ('PLAN', 'BUILD') else WHITE, track=-2)
        L.text((116, 548), '1,689 OBJECTS  ·  1,670 TAGGED  ·  54 MCP TOOLS', 'ocr', 22, WHITE, 0.9, reveal=k / 30)
    if si >= 0 and t >= 30:
        smp = STAGE_SAMPLES[si]
        o = smp[(t // 6) % len(smp)]
        done = sum(STAGE_OBJ[:si]) + int(STAGE_OBJ[si] * sp)
        rows = [('object', o['name'][:30]), ('id', o['id'][:8] + '...' + o['id'][-4:]),
                ('type', o['type'].upper() + '  %dx%dx%d mm' % (o['dx'], o['dy'], o['dz'])),
                ('Almond.Project', 'Atelier 07 / Urban duplex'), ('Almond.Source', (o['src'] or 'Original authored geometry')[:30]),
                ('tagged', '%s / 1,689' % format(int(done * 1670 / 1689), ','))]
        meta_panel(L, (80, H - 330, 820, H - 90), 'METADATA STREAM  //  ALMOND.* USER TEXT', rows, 30, stagger=0)
    hud(L, f, 1, 'GENERATE')
    img = L.comp(img)
    gl = 0.6 if t < 4 else (0.35 if (t % BAR) < 2 and t > 40 else 0)
    return img, gl


# ------------------------------------------------------------------ S2 LIBRARY (live placement recording)
LIBDIR = os.path.join(WORK, 'libsec')
# timeline-local frame -> source seconds in lib_rec.mp4 (drops land on beats)
LIB_ANCH = [(0, 1.8), (60, 8.75), (72, 10.1), (120, 17.65), (132, 19.4), (180, 27.1), (192, 29.0),
            (240, 36.55), (264, 43.45), (276, 45.4), (324, 53.3), (336, 55.8), (348, 62.2), (384, 72.5)]
DROP_IDS = ['gen-sofa-3-seat-1', 'gen-folded-throw-1', 'gen-armchair-bent-birch-webbed-1', 'gen-lounge-chair-leather-plywood-1',
            'gen-ottoman-leather-plywood-1', 'gen-dining-chair-1']
DROPS = [(60, '022', 'SOFA', '3-SEAT  ·  FABRIC'), (120, '050', 'THROW', 'LOOSELY FOLDED  ·  RED WOOL'),
         (180, '032', 'ARMCHAIR', 'BENT BIRCH  ·  LINEN WEBBING'), (240, '035', 'LOUNGE CHAIR', 'LEATHER  ·  PLYWOOD SHELLS'),
         (264, '036', 'OTTOMAN', 'LEATHER  ·  PLYWOOD'), (324, '024', 'DINING CHAIR ×6', 'TIMBER  ·  ARMLESS')]


def lib_src_time(t):
    for (a, sa), (b, sb) in zip(LIB_ANCH, LIB_ANCH[1:]):
        if t <= b: return sa + (sb - sa) * (t - a) / (b - a)
    return LIB_ANCH[-1][1]


def prep_library():
    """Decode lib_rec.mp4 once; blend the source frames that fall in each timeline frame (motion blur)."""
    os.makedirs(LIBDIR, exist_ok=True)
    if len(glob.glob(os.path.join(LIBDIR, '*.jpg'))) >= 384: return
    cap = cv2.VideoCapture(os.path.join(WORK, 'lib_rec.mp4'))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fi, cur = -1, None
    for t in range(384):
        s0, s1 = lib_src_time(t), lib_src_time(t + 1)
        a, b = int(s0 * fps), max(int(s0 * fps) + 1, int(s1 * fps))
        idxs = np.linspace(a, b - 1, min(5, b - a)).astype(int)
        acc = None; n = 0
        for want in idxs:
            while fi < want:
                ok, fr = cap.read()
                if not ok: break
                fi += 1; cur = fr
            acc = cur.astype(np.float32) if acc is None else acc + cur
            n += 1
        out = (acc / n).astype(np.uint8)[SCREEN_CROP_Y:SCREEN_CROP_Y + 1440]
        cv2.imwrite(os.path.join(LIBDIR, 'l_%03d.jpg' % t), out, [cv2.IMWRITE_JPEG_QUALITY, 94])


LIVING = (560, 610, 860, 664)          # living + dining zone in cropped screen coords (~2.2x)
PANEL = (2000, 250, 560, 1163)          # Almond panel column


PREVIEW = PKG + "/archive/files/generated/previews/gen-sofa-3-seat-1.png"


def iso_box(L, ox, oy, w, d, h, k=14, a=1.0):
    """Tiny isometric box (w along +x/right-down, d along left-down, h up) with three shaded faces."""
    cx, sx = 0.87 * k, 0.5 * k
    p = lambda x, y, z: (ox + (x - y) * cx, oy + (x + y) * sx - z * k)
    top = [p(0, 0, h), p(w, 0, h), p(w, d, h), p(0, d, h)]
    right = [p(w, 0, 0), p(w, d, 0), p(w, d, h), p(w, 0, h)]
    left = [p(0, d, 0), p(w, d, 0), p(w, d, h), p(0, d, h)]
    for poly, c in ((left, (120, 120, 126)), (right, (160, 160, 166)), (top, (205, 205, 210))):
        L.polygon(poly, fill=(*c, int(255 * a)), outline=(*INK, int(255 * a)))


def explainer(L, t):
    """Plain-language card: why generating furniture through a conventional MCP is hard, and what Almond does."""
    x0, y0, x1, y1 = 80, 270, 800, 780
    if t < 6 or t >= 116: return
    a = clamp((t - 6) / 6) * clamp((116 - t) / 6)
    L.rect((x0, y0, x1, y1), fill=INK, alpha=0.84 * a)
    almond = t >= 64
    k = t - (64 if almond else 6)
    L.rect((x0, y0, x1, y0 + 4), fill=(CYAN if almond else RED), alpha=a)
    L.text((x0 + 24, y0 + 18), 'ALMOND MCP' if almond else 'CONVENTIONAL MCP', 'ocr', 20, CYAN if almond else RED, a)
    head = 'PLACE A REAL, MEASURED MODEL' if almond else 'THE AI BUILDS A SOFA FROM BOXES'
    L.text((x0 + 24, y0 + 50), head, 'bold', 34, WHITE, a, reveal=k / 10)
    rows = (['1 call: search the library, drop the asset', 'measured 2346 x 983 x 850 mm', 'real designed mesh + material slots',
             'passport: source, SHA-256, CC BY 4.0'] if almond else
            ['dozens of box and cylinder calls in code', 'dimensions guessed, proportions drift', 'blocky result, slow, heavy on tokens',
             'no materials, no source, no licence'])
    for i, r in enumerate(rows):
        L.text((x0 + 24, y0 + 112 + i * 38), ('+ ' if almond else '- ') + r, 'mono', 21, WHITE, a * clamp((k - 4 - i * 4) / 5))
    # visual: blocky primitive sofa vs the library thumbnail
    vx, vy = x0 + 300, y0 + 350
    if not almond:
        n = int(clamp((k - 2) / 30) * 6)
        parts = [(0, 0, 0, 7, 3, 1.2), (0, 2.2, 1.2, 7, 0.8, 2.0), (0, 0, 1.2, 0.8, 3, 1.0), (6.2, 0, 1.2, 0.8, 3, 1.0),
                 (0.8, 0, 1.2, 2.8, 2.2, 0.5), (3.6, 0, 1.2, 2.6, 2.2, 0.5)]
        for (bx, by, bz, w, d, h) in parts[:n]:
            ox = vx + (bx - by) * 0.87 * 24; oy = vy + (bx + by) * 0.5 * 24 - bz * 24
            iso_box(L, ox, oy, w, d, h, 24, a)
    return almond


def s_lib(t, f):
    src = load(os.path.join(LIBDIR, 'l_%03d.jpg' % t))
    L = Layer()
    if t < 340:
        k = ease_out(t / 14)
        left = view(src, LIVING if t > 14 else lerp_rect(VP169, LIVING, k), (1400, 1080))
        right = view(src, PANEL, (520, 1080))
        img = np.concatenate([left, right], 1)
        L.rect((1398, 0, 1402, H), fill=RED)
        L.rect((1402, 0, W, 64), fill=INK, alpha=0.8)
        L.text((1430, 20), 'ALMOND LIBRARY // LIVE PANEL', 'ocr', 20, RED)
    else:
        k = ease_io((t - 340) / 30)
        img = view(src, lerp_rect(LIVING, VP169, k))
    L.grad(250, 0.65, 1398 if t < 340 else W)
    almond_card = explainer(L, t)
    section_title(L, t, '02', 'LIBRARY', '57 OBJECTS  ·  PROVENANCE PASSPORT ON EVERY BLOCK  ·  SEARCH → PLACE → DROP')
    # drop labels
    for i, (df, num, name, sub) in enumerate(DROPS):
        nxt = DROPS[i + 1][0] if i + 1 < len(DROPS) else 348
        if df - 2 <= t < nxt:
            k = t - df
            L.rect((80, H - 300, 80 + 760, H - 110), fill=INK, alpha=0.82)
            L.rect((80, H - 300, 92, H - 110), fill=RED)
            L.text((116, H - 288), 'PLACED  #%s   %02d/24' % (num, min(24, [1, 2, 3, 4, 5, 11][i])), 'ocr', 22, RED)
            slam(L, k, name, (112, H - 258), 84, 'bold', WHITE, track=1)
            L.text((116, H - 158), sub, 'ocr', 22, WHITE, 0.9, reveal=k / 10)
            if t < 340:
                meta_panel(L, (1410, 836, 1910, 1070), 'ALMOND.PASSPORT  //  SCHEMA V1', passport(DROP_IDS[i]), k + 2,
                           size=16, keyw=110, stagger=2)
    if t >= 348:
        k = t - 348
        L.rect((80, H - 300, 80 + 760, H - 110), fill=INK, alpha=0.82)
        L.rect((80, H - 300, 92, H - 110), fill=RED)
        L.text((116, H - 288), 'PLACED  24/24', 'ocr', 22, RED)
        slam(L, k, '+ 13 MORE', (112, H - 258), 84, 'bold', WHITE)
        L.text((116, H - 158), 'BED · PENDANTS · BATH · BIKE · TROLLEY', 'ocr', 22, WHITE, 0.9, reveal=k / 10)
    hud(L, f, 2, 'LIBRARY')
    img = L.comp(img)
    if almond_card:   # library thumbnail of the actual asset inside the explainer card
        a = clamp((t - 66) / 6) * clamp((116 - t) / 6)
        pv = cv2.imread(PREVIEW, cv2.IMREAD_UNCHANGED)
        n = 260 * S
        pv = cv2.resize(pv, (n, n), interpolation=cv2.INTER_CUBIC)
        al = (pv[..., 3:4] / 255.0) if pv.shape[2] == 4 else np.ones((n, n, 1))
        th = cv2.cvtColor(pv[..., :3], cv2.COLOR_BGR2RGB) * al + np.array([196, 198, 204]) * (1 - al)
        y, x = (270 + 245) * S, (80 + 230) * S
        img = img.copy()
        img[y:y + n, x:x + n] = (img[y:y + n, x:x + n] * (1 - a) + th * a).astype(np.uint8)
    gl = 0.6 if t < 4 else (0.45 if any(0 <= t - d[0] < 2 for d in DROPS) else 0)
    return img, gl


# ------------------------------------------------------------------ S3 PHYSICS (Karamba3D live analysis in Rhino)
# 12 bars: section A-A physics OFF (0-96) -> ON (96-192) -> camera move into the axon (192-240) ->
# Almond iterates the section (240-336) -> erection stages verified (336-384) -> side-by-side impact (384-576).
PHYS = os.path.join(WORK, 'phys')
SECT = os.path.join(WORK, 'section')
IMPACT = os.path.join(WORK, 'impact')
PH_CROP = (138.2, 79.3, 3563.8, 2004.6)   # ViewCapture 4K -> the screen viewport's VP169 framing (SIFT-registered)
PH_FULL = (0.0, 0.0, 3840.0, 2160.0)
PH_STATES = {s['name']: s for s in json.load(open(os.path.join(WORK, 'phys_states.json')))}


def _report(path):
    out = {}
    for ln in open(path, encoding='utf-8'):
        if '\t' in ln:
            n, j = ln.rstrip('\n').split('\t', 1)
            r = {}
            # rows are truncated at 300 chars; the headline numbers come first, per-element keys repeat later
            for k, v in re.findall(r'"(status|max_displacement_mm|deflection_limit_mm|max_utilization)":"?([\w.]+)"?', j):
                r.setdefault(k, v if k == 'status' else float(v))
            out[n] = r
    return out


PH_RES = _report(os.path.join(PHYS, 'report.tsv'))
PH_RES.update(_report(os.path.join(SECT, 'report.tsv')))
IM_RES = _report(os.path.join(IMPACT, 'report.tsv'))
GREEN = (40, 220, 90)
SEC_LOADS = (0, 25, 50, 75, 100, 125, 150)
PH_TL = ([(0, 'sec_off_0'), (24, 'sec_off_1'), (44, 'sec_off_2'), (60, 'sec_off_3')] +
         [(96, 'sec_stage1'), (108, 'sec_stage2'), (120, 'sec_stage3')] +
         [(132 + 8 * i, 'sec_load%03d' % q) for i, q in enumerate(SEC_LOADS)] +
         [(192, 'tr')] +
         [(240, 'fix_0'), (264, 'fix_1'), (288, 'fix_2'), (312, 'fix_3')] +
         [(336, 'ok_stage1'), (344, 'ok_stage2'), (352, 'ok_stage3'), (360, 'ok_stage4'), (368, 'ok_final')] +
         [(384, 'impact')])
PH_LOG = [(240, '> visualize_structure(load_kn=150)', 'FAIL   d 183.0 mm   u 3.59'),
          (264, '> resize   CHS 139.7 x 5.0', 'FAIL   d  82.1 mm   u 1.91'),
          (288, '> resize   CHS 168.3 x 6.3', 'FAIL   d  38.6 mm   u 1.07'),
          (312, '> resize   CHS 193.7 x 8.0', 'PASS   d  20.9 mm   u 0.66')]
# the section frames reuse the axon states' requests (same members, loads and sections) for the readout
SEC_REQ = {'sec_stage1': 'on_stage1', 'sec_stage2': 'on_stage3', 'sec_stage3': 'on_stage4'}
SEC_REQ.update({'sec_load%03d' % q: 'on_load%03d' % q for q in SEC_LOADS})
IM_LOADS = [(384, 0), (408, 50), (432, 100), (456, 150)]
IM_SRC = (380, 150, 1180, 700)      # layout-space crop of the axon for each half


def ramp(u):
    stops = [(30, 70, 255), (0, 210, 255), (40, 220, 90), (255, 220, 0), (240, 40, 30)]
    x = clamp(u) * 4
    i = min(3, int(x))
    fr = x - i
    return tuple(int(a + (b - a) * fr) for a, b in zip(stops[i], stops[i + 1]))


def ph_state(t):
    return [n for (t0, n) in PH_TL if t0 <= t][-1]


def ph_img(name, crop=PH_CROP):
    return view(load(os.path.join(PHYS, name + '.jpg')), crop)


def karamba_panel(L, name, a, y0=250):
    """Live FEA readout; every number is the bridge's structure_view reply for that frame."""
    q = PH_STATES[SEC_REQ.get(name, name)].get('req', {})
    r = PH_RES.get(name, {})
    x0, x1, y1 = 1390, 1840, y0 + 390
    ok = r.get('status') == 'pass'
    acc = GREEN if ok else RED
    title = q.get('title', '')
    sub = title.split('·', 1)[1].strip() if '·' in title else 'SERVICE CHECK'
    if name.startswith('sec_'):
        sub = 'SECTION A-A  ·  ' + sub
    L.rect((x0, y0, x1, y1), fill=INK, alpha=0.86 * a)
    L.rect((x0, y0, x0 + 6, y1), fill=acc, alpha=a)
    L.text((x0 + 26, y0 + 18), 'KARAMBA3D  //  LIVE FEA', 'ocr', 18, acc, a)
    L.text((x0 + 26, y0 + 46), sub[:40], 'ocr', 15, WHITE, 0.8 * a)
    L.text((x0 + 26, y0 + 82), 'MAX DEFLECTION', 'ocr', 16, GREY, a)
    L.text((x0 + 26, y0 + 102), '%.1f mm' % r.get('max_displacement_mm', 0), 'bold', 62, WHITE, a)
    L.text((x1 - 24, y0 + 78), 'PASS' if ok else 'FAIL', 'bold', 40, acc, a, anchor='ra')
    util = r.get('max_utilization', 0)
    rows = [('limit L/250', '%.1f mm' % r.get('deflection_limit_mm', 24.8)),
            ('utilization', '%.2f' % util),
            ('load', '%d kN + self weight' % round(q.get('load_kn', 0))),
            ('section', 'CHS %.1f x %.1f' % (q.get('beam_diameter_mm', 0), q.get('beam_wall_mm', 0)))]
    for i, (kk, v) in enumerate(rows):
        y = y0 + 190 + i * 30
        L.text((x0 + 26, y), kk, 'mono', 19, GREY, a)
        L.text((x0 + 190, y), v, 'mono', 19, (255, 120, 100) if kk == 'utilization' and util > 1 else WHITE, a)
    by = y0 + 322
    for i in range(0, 400, 2):
        L.rect((x0 + 26 + i, by, x0 + 28 + i, by + 12), fill=ramp(i / 400), alpha=a)
    u = clamp(util)
    L.rect((x0 + 24 + 400 * u, by - 6, x0 + 28 + 400 * u, by + 18), fill=WHITE, alpha=a)
    L.text((x0 + 26, by + 24), 'UTILIZATION  0', 'ocr', 14, GREY, a)
    L.text((x0 + 426, by + 24), '>= 1.0', 'ocr', 14, GREY, a, anchor='ra')


def ph_card(L, t, x0, y0, head, rows, acc, t0, t1, w=660, size=20):
    if not (t0 <= t < t1): return
    k = t - t0
    a = clamp(k / 6) * clamp((t1 - t) / 6)
    h = 112 + len(rows) * int(size * 1.8)
    L.rect((x0, y0, x0 + w, y0 + h), fill=INK, alpha=0.84 * a)
    L.rect((x0, y0, x0 + w, y0 + 4), fill=acc, alpha=a)
    L.text((x0 + 24, y0 + 16), head[0], 'ocr', 19, acc, a)
    L.text((x0 + 24, y0 + 46), head[1], 'bold', 30, WHITE, a, reveal=k / 10)
    for i, r in enumerate(rows):
        L.text((x0 + 24, y0 + 104 + i * int(size * 1.8)), r, 'mono', size, WHITE, a * clamp((k - 4 - i * 4) / 5))


def physics_switch(L, on, a):
    sx, sy = 1390, 180
    L.rect((sx, sy, sx + 450, sy + 52), fill=INK, alpha=0.86 * a)
    L.text((sx + 22, sy + 14), 'PHYSICS', 'ocr', 22, WHITE, a)
    L.rect((sx + 190, sy + 12, sx + 290, sy + 40), fill=(RED if on else (70, 70, 76)), alpha=a)
    kx = sx + 262 if on else sx + 194
    L.rect((kx, sy + 15, kx + 24, sy + 37), fill=WHITE, alpha=a)
    L.text((sx + 310, sy + 12), 'ON' if on else 'OFF', 'bold', 26, RED if on else GREY, a)


def section_tag(L, t, a):
    """Drawing label under the cut, like a sheet annotation."""
    L.text((80, 912), 'SECTION A-A', 'bold', 30, WHITE, a)
    L.text((300, 920), 'y = 5.00 m  ·  CUT THROUGH THE MID COLUMN  ·  1:100', 'ocr', 18, WHITE, 0.85 * a)
    L.rect((80, 950, 80 + 1280 * clamp(t / 30), 952), fill=RED, alpha=a)


def impact_half(L, img, x0, name, key, t, good):
    """One side of the comparison: framed axon crop + key figures."""
    res = IM_RES.get(name, {})
    acc = GREEN if good else RED
    w = 900
    L.rect((x0, 170, x0 + w, 174), fill=acc)
    L.text((x0, 186), 'WITH ALMOND + KARAMBA3D' if good else 'WITHOUT SIMULATION', 'bold', 34, WHITE)
    L.text((x0 + w, 196), 'CHS 193.7 x 8.0' if good else 'CHS 114.3 x 4.0  ·  AS DRAWN', 'ocr', 18, acc, anchor='ra')
    L.text((x0 + 12, 776), 'deformation shown x5  ·  same load, same model', 'ocr', 14, WHITE, 0.8)
    d = res.get('max_displacement_mm', 0)
    ok = res.get('status') == 'pass'
    L.text((x0 + w - 12, 704), 'PASS' if ok else 'FAIL', 'bold', 40, GREEN if ok else RED, anchor='ra')
    rows = ([('MAX SAG', '%.1f mm' % d), ('SPAN / SAG', 'L/%d' % round(6200 / max(d, 0.1))),
             ('UTILIZATION', '%d %%' % round(100 * res.get('max_utilization', 0))),
             ('STEEL', '2.09 t' if good else '0.62 t'),
             ('FOUND', 'in design  ·  1.5 s solve' if good else 'after it is built')])
    k = t - 456
    for i, (kk, v) in enumerate(rows):
        a = clamp((k - i * 5) / 6) if i >= 3 else 1.0
        y = 812 + i * 38
        L.text((x0, y), kk, 'ocr', 18, GREY, a)
        L.text((x0 + 230, y - 4), v, 'bold', 28, acc if i < 3 or i == 4 else WHITE, a)


def s_phys(t, f):
    name = ph_state(t)
    L = Layer()
    fade = clamp((564 - t) / 12)
    if name == 'impact':
        # side-by-side: the same house under the same occupancy load, framed as built without / with simulation
        li = [q for (t0, q) in IM_LOADS if t0 <= t][-1]
        img = np.full((PH, PW, 3), 22, np.uint8)
        for side, x0 in (('without', 30), ('with', 990)):
            src = load(os.path.join(IMPACT, '%s_%03d.jpg' % (side, li)))
            crop = (PH_CROP[0] + IM_SRC[0] * PH_CROP[2] / W, PH_CROP[1] + IM_SRC[1] * PH_CROP[3] / H,
                    IM_SRC[2] * PH_CROP[2] / W, IM_SRC[3] * PH_CROP[3] / H)
            tile = view(src, crop, (900, 534))
            y = 232 * S
            img[y:y + tile.shape[0], x0 * S:x0 * S + tile.shape[1]] = tile
        k = t - 384
        if k < 12:   # the axon splits into the two halves
            img = (img * smooth(k / 12) + ph_img('ok_final') * (1 - smooth(k / 12))).astype(np.uint8)
        for side, x0 in (('without', 30), ('with', 990)):
            impact_half(L, img, x0, '%s_%03d' % (side, li), side, t, side == 'with')
        L.rect((955, 170, 957, 1000), fill=WHITE, alpha=0.35)
        L.text((W / 2, 72), 'BEFORE THE HOUSE IS BUILT', 'bold', 54, WHITE, anchor='ma', track=2)
        if t < 516:
            L.text((W / 2, 138), 'OCCUPANCY LOAD  %3d kN  +  SELF WEIGHT' % li, 'ocr', 22, RED, anchor='ma')
        else:   # the one-line takeaway replaces the load ticker
            L.text((W / 2, 138), '+1.47 t OF STEEL, DECIDED BEFORE A SINGLE MEMBER IS ORDERED', 'ocr', 22, WHITE,
                   clamp((t - 516) / 8), anchor='ma')
        hud(L, f, 3, 'PHYSICS')
        img = L.comp(img)
        if t >= 556:   # back to the clean model for the Blender look-dev
            m = smooth((t - 556) / 20)
            img = (img * (1 - m) + ph_img('off_00') * m).astype(np.uint8)
        return img, 0

    if name == 'tr':   # camera move: parallel section -> promo axon, crop eases to the VP169 framing
        k = min(36, t - 192)
        e = ease_io(k / 36)
        img = view(load(os.path.join(SECT, 'tr_%02d.jpg' % k)), lerp_rect(PH_FULL, PH_CROP, e))
        if t >= 228:   # drop the clipping plane: cut axon -> full axon, same solve
            m = smooth((t - 228) / 12)
            img = (img * (1 - m) + ph_img('on_load150') * m).astype(np.uint8)
    elif name.startswith('sec_'):
        img = view(load(os.path.join(SECT, name + '.jpg')), PH_FULL)
    else:
        img = ph_img(name)
    L.grad(250, 0.65)
    section_title(L, t, '03', 'PHYSICS', 'KARAMBA3D FEA  ·  LIVE INSIDE THE MCP LOOP  ·  SECTION  >  AXON  >  ITERATE')
    on = t >= 96
    physics_switch(L, on, fade)
    if name.startswith('sec_'):
        section_tag(L, t, clamp(t / 8))
    if not on:
        n = {'sec_off_0': 0, 'sec_off_1': 1, 'sec_off_2': 2, 'sec_off_3': 3}[name]
        a = clamp((t - 4) / 6)
        L.rect((1390, 250, 1840, 400), fill=INK, alpha=0.86 * a)
        L.rect((1390, 250, 1396, 400), fill=GREY, alpha=a)
        L.text((1416, 268), 'GEOMETRY ONLY  ·  FRAME LINE A-A', 'ocr', 16, GREY, a)
        L.text((1416, 296), '%d / 3' % n, 'bold', 64, WHITE, a)
        L.text((1416, 372), 'MEMBERS  ·  CHS 114.3 x 4.0', 'ocr', 16, WHITE, 0.8 * a)
        ph_card(L, t, 1390, 420, ('CONVENTIONAL MCP', 'LINES, NOT A STRUCTURE'),
                ['- no loads, no stiffness', '- looks buildable in section', '- nothing says the floor', '  will sag'],
                GREY, 14, 96, w=450, size=18)
    else:
        karamba_panel(L, name if name != 'tr' else 'on_load150', clamp((t - 96) / 4) * fade)
        if 96 <= t < 192:
            ph_card(L, t, 1390, 660, ('ALMOND MCP  //  PHYSICS ON', 'SOLVED AS IT GOES UP'),
                    ['+ Karamba3D FEA in the bridge', '+ every erection stage solved', '+ then the 150 kN load ramp'],
                    RED, 100, 190, w=450, size=18)
        if 192 <= t < 240:
            a = clamp((t - 196) / 6) * clamp((240 - t) / 6)
            L.rect((80, 300, 700, 380), fill=INK, alpha=0.84 * a)
            L.text((104, 316), 'SAME SOLVE  //  SECTION  >  AXON', 'ocr', 19, RED, a)
            L.text((104, 344), 'the cut line is one of 20 members', 'mono', 19, WHITE, a)
        if 240 <= t < 336:
            x0, y0 = 80, 300
            a = clamp((t - 240) / 5) * clamp((336 - t) / 6)
            L.rect((x0, y0, x0 + 700, y0 + 300), fill=INK, alpha=0.86 * a)
            L.rect((x0, y0, x0 + 700, y0 + 4), fill=CYAN, alpha=a)
            L.text((x0 + 24, y0 + 16), 'ALMOND AGENT  //  ITERATE UNTIL IT STANDS', 'ocr', 19, CYAN, a)
            for i, (t0, cmd, res) in enumerate(PH_LOG):
                if t < t0: break
                kk = t - t0
                y = y0 + 58 + i * 52
                L.text((x0 + 24, y), cmd, 'mono', 21, WHITE, a, reveal=kk / 8)
                L.text((x0 + 44, y + 25), res, 'monob', 19, GREEN if res.startswith('PASS') else RED, a * clamp((kk - 8) / 3))
            L.text((x0 + 24, y0 + 268), 'lightest passing section  ·  no human in the loop', 'ocr', 16, WHITE, a * clamp((t - 320) / 6))
        ph_card(L, t, 80, 300, ('VERIFIED  //  EVERY ERECTION STAGE', 'CHECKED AS IT WOULD BE BUILT'),
                ['+ columns + void-edge beam  u 0.25', '+ edge beams               u 0.43',
                 '+ joists                   u 0.51', '+ stringer, complete       u 0.66'], GREEN, 338, 384, w=660)
    hud(L, f, 3, 'PHYSICS')
    img = L.comp(img)
    return img, 0


# ------------------------------------------------------------------ S4 LIGHT + MATERIAL (Blender)
BL = os.path.join(WORK, 'blender')
SWEEP = sorted(glob.glob(os.path.join(BL, 'sweep', 's_*.png')))
LOOKS = [(156, 'look_noon', 'LIGHT 02', 'NOON'), (180, 'look_clay', 'MAT 01', 'CLAY'),
         (204, 'look_graphite', 'MAT 02', 'GRAPHITE'), (228, 'look_swiss_red', 'MAT 03', 'SWISS RED'),
         (252, 'look_bluehour_off', 'LIGHT 03', 'BLUE HOUR'), (264, 'look_bluehour_on', 'LIGHT 03', 'LAMPS ON'),
         (288, 'look_neon_night', 'LIGHT 04', 'NEON'), (336, 'look_chrome_neon', 'MAT 04', 'CHROME')]


def bl_img(name):
    for p in (os.path.join(BL, name + '_3840.png'), os.path.join(BL, name + '_2560.png'), os.path.join(BL, 'look_golden_3840.png')):
        if os.path.exists(p): return load(p, px=(BLW, BLH))
    raise FileNotFoundError(name)


def push(t, total=384):
    """slow continuous push-in across the Blender section (same shot, creeping closer)."""
    s = 1.0 + 0.10 * (t / total)
    w, h = BLW / s, BLH / s
    return (BLW / 2 - w / 2, BLH * 740 / 1440 - h / 2, w, h)


def s_light(t, f):
    L = Layer()
    if t < 156:
        if SWEEP:
            i = min(len(SWEEP) - 1, max(0, (t - 12) // 2))
            src = load(SWEEP[i], px=(BLW, BLH))
        else:
            src = bl_img('look_golden')
        img = view(src, push(t))
        if t < 14:  # render-scan wipe from the Rhino viewport
            rh = view(load(os.path.join(LIBDIR, 'l_383.jpg')), VP169)
            yline = int(H * ease_io(t / 13))
            img = img.copy(); img[yline * S:] = rh[yline * S:]
            L.rect((0, yline - 2, W, yline + 2), fill=RED)
            L.rect((0, yline - 30, W, yline - 2), fill=RED, alpha=0.18)
        tt = clamp((t - 12) / 144)
        az, el = 95 + 170 * tt, 8 + 52 * math.sin(math.pi * tt)
        hours = 6.5 + 12 * tt
        L.rect((W - 560, H - 250, W - 70, H - 90), fill=INK, alpha=0.75)
        L.rect((W - 560, H - 250, W - 554, H - 90), fill=RED)
        L.text((W - 530, H - 232), 'SUN STUDY  //  CYCLES', 'ocr', 22, RED)
        L.text((W - 530, H - 198), '%02d:%02d' % (int(hours), int(hours % 1 * 60)), 'bold', 64, WHITE)
        L.text((W - 530, H - 124), 'AZ %03d°   EL %02d°' % (az, el), 'mono', 24, WHITE, 0.9)
        name = None
    else:
        cur = [lk for lk in LOOKS if lk[0] <= t][-1]
        src = bl_img(cur[1])
        img = view(src, push(t))
        k = t - cur[0]
        L.rect((W - 560, H - 250, W - 70, H - 90), fill=INK, alpha=0.75)
        L.rect((W - 560, H - 250, W - 554, H - 90), fill=RED)
        L.text((W - 530, H - 232), cur[2] + '  //  LOOKDEV', 'ocr', 22, RED)
        slam(L, k, cur[3], (W - 530, H - 198), 64, 'bold', WHITE)
        L.text((W - 530, H - 124), 'SAME CAMERA  ·  NEW %s' % ('LIGHT' if cur[2].startswith('LIGHT') else 'MATERIAL'), 'mono', 22, WHITE, 0.9)
        # swatch strip of all looks
        for j, lk in enumerate(LOOKS):
            x = W - 560 + j * 58
            L.rect((x, H - 80, x + 50, H - 72), fill=RED if lk is cur else (90, 90, 96))
    if 16 <= t < 156:
        meta_panel(L, (80, H - 330, 900, H - 90), 'EXPORT_ASSET_CONTRACT  >  BLENDER', [
            ('mesh parts', '1,707  (3,139,528 tris, no decimation)'), ('custom props', 'rhino_id / almond_asset_id / source_instance'),
            ('materials', '.almond.json material_id map'), ('camera', 'Rhino frustum 50.47 deg hfov, 1:1'),
            ('provenance', '15 asset passports carried over')], t - 16, keyw=190)
    elif t >= 156:
        cur = [lk for lk in LOOKS if lk[0] <= t][-1]
        meta_panel(L, (80, H - 250, 760, H - 90), 'LOOKDEV  //  SAME GEOMETRY', [
            ('look', cur[3].lower()), ('engine', 'Cycles / OptiX / 64 spp / AgX'),
            ('geometry', 'unchanged: 1,707 parts')], 20, keyw=150)
    L.grad(250, 0.6)
    section_title(L, t, '04', 'LIGHT + MATERIAL', 'BLENDER 5.1  ·  ONE CAMERA  ·  NINE LOOKS  ·  SUN STUDY')
    hud(L, f, 4, 'LIGHT')
    img = L.comp(img)
    cut = t >= 156 and any(0 <= t - lk[0] < 2 for lk in LOOKS)
    gl = 0.6 if 12 <= t < 15 else (0.5 if cut else 0)
    if t >= 264 and t < 276 and (t - 264) in (0, 1, 3, 6):  # lamp flicker
        pass
    return img, gl


# ------------------------------------------------------------------ S4 RENDER collage
HF = os.path.join(WORK, 'hf')
INT = os.path.join(WORK, 'interior')
# living-room camera 01: model side (Rhino viewport / clay / Cycles) vs photoreal side, all registered to one camera
PASSES = [('aligned4k/rhino_living.png', 'photo_golden_a', 'RHINO VIEWPORT', 'GOLDEN HOUR'),
          ('../blender/int_clay_3840.png', 'photo_morning', 'CLAY MASSING', 'OVERCAST MORNING'),
          ('../blender/int_bluehour_on_3840.png', 'photo_bluehour', 'BLENDER CYCLES', 'BLUE HOUR'),
          ('model_golden_4k.png', 'photo_neon', 'BLENDER CYCLES', 'NEON RAIN')]
ALIGN = json.load(open(os.path.join(INT, 'aligned', 'report.json')))
ALDIR = 'aligned4k' if os.path.isdir(os.path.join(INT, 'aligned4k')) else 'aligned'


def model_img(i, size=(W, H)):
    return load(os.path.normpath(os.path.join(INT, PASSES[i][0])), size)


def photo_img(i, size=(W, H)):
    return load(os.path.join(INT, ALDIR, PASSES[i][1] + '.png'), size)


def s_render(t, f):
    L = Layer()
    if t < 96:            # pass 1: Rhino viewport -> photoreal, vertical slices then before/after divider
        a, b = model_img(0), photo_img(0); pi = 0
        if t < 48:
            n = 12; img = a.copy(); sw = W // n; spx = sw * S
            for i in range(n):
                if t >= 6 + i * 3: img[:, i * spx:(i + 1) * spx] = b[:, i * spx:(i + 1) * spx]
                if 6 + i * 3 <= t < 8 + i * 3: L.rect((i * sw, 0, i * sw + 3, H), fill=RED)
        else:
            x = int(W * (0.15 + 0.7 * ease_io((t - 48) / 44)))
            img = b.copy(); img[:, :x * S] = a[:, :x * S]
            L.rect((x - 2, 0, x + 2, H), fill=RED)
            L.text((x - 20, 300), PASSES[0][2], 'bold', 34, INK if x > 700 else WHITE, anchor='ra')
            L.text((x + 20, 300), 'PHOTOREAL', 'bold', 34, WHITE)
    elif t < 144:         # pass 2: clay -> photoreal, diagonal sweep
        a, b = model_img(1), photo_img(1); pi = 1; k = ease_io((t - 96) / 44)
        edge = (-700 + (W + 1400) * k) * S
        m = (XX + YY * 0.6) < edge
        img = np.where(m[..., None], b, a)
    elif t < 192:         # pass 3: blue hour tile mosaic
        a, b = model_img(2), photo_img(2); pi = 2; k = (t - 144) / 40
        img = a.copy(); r = np.random.default_rng(11)
        for j, o in enumerate(r.permutation(8 * 6)):
            if j / 48 < k:
                cx, cy = o % 8, o // 8; x0, y0 = cx * PW // 8, cy * PH // 6
                img[y0:y0 + PH // 6, x0:x0 + PW // 8] = b[y0:y0 + PH // 6, x0:x0 + PW // 8]
        for i in range(1, 8): L.line([(i * W // 8, 0), (i * W // 8, H)], INK, 2, 0.8)
        for i in range(1, 6): L.line([(0, i * H // 6), (W, i * H // 6)], INK, 2, 0.8)
    elif t < 240:         # pass 4: neon lens reveal
        a, b = model_img(3), photo_img(3); pi = 3; k = (t - 192) / 48
        cx, cy = W * (0.2 + 0.6 * k), H * (0.5 + 0.18 * math.sin(k * 6))
        rad = 260 + 900 * ease_in(clamp((k - 0.55) / 0.45))
        m = ((XX - cx * S) ** 2 + (YY - cy * S) ** 2) < (rad * S) ** 2
        img = np.where(m[..., None], b, a)
        L.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), outline=(*CYAN, 220), width=3)
    else:                 # grid wall of the four photos, then punch to golden
        k = t - 240; pi = None
        img = np.full((PH, PW, 3), INK, np.uint8)
        if k < 36:
            tw, th = W // 2 - 6, H // 2 - 6
            for i in range(4):
                if k >= i * 3:
                    b = photo_img(i, (tw, th))
                    x, y = (i % 2) * (W // 2) + 3, (i // 2) * (H // 2) + 3
                    img[y * S:y * S + b.shape[0], x * S:x * S + b.shape[1]] = b
                    L.rect((x, y + th - 96, x + 620, y + th), fill=INK, alpha=0.7)
                    L.text((x + 24, y + th - 86), PASSES[i][3], 'bold', 34, WHITE)
                    L.text((x + 24, y + th - 40), 'PHOTOREAL  /  SAME CAMERA  /  SAME GEOMETRY', 'ocr', 16, WHITE, 0.85)
        else:
            s_ = ease_io((k - 36) / 11)
            b = load(os.path.join(INT, PHOTO_GOLDEN), px=(3840, 2160))
            img = view(b, lerp_rect((0, 0, 3840 * 2, 2160 * 2), (0, 0, 3840, 2160), s_))
    if pi is not None or t >= 276: L.grad(250, 0.6)
    section_title(L, t, '05', 'RENDER', 'CAMERA 01 / LIVING  ·  MODEL FRAME IN  ·  PHOTOREAL OUT  ·  GEOMETRY LOCKED')
    if pi is not None:
        st = t - [0, 96, 144, 192][pi]
        L.rect((W - 560, H - 250, W - 70, H - 90), fill=INK, alpha=0.78)
        L.rect((W - 560, H - 250, W - 554, H - 90), fill=RED)
        L.text((W - 530, H - 232), 'PASS %02d/04  //  %s' % (pi + 1, PASSES[pi][2]), 'ocr', 20, RED)
        slam(L, st, PASSES[pi][3], (W - 530, H - 198), 56 if len(PASSES[pi][3]) < 13 else 42, 'bold', WHITE)
        L.text((W - 530, H - 124), 'MODEL  >  PHOTOREAL', 'mono', 22, WHITE, 0.9)
        rep_ = ALIGN.get(PASSES[pi][1], {})
        meta_panel(L, (80, H - 290, 820, H - 90), 'PROVENANCE TRAVELS WITH THE MODEL', [
            ('source register', 'Almond.SourceRegister  28,167 chars'), ('passports', '24 instances / 15 library assets'),
            ('license', 'CC BY 4.0, attribution embedded'),
            ('registration', '%s px median to model frame' % rep_.get('median_residual_px', '-'))], st + 4, keyw=210)
    elif t >= 276:
        L.rect((W - 560, H - 250, W - 70, H - 90), fill=INK, alpha=0.78)
        L.rect((W - 560, H - 250, W - 554, H - 90), fill=RED)
        L.text((W - 530, H - 232), '4 PASSES', 'ocr', 22, RED)
        L.text((W - 530, H - 198), 'ONE MODEL', 'bold', 64, WHITE)
    hud(L, f, 5, 'RENDER')
    img = L.comp(img)
    return img, 0


# ------------------------------------------------------------------ S5 WORLD (gaussian splat flythrough)
SPLAT_DIR = os.path.join(WORK, 'splat_interior')
SPLAT = sorted(glob.glob(os.path.join(SPLAT_DIR, 'frames4k' if S > 1 and os.path.isdir(os.path.join(SPLAT_DIR, 'frames4k')) else 'frames', 'p_*.*')))
PHOTO_GOLDEN = 'photo_golden_a_4k.png' if os.path.exists(os.path.join(WORK, 'interior', 'photo_golden_a_4k.png')) else 'photo_golden_a.png'
SPLAT_STATS = json.load(open(os.path.join(SPLAT_DIR, 'stats.json'))) if os.path.exists(os.path.join(SPLAT_DIR, 'stats.json')) else {}
CROP = None
PUNCH = 24   # 2 beats: push-in from the full photo to the splat's input crop, then a reconstruction scan reveals the splat
SCAN_F = 12


def s_world(t, f):
    L = Layer()
    photo = load(os.path.join(INT, PHOTO_GOLDEN))
    ph, pw = photo.shape[:2]
    crop_rect = (pw * 0.04, ph * 0.04, pw * 0.92, ph * 0.92)   # gentle push-in before the splat takes over
    if t < PUNCH or not SPLAT:
        k = ease_io(t / PUNCH) if SPLAT else ease_io(t / 384)
        img = view(photo, lerp_rect((0, 0, pw, ph), crop_rect, k))
    else:
        i = min(len(SPLAT) - 1, t - PUNCH)
        img = load(SPLAT[i], (W, H))
        if t < PUNCH + SCAN_F:   # scan line sweeps down: photo above, splat below
            y = int(H * ease_io((t - PUNCH) / (SCAN_F - 1)))
            img = img.copy(); img[y * S:] = view(photo, crop_rect)[y * S:]
            L.rect((0, y - 2, W, y + 2), fill=CYAN)
            L.rect((0, y - 34, W, y - 2), fill=CYAN, alpha=0.15)
    L.grad(250, 0.5)
    section_title(L, t, '06', 'WORLD', 'PHOTOREAL FRAME  >  GAUSSIAN SPLAT  ·  WALKABLE 3D')
    L.brackets((W / 2 - 60, H / 2 - 60, W / 2 + 60, H / 2 + 60), 14, WHITE, 2, 0.7)
    L.line([(W / 2 - 8, H / 2), (W / 2 + 8, H / 2)], WHITE, 1, 0.7); L.line([(W / 2, H / 2 - 8), (W / 2, H / 2 + 8)], WHITE, 1, 0.7)
    L.rect((W - 560, H - 250, W - 70, H - 90), fill=INK, alpha=0.7)
    L.rect((W - 560, H - 250, W - 554, H - 90), fill=CYAN)
    L.text((W - 530, H - 232), 'FLYTHROUGH  //  SPLAT', 'ocr', 22, CYAN)
    L.text((W - 530, H - 198), 'CAM %03d' % max(0, t - PUNCH), 'bold', 64, WHITE)
    tt = clamp((t - PUNCH) / (384 - PUNCH))
    L.text((W - 530, H - 124), 'ORBIT %+05.1f°  DOLLY %02d%%' % (SPLAT_STATS.get('yaw', -12) * ease_io(tt), 100 * SPLAT_STATS.get('dolly', 0.3) * ease_io(tt)), 'mono', 22, WHITE, 0.9)
    if t >= PUNCH:
        meta_panel(L, (80, H - 290, 780, H - 90), 'GAUSSIAN SPLAT  //  .SPZ', [
            ('splats', format(SPLAT_STATS.get('n', 0), ',')), ('source', '1 photoreal frame'),
            ('pose', 'recovered from world pano'), ('render', 'Spark / WebGL2 / RTX 5070')], t - PUNCH, accent=CYAN, keyw=120)
    hud(L, f, 6, 'WORLD')
    img = L.comp(img)
    if t >= 384 - 36:   # the outro hit lands at t=288; picture fades out on the tail
        img = (img * (1 - ease_io((t - 348) / 35))).astype(np.uint8)
    return img, 0


# ------------------------------------------------------------------ S6 GINKGO (worlds generated through Ginkgo -> Unreal MCP)
GK = "C:/Users/liang/OneDrive/Documents/Builiding0/Ginkgo/publishing/fab/releases"
GK_WORLDS = [('W041', 'CORAL TERMINAL', 'v0.1.0'), ('W040', 'SMASH COUNTER', 'v0.1.0'), ('W039', 'CONTAINER STACK', 'v0.1.0'),
             ('W038', 'IDOL TOWER', 'v0.1.0'), ('W037', 'SCAFFOLD SPIRE', 'v0.1.0'), ('W036', 'OVERGROWN PLATFORM', 'v0.1.1'),
             ('W035', 'FLYOVER FUEL', 'v0.1.0'), ('W034', 'STATION STAIR', 'v0.1.1'), ('W033', 'RUST WORKS', 'v0.1.3'),
             ('W032', 'CONDUIT BLOCK', 'v0.1.3')]
GK_HERO = {'W041': 1, 'W040': 1, 'W039': 3, 'W038': 1, 'W037': 1, 'W036': 1, 'W035': 1, 'W034': 1, 'W033': 1, 'W032': 1}
GK_OVER = {'W041': 6, 'W040': 2, 'W039': 2, 'W038': 6, 'W037': 2, 'W036': 2, 'W035': 2, 'W034': 2, 'W033': 2, 'W032': 2}


def gk_img(code, ver, shot):
    im = load('%s/%s/%s/gallery/%s-S%02d.jpg' % (GK, code, ver, code, shot))
    h = im.shape[1] * 9 // 16
    y = max(0, (im.shape[0] - h) // 3)
    return im[y:y + h]


GK_SHOTS = ['W038', 'W041', 'W039', 'W037', 'W035', 'W036']   # Blender fly-arounds, one per bar
GK_DIR = os.path.join(WORK, 'ginkgo')


def gk_frame(code, i):
    return load(os.path.join(GK_DIR, code, 'g_%04d.png' % min(47, max(0, i))), (W, H))


def s_ginkgo(t, f):
    """Just the worlds: no numbering, no captions, no HUD. Soft 8-frame crossfades between fly-arounds."""
    i, k = divmod(t, BAR)
    i = min(i, len(GK_SHOTS) - 1)
    img = gk_frame(GK_SHOTS[i], k)
    XF = 8
    if k < XF and i > 0:
        prev = gk_frame(GK_SHOTS[i - 1], BAR - 1)
        a = (k + 1) / (XF + 1)
        img = (img * a + prev * (1 - a)).astype(np.uint8)
    return img, 0


# ------------------------------------------------------------------ S6 END
FACTS = [('54', 'MCP TOOLS'), ('57', 'LIBRARY OBJECTS'), ('1,670', 'OBJECTS TAGGED'),
         ('SHA-256', 'PASSPORT PER ASSET'), ('CC BY 4.0', 'SHIPPABLE ASSETS'), ('BCI', 'CONSTRUCTION + EGRESS CHECKS')]


def s_end(t, f):
    img = np.full((H, W, 3), INK, np.uint8)
    L = Layer()
    k = ease_out(t / 6)
    L.rect((110, 170, 110 + 130 * k, 300), fill=RED)
    slam(L, t, 'ALMOND', (270, 140), 180, 'bold', WHITE, track=-4)
    L.text((276, 346), 'MCP FOR RHINO 8', 'bold', 44, WHITE, clamp((t - 4) / 6), track=2)
    for i, (big, small) in enumerate(FACTS):
        x, y = 110 + (i % 3) * 560, 470 + (i // 3) * 180
        a = clamp((t - 8 - i * 3) / 5)
        L.rect((x, y, x + 520, y + 2), fill=RED, alpha=a)
        L.text((x, y + 16), big, 'bold', 64, WHITE, a)
        L.text((x + 2, y + 100), small, 'ocr', 20, WHITE, 0.85 * a)
    L.text((110, 868), '$ uvx almond-mcp', 'monob', 34, RED, clamp((t - 30) / 6), reveal=(t - 30) / 14)
    hud(L, f, 6, 'END')
    img = L.comp(img)
    if t > 88: img = (img * (1 - (t - 88) / 8)).astype(np.uint8)
    return img, 0


SECTIONS = [(S_BOOT, s_boot), (S_GEN, s_gen), (S_LIB, s_lib), (S_PHYS, s_phys), (S_LIGHT, s_light), (S_REND, s_render), (S_WORLD, s_world)]


def frame(f):
    start, fn = [s for s in SECTIONS if s[0] <= f][-1]
    img, gl = fn(f - start, f)
    # section-change hit: 2 frames of heavy glitch + white flash on the downbeat
    return finish(img, f, gl)


def render_chunk(job):
    a, b, path, crf = job
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (PW, PH), '-r', str(FPS),
           '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', str(crf), '-pix_fmt', 'yuv420p', path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fr in range(a, b):
        p.stdin.write(frame(fr).tobytes())
    p.stdin.close(); p.wait()
    return path


def main():
    args = sys.argv[1:]
    prep_library()
    if '--stills' in args:
        fs = [int(x) for x in args[args.index('--stills') + 1].split(',')]
        os.makedirs(os.path.join(WORK, 'stills'), exist_ok=True)
        for fr in fs:
            Image.fromarray(frame(fr)).save(os.path.join(WORK, 'stills', 'e_%04d.jpg' % fr), quality=90)
        return
    preview = '--preview' in args
    out = os.path.join(WORK, 'almond_promo_preview.mp4' if preview else 'almond_promo_video.mp4')
    n = int(args[args.index('--jobs') + 1]) if '--jobs' in args else 6
    crf = 21 if preview else 14
    cdir = os.path.join(WORK, 'chunks'); os.makedirs(cdir, exist_ok=True)
    edges = [round(TOTAL * i / n / BEAT) * BEAT for i in range(n + 1)]
    jobs = [(edges[i], edges[i + 1], os.path.join(cdir, 'c_%02d.mp4' % i), crf) for i in range(n)]
    import multiprocessing as mp
    with mp.Pool(n) as pool:
        for pth in pool.imap_unordered(render_chunk, jobs):
            print('chunk done', pth, flush=True)
    lst = os.path.join(cdir, 'list.txt')
    with open(lst, 'w') as fh:
        for j in jobs: fh.write("file '%s'\n" % j[2].replace(os.sep, '/'))
    music = os.path.join(WORK, 'music_final.wav' if os.path.exists(os.path.join(WORK, 'music_final.wav')) else 'music.wav')
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-i', music,
                    '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
                    '-af', 'lowpass=f=15000,loudnorm=I=-14:TP=-1.0:LRA=9', '-c:a', 'aac', '-b:a', '256k', '-ar', '48000',
                    '-movflags', '+faststart', '-shortest', out], check=True)
    print('wrote', out)


if __name__ == '__main__':
    main()
