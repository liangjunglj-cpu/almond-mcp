"""The Rhino panel's environment engine: ``almond-mcp environment`` reads one JSON request on stdin and
writes one JSON reply on stdout (the same out-of-process pattern as ``almond-mcp solve``).

Requests ({"action": ...}):
  catalogue                       constructions, sets, room uses, code packs, step and study diagrams
  construction  {id | custom}     one assembly in full, with its section detail (SVG)
  site          {epw_path}        location and climate headline, sun-path diagram
  rooms         {export}          rooms and their enclosure check, room plan
  climate       {epw_path}        warmest / coldest week and day, the file's own periods, monthly diurnal chart
  setpoints     {met, clo_heating, clo_cooling, rh, air_speed, category}
                                  heating / cooling set-points from PMV
  run           {export, epw_path, study, settings, envelope_pack, pack_options}
                                  study: thermal | daylight | view_out | sunlight | shadows. The study, per-room
                                  results, the tinted plan, metric tiles, charts and a draw file (coloured quads in
                                  rhino.draw_file format) for the viewport
  charts        {run_id, epw_path, room}
                                  a thermal run's week and energy-balance charts for one room
  compare       {cases: [{name, run_id}], epw_path, room}
                                  kept runs side by side: table, bar charts, operative-temperature weeks
  run_dir       {run_id}          a saved run's folder (CSV files and charts)

``export`` is the JSON the environment export script writes (rhino.export_script). Diagrams come from
diagrams.py, so the panel and the boards share one visual language.
"""
from __future__ import annotations

import json
import sys
import traceback

import numpy as np

from . import (cases, charts, climate, codes, comfort, constructions as asm, diagrams, en17037, epw, render, rhino,
               rooms as rm, shadows, studies)

# panel-only keys of a study request; the rest of a thermal request are thermal.Settings fields
PANEL_KEYS = {"cooling", "daylight_study", "quality", "spacing_m", "heating_setpoint", "cooling_setpoint", "export_csv",
              "balance_room", "view_height_m", "month", "day", "times", "date_range", "min_altitude_deg"}
MAX_CASES = 12


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


def climate_action(req: dict) -> dict:
    w = epw.load(req["epw_path"])
    ch = studies.climate_charts(w)
    return {"weeks": climate.extreme_weeks(w), "svg": climate.diurnal_chart(w).svg("Monthly diurnal averages"),
            "files": ch["files"], "run_dir": str(studies.runs_dir() / ch["run_id"])}


def setpoints(req: dict) -> dict:
    def num(key, lo, hi, default):
        v = req.get(key)
        v = default if v in (None, "") else float(v)
        if not lo <= v <= hi:
            raise ValueError(f"{key} must be {lo:g}..{hi:g}")
        return v
    return {"setpoints": comfort.pmv_setpoints(num("met", 0.7, 4, 1.2), num("clo_heating", 0, 2, 1.0), num("clo_cooling", 0, 2, 0.5),
                                               num("rh", 0, 100, 50.0), num("air_speed", 0, 2, 0.1), str(req.get("category") or "II"))}


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


def _draw_metric(arrays: dict, metric: str, units: float) -> str:
    """A saved run's metric as coloured quads with a legend, for the viewport ('' when the run has none)."""
    if metric not in arrays or "cells" not in arrays:
        return ""
    unit, lo, hi, ramp, title = studies.DISPLAY.get(metric, ("", None, None, "viridis", metric))
    v = arrays[metric].astype(float) * (100.0 if metric in studies.PERCENT_METRICS else 1.0)
    lo, hi = render.nice_range(v, lo, hi)
    quads, labels = render.legend_geometry(arrays["cells"], lo, hi, unit, title, ramp, normals=arrays.get("normals"))
    return rhino.draw_file(arrays["cells"], render.colorize(v, lo, hi, ramp), units, labels, quads)


def _data_uri(png_path: str) -> str:
    import base64
    from pathlib import Path
    return "data:image/png;base64," + base64.b64encode(Path(png_path).read_bytes()).decode("ascii")


def thermal_charts(result: dict, arrays: dict, weather, room: str = "") -> dict:
    """Operative temperature of the rooms through the warmest and coldest week, and one room's hourly energy
    balance on the hottest and coldest day, as SVG (from a saved rooms-thermal run)."""
    rows = [(k, r) for k, r in enumerate(result.get("rooms") or []) if r.get("thermal") and f"r{k}_t_op" in arrays]
    if not rows:
        return {}
    ext = climate.extreme_weeks(weather)
    warm, cold = ext["warmest_week"], ext["coldest_week"]
    site = weather.location.label()
    t_ops = [(r["room"], arrays[f"r{k}_t_op"]) for k, r in rows[:8]]
    k, r = next(((k, r) for k, r in rows if r["room"] == room), rows[0])
    pre = f"r{k}_bal_"
    bal = {"balance_w": {key[len(pre):]: v for key, v in arrays.items() if key.startswith(pre)}}
    out = {"room": r["room"], "rooms": [x["room"] for _, x in rows],
           "warmest_week": cases.week_chart(weather, t_ops, warm["start_day_of_year"] - 1,
                                            f"Operative temperature, warmest week {warm['start']} - {warm['end']} ({site})").svg("Warmest week"),
           "coldest_week": cases.week_chart(weather, t_ops, cold["start_day_of_year"] - 1,
                                            f"Operative temperature, coldest week {cold['start']} - {cold['end']} ({site})").svg("Coldest week")}
    if bal["balance_w"]:
        area = r["thermal"]["floor_area_m2"]
        hot, cd = warm["hottest_day"], cold["coldest_day"]
        out["balance_hottest_day"] = cases.balance_chart(bal, area, hot["day_of_year"] - 1,
                                                         f"{r['room']}: energy balance, hottest day {hot['date']}").svg("Hottest day")
        out["balance_coldest_day"] = cases.balance_chart(bal, area, cd["day_of_year"] - 1,
                                                         f"{r['room']}: energy balance, coldest day {cd['date']}").svg("Coldest day")
    return out


def charts_action(req: dict) -> dict:
    result, arrays = studies.load_run(str(req["run_id"]))
    if result.get("study") != "rooms_thermal":
        raise ValueError("charts are for thermal room studies")
    return {"charts": thermal_charts(result, arrays, epw.load(req["epw_path"]), str(req.get("room") or ""))}


# the figures compared across kept runs, per study: (key, label, unit)
COMPARE = {"rooms_thermal": [("heating_kwh_m2", "Heating", "kWh/m²"), ("cooling_kwh_m2", "Cooling", "kWh/m²"),
                             ("lighting_kwh_m2", "Lighting", "kWh/m²"), ("hours_above_26c", "Hours above 26 °C", "h"),
                             ("adaptive_too_warm_h", "Adaptive cat. II too warm", "h"),
                             ("adaptive_too_cool_h", "Adaptive cat. II too cool", "h")],
           "rooms_daylight": [("average_df_pct", "Mean daylight factor", "%"), ("sda_pct", "sDA300/50%", "%"),
                              ("ase_pct", "ASE1000/250h", "%")],
           "rooms_view_out": [("minimum", "View out: at least minimum", "%"), ("medium", "View out: at least medium", "%"),
                              ("high", "View out: high", "%")]}


def _case_figures(result: dict, room: str) -> dict:
    """One kept run's comparable figures: the named room's, or over all rooms (area-weighted energies,
    the worst room's hours)."""
    rows = [r for r in result.get("rooms") or [] if not room or r.get("room") == room]
    out = {}
    if result.get("study") == "rooms_thermal":
        th = [r["thermal"] for r in rows if r.get("thermal")]
        area = sum(t["floor_area_m2"] for t in th)
        if not area:
            return out
        for key in ("heating_kwh_m2", "cooling_kwh_m2", "lighting_kwh_m2"):
            if all(t.get(key) is not None for t in th):
                out[key] = round(sum(t[key] * t["floor_area_m2"] for t in th) / area, 1)
        out["hours_above_26c"] = max(t["hours_above_26c_occupied"] for t in th)
        ad = [t.get("adaptive_en16798_hours", {}).get("II") for t in th]
        if all(ad):
            out["adaptive_too_warm_h"] = max(a["too_warm_h"] for a in ad)
            out["adaptive_too_cool_h"] = max(a["too_cool_h"] for a in ad)
    else:
        w = [r.get("floor_area_m2") or r.get("viewpoints") or 1.0 for r in rows]
        for key, _, _ in COMPARE.get(result.get("study"), []):
            vals = [(r[key], wi) for r, wi in zip(rows, w) if r.get(key) is not None]
            if vals:
                out[key] = round(sum(v * wi for v, wi in vals) / sum(wi for _, wi in vals), 1)
    return out


def compare(req: dict) -> dict:
    """Kept runs side by side: one row per case, a bar chart per figure, and for thermal runs the operative
    temperature of the chosen room (or each case's first room) through the warmest and coldest week."""
    kept = req.get("cases") or []
    if not kept:
        raise ValueError("Keep at least one run as a case first")
    if len(kept) > MAX_CASES:
        raise ValueError(f"At most {MAX_CASES} cases")
    room = str(req.get("room") or "")
    loaded = []
    for c in kept:
        result, arrays = studies.load_run(str(c["run_id"]))
        loaded.append((str(c.get("name") or result.get("label") or c["run_id"])[:40], result, arrays))
    kinds = {r.get("study") for _, r, _ in loaded}
    if len(kinds) != 1 or not kinds <= set(COMPARE):
        raise ValueError("Compare cases of one study type: thermal, daylight or view out")
    study = kinds.pop()
    names = [n for n, _, _ in loaded]
    if len(set(names)) != len(names):
        raise ValueError(f"Case names must be unique: {names}")
    rows = [{"case": n, "run_id": r["run_id"], **_case_figures(r, room)} for n, r, _ in loaded]
    bars = {}
    for key, label, unit in COMPARE[study]:
        vals = [row.get(key) for row in rows]
        if any(v is not None for v in vals):
            bars[key] = charts.bar_chart(names, vals, label + (f" - {room}" if room else ""), unit).svg(label)
    out = {"study": study, "room": room or "all rooms", "rows": rows, "figures": [list(f) for f in COMPARE[study]],
           "bars": bars}
    if study == "rooms_thermal" and req.get("epw_path"):
        weather = epw.load(req["epw_path"])
        ext = climate.extreme_weeks(weather)
        series = []
        for n, r, arrays in loaded:
            ks = [k for k, x in enumerate(r["rooms"]) if x.get("thermal") and (not room or x["room"] == room)]
            if ks and f"r{ks[0]}_t_op" in arrays:
                series.append((n, arrays[f"r{ks[0]}_t_op"]))
        if series:
            site = weather.location.label()
            for tag in ("warmest", "coldest"):
                wk = ext[f"{tag}_week"]
                out[f"{tag}_week"] = cases.week_chart(weather, series, wk["start_day_of_year"] - 1,
                                                      f"Operative temperature, {tag} week {wk['start']} - {wk['end']} "
                                                      f"({room or 'first room'}, {site})").svg(f"{tag} week")
    return out


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
        draw = _draw_metric(arrays, "da" if "da" in arrays else "df", units)
        extra = {}
        rs, encs, _, _ = studies.prepare_rooms(data)
        plan = diagrams.room_plan(_room_outlines(rs, encs), title, values, unit, vrange)
    elif study == "thermal":
        weather = epw.load(req["epw_path"])
        panel_s = {k: s[k] for k in PANEL_KEYS if k in s}
        st = cases.settings_from({k: v for k, v in s.items() if k not in PANEL_KEYS and v is not None})
        sp = rm.parse_setpoints(panel_s.get("heating_setpoint"), panel_s.get("cooling_setpoint"), "all rooms: ")
        res = studies.run_rooms_thermal(data, weather, st, req.get("label", ""),
                                        {"epw_path": req["epw_path"], "units_to_m": units, "export_csv": bool(panel_s.get("export_csv"))},
                                        envelope_pack=req.get("envelope_pack", ""), pack_options=req.get("pack_options"),
                                        cooling=bool(panel_s.get("cooling", True)), setpoints=sp or None)
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
        b = res.get("building") or {}
        tiles = []
        if b.get("heating_kwh_m2") is not None:
            tiles += [(f"{b['heating_kwh_m2']:.0f}", "heating", "kWh/m²"), (f"{b['cooling_kwh_m2']:.0f}", "cooling", "kWh/m²")]
            if b.get("lighting_kwh_m2") is not None:
                tiles.append((f"{b['lighting_kwh_m2']:.0f}", "lighting", "kWh/m²"))
            tiles.append((f"{max(values.values()):.0f}", "max h > 26 °C", ""))
        if open_rooms:
            tiles.append((f"{np.mean(list(open_rooms.values())):.1f}", "open rooms SET*", "°C"))
        draw = _draw_rooms(rs, values, unit, title, vrange, "heat", units)
        _, arrays = studies.load_run(res["run_id"])
        extra = {"charts": thermal_charts(res, arrays, weather, str(panel_s.get("balance_room") or ""))}
        if panel_s.get("export_csv"):
            extra["csv_dir"] = res["run_dir"]
    elif study == "view_out":
        res = studies.run_rooms_view_out(data, float(s.get("view_height_m") or 1.2), float(s.get("spacing_m") or 0.6),
                                         label=req.get("label", ""))
        values = {r["room"]: r["medium"] for r in res["rooms"]}
        title, unit = "Floor with at least a medium view", "%"
        rs, encs, _, _ = studies.prepare_rooms(data)
        plan = diagrams.room_plan(_room_outlines(rs, encs), title, values, unit, (0.0, 100.0))
        m = res["metrics"]["area_at_least_pct"]
        tiles = [(f"{m['minimum']:.0f} %", "at least minimum", ""), (f"{m['medium']:.0f} %", "at least medium", ""),
                 (f"{m['high']:.0f} %", "high", "")]
        _, arrays = studies.load_run(res["run_id"])
        draw = _draw_metric(arrays, "view_level", units)
        extra = {}
    elif study in ("sunlight", "shadows"):
        weather = epw.load(req["epw_path"])
        rs, encs, scene, _ = studies.prepare_rooms(data)
        # a room drawn as one closed volume would cover its own windows: use its boundary without the glass
        scene, _ = studies._daylight_shells(data, rs, encs, scene, None)
        month, day = int(s.get("month") or 3), int(s.get("day") or (21 if study == "sunlight" else 20))
        run_id = studies.new_run_id("sunlight" if study == "sunlight" else "sun")
        d = studies.runs_dir() / run_id
        d.mkdir(parents=True, exist_ok=True)
        if study == "sunlight":
            st = en17037.sunlight_study(scene, weather.location, month, day, d, s.get("date_range"),
                                        float(s.get("min_altitude_deg", 10.0)))
            svg = st.pop("chart_svg", "")
            res = {"run_id": run_id, "study": "en17037_sunlight", "label": req.get("label") or "sunlight", **st}
            hours = [w["sun_hours"] for w in st["windows"]]
            tiles = [(f"{max(hours):.1f}", "best window", "h"), (f"{sum(h >= 1.5 for h in hours)}/{len(hours)}", "windows ≥ 1.5 h", "")]
            extra = {"charts": {"sunlight": svg}} if svg else {}
        else:
            st = shadows.study(scene, weather.location, month, day, s.get("times"),
                               str(d / f"shadow-plans-{month:02d}{day:02d}.png"))
            res = {"run_id": run_id, "study": "shadow_study", "label": req.get("label") or f"shadows {month}/{day}",
                   "site": weather.location.label(), **{k: v for k, v in st.items() if k != "suns"},
                   "headline": f"Shadow plans, {st['date']}: " + ", ".join(r["time"] for r in st["shots"]),
                   "rooms": [], "notes": st["notes"] + [f"Times are {st['time_convention']}."]}
            tiles = []
            extra = {"image": _data_uri(st["sheet"])}
        studies.save_run(run_id, res, None, {})
        res["run_dir"] = str(d)
        return {"result": res, "svg": "", "tiles_svg": diagrams.results_tiles(tiles).svg("Results") if tiles else "",
                "draw": "", "label": res["label"], **extra}
    else:
        raise ValueError("study must be thermal, daylight, view_out, sunlight or shadows")
    return {"result": res, "svg": plan.svg(title), "tiles_svg": diagrams.results_tiles(tiles).svg("Results") if tiles else "",
            "draw": draw, "label": res.get("label", study), **extra}


def run_dir(req: dict) -> dict:
    """A saved run's folder (its CSV files and charts), for the panel to open."""
    return {"run_dir": str(studies._safe_run_dir(str(req.get("run_id") or "")))}


def export_script(req: dict) -> dict:
    """The C# export script for the panel to run in Rhino (writes the export JSON to req['out'])."""
    return {"script": rhino.export_script([str(g) for g in req.get("guids") or []], str(req["out"]))}


ACTIONS = {"catalogue": catalogue, "construction": construction, "site": site, "climate": climate_action,
           "setpoints": setpoints, "rooms": rooms, "run": run, "charts": charts_action, "compare": compare,
           "run_dir": run_dir, "export_script": export_script}
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
