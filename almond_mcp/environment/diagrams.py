"""Architectural diagrams for the environment workspace, in Almond's visual language.

One set of drawing primitives (``Canvas``) renders to SVG for the Rhino panel and to PNG (Pillow) for
boards, so a section detail or a room plan looks the same wherever it appears. The palette and type are
the panel's (library_ui/style.css): paper, ink, muted grey, hairline grey, Almond red and green; Arial
for text, Courier New for the small mono labels. Drawing conventions: line weights in three steps (cut,
outline, hairline), material hatches after common architectural practice (concrete, masonry, timber,
insulation, plaster, membrane, glass), north up in plans, the room's side of a section on the right.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

import numpy as np

PAPER = "#efeee8"
INK = "#21231f"
MUTED = "#676a61"
LINE = "#c8c9bf"
PANEL = "#e6e6dd"
RED = "#e94329"
GREEN = "#237963"
AMBER = "#ab6b11"
SANS = "Arial, Helvetica, sans-serif"
MONO = "'Courier New', monospace"
CUT, OUTLINE, HAIR = 2.0, 1.2, 0.6

STATE_FILL = {"enclosed": "#f7f6f1", "semi_open": "#f3e4dc", "open": PAPER}
STEPS = [("site", "Site"), ("rooms", "Rooms"), ("constructions", "Constructions"), ("study", "Study"), ("results", "Results")]


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


@dataclass
class Canvas:
    width: float
    height: float
    items: list[tuple] = field(default_factory=list)
    background: str | None = None
    _clip: int = 0

    # primitives ---------------------------------------------------------------
    def line(self, pts, stroke=INK, width=OUTLINE, dash=None):
        self.items.append(("line", [tuple(map(float, p)) for p in pts], stroke, width, dash))

    def polygon(self, pts, fill=None, stroke=INK, width=OUTLINE, hatch=None, dash=None):
        self.items.append(("poly", [tuple(map(float, p)) for p in pts], fill, stroke, width, hatch, dash))

    def rect(self, x, y, w, h, **kw):
        self.polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], **kw)

    def circle(self, cx, cy, r, fill=None, stroke=INK, width=OUTLINE, dash=None):
        self.items.append(("circle", float(cx), float(cy), float(r), fill, stroke, width, dash))

    def text(self, x, y, s, size=11, fill=INK, mono=False, anchor="start", weight="normal"):
        self.items.append(("text", float(x), float(y), str(s), float(size), fill, mono, anchor, weight))

    def arrow(self, a, b, stroke=INK, width=OUTLINE, head=6.0):
        a, b = np.asarray(a, float), np.asarray(b, float)
        self.line([a, b], stroke, width)
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-9:
            return
        d /= L
        n = np.array([-d[1], d[0]])
        self.polygon([b, b - d * head + n * head * 0.45, b - d * head - n * head * 0.45], fill=stroke, stroke=stroke, width=0.5)

    # SVG ----------------------------------------------------------------------
    def svg(self, title: str = "") -> str:
        defs, body = [], []
        hatches_used = set()
        for it in self.items:
            if it[0] == "poly" and it[5]:
                hatches_used.add(it[5])
        for h in sorted(hatches_used):
            defs.append(_svg_pattern(h))
        if self.background:
            body.append(f'<rect width="{self.width:g}" height="{self.height:g}" fill="{self.background}"/>')
        for it in self.items:
            kind = it[0]
            if kind == "line":
                _, pts, stroke, w, dash = it
                d = f' stroke-dasharray="{dash}"' if dash else ""
                body.append(f'<polyline points="{_pts(pts)}" fill="none" stroke="{stroke}" stroke-width="{w:g}"'
                            f' stroke-linecap="round" stroke-linejoin="round"{d}/>')
            elif kind == "poly":
                _, pts, fill, stroke, w, hatch, dash = it
                d = f' stroke-dasharray="{dash}"' if dash else ""
                if fill:
                    body.append(f'<polygon points="{_pts(pts)}" fill="{fill}" stroke="none"/>')
                if hatch:
                    body.append(f'<polygon points="{_pts(pts)}" fill="url(#h-{hatch})" stroke="none"/>')
                if stroke:
                    body.append(f'<polygon points="{_pts(pts)}" fill="none" stroke="{stroke}" stroke-width="{w:g}"'
                                f' stroke-linejoin="round"{d}/>')
            elif kind == "circle":
                _, cx, cy, r, fill, stroke, w, dash = it
                d = f' stroke-dasharray="{dash}"' if dash else ""
                body.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill or "none"}"'
                            f' stroke="{stroke or "none"}" stroke-width="{w:g}"{d}/>')
            elif kind == "text":
                _, x, y, s, size, fill, mono, anchor, weight = it
                fam = MONO if mono else SANS
                body.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{fam}" font-size="{size:g}" fill="{fill}"'
                            f' text-anchor="{anchor}" font-weight="{weight}">{escape(s)}</text>')
        t = f"<title>{escape(title)}</title>" if title else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width:g} {self.height:g}" '
                f'role="img">{t}<defs>{"".join(defs)}</defs>{"".join(body)}</svg>')

    # PNG ----------------------------------------------------------------------
    def png(self, path: str, scale: float = 2.0) -> str:
        from PIL import Image, ImageDraw
        W, H = int(self.width * scale), int(self.height * scale)
        im = Image.new("RGB", (W, H), _hex(self.background or PAPER))
        d = ImageDraw.Draw(im)
        S = lambda pts: [(x * scale, y * scale) for x, y in pts]
        for it in self.items:
            kind = it[0]
            if kind == "line":
                _, pts, stroke, w, dash = it
                _pil_line(d, S(pts), _hex(stroke), max(1, int(round(w * scale))), dash, scale)
            elif kind == "poly":
                _, pts, fill, stroke, w, hatch, dash = it
                if fill:
                    d.polygon(S(pts), fill=_hex(fill))
                if hatch:
                    _pil_hatch(im, S(pts), hatch, scale)
                    d = ImageDraw.Draw(im)
                if stroke:
                    _pil_line(d, S(pts + [pts[0]]), _hex(stroke), max(1, int(round(w * scale))), dash, scale)
            elif kind == "circle":
                _, cx, cy, r, fill, stroke, w, dash = it
                box = [(cx - r) * scale, (cy - r) * scale, (cx + r) * scale, (cy + r) * scale]
                if fill:
                    d.ellipse(box, fill=_hex(fill))
                if stroke:
                    if dash:
                        n = max(24, int(r * 0.6))
                        pts = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]
                        _pil_line(d, S(pts), _hex(stroke), max(1, int(round(w * scale))), dash, scale)
                    else:
                        d.ellipse(box, outline=_hex(stroke), width=max(1, int(round(w * scale))))
            elif kind == "text":
                _, x, y, s, size, fill, mono, anchor, weight = it
                f = _font(size * scale, mono, weight == "bold")
                tw = d.textlength(s, font=f)
                ox = {"start": 0, "middle": -tw / 2, "end": -tw}[anchor]
                d.text((x * scale + ox, y * scale - size * scale * 0.82), s, fill=_hex(fill), font=f)
        im.save(path)
        return path


def _pts(pts) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


HATCH_SPECS = {   # id -> (svg pattern body, size)
    "concrete": ('<path d="M0 8L8 0" stroke="#21231f" stroke-width="0.5"/><circle cx="2" cy="2" r="0.6" fill="#21231f"/>'
                 '<circle cx="6" cy="5" r="0.5" fill="#21231f"/>', 8),
    "masonry": ('<path d="M0 6L6 0M-1 1L1 -1M5 7L7 5" stroke="#21231f" stroke-width="0.6"/>', 6),
    "timber": ('<path d="M0 2Q4 0 8 2T16 2M0 6Q4 4 8 6T16 6" stroke="#21231f" stroke-width="0.45" fill="none"/>', 8),
    "insulation": ('<path d="M0 4L2 0L4 8L6 0L8 4" stroke="#e94329" stroke-width="0.6" fill="none"/>', 8),
    "plaster": ('<circle cx="1.5" cy="1.5" r="0.45" fill="#676a61"/><circle cx="4.5" cy="4" r="0.45" fill="#676a61"/>', 6),
    "stone": ('<path d="M0 8L8 0M0 4L4 0M4 8L8 4" stroke="#21231f" stroke-width="0.4"/>', 8),
    "metal": ('<path d="M0 0H8" stroke="#21231f" stroke-width="1"/>', 3),
    "glass": ('<path d="M0 8L8 0" stroke="#237963" stroke-width="0.5"/>', 8),
    "soil": ('<circle cx="2" cy="3" r="0.7" fill="#676a61"/><circle cx="6" cy="6" r="0.5" fill="#676a61"/>', 8),
    "open": ('<path d="M0 8L8 0" stroke="#c8c9bf" stroke-width="0.6"/>', 8),
}
CATEGORY_HATCH = {"concrete": "concrete", "masonry": "masonry", "timber": "timber", "insulation": "insulation",
                  "finish": "plaster", "stone": "stone", "metal": "metal", "glass": "glass", "membrane": None, "air": None}


def _svg_pattern(h: str) -> str:
    body, size = HATCH_SPECS[h]
    return (f'<pattern id="h-{h}" width="{size}" height="{size}" patternUnits="userSpaceOnUse">'
            f'{body}</pattern>')


def _font(px: float, mono: bool, bold: bool):
    from PIL import ImageFont
    names = (["courbd.ttf", "cour.ttf", "DejaVuSansMono.ttf"] if mono else
             (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]))
    for n in names:
        try:
            return ImageFont.truetype(n, max(6, int(px)))
        except OSError:
            continue
    return ImageFont.load_default()


def _pil_line(d, pts, color, width, dash, scale):
    if not dash:
        d.line(pts, fill=color, width=width, joint="curve")
        return
    on, off = (float(x) * scale for x in str(dash).replace(",", " ").split()[:2])
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        t = 0.0
        while t < L:
            t1 = min(t + on, L)
            d.line([(x0 + (x1 - x0) * t / L, y0 + (y1 - y0) * t / L), (x0 + (x1 - x0) * t1 / L, y0 + (y1 - y0) * t1 / L)],
                   fill=color, width=width)
            t = t1 + off


def _pil_hatch(im, pts, hatch, scale):
    """Hatch a polygon by drawing the pattern lines through a mask."""
    from PIL import Image, ImageDraw
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1
    if x1 <= x0 or y1 <= y0:
        return
    tile = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    step = (8 if hatch not in ("masonry", "plaster", "metal") else 6) * scale
    w = max(1, int(round(0.6 * scale)))
    col = _hex(RED if hatch == "insulation" else GREEN if hatch == "glass" else LINE if hatch == "open" else INK if hatch != "plaster" else MUTED)
    Wt, Ht = x1 - x0, y1 - y0
    if hatch == "insulation":
        y = 0.0
        while y < Ht:
            zz = []
            x = 0.0
            k = 0
            while x <= Wt + step:
                zz.append((x, y + (step if k % 2 else 0)))
                x += step / 2
                k += 1
            td.line(zz, fill=col + (255,), width=w)
            y += step * 1.2
    elif hatch == "timber":
        y = step / 3
        while y < Ht:
            td.line([(x, y + math.sin(x / (step * 0.6)) * step * 0.15) for x in np.arange(0, Wt + 2, 2)], fill=col + (255,), width=w)
            y += step / 2
    elif hatch in ("plaster", "soil"):
        for yy in np.arange(step / 3, Ht, step / 2):
            for xx in np.arange((yy * 1.7) % (step / 2), Wt, step / 2):
                td.ellipse([xx - w, yy - w, xx + w, yy + w], fill=col + (255,))
    elif hatch == "metal":
        for yy in np.arange(0, Ht, step / 2):
            td.line([(0, yy), (Wt, yy)], fill=col + (255,), width=w)
    else:
        for c in np.arange(-Ht, Wt + Ht, step):
            td.line([(c, Ht), (c + Ht, 0)], fill=col + (255,), width=w)
        if hatch == "concrete":
            rng = np.random.default_rng(3)
            for _ in range(int(Wt * Ht / (step * step) * 2)):
                xx, yy = rng.uniform(0, Wt), rng.uniform(0, Ht)
                td.ellipse([xx - w, yy - w, xx + w, yy + w], fill=col + (255,))
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in pts], fill=255)
    alpha = tile.getchannel("A")
    from PIL import ImageChops
    tile.putalpha(ImageChops.multiply(alpha, mask))
    im.paste(tile, (x0, y0), tile)


# ── icons and the step strip ─────────────────────────────────────────────────

def _icon(c: Canvas, key: str, x: float, y: float, s: float, color: str):
    """16-unit line icons, drawn at (x, y) with size s - the panel's tab-icon style."""
    k = s / 16.0
    P = lambda pts: [(x + px * k, y + py * k) for px, py in pts]
    w = 1.3
    if key == "site":
        c.circle(x + 8 * k, y + 8 * k, 6.5 * k, stroke=color, width=w)
        c.polygon(P([(8, 2.5), (10, 9), (8, 8), (6, 9)]), fill=color, stroke=color, width=0.5)
    elif key == "rooms":
        c.polygon(P([(1.5, 2.5), (14.5, 2.5), (14.5, 13.5), (1.5, 13.5)]), stroke=color, width=w)
        c.line(P([(8, 2.5), (8, 9)]), color, w)
        c.line(P([(8, 9), (14.5, 9)]), color, w)
    elif key == "constructions":
        for i, xx in enumerate((2.5, 6, 9.5, 13)):
            c.line(P([(xx, 2), (xx, 14)]), color, w if i in (0, 3) else 0.8)
        c.line(P([(6, 5), (9.5, 3), (6, 8), (9.5, 6), (6, 11), (9.5, 9), (6, 14)]), color, 0.8)
    elif key == "study":
        c.line(P([(1.5, 9), (4, 4.5), (8, 2.5), (12, 4.5), (14.5, 9)]), color, w)
        c.polygon(P([(3, 9), (13, 9), (13, 14), (3, 14)]), stroke=color, width=w)
        c.line(P([(5, 12), (11, 12)]), color, 0.8, dash="1.5 1.5")
    elif key == "results":
        for xx, hh in ((3.5, 5), (8, 10), (12.5, 7)):
            c.line(P([(xx, 14), (xx, 14 - hh)]), color, 2.4)
        c.line(P([(1.5, 14.5), (14.5, 14.5)]), color, w)


def step_strip(active: str = "site", done: tuple[str, ...] = ()) -> Canvas:
    """Site -> Rooms -> Constructions -> Study -> Results, the current step in red."""
    W, H = 720, 74
    c = Canvas(W, H)
    n = len(STEPS)
    cw = W / n
    for i, (key, label) in enumerate(STEPS):
        x = i * cw
        col = RED if key == active else INK if key in done else MUTED
        _icon(c, key, x + 12, 14, 22, col)
        c.text(x + 42, 22, f"{i + 1:02d}", 10, col, mono=True)
        c.text(x + 42, 38, label, 12, col, weight="bold" if key == active else "normal")
        if i < n - 1:
            c.line([(x + cw - 14, 26), (x + cw - 4, 26)], LINE, 1.0)
            c.line([(x + cw - 8, 22), (x + cw - 4, 26), (x + cw - 8, 30)], LINE, 1.0)
        c.line([(x + 6, 58), (x + cw - 10, 58)], RED if key == active else LINE, 2.0 if key == active else 1.0)
    return c


# ── site ─────────────────────────────────────────────────────────────────────

def site_diagram(latitude: float, longitude: float, time_zone: float, north_deg: float = 0.0, label: str = "") -> Canvas:
    """Plan compass with the sun path (stereographic): June and December solstices and the equinox."""
    from .solar import sun_position
    W, H = 320, 300
    c = Canvas(W, H)
    cx, cy, R = 160, 150, 115
    for alt in (0, 30, 60):
        r = R * math.tan(math.radians((90 - alt) / 2))
        c.circle(cx, cy, r, stroke=LINE if alt else INK, width=HAIR if alt else OUTLINE)
    for az in range(0, 360, 30):
        a = math.radians(az - north_deg)
        c.line([(cx, cy), (cx + R * math.sin(a), cy - R * math.cos(a))], LINE, HAIR)
    a = math.radians(-north_deg)
    c.polygon([(cx + (R + 18) * math.sin(a), cy - (R + 18) * math.cos(a)),
               (cx + (R + 6) * math.sin(a) + 5 * math.cos(a), cy - (R + 6) * math.cos(a) + 5 * math.sin(a)),
               (cx + (R + 6) * math.sin(a) - 5 * math.cos(a), cy - (R + 6) * math.cos(a) - 5 * math.sin(a))], fill=INK, stroke=INK, width=0.5)
    c.text(cx + (R + 28) * math.sin(a), cy - (R + 28) * math.cos(a) + 4, "N", 11, INK, anchor="middle", weight="bold")
    for doy, col, name in ((172, RED, "21 JUN"), (80, MUTED, "EQUINOX"), (355, GREEN, "21 DEC")):
        hours = np.arange(0, 24.01, 0.25)
        sp = sun_position(latitude, longitude, time_zone, np.full(hours.shape, doy), hours)
        up = sp["altitude"] > 0
        pts = []
        for alt, az in zip(sp["altitude"][up], sp["azimuth"][up]):
            r = R * math.tan(math.radians((90 - alt) / 2))
            aa = math.radians(az - north_deg)
            pts.append((cx + r * math.sin(aa), cy - r * math.cos(aa)))
        if len(pts) > 1:
            c.line(pts, col, CUT if col == RED else OUTLINE)
            c.text(pts[len(pts) // 2][0], pts[len(pts) // 2][1] - 6, name, 8, col, mono=True, anchor="middle")
    c.text(12, 18, label or f"{latitude:.2f}, {longitude:.2f}", 10, MUTED, mono=True)
    c.text(12, H - 10, "SUN PATH · STEREOGRAPHIC · 0/30/60° ALTITUDE", 8, MUTED, mono=True)
    return c


# ── rooms ────────────────────────────────────────────────────────────────────

def _footprint(vertices: np.ndarray, triangles: np.ndarray) -> list[np.ndarray]:
    """Plan outline(s) of a mesh's downward faces (or all faces) as closed polygons."""
    import shapely
    from shapely.ops import unary_union
    v = np.asarray(vertices, float)
    f = np.asarray(triangles, int)
    a, b, cc = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    nz = np.cross(b - a, cc - a)[:, 2]
    sel = f[nz < 0] if (nz < 0).any() else f
    polys = [shapely.Polygon(v[t][:, :2]) for t in sel]
    u = unary_union([p.buffer(1e-6) for p in polys if p.area > 1e-9]).buffer(-1e-6)
    geoms = getattr(u, "geoms", [u])
    return [np.asarray(g.exterior.coords) for g in geoms if g.area > 1e-6]


def room_plan(rooms: list[dict], title: str = "Rooms", values: dict | None = None, unit: str = "",
              vrange: tuple[float, float] | None = None, ramp: str = "viridis", width: float = 520) -> Canvas:
    """Plan of the rooms: ``rooms`` = [{"name", "outline": [(x, y), ...] metres, "state", "use", "area",
    "openings": [{"normal"}], "level": z}], one panel per level. ``values`` {name: number} tints the rooms."""
    from .render import colorize
    if not rooms:
        c = Canvas(width, 120)
        c.text(16, 60, "No rooms defined yet", 13, MUTED)
        return c
    levels = sorted({round(r.get("level", 0.0), 1) for r in rooms})
    allpts = np.vstack([np.asarray(r["outline"]) for r in rooms])
    lo, hi = allpts.min(axis=0), allpts.max(axis=0)
    span = max(hi[0] - lo[0], 1e-6)
    pad = 28
    panel_w = width - 2 * pad
    s = panel_w / span
    ph = (hi[1] - lo[1]) * s
    H = 56 + len(levels) * (ph + 54) + (40 if values else 10)
    c = Canvas(width, H)
    c.text(pad, 22, title.upper(), 10, MUTED, mono=True)
    vmin, vmax = vrange or ((min(values.values()), max(values.values())) if values else (0, 1))
    if values and vmax <= vmin:
        vmax = vmin + 1
    for li, lev in enumerate(levels):
        oy = 56 + li * (ph + 54)
        c.text(pad, oy - 12, f"LEVEL +{lev:.1f} m" if len(levels) > 1 else "PLAN", 9, INK, mono=True)
        X = lambda p: (pad + (p[0] - lo[0]) * s, oy + ph - (p[1] - lo[1]) * s)
        for r in [r for r in rooms if round(r.get("level", 0.0), 1) == lev]:
            pts = [X(p) for p in r["outline"]]
            state = r.get("state", "enclosed")
            fill = STATE_FILL.get(state, PAPER)
            if values and r["name"] in values and values[r["name"]] is not None:
                rgb = colorize(np.array([values[r["name"]]], float), vmin, vmax, ramp)[0]
                fill = "#%02x%02x%02x" % tuple(int(x) for x in rgb[:3])
            c.polygon(pts, fill=fill, hatch="open" if state == "open" and not values else None,
                      stroke=INK, width=CUT if state == "enclosed" else OUTLINE, dash=None if state == "enclosed" else "5 3")
            cen = np.mean(np.asarray(pts), axis=0)
            c.text(cen[0], cen[1] - 3, r["name"], 11, INK, anchor="middle", weight="bold")
            sub = f"{r.get('area', 0):.0f} m²" + (f" · {r['use']}" if r.get("use") else "")
            if values and r["name"] in values and values[r["name"]] is not None:
                sub = f"{values[r['name']]:.1f} {unit}".strip()
            c.text(cen[0], cen[1] + 11, sub, 9, MUTED if not values else INK, mono=True, anchor="middle")
            for o in r.get("openings", []):
                nrm = o.get("normal", [0, 0, 0])
                if abs(nrm[2]) > 0.7:
                    continue
                q = cen + np.array([nrm[0], -nrm[1]]) * 0.5 * min(np.ptp(np.asarray(pts)[:, 0]), np.ptp(np.asarray(pts)[:, 1]))
                c.arrow(cen + (q - cen) * 0.55, q, RED, 1.2, 5)
    # north arrow and scale bar
    nx, ny = width - pad - 10, 30
    c.polygon([(nx, ny - 14), (nx - 5, ny), (nx, ny - 4), (nx + 5, ny)], fill=INK, stroke=INK, width=0.5)
    c.text(nx, ny + 12, "N", 9, INK, anchor="middle", mono=True)
    bar = 5.0 if span > 8 else 1.0
    by = H - (34 if values else 8)
    c.line([(pad, by), (pad + bar * s, by)], INK, CUT)
    c.text(pad + bar * s + 6, by + 3, f"{bar:g} m", 8, MUTED, mono=True)
    if values:
        _legend(c, pad + 120, H - 26, 180, vmin, vmax, unit, ramp)
    else:
        lx = pad + bar * s + 60
        for state, label in (("enclosed", "enclosed"), ("semi_open", "semi-open"), ("open", "open")):
            c.rect(lx, by - 7, 14, 9, fill=STATE_FILL[state], hatch="open" if state == "open" else None,
                   stroke=INK, width=HAIR, dash=None if state == "enclosed" else "3 2")
            c.text(lx + 18, by + 1, label, 8, MUTED, mono=True)
            lx += 82
    return c


def _legend(c: Canvas, x, y, w, vmin, vmax, unit, ramp):
    from .render import colorize
    n = 24
    vals = np.linspace(vmin, vmax, n)
    cols = colorize(vals, vmin, vmax, ramp)
    for i in range(n):
        c.rect(x + i * w / n, y, w / n + 0.5, 8, fill="#%02x%02x%02x" % tuple(int(v) for v in cols[i][:3]), stroke=None)
    c.text(x, y + 20, f"{vmin:.0f}", 8, MUTED, mono=True)
    c.text(x + w, y + 20, f"{vmax:.0f} {unit}", 8, MUTED, mono=True, anchor="end")


# ── construction section detail ─────────────────────────────────────────────

def construction_section(props: dict, width: float = 520, height: float = 300) -> Canvas:
    """Section detail of an assembly from ``constructions.properties``: layers to scale (thin layers
    widened to stay readable), hatched by material, labelled with leaders; U-value and kappa below."""
    c = Canvas(width, height)
    c.text(16, 22, props.get("name", ""), 13, INK, weight="bold")
    sub = f"{props.get('kind', '').replace('_', ' ').upper()} · {props.get('thickness_mm', 0):.0f} MM"
    if props.get("kind") == "window":
        sub += f" · FRAME {int(round(100 * props.get('frame_fraction', 0)))} % {props.get('frame', '')}".upper()
    c.text(16, 38, sub, 9, MUTED, mono=True)
    top, bot = 64, height - 92
    x0, x1 = 70, width - 70
    if props.get("kind") == "window":
        _window_section(c, props, x0, x1, top, bot)
    else:
        layers = props["layers"]
        th = np.array([max(L["thickness_mm"], 0.1) for L in layers])
        vis = np.maximum(th / th.sum(), 0.035)
        vis = vis / vis.sum() * (x1 - x0)
        x = x0
        from . import constructions as asm
        mats = asm.materials()
        n = len(layers)
        for i, (L, wv) in enumerate(zip(layers, vis)):
            m = mats.get(L["material"], {})
            cat = m.get("category", "")
            hatch = CATEGORY_HATCH.get(cat)
            fill = INK if cat == "membrane" else "#ffffff" if cat == "air" else "#fbfaf6"
            c.rect(x, top, wv, bot - top, fill=fill, hatch=hatch, stroke=INK, width=HAIR)
            # leader + label, alternating above / below
            lx = x + wv / 2
            ly = top - 6 if i % 2 == 0 else bot + 6
            ty = 52 if i % 2 == 0 else bot + 22 + (i // 2 % 2) * 0
            c.line([(lx, top + 6 if i % 2 == 0 else bot - 6), (lx, ly)], MUTED, HAIR)
            label = f"{L['thickness_mm']:g} {_short(L['name'])}"
            c.text(lx, ty if i % 2 == 0 else bot + 20, label, 8, INK, mono=True, anchor="middle")
            x += wv
        c.line([(x0, top), (x1, top)], INK, CUT)
        c.line([(x0, bot), (x1, bot)], INK, CUT)
        c.line([(x0, top), (x0, bot)], INK, CUT)
        c.line([(x1, top), (x1, bot)], INK, CUT)
    out_label, in_label = _side_labels(props.get("kind", ""))
    c.text(x0 - 10, (top + bot) / 2, out_label, 9, MUTED, mono=True, anchor="end")
    c.text(x1 + 10, (top + bot) / 2, in_label, 9, MUTED, mono=True)
    # metrics row
    y = height - 46
    c.line([(16, y - 18), (width - 16, y - 18)], INK, HAIR)
    tiles = [("U", f"{props['u_value']:.2f}", "W/m²K")]
    if props.get("kind") == "window":
        tiles += [("g", f"{props['g_value']:.2f}", ""), ("τv", f"{props['tau_v']:.2f}", ""), ("Ug", f"{props['u_g']:.2f}", "W/m²K")]
    else:
        tiles += [("κ in", f"{props['kappa_inside_kj_m2k']:.0f}", "kJ/m²K"), ("mass", f"{props['mass_kg_m2']:.0f}", "kg/m²"),
                  ("R", f"{props['r_total']:.2f}", "m²K/W")]
    tw = (width - 32) / len(tiles)
    for i, (k, v, u) in enumerate(tiles):
        tx = 16 + i * tw
        c.text(tx, y + 6, v, 20, RED if i == 0 else INK)
        c.text(tx, y + 22, f"{k} {u.upper()}".strip(), 8, MUTED, mono=True)
    return c


def _short(name: str) -> str:
    s = name.split(",")[0].split("(")[0].strip()
    return s if len(s) <= 22 else s[:21] + "…"


def _side_labels(kind: str) -> tuple[str, str]:
    if kind == "floor_internal":
        return "BELOW", "ABOVE"
    if kind in ("floor_ground",):
        return "GROUND", "ROOM"
    if kind == "wall_internal":
        return "SIDE A", "SIDE B"
    return "OUT", "IN"


def _window_section(c: Canvas, p: dict, x0, x1, top, bot):
    panes = p.get("panes", [])
    gaps = p.get("gaps", [])
    total = sum(6.0 for _ in panes) + sum(g["width_m"] * 1000 for g in gaps)
    s = (x1 - x0) * 0.5 / max(total, 1)
    x = x0 + (x1 - x0) * 0.25
    fr_w = (x1 - x0) * 0.08
    c.rect(x - fr_w, top, fr_w, bot - top, fill=PANEL, stroke=INK, width=OUTLINE)
    for i, pane in enumerate(panes):
        w = 6.0 * s
        c.rect(x, top + 18, w, bot - top - 36, fill="#e3efe9", hatch="glass", stroke=GREEN, width=OUTLINE)
        c.text(x + w / 2, top - 8, _short(pane["name"]), 8, INK, mono=True, anchor="middle")
        x += w
        if i < len(gaps):
            gw = gaps[i]["width_m"] * 1000 * s
            c.text(x + gw / 2, bot + 18, f"{gaps[i]['width_m'] * 1000:g} {gaps[i]['gas']}", 8, MUTED, mono=True, anchor="middle")
            x += gw
    c.rect(x, top, fr_w, bot - top, fill=PANEL, stroke=INK, width=OUTLINE)


# ── study section ────────────────────────────────────────────────────────────

def study_section(study: str = "daylight", width: float = 520, height: float = 230) -> Canvas:
    """A schematic section that says what the study computes."""
    c = Canvas(width, height)
    gx0, gx1, gy = 40, width - 40, height - 40
    rx0, rx1, ry0 = 150, width - 150, gy - 100
    c.line([(gx0, gy), (gx1, gy)], INK, CUT)
    c.polygon([(rx0, gy), (rx0, ry0), (rx1, ry0), (rx1, gy)], fill="#fbfaf6", stroke=INK, width=CUT)
    c.line([(rx0, gy - 75), (rx0, gy - 25)], GREEN, 3.0)                       # window
    pts = [(width / 2 + 210 * math.cos(t), gy + 30 - 175 * math.sin(t)) for t in np.linspace(0.12, math.pi - 0.12, 40)]
    c.line(pts, LINE, OUTLINE, dash="4 3")
    sun = (rx0 - 95, ry0 - 40)
    c.circle(*sun, 9, fill=None, stroke=RED, width=OUTLINE)
    if study == "daylight":
        c.line([(rx0 + 12, gy - 32), (rx1 - 12, gy - 32)], RED, OUTLINE, dash="3 3")
        c.arrow(sun, (rx0 + 40, gy - 34), RED, 1.0, 6)
        for k in range(3):
            c.arrow((rx0 - 60, ry0 - 70 + 18 * k), (rx0 - 2, gy - 60 + 12 * k), MUTED, 0.8, 5)
        c.text(rx1 - 12, gy - 38, "SENSORS · 0.8 M WORK PLANE", 8, RED, mono=True, anchor="end")
        c.text(gx0, 20, "DAYLIGHT · SKY + SUN THROUGH GLAZING, INTERREFLECTED", 9, MUTED, mono=True)
    elif study == "thermal":
        c.arrow(sun, (rx0 + 30, gy - 40), RED, 1.0, 6)
        mx = (rx0 + rx1) / 2
        c.arrow((rx1 - 10, ry0 + 40), (rx1 + 40, ry0 + 40), INK, 1.0, 5)
        c.arrow((mx, ry0 + 6), (mx, ry0 - 26), INK, 1.0, 5)
        c.arrow((rx0 - 40, gy - 15), (rx0 + 20, gy - 15), GREEN, 1.0, 5)
        c.text(mx, gy - 45, "AIR · SURFACE · MASS", 8, INK, mono=True, anchor="middle")
        c.text(rx1 + 44, ry0 + 44, "CONDUCTION", 8, MUTED, mono=True)
        c.text(rx0 - 44, gy - 20, "AIR", 8, GREEN, mono=True, anchor="end")
        c.text(gx0, 20, "THERMAL · HOURLY 5R1C PER ROOM · ROOMS EXCHANGE HEAT", 9, MUTED, mono=True)
    else:
        c.text(gx0, 20, study.upper(), 9, MUTED, mono=True)
    return c


def results_tiles(items: list[tuple[str, str, str]], width: float = 520) -> Canvas:
    """A row of metric tiles: (value, label, unit)."""
    c = Canvas(width, 64)
    n = max(1, len(items))
    tw = (width - 32) / n
    c.line([(16, 8), (width - 16, 8)], INK, HAIR)
    for i, (v, label, unit) in enumerate(items):
        x = 16 + i * tw
        c.text(x, 38, v, 22, RED if i == 0 else INK)
        c.text(x, 54, f"{label.upper()} {unit}".strip(), 8, MUTED, mono=True)
    return c
