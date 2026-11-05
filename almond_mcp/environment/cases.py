"""Design cases side by side: one base model, a list of variations, the same weather year.

A thermal case study runs every case through the 5R1C model and returns a comparison table, hourly CSV
files with explicit column names (one per case, plus one with every case's operative temperature), and
report charts: operative temperature through the warmest and coldest weeks against the outdoor air, and
the hourly energy balance of one case on the hottest day of the warmest week and the coldest day of the
coldest week. The weeks and days come from ``climate.extreme_weeks`` (the hourly outdoor extreme).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np

from . import charts, climate, epw, thermal
from .diagrams import AMBER, GREEN, INK, MUTED, RED

SETTING_NAMES = {f.name for f in dataclasses.fields(thermal.Settings)}
BALANCE_STYLE = (  # (balance key, label, colour) in the chart's stacking order
    ("people_w", "People", "#7d5aa3"), ("equipment_w", "Equipment", "#a48bc0"), ("lighting_w", "Lighting", "#c9b6dc"),
    ("window_solar_w", "Window solar", AMBER), ("window_conduction_w", "Window conduction", "#3b6ea8"),
    ("opaque_conduction_w", "Opaque conduction", "#7d9bc1"), ("infiltration_w", "Infiltration", GREEN),
    ("ventilation_w", "Ventilation", "#6fa58f"), ("openings_w", "Openings", "#9cc3b2"),
    ("natural_ventilation_w", "Natural ventilation", "#4f8f8b"), ("interzone_w", "Interzone", MUTED),
    ("thermal_mass_w", "Thermal mass", "#b4b3aa"), ("gains_lost_through_windows_w", "Gains lost via windows", "#d8d7cf"),
    ("heating_w", "Heating", RED), ("cooling_w", "Cooling", INK),
)


def settings_from(spec: dict) -> thermal.Settings:
    """thermal.Settings from a dict of its field names; free_running=True clears both set-points."""
    spec = dict(spec or {})
    free = bool(spec.pop("free_running", False))
    bad = sorted(set(spec) - SETTING_NAMES)
    if bad:
        raise ValueError(f"Unknown thermal setting(s) {bad}; known: {sorted(SETTING_NAMES)}")
    st = thermal.Settings(**spec)
    if free:
        st.heating_setpoint = st.cooling_setpoint = None
    st.validate()
    return st


def merge_case(base: dict, case: dict) -> dict:
    """The base with the case's overrides: 'settings' and 'shoebox' are merged key by key."""
    out = {"id": str(case.get("id") or ""), "settings": dict(base.get("settings") or {}), "shoebox": dict(base.get("shoebox") or {})}
    bad = sorted(set(case) - {"id", "settings", "shoebox", "label"})
    if bad:
        raise ValueError(f"A case has unknown key(s) {bad}: use 'id', 'settings' and 'shoebox'")
    out["settings"].update(case.get("settings") or {})
    out["shoebox"].update(case.get("shoebox") or {})
    out["label"] = str(case.get("label") or out["id"])
    return out


def hourly_columns(weather, res: dict) -> dict[str, np.ndarray]:
    """Named hourly columns for one zone: time, outdoor air, temperatures, loads and the energy balance."""
    cols = {"month": weather.month, "day": weather.day, "hour_ending": weather.hour,
            "outdoor_dry_bulb_c": weather["dry_bulb"], "air_temperature_c": res["t_air"],
            "operative_temperature_c": res["t_op"], "mean_radiant_temperature_c": 2 * res["t_op"] - res["t_air"],
            "occupancy_fraction": res.get("occupancy", res["occupied"].astype(float)),
            "window_shade_down": res["window_shading"].astype(int), "windows_open": res["natural_ventilation"].astype(int)}
    for k, v in res["balance_w"].items():
        cols[k] = v
    return cols


def write_csv(path: Path, cols: dict[str, np.ndarray]) -> str:
    keys = list(cols)
    n = len(next(iter(cols.values())))
    ints = {"month", "day", "hour_ending", "window_shade_down", "windows_open"}
    lines = [",".join(keys)]
    for i in range(n):
        lines.append(",".join(str(int(cols[k][i])) if k in ints else f"{float(cols[k][i]):.3f}" for k in keys))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _week_slice(doy0: int) -> slice:
    return slice(doy0 * 24, (doy0 + 7) * 24)


def week_chart(weather, cases: list[tuple[str, np.ndarray]], doy0: int, title: str):
    sl = _week_slice(doy0)
    series = [{"label": "Outdoor dry-bulb", "y": weather["dry_bulb"][sl], "colour": MUTED, "width": 1.2, "dash": "5 3"}]
    for k, (name, t_op) in enumerate(cases):
        series.append({"label": name, "y": t_op[sl], "colour": charts.SERIES[k % len(charts.SERIES)], "width": 1.4})
    labels = [(d / 7 + 1 / 14, climate._date(doy0 + d)) for d in range(7)]
    return charts.line_chart(series, labels, title, "Operative temperature C", width=860, height=380,
                             note="HOURLY, LOCAL STANDARD TIME")


def balance_chart(res: dict, floor_area: float, doy: int, title: str):
    """Hourly energy balance of one day in kWh/m2 (bars: gains up, losses down)."""
    sl = slice(doy * 24, doy * 24 + 24)
    stacks = []
    for key, label, col in BALANCE_STYLE:
        v = np.asarray(res["balance_w"].get(key, np.zeros(8760)), float)[sl] / 1000.0 / floor_area
        if np.any(np.abs(v) > 1e-6):
            stacks.append({"label": label, "values": v, "colour": col})
    return charts.stacked_bars([str(h + 1) for h in range(24)], stacks, title, "kWh/m2 per hour", width=860, height=420,
                               note="HOUR ENDING, LOCAL STANDARD TIME")


def run_thermal_cases(weather, base: dict, cases: list[dict], make_zones, out_dir: Path, balance_case: str = "") -> dict:
    """Run every case. ``make_zones(case) -> (zones, scene)`` builds fresh zones for a merged case
    (constructions are applied to the zones, so each case needs its own). Returns the comparison."""
    from . import studies
    if not cases:
        raise ValueError("Give at least one case")
    if len(cases) > 12:
        raise ValueError("At most 12 cases per comparison")
    merged = [merge_case(base, c) for c in cases]
    ids = [m["id"] or f"case {k + 1}" for k, m in enumerate(merged)]
    if len(set(ids)) != len(ids):
        raise ValueError(f"Case ids must be unique: {ids}")
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = climate.extreme_weeks(weather)
    warm, cold = ext["warmest_week"], ext["coldest_week"]
    hot_day, cold_day = warm["hottest_day"]["day_of_year"] - 1, cold["coldest_day"]["day_of_year"] - 1
    rows, t_ops, files, keep = [], [], {"cases": {}}, {}
    for cid, m in zip(ids, merged):
        st = settings_from(m["settings"])
        zones, sc = make_zones(m)
        thermal.solar_on_surfaces(zones, sc, weather, sc.north_deg)
        studies.prepare_lighting(zones, sc, weather, st)
        z = zones[0]
        thermal.apply_construction(z, st)
        res = thermal.simulate(z, weather, st)
        summ = thermal.summarize(z, res, weather, st)
        hrs = summ.get("adaptive_en16798_hours", {})
        rows.append({"id": cid, "label": m["label"], "zone": z.name, "floor_area_m2": summ["floor_area_m2"],
                     "heating_kwh_m2": summ["heating_kwh_m2"], "cooling_kwh_m2": summ["cooling_kwh_m2"],
                     "lighting_kwh_m2": summ.get("lighting_kwh_m2"),
                     "lighting_saving_pct": (summ.get("lighting_control") or {}).get("saving_pct"),
                     "peak_heating_w_m2": summ["peak_heating_w_m2"], "peak_cooling_w_m2": summ["peak_cooling_w_m2"],
                     "operative_max_c": summ["operative_temperature_c"]["max"],
                     "operative_min_c": summ["operative_temperature_c"]["min"],
                     "hours_above_26c_occupied": summ["hours_above_26c_occupied"],
                     "adaptive_cat_ii_too_warm_h": hrs.get("II", {}).get("too_warm_h"),
                     "adaptive_cat_ii_too_cool_h": hrs.get("II", {}).get("too_cool_h"),
                     "tm52_pass": (summ.get("tm52") or {}).get("pass"), "window_shading_hours": summ["window_shading_hours"],
                     "settings_changed": {k: v for k, v in m["settings"].items() if (base.get("settings") or {}).get(k) != v},
                     "shoebox_changed": {k: v for k, v in m["shoebox"].items() if (base.get("shoebox") or {}).get(k) != v}})
        t_ops.append((cid, res["t_op"]))
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in cid)
        files["cases"][cid] = write_csv(out_dir / f"hourly-{safe}.csv", hourly_columns(weather, res))
        keep[cid] = (res, summ["floor_area_m2"])
    all_cols = {"month": weather.month, "day": weather.day, "hour_ending": weather.hour,
                "outdoor_dry_bulb_c": weather["dry_bulb"]}
    for cid, t in t_ops:
        all_cols[f"operative_{cid}_c"] = t
    files["operative_all_cases_csv"] = write_csv(out_dir / "operative-temperature-all-cases.csv", all_cols)
    site = weather.location.label()
    files["warmest_week"] = charts.save(week_chart(weather, t_ops, warm["start_day_of_year"] - 1,
                                                   f"Operative temperature, warmest week {warm['start']} - {warm['end']} ({site})"),
                                        out_dir / "operative-warmest-week")
    files["coldest_week"] = charts.save(week_chart(weather, t_ops, cold["start_day_of_year"] - 1,
                                                   f"Operative temperature, coldest week {cold['start']} - {cold['end']} ({site})"),
                                        out_dir / "operative-coldest-week")
    bc = balance_case or ids[0]
    if bc not in keep:
        raise ValueError(f"balance_case '{bc}' is not one of the cases {ids}")
    res, area = keep[bc]
    files["balance_hottest_day"] = charts.save(balance_chart(res, area, hot_day, f"{bc}: energy balance, hottest day {warm['hottest_day']['date']}"),
                                               out_dir / f"energy-balance-hottest-day")
    files["balance_coldest_day"] = charts.save(balance_chart(res, area, cold_day, f"{bc}: energy balance, coldest day {cold['coldest_day']['date']}"),
                                               out_dir / f"energy-balance-coldest-day")
    for tag, doy in (("hottest", hot_day), ("coldest", cold_day)):
        sl = slice(doy * 24, doy * 24 + 24)
        cols = {"hour_ending": np.arange(1, 25), "outdoor_dry_bulb_c": weather["dry_bulb"][sl],
                "operative_temperature_c": res["t_op"][sl]}
        cols.update({k.replace("_w", "_kwh_m2"): v[sl] / 1000.0 / area for k, v in res["balance_w"].items()})
        files[f"balance_{tag}_day_csv"] = write_csv(out_dir / f"energy-balance-{tag}-day.csv", cols)
    return {"cases": rows, "weeks": {"warmest": warm, "coldest": cold, "file_periods": ext["file_periods"]},
            "balance_case": bc, "files": files,
            "notes": ["CSV temperatures in degC; balance columns in W (hourly CSVs) or kWh/m2 (day CSVs), + = heat into the room.",
                      "Energy balance terms add up to zero every hour; 'thermal_mass' is heat released (+) or stored (-) "
                      "by the structure.", ext["method"]]}
