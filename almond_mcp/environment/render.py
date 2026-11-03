"""False-colour images and legends for analysis results (Pillow only)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

# Perceptually ordered ramps, sampled from the matplotlib colormaps (CC0 data) at 9 stops.
RAMPS = {
    "viridis": ["#440154", "#472c7a", "#3b518b", "#2c718e", "#21908d", "#27ad81", "#5cc863", "#aadc32", "#fde725"],
    "magma": ["#000004", "#1c1044", "#4f127b", "#812581", "#b5367a", "#e55064", "#fb8761", "#fec287", "#fcfdbf"],
    "coolwarm": ["#3b4cc0", "#6282ea", "#8db0fe", "#b8d0f9", "#dddddd", "#f5c4ad", "#f49a7b", "#de604d", "#b40426"],
}


def _hex(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def colorize(values: np.ndarray, vmin: float, vmax: float, ramp: str = "viridis") -> np.ndarray:
    """(N, 3) uint8 colours; NaN -> grey."""
    stops = np.array([_hex(c) for c in RAMPS[ramp]], dtype=float)
    v = np.asarray(values, dtype=float)
    t = np.clip((v - vmin) / (vmax - vmin), 0, 1) if vmax > vmin else np.zeros_like(v)
    x = t * (len(stops) - 1)
    i = np.clip(np.floor(x).astype(int), 0, len(stops) - 2)
    f = (x - i)[:, None]
    rgb = stops[i] * (1 - f) + stops[i + 1] * f
    rgb[~np.isfinite(v)] = (160, 160, 160)
    return rgb.round().astype(np.uint8)


def nice_range(values: np.ndarray, vmin: float | None = None, vmax: float | None = None) -> tuple[float, float]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    lo = float(v.min()) if vmin is None and v.size else (vmin if vmin is not None else 0.0)
    hi = float(v.max()) if vmax is None and v.size else (vmax if vmax is not None else 1.0)
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _projection(cells: np.ndarray, normals: np.ndarray) -> tuple[np.ndarray, str]:
    n = normals.mean(axis=0)
    n = n / max(np.linalg.norm(n), 1e-12)
    if abs(n[2]) > 0.7:
        return cells[..., :2], "plan"
    u = np.cross([0.0, 0.0, 1.0], n)
    u /= max(np.linalg.norm(u), 1e-12)
    return np.stack([cells @ u, cells[..., 2]], axis=-1), "elevation"


def render_grid_png(cells: np.ndarray, normals: np.ndarray, values: np.ndarray, path: str | Path, title: str,
                    unit: str, vmin: float | None = None, vmax: float | None = None, ramp: str = "viridis",
                    width_px: int = 1000, outlines: list[np.ndarray] | None = None) -> dict:
    """Plan (or elevation) image of a sensor grid's cells coloured by value, with a legend."""
    from PIL import Image, ImageDraw, ImageFont
    lo, hi = nice_range(values, vmin, vmax)
    xy, view = _projection(np.asarray(cells, dtype=float), np.asarray(normals, dtype=float))
    mn, mx = xy.reshape(-1, 2).min(axis=0), xy.reshape(-1, 2).max(axis=0)
    span = np.maximum(mx - mn, 1e-6)
    margin, legend_w, title_h = 40, 150, 50
    plot_w = width_px - 2 * margin - legend_w
    scale = plot_w / span[0]
    plot_h = int(span[1] * scale)
    if plot_h > 1400:
        scale *= 1400 / plot_h
        plot_h = 1400
    H = plot_h + 2 * margin + title_h
    img = Image.new("RGB", (width_px, max(H, 360)), (250, 250, 248))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 15)
        small = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font = small = ImageFont.load_default()
    colors = colorize(values, lo, hi, ramp)

    def px(p):
        return (margin + (p[0] - mn[0]) * scale, margin + title_h + plot_h - (p[1] - mn[1]) * scale)

    for quad, col in zip(xy, colors):
        d.polygon([px(p) for p in quad], fill=tuple(int(c) for c in col))
    for poly in outlines or []:
        pts = [px(p) for p in poly]
        d.line(pts + pts[:1], fill=(40, 40, 40), width=2)
    d.text((margin, 14), title, fill=(20, 20, 20), font=font)
    # legend
    lx = width_px - legend_w + 10
    ly0, ly1 = margin + title_h, margin + title_h + min(plot_h, 320)
    steps = 64
    for k in range(steps):
        c = colorize(np.array([lo + (hi - lo) * (1 - k / (steps - 1))]), lo, hi, ramp)[0]
        y = ly0 + (ly1 - ly0) * k / steps
        d.rectangle([lx, y, lx + 22, y + (ly1 - ly0) / steps + 1], fill=tuple(int(x) for x in c))
    for k in range(5):
        val = hi - (hi - lo) * k / 4
        y = ly0 + (ly1 - ly0) * k / 4
        d.text((lx + 28, y - 7), _fmt(val), fill=(20, 20, 20), font=small)
    d.text((lx, ly1 + 10), unit, fill=(20, 20, 20), font=small)
    # scale bar (1, 2, 5, 10 ... m)
    target = span[0] / 5
    bar = 10 ** math.floor(math.log10(target)) if target > 0 else 1
    barm = bar
    for m in (2, 5):
        if bar * m <= target:
            barm = bar * m
    x0, y0 = margin, H - 22
    d.line([(x0, y0), (x0 + barm * scale, y0)], fill=(20, 20, 20), width=3)
    d.text((x0 + barm * scale + 6, y0 - 8), f"{_fmt(barm)} m", fill=(20, 20, 20), font=small)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return {"path": str(path), "view": view, "range": [lo, hi]}


def _fmt(v: float) -> str:
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 100:
        return f"{v:.0f}"
    if a >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


def legend_geometry(cells: np.ndarray, lo: float, hi: float, unit: str, title: str, ramp: str = "viridis",
                    steps: int = 10, normals: np.ndarray | None = None) -> tuple[list, list]:
    """Legend quads and labels (metres) beside the result grid, for drawing in Rhino: lying flat
    beside a plan grid, standing upright (in the XZ plane) beside a 3D one, so it reads in a
    perspective view either way."""
    pts = np.asarray(cells, dtype=float).reshape(-1, 3)
    mn, mx = pts.min(axis=0), pts.max(axis=0)
    flat = normals is None or float(np.abs(np.asarray(normals)[:, 2]).mean()) > 0.7
    size = max(mx[0] - mn[0], mx[1] - mn[1], 1.0) if flat else max(mx[0] - mn[0], mx[2] - mn[2], 1.0)
    w, h = 0.04 * size, 0.06 * size
    x0 = mx[0] + 0.08 * size

    def at(x, v):          # v runs up the legend: +Y on a plan, +Z upright
        return [x, mn[1] + v, mx[2]] if flat else [x, mn[1], mn[2] + v]
    quads, labels = [], []
    for k in range(steps):
        val = lo + (hi - lo) * (k + 0.5) / steps
        col = colorize(np.array([val]), lo, hi, ramp)[0]
        quads.append(([at(x0, k * h), at(x0 + w, k * h), at(x0 + w, (k + 1) * h), at(x0, (k + 1) * h)],
                      tuple(int(c) for c in col)))
    for k in range(0, steps + 1, max(1, steps // 5)):
        labels.append((tuple(at(x0 + w * 1.6, k * h)), _fmt(lo + (hi - lo) * k / steps)))
    # title above the bar, pushed right so its (screen-sized) dot does not cover the grid
    labels.append((tuple(at(x0 + 3 * w, (steps + 2.5) * h)), f"{title} [{unit}]"))
    return quads, labels
