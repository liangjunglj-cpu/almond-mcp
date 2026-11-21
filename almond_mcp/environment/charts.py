"""Report charts (line, stacked-bar and bar charts) in the diagrams' visual language.

Built on ``diagrams.Canvas``, so every chart renders to SVG for the panel and to PNG for reports with the
same paper, ink and mono labels as the architectural diagrams. Used for climate summaries (monthly
diurnal averages), thermal case comparisons (operative temperature over a week, hourly energy balance)
and daylight case comparisons.
"""
from __future__ import annotations

import math

import numpy as np

from .diagrams import AMBER, GREEN, HAIR, INK, LINE, MUTED, OUTLINE, PAPER, RED, Canvas

BLUE = "#3b6ea8"
PURPLE = "#7d5aa3"
TEAL = "#4f8f8b"
SERIES = (INK, RED, GREEN, BLUE, AMBER, PURPLE, TEAL, MUTED)


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if not math.isfinite(lo) or not math.isfinite(hi):
        return [0.0]
    if hi - lo < 1e-9:
        hi = lo + 1.0
    raw = (hi - lo) / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    start = math.floor(lo / step) * step
    out, v = [], start
    while v <= hi + 1e-9 * step:
        out.append(round(v, 10))
        v += step
    return out


def _fmt(v: float, step: float | None = None) -> str:
    """A tick or bar label; with ``step`` (the tick spacing) as many decimals as the spacing needs."""
    if step:
        exp = math.floor(math.log10(abs(step)) + 1e-9)
        dec = max(0, -exp + (1 if round(abs(step) / 10 ** exp, 6) == 2.5 else 0))
        s = f"{v:.{dec}f}"
        return "0" if float(s) == 0 else s
    return f"{v:.0f}" if abs(v) >= 10 or float(v).is_integer() else (f"{v:.1f}" if abs(v) >= 0.1 else f"{v:.2g}")


class Frame:
    """A plot area with a y axis (and optional second y axis) on a Canvas."""

    def __init__(self, c: Canvas, x0: float, y0: float, w: float, h: float, ylo: float, yhi: float,
                 ylabel: str = "", y2: tuple[float, float, str] | None = None):
        self.c, self.x0, self.y0, self.w, self.h = c, x0, y0, w, h
        ticks = _ticks(ylo, yhi)
        self.ylo, self.yhi = min(ticks[0], ylo), max(ticks[-1], yhi)
        step = ticks[1] - ticks[0] if len(ticks) > 1 else None
        for t in ticks:
            y = self.y(t)
            c.line([(x0, y), (x0 + w, y)], LINE, HAIR)
            c.text(x0 - 5, y + 3, _fmt(t, step), 8, MUTED, mono=True, anchor="end")
        if self.ylo < 0 < self.yhi:
            c.line([(x0, self.y(0)), (x0 + w, self.y(0))], INK, HAIR)
        c.line([(x0, y0), (x0, y0 + h)], INK, HAIR)
        c.line([(x0, y0 + h), (x0 + w, y0 + h)], INK, HAIR)
        if ylabel:
            c.text(x0, y0 - 8, ylabel.upper(), 8, MUTED, mono=True)
        self.y2 = None
        if y2:
            t2 = _ticks(y2[0], y2[1])
            self.y2 = (min(t2[0], y2[0]), max(t2[-1], y2[1]))
            step2 = t2[1] - t2[0] if len(t2) > 1 else None
            for t in t2:
                c.text(x0 + w + 5, self.yb(t) + 3, _fmt(t, step2), 8, MUTED, mono=True)
            c.line([(x0 + w, y0), (x0 + w, y0 + h)], INK, HAIR)
            c.text(x0 + w, y0 - 8, y2[2].upper(), 8, MUTED, mono=True, anchor="end")

    def y(self, v: float) -> float:
        return self.y0 + self.h * (1 - (v - self.ylo) / (self.yhi - self.ylo))

    def yb(self, v: float) -> float:
        lo, hi = self.y2
        return self.y0 + self.h * (1 - (v - lo) / (hi - lo))

    def x(self, f: float) -> float:
        """f in 0..1 across the plot."""
        return self.x0 + self.w * f


def legend(c: Canvas, x: float, y: float, items: list[tuple[str, str, str | None]], per_row: int = 4, step: float = 150):
    """items: (label, colour, dash or None). Swatch lines, wrapped into rows."""
    for k, (label, col, dash) in enumerate(items):
        xx, yy = x + (k % per_row) * step, y + (k // per_row) * 14
        c.line([(xx, yy - 3), (xx + 16, yy - 3)], col, 2.0, dash)
        c.text(xx + 21, yy, label, 9, INK)


def line_chart(series: list[dict], x_labels: list[tuple[float, str]], title: str, ylabel: str,
               width: float = 760, height: float = 360, y_range: tuple[float, float] | None = None,
               bands: list[tuple[float, float, str]] | None = None, note: str = "") -> Canvas:
    """series: {"label", "y" (sequence), "colour", "width", "dash"}; all share the x positions 0..n-1.
    x_labels: (fraction 0..1, text) along the bottom. bands: shaded vertical spans (f0, f1, colour)."""
    c = Canvas(width, height, background=PAPER)
    c.text(16, 22, title, 12, INK, weight="bold")
    ys = np.concatenate([np.asarray(s["y"], float) for s in series]) if series else np.zeros(1)
    lo, hi = y_range or (float(np.nanmin(ys)), float(np.nanmax(ys)))
    rows = math.ceil(len(series) / 4)
    f = Frame(c, 50, 52, width - 76, height - 96 - 14 * rows, lo, hi, ylabel)
    for f0, f1, col in bands or []:
        c.rect(f.x(f0), f.y0, f.x(f1) - f.x(f0), f.h, fill=col, stroke=None)
    for fx, label in x_labels:
        x = f.x(fx)
        c.line([(x, f.y0 + f.h), (x, f.y0 + f.h + 4)], INK, HAIR)
        c.text(x, f.y0 + f.h + 15, label, 8, MUTED, mono=True, anchor="middle")
    for s in series:
        y = np.asarray(s["y"], float)
        n = len(y)
        pts = [(f.x(i / max(n - 1, 1)), f.y(v)) for i, v in enumerate(y) if math.isfinite(v)]
        if len(pts) > 1:
            c.line(pts, s.get("colour", INK), s.get("width", OUTLINE), s.get("dash"))
    legend(c, 50, height - 22 - 14 * (rows - 1), [(s["label"], s.get("colour", INK), s.get("dash")) for s in series])
    if note:
        c.text(width - 16, 22, note, 8, MUTED, mono=True, anchor="end")
    return c


def stacked_bars(categories: list[str], stacks: list[dict], title: str, ylabel: str, width: float = 760,
                 height: float = 380, line: dict | None = None, note: str = "") -> Canvas:
    """stacks: {"label", "values" (one per category), "colour"}. Positive values stack up from zero and
    negative values stack down, so gains and losses read on one chart. line: an optional overlaid series."""
    c = Canvas(width, height, background=PAPER)
    c.text(16, 22, title, 12, INK, weight="bold")
    V = np.array([np.asarray(s["values"], float) for s in stacks]) if stacks else np.zeros((1, len(categories)))
    up = np.where(V > 0, V, 0).sum(axis=0)
    dn = np.where(V < 0, V, 0).sum(axis=0)
    lo, hi = float(min(dn.min(), 0)), float(max(up.max(), 0))
    if line:
        lv = np.asarray(line["values"], float)
        lo, hi = min(lo, float(lv.min())), max(hi, float(lv.max()))
    rows = math.ceil((len(stacks) + (1 if line else 0)) / 4)
    f = Frame(c, 56, 52, width - 80, height - 100 - 14 * rows, lo, hi, ylabel)
    n = max(len(categories), 1)
    bw = f.w / n * 0.72
    for j, cat in enumerate(categories):
        xc = f.x((j + 0.5) / n)
        pos = neg = 0.0
        for s, v in zip(stacks, V[:, j]):
            if v == 0 or not math.isfinite(v):
                continue
            base = pos if v > 0 else neg
            top = base + v
            y0, y1 = f.y(base), f.y(top)
            c.rect(xc - bw / 2, min(y0, y1), bw, abs(y1 - y0), fill=s["colour"], stroke=None)
            if v > 0:
                pos = top
            else:
                neg = top
        if n <= 31 or j % max(1, n // 24) == 0:
            c.text(xc, f.y0 + f.h + 14, cat, 8, MUTED, mono=True, anchor="middle")
    items = [(s["label"], s["colour"], None) for s in stacks]
    if line:
        pts = [(f.x((j + 0.5) / n), f.y(v)) for j, v in enumerate(lv)]
        c.line(pts, line.get("colour", INK), 1.6, line.get("dash"))
        items.append((line["label"], line.get("colour", INK), line.get("dash")))
    legend(c, 56, height - 22 - 14 * (rows - 1), items)
    if note:
        c.text(width - 16, 22, note, 8, MUTED, mono=True, anchor="end")
    return c


def bar_chart(labels: list[str], values: list[float | None], title: str, ylabel: str, width: float = 520,
              height: float = 300, colour: str = INK, refs: list[tuple[float, str, str]] | None = None) -> Canvas:
    """One bar per label; refs are horizontal reference lines (value, label, colour), e.g. a target."""
    c = Canvas(width, height, background=PAPER)
    c.text(16, 22, title, 12, INK, weight="bold")
    vals = [v if v is not None and math.isfinite(v) else 0.0 for v in values]
    hi = max(vals + [r[0] for r in refs or []] + [1e-6])
    f = Frame(c, 50, 52, width - 70, height - 96, 0.0, hi * 1.08, ylabel)
    n = max(len(labels), 1)
    bw = f.w / n * 0.6
    for j, (lab, v, raw) in enumerate(zip(labels, vals, values)):
        xc = f.x((j + 0.5) / n)
        if raw is not None:
            c.rect(xc - bw / 2, f.y(v), bw, f.y(0) - f.y(v), fill=colour, stroke=None)
            c.text(xc, f.y(v) - 4, _fmt(v), 8, INK, mono=True, anchor="middle")
        c.text(xc, f.y0 + f.h + 14, lab, 9, INK, anchor="middle")
    for v, lab, col in refs or []:
        c.line([(f.x0, f.y(v)), (f.x0 + f.w, f.y(v))], col, 1.2, "5 3")
        c.text(f.x0 + f.w, f.y(v) - 4, lab, 8, col, mono=True, anchor="end")
    return c


def save(c: Canvas, stem, title: str = "") -> dict:
    """Write <stem>.svg and <stem>.png next to each other; returns both paths."""
    from pathlib import Path
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    svg = stem.with_suffix(".svg")
    svg.write_text(c.svg(title), encoding="utf-8")
    png = c.png(str(stem.with_suffix(".png")))
    return {"svg": str(svg), "png": str(png)}
