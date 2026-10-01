"""Almond's native structural check: a conditioned line model -> frame_solver -> validation result.

The bridge's ``structure_model`` message exports the same conditioned geometry the Karamba
path analyses (welded nodes, members split at intersections, inferred sections, declared
support points). This module applies the same modelling conventions as the Karamba adapter
so the two engines are comparable:

- supports: declared anchor points (snapped to the nearest node), else every lowest-Z node;
  fully fixed, or pinned (translations only) when ``fixed_supports`` is False;
- connections: rigid joints by default; ``connections="simple"`` pins beams (major-axis bending)
  and braces (both axes) where they stop, i.e. where no other member carries on in line (pieces
  drawn along one line form a continuous member); columns stay continuous; a curve's user text
  ``almond:release``
  ("pinned" | "pinned_start" | "pinned_end" | "rigid") overrides either mode for that member;
- imposed load: ``load_kn`` split equally over the free (unsupported) nodes, acting -Z;
- self weight: gamma x A along every member, -Z;
- deflection limit: span / 250, span = longest member for beam/frame, else overall extent,
  unless the caller names the structural span (members split at every node are shorter);
- load cases: permanent G (self weight, floor build-up, the weight of placed items) and
  variable Q (load_kn, occupancy floor load, contents and occupants of placed items);
- combinations (EN 1990, recommended values): deflection at SLS characteristic G + Q; member
  checks at ULS 6.10, 1.35 G + 1.5 Q (or the worse of 6.10a/6.10b); design_basis="unfactored"
  checks both at G + Q (the Karamba route's basis);
- pass: SLS deflection within the limit and ULS member utilization <= 1.0.

The result dict has the same shape as the bridge's ``validate`` reply, with
``analysis_method`` "native".
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import asset_loads as al
from . import floor_loads as fl
from . import frame_solver as fs

METHOD_PREFIX = "[ALMOND NATIVE FEA (LINEAR 3D FRAME), HIGH CONFIDENCE] "
LINE_TYPES = ("beam", "frame", "truss", "canopy", "highrise")
ASSUMPTIONS = [
    "Linear-elastic, first-order 3D frame analysis (Almond native solver).",
    "Rigid joints; supports as described in support_mode.",
    "Imposed load shared equally by the free nodes, acting downward; self weight included when enabled.",
    "Member check: EN 1993-1-1 cross-section interaction (6.2.1(7), elastic moduli unless plastic "
    "design is requested) and flexural buckling "
    "(6.3.1, L_cr = member length); lateral-torsional buckling not checked.",
    "Preliminary design check, not an engineer's sign-off.",
]


def section_from_spec(spec: dict | None, diameter_mm=None, wall_mm=None) -> tuple[fs.Section, list[str]]:
    """Section from the bridge's SectionSpec (meters) or an explicit CHS override (mm)."""
    notes = []
    if diameter_mm:
        return fs.chs(float(diameter_mm), float(wall_mm or diameter_mm / 20)), notes
    spec = spec or {}
    shape = (spec.get("shape") or "circular_hollow").lower()
    to_mm = 1000.0
    try:
        if shape == "box" and spec.get("height") and spec.get("width"):
            t = spec.get("wall") or min(spec["height"], spec["width"]) / 10
            return fs.rhs(spec["height"] * to_mm, spec["width"] * to_mm, t * to_mm), notes
        if spec.get("diameter"):
            d = spec["diameter"] * to_mm
            t = (spec.get("wall") or spec["diameter"] / 20) * to_mm
            return fs.chs(d, t), notes
    except ValueError as exc:
        notes.append(f"Section {spec} rejected ({exc}); default CHS 114.3x4 used.")
    return fs.chs(114.3, 4.0), notes


CONNECTIONS = ("rigid", "simple")
RELEASES = ("rigid", "pinned", "pinned_start", "pinned_end")


def _member_ends(model: dict, tol: float) -> list:
    """Per member: (start point, end point) of its drawn curve. Uses the bridge's curve_start_m /
    curve_end_m; otherwise the endpoints that occur once among the pieces sharing its first GUID
    (start/end order unknown then: None)."""
    counts: dict = {}
    for m in model.get("members", []):
        pts = m.get("points") or []
        g = (m.get("source_guids") or [""])[0]
        for q in (pts[0], pts[-1]) if pts else ():
            key = (g, tuple(round(v / max(tol, 1e-6)) for v in q))
            counts[key] = counts.get(key, 0) + 1
    ends = []
    for m in model.get("members", []):
        if m.get("curve_start_m") and m.get("curve_end_m"):
            ends.append((m["curve_start_m"], m["curve_end_m"], True))
            continue
        pts = m.get("points") or []
        g = (m.get("source_guids") or [""])[0]
        free = [q for q in ((pts[0], pts[-1]) if pts else ())
                if counts[(g, tuple(round(v / max(tol, 1e-6)) for v in q))] == 1]
        ends.append((free[0] if free else None, free[1] if len(free) > 1 else None, False))
    return ends


def _continued(model: dict, tol: float) -> dict:
    """{(member index, 0 start | 1 end): True} where another member carries on in line (within 5
    degrees) from that end, i.e. the drawn pieces form one continuous member."""
    ends = []
    for i, m in enumerate(model.get("members", [])):
        pts = m.get("points") or []
        if len(pts) < 2:
            continue
        for which, (a, b) in ((0, (pts[0], pts[1])), (1, (pts[-1], pts[-2]))):
            d = np.subtract(b, a)
            n = float(np.linalg.norm(d))
            if n > 0:
                ends.append((i, which, np.asarray(a, float), d / n))
    reach = max(tol, 1e-3)
    return {(i, w): any(j != i and np.linalg.norm(q - p) <= reach and float(d @ e) < -0.996 for (j, _, q, e) in ends)
            for (i, w, p, d) in ends}


def _orientation(m: dict) -> str:
    pts = m.get("points") or []
    if len(pts) < 2:
        return "beam"
    d = np.subtract(pts[-1], pts[0])
    L = float(np.linalg.norm(d))
    slope = abs(d[2]) / L if L > 0 else 0.0
    return "column" if slope > 0.98 else ("beam" if slope < 0.05 else "brace")


def _release_ends(m: dict, connections: str) -> tuple[bool, bool, str, bool]:
    """(release at curve start, at curve end, source, release minor axis too) for one member.
    Beams release major-axis bending only; braces both axes; columns stay continuous."""
    kind = _orientation(m)
    minor = kind != "beam"
    user = (m.get("release") or "").strip().lower()
    if user in RELEASES:
        return user in ("pinned", "pinned_start"), user in ("pinned", "pinned_end"), "user", minor
    if connections == "simple" and kind != "column":
        return True, True, "simple", minor
    return False, False, "rigid", minor


def build_frame(model: dict, load_kn: float, material: str = "Steel", fixed_supports: bool = True,
                self_weight: bool = True, diameter_mm=None, wall_mm=None, asset_loads: dict | None = None,
                floor_loads: dict | None = None, connections: str = "rigid"):
    """``asset_loads``: {"placements": [...], "table": LoadTable, "catalogue": {...}} adds the
    gravity loads of placed library assets (see asset_loads.apply); its report is info["asset_loads"].
    ``floor_loads``: {"imposed": kN/m2, "dead": kN/m2, "levels": [z m] | None} loads every enclosed
    floor bay (see floor_loads.apply); its report is info["floor_loads"].
    ``connections``: "rigid" or "simple" (see module notes); per-member ``release`` overrides.
    All coordinates in meters (the bridge's exported conditioned model)."""
    connections = (connections or "rigid").lower()
    if connections not in CONNECTIONS:
        raise ValueError("connections must be 'rigid' or 'simple'.")
    mat = fs.material(material)
    tol = max(float(model.get("tolerance_m") or 0.0), 1e-6)
    frame = fs.Frame()
    warnings = []

    def node(p):
        for i, q in enumerate(frame.nodes):
            if math.dist(p, q) <= tol:
                return i
        return frame.add_node(p)

    lineage = []
    pinned_ends, user_members, unordered = 0, 0, 0
    cont = _continued(model, tol) if connections == "simple" else {}
    for mi, (m, (c0, c1, ordered)) in enumerate(zip(model.get("members", []), _member_ends(model, tol))):
        sec, notes = section_from_spec(m.get("section"), diameter_mm, wall_mm)
        warnings += notes
        rel0, rel1, source, minor = _release_ends(m, connections)
        user_members += source == "user"
        if source == "user" and rel0 != rel1 and not ordered:
            unordered += 1
            rel0 = rel1 = True                                  # direction unknown: pin both ends
        pts = m.get("points") or []
        for a, b in zip(pts, pts[1:]):
            if math.dist(a, b) <= tol:
                continue
            at = lambda q, c: c is not None and math.dist(q, c) <= max(tol, 1e-3)
            if source == "simple":
                # pin only where the member stops: not at a joint where it carries on in line
                ra = a is pts[0] and not cont.get((mi, 0), False)
                rb = b is pts[-1] and not cont.get((mi, 1), False)
            else:
                ra = (rel0 and at(a, c0)) or (rel1 and at(a, c1))
                rb = (rel0 and at(b, c0)) or (rel1 and at(b, c1))
            ei = frame.add_element(node(a), node(b), sec, mat, tag=list(m.get("source_guids", [])),
                                   releases=fs.release_mask(ra, rb, minor))
            pinned_ends += int(ra) + int(rb)
            lineage.append(ei)
    if unordered:
        warnings.append(f"{unordered} member(s) asked for a one-sided release but the curve direction is "
                        "unknown (update almondbridge); both ends were pinned.")
    if not frame.elements:
        raise ValueError("No line members to analyse.")

    anchors = model.get("anchor_points") or []
    support_nodes = []
    if anchors:
        X = np.asarray(frame.nodes)
        for p in anchors:
            d = np.linalg.norm(X - np.asarray(p), axis=1)
            i = int(np.argmin(d))
            if d[i] <= max(tol, 0.05):
                support_nodes.append(i)
            else:
                warnings.append(f"Support point {tuple(round(v, 3) for v in p)} is {d[i]:.3f} m from "
                                "the nearest node and was ignored.")
    if not support_nodes:
        zmin = min(p[2] for p in frame.nodes)
        support_nodes = [i for i, p in enumerate(frame.nodes) if p[2] <= zmin + tol]
        warnings.append(f"No anchor points declared; supporting {len(support_nodes)} lowest-Z node(s).")
    support_nodes = sorted(set(support_nodes))
    for n in support_nodes:
        frame.fix(n) if fixed_supports else frame.pin(n)

    free = [i for i in range(len(frame.nodes)) if i not in support_nodes] or list(range(len(frame.nodes)))
    if load_kn > 0:
        for n in free:
            frame.load(n, fz=-load_kn / len(free), case="Q")
    if self_weight:
        frame.gravity = (0.0, 0.0, -1.0)
    info = {"support_nodes": support_nodes, "loaded_nodes": free if load_kn > 0 else [], "material": mat,
            "connections": {"mode": connections, "pinned_ends": pinned_ends, "user_released_members": user_members}}
    if floor_loads and (floor_loads.get("imposed") or floor_loads.get("dead")):
        info["floor_loads"] = fl.apply(frame, floor_loads.get("imposed", 0.0), floor_loads.get("dead", 0.0),
                                       floor_loads.get("levels"))
        warnings += info["floor_loads"]["warnings"]
    if asset_loads:
        report = al.apply(frame, asset_loads["placements"], asset_loads["table"], asset_loads.get("catalogue") or {})
        info["asset_loads"] = report
        info["loaded_nodes"] = sorted(set(info["loaded_nodes"]) | set(report["loaded_nodes"]))
    return frame, info, warnings


GAMMA_G, GAMMA_Q, PSI_0, XI = 1.35, 1.5, 0.7, 0.85     # EN 1990 Table A1.2(B), category A psi_0
SLS = ("SLS characteristic", {"G": 1.0, "Q": 1.0})


def combinations(design_basis: str = "en1990", uls: str = "6.10") -> tuple[tuple, list]:
    """(SLS combination, [ULS combinations]) as (name, {case: factor})."""
    basis = (design_basis or "en1990").lower()
    if basis == "unfactored":
        return SLS, [("Unfactored", {"G": 1.0, "Q": 1.0})]
    if basis != "en1990":
        raise ValueError("design_basis must be 'en1990' or 'unfactored'.")
    if uls == "6.10":
        return SLS, [("ULS 6.10", {"G": GAMMA_G, "Q": GAMMA_Q})]
    if uls == "6.10ab":
        return SLS, [("ULS 6.10a", {"G": GAMMA_G, "Q": PSI_0 * GAMMA_Q}),
                     ("ULS 6.10b", {"G": XI * GAMMA_G, "Q": GAMMA_Q})]
    raise ValueError("uls_combination must be '6.10' or '6.10ab'.")


def _label(factors: dict) -> str:
    return " + ".join(f"{v:g}{k}" for k, v in factors.items())


PHI_0 = 1 / 200            # EN 1993-1-1 5.3.2(3) basic sway imperfection
STABILITY_SUBDIVISION = 4   # elements per member for geometric stiffness (alpha_cr error ~0.05 %; 1 element: +22 %)
ALPHA_CR_FIRST_ORDER = 10.0  # 5.2.1(3): first-order analysis suffices at or above this (elastic)


class InstabilityError(ValueError):
    """The frame buckles below the ULS loads (alpha_cr <= 1 or second-order divergence)."""
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def subdivide(frame, parts: int, only: set | None = None) -> None:
    """Split bending members (all, or the element indices in ``only``) into ``parts`` equal elements
    (in place; loads, releases and lineage follow). Geometric stiffness is only accurate with interior
    nodes; first-order results are exact either way."""
    if parts < 2:
        return
    for ei in range(len(frame.elements)):
        if frame.elements[ei].truss or (only is not None and ei not in only):
            continue
        tail = ei
        for j in range(1, parts):
            frame.split_element(tail, 1.0 / (parts - j + 1))
            tail = len(frame.elements) - 1


def sway_imperfection(frame) -> dict:
    """EN 1993-1-1 5.3.2(3): phi = phi_0 * alpha_h * alpha_m, alpha_h = 2/sqrt(h) in [2/3, 1],
    alpha_m = sqrt(0.5 (1 + 1/m)), h = height of the structure, m = number of column lines.
    No columns (or no height): no sway imperfection."""
    X = np.asarray(frame.nodes, float)
    lines = set()
    for e in frame.elements:
        d = X[e.n2] - X[e.n1]
        L = float(np.linalg.norm(d))
        if L > 0 and abs(d[2]) / L > 0.98:
            lines.add((round(float(X[e.n1][0]), 2), round(float(X[e.n1][1]), 2)))
    h = float(X[:, 2].max() - X[:, 2].min()) if len(X) else 0.0
    if not lines or h < 0.1:
        return {"phi": 0.0, "h_m": round(h, 3), "columns": len(lines), "basis": "no columns: no sway imperfection"}
    a_h = min(1.0, max(2 / 3, 2 / math.sqrt(h)))
    a_m = math.sqrt(0.5 * (1 + 1 / len(lines)))
    return {"phi": PHI_0 * a_h * a_m, "h_m": round(h, 3), "columns": len(lines), "alpha_h": round(a_h, 4),
            "alpha_m": round(a_m, 4), "basis": "EN 1993-1-1 5.3.2(3), phi_0 = 1/200"}


def _imperfection_loads(asm, frame, combo, phi) -> dict:
    """Equivalent horizontal forces phi * V at every loaded free node, in +x, -x, +y, -y."""
    if phi <= 0:
        return {"": None}
    F = fs.load_vector(asm, combo).reshape(-1, fs.DOF)
    V = np.where(F[:, 2] < 0, -F[:, 2], 0.0)
    for n, flags in frame.supports.items():
        if flags[2]:                                       # vertically supported: the load goes straight down
            V[n] = 0.0
    out = {}
    for label, axis, sign in (("+x", 0, 1), ("-x", 0, -1), ("+y", 1, 1), ("-y", 1, -1)):
        H = np.zeros_like(F)
        H[:, axis] = sign * phi * V
        out[label] = H.reshape(-1)
    return out


def _solve_design(frame, design_basis, uls, plastic=False, stations=11, stability="auto"):
    """Solve SLS + ULS combinations; per-element ULS envelope. Returns (sls, uls_results, envelope,
    stability report) with envelope[i] = (utilization, governing name, element result).

    stability="auto": alpha_cr per ULS combination; sway imperfections (5.3.2) in every ULS check;
    alpha_cr < 10 -> second-order (P-Delta) ULS analysis; alpha_cr <= 1 -> InstabilityError.
    stability="off": first-order, no imperfections."""
    sls, ulss = combinations(design_basis, uls)
    if (stability or "auto").lower() == "off":
        res = fs.solve_combinations(frame, {sls[0]: sls[1], **dict(ulss)}, stations=stations, plastic=plastic)
        envelope = []
        for i in range(len(frame.elements)):
            best = max(((res[n].elements[i].utilization, n) for n, _ in ulss), key=lambda t: t[0])
            envelope.append((best[0], best[1], res[best[1]].elements[i]))
        return res[sls[0]], [(n, f, res[n]) for n, f in ulss], envelope, {"mode": "off", "method": "first-order"}
    if (stability or "").lower() != "auto":
        raise ValueError("stability must be 'auto' or 'off'.")
    # buckling needs interior nodes in the compression members: refine those (in place), then re-assemble
    asm = fs.prepare(frame)
    compressed = set()
    for _, factors in ulss:
        N = fs.axial_forces(asm, factors)
        if N.size and N.min() < 0:
            compressed |= {i for i in range(len(N)) if N[i] < 0.01 * N.min()}
    if compressed:
        subdivide(frame, STABILITY_SUBDIVISION, compressed)
        asm = fs.prepare(frame)
    sls_res = fs.solve_linear(asm, sls[1], stations=stations, plastic=plastic)
    imp = sway_imperfection(frame)
    report = {"mode": "auto", "alpha_cr": {}, "sway_imperfection": imp, "second_order": [], "iterations": 0,
              "elements_per_member": STABILITY_SUBDIVISION}
    variants = []                                           # (name, factors, result)
    for name, factors in ulss:
        alpha, _ = fs.critical_load_factor(asm, factors)
        report["alpha_cr"][name] = None if math.isinf(alpha) else round(alpha, 3)
        if alpha <= 1.0:
            report["method"] = "unstable"
            raise InstabilityError(f"Instability: elastic critical load factor alpha_cr = {alpha:.2f} <= 1 under "
                                   f"{name}: the frame buckles before reaching the design loads.", report)
        second = alpha < ALPHA_CR_FIRST_ORDER
        if second:
            report["second_order"].append(name)
        for label, H in _imperfection_loads(asm, frame, factors, imp["phi"]).items():
            vname = f"{name} {label} sway".strip() if label else name
            try:
                r_ = (fs.solve_second_order(asm, factors, extra=H, stations=stations, plastic=plastic) if second
                      else fs.solve_linear(asm, factors, extra=H, stations=stations, plastic=plastic))
            except fs.MechanismError as exc:
                report["method"] = "unstable"
                raise InstabilityError(f"Instability under {vname}: {exc}", report) from None
            report["iterations"] = max(report["iterations"], r_.iterations)
            variants.append((vname, factors, r_))
    report["method"] = "second-order (P-Delta)" if report["second_order"] else "first-order"
    finite = [a for a in report["alpha_cr"].values() if a is not None]
    report["min_alpha_cr"] = min(finite) if finite else None
    envelope = []
    for i in range(len(frame.elements)):
        best = max(((v[2].elements[i].utilization, v[0]) for v in variants), key=lambda t: t[0])
        envelope.append((best[0], best[1], next(v[2] for v in variants if v[0] == best[1]).elements[i]))
    # one representative per ULS combination (base name): its worst imperfection variant
    reps = []
    for name, factors in ulss:
        mine = [v for v in variants if v[0] == name or v[0].startswith(name + " ")]
        worst = max(mine, key=lambda v: v[2].max_utilization)
        worst[2].variant = worst[0][len(name):].strip()
        reps.append((name, factors, worst[2]))
    return sls_res, reps, envelope, report


def view_result(model: dict, load_kn: float = 10.0, material: str = "Steel", fixed_supports: bool = True,
                self_weight: bool = True, diameter_mm=None, wall_mm=None, span_m: float | None = None,
                stations: int = 13, asset_loads: dict | None = None,
                floor_loads: dict | None = None, design_basis: str = "en1990",
                uls: str = "6.10", connections: str = "rigid", stability: str = "auto",
                view: str = "deflection") -> tuple[dict, float]:
    """Solve and package the result for the bridge's ``structure_draw`` overlay.

    Returns (result, span_m): per-element start/end points and sampled global displacements in
    meters (SLS characteristic), ULS utilization envelope, supports, loaded nodes and the max
    displacement. Raises frame_solver.MechanismError for unstable models."""
    frame, info, warnings = build_frame(model, load_kn, material, fixed_supports, self_weight, diameter_mm, wall_mm,
                                        asset_loads, floor_loads, connections)
    want_mode = (view or "deflection").lower() == "buckling"
    if (view or "deflection").lower() not in ("deflection", "buckling"):
        raise ValueError("view must be 'deflection' or 'buckling'.")
    res, ulss, envelope, stab = _solve_design(frame, design_basis, uls, stations=stations,
                                              stability="off" if want_mode else stability)
    span = float(span_m or model.get("max_member_span_m") or model.get("max_span_m") or 5.0)
    buckling = None
    if want_mode:
        asm = fs.prepare(frame)
        N = fs.axial_forces(asm, combinations(design_basis, uls)[1][0][1])
        if N.size and N.min() < 0:
            subdivide(frame, STABILITY_SUBDIVISION, {i for i in range(len(N)) if N[i] < 0.01 * N.min()})
            asm = fs.prepare(frame)
        name, factors = combinations(design_basis, uls)[1][0]
        alpha, mode = fs.critical_load_factor(asm, factors)
        if math.isinf(alpha):
            raise ValueError("Nothing is in compression under " + name + ": there is no buckling mode to show.")
        res = fs.mode_result(asm, mode, stations=stations)
        buckling = {"combination": name, "alpha_cr": round(alpha, 3)}
    elements = []
    # a buckling mode has no magnitude: no utilization, coloured by shape (and its own, refined elements)
    utils = [None] * len(res.elements) if buckling else [round(u, 4) for u, _, _ in envelope]
    if len(utils) != len(res.elements):
        raise RuntimeError("Element results and utilization envelope do not line up.")
    for er, u in zip(res.elements, utils):
        e = frame.elements[er.index]
        rel = e.releases or (False,) * 12
        elements.append({"source_guids": e.tag or [], "start_m": list(frame.nodes[e.n1]), "end_m": list(frame.nodes[e.n2]),
                         "samples_m": np.round(er.disp, 9).tolist(), "utilization": u,
                         "hinges": [bool(rel[4] or rel[5]), bool(rel[10] or rel[11])]})
    result = {"elements": elements,
              "support_points_m": [list(frame.nodes[n]) for n in info["support_nodes"]],
              "loaded_points_m": [list(frame.nodes[n]) for n in info["loaded_nodes"]],
              "max_displacement_mm": round(res.max_displacement * 1000.0, 3),
              "connections": info["connections"], "stability": stab,
              "combinations": {"deflection": SLS[0],
                               "utilization": [f"{n} ({_label(f)})" for n, f, _ in ulss]},
              "warnings": list(model.get("warnings") or []) + warnings}
    for key in ("asset_loads", "floor_loads"):
        if key in info:
            result[key] = info[key]
    if buckling:
        result["buckling"] = buckling
    return result, span


def validate(model: dict, structure_type: str = "beam", load_kn: float = 10.0, material: str = "Steel",
             fixed_supports: bool = True, self_weight: bool = True, diameter_mm=None, wall_mm=None,
             limit_ratio: float = 250.0, plastic: bool = False, span_m: float | None = None,
             asset_loads: dict | None = None, floor_loads: dict | None = None,
             design_basis: str = "en1990", uls: str = "6.10", connections: str = "rigid",
             stability: str = "auto") -> dict:
    """Run the native check and return a bridge-compatible validation result."""
    result = {"status": "error", "passed": False, "structure_type": structure_type, "material": material,
              "confidence": "high", "suggestions": [], "worst_member_guids": [],
              "warnings": list(model.get("warnings") or []), "assumptions": ASSUMPTIONS,
              "results": {"analysis_method": "native"}}
    t0 = time.perf_counter()
    try:
        frame, info, notes = build_frame(model, load_kn, material, fixed_supports, self_weight, diameter_mm, wall_mm,
                                         asset_loads, floor_loads, connections)
        result["warnings"] += notes
        res, ulss, envelope, stab = _solve_design(frame, design_basis, uls, plastic=plastic, stability=stability)
    except InstabilityError as exc:
        result["verdict"] = METHOD_PREFIX + f"FAILED: {exc}"
        result["status"] = "fail"
        result["results"]["stability"] = exc.report
        result["suggestions"] = ["Brace the frame, fix the column bases, or use stiffer columns: it buckles "
                                 "before reaching the design loads."]
        return result
    except fs.MechanismError as exc:
        result["verdict"] = METHOD_PREFIX + f"FAILED: {exc}"
        result["status"] = "fail"
        result["suggestions"] = ["Add supports or bracing so every part of the structure is restrained."]
        if (connections or "").lower() == "simple":
            result["suggestions"].append("With simple (pinned) connections the frame needs bracing, fixed column "
                                         "bases or rigid joints for stability.")
        result["results"]["mechanism_nodes_m"] = [list(frame.nodes[n]) for n in exc.nodes] if "frame" in locals() else []
        return result
    except ValueError as exc:
        result["verdict"] = str(exc)
        return result

    mat = info["material"]
    if span_m:
        span, basis = float(span_m), "user"
    elif structure_type in ("beam", "frame") and model.get("max_member_span_m", 0) > 0.001:
        span, basis = float(model["max_member_span_m"]), "member"
    else:
        span, basis = float(model.get("max_span_m") or 0.0), "extent"
    if span < 0.001:
        span, basis = 5.0, "default"
    limit_mm = span * 1000.0 / limit_ratio
    dmax_mm = res.max_displacement * 1000.0
    umax = max(u for u, _, _ in envelope)
    governing = max(envelope, key=lambda t: t[0])[1]
    stress = max(er.util_detail.get("max_stress_mpa", 0.0) for _, _, er in envelope)
    per_member: dict = {}                                   # one entry per drawn member (max over its pieces)
    for i, (u, n, _) in enumerate(envelope):
        key = tuple(frame.elements[i].tag or [])
        if key not in per_member or u > per_member[key]["utilization"]:
            per_member[key] = {"source_guids": list(key), "utilization": round(u, 4), "combination": n}
    elem_util = list(per_member.values())
    r = result["results"]
    r.update({
        "max_deflection_mm": round(dmax_mm, 3), "displacement_available": True, "utilization_available": True,
        "deflection_limit_mm": round(limit_mm, 3), "utilization_ratio": round(umax, 4),
        "max_stress_mpa": round(stress, 2), "yield_stress_mpa": mat.fy / 1000.0, "span_m": round(span, 3),
        "span_basis": basis, "reactions_kn": round(float(res.reactions[:, 2].sum()), 3),
        "design_basis": (design_basis or "en1990").lower(),
        "deflection_combination": SLS[0], "utilization_combination": governing,
        "combinations": [{"name": SLS[0], "factors": SLS[1], "max_deflection_mm": round(dmax_mm, 3),
                          "reactions_kn": round(float(res.reactions[:, 2].sum()), 3)}] +
                        [{"name": n, "factors": f, "max_utilization": round(r_.max_utilization, 4),
                          "governing_variant": getattr(r_, "variant", ""),
                          "max_deflection_mm": round(r_.max_displacement * 1000.0, 3),
                          "reactions_kn": round(float(r_.reactions[:, 2].sum()), 3)} for n, f, r_ in ulss],
        "support_points_m": [list(frame.nodes[n]) for n in info["support_nodes"]],
        "loaded_points_m": [list(frame.nodes[n]) for n in info["loaded_nodes"]],
        "per_element_utilization": elem_util,
        "max_member_sag_mm": round(max(er.max_sag for er in res.elements) * 1000.0, 3),
        "support_mode": "fixed" if fixed_supports else "pinned",
        "connections": info["connections"],
        "stability": stab,
        "nodes": len(frame.nodes), "elements": len(frame.elements),
        "equilibrium_error_kn": round(res.equilibrium_error(), 9),
        "solve_ms": round((time.perf_counter() - t0) * 1000.0, 1),
    })
    result["assumptions"] = result["assumptions"] + [
        ("Connections: rigid joints." if info["connections"]["mode"] == "rigid" and not info["connections"]["pinned_ends"]
         else f"Connections: {info['connections']['mode']} ({info['connections']['pinned_ends']} pinned member ends; "
              "beams release major-axis bending, braces both axes; torsion released at one end of "
              "members pinned at both)."),
        (f"Stability (EN 1993-1-1 5.2): alpha_cr {stab.get('min_alpha_cr')} -> {stab['method']}; sway imperfection "
         f"phi = {stab['sway_imperfection']['phi']:.5f} in +/-x, +/-y; member buckling length = member length"
         if stab.get("mode") == "auto" else "Stability check off: first-order, no sway imperfections."),
        f"Load combinations ({r['design_basis']}): deflection at {SLS[0]} ({_label(SLS[1])}); member checks at "
        + ", ".join(f"{n} ({_label(f)})" for n, f, _ in ulss) + ". G = self weight, floor build-up and the weight "
        "of placed items; Q = load_kn, occupancy floor load, contents and occupants."]
    if "floor_loads" in info:
        result["floor_loads"] = info["floor_loads"]
        result["assumptions"] = result["assumptions"] + [
            "Floor loads: every bay enclosed by beams on a level carries the area load; 45-degree two-way "
            "distribution (one-way above 2:1), centroid fan for non-rectangular bays."]
    if "asset_loads" in info:
        result["asset_loads"] = info["asset_loads"]
        if info["asset_loads"]["applied"]:
            result["assumptions"] = result["assumptions"] + [
                "Asset loads: estimated self weight + in-use load per placed asset (structural-loads.json), "
                "carried by the nearest member or shared by the lever rule between two parallel members."]
    failures, sug = [], []
    if dmax_mm > limit_mm:
        failures.append(f"Deflection {dmax_mm:.1f}mm ({SLS[0]}) exceeds L/{limit_ratio:g} limit ({limit_mm:.1f}mm)")
        sug += ["Increase member depth or use a stiffer cross-section", "Add intermediate supports to reduce effective span"]
    if umax > 1.0:
        failures.append(f"Utilization ratio {umax:.2f} ({governing}) exceeds 1.0")
        sug.append("Use a larger cross-section or higher-grade material")
    result["passed"] = not failures
    result["status"] = "pass" if not failures else "fail"
    result["verdict"] = METHOD_PREFIX + (
        f"PASSED: Configured checks satisfied. Deflection {dmax_mm:.1f}mm ({SLS[0]}, limit {limit_mm:.1f}mm), "
        f"Utilization {umax:.2f} ({governing})" if not failures else "FAILED: " + "; ".join(failures))
    result["suggestions"] = sug
    worst = sorted(elem_util, key=lambda e: -e["utilization"])
    seen = []
    for e in worst:
        for g in e["source_guids"]:
            if g not in seen:
                seen.append(g)
    result["worst_member_guids"] = seen[:5]
    if res.auto_restrained:
        result["warnings"].append(f"{len(res.auto_restrained)} unstiffened rotation(s) at pin-jointed nodes were restrained.")
    return result
