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


def _bridge_errors(exc: Exception) -> dict:
    if isinstance(exc, ConnectionRefusedError):
        return _err("Rhino is not reachable: open Rhino 8 with the almondbridge plugin, or use shoebox=... to analyse "
                    "a parametric room without Rhino.")
    return _err(f"{type(exc).__name__}: {exc}")


def register(mcp, send: Sender) -> dict:
    """Register the environmental tools on ``mcp``; returns them by name."""

    @mcp.tool(annotations=READ_ONLY)
    def climate_summary(epw_path: str, hdd_base_c: float = 18.0, cdd_base_c: float = 18.0,
                        strategy_thresholds: dict | None = None, include_psychrometric_bins: bool = False) -> dict:
        """Climate analysis of an EPW weather file (no Rhino needed): location and data quality (every
        repaired or missing value is counted), monthly temperatures / humidity / solar radiation /
        sunshine / wind, heating and cooling degree days, design temperatures, a 16-sector wind rose,
        outdoor adaptive-comfort hours, and indicative passive-strategy hours on the bioclimatic chart
        (comfort, natural ventilation, thermal mass + night flush, evaporative cooling, passive solar,
        dehumidification, active heating/cooling; thresholds returned and adjustable through
        strategy_thresholds, e.g. {"comfort": {"t_max": 27}}). include_psychrometric_bins adds the
        hourly temperature x humidity-ratio histogram for drawing a psychrometric chart."""
        try:
            w = _weather(epw_path)
            return {"status": "success", **studies.climate_report(w, hdd_base_c, cdd_base_c, strategy_thresholds,
                                                                  include_psychrometric_bins)}
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
    def analyze_daylight(epw_path: str = "", study: str = "annual", grid_guids: list[str] | None = None,
                         geometry_guids: list[str] | None = None, shoebox: dict | None = None,
                         quality: str = "medium", grid_spacing_m: float = 0.6, work_plane_m: float = 0.76,
                         edge_offset_m: float = 0.0, materials: dict | None = None, glazing: str = "",
                         shade_transmittance: float | None = None, dynamic_shading: bool = True,
                         aperture_grouping: str = "orientation", occupied_hours: list[float] | None = None,
                         weekdays_only: bool = False, da_threshold_lux: float = 300.0,
                         point_in_time: dict | None = None, views: list[dict] | None = None,
                         ground_reflectance: float = 0.2, north_deg: float | None = None,
                         show_in_rhino: bool = True, label: str = "", background: bool = False) -> dict:
        """Daylight simulation in the manner of ClimateStudio / Radiance (clean-room, native engine).

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
                                       inputs=inputs, dropped=dropped)
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
                                  metabolic_rate=metabolic_rate, air_speed=air_speed)
            st.validate()
            inputs = {"epw_path": epw_path}
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

    return {"climate_summary": climate_summary, "sun_path": sun_path, "analyze_daylight": analyze_daylight,
            "analyze_solar_radiation": analyze_solar_radiation, "analyze_thermal": analyze_thermal,
            "thermal_comfort": thermal_comfort, "show_environment_result": show_environment_result,
            "list_environment_runs": list_environment_runs, "get_environment_run": get_environment_run,
            "list_environment_materials": list_environment_materials}
