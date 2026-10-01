"""Almond's native structural check: a conditioned line model -> frame_solver -> validation result.

The bridge's ``structure_model`` message exports the same conditioned geometry the Karamba
path analyses (welded nodes, members split at intersections, inferred sections, declared
support points). This module applies the same modelling conventions as the Karamba adapter
so the two engines are comparable:

- supports: declared anchor points (snapped to the nearest node), else every lowest-Z node;
  fully fixed, or pinned (translations only) when ``fixed_supports`` is False;
- imposed load: ``load_kn`` split equally over the free (unsupported) nodes, acting -Z;
- self weight: gamma x A along every member, -Z;
- deflection limit: span / 250, span = longest member for beam/frame, else overall extent,
  unless the caller names the structural span (members split at every node are shorter);
- pass: max deflection within the limit and member utilization <= 1.0.

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


def build_frame(model: dict, load_kn: float, material: str = "Steel", fixed_supports: bool = True,
                self_weight: bool = True, diameter_mm=None, wall_mm=None, asset_loads: dict | None = None,
                floor_loads: dict | None = None):
    """``asset_loads``: {"placements": [...], "table": LoadTable, "catalogue": {...}} adds the
    gravity loads of placed library assets (see asset_loads.apply); its report is info["asset_loads"].
    ``floor_loads``: {"imposed": kN/m2, "dead": kN/m2, "levels": [z m] | None} loads every enclosed
    floor bay (see floor_loads.apply); its report is info["floor_loads"]."""
    """Frame + bookkeeping from an exported conditioned model (all coordinates in meters)."""
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
    for m in model.get("members", []):
        sec, notes = section_from_spec(m.get("section"), diameter_mm, wall_mm)
        warnings += notes
        pts = m.get("points") or []
        for a, b in zip(pts, pts[1:]):
            if math.dist(a, b) <= tol:
                continue
            ei = frame.add_element(node(a), node(b), sec, mat, tag=list(m.get("source_guids", [])))
            lineage.append(ei)
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
            frame.load(n, fz=-load_kn / len(free))
    if self_weight:
        frame.gravity = (0.0, 0.0, -1.0)
    info = {"support_nodes": support_nodes, "loaded_nodes": free if load_kn > 0 else [], "material": mat}
    if floor_loads and (floor_loads.get("imposed") or floor_loads.get("dead")):
        info["floor_loads"] = fl.apply(frame, floor_loads.get("imposed", 0.0), floor_loads.get("dead", 0.0),
                                       floor_loads.get("levels"))
        warnings += info["floor_loads"]["warnings"]
    if asset_loads:
        report = al.apply(frame, asset_loads["placements"], asset_loads["table"], asset_loads.get("catalogue") or {})
        info["asset_loads"] = report
        info["loaded_nodes"] = sorted(set(info["loaded_nodes"]) | set(report["loaded_nodes"]))
    return frame, info, warnings


def view_result(model: dict, load_kn: float = 10.0, material: str = "Steel", fixed_supports: bool = True,
                self_weight: bool = True, diameter_mm=None, wall_mm=None, span_m: float | None = None,
                stations: int = 13, asset_loads: dict | None = None,
                floor_loads: dict | None = None) -> tuple[dict, float]:
    """Solve and package the result for the bridge's ``structure_draw`` overlay.

    Returns (result, span_m): per-element start/end points and sampled global displacements in
    meters, utilization, supports, loaded nodes and the max displacement. Raises
    frame_solver.MechanismError for unstable models."""
    frame, info, warnings = build_frame(model, load_kn, material, fixed_supports, self_weight, diameter_mm, wall_mm,
                                        asset_loads, floor_loads)
    res = fs.solve(frame, stations=stations)
    span = float(span_m or model.get("max_member_span_m") or model.get("max_span_m") or 5.0)
    elements = []
    for er in res.elements:
        e = frame.elements[er.index]
        elements.append({"source_guids": e.tag or [], "start_m": list(frame.nodes[e.n1]), "end_m": list(frame.nodes[e.n2]),
                         "samples_m": np.round(er.disp, 9).tolist(), "utilization": round(er.utilization, 4)})
    result = {"elements": elements,
              "support_points_m": [list(frame.nodes[n]) for n in info["support_nodes"]],
              "loaded_points_m": [list(frame.nodes[n]) for n in info["loaded_nodes"]],
              "max_displacement_mm": round(res.max_displacement * 1000.0, 3),
              "warnings": list(model.get("warnings") or []) + warnings}
    for key in ("asset_loads", "floor_loads"):
        if key in info:
            result[key] = info[key]
    return result, span


def validate(model: dict, structure_type: str = "beam", load_kn: float = 10.0, material: str = "Steel",
             fixed_supports: bool = True, self_weight: bool = True, diameter_mm=None, wall_mm=None,
             limit_ratio: float = 250.0, plastic: bool = False, span_m: float | None = None,
             asset_loads: dict | None = None, floor_loads: dict | None = None) -> dict:
    """Run the native check and return a bridge-compatible validation result."""
    result = {"status": "error", "passed": False, "structure_type": structure_type, "material": material,
              "confidence": "high", "suggestions": [], "worst_member_guids": [],
              "warnings": list(model.get("warnings") or []), "assumptions": ASSUMPTIONS,
              "results": {"analysis_method": "native"}}
    t0 = time.perf_counter()
    try:
        frame, info, notes = build_frame(model, load_kn, material, fixed_supports, self_weight, diameter_mm, wall_mm,
                                         asset_loads, floor_loads)
        result["warnings"] += notes
        res = fs.solve(frame, plastic=plastic)
    except fs.MechanismError as exc:
        result["verdict"] = METHOD_PREFIX + f"FAILED: {exc}"
        result["status"] = "fail"
        result["suggestions"] = ["Add supports or bracing so every part of the structure is restrained."]
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
    umax = res.max_utilization
    stress = max(er.util_detail.get("max_stress_mpa", 0.0) for er in res.elements)
    elem_util = [{"source_guids": frame.elements[er.index].tag or [], "utilization": round(er.utilization, 4)}
                 for er in res.elements]
    r = result["results"]
    r.update({
        "max_deflection_mm": round(dmax_mm, 3), "displacement_available": True, "utilization_available": True,
        "deflection_limit_mm": round(limit_mm, 3), "utilization_ratio": round(umax, 4),
        "max_stress_mpa": round(stress, 2), "yield_stress_mpa": mat.fy / 1000.0, "span_m": round(span, 3),
        "span_basis": basis, "reactions_kn": round(float(res.reactions[:, 2].sum()), 3),
        "support_points_m": [list(frame.nodes[n]) for n in info["support_nodes"]],
        "loaded_points_m": [list(frame.nodes[n]) for n in info["loaded_nodes"]],
        "per_element_utilization": elem_util,
        "max_member_sag_mm": round(max(er.max_sag for er in res.elements) * 1000.0, 3),
        "support_mode": "fixed" if fixed_supports else "pinned",
        "nodes": len(frame.nodes), "elements": len(frame.elements),
        "equilibrium_error_kn": round(res.equilibrium_error(), 9),
        "solve_ms": round((time.perf_counter() - t0) * 1000.0, 1),
    })
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
        failures.append(f"Deflection {dmax_mm:.1f}mm exceeds L/{limit_ratio:g} limit ({limit_mm:.1f}mm)")
        sug += ["Increase member depth or use a stiffer cross-section", "Add intermediate supports to reduce effective span"]
    if umax > 1.0:
        failures.append(f"Utilization ratio {umax:.2f} exceeds 1.0")
        sug.append("Use a larger cross-section or higher-grade material")
    result["passed"] = not failures
    result["status"] = "pass" if not failures else "fail"
    result["verdict"] = METHOD_PREFIX + (
        f"PASSED: Configured checks satisfied. Deflection {dmax_mm:.1f}mm (limit {limit_mm:.1f}mm), "
        f"Utilization {umax:.2f}" if not failures else "FAILED: " + "; ".join(failures))
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
