"""Render a .ghx canvas layout to PNG from the archive alone (nothing is solved).

python render_canvas.py <in.ghx> <out.png>
"""
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from annotate_ghx import Obj, build_graph  # noqa: E402
from ghx_inspect import first, items, text  # noqa: E402


def argb(s, default=(0.8, 0.8, 0.8, 0.4)):
    try:
        a, r, g, b = (int(v) / 255 for v in s.split(";"))
        return r, g, b, a
    except (AttributeError, ValueError):
        return default


def main():
    root = ET.parse(sys.argv[1]).getroot()
    dobj = first(first(root, "Definition"), "DefinitionObjects")
    objs = [Obj(el) for el in dobj.find("chunks").findall("chunk") if first(el, "Container") is not None]
    build_graph(objs)
    by_guid = {o.guid: o for o in objs}
    bounds = {o.guid: o.bounds() for o in objs if not o.is_group and o.bounds()}
    xs = [b[0] for b in bounds.values()] + [b[0] + b[2] for b in bounds.values()]
    ys = [b[1] for b in bounds.values()] + [b[1] + b[3] for b in bounds.values()]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    scale = min(1.0, 3600 / max(w, 1))
    fig = plt.figure(figsize=(max(6, w * scale / 100), max(3, h * scale / 100)), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(min(xs) - 20, max(xs) + 20)
    ax.set_ylim(max(ys) + 20, min(ys) - 20)
    ax.axis("off")
    fig.patch.set_facecolor("#d4d4d4")

    def union(guids):
        bs = [bounds[g] for g in guids if g in bounds]
        if not bs:
            return None
        x0, y0 = min(b[0] for b in bs), min(b[1] for b in bs)
        return x0 - 8, y0 - 8, max(b[0] + b[2] for b in bs) - x0 + 16, max(b[1] + b[3] for b in bs) - y0 + 16

    for g in (o for o in objs if o.is_group):
        r = union([i.text for i in items(g.container).get("ID", [])])
        if r:
            col = items(g.container).get("Colour")
            ax.add_patch(mpatches.FancyBboxPatch((r[0], r[1]), r[2], r[3], boxstyle="round,pad=2",
                                                 fc=argb("".join(col[0].itertext()).strip() if col else None), ec="#555", lw=0.6))
    for o in objs:
        for p in o.preds:
            if p.guid in bounds and o.guid in bounds:
                a, b = bounds[p.guid], bounds[o.guid]
                x0, y0, x1, y1 = a[0] + a[2], a[1] + a[3] / 2, b[0], b[1] + b[3] / 2
                dx = max(30, abs(x1 - x0) / 2)
                path = MPath([(x0, y0), (x0 + dx, y0), (x1 - dx, y1), (x1, y1)], [1, 4, 4, 4])
                ax.add_patch(mpatches.PathPatch(path, fc="none", ec="#333", lw=0.5, alpha=0.6))
    for o in objs:
        if o.is_group or o.guid not in bounds:
            continue
        x, y, bw, bh = bounds[o.guid]
        if o.type == "Scribble":
            size = float(text(o.container, "Size") or 12)
            ax.text(x, y, text(o.container, "Text") or "", fontsize=max(5, size * scale * 0.55), va="top", weight="bold")
            continue
        if o.type == "Panel":
            props = first(o.container, "PanelProperties")
            col = items(props).get("Colour") if props is not None else None
            ax.add_patch(mpatches.Rectangle((x, y), bw, bh, fc=argb("".join(col[0].itertext()).strip() if col else None,
                                                                     (1, 1, 0.8, 1)), ec="#777", lw=0.5))
            body = text(o.container, "UserText") or ""
            cols = max(20, int((bw - 12) / 7.0))
            lines = [w for para in body.splitlines() for w in (textwrap.wrap(para, cols) or [""])]
            lines = lines[: max(1, int(bh / 21.5))]
            t = ax.text(x + 3, y + 3, chr(10).join(lines), fontsize=max(3, 6 * scale), va="top", linespacing=1.15)
            t.set_clip_path(mpatches.Rectangle((x, y), bw, bh, transform=ax.transData))
            continue
        face = "#f4f4f4" if "Slider" in (o.type or "") or o.type in ("Boolean Toggle", "Value List") else "#bdbdbd"
        ax.add_patch(mpatches.Rectangle((x, y), bw, bh, fc=face, ec="#222", lw=0.6))
        label = o.nickname if o.nickname and "Slider" in (o.type or "") else (o.type or "")
        ax.text(x + bw / 2, y + bh / 2, label[:28], fontsize=max(3, 6 * scale), ha="center", va="center")
    fig.savefig(sys.argv[2], facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
