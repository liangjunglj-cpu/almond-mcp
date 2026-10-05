"""Building typologies as native frame_solver models (SI, kN), shared by the closed-form typology tests
and the OpenSees cross-check benchmarks (benchmarks/).

Each builder returns {"frame": Frame, "combos": {name: {case: factor}}, ...extras}. Sections are hollow
or solid (what the Rhino bridge exports); ``moment_frame(open_sections=True)`` uses I-sections."""
from __future__ import annotations

import math

import numpy as np

from almond_mcp import frame_solver as fs

S355 = fs.material("S355")


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


def refined(frame: fs.Frame, parts: int) -> fs.Frame:
    """Copy of ``frame`` with every bending element split into ``parts`` (loads and releases follow)."""
    import copy
    f = copy.deepcopy(frame)
    for ei in range(len(f.elements)):
        if f.elements[ei].truss or parts < 2:
            continue
        tail = ei
        for j in range(1, parts):
            f.split_element(tail, 1.0 / (parts - j + 1))
            tail = len(f.elements) - 1
    return f
