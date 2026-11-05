"""MCP tools for environmental analysis (climate, sun, daylight, solar radiation, thermal comfort and
energy). Registered on the Almond server by ``register``; the analysis itself lives in
``almond_mcp.environment`` and runs in this process, so only geometry export and result drawing
touch Rhino."""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import numpy as np

from almond_mcp import paths
from almond_mcp.environment import comfort, daylight, epw, rhino, render, scene as scenemod, solar, studies, thermal

Sender = Callable[[bytes, float], str]

READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
WRITES = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}


# Background jobs: a long study on a real model can outlast the MCP client's request timeout, so the
# analyze tools can run in a thread and hand back a job id at once (poll with get_environment_run).
JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _params(fn, values: dict) -> dict:
    """The call's own arguments (locals() also holds closure names), with background switched off."""
    import inspect
    out = {k: values[k] for k in inspect.signature(fn).parameters if k in values}
    out["background"] = False
    return out


def _start_job(kind: str, work: Callable[[], dict]) -> dict:
    job_id = f"job-{kind}-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        JOBS[job_id] = {"state": "running", "kind": kind, "started": time.time()}

    def run():
        try:
            result = work()
            state = "done" if result.get("status") == "success" else "error"
            with _JOBS_LOCK:
                JOBS[job_id].update(state=state, result=result, finished=time.time())
        except Exception as exc:  # noqa: BLE001 - a job must always end in a readable state
            with _JOBS_LOCK:
                JOBS[job_id].update(state="error", result=_err(f"{type(exc).__name__}: {exc}"), finished=time.time())

    threading.Thread(target=run, name=job_id, daemon=True).start()
    return {"status": "running", "job_id": job_id,
            "next_step": f"get_environment_run('{job_id}') until its status is no longer 'running'"}


def _job_status(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        if job["state"] == "running":
            return {"status": "running", "job_id": job_id, "kind": job["kind"],
                    "elapsed_s": round(time.time() - job["started"], 1)}
        out = dict(job["result"])
        out["job_id"] = job_id
        return out


def _err(message: str, **extra) -> dict:
    return {"status": "error", "message": message, **extra}


def _weather(epw_path: str):
    if not epw_path:
        raise ValueError("epw_path is required: the full path to an EnergyPlus weather file (.epw), "
                         "e.g. from climate.onebuilding.org")
    return epw.load(epw_path)


def _execute(send: Sender, script: str, timeout: float) -> dict:
    reply = json.loads(send(json.dumps({"type": "execute", "script": script}).encode("utf-8"), timeout))
    if not isinstance(reply, dict) or reply.get("status") != "success":
        msg = reply.get("message") or reply.get("error") or reply if isinstance(reply, dict) else reply
        raise RuntimeError(f"Rhino script failed: {str(msg)[:600]}")
    return reply


def _export(send: Sender, guids: list[str]) -> dict:
    out_dir = paths.user_data_dir() / "environment" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{uuid.uuid4().hex}.json"
    try:
        _execute(send, rhino.export_script(guids, str(out)), 240.0)
        if not out.is_file():
            raise RuntimeError("The Rhino export wrote no file")
        data = json.loads(out.read_text(encoding="utf-8"))
    finally:
        try:
            out.unlink()
        except OSError:
            pass
    if data.get("missing"):
        raise ValueError(f"These GUIDs are not in the Rhino document: {data['missing'][:5]}")
    if not data.get("objects"):
        raise ValueError("Nothing to analyse: the export produced no meshable geometry (surfaces, polysurfaces, "
                         "extrusions, meshes, SubD or blocks of them)")
    return data


def _north(data: dict | None, north_deg: float | None) -> float:
    if north_deg is not None:
        return float(north_deg)
    if data and data.get("rhino_north_deg") is not None:
        # Rhino's Sun panel: north measured counter-clockwise from +X (90 = +Y)
        return float(data["rhino_north_deg"]) - 90.0
    return 0.0


def _geometry(send: Sender, grid_guids, geometry_guids, materials, glazing, north_deg):
    """(export data, scene) for a Rhino study. geometry_guids empty = every visible object."""
    ids = list(dict.fromkeys(list(geometry_guids or []) + (list(grid_guids or []) if geometry_guids else [])))
    data = _export(send, ids)
    scene = scenemod.scene_from_export(data, materials, glazing or scenemod.DEFAULT_GLAZING)
    scene.north_deg = _north(data, north_deg)
    return data, scene


def _draw(send: Sender, run_id: str, metric: str = "", vmin=None, vmax=None, units_to_m: float | None = None) -> dict:
    result, arrays = studies.load_run(run_id)
    if "cells" not in arrays:
        return _err(f"Run {run_id} has no sensor grid to draw (thermal runs report per zone).")
    metrics = result.get("display_metrics") or []
    metric = metric or (metrics[0] if metrics else "")
    if metric not in arrays:
        return _err(f"Metric '{metric}' is not in run {run_id}; available: {metrics}")
    unit, lo, hi, ramp, title = studies.DISPLAY.get(metric, ("", None, None, "viridis", metric))
    vals = arrays[metric].astype(float) * (100.0 if metric in studies.PERCENT_METRICS else 1.0)
    lo, hi = render.nice_range(vals, vmin if vmin is not None else lo, vmax if vmax is not None else hi)
    colors = render.colorize(vals, lo, hi, ramp)
    quads, labels = render.legend_geometry(arrays["cells"], lo, hi, unit, title, ramp, normals=arrays.get("normals"))
    scale = units_to_m or float(result.get("inputs", {}).get("units_to_m") or 1.0)
    text = rhino.draw_file(arrays["cells"], colors, scale, labels, quads)
    f = paths.user_data_dir() / "environment" / "exports" / f"draw-{uuid.uuid4().hex}.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    try:
        reply = _execute(send, rhino.draw_script(str(f), f"{result.get('label', run_id)} {metric}", run_id), 120.0)
    finally:
        try:
            f.unlink()
        except OSError:
            pass
    return {"status": "success", "metric": metric, "range": [lo, hi], "unit": unit,
            "layer": f"{rhino.RESULT_ROOT}::{rhino.safe_label(result.get('label', run_id) + ' ' + metric)}",
            "guids": reply.get("guids") or reply.get("created_guids") or []}


# what a bad input can raise in the engine; answered as status=error, never as a crash
INPUT_ERRORS = (ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError, OverflowError, MemoryError,
                OSError, RuntimeError)


def _bridge_errors(exc: Exception) -> dict:
    if isinstance(exc, ConnectionRefusedError):
        return _err("Rhino is not reachable: open Rhino 8 with the almondbridge plugin, or use shoebox=... to analyse "
                    "a parametric room without Rhino.")
    return _err(f"{type(exc).__name__}: {exc}")


def register(mcp, send: Sender) -> dict:
    """Register the environmental tools on ``mcp``; returns them by name."""

    @mcp.tool(annotations=READ_ONLY)
    def climate_summary(epw_path: str, hdd_base_c: float = 18.0, cdd_base_c: float = 18.0,
                        strategy_thresholds: dict | None = None, include_psychrometric_bins: bool = False,
                        diurnal_chart: bool = False) -> dict:
        """Climate analysis of an EPW weather file (no Rhino needed): location and data quality (every
        repaired or missing value is counted), monthly temperatures / humidity / solar radiation /
        sunshine / wind, heating and cooling degree days, design temperatures, a 16-sector wind rose,
        outdoor adaptive-comfort hours, and indicative passive-strategy hours on the bioclimatic chart
        (comfort, natural ventilation, thermal mass + night flush, evaporative cooling, passive solar,
        dehumidification, active heating/cooling; thresholds returned and adjustable through
        strategy_thresholds, e.g. {"comfort": {"t_max": 27}}). include_psychrometric_bins adds the
        hourly temperature x humidity-ratio histogram for drawing a psychrometric chart.
        extreme_weeks gives the warmest and coldest 7-day periods computed from the data, the hottest /
        coldest day in each (by the hourly outdoor extreme), and the file's own typical/extreme periods
        with their real length (a file's "week" can cross the year end and run longer than 7 days).
        diurnal_chart=True also writes the monthly diurnal averages (dry-bulb, wet-bulb, global and diffuse
        horizontal, direct normal) as a chart (PNG + SVG) and a CSV, and returns their paths."""
        try:
            w = _weather(epw_path)
            out = {"status": "success", **studies.climate_report(w, hdd_base_c, cdd_base_c, strategy_thresholds,
                                                                 include_psychrometric_bins)}
            if diurnal_chart:
                ch = studies.climate_charts(w)
                out["diurnal"] = {"run_id": ch["run_id"], "files": ch["files"], "hours": ch["diurnal"]["hours"]}
            return out
        except (ValueError, OSError) as exc:
            return _err(str(exc))

    @mcp.tool(annotations=READ_ONLY)
    def sun_path(epw_path: str = "", latitude: float | None = None, longitude: float | None = None,
                 time_zone: float | None = None, month: int = 6, day: int = 21, north_deg: float = 0.0,
                 include_diagram: bool = False) -> dict:
        """Sun positions for a site (from an EPW file or latitude/longitude/time_zone, east and north
        positive, time zone in hours from UTC): sunrise, solar noon, sunset and day length for
        month/day, the hourly altitude/azimuth through that day, and with include_diagram the sun-path
        diagram arcs (21st of each month) and hourly analemmas. Azimuth is clockwise from true north;
        north_deg rotates the returned model-space sun vectors (angle of true north from +Y, CCW)."""
        try:
            if epw_path:
                loc = _weather(epw_path).location
                lat, lon, tz = loc.latitude, loc.longitude, loc.time_zone
            else:
                if latitude is None or longitude is None or time_zone is None:
                    return _err("Give epw_path, or latitude, longitude and time_zone.")
                lat, lon, tz = float(latitude), float(longitude), float(time_zone)
                if not (-90 <= lat <= 90 and -180 <= lon <= 180 and -12 <= tz <= 14):
                    return _err("latitude, longitude or time_zone out of range")
            solar.hour_index(month, day, 12)                 # validates month and day
            doy = int(epw.MONTH_START[month - 1] + day)
            t = np.arange(0, 24.01, 1.0)
            sp = solar.sun_position(lat, lon, tz, np.full_like(t, doy), t)
            vec = solar.direction_vector(sp["altitude"], sp["azimuth"], north_deg)
            hours = [{"hour": float(h), "altitude": round(float(a), 2), "azimuth": round(float(z), 2),
                      "vector": np.round(v, 4).tolist()} for h, a, z, v in zip(t, sp["altitude"], sp["azimuth"], vec) if a > -1]
            out = {"status": "success", "latitude": lat, "longitude": lon, "time_zone": tz, "date": f"{month}/{day}",
                   "events": solar.day_events(lat, lon, tz, doy), "hourly": hours,
                   "note": "Local standard time (no daylight saving)."}
            if include_diagram:
                out["diagram"] = solar.sun_path(lat, lon, tz, north_deg)
            return out
        except (ValueError, OSError) as exc:
            return _err(str(exc))

    @mcp.tool(annotations=WRITES)
    def shadow_study(epw_path: str, month: int = 3, day: int = 20, times: list[str] | None = None,
                     geometry_guids: list[str] | None = None, shoebox: dict | None = None, pixels: int = 560,
                     north_deg: float | None = None, rhino_view: str = "", rhino_display_mode: str = "Rendered") -> dict:
        """Sun and shadow study for a date (default 20 March at 09:00, 12:00 and 15:00). Times are LOCAL
        STANDARD TIME (the EPW time zone, no daylight saving): 12:00 is clock noon, not solar noon; each shot
        reports its solar time too. For each time Almond ray traces a shadow plan of the model seen from above
        (every visible Rhino object, or geometry_guids, or a shoebox), with roofs, the ground, the shadows,
        the sun's direction, north and a scale bar, and lays the times side by side on one sheet (PNG). The
        plans use the analysis scene itself, so they show exactly what the daylight and thermal studies see;
        closed room volumes are left out, glazing casts no shadow.
        rhino_view (e.g. "Perspective") also captures that Rhino viewport with the document sun set to each
        position, in rhino_display_mode; whether shadows appear there depends on that display mode's own
        shadow settings. The sun, ground plane and display mode are restored afterwards."""
        from almond_mcp.environment import shadows
        try:
            loc = _weather(epw_path).location
            run_id = studies.new_run_id("sun")
            d = studies.runs_dir() / run_id
            d.mkdir(parents=True, exist_ok=True)
            if shoebox:
                sc = scenemod.Shoebox(**shoebox).build()
                sc.north_deg = float(north_deg or 0.0)
            else:
                data, sc = _geometry(send, [], geometry_guids, None, None, north_deg)
                sc = shadows.without_room_volumes(sc, data)
            st = shadows.study(sc, loc, month, day, times, str(d / f"shadow-plans-{month:02d}{day:02d}.png"), int(pixels))
            rows, notes = st["shots"], st["notes"]
            files = {"shadow_plans": st["sheet"]}
            if rhino_view and not shoebox:
                shots = [(a, z, str(d / f"rhino-{month:02d}{day:02d}-{r['time'].replace(':', '')}.png")) for (a, z), r in zip(st["suns"], rows)]
                _execute(send, rhino.sun_views_script(shots, rhino_view, 1600, 1000, rhino_display_mode, True), 300.0)
                for (_, _, p), row in zip(shots, rows):
                    if Path(p).is_file():
                        row["rhino_png"] = p
                if not all("rhino_png" in r for r in rows):
                    notes.append(f"Some Rhino captures were not written: is display mode '{rhino_display_mode}' available?")
            result = {"status": "success", "run_id": run_id, "site": loc.label(), "date": st["date"],
                      "time_convention": st["time_convention"], "north_deg": st["north_deg"], "shots": rows, "files": files,
                      "plan": st["plan"], "notes": notes}
            studies.save_run(run_id, dict(result, study="shadow_study", label=f"shadows {month}/{day}"), None, {})
            return result
        except (ValueError, OSError) as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _bridge_errors(exc)

    @mcp.tool(annotations=WRITES)
    def analyze_daylight(epw_path: str = "", study: str = "annual", grid_guids: list[str] | None = None,
                         geometry_guids: list[str] | None = None, shoebox: dict | None = None,
                         quality: str = "medium", grid_spacing_m: float = 0.6, work_plane_m: float = 0.76,
                         edge_offset_m: float = 0.0, materials: dict | None = None, glazing: str = "",
                         shade_transmittance: float | None = None, dynamic_shading: bool = True,
                         aperture_grouping: str = "orientation", occupied_hours: list[float] | None = None,
                         weekdays_only: bool = False, da_threshold_lux: float = 300.0,
                         point_in_time: dict | None = None, views: list[dict] | None = None,
                         ground_reflectance: float = 0.2, north_deg: float | None = None,
                         probes: list[list[float]] | None = None, probe_distance_from_window_m: float | None = None,
                         show_in_rhino: bool = True, label: str = "", background: bool = False) -> dict:
        """Daylight simulation by daylight coefficients (Almond's own native engine).
        probes = points [x, y] (or [x, y, z]) in metres where every metric is reported from the nearest
        sensor (e.g. DA300 2 m from the window); with a shoebox, probe_distance_from_window_m puts one on the
        room's centreline at that distance from the facade.

        study: "annual" (climate-based, needs epw_path): sDA300/50% and ASE1000,250h per IES LM-83
          with dynamic shades (a group's shade closes when > 2 % of sensors get > 1000 lux of direct
          sun), DA, cDA, UDI bins, mean illuminance, EN 17037 daylight provision, and simplified DGP
          for optional view points; "daylight_factor" (CIE overcast, no EPW needed; with an EPW also
          the EN 17037 DF targets for the site); "point_in_time" (point_in_time={"month":6,"day":21,
          "hour":12,"sky":"epw"} - or sky "cie_overcast", "uniform", "cie_1".."cie_15" with
          "horizontal_illuminance" and optional "direct_normal_illuminance").

        Geometry, one of:
          - Rhino: grid_guids = floor surfaces to put sensors on (work_plane_m above them,
            grid_spacing_m apart); geometry_guids = objects that take part (default: every visible
            object; results layers are ignored). Materials come from layer / object / render-material
            names (glass/glazing/window -> glazing; floor, ceiling, wall, roof, ground, context,
            shading, furniture ...), user text almond:env_material, or the materials override
            ({"<layer path or GUID or library name>": "glazing_double_clear" | {"reflectance": 0.6}
            | {"transmittance": 0.5}}). Unmatched surfaces are classified by orientation.
            The result lists how every object was classified - check it.
          - shoebox (no Rhino): {"width":6,"depth":8,"height":3,"orientation":180,"wwr":0.4,
            "sill":0.8,"glazing":"glazing_double_lowe","overhang":0,"fins":0,
            "obstruction_height":0,"obstruction_distance":10}.

        quality: draft | medium | high. glazing picks the library glazing for generic glass;
        shade_transmittance sets every shade's diffuse transmittance (default 0.15).
        occupied_hours [start, end] (default [8, 18], every day, as LM-83). views:
        [{"position":[x,y,z],"direction":[dx,dy,dz]}] in metres for glare. north_deg: true north
        angle from +Y, counter-clockwise (default: Rhino's Sun panel north).
        Saves the run (see get_environment_run) with PNG plans, and draws the first metric in Rhino
        when show_in_rhino (Rhino studies only).
        background=True starts the study and returns a job_id at once - use it for annual studies on real models,
        which can take longer than the client waits; poll get_environment_run(job_id)."""
        if background:
            fn = getattr(analyze_daylight, "fn", analyze_daylight)
            args = _params(fn, locals())
            return _start_job("daylight", lambda: fn(**args))
        try:
            if study not in ("annual", "daylight_factor", "point_in_time"):
                return _err("study must be 'annual', 'daylight_factor' or 'point_in_time'.")
            sky = (point_in_time or {}).get("sky", "epw")
            needs_site = study == "annual" or (study == "point_in_time" and sky not in studies.SUNLESS_SKIES)
            weather = _weather(epw_path) if (epw_path or needs_site) else None
            occ = occupied_hours or [8.0, 18.0]
            if len(occ) != 2:
                return _err("occupied_hours must be [start, end]")
            if not 0.1 <= grid_spacing_m <= 20:
                return _err("grid_spacing_m must be between 0.1 and 20")
            inputs = {"epw_path": epw_path, "grid_spacing_m": grid_spacing_m, "work_plane_m": work_plane_m,
                      "materials": materials, "glazing": glazing, "shade_transmittance": shade_transmittance}
            if shoebox:
                box = studies.shoebox_from_spec(shoebox)
                sc = box.build({k: scenemod.material_from_spec(k, v) for k, v in (materials or {}).items()})
                sc.north_deg = float(north_deg or 0.0)
                grid = box.floor_grid(sc, grid_spacing_m, work_plane_m, edge_offset_m)
                inputs.update(shoebox=box.__dict__, units_to_m=1.0)
                show_in_rhino = False
                if probe_distance_from_window_m is not None:
                    probes = list(probes or []) + [box.to_scene([box.width / 2, float(probe_distance_from_window_m),
                                                                 work_plane_m])[0].tolist()]
            else:
                if not grid_guids:
                    return _err("Give grid_guids (the floor surfaces to analyse), or a shoebox to study without Rhino.")
                data, sc = _geometry(send, grid_guids, geometry_guids, materials, glazing, north_deg)
                grid = studies.grid_from_export(data, sc, grid_guids, grid_spacing_m, work_plane_m, edge_offset_m)
                inputs.update(grid_guids=grid_guids, geometry_guids=geometry_guids or "all visible",
                              units_to_m=data.get("units_to_m"), document_units=data.get("units"))
            studies.apply_shade_transmittance(sc, shade_transmittance)
            grid, dropped = studies.drop_enclosed_sensors(sc, grid)
            res = studies.run_daylight(sc, grid, weather, study, quality, label, (float(occ[0]), float(occ[1])),
                                       weekdays_only, dynamic_shading, aperture_grouping, da_threshold_lux,
                                       point_time=point_in_time, views=views, ground_reflectance=ground_reflectance,
                                       inputs=inputs, dropped=dropped, probes=probes)
            res["status"] = "success"
            if show_in_rhino:
                try:
                    res["rhino"] = _draw(send, res["run_id"], "", units_to_m=inputs.get("units_to_m"))
                except Exception as exc:  # noqa: BLE001 - drawing must not lose the analysis
                    res["rhino"] = _err(f"Results saved, but drawing them failed: {exc}")
            res["next_steps"] = ("show_environment_result(run_id, metric=...) to draw another metric; "
                                 "list_environment_runs to compare options.")
            return res
        except (ValueError, OSError, RuntimeError) as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=WRITES)
    def compare_daylight_cases(epw_path: str, cases: list[dict], base: dict | None = None, quality: str = "medium",
                               grid_spacing_m: float = 0.6, work_plane_m: float = 0.76, edge_offset_m: float = 0.5,
                               probe_distance_from_window_m: float = 2.0, view_out: bool = True,
                               view_height_m: float = 1.2, label: str = "", background: bool = False) -> dict:
        """Daylight of shoebox design cases side by side. base = {"shoebox": {...}, "materials": {...},
        "glazing": "...", "shade_transmittance": 0.15}; each case = {"id": "ID3", "shoebox": {...overrides},
        "materials": {...}, "glazing": ..., "shade_transmittance": ..., "static_shade_transmittance": 0.14}
        (shade_transmittance: the dynamic shade that closes against direct sun; static_shade_transmittance: a blind
        kept down all year, multiplying the glazing's transmittance). Per case: mean daylight factor (CIE
        overcast), annual sDA300/50 %, ASE, DA300 at probe_distance_from_window_m on the centreline, EN 17037
        daylight provision (area meeting the minimum-level target 300 lx and minimum 100 lx, and the level met),
        and with view_out the EN 17037 view-out shares. Writes a bar chart per metric (PNG + SVG) and a CSV
        table in the run folder. background=True returns a job_id (poll get_environment_run)."""
        if background:
            fn = getattr(compare_daylight_cases, "fn", compare_daylight_cases)
            args = _params(fn, locals())
            return _start_job("daylight-cases", lambda: fn(**args))
        from almond_mcp.environment import cases as cs, charts, en17037 as en
        try:
            weather = _weather(epw_path)
            base = base or {}
            if not cases or len(cases) > 12:
                return _err("Give 1..12 cases")
            run_id = studies.new_run_id("dlcases")
            d = studies.runs_dir() / run_id
            d.mkdir(parents=True, exist_ok=True)
            rows = []
            for k, case in enumerate(cases):
                bad = sorted(set(case) - {"id", "label", "shoebox", "materials", "glazing", "shade_transmittance",
                                          "static_shade_transmittance"})
                if bad:
                    return _err(f"case {k + 1}: unknown key(s) {bad}")
                spec = {**(base.get("shoebox") or {}), **(case.get("shoebox") or {})}
                if not spec:
                    return _err("Every case needs a shoebox (in base or in the case)")
                mats = {**(base.get("materials") or {}), **(case.get("materials") or {})}
                glazing = case.get("glazing", base.get("glazing"))
                if glazing:
                    spec["glazing"] = glazing
                static = case.get("static_shade_transmittance", base.get("static_shade_transmittance"))
                if static is not None:
                    if not 0.0 < float(static) <= 1.0:
                        return _err(f"case {k + 1}: static_shade_transmittance must be in (0, 1]")
                    gname = spec.get("glazing") or scenemod.DEFAULT_GLAZING
                    tau = scenemod.material_from_spec(gname, mats.get(gname)).transmittance
                    mats[gname] = {**(mats.get(gname) if isinstance(mats.get(gname), dict) else {}),
                                   "transmittance": round(float(tau) * float(static), 4)}
                shade = case.get("shade_transmittance", base.get("shade_transmittance"))
                cid = str(case.get("id") or f"case {k + 1}")
                row = {"id": cid, "label": str(case.get("label") or cid)}
                for study in ("daylight_factor", "annual"):
                    box = studies.shoebox_from_spec(spec)
                    sc = box.build({n: scenemod.material_from_spec(n, v) for n, v in mats.items()})
                    grid = box.floor_grid(sc, grid_spacing_m, work_plane_m, edge_offset_m)
                    studies.apply_shade_transmittance(sc, shade)
                    probe = box.to_scene([box.width / 2, probe_distance_from_window_m, work_plane_m])[0].tolist()
                    res = studies.run_daylight(sc, grid, weather, study, quality, f"{cid} {study}", probes=[probe],
                                               inputs={"shoebox": box.__dict__, "case": cid})
                    m = res["metrics"]
                    if study == "daylight_factor":
                        row.update(mean_df_pct=m["average_df_pct"], median_df_pct=m["median_df_pct"], df_run=res["run_id"])
                    else:
                        p = res["probes"][0]
                        prov = m.get("en17037", {})
                        row.update(sda_pct=m["sda_pct"], ase_pct=m["ase_pct"], da_at_probe_pct=p.get("da"),
                                   en17037_area_target_300lx_pct=prov.get("minimum", {}).get("area_meeting_target_pct"),
                                   en17037_area_minimum_100lx_pct=prov.get("minimum", {}).get("area_meeting_minimum_pct"),
                                   en17037_level=prov.get("level"), annual_run=res["run_id"])
                if view_out:
                    box = studies.shoebox_from_spec(spec)
                    sc = box.build({n: scenemod.material_from_spec(n, v) for n, v in mats.items()})
                    vg = box.floor_grid(sc, grid_spacing_m, view_height_m, edge_offset_m)
                    vs = en.view_summary(en.view_out(sc, vg.points), vg.cell_area)
                    row.update(view_out_area_pct=vs["area_at_least_pct"], view_out_level=vs["level_of_most_points"])
                rows.append(row)
            ids = [r["id"] for r in rows]
            files = {}
            for key, title, unit, refs in (
                    ("mean_df_pct", "Mean daylight factor", "DF %", [(2.0, "2 %", charts.GREEN)]),
                    ("sda_pct", "Spatial daylight autonomy sDA300/50%", "% of floor", [(55.0, "55 %", charts.GREEN)]),
                    ("da_at_probe_pct", f"Daylight autonomy DA300 at {probe_distance_from_window_m:g} m from the window", "% of hours", []),
                    ("en17037_area_target_300lx_pct", "EN 17037 minimum level: area reaching 300 lx", "% of floor", [(50.0, "50 %", charts.GREEN)]),
                    ("en17037_area_minimum_100lx_pct", "EN 17037 minimum level: area reaching 100 lx", "% of floor", [(95.0, "95 %", charts.GREEN)])):
                c = charts.bar_chart(ids, [r.get(key) for r in rows], title, unit, width=560, height=300, refs=refs)
                files[key] = charts.save(c, d / f"bars-{key.replace('_pct', '')}")
            keys = ["id", "label", "mean_df_pct", "median_df_pct", "sda_pct", "ase_pct", "da_at_probe_pct",
                    "en17037_area_target_300lx_pct", "en17037_area_minimum_100lx_pct", "en17037_level", "view_out_level"]
            lines = [",".join(keys)] + [",".join(str(r.get(k, "")) for k in keys) for r in rows]
            (d / "daylight-cases.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
            files["table_csv"] = str(d / "daylight-cases.csv")
            result = {"status": "success", "run_id": run_id, "study": "daylight_cases", "label": label or "daylight cases",
                      "weather": weather.location.label(), "cases": rows, "files": files,
                      "settings": {"quality": quality, "grid_spacing_m": grid_spacing_m, "work_plane_m": work_plane_m,
                                   "edge_offset_m": edge_offset_m, "probe_distance_from_window_m": probe_distance_from_window_m,
                                   "view_height_m": view_height_m},
                      "notes": ["Reference lines on the charts are common targets (DF 2 %, sDA 55 %, EN 17037 minimum level "
                                "50 % / 95 % of the area), drawn for orientation only."]}
            studies.save_run(run_id, result, None, {})
            return result
        except (ValueError, OSError, RuntimeError, TypeError) as exc:
            return _bridge_errors(exc)

    def _en_scene(grid_guids, geometry_guids, shoebox, north_deg, height, spacing, edge, need_grid=True):
        """(scene, grid or None, inputs) for the EN 17037 tools: a shoebox, or Rhino geometry."""
        from almond_mcp.environment import shadows
        if shoebox:
            box = studies.shoebox_from_spec(shoebox)
            sc = box.build()
            sc.north_deg = float(north_deg or 0.0)
            grid = box.floor_grid(sc, spacing, height, edge) if need_grid else None
            return sc, grid, {"shoebox": box.__dict__, "units_to_m": 1.0}
        if need_grid and not grid_guids:
            raise ValueError("Give grid_guids (the floor surfaces of the rooms to assess), or a shoebox.")
        data, sc = _geometry(send, list(grid_guids or []), geometry_guids, None, None, north_deg)
        sc = shadows.without_room_volumes(sc, data)
        grid = studies.grid_from_export(data, sc, grid_guids, spacing, height, edge) if need_grid else None
        return sc, grid, {"grid_guids": grid_guids, "units_to_m": data.get("units_to_m")}

    @mcp.tool(annotations=WRITES)
    def en17037_view_out(grid_guids: list[str] | None = None, geometry_guids: list[str] | None = None,
                         shoebox: dict | None = None, view_height_m: float = 1.2, grid_spacing_m: float = 0.6,
                         edge_offset_m: float = 0.5, north_deg: float | None = None, show_in_rhino: bool = True,
                         label: str = "") -> dict:
        """EN 17037 view out, ray traced at viewpoints on a grid view_height_m above the floors (grid_guids in
        Rhino, or a shoebox): horizontal sight angle through the windows, outside distance to the first
        obstruction, and the layers seen (sky, landscape, ground). Each viewpoint gets the lowest of the three
        levels (none / minimum / medium / high; thresholds 14 / 28 / 54 deg, 6 / 20 / 50 m, landscape / + one /
        all layers, per EN 17037 Annex A). Returns the share of the floor reaching each level, a plan PNG per
        metric, and draws the level map in Rhino. Indicative design check by Almond's own implementation;
        not a certification."""
        from almond_mcp.environment import en17037 as en
        try:
            if not 0.2 <= grid_spacing_m <= 5:
                return _err("grid_spacing_m must be 0.2..5")
            sc, grid, inputs = _en_scene(grid_guids, geometry_guids, shoebox, north_deg, view_height_m, grid_spacing_m, edge_offset_m)
            if shoebox:
                show_in_rhino = False
            t0 = time.time()
            v = en.view_out(sc, grid.points)
            run_id = studies.new_run_id("viewout")
            arrays = {"view_level": v["level"].astype(float), "sight_angle_deg": v["sight_angle_deg"],
                      "outside_distance_m": np.minimum(v["outside_distance_m"], 999.0)}
            summ = en.view_summary(v, grid.cell_area)
            result = {"run_id": run_id, "study": "en17037_view_out", "label": label or "view out",
                      "metrics": summ, "inputs": {**inputs, "view_height_m": view_height_m, "grid_spacing_m": grid_spacing_m,
                                                  "edge_offset_m": edge_offset_m},
                      "grid": {"sensors": grid.n, "area_m2": round(grid.area, 2), "spacing_m": grid.spacing},
                      "display_metrics": list(arrays), "timing_s": round(time.time() - t0, 2),
                      "headline": "view out: " + ", ".join(f"{k} on {p} %" for k, p in summ["area_at_least_pct"].items()),
                      "notes": ["Indicative, by Almond's implementation of the EN 17037 Annex A view-out principles; "
                                "thresholds quoted by value. Glazing is treated as clear; frames and mullions modelled as "
                                "geometry reduce the sight angle."]}
            run_dir = studies.save_run(run_id, result, grid, arrays)
            result["images"] = studies._images(run_dir, grid, arrays, list(arrays), result["label"])
            result["run_dir"] = str(run_dir)
            result["status"] = "success"
            if show_in_rhino:
                try:
                    result["rhino"] = _draw(send, run_id, "view_level", units_to_m=inputs.get("units_to_m"))
                except Exception as exc:  # noqa: BLE001
                    result["rhino"] = _err(f"Results saved, but drawing them failed: {exc}")
            return result
        except (ValueError, OSError, RuntimeError) as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=WRITES)
    def en17037_sunlight(epw_path: str, month: int = 3, day: int = 21, date_range: list[list[int]] | None = None,
                         geometry_guids: list[str] | None = None, shoebox: dict | None = None,
                         min_altitude_deg: float = 10.0, window_guids: list[str] | None = None,
                         north_deg: float | None = None, label: str = "") -> dict:
        """EN 17037 exposure to sunlight: hours of direct sun on a reference point at the centre of each window
        (on its inside face) on month/day, with the sun above min_altitude_deg and not blocked by the building
        or its surroundings (every visible Rhino object, or geometry_guids, or a shoebox). Levels: >= 1.5 h
        minimum, 3 h medium, 4 h high. The standard uses a day between 1 February and 21 March and a minimum
        sun altitude that depends on the location: set min_altitude_deg to the value that applies (Almond's
        default 10). date_range=[[2, 1], [3, 21]] also scans every day in the range, reports each window's
        hours per day and the best day, and writes a chart. Windows: window_guids, or else the glazing that
        carries a window construction (assign_construction) when the model has any, or else every glazing
        object (check the list: glass objects inside the building would count too).
        Indicative design check, not a certification."""
        from almond_mcp.environment import en17037 as en
        try:
            loc = _weather(epw_path).location
            sc, _, inputs = _en_scene([], geometry_guids, shoebox, north_deg, 0, 1, 0, need_grid=False)
            run_id = studies.new_run_id("sunlight")
            d = studies.runs_dir() / run_id
            d.mkdir(parents=True, exist_ok=True)
            st = en.sunlight_study(sc, loc, month, day, d, date_range, min_altitude_deg, window_guids)
            st.pop("chart_svg", None)
            result = {"status": "success", "run_id": run_id, "study": "en17037_sunlight", "label": label or "sunlight",
                      **st, "inputs": inputs}
            studies.save_run(run_id, result, None, {})
            return result
        except (ValueError, OSError, RuntimeError) as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=WRITES)
    def analyze_solar_radiation(epw_path: str, grid_guids: list[str] | None = None,
                                geometry_guids: list[str] | None = None, shoebox: dict | None = None,
                                months: list[int] | None = None, hours: list[float] | None = None,
                                grid_spacing_m: float = 1.0, offset_m: float = 0.05, bounces: int = 1,
                                quality: str = "draft", materials: dict | None = None,
                                ground_reflectance: float = 0.2, north_deg: float | None = None,
                                show_in_rhino: bool = True, label: str = "", background: bool = False) -> dict:
        """Incident solar irradiation (kWh/m2) and direct-sun hours on surfaces - roofs, facades,
        ground, a site - over the year or a period (months e.g. [6,7,8]; hours [start, end] local
        standard time). Perez cumulative sky by daylight coefficients plus the sun traced hourly, with
        every object in the model shading and (bounces >= 1, the default) reflecting - modelled ground
        and neighbours included; bounces=0 counts direct sky and sun only. Sensors sit offset_m off
        each surface, on the side that faces open sky. Geometry: grid_guids (+ geometry_guids,
        default all visible) in Rhino, or shoebox={...} (sensors on its glazed facade, no Rhino).
        Returns per-month means, totals and PNG maps; draws in Rhino when show_in_rhino.
        background=True starts the study and returns a job_id at once - use it for annual studies on real models,
        which can take longer than the client waits; poll get_environment_run(job_id)."""
        if background:
            fn = getattr(analyze_solar_radiation, "fn", analyze_solar_radiation)
            args = _params(fn, locals())
            return _start_job("radiation", lambda: fn(**args))
        try:
            weather = _weather(epw_path)
            inputs = {"epw_path": epw_path, "grid_spacing_m": grid_spacing_m, "offset_m": offset_m, "months": months, "hours": hours}
            if shoebox:
                box = studies.shoebox_from_spec(shoebox)
                sc = box.build()
                sc.north_deg = float(north_deg or 0.0)
                sel = box.part_mask(sc, "facade") | box.part_mask(sc, "window")
                g0 = scenemod.grid_from_triangles(sc.vertices, sc.triangles[sel], grid_spacing_m, 0.0, 0.0, face_up=False)
                inputs.update(shoebox=box.__dict__, units_to_m=1.0)
                show_in_rhino = False
            else:
                if not grid_guids:
                    return _err("Give grid_guids (the surfaces to analyse), or a shoebox.")
                data, sc = _geometry(send, grid_guids, geometry_guids, materials, "", north_deg)
                g0 = studies.grid_from_export(data, sc, grid_guids, grid_spacing_m, 0.0, 0.0, face_up=False)
                inputs.update(grid_guids=grid_guids, units_to_m=data.get("units_to_m"), document_units=data.get("units"))
            grid, dropped = studies.orient_outward(g0, sc, offset_m)
            res = studies.run_radiation(sc, grid, weather, quality, months, hours, bounces, label, ground_reflectance, inputs,
                                        dropped=dropped)
            res["status"] = "success"
            if show_in_rhino:
                try:
                    res["rhino"] = _draw(send, res["run_id"], "kwh_m2", units_to_m=inputs.get("units_to_m"))
                except Exception as exc:  # noqa: BLE001
                    res["rhino"] = _err(f"Results saved, but drawing them failed: {exc}")
            return res
        except (ValueError, OSError, RuntimeError) as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=WRITES)
    def analyze_thermal(epw_path: str, zone_guids: list[str] | None = None, geometry_guids: list[str] | None = None,
                        shoebox: dict | None = None, construction: str = "typical", u_values: dict | None = None,
                        thermal_mass: str = "", free_running: bool = False, heating_setpoint_c: float | None = 20.0,
                        cooling_setpoint_c: float | None = 26.0, schedule: str = "office",
                        infiltration_ach: float = 0.3, ventilation_ach: float | None = None,
                        ventilation_l_s_m2: float | None = None,
                        natural_ventilation_ach: float = 0.0, natural_ventilation_above_c: float = 24.0,
                        occupancy_w_m2: float = 7.5, equipment_w_m2: float = 10.0, lighting_w_m2: float = 8.0,
                        window_g: float | None = None, window_u: float | None = None,
                        shading_g_factor: float = 1.0, shading_min_outdoor_c: float | None = None,
                        clothing_summer: float = 0.5, clothing_winter: float = 1.0,
                        metabolic_rate: float = 1.2, air_speed: float = 0.1, materials: dict | None = None,
                        heating_setback_c: float | None = None, cooling_setback_c: float | None = None,
                        people_per_m2: float | None = None, ventilation_l_s_person: float | None = None,
                        heating_months: list[int] | None = None, cooling_months: list[int] | None = None,
                        ventilation_months: list[int] | None = None, natural_ventilation_months: list[int] | None = None,
                        natural_ventilation_min_outdoor_c: float = 12.0, shading_on_above_w_m2: float = 300.0,
                        custom_schedule: dict | None = None, comfort_months: list[int] | None = None,
                        export_csv: bool = False,
                        north_deg: float | None = None, label: str = "", background: bool = False) -> dict:
        """Hourly thermal simulation of zones for a year (ISO 13790 5R1C, one node set per zone) with
        solar gains ray traced on the real geometry: heating/cooling energy and peaks (kWh/m2, W/m2),
        operative temperatures, and comfort - adaptive ASHRAE 55 and EN 16798-1 (Cat II) hours, CIBSE
        TM52 overheating criteria, PMV/PPD. free_running=True removes both set-points (use with
        natural_ventilation_ach to test passive design).

        Zones: zone_guids = closed polysurfaces / extrusions / closed meshes in Rhino, one per zone
        (glazing objects lying on a zone face become its windows; faces shared between listed zones are
        adiabatic; the lowest floor is ground-coupled to the EPW ground temperature); geometry_guids =
        context that shades (default all visible). Or shoebox={...} for a room with one exposed facade.
        construction: insulated | typical | uninsulated_masonry | lightweight_tropical; u_values
        overrides per kind ({"wall":0.3,"roof":0.2,"ground_floor":0.3,"window":1.4}); thermal_mass:
        very_light | light | medium | heavy | very_heavy. schedule: office | school | residential | always.
        shading_g_factor < 1 lowers a window's g when its irradiance passes 300 W/m2 (movable shading);
        shading_min_outdoor_c keeps the shading up on days colder than that (summer mode, e.g. 12).
        Fresh air when occupied: ventilation_l_s_m2 per floor area (default by schedule, EN 16798-1
        Cat II: office 1.4, school 4.0, residential 0.42) or ventilation_ach; infiltration_ach always.
        Brief-style inputs: people_per_m2 (their sensible heat at metabolic_rate replaces occupancy_w_m2;
        60 % of the metabolic heat, an Almond assumption) and ventilation_l_s_person (added to
        ventilation_l_s_m2, e.g. 5 l/s per person + 1 l/s m2); heating_setback_c / cooling_setback_c are the
        set-points outside occupied hours (e.g. 21 occupied / 18 setback; default: off when unoccupied);
        heating_months / cooling_months / ventilation_months / natural_ventilation_months limit each system to
        a season (e.g. heating [11,12,1,2,3,4], natural ventilation [5,...,10]); natural_ventilation_above_c and
        natural_ventilation_min_outdoor_c set when windows open; shading_on_above_w_m2 is the irradiance on the
        window that lowers the shade (e.g. 150). custom_schedule = your own day profiles,
        {"occupancy": {"weekday": [24 fractions], "weekend": [24]}, "lighting": {...}, "equipment": {...}}.
        comfort_months = the season for the adaptive EN 16798-1 hour counts (adaptive_en16798_hours: too warm /
        too cool / comfortable occupied hours per category I-III). Every zone reports its hourly energy balance
        as annual gains / losses per term (energy_balance_kwh_m2) and lighting / equipment energy;
        export_csv=True also writes each zone's hourly results and balance to a CSV in the run folder.
        background=True starts the study and returns a job_id at once - use it for annual studies on real models,
        which can take longer than the client waits; poll get_environment_run(job_id)."""
        if background:
            fn = getattr(analyze_thermal, "fn", analyze_thermal)
            args = _params(fn, locals())
            return _start_job("thermal", lambda: fn(**args))
        try:
            weather = _weather(epw_path)
            st = thermal.Settings(construction=construction, u_values=u_values or {}, mass=thermal_mass or None,
                                  infiltration_ach=infiltration_ach, ventilation_ach=ventilation_ach,
                                  ventilation_l_s_m2=ventilation_l_s_m2,
                                  heating_setpoint=None if free_running else heating_setpoint_c,
                                  cooling_setpoint=None if free_running else cooling_setpoint_c,
                                  schedule=schedule, occupancy_w_m2=occupancy_w_m2, equipment_w_m2=equipment_w_m2,
                                  lighting_w_m2=lighting_w_m2, natural_ventilation_ach=natural_ventilation_ach,
                                  natural_ventilation_on_above=natural_ventilation_above_c,
                                  shading_g_factor=shading_g_factor, shading_min_outdoor_c=shading_min_outdoor_c,
                                  window_u=window_u, window_g=window_g,
                                  clothing_summer=clothing_summer, clothing_winter=clothing_winter,
                                  metabolic_rate=metabolic_rate, air_speed=air_speed,
                                  heating_setback=heating_setback_c, cooling_setback=cooling_setback_c,
                                  people_per_m2=people_per_m2, ventilation_l_s_person=ventilation_l_s_person,
                                  heating_months=heating_months, cooling_months=cooling_months,
                                  ventilation_months=ventilation_months, natural_ventilation_months=natural_ventilation_months,
                                  natural_ventilation_min_outdoor=natural_ventilation_min_outdoor_c,
                                  shading_on_above_w_m2=shading_on_above_w_m2, custom_schedule=custom_schedule,
                                  comfort_months=comfort_months)
            st.validate()
            inputs = {"epw_path": epw_path, "export_csv": export_csv}
            if shoebox:
                box = studies.shoebox_from_spec(shoebox)
                sc = box.build()
                sc.north_deg = float(north_deg or 0.0)
                zones = [thermal.zone_from_shoebox(box, sc, scenemod.LIBRARY[box.glazing])]
                inputs["shoebox"] = box.__dict__
            else:
                if not zone_guids:
                    return _err("Give zone_guids (closed volumes, one per zone), or a shoebox.")
                ids = list(dict.fromkeys(list(geometry_guids or []) + list(zone_guids))) if geometry_guids else []
                data = _export(send, ids)
                sc = scenemod.scene_from_export(data, materials)
                sc.north_deg = _north(data, north_deg)
                zones = studies.zones_from_export(data, sc, zone_guids)
                inputs.update(zone_guids=zone_guids, units_to_m=data.get("units_to_m"))
            res = studies.run_thermal(zones, sc, weather, st, label, inputs)
            res["status"] = "success"
            return res
        except (ValueError, OSError, RuntimeError) as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=WRITES)
    def compare_thermal_cases(epw_path: str, cases: list[dict], base: dict | None = None,
                              zone_guids: list[str] | None = None, geometry_guids: list[str] | None = None,
                              balance_case: str = "", label: str = "") -> dict:
        """Run design cases side by side (one zone each) on the same weather year and compare them.
        base = {"shoebox": {...}, "settings": {...}}; each case = {"id": "ID2", "settings": {...overrides},
        "shoebox": {...overrides}} merged over the base. settings use the thermal setting names
        (heating_setpoint, cooling_setpoint, heating_setback, people_per_m2, ventilation_l_s_person,
        ventilation_l_s_m2, equipment_w_m2, lighting_w_m2, u_values, window_u, window_g, shading_g_factor,
        shading_on_above_w_m2, infiltration_ach, heat_recovery, schedule, custom_schedule, comfort_months,
        ...; "free_running": true clears both set-points); shoebox uses its fields (width, depth, height,
        orientation, wwr, sill, overhang, fins, obstruction_height, obstruction_distance, glazing). Without a
        shoebox, zone_guids[0] is the zone in Rhino and cases vary settings only.
        Returns a table (heating / cooling / lighting kWh/m2, peaks, operative min / max, hours > 26 degC,
        adaptive Cat II too-warm / too-cool hours in comfort_months, TM52) and writes, in the run folder: an
        hourly CSV per case (temperatures and every energy-balance term, named columns), one CSV with each
        case's operative temperature next to the outdoor air, charts of operative temperature through the
        warmest and coldest week (from the weather data), and balance_case's (default the first) hourly energy
        balance on the hottest and coldest day, as charts and CSVs in kWh/m2."""
        from almond_mcp.environment import cases as cs
        try:
            weather = _weather(epw_path)
            base = base or {}
            rhino_zone = None
            if not (base.get("shoebox") or all(c.get("shoebox") for c in cases or [])):
                if not zone_guids:
                    return _err("Give base={'shoebox': {...}} (or a shoebox in every case), or zone_guids for a Rhino zone.")
                ids = list(dict.fromkeys(list(geometry_guids or []) + list(zone_guids))) if geometry_guids else []
                rhino_zone = _export(send, ids)

            def make_zones(m):
                if m["shoebox"]:
                    box = studies.shoebox_from_spec(m["shoebox"])
                    sc = box.build()
                    return [thermal.zone_from_shoebox(box, sc, scenemod.LIBRARY[box.glazing])], sc
                sc = scenemod.scene_from_export(rhino_zone)
                sc.north_deg = _north(rhino_zone, None)
                return studies.zones_from_export(rhino_zone, sc, zone_guids[:1]), sc

            run_id = studies.new_run_id("cases")
            out = cs.run_thermal_cases(weather, base, cases, make_zones, studies.runs_dir() / run_id, balance_case)
            result = {"status": "success", "run_id": run_id, "study": "thermal_cases", "label": label or "thermal cases",
                      "weather": weather.location.label(), **out}
            studies.save_run(run_id, result, None, {})
            return result
        except (ValueError, OSError, RuntimeError, TypeError) as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=READ_ONLY)
    def thermal_comfort(air_temperature_c: float, mean_radiant_temperature_c: float | None = None,
                        relative_humidity: float = 50.0, air_speed: float = 0.1, metabolic_rate: float = 1.2,
                        clothing: float = 0.5, outdoor_running_mean_c: float | None = None) -> dict:
        """Comfort calculator for one condition: PMV/PPD (ISO 7730, with its validity range), operative
        temperature, psychrometrics (humidity ratio, dew point, wet bulb, enthalpy), and - when
        outdoor_running_mean_c (the prevailing / running mean outdoor temperature) is given - the
        adaptive ASHRAE 55 (80 / 90 %, with the elevated-air-speed allowance) and EN 16798-1
        category I-III limits."""
        try:
            tr = air_temperature_c if mean_radiant_temperature_c is None else mean_radiant_temperature_c
            if not (-50 < air_temperature_c < 60 and -50 < tr < 80 and 0 <= relative_humidity <= 100):
                return _err("Inputs out of range (air -50..60 degC, radiant -50..80 degC, RH 0..100 %).")
            if air_speed < 0 or not 0.5 <= metabolic_rate <= 6 or not 0 <= clothing <= 4:
                return _err("air_speed >= 0, metabolic_rate 0.5..6 met, clothing 0..4 clo.")
            p = comfort.pmv_ppd(air_temperature_c, tr, air_speed, relative_humidity, metabolic_rate, clothing)
            t_op = float(comfort.operative_temperature(air_temperature_c, tr, air_speed))
            w = float(comfort.humidity_ratio(air_temperature_c, relative_humidity))
            out = {"status": "success",
                   "pmv": round(float(p["pmv"]), 2), "ppd_pct": round(float(p["ppd"]), 1),
                   "pmv_category_iso7730": ("A (|PMV| < 0.2)" if abs(float(p["pmv"])) < 0.2 else
                                            "B (|PMV| < 0.5)" if abs(float(p["pmv"])) < 0.5 else
                                            "C (|PMV| < 0.7)" if abs(float(p["pmv"])) < 0.7 else "outside C"),
                   "within_iso7730_range": bool(p["within_iso7730_range"]),
                   "operative_temperature_c": round(t_op, 2),
                   "psychrometrics": {"humidity_ratio_g_kg": round(w * 1000, 2),
                                      "dew_point_c": round(float(comfort.dew_point(air_temperature_c, max(relative_humidity, 0.1))), 2),
                                      "wet_bulb_c": round(float(comfort.wet_bulb(air_temperature_c, max(relative_humidity, 0.1))), 2),
                                      "enthalpy_kj_kg": round(float(comfort.enthalpy(air_temperature_c, w)), 2)}}
            if outdoor_running_mean_c is not None:
                a = comfort.adaptive_ashrae55(np.full(24, t_op), np.array([outdoor_running_mean_c]), air_speed)
                out["adaptive_ashrae55"] = {"neutral_c": round(float(a["neutral"][0]), 2),
                                            "range_80_c": [round(float(a["lower_80"][0]), 2), round(float(a["upper_80"][0]), 2)],
                                            "range_90_c": [round(float(a["lower_90"][0]), 2), round(float(a["upper_90"][0]), 2)],
                                            "comfortable_80": bool(a["comfortable_80"][0]), "comfortable_90": bool(a["comfortable_90"][0]),
                                            "applicable": bool(a["applicable"][0]), "air_speed_bonus_k": a["air_speed_bonus_k"]}
                out["adaptive_en16798"] = {}
                for cat in ("I", "II", "III"):
                    e = comfort.adaptive_en16798(np.full(24, t_op), np.array([outdoor_running_mean_c]), cat)
                    out["adaptive_en16798"][cat] = {"range_c": [round(float(e["lower"][0]), 2), round(float(e["upper"][0]), 2)],
                                                    "comfortable": bool(e["comfortable"][0])}
            return out
        except (ValueError, TypeError) as exc:
            return _err(str(exc))

    @mcp.tool(annotations=READ_ONLY)
    def comfort_setpoints(metabolic_rate: float = 1.2, clothing_heating: float = 1.0, clothing_cooling: float = 0.5,
                          relative_humidity: float = 50.0, air_speed: float = 0.1, category: str = "II",
                          radiant_minus_air_k: float = 0.0) -> dict:
        """Heating and cooling set-points from PMV for an activity and clothing: the lowest operative
        temperature that keeps PMV at or above the EN 16798-1 / ISO 7730 category's lower limit with the
        winter clothing (heating set-point), and the highest that keeps PMV at or below the upper limit with
        the summer clothing (cooling set-point). Category I +/-0.2, II +/-0.5, III +/-0.7, IV +/-1.0.
        Typical inputs: seated office 1.2 met, bedroom (sleeping) 0.8 met; clothing 1.0 clo winter, 0.5
        summer; radiant_minus_air_k < 0 for cold windows. Use the result as heating_setpoint_c /
        cooling_setpoint_c, and state the assumptions with it."""
        try:
            if not (0.7 <= metabolic_rate <= 4 and 0 <= clothing_heating <= 2 and 0 <= clothing_cooling <= 2
                    and 0 <= relative_humidity <= 100 and 0 <= air_speed <= 2 and -10 <= radiant_minus_air_k <= 10):
                return _err("Inputs out of range: met 0.7..4, clo 0..2, RH 0..100 %, air speed 0..2 m/s, radiant offset -10..10 K.")
            return {"status": "success", **comfort.pmv_setpoints(metabolic_rate, clothing_heating, clothing_cooling,
                                                                  relative_humidity, air_speed, category, radiant_minus_air_k)}
        except ValueError as exc:
            return _err(str(exc))

    @mcp.tool(annotations=WRITES)
    def show_environment_result(run_id: str = "", metric: str = "", clear: bool = False,
                                min_value: float | None = None, max_value: float | None = None) -> dict:
        """Draw a saved daylight or radiation run in Rhino as a vertex-coloured mesh with a legend, on
        layer Almond::Environment::<label metric> (replacing that layer's previous drawing). metric:
        one of the run's display_metrics (e.g. da, ase_hours, udi_useful, mean_lux, df, lux, kwh_m2,
        sun_hours). clear=True removes the drawings (of this run's label, or all when run_id is empty)."""
        try:
            if clear:
                label = ""
                if run_id:
                    r, _ = studies.load_run(run_id)
                    label = r.get("label", "")
                if label:
                    # each metric has its own layer: clear every Environment layer that starts with the label
                    scripts = [rhino.clear_script(f"{label} {m}") for m in (r.get("display_metrics") or [])]
                else:
                    scripts = [rhino.clear_script("")]
                for s in scripts:
                    _execute(send, s, 60.0)
                return {"status": "success", "cleared": run_id or "all environment results"}
            if not run_id:
                return _err("Give run_id (see list_environment_runs).")
            return _draw(send, run_id, metric, min_value, max_value)
        except (ValueError, OSError, RuntimeError) as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=READ_ONLY)
    def list_environment_runs(limit: int = 20) -> dict:
        """Saved environmental analysis runs, newest first, with their headline results."""
        return {"status": "success", "runs": studies.list_runs(max(1, min(int(limit), 200))),
                "directory": str(studies.runs_dir())}

    @mcp.tool(annotations=READ_ONLY)
    def get_environment_run(run_id: str, include_values: bool = False, metric: str = "") -> dict:
        """A saved run's full summary (inputs, assumptions, classification, metrics, image paths).
        include_values adds the per-sensor values (and sensor points, metres) of one metric.
        Also takes a job_id from a background study: 'running' until it finishes, then its result."""
        job = _job_status(run_id)
        if job is not None:
            if job.get("status") != "success" or not include_values:
                return job
            run_id = job["run_id"]
        try:
            result, arrays = studies.load_run(run_id)
            result["status"] = "success"
            if include_values:
                m = metric or (result.get("display_metrics") or [None])[0]
                if m not in arrays:
                    return _err(f"Metric '{m}' not in this run; available: {[k for k in arrays if k not in ('points','normals','cells','area')]}")
                result["values"] = {"metric": m, "values": np.round(arrays[m].astype(float), 4).tolist(),
                                    "points": np.round(arrays["points"].astype(float), 3).tolist() if "points" in arrays else None}
            return result
        except (ValueError, OSError) as exc:
            return _err(str(exc))

    @mcp.tool(annotations=READ_ONLY)
    def list_environment_materials() -> dict:
        """The environmental material library (visible reflectance; glazing transmittance, shade
        transmittance, g and U) and the layer-name rules that pick them. Use the names in
        analyze_* materials overrides or as Rhino user text almond:env_material."""
        lib = [{"name": m.name, "kind": m.kind, **({"reflectance": m.reflectance} if m.kind == "opaque" else
                                                    {"transmittance": m.transmittance, "shade_transmittance": m.shade_transmittance,
                                                     "g_value": m.g_value, "u_value": m.u_value} if m.kind == "glazing" else {})}
               for m in scenemod.LIBRARY.values()]
        rules = [{"pattern": p, "material": m or scenemod.DEFAULT_GLAZING} for p, m in scenemod._RULES]
        return {"status": "success", "materials": lib, "name_rules_first_match_wins": rules,
                "unmatched": "classified per triangle by orientation: facing up -> floor (0.2), down -> ceiling (0.7), else wall (0.5)",
                "constructions": thermal.CONSTRUCTIONS, "thermal_mass_classes": list(thermal.MASS_CLASSES),
                "ray_backend": daylight.raytrace.backend()}

    # ── rooms, constructions, code packs ─────────────────────────────────────

    @mcp.tool(annotations=READ_ONLY)
    def list_constructions(kind: str = "", region: str = "") -> dict:
        """The construction library: layered assemblies (walls, roofs, floors, partitions, windows) with their
        U-value, areal heat capacity, finishes and glazing g / visible transmittance, plus construction sets
        (defaults per surface kind) and the sources and licences of the material data. kind: wall_external |
        wall_internal | roof | floor_ground | floor_exposed | floor_internal | window | door; region: eu, ch, de,
        uk, sg, tropical, temperate. Assign one to Rhino elements with assign_construction."""
        from almond_mcp.environment import constructions as asm
        try:
            sets = asm._load("assemblies.json")["sets"]
            if kind and kind not in asm.KINDS:
                return _err(f"kind must be one of {', '.join(asm.KINDS)}")
            regions = sorted({r for a in asm.library().values() for r in a.get("regions", [])} |
                             {r for st in sets for r in st["regions"]})
            if region and region not in regions:
                return _err(f"region must be one of {', '.join(r for r in regions if r != 'any')}")
            return {"status": "success", "constructions": asm.catalogue(kind, region),
                    "sets": [s for s in sets if not region or region in s["regions"] or "any" in s["regions"]],
                    "frames": list(asm.frames().values()),
                    "sources": [{k: s[k] for k in ("id", "title", "licence", "attribution")} for s in asm.sources().values()],
                    "note": "Layer data: EnergyPlus / ASHRAE HOF (BSD-style licence); finishes, frames and assembly "
                            "compositions are Almond assumptions - check against product data."}
        except ValueError as exc:
            return _err(str(exc))

    @mcp.tool(annotations=READ_ONLY)
    def get_construction(construction: str = "", custom: dict | None = None, diagram: bool = True) -> dict:
        """One construction in full: its layers (outside to inside, with conductivity, density, specific heat,
        thermal resistance and source), U-value by the EN ISO 6946 procedure, areal heat capacity each side
        (EN ISO 13786 periodic method), finishes; windows: U_g, U_w, g, visible transmittance. custom = an
        inline assembly {"kind": "wall_external", "layers": [{"material": "concrete_2400", "thickness_m": 0.2},
        ...]} to evaluate your own build-up. diagram=True adds an SVG section detail."""
        from almond_mcp.environment import constructions as asm
        try:
            if custom and construction:
                return _err("Give either construction (a library id) or custom (an inline build-up), not both")
            if custom is not None and not isinstance(custom, dict):
                return _err("custom must be an object such as {\"kind\": \"wall_external\", \"layers\": [...]}")
            p = asm.properties(custom if custom else construction)
            out = {"status": "success", **p}
            if diagram:
                from almond_mcp.environment import diagrams
                out["section_svg"] = diagrams.construction_section(p).svg()
            return out
        except INPUT_ERRORS as exc:
            return _err(str(exc))

    @mcp.tool(annotations=READ_ONLY)
    def list_code_packs() -> dict:
        """Regional code packs for envelope checks: what each contains, whether its values are bundled (licence
        recorded) or only its method is implemented, and the attribution to show. Packs: sg_bca (ETTV / RETV /
        RTTV, method; indicative, not a Green Mark assessment), uk_adl_2021 (Approved Document L limiting
        U-values, OGL), de_banz_2020 (German age-band U-values, public domain), eu_hotmaps (EU stock U-values,
        CC BY 4.0)."""
        from almond_mcp.environment import codes
        return {"status": "success", "packs": codes.packs()}

    @mcp.tool(annotations=WRITES)
    def define_room(name: str, guids: list[str], use: str = "living", construction_set: str = "",
                    heating_setpoint_c: float | str | None = None, cooling_setpoint_c: float | str | None = None,
                    height_m: float | None = None, remove: bool = False) -> dict:
        """Mark Rhino objects as one room (user text almond:room...). guids: a closed volume, several surfaces
        that bound the room (roof, walls - the room is the prism over their plan), or a closed planar curve
        with height_m. Rooms need not be enclosed: open pavilions and loggias are assessed with a warning.
        use: living | bedroom | kitchen | bath | circulation | office | classroom | outdoor (sets gains,
        schedule and set-points); construction_set fills faces with no construction (list_constructions).
        Set-points in degC (5-40, heating below cooling) or "off"; height_m in metres, for a boundary curve only.
        Room names must be unique: objects are grouped into a room by name. remove=True clears the room tags.
        Nothing is tagged if any GUID is missing. Undoable in Rhino."""
        from almond_mcp.environment import rooms as rm
        try:
            if not guids:
                return _err("Give the GUIDs of the room's volume, surfaces or boundary curve")
            if remove:
                tags = {k: "" for k in ("room", "room_use", "room_set", "room_heat_c", "room_cool_c", "room_height")}
            else:
                if not name.strip():
                    return _err("A room needs a name")
                if use not in rm.ROOM_USES:
                    return _err(f"use must be one of {', '.join(rm.ROOM_USES)}")
                if construction_set:
                    from almond_mcp.environment import constructions as asm
                    if construction_set not in {s["id"] for s in asm._load("assemblies.json")["sets"]}:
                        return _err(f"Unknown construction set '{construction_set}' (list_constructions)")
                sp = rm.parse_setpoints(heating_setpoint_c, cooling_setpoint_c)
                if height_m is not None:
                    rm.check_height(float(height_m))
                tags = {"room": name.strip(), "room_use": use, "room_set": construction_set,
                        "room_heat_c": "" if heating_setpoint_c is None else
                        ("off" if sp.get("heating_setpoint", 0) is None else f"{sp['heating_setpoint']:g}"),
                        "room_cool_c": "" if cooling_setpoint_c is None else
                        ("off" if sp.get("cooling_setpoint", 0) is None else f"{sp['cooling_setpoint']:g}"),
                        "room_height": "" if height_m is None else f"{float(height_m):g}"}
            reply = _execute(send, rhino.tag_script({g: tags for g in guids}, unique_room="" if remove else name.strip()), 60.0)
            return {"status": "success", "room": None if remove else name.strip(), "tagged": len(guids),
                    "guids": reply.get("guids") or [], "next_step": "list_rooms to see the enclosure check"}
        except INPUT_ERRORS as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=WRITES)
    def assign_construction(guids: list[str], construction: str) -> dict:
        """Give Rhino elements (walls, slabs, roofs, windows) a construction from list_constructions (user text
        almond:construction). An empty construction removes it. Rooms pick up the construction of each element
        that bounds them; analyses use its U-value, thermal mass, finishes and glazing. Undoable in Rhino."""
        from almond_mcp.environment import constructions as asm
        try:
            if construction:
                asm.get(construction)
            reply = _execute(send, rhino.tag_script({g: {"construction": construction} for g in guids}), 60.0)
            return {"status": "success", "construction": construction or None, "tagged": len(guids),
                    "guids": reply.get("guids") or [], "summary": asm.summary(construction) if construction else None}
        except INPUT_ERRORS as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=READ_ONLY)
    def list_rooms(geometry_guids: list[str] | None = None) -> dict:
        """The rooms defined in Rhino with their enclosure check: enclosed / semi-open / open, open share of the
        sides and top, openings by orientation, and the constructions found on their boundaries. geometry_guids:
        what to export (default every visible object)."""
        from almond_mcp.environment import rooms as rm
        try:
            data = _export(send, list(geometry_guids or []))
            rooms, encs, scene, notes = studies.prepare_rooms(data)
            out = []
            for r, e in zip(rooms, encs):
                found = sorted({c for c in e.tri_construction if c})
                out.append({"room": r.name, "use": r.use, "defined_by": r.source, "construction_set": r.construction_set or None,
                            "floor_area_m2": round(rm._floor_area(r), 2), "height_m": round(r.height, 2),
                            "enclosure": e.to_json(), "constructions_on_boundary": found, "guids": r.guids})
            return {"status": "success", "rooms": out, "warnings": notes}
        except INPUT_ERRORS as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=WRITES)
    def analyze_rooms(epw_path: str, study: str = "thermal", geometry_guids: list[str] | None = None,
                      construction: str = "typical", schedule: str = "residential", infiltration_ach: float = 0.3,
                      natural_ventilation_ach: float = 0.0, shading_g_factor: float = 1.0,
                      shading_min_outdoor_c: float | None = None, daylight_study: str = "annual",
                      quality: str = "medium", spacing_m: float = 0.5, envelope_pack: str = "",
                      pack_options: dict | None = None, cooling: bool = True, heat_recovery: float = 0.0, label: str = "",
                      point_in_time: dict | None = None, thermal_settings: dict | None = None,
                      background: bool = False) -> dict:
        """Analyse the rooms defined in Rhino (define_room) with their constructions (assign_construction).
        thermal_settings: any further thermal setting by name, e.g. {"heating_months": [11,12,1,2,3,4],
        "natural_ventilation_months": [5,6,7,8,9,10], "natural_ventilation_on_above": 18,
        "natural_ventilation_min_outdoor": 10, "comfort_months": [5,...,10], "heating_setback": 16,
        "custom_schedule": {...}}; the result's "building" gives whole-building heating / cooling / lighting
        kWh/m2 over the simulated rooms.
        study: thermal | daylight. Thermal: enclosed and semi-open rooms as coupled ISO 13790 zones (mass from
        the constructions, heat flow between rooms through shared walls and floors, air through openings);
        open rooms as semi-outdoor comfort (MRT with sun on the body, SET*). Rooms without a construction set
        use the preset `construction` for untagged faces. Daylight: one work-plane grid per room, metrics
        per room (sDA/ASE annual, or daylight_factor / point_in_time via daylight_study). envelope_pack
        (sg_bca, uk_adl_2021, de_banz_2020, eu_hotmaps) adds a code check with pack_options such as
        {"residential": true} for RETV, {"dwelling": false}, {"age_band": "1958-1968"}, {"country": "de"}.
        cooling=False runs every room without mechanical cooling (free-running in warm weather); heat_recovery =
        efficiency of heat recovery on the mechanical fresh air (0.8 for a typical heat-recovery ventilation unit).
        point_in_time (daylight_study="point_in_time"): {"month", "day", "hour", "sky": "epw" | "cie_overcast" |
        ...} as in analyze_daylight; per-room mean and minimum lux. Writes a saved run (get_environment_run).
        background=True returns a job_id (poll get_environment_run)."""
        if background:
            fn = getattr(analyze_rooms, "fn", analyze_rooms)
            args = _params(fn, locals())
            return _start_job("rooms", lambda: fn(**args))
        try:
            if study not in ("thermal", "daylight"):
                return _err("study must be thermal or daylight")
            if envelope_pack:
                from almond_mcp.environment import codes
                codes.check_options(envelope_pack, pack_options or {})        # before the simulation, not after
            data = _export(send, list(geometry_guids or []))
            if study == "daylight":
                weather = epw.load(epw_path) if epw_path else None
                res = studies.run_rooms_daylight(data, weather, daylight_study, quality, label, spacing_m,
                                                 point_time=point_in_time)
            elif study == "thermal":
                weather = _weather(epw_path)
                from almond_mcp.environment import cases as cs
                st = cs.settings_from({"construction": construction, "schedule": schedule, "infiltration_ach": infiltration_ach,
                                       "natural_ventilation_ach": natural_ventilation_ach, "shading_g_factor": shading_g_factor,
                                       "shading_min_outdoor_c": shading_min_outdoor_c, "heat_recovery": heat_recovery,
                                       **(thermal_settings or {})})
                res = studies.run_rooms_thermal(data, weather, st, label, {"epw_path": epw_path, "units_to_m": data.get("units_to_m")},
                                                envelope_pack=envelope_pack, pack_options=pack_options, cooling=cooling)
            else:
                return _err("study must be thermal or daylight")
            res["status"] = "success"
            return res
        except INPUT_ERRORS as exc:
            return _bridge_errors(exc)

    @mcp.tool(annotations=READ_ONLY)
    def check_envelope(pack: str, epw_path: str = "", geometry_guids: list[str] | None = None,
                       residential: bool = False, dwelling: bool = True, age_band: str = ">=2002",
                       country: str = "de", sector: str = "residential", flat_roof: bool = True,
                       user_tables_path: str = "") -> dict:
        """Check the envelope of the rooms defined in Rhino against a code pack (list_code_packs). sg_bca: ETTV
        (or RETV with residential=True) per facade and overall, with solar correction factors derived from the
        site EPW (epw_path required) and shading from the glazing g-value; user_tables_path = a JSON file of your
        own licensed CF tables to use instead ({"ETTV_walls": {"N": 0.8, ...}}). uk_adl_2021: area-weighted U per
        element against the limiting values (flat_roof=False for pitched roofs). de_banz_2020 / eu_hotmaps:
        reference U-values of the building stock for an age band / country to compare with (they do not check
        the model). Faces with no construction use the preset U-values and are listed. Indicative design checks,
        not certification."""
        from almond_mcp.environment import codes, rooms as rm
        try:
            data = _export(send, list(geometry_guids or []))
            options = {"residential": residential, "dwelling": dwelling, "age_band": age_band, "country": country,
                       "sector": sector, "flat_roof": flat_roof}
            codes.check_options(pack, options)
            weather = epw.load(epw_path) if epw_path else None
            tables = codes.load_user_tables(user_tables_path) if user_tables_path else None
            data = _export(send, list(geometry_guids or []))
            rooms, encs, scene, notes = studies.prepare_rooms(data)
            zones = rm.zones_from_rooms(rooms, encs, scene, studies._windows(scene), problems=notes)
            st = thermal.Settings()
            for z in zones:
                thermal.apply_construction(z, st)
            surfaces = studies.envelope_surfaces(zones)
            res = codes.check_envelope(surfaces, pack, weather, user_tables=tables, north_deg=scene.north_deg, **options)
            preset = sorted({(s["room"], s["kind"]) for s in surfaces if not s.get("construction")})
            if preset:
                notes.append("No construction on: " + ", ".join(f"{r} {k}" for r, k in preset) +
                             f" - the '{st.construction}' preset U-values stand in (assign_construction or a room construction set)")
            return {"status": "success", **res, "notes": notes}
        except INPUT_ERRORS as exc:
            return _bridge_errors(exc)

    return {"climate_summary": climate_summary, "sun_path": sun_path, "analyze_daylight": analyze_daylight,
            "analyze_solar_radiation": analyze_solar_radiation, "analyze_thermal": analyze_thermal,
            "thermal_comfort": thermal_comfort, "show_environment_result": show_environment_result,
            "list_environment_runs": list_environment_runs, "get_environment_run": get_environment_run,
            "list_environment_materials": list_environment_materials, "list_constructions": list_constructions,
            "get_construction": get_construction, "list_code_packs": list_code_packs, "define_room": define_room,
            "assign_construction": assign_construction, "list_rooms": list_rooms, "analyze_rooms": analyze_rooms,
            "check_envelope": check_envelope, "shadow_study": shadow_study, "compare_thermal_cases": compare_thermal_cases,
            "comfort_setpoints": comfort_setpoints, "compare_daylight_cases": compare_daylight_cases,
            "en17037_view_out": en17037_view_out, "en17037_sunlight": en17037_sunlight}
