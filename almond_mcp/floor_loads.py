"""Floor area loads (kN/m2) on a native frame: find the floor bays, send each bay's load to its beams.

Bays are the faces of the plan graph formed by horizontal members on one level (every area
enclosed by beams). Each bay's load reaches its edge members by the usual tributary rules:

- rectangular bay, long/short <= 2 (two-way): 45-degree lines from the corners; short edges
  carry a triangle (peak q*s/2 at midspan), long edges a trapezoid (plateau q*s/2);
- rectangular bay, long/short > 2 (one-way): the long edges carry q*s/2 uniformly;
- any other convex bay: a centroid fan; each edge carries a triangle with its apex under the
  bay centroid and the triangle's area as tributary area.

A straight line between two adjacent supports on the level, with no beam along it, is a bearing
wall: bays close on it and its share goes straight into those supports (it shows in the
reactions but bends no member).

Each loaded member is split at the load shape's kinks and every part carries a linearly varying
load, which the solver integrates exactly (fixed-end forces and deflected shape).
"""
from __future__ import annotations

import math

import numpy as np

from . import frame_solver as fs

LEVEL_TOL = 0.05


def _levels(frame: fs.Frame) -> dict:
    """{z: [element index]} for horizontal elements (same rule as asset_loads)."""
    levels: dict[float, list[int]] = {}
    for ei, e in enumerate(frame.elements):
        a, b = frame.nodes[e.n1], frame.nodes[e.n2]
        L = math.dist(a, b)
        if L <= 0 or abs(a[2] - b[2]) > min(LEVEL_TOL, 0.02 * L):
            continue
        z = (a[2] + b[2]) / 2
        key = next((k for k in levels if abs(k - z) <= LEVEL_TOL), None)
        levels.setdefault(z if key is None else key, []).append(ei)
    return levels


def find_bays(frame: fs.Frame, members: list[int], walls: list | None = None) -> list[dict]:
    """Enclosed faces of the plan graph of ``members`` (+ bearing ``walls`` as node pairs, given
    edge ids -1, -2, ...): [{nodes, edges, area, centroid}].

    Half-edge walk keeping the face on the left: at each vertex take the neighbour that comes
    just before the arrival vertex in counter-clockwise order. Bounded faces come out
    counter-clockwise (positive area); the outer face is negative and dropped."""
    adj: dict[int, list[tuple[float, int, int]]] = {}
    links = [(frame.elements[ei].n1, frame.elements[ei].n2, ei) for ei in members]
    links += [(a, b, -(k + 1)) for k, (a, b) in enumerate(walls or [])]
    for n1, n2, ei in links:
        for u, v in ((n1, n2), (n2, n1)):
            pu, pv = frame.nodes[u], frame.nodes[v]
            adj.setdefault(u, []).append((math.atan2(pv[1] - pu[1], pv[0] - pu[0]), v, ei))
    for u in adj:
        adj[u].sort()
    used, bays = set(), []
    for u in adj:
        for _, v, ei in adj[u]:
            if (u, v) in used:
                continue
            nodes, edges, a, b = [], [], u, v
            while (a, b) not in used:
                used.add((a, b))
                nodes.append(a)
                edges.append(next(x[2] for x in adj[a] if x[1] == b))
                around = adj[b]
                i = next(k for k, x in enumerate(around) if x[1] == a)
                a, b = b, around[i - 1][1]
                if len(nodes) > 4 * len(links) + 4:
                    break
            if len(nodes) < 3 or len(set(edges)) != len(edges):
                continue                       # dangling edges, not an enclosed bay
            P = np.array([frame.nodes[n][:2] for n in nodes])
            x, y = P[:, 0], P[:, 1]
            cross = x * np.roll(y, -1) - np.roll(x, -1) * y
            area = cross.sum() / 2
            if area <= 1e-9:
                continue                       # the outer face
            cx = ((x + np.roll(x, -1)) * cross).sum() / (6 * area)
            cy = ((y + np.roll(y, -1)) * cross).sum() / (6 * area)
            bays.append({"nodes": nodes, "edges": edges, "area": float(area), "centroid": (float(cx), float(cy))})
    return bays


def _cross(u, v) -> float:
    return float(u[0] * v[1] - u[1] * v[0])


def _is_rectangle(P):
    if len(P) != 4:
        return False
    for i in range(4):
        u, w = P[(i + 1) % 4] - P[i], P[(i - 1) % 4] - P[i]
        if abs(u @ w) > 1e-3 * np.linalg.norm(u) * np.linalg.norm(w):
            return False
    return True


def _convex(P):
    s = [_cross(P[(i + 1) % len(P)] - P[i], P[(i + 2) % len(P)] - P[(i + 1) % len(P)]) for i in range(len(P))]
    return all(v >= -1e-9 for v in s)


def edge_shapes(frame: fs.Frame, bay: dict, q: float) -> list[tuple[int, int, list[tuple[float, float]]]]:
    """Load shape on each bay edge: (element, start node, [(t, w kN/m), ...]) piecewise linear in t."""
    P = np.array([frame.nodes[n][:2] for n in bay["nodes"]])
    k = len(P)
    out = []
    if _is_rectangle(P):
        lens = [float(np.linalg.norm(P[(i + 1) % 4] - P[i])) for i in range(4)]
        s, l = min(lens), max(lens)
        for i in range(4):
            L = lens[i]
            if l / s > 2.0:                                    # one-way onto the long edges
                w = q * s / 2 if L > (s + l) / 2 else 0.0
                pts = [(0.0, w), (1.0, w)]
            else:                                              # two-way, 45-degree lines
                r = (s / 2) / L
                pts = [(0.0, 0.0), (r, q * s / 2), (1 - r, q * s / 2), (1.0, 0.0)] if r < 0.5 else [(0.0, 0.0), (0.5, q * L / 2), (1.0, 0.0)]
            out.append((bay["edges"][i], bay["nodes"][i], pts))
        return out
    c = np.asarray(bay["centroid"])
    for i in range(k):
        a, b = P[i], P[(i + 1) % k]
        d = b - a
        L = float(np.linalg.norm(d))
        t_c = float(np.clip((c - a) @ d / L ** 2, 0.0, 1.0))
        area = abs(_cross(d, c - a)) / 2
        peak = 2 * q * area / L
        out.append((bay["edges"][i], bay["nodes"][i], [(0.0, 0.0), (t_c, peak), (1.0, 0.0)]))
    return out


def load_member(frame: fs.Frame, ei: int, shape_list: list, cases: dict | None = None) -> list[int]:
    """Apply the summed piecewise-linear shapes [(t, w kN/m), ...] (t along n1 -> n2, downward) to
    element ``ei`` exactly: split at the shapes' kinks and give each part its linear load, once per
    load case scaled by ``cases`` ({case: factor}; default {"Q": 1})."""
    ts = sorted({round(t, 12) for pts in shape_list for t, _ in pts if 1e-9 < t < 1 - 1e-9})
    bounds = [0.0] + ts + [1.0]
    f = lambda t: sum(float(np.interp(t, [q[0] for q in pts], [q[1] for q in pts])) for pts in shape_list)
    parts = [ei]
    for j in range(1, len(bounds) - 1):                         # split the remaining tail each time
        frame.split_element(parts[-1], (bounds[j] - bounds[j - 1]) / (1.0 - bounds[j - 1]))
        parts.append(len(frame.elements) - 1)
    for j, part in enumerate(parts):
        for case, k in (cases or {"Q": 1.0}).items():
            if k:
                frame.linear_load(part, (0.0, 0.0, -k * f(bounds[j])), (0.0, 0.0, -k * f(bounds[j + 1])), case=case)
    return parts


def bearing_walls(frame: fs.Frame, members: list[int], z: float) -> list[tuple[int, int]]:
    """Pairs of adjacent supports on level z with no beam between them: straight, nothing else on
    the line between them, crossing no member in plan."""
    on_level = [n for n in frame.supports if abs(frame.nodes[n][2] - z) <= LEVEL_TOL]
    level_nodes = {n for ei in members for n in (frame.elements[ei].n1, frame.elements[ei].n2)} | set(on_level)
    linked = {frozenset((frame.elements[ei].n1, frame.elements[ei].n2)) for ei in members}
    segs = [(np.asarray(frame.nodes[frame.elements[ei].n1][:2]), np.asarray(frame.nodes[frame.elements[ei].n2][:2]))
            for ei in members]
    walls = []
    for i, a in enumerate(on_level):
        for b in on_level[i + 1:]:
            if frozenset((a, b)) in linked:
                continue
            pa, pb = np.asarray(frame.nodes[a][:2]), np.asarray(frame.nodes[b][:2])
            d = pb - pa
            L2 = float(d @ d)
            if L2 < 1e-12:
                continue
            between = False
            for n in level_nodes - {a, b}:
                q = np.asarray(frame.nodes[n][:2]) - pa
                t = float(q @ d) / L2
                if 0 < t < 1 and abs(_cross(d, q)) / math.sqrt(L2) < 1e-3:
                    between = True
                    break
            if between or any(_crosses(pa, pb, s0, s1) for s0, s1 in segs):
                continue
            walls.append((a, b))
    # shortest first; a candidate cutting through a bay that is already closed is a diagonal, not a wall
    walls.sort(key=lambda w: math.dist(frame.nodes[w[0]][:2], frame.nodes[w[1]][:2]))
    accepted = []
    for a, b in walls:
        mid = (np.asarray(frame.nodes[a][:2]) + np.asarray(frame.nodes[b][:2])) / 2
        if any(_inside(mid, [frame.nodes[n][:2] for n in bay["nodes"]]) for bay in find_bays(frame, members, accepted)):
            continue
        accepted.append((a, b))
    return accepted


def _inside(p, poly) -> bool:
    """Ray casting point-in-polygon (plan)."""
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > p[1]) != (y1 > p[1]) and p[0] < x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _crosses(p1, p2, q1, q2) -> bool:
    """Proper crossing of two plan segments (touching at endpoints does not count)."""
    d1, d2 = _cross(p2 - p1, q1 - p1), _cross(p2 - p1, q2 - p1)
    d3, d4 = _cross(q2 - q1, p1 - q1), _cross(q2 - q1, p2 - q1)
    return d1 * d2 < -1e-12 and d3 * d4 < -1e-12


def _wall_reactions(pts, L):
    """End reactions (simple statics) of a piecewise-linear line load on a wall segment."""
    t = np.linspace(0.0, 1.0, 801)
    w = np.interp(t, [q[0] for q in pts], [q[1] for q in pts])
    total = float(np.trapezoid(w, t)) * L
    rb = float(np.trapezoid(w * t, t)) * L
    return total - rb, rb


def apply(frame: fs.Frame, imposed_kn_m2: float = 0.0, dead_kn_m2: float = 0.0, levels_m: list | None = None) -> dict:
    """Load every enclosed bay with dead (case "G") + imposed (case "Q") kN/m2; mutates ``frame``.
    Load shapes are built at unit intensity and applied once per case. Returns a report."""
    q = float(imposed_kn_m2) + float(dead_kn_m2)
    report = {"imposed_kn_m2": imposed_kn_m2, "dead_kn_m2": dead_kn_m2, "levels": [], "area_m2": 0.0,
              "imposed_kn": 0.0, "dead_kn": 0.0, "total_kn": 0.0, "wall_kn": 0.0, "warnings": []}
    if q <= 0:
        return report
    shapes: dict[int, list] = {}
    for z, members in sorted(_levels(frame).items()):
        if levels_m and not any(abs(z - lz) <= LEVEL_TOL for lz in levels_m):
            continue
        walls = bearing_walls(frame, members, z)
        bays = find_bays(frame, members, walls)
        if not bays:
            continue
        lv = {"z_m": round(z, 3), "bays": len(bays), "area_m2": round(sum(b["area"] for b in bays), 3),
              "bearing_walls": len(walls)}
        report["levels"].append(lv)
        for bay in bays:
            if not _convex(np.array([frame.nodes[n][:2] for n in bay["nodes"]])):
                report["warnings"].append(f"Non-convex bay at z={z:.2f} m ({bay['area']:.1f} m2): centroid-fan "
                                          "distribution is approximate.")
            for ei, start, pts in edge_shapes(frame, bay, 1.0):
                if ei < 0:                                     # bearing wall: straight into the supports
                    a, b = walls[-ei - 1]
                    other = b if start == a else a
                    ra, rb = _wall_reactions(pts, math.dist(frame.nodes[start][:2], frame.nodes[other][:2]))
                    for case, k in (("G", dead_kn_m2), ("Q", imposed_kn_m2)):
                        if k:
                            frame.load(start, fz=-k * ra, case=case)
                            frame.load(other, fz=-k * rb, case=case)
                    report["wall_kn"] = report.get("wall_kn", 0.0) + q * (ra + rb)
                    continue
                # store the shape in the element's own direction (n1 -> n2)
                if frame.elements[ei].n1 != start:
                    pts = [(1 - t, w) for t, w in reversed(pts)]
                shapes.setdefault(ei, []).append(pts)
        report["area_m2"] += lv["area_m2"]
    for ei, shape_list in sorted(shapes.items(), reverse=True):    # splits append elements; indices stay valid
        load_member(frame, ei, shape_list, {"G": dead_kn_m2, "Q": imposed_kn_m2})
    area = report["area_m2"]
    report["wall_kn"] = round(report["wall_kn"], 3)
    report.update({"area_m2": round(area, 3), "imposed_kn": round(imposed_kn_m2 * area, 3),
                   "dead_kn": round(dead_kn_m2 * area, 3), "total_kn": round(q * area, 3)})
    if not report["levels"]:
        report["warnings"].append("No enclosed floor bays: the frame has no level where beams enclose an area.")
    return report
