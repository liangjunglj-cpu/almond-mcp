"""The Rhino panel's environment engine: ``almond-mcp environment`` reads one JSON request on stdin and
writes one JSON reply on stdout (the same out-of-process pattern as ``almond-mcp solve``).

Requests ({"action": ...}):
  catalogue                       constructions, sets, room uses, code packs, step and study diagrams
  construction  {id | custom}     one assembly in full, with its section detail (SVG)
  site          {epw_path}        location and climate headline, sun-path diagram
  rooms         {export}          rooms and their enclosure check, room plan
  run           {export, epw_path, study: thermal | daylight, settings, envelope_pack, pack_options}
                                  the study, per-room results, the tinted plan, metric tiles and a draw file
                                  (coloured quads in rhino.draw_file format) for the viewport

``export`` is the JSON the environment export script writes (rhino.export_script). Diagrams come from
diagrams.py, so the panel and the boards share one visual language.
"""
from __future__ import annotations

import json
import sys
import traceback

import numpy as np

from . import codes, constructions as asm, diagrams, epw, render, rhino, rooms as rm, studies, thermal


def _room_outlines(rooms, encs) -> list[dict]:
    out = []
    for r, e in zip(rooms, encs):
        for poly in diagrams._footprint(r.vertices, r.triangles):
            out.append({"name": r.name, "outline": poly[:, :2].tolist(), "state": e.state, "use": r.use,
                        "area": rm._floor_area(r), "level": r.floor_z, "openings": e.openings})
    return out


def catalogue(_req: dict) -> dict:
    return {"constructions": asm.catalogue(), "sets": asm._load("assemblies.json")["sets"],
            "uses": {k: v for k, v in rm.ROOM_USES.items()}, "packs": codes.packs(),
            "steps": {key: diagrams.step_strip(key, tuple(k for k, _ in diagrams.STEPS[:i])).svg(f"Step {i + 1}: {label}")
                      for i, (key, label) in enumerate(diagrams.STEPS)},
            "study": {s: diagrams.study_section(s).svg(f"{s} study") for s in ("daylight", "thermal")},
            "sources": [{k: s[k] for k in ("id", "title", "licence", "attribution")} for s in asm.sources().values()]}


def static_catalogue() -> dict:
    """The catalogue with every section detail pre-rendered, for the archive build and the browser preview
    (served as /api/environment, so browsing constructions needs no engine process)."""
    out = catalogue({})
    out["sections"] = {cid: diagrams.construction_section(asm.properties(cid)).svg(asm.get(cid)["name"]) for cid in asm.library()}
    return out


def construction(req: dict) -> dict:
    p = asm.properties(req.get("custom") or req["id"])
    return {"construction": p, "svg": diagrams.construction_section(p).svg(p["name"])}


def site(req: dict) -> dict:
    w = epw.load(req["epw_path"])
    loc = w.location
    t = np.asarray(w["dry_bulb"], float)
    head = {"location": loc.label(), "latitude": loc.latitude, "longitude": loc.longitude, "time_zone": loc.time_zone,
            "elevation_m": loc.elevation, "dry_bulb_mean_c": round(float(t.mean()), 1), "dry_bulb_max_c": round(float(t.max()), 1),
            "dry_bulb_min_c": round(float(t.min()), 1), "ghi_kwh_m2": round(float(np.nansum(w["ghi"]) / 1000), 0)}
    north = float(req.get("north_deg") or 0.0)
    return {"site": head, "svg": diagrams.site_diagram(loc.latitude, loc.longitude, loc.time_zone, north, loc.label()).svg("Sun path")}


def rooms(req: dict) -> dict:
    data = req["export"]
    rs, encs, _scene, notes = studies.prepare_rooms(data)
    rows = []
    for r, e in zip(rs, encs):
        rows.append({"room": r.name, "use": r.use, "defined_by": r.source, "construction_set": r.construction_set or None,
                     "floor_area_m2": round(rm._floor_area(r), 2), "height_m": round(r.height, 2), "guids": r.guids,
                     "enclosure": e.to_json(), "constructions_on_boundary": sorted({c for c in e.tri_construction if c})})
    plan = diagrams.room_plan(_room_outlines(rs, encs), "Rooms")
    return {"rooms": rows, "warnings": notes, "svg": plan.svg("Rooms")}


def _draw_rooms(rs, values: dict, unit: str, title: str, vrange, ramp: str, scale_to_model: float) -> str:
    cells, vals = [], []
    for r in rs:
        if values.get(r.name) is None:
            continue
        g = rm.daylight_grid(r, 0.5, 0.05, 0.0)
        cells.append(g.cells)
        vals.append(np.full(g.n, float(values[r.name])))
    if not cells:
        return ""
    cells = np.vstack(cells)
    vals = np.concatenate(vals)
    lo, hi = vrange
    colors = render.colorize(vals, lo, hi, ramp)
    quads, labels = render.legend_geometry(cells, lo, hi, unit, title, ramp)
    return rhino.draw_file(cells, colors, scale_to_model, labels, quads)


def run(req: dict) -> dict:
    data = req["export"]
    study = req.get("study", "thermal")
    s = req.get("settings") or {}
    units = float(data.get("units_to_m", 1.0))
    if study == "daylight":
        weather = epw.load(req["epw_path"]) if req.get("epw_path") else None
        res = studies.run_rooms_daylight(data, weather, s.get("daylight_study", "annual"), s.get("quality", "medium"),
                                         req.get("label", ""), float(s.get("spacing_m", 0.5)))
        key, unit, title = ("sda_pct", "%", "sDA300/50%") if any("sda_pct" in r for r in res["rooms"]) else ("average_df_pct", "%", "Daylight factor")
        values = {r["room"]: r.get(key) for r in res["rooms"]}
        vrange = (0.0, 100.0) if key == "sda_pct" else (0.0, max(5.0, max([v for v in values.values() if v is not None] or [5.0])))
        tiles = [(f"{np.mean([v for v in values.values() if v is not None]):.0f} %", "mean " + title, "")] if values else []
        _, arrays = studies.load_run(res["run_id"])
        draw = ""
        metric = "da" if "da" in arrays else "df" if "df" in arrays else ""
        if metric and "cells" in arrays:
            unit_m, lo_m, hi_m, ramp_m, title_m = studies.DISPLAY.get(metric, ("", None, None, "viridis", metric))
            v = arrays[metric].astype(float) * (100.0 if metric in studies.PERCENT_METRICS else 1.0)
            lo_m, hi_m = render.nice_range(v, lo_m, hi_m)
            quads, labels = render.legend_geometry(arrays["cells"], lo_m, hi_m, unit_m, title_m, ramp_m, normals=arrays.get("normals"))
            draw = rhino.draw_file(arrays["cells"], render.colorize(v, lo_m, hi_m, ramp_m), units, labels, quads)
        rs, encs, _, _ = studies.prepare_rooms(data)
        plan = diagrams.room_plan(_room_outlines(rs, encs), title, values, unit, vrange)
    elif study == "thermal":
        weather = epw.load(req["epw_path"])
        st = thermal.Settings(construction=s.get("construction", "typical"), schedule=s.get("schedule", "residential"),
                              infiltration_ach=float(s.get("infiltration_ach", 0.3)),
                              natural_ventilation_ach=float(s.get("natural_ventilation_ach", 0.0)),
                              shading_g_factor=float(s.get("shading_g_factor", 1.0)),
                              shading_min_outdoor_c=s.get("shading_min_outdoor_c"),
                              heat_recovery=float(s.get("heat_recovery", 0.0)))
        res = studies.run_rooms_thermal(data, weather, st, req.get("label", ""), {"epw_path": req["epw_path"], "units_to_m": units},
                                        envelope_pack=req.get("envelope_pack", ""), pack_options=req.get("pack_options"),
                                        cooling=bool(s.get("cooling", True)))
        values, open_rooms = {}, {}
        for r in res["rooms"]:
            if r["method"] == "semi_outdoor":
                open_rooms[r["room"]] = r["comfort"]["set_c"]["mean_occupied"]
            else:
                values[r["room"]] = r["thermal"]["hours_above_26c_occupied"]
        top = max(values.values()) if values else 1
        vrange = (0.0, max(100.0, float(top)))
        unit, title = "h", "Hours above 26 °C (occupied)"
        rs, encs, _, _ = studies.prepare_rooms(data)
        plan = diagrams.room_plan(_room_outlines(rs, encs), title, values or None, unit, vrange, "heat")
        heat = [r["thermal"]["heating_kwh_m2"] for r in res["rooms"] if r["method"] != "semi_outdoor"]
        cool = [r["thermal"]["cooling_kwh_m2"] for r in res["rooms"] if r["method"] != "semi_outdoor"]
        tiles = []
        if heat:
            tiles += [(f"{np.mean(heat):.0f}", "heating", "kWh/m²"), (f"{np.mean(cool):.0f}", "cooling", "kWh/m²"),
                      (f"{max(values.values()):.0f}", "max h > 26 °C", "")]
        if open_rooms:
            tiles.append((f"{np.mean(list(open_rooms.values())):.1f}", "open rooms SET*", "°C"))
        draw = _draw_rooms(rs, values, unit, title, vrange, "heat", units)
    else:
        raise ValueError("study must be thermal or daylight")
    return {"result": res, "svg": plan.svg(title), "tiles_svg": diagrams.results_tiles(tiles).svg("Results") if tiles else "",
            "draw": draw, "label": res.get("label", study)}


def export_script(req: dict) -> dict:
    """The C# export script for the panel to run in Rhino (writes the export JSON to req['out'])."""
    return {"script": rhino.export_script([str(g) for g in req.get("guids") or []], str(req["out"]))}


ACTIONS = {"catalogue": catalogue, "construction": construction, "site": site, "rooms": rooms, "run": run,
           "export_script": export_script}
PROTOCOL = 1


def main(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        req = json.loads(stdin.read() or "{}")
        action = req.get("action", "")
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
        reply = {"status": "ok", **ACTIONS[action](req)}
        if action == "run" and reply.get("draw") and req.get("draw_path"):
            from pathlib import Path
            Path(req["draw_path"]).write_text(reply.pop("draw"), encoding="utf-8")
            reply["draw_script"] = rhino.draw_script(req["draw_path"], "Panel " + reply.get("label", "study"), reply["result"]["run_id"])
    except (ValueError, KeyError, OSError) as exc:
        reply = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - the panel must always get a readable reply
        reply = {"status": "error", "message": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
    reply["protocol"] = PROTOCOL
    stdout.write(json.dumps(studies._jsonable(reply)))
    stdout.flush()
    return 0 if reply["status"] == "ok" else 1
