"""Almond's structural reference library: benchmarked building typologies as parametric line models.

Twelve typologies (moment frame, braced tower, Pratt truss, portal, warehouse, space grid, arch,
L-bracket, canopy, diagrid, Vierendeel girder, mixed supports) are built directly as ``frame_solver``
models, in SI (m, kN). They are the models the native solver is verified against: closed forms in
``tests/test_structural_typologies.py`` (method of joints, virtual work, the force method, funicular
statics) and OpenSees cross-checks in ``benchmarks/``. This module makes them usable from Almond:

- :class:`ReferenceLibrary` reads ``StructuralReferences/catalogue.json`` (titles, parameters with
  ranges, the default study, teaching notes) and validates user parameters;
- :func:`to_model` turns a built frame into the bridge's conditioned-model JSON (members with sections
  and releases, typed supports, explicit G/Q loads): the shape ``validate_structure`` analyses, so
  :func:`analyze` runs ``native_structure.validate`` on it with no Rhino session;
- :func:`closed_form_checks` compares the Almond result with the textbook value where one exists;
- :func:`place_script` writes the C# that draws a reference in Rhino with ``almond:section``,
  ``almond:release`` and ``almond:support`` user text, ready for ``validate_structure`` and
  ``visualize_structure``.

``ALL`` and ``refined`` keep the benchmark interface (``tests/structural_typologies.py`` re-exports them).
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

import numpy as np

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns

S355 = fs.material("S355")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Typology builders (benchmarked; see benchmarks/README.md)
# ══════════════════════════════════════════════════════════════════════════════════════════════
class Grid:
    """Node registry that merges coincident coordinates."""

    def __init__(self, frame):
        self.f, self.map = frame, {}

    def n(self, x, y, z):
        k = (round(x, 6), round(y, 6), round(z, 6))
        if k not in self.map:
            self.map[k] = self.f.add_node((x, y, z))
        return self.map[k]


def in_plane(frame, nodes=None):
    """Restrain out-of-plane (y) translation and rotations about x and z: a planar x-z model."""
    for n in nodes if nodes is not None else range(len(frame.nodes)):
        old = frame.supports.get(n, (False,) * 6)
        frame.fix(n, (old[0], True, old[2], True, old[4], True))


def moment_frame(bx=3, by=2, storeys=6, bay=6.0, h=3.5, wind=10.0, open_sections=False):
    """Rigid 3D moment frame, fixed bases, beam UDLs (G, Q) and wind on the windward face (W)."""
    if open_sections:
        col, bm_x, bm_y = fs.i_section(300, 300, 11, 19), fs.i_section(400, 180, 8.6, 13.5), fs.i_section(300, 150, 7.1, 10.7)
    else:
        col, bm_x, bm_y = fs.rhs(300, 300, 16), fs.rhs(400, 200, 12.5), fs.rhs(300, 150, 10)
    f = fs.Frame()
    g = Grid(f)
    for i in range(bx + 1):
        for j in range(by + 1):
            f.fix(g.n(i * bay, j * bay, 0))
    for s in range(storeys):
        z0, z1 = s * h, (s + 1) * h
        for i in range(bx + 1):
            for j in range(by + 1):
                f.add_element(g.n(i * bay, j * bay, z0), g.n(i * bay, j * bay, z1), col, S355)
        for i in range(bx):
            for j in range(by + 1):
                e = f.add_element(g.n(i * bay, j * bay, z1), g.n((i + 1) * bay, j * bay, z1), bm_x, S355)
                f.udl(e, (0, 0, -15), "G")
                f.udl(e, (0, 0, -10), "Q")
        for i in range(bx + 1):
            for j in range(by):
                e = f.add_element(g.n(i * bay, j * bay, z1), g.n(i * bay, (j + 1) * bay, z1), bm_y, S355)
                f.udl(e, (0, 0, -5), "G")
                f.udl(e, (0, 0, -3), "Q")
        for j in range(by + 1):
            f.load(g.n(0, j * bay, z1), fx=wind, case="W")
    f.gravity = (0, 0, -1)
    return {"frame": f, "combos": {"ULS gravity": {"G": 1.35, "Q": 1.5}, "ULS wind": {"G": 1.35, "Q": 1.05, "W": 1.5}}}


def braced_tower(n=3, storeys=8, bay=6.0, h=3.6, wind=12.0, plan_bracing=False):
    """Pinned-base tower, simple beams (major axis pinned), X braces (truss bars) in the middle bay of
    every face. Without ``plan_bracing`` the floors have no diaphragm: only the beams' weak axis ties
    them in plan, which buckles below the design load (a real, correctly found instability)."""
    f = fs.Frame()
    g = Grid(f)
    col, br = fs.rhs(300, 300, 16), fs.chs(219.1, 10)
    bx, by = fs.rhs(400, 200, 12.5), fs.rhs(300, 150, 10)
    for i in range(n + 1):
        for j in range(n + 1):
            f.pin(g.n(i * bay, j * bay, 0))
    mid = n // 2
    for s in range(storeys):
        z0, z1 = s * h, (s + 1) * h
        for i in range(n + 1):
            for j in range(n + 1):
                f.add_element(g.n(i * bay, j * bay, z0), g.n(i * bay, j * bay, z1), col, S355)
        for i in range(n):
            for j in range(n + 1):
                e = f.add_element(g.n(i * bay, j * bay, z1), g.n((i + 1) * bay, j * bay, z1), bx, S355,
                                  releases=fs.release_mask(True, True, minor=False))
                f.udl(e, (0, 0, -18), "G")
                f.udl(e, (0, 0, -9), "Q")
        for i in range(n + 1):
            for j in range(n):
                f.add_element(g.n(i * bay, j * bay, z1), g.n(i * bay, (j + 1) * bay, z1), by, S355,
                              releases=fs.release_mask(True, True, minor=False))
        for (a, b) in (((mid, 0), (mid + 1, 0)), ((mid, n), (mid + 1, n)), ((0, mid), (0, mid + 1)), ((n, mid), (n, mid + 1))):
            f.add_element(g.n(a[0] * bay, a[1] * bay, z0), g.n(b[0] * bay, b[1] * bay, z1), br, S355, truss=True)
            f.add_element(g.n(b[0] * bay, b[1] * bay, z0), g.n(a[0] * bay, a[1] * bay, z1), br, S355, truss=True)
        if plan_bracing:
            for (x0, y0) in ((0, 0), ((n - 1) * bay, 0), (0, (n - 1) * bay), ((n - 1) * bay, (n - 1) * bay)):
                f.add_element(g.n(x0, y0, z1), g.n(x0 + bay, y0 + bay, z1), fs.chs(168.3, 8), S355, truss=True)
        for j in range(n + 1):
            f.load(g.n(0, j * bay, z1), fx=wind, case="W")
    f.gravity = (0, 0, -1)
    return {"frame": f, "combos": {"ULS gravity": {"G": 1.35, "Q": 1.5}, "ULS wind": {"G": 1.35, "Q": 1.05, "W": 1.5}}}


def pratt_truss(span=40.0, panels=10, depth=4.0, P=50.0):
    """Pin-jointed planar Pratt truss on a pin and a roller, top-chord point loads (statically
    determinate: method of joints is exact)."""
    f = fs.Frame()
    ch, web = fs.chs(273, 12.5), fs.chs(168.3, 8)
    a = span / panels
    bot = [f.add_node((i * a, 0, 0)) for i in range(panels + 1)]
    top = {i: f.add_node((i * a, 0, depth)) for i in range(1, panels)}
    half = panels // 2
    for i in range(panels):
        f.add_element(bot[i], bot[i + 1], ch, S355, truss=True)
    for i in range(1, panels - 1):
        f.add_element(top[i], top[i + 1], ch, S355, truss=True)
    for i in range(1, panels):
        f.add_element(bot[i], top[i], web, S355, truss=True)
    f.add_element(bot[0], top[1], ch, S355, truss=True)
    f.add_element(bot[panels], top[panels - 1], ch, S355, truss=True)
    for i in range(1, panels - 1):
        f.add_element(top[i], bot[i + 1], web, S355, truss=True) if i < half else f.add_element(top[i + 1], bot[i], web, S355, truss=True)
    for nd in range(len(f.nodes)):
        f.fix(nd, (False, True, False, False, False, False))
    f.fix(bot[0], (True, True, True, False, False, False))
    f.fix(bot[-1], (False, True, True, False, False, False))
    for i in range(1, panels):
        f.load(top[i], fz=-P, case="Q")
    return {"frame": f, "combos": {"Q": {"Q": 1.0}}, "mid_node": bot[half], "supports": (bot[0], bot[-1])}


def portal_2d(span=30.0, h=6.0, rise=1.6, w=6.0):
    """Pinned-base gable portal (rigid eaves and apex), planar, vertical UDL w per plan length on the rafters."""
    f = fs.Frame()
    sec = fs.rhs(450, 250, 12.5)
    A, B, C = f.add_node((0, 0, 0)), f.add_node((0, 0, h)), f.add_node((span / 2, 0, h + rise))
    D, E = f.add_node((span, 0, h)), f.add_node((span, 0, 0))
    f.add_element(A, B, sec, S355)
    r1 = f.add_element(B, C, sec, S355)
    r2 = f.add_element(C, D, sec, S355)
    f.add_element(D, E, sec, S355)
    f.pin(A)
    f.pin(E)
    in_plane(f)
    Lr = math.hypot(span / 2, rise)
    for e in (r1, r2):
        f.udl(e, (0, 0, -w * (span / 2) / Lr), "Q")
    return {"frame": f, "combos": {"Q": {"Q": 1.0}}, "nodes": (A, B, C, D, E), "section": sec,
            "geometry": {"span": span, "h": h, "rise": rise, "w": w}}


def warehouse(span=30.0, h=6.0, rise=1.6, frames=6, spacing=6.0, g=0.5, q=0.6):
    """Pitched portal frames (pinned bases) tied by pinned purlins, X bracing (bars) in the end bays."""
    f = fs.Frame()
    G = Grid(f)
    frm, pur, br = fs.rhs(450, 250, 12.5), fs.chs(139.7, 5), fs.chs(88.9, 5)
    ts = [0, 0.25, 0.5, 0.75, 1.0]
    line = sorted({(round(t * span / 2, 6), round(h + t * rise, 6)) for t in ts} |
                  {(round(span - t * span / 2, 6), round(h + t * rise, 6)) for t in ts})
    for k in range(frames):
        y = k * spacing
        trib = spacing / 2 if k in (0, frames - 1) else spacing
        for x in (0, span):
            f.pin(G.n(x, y, 0))
            f.add_element(G.n(x, y, 0), G.n(x, y, h), frm, S355)
        for (xa, za), (xb, zb) in zip(line, line[1:]):
            e = f.add_element(G.n(xa, y, za), G.n(xb, y, zb), frm, S355)
            cos = abs(xb - xa) / math.hypot(xb - xa, zb - za)
            f.udl(e, (0, 0, -g * trib * cos), "G")
            f.udl(e, (0, 0, -q * trib * cos), "Q")
    for k in range(frames - 1):
        for (x, z) in line:
            f.add_element(G.n(x, k * spacing, z), G.n(x, (k + 1) * spacing, z), pur, S355,
                          releases=fs.release_mask(True, True, minor=True))
    for k in (0, frames - 2):
        y0, y1 = k * spacing, (k + 1) * spacing
        for x in (0, span):
            f.add_element(G.n(x, y0, 0), G.n(x, y1, h), br, S355, truss=True)
            f.add_element(G.n(x, y1, 0), G.n(x, y0, h), br, S355, truss=True)
        for (xa, za), (xb, zb) in zip(line, line[1:]):
            f.add_element(G.n(xa, y0, za), G.n(xb, y1, zb), br, S355, truss=True)
            f.add_element(G.n(xa, y1, za), G.n(xb, y0, zb), br, S355, truss=True)
    f.gravity = (0, 0, -1)
    return {"frame": f, "combos": {"ULS snow": {"G": 1.35, "Q": 1.5}}}


def space_grid(nx=12, module=2.0, depth=1.5, g=1.0, q=1.5):
    """Square-on-square double-layer grid of bars, pinned at edge columns every 3 modules."""
    f = fs.Frame()
    G = Grid(f)
    ch, di = fs.chs(114.3, 5), fs.chs(88.9, 4)
    top = lambda i, j: G.n(i * module, j * module, depth)
    bot = lambda i, j: G.n((i + .5) * module, (j + .5) * module, 0)
    for i in range(nx):
        for j in range(nx + 1):
            f.add_element(top(i, j), top(i + 1, j), ch, S355, truss=True)
            f.add_element(top(j, i), top(j, i + 1), ch, S355, truss=True)
    for i in range(nx - 1):
        for j in range(nx):
            f.add_element(bot(i, j), bot(i + 1, j), ch, S355, truss=True)
            f.add_element(bot(j, i), bot(j, i + 1), ch, S355, truss=True)
    for i in range(nx):
        for j in range(nx):
            for di_, dj in ((0, 0), (1, 0), (0, 1), (1, 1)):
                f.add_element(bot(i, j), top(i + di_, j + dj), di, S355, truss=True)
    for i in range(nx + 1):
        for j in range(nx + 1):
            if i in (0, nx) or j in (0, nx):
                if i % 3 == 0 and j % 3 == 0:
                    f.pin(top(i, j))
            else:
                f.load(top(i, j), fz=-g * module ** 2, case="G")
                f.load(top(i, j), fz=-q * module ** 2, case="Q")
    f.gravity = (0, 0, -1)
    return {"frame": f, "combos": {"ULS": {"G": 1.35, "Q": 1.5}}}


def arch(span=40.0, rise=8.0, n=32, w=20.0, ends="pinned"):
    """Planar parabolic arch, nodal loads w*dx at every interior node (funicular for the polygon)."""
    f = fs.Frame()
    sec = fs.chs(406.4, 12)
    xs = np.linspace(0, span, n + 1)
    nodes = [f.add_node((x, 0, 4 * rise * x * (span - x) / span ** 2)) for x in xs]
    for a, b in zip(nodes, nodes[1:]):
        f.add_element(a, b, sec, S355)
    for nd in (nodes[0], nodes[-1]):
        f.fix(nd) if ends == "fixed" else f.pin(nd)
    in_plane(f)
    dx = span / n
    for nd in nodes[1:-1]:
        f.load(nd, fz=-w * dx, case="Q")
    # thrust: midspan moment of the equivalent simply supported beam under the same nodal loads / rise
    P, mid = w * dx, span / 2
    M0 = P * (n - 1) / 2 * mid - sum(P * (mid - x) for x in xs[1:-1] if x < mid)
    return {"frame": f, "combos": {"Q": {"Q": 1.0}}, "nodes": nodes, "thrust": M0 / rise, "M0": M0}


def l_bracket(a=3.0, b=2.0, P=10.0):
    """Horizontal L-shaped cantilever with a tip load: bending of both arms plus torsion of the first."""
    f = fs.Frame()
    sec = fs.chs(168.3, 6.3)
    n0, n1, n2 = f.add_node((0, 0, 3)), f.add_node((a, 0, 3)), f.add_node((a, b, 3))
    f.add_element(n0, n1, sec, S355)
    f.add_element(n1, n2, sec, S355)
    f.fix(n0)
    f.load(n2, fz=-P, case="Q")
    EI, GJ = S355.E * sec.Iy, S355.G * sec.J
    tip = P * b ** 3 / (3 * EI) + P * a ** 3 / (3 * EI) + P * b ** 2 * a / GJ
    return {"frame": f, "combos": {"Q": {"Q": 1.0}}, "tip": n2, "tip_deflection": tip, "torsion": P * b}


def canopy(n=5, out=5.0, spacing=3.0, back=2.0):
    """Cantilever canopy: columns with back-spanned cantilever beams tied by an edge beam, corner load."""
    f = fs.Frame()
    G = Grid(f)
    bm, ed, col = fs.rhs(300, 200, 10), fs.rhs(200, 100, 8), fs.chs(323.9, 12.5)
    tips = []
    for k in range(n):
        y = k * spacing
        base, top = G.n(0, y, 0), G.n(0, y, 4.0)
        f.fix(base)
        f.add_element(base, top, col, S355)
        tip = G.n(out, y, 4.0)
        e = f.add_element(top, tip, bm, S355)
        f.udl(e, (0, 0, -1.0 * spacing), "G")
        f.udl(e, (0, 0, -1.5 * spacing), "Q")
        f.add_element(G.n(-back, y, 4.0), top, bm, S355)
        tips.append(tip)
    for a, b in zip(tips, tips[1:]):
        f.udl(f.add_element(a, b, ed, S355), (0, 0, -3.0), "Q")
    f.load(tips[0], fz=-15.0, case="Q")
    f.gravity = (0, 0, -1)
    return {"frame": f, "combos": {"ULS": {"G": 1.35, "Q": 1.5}}}


def diagrid(radius=10.0, nseg=12, levels=6, h=4.0, wind=8.0, rot_deg=0.0, offset=(0.0, 0.0, 0.0)):
    """Cylindrical diagrid tower with ring beams; ``rot_deg``/``offset`` move the whole model (and
    the wind direction) rigidly, for invariance checks."""
    f = fs.Frame()
    G = Grid(f)
    dg, rb = fs.chs(355.6, 16), fs.chs(219.1, 10)
    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))

    def P(k, lev):
        th = 2 * math.pi * (k + 0.5 * (lev % 2)) / nseg
        x, y = radius * math.cos(th), radius * math.sin(th)
        return (c * x - s * y + offset[0], s * x + c * y + offset[1], lev * h + offset[2])

    for k in range(nseg):
        f.fix(G.n(*P(k, 0)))
    for lev in range(levels):
        for k in range(nseg):
            a = G.n(*P(k, lev))
            nxt = (k, k - 1) if lev % 2 == 0 else (k, k + 1)
            for kk in nxt:
                f.add_element(a, G.n(*P(kk, lev + 1)), dg, S355)
        for k in range(nseg):
            e = f.add_element(G.n(*P(k, lev + 1)), G.n(*P(k + 1, lev + 1)), rb, S355)
            f.udl(e, (0, 0, -25.0), "G")
            f.udl(e, (0, 0, -12.0), "Q")
            f.load(G.n(*P(k, lev + 1)), fx=wind / nseg * c, fy=wind / nseg * s, case="W")
    f.gravity = (0, 0, -1)
    return {"frame": f, "combos": {"ULS wind": {"G": 1.35, "Q": 1.05, "W": 1.5}}}


def vierendeel(span=12.0, depth=1.5, panels=6, P=30.0):
    """Planar Vierendeel girder (rigid joints, no diagonals) on a pin and a roller."""
    f = fs.Frame()
    sec = fs.rhs(250, 150, 10)
    a = span / panels
    bot = [f.add_node((i * a, 0, 0)) for i in range(panels + 1)]
    top = [f.add_node((i * a, 0, depth)) for i in range(panels + 1)]
    for i in range(panels):
        f.add_element(bot[i], bot[i + 1], sec, S355)
        f.add_element(top[i], top[i + 1], sec, S355)
    for i in range(panels + 1):
        f.add_element(bot[i], top[i], sec, S355)
    f.fix(bot[0], (True, True, True, False, False, False))
    f.fix(bot[-1], (False, True, True, False, False, False))
    in_plane(f)
    for i in range(1, panels):
        f.load(top[i], fz=-P, case="Q")
    f.gravity = (0, 0, -1)
    return {"frame": f, "combos": {"ULS": {"G": 1.35, "Q": 1.5}}}


def mixed_supports(bay=6.0, h=4.0):
    """Single-storey 2 x 1 bay frame on six different supports: fixed, semi-rigid (rotational springs),
    pinned, a roller sliding along x, a soil spring and a roller; beam UDLs and wind in x."""
    f = fs.Frame()
    G = Grid(f)
    col, bm = fs.rhs(250, 250, 10), fs.rhs(400, 200, 12.5)
    bases = {(0, 0): ((True,) * 6, None), (1, 0): ((True, True, True, False, False, True), dict(rx=8000, ry=8000)),
             (2, 0): ((True, True, True, False, False, False), None), (0, 1): ((False, True, True, False, False, False), None),
             (1, 1): ((False,) * 6, dict(kx=1e5, ky=1e5, kz=5e4, rx=2e4, ry=2e4, rz=2e4)),
             (2, 1): ((False, False, True, False, False, False), None)}
    for (i, j), (restraint, springs) in bases.items():
        b = G.n(i * bay, j * bay, 0)
        f.fix(b, restraint)
        if springs:
            f.spring(b, **springs)
        f.add_element(b, G.n(i * bay, j * bay, h), col, S355)
    for j in (0, 1):
        for i in (0, 1):
            e = f.add_element(G.n(i * bay, j * bay, h), G.n((i + 1) * bay, j * bay, h), bm, S355)
            f.udl(e, (0, 0, -12), "G")
            f.udl(e, (0, 0, -9), "Q")
    for i in (0, 1, 2):
        f.add_element(G.n(i * bay, 0, h), G.n(i * bay, bay, h), bm, S355)
    for j in (0, 1):
        f.load(G.n(0, j * bay, h), fx=6.0, case="W")
    f.gravity = (0, 0, -1)
    return {"frame": f, "combos": {"ULS wind": {"G": 1.35, "Q": 1.05, "W": 1.5}}}


ALL = {
    "moment frame": moment_frame, "braced tower": braced_tower, "Pratt truss": pratt_truss, "portal": portal_2d,
    "warehouse": warehouse, "space grid": space_grid, "arch": arch, "L-bracket": l_bracket, "canopy": canopy,
    "diagrid": diagrid, "Vierendeel": vierendeel, "mixed supports": mixed_supports,
}

BUILDERS = {fn.__name__: fn for fn in ALL.values()}


def refined(frame: fs.Frame, parts: int) -> fs.Frame:
    """Copy of ``frame`` with every bending element split into ``parts`` (loads and releases follow)."""
    f = copy.deepcopy(frame)
    for ei in range(len(f.elements)):
        if f.elements[ei].truss or parts < 2:
            continue
        tail = ei
        for j in range(1, parts):
            f.split_element(tail, 1.0 / (parts - j + 1))
            tail = len(f.elements) - 1
    return f


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Frame -> conditioned model (the bridge's structure_model shape)
# ══════════════════════════════════════════════════════════════════════════════════════════════
WIND_CASE = "W"
LOAD_CASES = ("G", "Q")
PLANAR_DOFS = (1, 3, 5)      # uy, rx, rz: the restraints in_plane() adds to every node of a planar model
LATERAL = "lateral-y"        # the out-of-plane restraint every free node of a planar model gets in 3D
_SUPPORT_ORDER = ("pinned", "roller-x", "roller-y", "roller", "lateral-x", "lateral-y", "fixed")


def section_spec(sec: fs.Section) -> dict:
    """The bridge's SectionSpec (metres) for a solver section."""
    if sec.shape == "chs":
        d, t = sec.dims_mm
        return {"shape": "circular_hollow", "diameter": d / 1000, "wall": t / 1000}
    if sec.shape == "rhs":
        h, b, t = sec.dims_mm
        return {"shape": "box", "height": h / 1000, "width": b / 1000, "wall": t / 1000}
    if sec.shape == "rect":
        b, h = sec.dims_mm
        return {"shape": "rect", "width": b / 1000, "height": h / 1000}
    raise ValueError(f"{sec.name}: only hollow and solid rectangular/circular sections are in the model protocol "
                     "(what the Rhino bridge exports).")


def section_text(sec: fs.Section) -> str:
    """The ``almond:section`` user text for a solver section (mm; width x depth x wall for boxes)."""
    g = lambda v: f"{v:g}"
    if sec.shape == "chs":
        d, t = sec.dims_mm
        return f"chs {g(d)}x{g(t)}"
    if sec.shape == "rhs":
        h, b, t = sec.dims_mm
        return f"box {g(b)}x{g(h)}x{g(t)}"
    if sec.shape == "rect":
        b, h = sec.dims_mm
        return f"rect {g(b)}x{g(h)}"
    raise ValueError(f"{sec.name}: no almond:section text for this shape.")


def release_text(e: fs.Element) -> str | None:
    """``almond:release`` value for an element: truss bars are "bar" (both axes released), members pinned
    about the major axis only at both ends are "hinged", one-sided pins keep the orientation-based words.
    ``planar``-model members that must stay rigid out of plane are handled by the caller."""
    if e.truss:
        return "bar"
    r = e.releases
    if not r:
        return None
    start, end = bool(r[4]), bool(r[10])
    minor = bool(r[5]) or bool(r[11])
    if start and end:
        return "bar" if minor else "hinged"
    return {(True, False): "pinned_start", (False, True): "pinned_end"}.get((start, end))


def support_spec(restraint, springs) -> str:
    """The ``almond:support`` text (``native_structure.parse_support`` grammar) for a solver support:
    restrained DOFs plus springs to ground. Raises ValueError for a restraint pattern the grammar has no
    word for (e.g. a planar model's in-plane restraints)."""
    restraint = tuple(bool(v) for v in restraint)
    springs = tuple(float(v) for v in (springs or (0.0,) * 6))
    sprung = tuple(k > 0 for k in springs)
    extras = [f"{key}={k:g}" for key, k in zip(ns.SPRING_KEYS, springs) if k > 0]
    if not any(restraint):
        if not extras:
            raise ValueError("a support needs a restraint or a spring")
        return " ".join(["spring", *extras])
    for name in _SUPPORT_ORDER:
        final = tuple(t and not s for t, s in zip(ns.SUPPORT_TYPES[name], sprung))
        if final == restraint:
            return " ".join([name, *extras])
    raise ValueError(f"restraint {restraint} has no almond:support type")


def _planar_support(restraint, springs):
    """A planar (x-z) support as a 3D one: drop the in-plane restraints in_plane() added and restrain y.
    Returns (None, None) for a free node that in_plane() restrained; those become LATERAL supports."""
    r = list(restraint)
    for d in PLANAR_DOFS:
        r[d] = False
    if not any(r) and not any(springs):
        return None, None
    r[1] = True
    return tuple(r), tuple(springs)


def to_model(frame: fs.Frame, planar: bool = False, reference_id: str = "", tolerance_m: float = 0.001,
             lateral_restraints: bool = True) -> tuple[dict, dict]:
    """The bridge's conditioned-model JSON for a solver frame, plus a conversion report.

    One member per element (``source_guids`` "M1"...), sections as SectionSpec, pinned ends and truss
    bars as ``release``, supports typed (``supports``) unless every support is plain fixed or plain pinned
    (then ``anchor_points``, so ``fixed_supports`` chooses). Nodal and member loads of cases G and Q go to
    ``loads``; wind (case W) is not part of Almond's gravity-only checks and is dropped with a note.
    ``planar``: the model is an x-z textbook model whose in-plane restraints are translated for 3D: supports
    restrain y, every other node gets a ``lateral-y`` support (the deck or bracing a planar truss relies on;
    omitted when ``lateral_restraints`` is False, e.g. for a bridge that cannot read almond:support yet), and
    bars become "hinged" members (pin-jointed in the plane, continuous in plan)."""
    X = np.asarray(frame.nodes, float)
    members, notes = [], []
    for i, e in enumerate(frame.elements):
        p1, p2 = X[e.n1].tolist(), X[e.n2].tolist()
        m = {"points": [p1, p2], "section": section_spec(e.section), "source_guids": [f"M{i + 1}"],
             "curve_start_m": p1, "curve_end_m": p2}
        rel = release_text(e)
        if rel and planar and rel == "bar":
            rel = "hinged"                              # pin-jointed in the plane, continuous out of it: the
                                                        # in_plane() restraints of the textbook model in 3D
        if rel:
            m["release"] = rel
        members.append(m)
    supports, labels, lateral = [], {}, 0
    for n in range(len(frame.nodes)):
        restraint = frame.supports.get(n, (False,) * 6)
        springs = frame.springs.get(n, (0.0,) * 6)
        if planar:
            restraint, springs = _planar_support(restraint, springs)
            if restraint is None:
                if lateral_restraints:
                    supports.append({"point_m": X[n].tolist(), "spec": LATERAL})
                    lateral += 1
                continue
        elif not any(restraint) and not any(springs):
            continue
        spec = support_spec(restraint, springs)
        supports.append({"point_m": X[n].tolist(), "spec": spec})
        labels[spec] = labels.get(spec, 0) + 1
    if planar:
        if lateral:
            labels[LATERAL] = lateral
            notes.append(f"Planar model: supports restrain y and the other {lateral} node(s) carry a {LATERAL} restraint, "
                         "the out-of-plane bracing a planar truss or frame relies on (in-plane statics unchanged).")
        else:
            notes.append("Planar model drawn without its out-of-plane (lateral-y) restraints: in 3D it can buckle "
                         "sideways, so expect a stability verdict unless the deck or bracing is modelled.")
    loads, dropped, totals = [], {}, {"G": 0.0, "Q": 0.0}
    nodal_count = member_count = 0
    for (n, case), v in sorted(frame.nodal_loads.items()):
        if case not in LOAD_CASES:
            dropped[case] = dropped.get(case, 0) + 1
            continue
        v = [float(x) for x in v]
        entry = {"point_m": X[n].tolist(), "force_kn": v[:3], "case": case}
        if any(v[3:]):
            entry["moment_knm"] = v[3:]
        loads.append(entry)
        totals[case] += -v[2]
        nodal_count += 1
    for (ei, wa, wb, case) in frame.member_loads:
        if case not in LOAD_CASES:
            dropped[case] = dropped.get(case, 0) + 1
            continue
        L = float(np.linalg.norm(X[frame.elements[ei].n2] - X[frame.elements[ei].n1]))
        entry = {"member": int(ei), "w_start_kn_m": [float(x) for x in wa], "w_end_kn_m": [float(x) for x in wb],
                 "case": case}
        loads.append(entry)
        totals[case] += -(float(wa[2]) + float(wb[2])) / 2 * L
        member_count += 1
    for case, count in dropped.items():
        what = "wind" if case == WIND_CASE else f"case {case}"
        notes.append(f"{count} {what} load(s) dropped: Almond checks gravity combinations (G, Q) only; "
                     "the sway imperfection stands in for lateral effects.")
    spans = [math.dist(*m["points"]) for m in members]
    model = {"status": "ok", "units": "m", "source": "almond-structural-reference", "reference_id": reference_id,
             "members": members, "loads": loads, "tolerance_m": tolerance_m,
             "max_member_span_m": max(spans) if spans else 0.0,
             "max_span_m": float(np.max(np.ptp(X, axis=0))) if len(X) else 0.0, "warnings": [], "shells": 0}
    uniform = len(labels) == 1 and next(iter(labels)) in ("fixed", "pinned") and not planar
    if uniform:
        model["anchor_points"] = [s["point_m"] for s in supports]
    else:
        model["supports"] = supports
    report = {"members": len(members), "nodes": len(frame.nodes), "supports": labels,
              "supports_mode": "anchor_points" if uniform else "typed",
              "default_fixed": (next(iter(labels)) == "fixed") if uniform else None,
              "loads": {"nodal": nodal_count, "member": member_count, "total_vertical_kn": {k: round(v, 3) for k, v in totals.items()},
                        "self_weight": frame.gravity is not None},
              "dropped_cases": dropped, "notes": notes}
    return model, report


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Catalogue
# ══════════════════════════════════════════════════════════════════════════════════════════════
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ReferenceLibrary:
    """Read-only access to ``StructuralReferences/catalogue.json`` plus parameter validation."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._catalogue = None

    @property
    def available(self) -> bool:
        return (self.root / "catalogue.json").is_file()

    @property
    def catalogue(self) -> dict:
        if self._catalogue is None:
            self._catalogue = json.loads((self.root / "catalogue.json").read_text(encoding="utf-8"))
        return self._catalogue

    @property
    def entries(self) -> list[dict]:
        return self.catalogue["references"]

    def entry(self, reference_id: str) -> dict:
        reference_id = str(reference_id or "").strip().lower()
        for e in self.entries:
            if e["id"] == reference_id:
                return e
        raise KeyError(reference_id)

    @property
    def families(self) -> list[str]:
        return sorted({e["family"] for e in self.entries})

    def search(self, query: str = "", family: str = "", limit: int = 20) -> dict:
        terms = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
        cards = []
        for e in self.entries:
            if family and e["family"] != family.strip().lower():
                continue
            haystack = " ".join([e["id"], e["title"], e["summary"], e["family"], e["exercises"],
                                 e.get("structure_type", ""), *e.get("teaching", []),
                                 *(p["name"] + " " + p.get("label", "") for p in e["parameters"])]).lower()
            matched = sorted(t for t in terms if t in haystack)
            if terms and not matched:
                continue
            cards.append({"id": e["id"], "title": e["title"], "family": e["family"], "summary": e["summary"],
                          "structure_type": e["structure_type"], "planar": bool(e.get("planar")),
                          "parameters": [p["name"] for p in e["parameters"]],
                          "closed_form": e.get("verification", {}).get("closed_form"),
                          "matched_terms": matched, "model_uri": f"almond://structural/{e['id']}/model"})
        cards.sort(key=lambda c: (-len(c["matched_terms"]), c["family"], c["id"]))
        return {"total": len(cards), "families": self.families, "references": cards[:max(1, int(limit))]}

    def parameters(self, entry: dict, values: dict | None) -> dict:
        """Builder kwargs: catalogue defaults overridden by ``values``, each checked against its declared
        type and range. Unknown names and out-of-range values raise ValueError."""
        values = dict(values or {})
        out = {}
        declared = {p["name"]: p for p in entry["parameters"]}
        unknown = sorted(set(values) - set(declared))
        if unknown:
            raise ValueError(f"Unknown parameter(s) {unknown}; {entry['id']} takes {sorted(declared)}.")
        for name, p in declared.items():
            raw = values.get(name, p["default"])
            kind = p.get("type", "float")
            label = f"{entry['id']}.{name}"
            if kind == "bool":
                if isinstance(raw, str):
                    raw = raw.strip().lower() in ("1", "true", "yes", "on")
                out[name] = bool(raw)
                continue
            if kind == "choice":
                if raw not in p["choices"]:
                    raise ValueError(f"{label} must be one of {p['choices']}.")
                out[name] = raw
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{label} must be a number.") from None
            if isinstance(raw, bool) or not math.isfinite(number):
                raise ValueError(f"{label} must be a finite number.")
            if kind == "int":
                if number != int(number):
                    raise ValueError(f"{label} must be a whole number.")
                number = int(number)
            lo, hi = p.get("min"), p.get("max")
            if (lo is not None and number < lo) or (hi is not None and number > hi):
                raise ValueError(f"{label} must be between {lo} and {hi} ({p.get('unit') or 'no unit'}).")
            out[name] = number
        return out


def build(entry: dict, params: dict) -> dict:
    """Run the entry's builder: {"frame": Frame, "combos": ..., ...extras}."""
    fn = BUILDERS.get(entry["builder"])
    if fn is None:
        raise ValueError(f"{entry['id']}: builder {entry['builder']!r} does not exist.")
    return fn(**params)


def study_settings(entry: dict, **overrides) -> dict:
    """The entry's default study with the caller's non-None overrides."""
    s = dict(entry["study"])
    s.update({k: v for k, v in overrides.items() if v is not None})
    return s


def reference_model(library: ReferenceLibrary, reference_id: str, parameters: dict | None = None,
                    lateral_restraints: bool = True) -> tuple[dict, dict, dict, dict]:
    """(entry, params, model, report) for a reference at the given parameters."""
    entry = library.entry(reference_id)
    params = library.parameters(entry, parameters)
    built = build(entry, params)
    model, report = to_model(built["frame"], planar=bool(entry.get("planar")), reference_id=entry["id"],
                             lateral_restraints=lateral_restraints)
    report["built"] = built
    return entry, params, model, report


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Closed-form checks (the independent methods of tests/test_structural_typologies.py)
# ══════════════════════════════════════════════════════════════════════════════════════════════
def joint_forces(frame: fs.Frame, loads_case: str = "Q"):
    """Member forces (tension +) and reactions of a statically determinate planar (x-z) pin-jointed truss by
    the method of joints: 2 equilibrium equations per node, solved directly. Returns (N, A)."""
    X = np.asarray(frame.nodes)[:, [0, 2]]
    els = [(e.n1, e.n2) for e in frame.elements]
    sup = [(n, k) for n, flags in frame.supports.items() for k, d in ((0, 0), (1, 2)) if flags[d]]
    A = np.zeros((2 * len(X), len(els) + len(sup)))
    b = np.zeros(2 * len(X))
    for j, (p, q) in enumerate(els):
        d = (X[q] - X[p]) / np.linalg.norm(X[q] - X[p])
        A[2 * p:2 * p + 2, j] += d
        A[2 * q:2 * q + 2, j] -= d
    for k, (n, row) in enumerate(sup):
        A[2 * n + row, len(els) + k] = 1.0
    for (n, case), v in frame.nodal_loads.items():
        if case == loads_case:
            b[2 * n] -= v[0]
            b[2 * n + 1] -= v[2]
    if A.shape[0] != A.shape[1]:
        raise ValueError("truss must be statically determinate")
    return np.linalg.solve(A, b)[:len(els)], A


def portal_thrust(span: float, h: float, rise: float, w: float, steps: int = 4000) -> dict:
    """Horizontal reaction and eaves/apex moments of a pinned-base gable portal under a plan UDL by the
    force method (release H, integrate M0 m1 / EI and m1^2 / EI along the frame; bending only)."""
    path = []
    for (p, q) in (((0, 0), (0, h)), ((0, h), (span / 2, h + rise)), ((span / 2, h + rise), (span, h)), ((span, h), (span, 0))):
        L = math.dist(p, q)
        for k in range(steps):
            t = (k + 0.5) / steps
            path.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]), L / steps))
    M0 = lambda x: w * span / 2 * x - w * x * x / 2
    d10 = sum(M0(x) * -z * ds for x, z, ds in path)
    d11 = sum(z * z * ds for x, z, ds in path)
    H = -d10 / d11
    return {"H": H, "eaves_moment": H * h, "apex_moment": abs(M0(span / 2) - H * (h + rise))}


def _nearest(frame: fs.Frame, point) -> int:
    X = np.asarray(frame.nodes)
    return int(np.argmin(np.linalg.norm(X - np.asarray(point, float), axis=1)))


def _check(quantity, method, expected, almond, unit, tol):
    rel = abs(almond - expected) / max(abs(expected), 1e-12)
    return {"quantity": quantity, "method": method, "expected": expected, "almond": almond, "unit": unit,
            "rel_error": rel, "tolerance": tol, "ok": bool(rel <= tol)}


def closed_form_checks(entry: dict, built: dict, model: dict, material: str, fixed_supports: bool = True) -> list[dict]:
    """Compare a first-order Q-only solve of the *model* (through ``native_structure.build_frame``, i.e. the
    path validate_structure takes) with the benchmark frame and, where the catalogue names one, with the
    textbook closed form. Material as in the study (the closed forms are elastic: material-independent
    except through E and G)."""
    frame, _, _ = ns.build_frame(model, 0.0, material, bool(fixed_supports), self_weight=False)
    res = fs.solve(frame, combination={"Q": 1.0})
    ref = fs.solve(built["frame"], combination={"Q": 1.0})
    out = [_check("max displacement under Q (model protocol vs benchmark frame)", "same geometry solved from the "
                  "bridge-shaped model", ref.max_displacement * 1000, res.max_displacement * 1000, "mm", 1e-6)]
    kind = (entry.get("verification") or {}).get("closed_form")
    b = built["frame"]
    if kind == "pratt":
        N_ref, A = joint_forces(b)
        N = np.array([float(np.mean(er.N)) for er in res.elements])
        out.append(_check("largest member force error", "method of joints (statically determinate)",
                          0.0, float(np.max(np.abs(N - N_ref)) / np.max(np.abs(N_ref))), "relative", 1e-8))
        out[-1]["expected"], out[-1]["rel_error"] = 0.0, out[-1]["almond"]
        out[-1]["ok"] = out[-1]["almond"] <= 1e-8
        unit = np.zeros(A.shape[0])
        unit[2 * built["mid_node"] + 1] = 1.0
        n_unit = np.linalg.solve(A, unit)[:len(b.elements)]
        E = b.elements[0].material.E
        vw = sum(N_ref[j] * n_unit[j] * er.length / (E * b.elements[j].section.A) for j, er in enumerate(ref.elements))
        mid = _nearest(frame, b.nodes[built["mid_node"]])
        out.append(_check("midspan deflection", "virtual work (unit load at the midspan bottom node)",
                          abs(vw) * 1000, -res.displacements[mid, 2] * 1000, "mm", 1e-6))
    elif kind == "portal":
        g = built["geometry"]
        cf = portal_thrust(g["span"], g["h"], g["rise"], g["w"])
        A = _nearest(frame, b.nodes[built["nodes"][0]])
        out.append(_check("horizontal thrust at a base", "force method (release H, integrate M0 m1/EI)",
                          cf["H"], abs(float(res.reactions[A, 0])), "kN", 5e-3))
        out.append(_check("eaves moment", "force method", cf["eaves_moment"], abs(float(res.elements[0].My[-1])), "kNm", 5e-3))
    elif kind == "arch":
        n0 = _nearest(frame, b.nodes[built["nodes"][0]])
        out.append(_check("horizontal thrust", "funicular statics: M0 of the equivalent beam / rise",
                          built["thrust"], abs(float(res.reactions[n0, 0])), "kN", 1e-3))
        mmax = max(float(np.max(np.abs(er.My))) for er in res.elements)
        out.append(_check("largest bending moment / M0 (funicular: ~0)", "funicular statics", 0.0,
                          mmax / built["M0"], "relative", 1e-3))
        out[-1]["rel_error"], out[-1]["ok"] = out[-1]["almond"], out[-1]["almond"] <= 1e-3
    elif kind == "l_bracket":
        tip = _nearest(frame, b.nodes[built["tip"]])
        out.append(_check("tip deflection", "cantilever bending of both arms + torsion of the first (PL^3/3EI, PL^2a/GJ)",
                          built["tip_deflection"] * 1000, -res.displacements[tip, 2] * 1000, "mm", 1e-6))
        out.append(_check("torsion in the first arm", "statics: P x b", built["torsion"],
                          abs(float(res.elements[0].T)), "kNm", 1e-6))
    for c in out:
        for k in ("expected", "almond", "rel_error"):
            c[k] = float(c[k])
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Analysis without Rhino
# ══════════════════════════════════════════════════════════════════════════════════════════════
def analyze(library: ReferenceLibrary, reference_id: str, parameters: dict | None = None, *, material=None,
            fixed_supports=None, self_weight=None, connections=None, stability=None, span_m=None,
            load_kn: float = 0.0, floor_imposed_kn_m2: float = 0.0, floor_dead_kn_m2: float = 0.0,
            design_basis: str = "en1990", uls_combination=None, design_code="eurocode", detail: bool = False,
            fabrication: str = "cold_formed", checks: bool = True) -> dict:
    """``validate_structure``'s native check on a reference model, with a ``reference`` block: parameters,
    counts, the loads applied, conversion notes and the closed-form comparison."""
    entry, params, model, report = reference_model(library, reference_id, parameters)
    study = study_settings(entry, material=material, fixed_supports=fixed_supports, self_weight=self_weight,
                           connections=connections, stability=stability, span_m=span_m)
    if study.get("span_m") is None and study.get("span_parameter"):
        study["span_m"] = params[study["span_parameter"]]     # the deflection span follows the geometry parameter
    floor = None
    if float(floor_imposed_kn_m2 or 0) or float(floor_dead_kn_m2 or 0):
        floor = {"imposed": float(floor_imposed_kn_m2 or 0), "dead": float(floor_dead_kn_m2 or 0)}
    result = ns.validate(model, entry["structure_type"], float(load_kn or 0.0), study["material"],
                         fixed_supports=bool(study["fixed_supports"]), self_weight=bool(study["self_weight"]),
                         span_m=study.get("span_m"), floor_loads=floor, design_basis=design_basis,
                         uls=uls_combination, connections=study["connections"], stability=study["stability"],
                         design_code=design_code, detail=detail, fabrication=fabrication)
    built = report.pop("built")
    ref = {"id": entry["id"], "title": entry["title"], "family": entry["family"], "parameters": params,
           "study": study, **report, "benchmark": entry.get("verification", {})}
    if checks:
        try:
            ref["checks"] = closed_form_checks(entry, built, model, study["material"], study["fixed_supports"])
        except (ValueError, fs.MechanismError) as exc:
            ref["checks"] = [{"error": str(exc)}]
    result["reference"] = ref
    return result


def rhino_study(entry: dict, report: dict, study: dict) -> dict:
    """The nearest ``validate_structure`` call for the reference once placed in Rhino: the bridge exports
    geometry, sections, releases and support points, but not loads, so the variable loads become one
    ``load_kn`` shared over the free nodes and permanent member loads are named for a floor-load equivalent."""
    totals = report["loads"]["total_vertical_kn"]
    args = {"structure_type": entry["structure_type"], "material": study["material"],
            "load_kn": round(totals.get("Q", 0.0), 1), "self_weight": bool(study["self_weight"]),
            "fixed_supports": bool(study["fixed_supports"]), "connections": study["connections"],
            "stability": study["stability"]}
    if study.get("span_m"):
        args["span_m"] = study["span_m"]
    notes = ["load_kn is the reference's total variable load, shared equally over the free nodes by "
             "validate_structure (the reference itself applies it as the catalogue's loads)."]
    if totals.get("G"):
        notes.append(f"The reference also carries {totals['G']:.1f} kN of permanent load on members (finishes, "
                     "build-up); approximate it with floor_dead_kn_m2 on a frame with floor bays, or accept the "
                     "difference.")
    if report["supports_mode"] == "typed":
        notes.append("Support points carry almond:support user text; a bridge that does not read it yet applies "
                     "the fixed/pinned default to every point.")
    if entry.get("planar"):
        notes.append("Planar reference: without its lateral-y restraints (lateral_restraints=True places them as points) "
                     "the 3D model can buckle out of its plane, so the stability check may fail; the textbook "
                     "statics are those of analyze_structural_reference.")
    return {"validate_structure": args, "notes": notes}


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Rhino placement
# ══════════════════════════════════════════════════════════════════════════════════════════════
def _cs(value: float) -> str:
    return repr(float(value))


def _cstr(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def place_script(entry: dict, model: dict, built: dict, x_mm: float = 0.0, y_mm: float = 0.0, z_mm: float = 0.0,
                 layer: str = "") -> str:
    """C# for the bridge's execute message: draw the reference's members as lines and its supports as points,
    in document units, with Almond user text. Members come first in the returned GUID list, then supports."""
    for v, name in ((x_mm, "x_mm"), (y_mm, "y_mm"), (z_mm, "z_mm")):
        if not math.isfinite(float(v)):
            raise ValueError(f"{name} must be a finite number.")
    layer = (layer or f"Almond Reference {entry['id']}").strip()
    if "::" in layer or not layer:
        raise ValueError("layer must be a single layer name (no '::').")
    rows, sections, releases, names = [], [], [], []
    for i, m in enumerate(model["members"]):
        (a, b) = m["points"]
        rows.append("{" + ", ".join(_cs(v) for v in (*a, *b)) + "}")
        sections.append(_cstr(section_text(built["frame"].elements[i].section)))
        releases.append(_cstr(m.get("release") or ""))
        names.append(_cstr(f"M{i + 1} {ns._orientation(m)}"))
    supports = model.get("supports") or [{"point_m": p, "spec": ""} for p in model.get("anchor_points", [])]
    s_rows = ["{" + ", ".join(_cs(v) for v in s["point_m"]) + "}" for s in supports]
    s_specs = [_cstr(s.get("spec") or "") for s in supports]
    return f"""
using System;
using System.Collections.Generic;
using Rhino;
using Rhino.Geometry;
using Rhino.DocObjects;

public class Script
{{
    static readonly double[,] M = {{ {", ".join(rows)} }};
    static readonly string[] S = {{ {", ".join(sections)} }};
    static readonly string[] R = {{ {", ".join(releases)} }};
    static readonly string[] N = {{ {", ".join(names)} }};
    static readonly double[,] P = {{ {", ".join(s_rows) if s_rows else "{0, 0, 0}"} }};
    static readonly string[] T = {{ {", ".join(s_specs) if s_specs else '""'} }};
    const int Supports = {len(supports)};

    public static List<Guid> Run(RhinoDoc doc)
    {{
        var guids = new List<Guid>();
        double s = RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem);
        double mm = RhinoMath.UnitScale(UnitSystem.Millimeters, doc.ModelUnitSystem);
        var shift = new Vector3d({_cs(x_mm)} * mm, {_cs(y_mm)} * mm, {_cs(z_mm)} * mm);
        int layerIndex = doc.Layers.FindByFullPath({_cstr(layer)}, -1);
        if (layerIndex < 0)
        {{
            var l = new Layer {{ Name = {_cstr(layer)}, Color = System.Drawing.Color.FromArgb(140, 40, 40) }};
            layerIndex = doc.Layers.Add(l);
        }}
        Func<double, double, double, Point3d> Pt = (x, y, z) => new Point3d(x * s, y * s, z * s) + shift;
        for (int i = 0; i < M.GetLength(0); i++)
        {{
            var a = new ObjectAttributes {{ LayerIndex = layerIndex, Name = N[i] }};
            a.SetUserString("almond:section", S[i]);
            if (R[i].Length > 0) a.SetUserString("almond:release", R[i]);
            a.SetUserString("almond:reference", {_cstr(entry['id'])});
            a.SetUserString("almond:member", (i + 1).ToString());
            var id = doc.Objects.AddLine(new Line(Pt(M[i, 0], M[i, 1], M[i, 2]), Pt(M[i, 3], M[i, 4], M[i, 5])), a);
            if (id != Guid.Empty) guids.Add(id);
        }}
        for (int i = 0; i < Supports; i++)
        {{
            var a = new ObjectAttributes {{ LayerIndex = layerIndex, Name = "S" + (i + 1) + " " + T[i] }};
            if (T[i].Length > 0) a.SetUserString("almond:support", T[i]);
            a.SetUserString("almond:reference", {_cstr(entry['id'])});
            var id = doc.Objects.AddPoint(Pt(P[i, 0], P[i, 1], P[i, 2]), a);
            if (id != Guid.Empty) guids.Add(id);
        }}
        doc.Views.Redraw();
        return guids;
    }}
}}
"""
