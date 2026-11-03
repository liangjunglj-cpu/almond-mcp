"""Shared drawing pieces for the Atelier 07 boards and video: plan cuts, heat-map plans, type, colour."""
import json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

here = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from almond_mcp.environment import render

PAPER = (244, 243, 239)
INK = (20, 20, 20)
GREY = (120, 120, 116)
LIGHT = (196, 195, 190)
GLASS = (92, 132, 160)
F = r"C:\Windows\Fonts"


def font(size, bold=False):
    return ImageFont.truetype(f"{F}\\{'arialbd' if bold else 'arial'}.ttf", size)


def load_export():
    d = json.loads((here / "export.json").read_text(encoding="utf-8"))
    s = d["units_to_m"]
    out = []
    for o in d["objects"]:
        v = np.asarray(o["vertices"], float).reshape(-1, 3) * s
        f = np.asarray(o["faces"], np.int64).reshape(-1, 3)
        out.append({"layer": o["layer"], "name": o["name"], "material": o["material"].split("/ ")[-1], "tris": v[f]})
    return out


def slice_at(tris, z):
    """Segments where triangles (k,3,3) cross the plane z (plan cut)."""
    if not len(tris):
        return np.zeros((0, 2, 2))
    d = tris[:, :, 2] - z
    segs = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a, b = d[:, i], d[:, j]
        cross = (a * b) < 0
        t = np.where(cross, a / np.where(cross, a - b, 1), 0)
        p = tris[:, i, :2] + t[:, None] * (tris[:, j, :2] - tris[:, i, :2])
        segs.append((cross, p))
    out = []
    m = np.stack([s[0] for s in segs], 1)
    pts = np.stack([s[1] for s in segs], 1)
    for k in np.flatnonzero(m.sum(1) == 2):
        q = pts[k][m[k]]
        out.append(q)
    return np.asarray(out).reshape(-1, 2, 2)


CUT_LAYERS = {"A07 / 01 Envelope": "wall", "A07 / 03 Facade": "facade", "A07 / 04 Stair and gallery": "detail",
              "A07 / 05 Partitions": "wall", "A07 / 06 Kitchen": "detail", "A07 / 08 Study and bedroom": "detail",
              "A07 / 09 Bathroom": "detail", "A07 / 07 Furniture": "furniture"}


def plan_lines(objs, z):
    """{style: segments} for a plan cut at height z."""
    out = {"wall": [], "glass": [], "detail": [], "furniture": []}
    for o in objs:
        style = CUT_LAYERS.get(o["layer"])
        if style is None:
            continue
        if o["material"] == "Glass":
            style = "glass"
        elif style == "facade":
            style = "wall" if o["material"] == "Concrete" else "detail"
        s = slice_at(o["tris"], z)
        if len(s):
            out[style].append(s)
    return {k: (np.concatenate(v) if v else np.zeros((0, 2, 2))) for k, v in out.items()}


class Plan:
    """Maps plan metres to a pixel box (north up)."""
    def __init__(self, box, x0=-0.6, x1=13.4, y0=-0.6, y1=10.6):
        self.bx, self.by, self.bw, self.bh = box
        self.s = min(self.bw / (x1 - x0), self.bh / (y1 - y0))
        self.ox = self.bx + (self.bw - (x1 - x0) * self.s) / 2 - x0 * self.s
        self.oy = self.by + (self.bh + (y1 - y0) * self.s) / 2 + y0 * self.s

    def px(self, p):
        return (self.ox + p[0] * self.s, self.oy - p[1] * self.s)

    def draw(self, d, cells=None, colors=None, lines=None, weights=None):
        w = weights or {"wall": 4, "glass": 2, "detail": 1, "furniture": 1}
        if cells is not None:
            for c, col in zip(cells, colors):
                d.polygon([self.px(q) for q in c[:, :2]], fill=tuple(int(x) for x in col))
        if lines:
            for style, color in (("furniture", LIGHT), ("detail", GREY), ("glass", GLASS), ("wall", INK)):
                for seg in lines.get(style, []):
                    d.line([self.px(seg[0]), self.px(seg[1])], fill=color, width=max(1, int(round(w[style] * self.s / 60))))


def legend_bar(d, x, y, w, h, lo, hi, ramp, ticks, fmt, label, size=22, log=False):
    for i in range(w):
        t = i / (w - 1)
        v = 10 ** (math.log10(lo) + t * (math.log10(hi) - math.log10(lo))) if log else lo + t * (hi - lo)
        col = colour(np.array([v]), lo, hi, ramp, log)[0]
        d.line([(x + i, y), (x + i, y + h)], fill=tuple(int(c) for c in col))
    f = font(size)
    for v in ticks:
        t = (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) if log else (v - lo) / (hi - lo)
        tx = x + t * (w - 1)
        d.line([(tx, y + h), (tx, y + h + 8)], fill=INK, width=2)
        s = fmt(v)
        d.text((tx - d.textlength(s, font=f) / 2, y + h + 12), s, fill=INK, font=f)
    if label:
        d.text((x, y - size - 12), label, fill=INK, font=f)


def colour(values, lo, hi, ramp="viridis", log=False):
    v = np.asarray(values, float)
    if log:
        v = np.log10(np.maximum(v, 1e-6))
        lo, hi = math.log10(lo), math.log10(hi)
    return render.colorize(v, lo, hi, ramp)
