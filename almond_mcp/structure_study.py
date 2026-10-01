"""One native structural study from one JSON request: the Rhino panel's solver (``almond-mcp solve``).

The Almond panel exports its conditioned line model (and, when asked, the placed library assets) from
Rhino, pipes ``{"protocol": 1, "model": ..., "placements": [...], "settings": {...}}`` to
``almond-mcp solve`` and draws the returned overlay through the bridge's ``structure_draw`` conduit.
The MCP tools share :func:`draw_message`, so both routes draw identical overlays.

Imports only the numerical modules (no MCP server, no index build), so a solve starts quickly.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from almond_mcp import __version__, asset_loads, design_codes, native_structure, paths

PROTOCOL = 1

DEFAULTS = {
    "structure": "frame", "material": "Steel", "load_kn": 10.0, "self_weight": True, "fixed_rotations": True,
    "diameter_mm": None, "wall_mm": None, "span_m": None, "floor_imposed_kn_m2": 0.0, "floor_dead_kn_m2": 0.0,
    "asset_loads": False, "design_basis": "en1990", "uls_combination": None, "connections": "rigid",
    "stability": "auto", "view": "deflection", "design_code": design_codes.DEFAULT, "deflection_limit_ratio": None,
}
CHOICES = {
    "structure": ("beam", "frame", "truss"), "design_basis": ("en1990", "unfactored"),
    "connections": ("rigid", "simple"), "stability": ("auto", "off"),
    "view": ("deflection", "buckling"),
}


def settings(raw: dict | None) -> dict:
    """Defaults + validation of the panel settings (unknown keys are ignored: older/newer panels)."""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (raw or {}).items() if k in DEFAULTS and v is not None})
    for key, allowed in CHOICES.items():
        s[key] = str(s[key]).lower()
        if s[key] not in allowed:
            raise ValueError(f"{key} must be one of: {', '.join(allowed)}.")
    for key in ("load_kn", "floor_imposed_kn_m2", "floor_dead_kn_m2"):
        s[key] = float(s[key])
        if not math.isfinite(s[key]) or s[key] < 0:
            raise ValueError(f"{key} must be finite and non-negative.")
    if s["uls_combination"] not in (None, "6.10", "6.10ab"):
        raise ValueError("uls_combination must be one of: 6.10, 6.10ab (or empty for the design code's choice).")
    s["design_code"] = str(s["design_code"] or design_codes.DEFAULT).lower()
    if s["deflection_limit_ratio"] is not None and not 100 <= float(s["deflection_limit_ratio"]) <= 1000:
        raise ValueError("deflection_limit_ratio must be between 100 and 1000 (span/ratio).")
    if (s["diameter_mm"] is None) != (s["wall_mm"] is None):
        raise ValueError("Give both the CHS diameter and wall thickness, or neither.")
    if s["span_m"] is not None and not (math.isfinite(float(s["span_m"])) and float(s["span_m"]) > 0):
        raise ValueError("span_m must be a positive length in meters.")
    return s


def asset_catalogue(placements: list[dict], lookup) -> dict:
    """Catalogue facts the asset-load estimate needs, per placed asset id (lookup: id -> manifest record)."""
    catalogue = {}
    for pl in placements:
        a = lookup(pl["asset_id"]) or {}
        catalogue[pl["asset_id"]] = {"category": a.get("category", ""), "name": a.get("product", ""),
                                     "support_plane": (a.get("spatial") or {}).get("support_plane", "floor"),
                                     "nominal_mm": a.get("nominal_dimensions_mm") or {}}
    return catalogue


def _asset_spec(placements: list[dict]) -> dict:
    library = Path(paths.resolve_dir("RHINO_MCP_GENERATED_ASSET_DIR"))
    table = asset_loads.LoadTable(library / "structural-loads.json")
    manifest = json.loads((library / "manifest.json").read_text(encoding="utf-8"))
    records = {str(a.get("asset_id", "")).strip(): a for a in manifest.get("assets", [])}
    return {"placements": placements, "table": table, "catalogue": asset_catalogue(placements, records.get)}


def draw_message(request: dict, result: dict, span: float) -> tuple[dict, dict]:
    """The bridge ``structure_draw`` message for a native view result, and the reports taken out of it.

    ``request`` carries the display options (load_kn, material, self_weight, fixed_rotations, title,
    color_by, scale, ...); keys that only steer the analysis are not forwarded."""
    reports = {k: result.pop(k, None) for k in
               ("asset_loads", "floor_loads", "combinations", "connections", "stability", "buckling",
                "design_code", "deflection_limit_ratio")}
    draw = {k: v for k, v in request.items() if k not in ("guids", "reanalyze", "clear")}
    draw.update({"type": "structure_draw", "engine": "native", "span_m": span, "result": result})
    buckling, combos = reports["buckling"], reports["combinations"]
    if buckling:
        draw["buckling_alpha"] = buckling["alpha_cr"]
        draw["color_by"] = "displacement"
        if not request.get("title"):
            draw["title"] = "ALMOND  //  NATIVE FEA  ·  BUCKLING  ·  " + buckling["combination"]
    elif combos and not request.get("title"):
        draw["title"] = "ALMOND  //  NATIVE FEA  ·  u: " + " / ".join(combos["utilization"]) + "  ·  d: SLS G + Q"
    report, floor_report = reports["asset_loads"], reports["floor_loads"]
    if report is not None or floor_report is not None:
        parts = [f"load {request['load_kn']:.0f} kN"] if request["load_kn"] >= 0.5 else []
        if floor_report is not None:
            parts.append(f"floor {floor_report['imposed_kn_m2'] + floor_report['dead_kn_m2']:g} kN/m2 "
                         f"x {floor_report['area_m2']:.0f} m2")
        if report is not None:
            parts.append(f"{report['applied']} assets {report['total_kn']:.1f} kN")
        if request["self_weight"]:
            parts.append("self weight")
        draw["load_label"] = " + ".join(parts)
    return draw, reports


def run(request: dict) -> dict:
    """Validate and (when the model is drawable) package the overlay. Never raises for bad input."""
    out = {"protocol": PROTOCOL, "version": __version__, "status": "error"}
    try:
        if int(request.get("protocol", PROTOCOL)) != PROTOCOL:
            raise ValueError(f"Unsupported solve protocol {request.get('protocol')} (this solver speaks {PROTOCOL}).")
        s = settings(request.get("settings"))
        model = request.get("model")
        if not isinstance(model, dict) or model.get("status") != "ok" or "members" not in model:
            raise ValueError("No exported structural model in the request.")
        if model.get("shells"):
            raise ValueError(f"The selection contains {model['shells']} shell element(s). The native solver analyses "
                             "line members; choose the Karamba engine for shells.")
        if not model["members"]:
            raise ValueError("No line members in the selection.")
        code = native_structure.design_profile(s["design_basis"], s["design_code"])
        floor = ({"imposed": s["floor_imposed_kn_m2"], "dead": s["floor_dead_kn_m2"]}
                 if s["floor_imposed_kn_m2"] or s["floor_dead_kn_m2"] else None)
        assets = _asset_spec(list(request.get("placements") or [])) if s["asset_loads"] else None
    except (ValueError, TypeError, KeyError, OSError) as e:
        out["message"] = str(e)
        return out

    common = dict(fixed_supports=s["fixed_rotations"], self_weight=s["self_weight"], diameter_mm=s["diameter_mm"],
                  wall_mm=s["wall_mm"], asset_loads=assets, floor_loads=floor, design_basis=s["design_basis"],
                  uls=s["uls_combination"], connections=s["connections"], stability=s["stability"],
                  design_code=code)
    limit_ratio = float(s["deflection_limit_ratio"] or code.deflection_limit_ratio)
    validation = native_structure.validate(model, s["structure"], s["load_kn"], s["material"],
                                           span_m=s["span_m"], limit_ratio=limit_ratio, **common)
    out.update(status=validation["status"], validation=validation, settings=s)
    if validation["status"] == "error":
        out["message"] = validation.get("verdict", "The native check could not run.")
        return out
    span = (validation.get("results") or {}).get("span_m") or s["span_m"]
    try:
        result, span = native_structure.view_result(model, s["load_kn"], s["material"], span_m=span,
                                                    view=s["view"], **common)
    except native_structure.InstabilityError as e:
        out["message"] = f"{e} Switch the view to Buckling mode to see the shape it buckles into."
        return out
    except native_structure.fs.MechanismError as e:
        out["message"] = str(e)
        return out
    except ValueError as e:
        out["message"] = str(e)
        return out
    display = {"load_kn": s["load_kn"], "material": s["material"], "self_weight": s["self_weight"],
               "fixed_rotations": s["fixed_rotations"], "color_by": "utilization",
               "deflection_limit_ratio": limit_ratio}
    draw, reports = draw_message(display, result, span)
    out["draw"] = draw
    if reports["buckling"]:
        out["buckling"] = reports["buckling"]
    return out


def main(stdin, stdout) -> int:
    """``almond-mcp solve``: one JSON request on stdin, one JSON reply on stdout."""
    try:
        request = json.loads(stdin.read().lstrip("\ufeff") or "{}")
        if not isinstance(request, dict):
            raise ValueError("The request must be a JSON object.")
    except ValueError as e:
        reply = {"protocol": PROTOCOL, "version": __version__, "status": "error", "message": f"Bad request: {e}"}
    else:
        reply = ({"protocol": PROTOCOL, "version": __version__, "status": "ok",
                  "design_codes": design_codes.listing()} if request.get("ping") else run(request))
    stdout.write(json.dumps(_clean(reply), allow_nan=False))
    stdout.flush()
    return 0 if reply["status"] != "error" else 1


def _clean(value):
    """Plain JSON: numpy scalars/arrays to Python, non-finite floats to null."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "tolist"):                      # numpy arrays and scalars
        return _clean(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
