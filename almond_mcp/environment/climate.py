"""Climate summaries from a weather year: monthly statistics, degree days, design temperatures, wind
rose, psychrometric bins, outdoor comfort hours and indicative passive-design strategy hours.

The strategy hours follow the bioclimatic-chart idea (Olgyay 1963; Givoni 1969/1992; Milne & Givoni
1979). Published charts disagree on exact boundaries, so the thresholds used are explicit, returned
with the result and adjustable; read them as a teaching aid that ranks strategies, not as a rule.
"""
from __future__ import annotations

import numpy as np

from . import comfort
from .epw import MONTH_NAMES
from .radiation import WMO_SUNSHINE

SECTORS16 = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
WIND_BINS = (0.5, 2.0, 4.0, 6.0, 8.0)        # m/s; below 0.5 is calm

STRATEGY_DEFAULTS = {
    "comfort": {"t_min": 20.0, "t_max": 26.0, "w_min_g_kg": 4.0, "w_max_g_kg": 12.0, "rh_max": 80.0},
    "natural_ventilation": {"t_max": 32.0, "w_max_g_kg": 18.0, "rh_max": 90.0, "air_speed_m_s": 1.0},
    "thermal_mass_night_flush": {"t_max": 35.0, "w_max_g_kg": 12.0, "min_daily_range_k": 10.0},
    "evaporative_cooling": {"t_max": 40.0, "wet_bulb_max": 22.0},
    "passive_solar_heating": {"t_min": 12.0},
}


def _circular_mean_deg(deg: np.ndarray, weights: np.ndarray | None = None) -> float:
    a = np.radians(deg)
    w = np.ones_like(a) if weights is None else weights
    return float(np.degrees(np.arctan2((np.sin(a) * w).sum(), (np.cos(a) * w).sum())) % 360.0)


def wind_rose(w, months=None) -> dict:
    d = w["wind_direction"]
    s = w["wind_speed"]
    mask = np.isfinite(d) & np.isfinite(s)
    if months:
        mask &= np.isin(w.month, months)
    d, s = d[mask], s[mask]
    n = max(len(s), 1)
    calm = s < WIND_BINS[0]
    sector = ((d + 11.25) % 360 // 22.5).astype(int)
    edges = list(WIND_BINS) + [np.inf]
    table = []
    for i, name in enumerate(SECTORS16):
        row = {"sector": name}
        for j in range(len(edges) - 1):
            sel = (sector == i) & (s >= edges[j]) & (s < edges[j + 1])
            row[f"{edges[j]:g}-{edges[j + 1]:g}" if np.isfinite(edges[j + 1]) else f">{edges[j]:g}"] = round(100 * sel.sum() / n, 2)
        row["total_pct"] = round(100 * ((sector == i) & ~calm).sum() / n, 2)
        table.append(row)
    prevailing = max(table, key=lambda r: r["total_pct"])["sector"] if table else None
    return {"calm_pct": round(100 * calm.sum() / n, 2), "prevailing": prevailing, "sectors": table,
            "speed_bins_m_s": ["calm<0.5"] + [r for r in table[0] if r not in ("sector", "total_pct")] if table else []}


def strategy_hours(w, thresholds: dict | None = None) -> dict:
    th = {k: dict(v) for k, v in STRATEGY_DEFAULTS.items()}
    for k, v in (thresholds or {}).items():
        if k not in th:
            raise ValueError(f"unknown strategy '{k}'")
        th[k].update(v)
    t = w["dry_bulb"]
    rh = w["rel_humidity"]
    p = w["pressure"]
    wr = comfort.humidity_ratio(t, rh, p) * 1000.0
    wb = comfort.wet_bulb(t, rh, p)
    daily_range = np.repeat(np.ptp(w["dry_bulb"].reshape(365, 24), axis=1), 24)
    c = th["comfort"]
    in_comfort = (t >= c["t_min"]) & (t <= c["t_max"]) & (wr >= c["w_min_g_kg"]) & (wr <= c["w_max_g_kg"]) & (rh <= c["rh_max"])
    nv = th["natural_ventilation"]
    vent = (t > c["t_max"]) & (t <= nv["t_max"]) & (wr <= nv["w_max_g_kg"]) & (rh <= nv["rh_max"])
    tm = th["thermal_mass_night_flush"]
    mass = (t > c["t_max"]) & (t <= tm["t_max"]) & (wr <= tm["w_max_g_kg"]) & (daily_range >= tm["min_daily_range_k"])
    ev = th["evaporative_cooling"]
    evap = (t > c["t_max"]) & (t <= ev["t_max"]) & (wb <= ev["wet_bulb_max"])
    ps = th["passive_solar_heating"]
    solar = (t >= ps["t_min"]) & (t < c["t_min"])
    heating = t < ps["t_min"]
    dehum = (t >= c["t_min"]) & (t <= c["t_max"]) & ((wr > c["w_max_g_kg"]) | (rh > c["rh_max"]))
    cooling = (t > c["t_max"]) & ~(vent | mass | evap)
    n = len(t)

    def pct(x):
        return round(100.0 * float(x.sum()) / n, 1)
    covered = in_comfort | vent | mass | evap | solar
    return {
        "hours_pct": {"comfortable": pct(in_comfort), "natural_ventilation": pct(vent),
                      "thermal_mass_night_flush": pct(mass), "evaporative_cooling": pct(evap),
                      "passive_solar_heating": pct(solar), "active_heating": pct(heating),
                      "dehumidification": pct(dehum), "active_cooling": pct(cooling),
                      "comfortable_with_passive_strategies": pct(covered)},
        "thresholds": th,
        "note": "Indicative bioclimatic-chart strategies (after Givoni); strategies overlap, so the "
                "shares do not add to 100. Thresholds are adjustable.",
    }


def psychrometric_bins(w, t_step: float = 1.0, w_step_g: float = 1.0) -> dict:
    t = w["dry_bulb"]
    wr = comfort.humidity_ratio(t, w["rel_humidity"], w["pressure"]) * 1000.0
    ti = np.floor(t / t_step).astype(int)
    wi = np.floor(wr / w_step_g).astype(int)
    keys, counts = np.unique(np.stack([ti, wi], axis=1), axis=0, return_counts=True)
    return {"t_step_c": t_step, "w_step_g_kg": w_step_g,
            "bins": [[float(k[0] * t_step), float(k[1] * w_step_g), int(c)] for k, c in zip(keys, counts)],
            "columns": ["dry_bulb_c (bin start)", "humidity_ratio_g_kg (bin start)", "hours"]}


def _date(doy: int) -> str:
    """0-based day of the year -> 'Mar 20' (no leap day)."""
    from .epw import MONTH_START
    m = int(np.searchsorted(MONTH_START, doy, side="right"))
    return f"{MONTH_NAMES[m - 1]} {doy - int(MONTH_START[m - 1]) + 1}"


def _period_days(start: str, end: str) -> int | None:
    """Length in days of an EPW 'm/d' to 'm/d' period, inclusive, also across the year end."""
    from .epw import MONTH_START
    try:
        (m0, d0), (m1, d1) = ((int(x) for x in s.strip().split("/")) for s in (start, end))
    except ValueError:
        return None
    a, b = int(MONTH_START[m0 - 1]) + d0 - 1, int(MONTH_START[m1 - 1]) + d1 - 1
    return (b - a) % 365 + 1


def extreme_weeks(w) -> dict:
    """The warmest and coldest 7-day periods of the year, by mean dry-bulb temperature computed from the
    hourly data, and in each the hottest / coldest day by the hourly outdoor extreme. Also the file's own
    TYPICAL/EXTREME PERIODS header, with each period's real length (the header's 'week' can cross the
    year end or be longer than 7 days)."""
    days = w["dry_bulb"].reshape(365, 24)
    daily = days.mean(axis=1)
    roll = np.convolve(daily, np.ones(7) / 7, mode="valid")          # start days 0..358, no wrap
    out = {}
    for key, k, pick, day_pick in (("warmest_week", int(np.argmax(roll)), "max", np.argmax),
                                   ("coldest_week", int(np.argmin(roll)), "min", np.argmin)):
        span = days[k:k + 7]
        extreme = getattr(span, pick)(axis=1)
        dk = k + int(day_pick(extreme))
        out[key] = {"start": _date(k), "end": _date(k + 6), "start_day_of_year": k + 1,
                    "mean_dry_bulb_c": round(float(roll[k]), 1),
                    ("hottest_day" if pick == "max" else "coldest_day"): {
                        "date": _date(dk), "day_of_year": dk + 1,
                        ("max_dry_bulb_c" if pick == "max" else "min_dry_bulb_c"): round(float(getattr(days[dk], pick)()), 1),
                        "hour_ending": int(day_pick(days[dk])) + 1}}
    periods = []
    for p in getattr(w, "typical_periods", []) or []:
        n = _period_days(p.get("start", ""), p.get("end", ""))
        row = dict(p, days=n)
        if n is not None and "week" in p.get("name", "").lower() and n != 7:
            row["note"] = f"called a week in the file, but spans {n} days"
        periods.append(row)
    out["file_periods"] = periods
    out["method"] = ("7-day running mean of the daily mean dry-bulb (days from 1 Jan, not wrapping the year end); "
                     "the hottest / coldest day is the day in that week with the highest / lowest hourly outdoor "
                     "dry-bulb. EPW hours are hour-ending: hour 13 is 12:00-13:00 local standard time.")
    return out


DIURNAL_VARIABLES = (("dry_bulb", "Dry-bulb", "C"), ("wet_bulb", "Wet-bulb", "C"), ("ghi", "Global horizontal", "W/m2"),
                     ("dhi", "Diffuse horizontal", "W/m2"), ("dni", "Direct normal", "W/m2"))


def diurnal_averages(w) -> dict:
    """Monthly diurnal averages: for each month the mean of each hour of the day, for dry-bulb and wet-bulb
    temperature and global horizontal, diffuse horizontal and direct normal irradiance."""
    wb = comfort.wet_bulb(w["dry_bulb"], w["rel_humidity"], w["pressure"])
    data = {"dry_bulb": w["dry_bulb"], "wet_bulb": wb, "ghi": w["ghi"], "dhi": w["dhi"], "dni": w["dni"]}
    hod = w.hour_of_day
    months = []
    for m in range(1, 13):
        sel = w.month == m
        row = {"month": MONTH_NAMES[m - 1]}
        for key, _, _ in DIURNAL_VARIABLES:
            v, h = data[key][sel], hod[sel]
            row[key] = [round(float(v[h == k].mean()), 1) for k in range(24)]
        months.append(row)
    return {"months": months, "hours": "index 0..23 = hour ending 01:00..24:00 local standard time (EPW convention)",
            "units": {k: u for k, _, u in DIURNAL_VARIABLES}}


def diurnal_chart(w, title: str = ""):
    """The monthly diurnal averages as one chart: 12 months side by side, 24 hours each, temperatures on
    the left axis and irradiance on the right."""
    from . import charts
    from .diagrams import AMBER, GREEN, INK, MUTED, PANEL, RED, Canvas
    d = diurnal_averages(w)
    c = Canvas(980, 420, background=charts.PAPER)
    c.text(16, 22, title or f"Monthly diurnal averages - {w.location.label()}", 12, INK, weight="bold")
    temps = np.array([m[k] for m in d["months"] for k in ("dry_bulb", "wet_bulb")]).ravel()
    rad = np.array([m[k] for m in d["months"] for k in ("ghi", "dhi", "dni")]).ravel()
    f = charts.Frame(c, 50, 52, 880, 300, float(temps.min()) - 1, float(temps.max()) + 1, "Temperature C",
                     y2=(0.0, max(float(rad.max()), 100.0), "Irradiance W/m2"))
    seg = f.w / 12
    styles = {"dry_bulb": (INK, 1.6, None), "wet_bulb": (GREEN, 1.2, None), "ghi": (AMBER, 1.2, None),
              "dhi": (MUTED, 1.0, "4 2"), "dni": (RED, 1.2, None)}
    for i, m in enumerate(d["months"]):
        x0 = f.x0 + i * seg
        if i % 2:
            c.rect(x0, f.y0, seg, f.h, fill=PANEL, stroke=None)
        c.text(x0 + seg / 2, f.y0 + f.h + 15, m["month"], 9, INK, anchor="middle")
    for i, m in enumerate(d["months"]):
        x0 = f.x0 + i * seg
        for key, (col, wid, dash) in styles.items():
            y = f.y if key in ("dry_bulb", "wet_bulb") else f.yb
            c.line([(x0 + seg * (h + 0.5) / 24, y(v)) for h, v in enumerate(m[key])], col, wid, dash)
    charts.legend(c, 50, 396, [(label, styles[k][0], styles[k][2]) for k, label, _ in DIURNAL_VARIABLES], per_row=5, step=170)
    c.text(964, 22, "HOUR-ENDING, LOCAL STANDARD TIME", 8, MUTED, mono=True, anchor="end")
    return c


def summarize(w, hdd_base: float = 18.0, cdd_base: float = 18.0, thresholds: dict | None = None) -> dict:
    t = w["dry_bulb"]
    days_t = t.reshape(365, 24)
    daily_mean = days_t.mean(axis=1)
    dmonth = w.month[::24]
    rh = w["rel_humidity"]
    t_rm = comfort.running_mean_outdoor(daily_mean, 0.8)
    ash = comfort.adaptive_ashrae55(t, t_rm, air_speed=0.0)
    months = []
    for m in range(1, 13):
        sel = w.month == m
        dsel = dmonth == m
        wd = w["wind_direction"][sel]
        ws = w["wind_speed"][sel]
        months.append({
            "month": MONTH_NAMES[m - 1],
            "dry_bulb_mean": round(float(t[sel].mean()), 1),
            "daily_max_mean": round(float(days_t[dsel].max(axis=1).mean()), 1),
            "daily_min_mean": round(float(days_t[dsel].min(axis=1).mean()), 1),
            "max": round(float(t[sel].max()), 1), "min": round(float(t[sel].min()), 1),
            "rel_humidity_mean": round(float(rh[sel].mean()), 0),
            "dew_point_mean": round(float(w["dew_point"][sel].mean()), 1),
            "ghi_kwh_m2": round(float(w["ghi"][sel].sum() / 1000), 1),
            "dni_kwh_m2": round(float(w["dni"][sel].sum() / 1000), 1),
            "dhi_kwh_m2": round(float(w["dhi"][sel].sum() / 1000), 1),
            "bright_sun_hours": int((w["dni"][sel] >= WMO_SUNSHINE).sum()),
            "wind_mean_m_s": round(float(ws.mean()), 1),
            "wind_prevailing": SECTORS16[int(((_circular_mean_deg(wd, ws) + 11.25) % 360) // 22.5)],
            "hdd": round(float(np.maximum(hdd_base - daily_mean[dsel], 0).sum()), 0),
            "cdd": round(float(np.maximum(daily_mean[dsel] - cdd_base, 0).sum()), 0),
            "outdoor_adaptive_comfort_pct": round(100 * float(ash["comfortable_80"][sel].mean()), 0),
            "sky_cover_mean_tenths": round(float(np.nanmean(w["total_sky_cover"][sel])), 1)
            if np.isfinite(w["total_sky_cover"][sel]).any() else None,
        })
    dc = w.design_conditions or {}
    hi_t = w["dew_point"]
    return {
        "location": w.summary(),
        "annual": {
            "dry_bulb_mean": round(float(t.mean()), 1), "max": round(float(t.max()), 1), "min": round(float(t.min()), 1),
            "mean_daily_range": round(float(np.ptp(days_t, axis=1).mean()), 1),
            "rel_humidity_mean": round(float(rh.mean()), 0),
            "ghi_kwh_m2": round(float(w["ghi"].sum() / 1000), 0), "dni_kwh_m2": round(float(w["dni"].sum() / 1000), 0),
            "dhi_kwh_m2": round(float(w["dhi"].sum() / 1000), 0),
            "bright_sun_hours": int((w["dni"] >= WMO_SUNSHINE).sum()),
            f"hdd_{hdd_base:g}": round(float(np.maximum(hdd_base - daily_mean, 0).sum()), 0),
            f"cdd_{cdd_base:g}": round(float(np.maximum(daily_mean - cdd_base, 0).sum()), 0),
            "heating_design_99_6_c": round(float(np.percentile(t, 0.4)), 1),
            "cooling_design_0_4_c": round(float(np.percentile(t, 99.6)), 1),
            "design_conditions_from_file": {k: v for k, v in dc.items() if k != "raw"},
            "hours_above_30c": int((t > 30).sum()), "hours_below_10c": int((t < 10).sum()),
            "heat_index_max_c": round(float(comfort.heat_index(t, rh).max()), 1),
            "max_dew_point_c": round(float(hi_t.max()), 1),
            "outdoor_adaptive_comfort_pct": round(100 * float(ash["comfortable_80"].mean()), 1),
            "ground_temperatures": w.ground_temperatures[:3],
        },
        "monthly": months,
        "extreme_weeks": extreme_weeks(w),
        "wind_rose": wind_rose(w),
        "strategies": strategy_hours(w, thresholds),
        "notes": ["Design temperatures here are percentiles of this file's hours; ASHRAE's published values "
                  "come from long records and appear under design_conditions_from_file when the file has them.",
                  "Outdoor adaptive comfort uses the ASHRAE 55 80 % band against outdoor air temperature: a "
                  "natural-ventilation potential indicator, not an indoor prediction.",
                  "bright_sun_hours count the hours with direct-normal irradiance of at least 120 W/m2 in this file. "
                  "Typical-year files with modelled radiation (TMYx, ERA5-based) can give far more than the measured "
                  "sunshine duration, so do not quote them as sunshine hours."],
    }
