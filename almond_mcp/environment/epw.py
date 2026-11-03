"""EnergyPlus weather (EPW) files: parse, validate, repair and write.

The format is documented in the EnergyPlus "Auxiliary Programs" reference (Weather Converter, section
"EnergyPlus Weather File (EPW) Data Dictionary"). Eight header lines, then one comma-separated record
per time step with 35 fields. Times are local standard time, and record ``hour`` h covers the interval
that *ends* at h:00 (hour 1 = 00:00-01:00).

What "robust" means here:

* every header is optional except LOCATION; a malformed one is reported, not fatal;
* missing-value sentinels (99.9, 999, 9999, 999999 ...) and out-of-range values become NaN;
* sub-hourly files are averaged to hourly; a leap-year file (8784 rows) drops 29 February;
* short gaps (<= ``max_gap_hours``) are filled by linear interpolation, longer ones from the mean
  of the same hour in the same month; a column with no valid data falls back to a derived value
  where one exists (relative humidity from dew point, illuminance from irradiance) or is reported;
* night-time irradiance is zeroed, negative irradiance clamped, and DNI that is inconsistent with
  global and diffuse is flagged;
* every repair is counted in ``Weather.report`` so a result can say how much of it is data.
"""
from __future__ import annotations

import hashlib
import io
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HOURS = 8760
MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
MONTH_START = np.cumsum((0,) + MONTH_DAYS[:-1])            # day-of-year index of each month's 1st
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# (name, column, missing sentinel (values >= it are missing; None = no sentinel), valid min, valid max)
FIELDS = (
    ("dry_bulb", 6, 99.9, -70.0, 70.0),                     # degC
    ("dew_point", 7, 99.9, -70.0, 70.0),                    # degC
    ("rel_humidity", 8, 999.0, 0.0, 110.0),                 # %
    ("pressure", 9, 999999.0, 31000.0, 120000.0),           # Pa
    ("extra_horizontal", 10, 9999.0, 0.0, 1500.0),          # Wh/m2
    ("extra_direct_normal", 11, 9999.0, 0.0, 1500.0),       # Wh/m2
    ("horizontal_ir", 12, 9999.0, 0.0, 1000.0),             # Wh/m2
    ("ghi", 13, 9999.0, 0.0, 1500.0),                       # global horizontal, Wh/m2
    ("dni", 14, 9999.0, 0.0, 1500.0),                       # direct normal, Wh/m2
    ("dhi", 15, 9999.0, 0.0, 1000.0),                       # diffuse horizontal, Wh/m2
    ("global_illuminance", 16, 999900.0, 0.0, 200000.0),    # lux
    ("direct_illuminance", 17, 999900.0, 0.0, 200000.0),    # lux
    ("diffuse_illuminance", 18, 999900.0, 0.0, 200000.0),   # lux
    ("zenith_luminance", 19, 9999.0, 0.0, 70000.0),         # cd/m2
    ("wind_direction", 20, 999.0, 0.0, 360.0),              # degrees from north, clockwise
    ("wind_speed", 21, 999.0, 0.0, 40.0),                   # m/s
    ("total_sky_cover", 22, 99.0, 0.0, 10.0),               # tenths
    ("opaque_sky_cover", 23, 99.0, 0.0, 10.0),              # tenths
    ("visibility", 24, 9999.0, 0.0, 9999.0),                # km
    ("ceiling_height", 25, 99999.0, 0.0, 99999.0),          # m
    ("precipitable_water", 28, 999.0, 0.0, 100.0),          # mm
    ("aerosol_depth", 29, 0.999, 0.0, 0.999),               # thousandths
    ("snow_depth", 30, 999.0, 0.0, 999.0),                  # cm
    ("days_since_snow", 31, 99.0, 0.0, 99.0),
    ("albedo", 32, 999.0, 0.0, 1.0),
    ("liquid_precip_depth", 33, 999.0, 0.0, 999.0),         # mm
    ("liquid_precip_rate", 34, 99.0, 0.0, 99.0),            # hours
)
FIELD_NAMES = tuple(f[0] for f in FIELDS)
RADIATION = ("extra_horizontal", "extra_direct_normal", "ghi", "dni", "dhi")
ILLUMINANCE = ("global_illuminance", "direct_illuminance", "diffuse_illuminance", "zenith_luminance")
# Columns whose gaps are filled (the rest are informational and stay NaN where missing).
CORE = ("dry_bulb", "dew_point", "rel_humidity", "pressure", "ghi", "dni", "dhi", "horizontal_ir",
        "wind_direction", "wind_speed", "total_sky_cover", "opaque_sky_cover")
NOMINAL_YEAR = 2019                                          # any non-leap year: only for day-of-week
MAX_FILE_BYTES = 60 * 1024 * 1024


class EPWError(ValueError):
    """The file cannot be read as weather data at all (not merely incomplete)."""


@dataclass
class Location:
    city: str = ""
    state: str = ""
    country: str = ""
    source: str = ""
    wmo: str = ""
    latitude: float = 0.0               # degrees, north positive
    longitude: float = 0.0              # degrees, east positive
    time_zone: float = 0.0              # hours from GMT, east positive
    elevation: float = 0.0              # m

    def label(self) -> str:
        parts = [p for p in (self.city, self.state, self.country) if p and p not in ("-", "?")]
        return ", ".join(parts) or "unknown location"


@dataclass
class Weather:
    """One year of hourly weather, 8760 rows, hour index 0 = 1 January 00:00-01:00 (standard time)."""
    location: Location
    data: dict[str, np.ndarray]
    month: np.ndarray                   # 1..12
    day: np.ndarray                     # 1..31
    hour: np.ndarray                    # 1..24 (EPW convention: hour ending)
    ground_temperatures: list[dict] = field(default_factory=list)
    design_conditions: dict = field(default_factory=dict)
    typical_periods: list[dict] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    source_path: str = ""
    sha256: str = ""
    report: dict = field(default_factory=dict)
    start_weekday: int = 1              # weekday of 1 January, 0 = Monday (DATA PERIODS)

    def __getitem__(self, name: str) -> np.ndarray:
        return self.data[name]

    @property
    def day_of_year(self) -> np.ndarray:
        """1..365 for every hour."""
        return MONTH_START[self.month - 1] + self.day

    @property
    def hour_of_day(self) -> np.ndarray:
        """0..23: the hour the interval starts at (hour ending 1 -> 0)."""
        return self.hour - 1

    def weekday(self) -> np.ndarray:
        """0 = Monday .. 6 = Sunday for every hour, starting from the file's DATA PERIODS weekday."""
        return (self.day_of_year - 1 + self.start_weekday) % 7

    def daily_mean(self, name: str = "dry_bulb") -> np.ndarray:
        return self.data[name].reshape(365, 24).mean(axis=1)

    def summary(self) -> dict:
        loc = self.location
        return {
            "location": loc.label(), "latitude": loc.latitude, "longitude": loc.longitude,
            "time_zone": loc.time_zone, "elevation_m": loc.elevation, "wmo": loc.wmo, "source": loc.source,
            "sha256": self.sha256[:16], "path": self.source_path, "data_quality": self.report,
        }


# ── parsing ──────────────────────────────────────────────────────────────────

def _f(value: str, default: float = math.nan) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _parse_location(line: list[str], report: dict) -> Location:
    if len(line) < 10:
        report.setdefault("warnings", []).append(
            f"LOCATION has {len(line) - 1} fields, expected 9; missing ones default to 0.")
        line = line + [""] * (10 - len(line))
    loc = Location(city=line[1].strip(), state=line[2].strip(), country=line[3].strip(),
                   source=line[4].strip(), wmo=line[5].strip(),
                   latitude=_f(line[6], 0.0), longitude=_f(line[7], 0.0),
                   time_zone=_f(line[8], 0.0), elevation=_f(line[9], 0.0))
    if not -90 <= loc.latitude <= 90:
        raise EPWError(f"LOCATION latitude {loc.latitude} is outside -90..90.")
    if not -180 <= loc.longitude <= 180:
        raise EPWError(f"LOCATION longitude {loc.longitude} is outside -180..180.")
    if not -12 <= loc.time_zone <= 14:
        raise EPWError(f"LOCATION time zone {loc.time_zone} is outside -12..+14 hours.")
    # A time zone far from the longitude's solar zone usually means a sign error (west = negative).
    if abs(loc.time_zone - loc.longitude / 15.0) > 3.5:
        report.setdefault("warnings", []).append(
            f"Time zone {loc.time_zone:+g} h is far from longitude {loc.longitude:+.2f} ({loc.longitude / 15:+.1f} h): "
            "check the signs (west and south are negative). Sun positions use the file's values.")
    return loc


def _parse_ground(line: list[str], report: dict) -> list[dict]:
    out = []
    try:
        n = int(_f(line[1], 0))
        vals = line[2:]
        for i in range(n):
            chunk = vals[i * 16:(i + 1) * 16]
            if len(chunk) < 16:
                break
            out.append({"depth_m": _f(chunk[0]), "conductivity": _f(chunk[1]), "density": _f(chunk[2]),
                        "specific_heat": _f(chunk[3]), "monthly_c": [_f(v) for v in chunk[4:16]]})
    except (IndexError, ValueError):
        report.setdefault("warnings", []).append("GROUND TEMPERATURES header could not be read.")
    return [g for g in out if all(math.isfinite(t) for t in g["monthly_c"])]


def _parse_design(line: list[str]) -> dict:
    """The ASHRAE design-condition block, kept by label: heating 99.6/99 %, cooling 0.4/1/2 % dry bulb."""
    out: dict = {"raw": ",".join(line[1:])[:2000]}
    try:
        tokens = [t.strip() for t in line]
        if "Heating" in tokens:
            h = tokens.index("Heating")
            out["heating_99_6_c"] = _f(tokens[h + 2])
            out["heating_99_c"] = _f(tokens[h + 3])
        if "Cooling" in tokens:
            c = tokens.index("Cooling")
            out["cooling_0_4_c"] = _f(tokens[c + 3])
            out["cooling_0_4_mcwb_c"] = _f(tokens[c + 4])
            out["cooling_1_c"] = _f(tokens[c + 5])
            out["cooling_2_c"] = _f(tokens[c + 7])
    except IndexError:
        pass
    return {k: v for k, v in out.items() if not (isinstance(v, float) and math.isnan(v))}


def _parse_periods(line: list[str]) -> list[dict]:
    out = []
    try:
        n = int(_f(line[1], 0))
        for i in range(n):
            name, kind, start, end = (t.strip() for t in line[2 + 4 * i:6 + 4 * i])
            out.append({"name": name, "type": kind, "start": start, "end": end})
    except (ValueError, IndexError):
        pass
    return out


def read_epw(path: str | os.PathLike, max_gap_hours: int = 6) -> Weather:
    """Read, validate and repair an EPW file. Raises EPWError when it cannot be weather data."""
    p = Path(path)
    if not p.is_file():
        raise EPWError(f"No weather file at {p}.")
    if p.suffix.lower() == ".zip":
        raise EPWError("This is a zip archive: extract the .epw file from it first.")
    size = p.stat().st_size
    if size > MAX_FILE_BYTES:
        raise EPWError(f"{p.name} is {size / 1e6:.0f} MB; an hourly EPW is about 1.6 MB.")
    raw = p.read_bytes()
    w = parse_epw_text(_decode(raw), max_gap_hours=max_gap_hours)
    w.source_path = str(p)
    w.sha256 = hashlib.sha256(raw).hexdigest()
    return w


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_epw_text(text: str, max_gap_hours: int = 6) -> Weather:
    report: dict = {"warnings": []}
    headers: dict[str, list[str]] = {}
    rows: list[list[str]] = []
    comments: list[str] = []
    records_per_hour = 1
    for raw_line in io.StringIO(text):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(",")
        key = parts[0].strip().upper()
        if not rows and (key[:1].isalpha() or key.startswith("!")):
            if key.startswith("COMMENTS"):
                comments.append(",".join(parts[1:]).strip())
            headers[key] = parts
            if key == "DATA PERIODS":
                try:
                    records_per_hour = max(1, int(_f(parts[2], 1)))
                except IndexError:
                    pass
            continue
        rows.append(parts)
    if "LOCATION" not in headers:
        raise EPWError("No LOCATION header: this is not an EPW file.")
    if not rows:
        raise EPWError("The file has headers but no data records.")
    location = _parse_location(headers["LOCATION"], report)

    n_fields = 35
    short = sum(1 for r in rows if len(r) < 22)
    if short > len(rows) * 0.01:
        raise EPWError(f"{short} of {len(rows)} records have fewer than 22 fields: not EPW data.")
    table = np.full((len(rows), n_fields), np.nan)
    month = np.zeros(len(rows), dtype=int)
    day = np.zeros(len(rows), dtype=int)
    hour = np.zeros(len(rows), dtype=int)
    minute = np.zeros(len(rows), dtype=int)
    for i, r in enumerate(rows):
        try:
            month[i], day[i], hour[i] = int(float(r[1])), int(float(r[2])), int(float(r[3]))
            minute[i] = int(float(r[4])) if r[4].strip() else 0
        except (ValueError, IndexError):
            month[i] = day[i] = hour[i] = 0
        for name, col, *_ in FIELDS:
            if col < len(r):
                table[i, col] = _f(r[col])
    bad_time = (month < 1) | (month > 12) | (day < 1) | (day > 31) | (hour < 1) | (hour > 24)
    if bad_time.any():
        report["warnings"].append(f"{int(bad_time.sum())} records with an invalid date or hour were dropped.")
        keep = ~bad_time
        table, month, day, hour, minute = table[keep], month[keep], day[keep], hour[keep], minute[keep]

    leap = (month == 2) & (day == 29)
    if leap.any():
        report["warnings"].append("29 February was dropped (analysis uses a 365-day year).")
        keep = ~leap
        table, month, day, hour, minute = table[keep], month[keep], day[keep], hour[keep], minute[keep]

    # Place every record in its hour of a nominal year; average sub-hourly records into their hour.
    valid_day = day <= np.array(MONTH_DAYS)[month - 1]
    if not valid_day.all():
        report["warnings"].append(f"{int((~valid_day).sum())} records on a non-existent date were dropped.")
        table, month, day, hour = table[valid_day], month[valid_day], day[valid_day], hour[valid_day]
    idx = (MONTH_START[month - 1] + day - 1) * 24 + (hour - 1)
    if records_per_hour > 1 or len(idx) > HOURS:
        report["sub_hourly"] = int(records_per_hour)
    sums = np.zeros((HOURS, n_fields))
    counts = np.zeros((HOURS, n_fields))
    finite = np.isfinite(table)
    np.add.at(sums, idx, np.where(finite, table, 0.0))
    np.add.at(counts, idx, finite.astype(float))
    present = np.zeros(HOURS, dtype=bool)
    present[idx] = True
    with np.errstate(invalid="ignore", divide="ignore"):
        hourly = sums / counts
    missing_rows = int((~present).sum())
    if missing_rows > HOURS * 0.5:
        raise EPWError(f"Only {HOURS - missing_rows} of 8760 hours are present: not a full weather year.")
    if missing_rows:
        report["warnings"].append(f"{missing_rows} hours had no record and were filled.")
    report["hours_missing_records"] = missing_rows

    data: dict[str, np.ndarray] = {}
    invalid: dict[str, int] = {}
    absent: list[str] = []
    for name, col, sentinel, lo, hi in FIELDS:
        v = hourly[:, col].copy()
        bad = ~np.isfinite(v)
        if sentinel is not None:
            bad |= v >= sentinel
        bad |= (v < lo) | (v > hi)
        n_bad = int(bad.sum() - (~present).sum())
        if bad.all():
            absent.append(name)           # a column the source never provides (common): not an error
        elif n_bad > 0:
            invalid[name] = n_bad
        v[bad] = np.nan
        data[name] = v
    if absent:
        report["absent_columns"] = absent

    ref = np.arange(HOURS)
    months = np.repeat(np.repeat(np.arange(1, 13), MONTH_DAYS), 24)
    days = np.concatenate([np.repeat(np.arange(1, d + 1), 24) for d in MONTH_DAYS])
    hours = np.tile(np.arange(1, 25), 365)
    w = Weather(location=location, data=data, month=months, day=days, hour=hours,
                ground_temperatures=_parse_ground(headers.get("GROUND TEMPERATURES", ["", "0"]), report),
                design_conditions=_parse_design(headers.get("DESIGN CONDITIONS", [""])),
                typical_periods=_parse_periods(headers.get("TYPICAL/EXTREME PERIODS", ["", "0"])),
                comments=comments, report=report)
    w.start_weekday = _start_weekday(headers.get("DATA PERIODS"))
    _repair(w, invalid, max_gap_hours)
    return w


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _start_weekday(line: list[str] | None) -> int:
    """Weekday of 1 January from DATA PERIODS (0 = Monday); the nominal year's Tuesday otherwise."""
    try:
        return _WEEKDAYS.index(line[4].strip().lower())
    except (TypeError, IndexError, ValueError):
        return 1


# ── repair ───────────────────────────────────────────────────────────────────

def _fill_gaps(v: np.ndarray, month: np.ndarray, hour: np.ndarray, max_gap: int, circular: bool = False) -> tuple[np.ndarray, int, int]:
    """Linear interpolation over runs of NaN up to ``max_gap`` long, then the same-hour monthly mean.
    Returns (filled, n_interpolated, n_climatology)."""
    v = v.copy()
    nan = np.isnan(v)
    if not nan.any():
        return v, 0, 0
    if nan.all():
        return v, 0, 0
    n_interp = 0
    # find NaN runs
    edges = np.diff(np.concatenate([[0], nan.view(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    good = np.flatnonzero(~nan)
    for s, e in zip(starts, ends):
        if e - s > max_gap:
            continue
        left, right = s - 1, e
        if left < 0 or right >= len(v):
            # gap at the year boundary: wrap around (December 31 to January 1)
            left_i = good[-1] if left < 0 else left
            right_i = good[0] if right >= len(v) else right
            vl, vr = v[left_i], v[right_i]
        else:
            vl, vr = v[left], v[right]
        span = e - s + 1
        for k in range(s, e):
            t = (k - s + 1) / span
            if circular:
                d = ((vr - vl + 180.0) % 360.0) - 180.0
                v[k] = (vl + t * d) % 360.0
            else:
                v[k] = vl + t * (vr - vl)
        n_interp += e - s
    nan = np.isnan(v)
    n_clim = int(nan.sum())
    if n_clim:
        for m in range(1, 13):
            for h in range(1, 25):
                sel = (month == m) & (hour == h)
                fill = sel & nan
                if not fill.any():
                    continue
                ok = v[sel & ~nan]
                if ok.size == 0:
                    ok = v[(month == m) & ~nan]
                if ok.size == 0:
                    ok = v[~nan]
                if circular:
                    a = np.radians(ok)
                    v[fill] = np.degrees(np.arctan2(np.sin(a).mean(), np.cos(a).mean())) % 360.0
                else:
                    v[fill] = ok.mean()
    return v, n_interp, n_clim


def _repair(w: Weather, invalid: dict[str, int], max_gap: int) -> None:
    from . import comfort, solar   # local: comfort/solar import nothing from here at module level

    rep = w.report
    d = w.data
    filled: dict[str, dict] = {}

    # Humidity: derive the missing one of RH / dew point where the other exists.
    t, dp, rh = d["dry_bulb"], d["dew_point"], d["rel_humidity"]
    derive_rh = np.isnan(rh) & np.isfinite(t) & np.isfinite(dp)
    if derive_rh.any():
        rh[derive_rh] = np.clip(comfort.rh_from_dew_point(t[derive_rh], dp[derive_rh]), 0, 100)
        filled.setdefault("rel_humidity", {})["derived"] = int(derive_rh.sum())
    derive_dp = np.isnan(dp) & np.isfinite(t) & np.isfinite(rh)
    if derive_dp.any():
        dp[derive_dp] = comfort.dew_point(t[derive_dp], np.maximum(rh[derive_dp], 1.0))
        filled.setdefault("dew_point", {})["derived"] = int(derive_dp.sum())
    if np.isnan(d["pressure"]).all():
        d["pressure"][:] = 101325.0 * (1 - 2.25577e-5 * w.location.elevation) ** 5.25588
        filled["pressure"] = {"standard_atmosphere": HOURS}

    for name in CORE:
        v = d[name]
        if np.isnan(v).all():
            continue
        new, n_i, n_c = _fill_gaps(v, w.month, w.hour, max_gap, circular=name == "wind_direction")
        if n_i or n_c:
            entry = filled.setdefault(name, {})
            if n_i:
                entry["interpolated"] = n_i
            if n_c:
                entry["monthly_hour_mean"] = n_c
        d[name] = new

    missing_core = [n for n in ("dry_bulb", "ghi", "dhi") if np.isnan(d[n]).all()]
    if "dry_bulb" in missing_core:
        raise EPWError("The file has no valid dry-bulb temperatures.")

    # Radiation: zero at night, non-negative, components consistent.
    sun = solar.sun_positions_for(w)
    alt = sun["altitude"]
    night = alt <= 0.0
    for name in RADIATION:
        v = d[name]
        v[night & np.isfinite(v)] = 0.0
        np.maximum(v, 0.0, out=v)
    ghi, dni, dhi = d["ghi"], d["dni"], d["dhi"]
    if np.isnan(dni).all() and np.isfinite(ghi).all() and np.isfinite(dhi).all():
        sin_alt = np.sin(np.radians(np.maximum(alt, 0.0)))
        with np.errstate(invalid="ignore", divide="ignore"):
            d["dni"] = np.where(sin_alt > 0.05, np.clip((ghi - dhi) / sin_alt, 0, 1400), 0.0)
        filled["dni"] = {"derived_from_ghi_dhi": HOURS}
        dni = d["dni"]
    if np.isnan(ghi).all() and np.isfinite(dni).all() and np.isfinite(dhi).all():
        d["ghi"] = dhi + dni * np.sin(np.radians(np.maximum(alt, 0.0)))
        filled["ghi"] = {"derived_from_dni_dhi": HOURS}
        ghi = d["ghi"]
    # Closure check (WMO-style): GHI vs DHI + DNI cos(Z), only where the sun is well up.
    day_ok = (alt > 10) & (ghi > 50)
    if day_ok.any():
        closure = dhi[day_ok] + dni[day_ok] * np.sin(np.radians(alt[day_ok]))
        rel = np.abs(closure - ghi[day_ok]) / ghi[day_ok]
        rep["radiation_closure_median_error"] = round(float(np.median(rel)), 3)
        bad = int((rel > 0.25).sum())
        if bad > day_ok.sum() * 0.1:
            rep["warnings"].append(
                f"GHI differs from DHI + DNI x cos(zenith) by more than 25 % in {bad} daytime hours: "
                "the file's solar radiation may be inconsistent (check its source).")
    # DHI must not exceed GHI by much.
    over = (dhi > ghi * 1.05 + 5) & ~night
    if over.any():
        dhi[over] = ghi[over]
        filled.setdefault("dhi", {})["clamped_to_ghi"] = int(over.sum())

    # Illuminance: keep valid file values, derive the rest (Perez 1990 luminous efficacy).
    from . import sky
    eff = sky.perez_illuminance(w, sun)
    for name in ("global_illuminance", "direct_illuminance", "diffuse_illuminance"):
        v = d[name]
        need = np.isnan(v) | night
        v[night] = 0.0
        derive = need & ~night
        if derive.any():
            v[derive] = eff[name][derive]
            filled.setdefault(name, {})["perez_1990"] = int(derive.sum())
        # a file value wildly off the irradiance (e.g. lux stored as Wh) is replaced too
        day = ~night & (eff[name] > 1000) & np.isfinite(v)
        ratio = np.ones_like(v)
        ratio[day] = v[day] / eff[name][day]
        wild = day & ((ratio < 0.2) | (ratio > 5))
        if wild.sum() > 50:
            v[wild] = eff[name][wild]
            filled.setdefault(name, {})["replaced_inconsistent"] = int(wild.sum())

    if invalid:
        rep["invalid_values"] = invalid
    if filled:
        rep["filled"] = filled
    core_total = sum(sum(e.values()) for k, e in filled.items() if k in CORE)
    rep["core_fill_fraction"] = round(core_total / (HOURS * len(CORE)), 4)
    if rep["core_fill_fraction"] > 0.05:
        rep["warnings"].append(
            f"{rep['core_fill_fraction']:.0%} of the core weather values were filled: treat results as indicative.")
    if not w.ground_temperatures:
        w.ground_temperatures = [{"depth_m": 0.5, "monthly_c": _ground_from_air(w), "derived": True}]


def _ground_from_air(w: Weather) -> list[float]:
    """Monthly ground temperature at ~0.5 m when the file has none: the annual mean plus the monthly
    swing damped to 60 % and lagged one month (a common Kusuda-type shortcut)."""
    t = w.data["dry_bulb"]
    monthly = np.array([t[w.month == m].mean() for m in range(1, 13)])
    mean = monthly.mean()
    lagged = np.roll(monthly, 1)
    return [round(float(mean + 0.6 * (x - mean)), 2) for x in lagged]


# ── writing (used by tests and to save repaired data) ────────────────────────

_SENTINEL_OUT = {f[0]: f[2] for f in FIELDS}


def write_epw(w: Weather, path: str | os.PathLike) -> Path:
    loc = w.location
    lines = [
        f"LOCATION,{loc.city},{loc.state},{loc.country},{loc.source},{loc.wmo},{loc.latitude:.4f},"
        f"{loc.longitude:.4f},{loc.time_zone:.1f},{loc.elevation:.1f}",
        "DESIGN CONDITIONS,0",
        "TYPICAL/EXTREME PERIODS,0",
    ]
    if w.ground_temperatures:
        g = w.ground_temperatures[0]
        lines.append("GROUND TEMPERATURES,1," + ",".join(
            [f"{g.get('depth_m', 0.5)}", "", "", ""] + [f"{t:.2f}" for t in g["monthly_c"]]))
    else:
        lines.append("GROUND TEMPERATURES,0")
    lines += ["HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
              "COMMENTS 1," + (w.comments[0] if w.comments else "written by almond_mcp.environment"),
              "COMMENTS 2,", "DATA PERIODS,1,1,Data,Tuesday, 1/ 1,12/31"]
    cols = {f[1]: f[0] for f in FIELDS}
    for i in range(HOURS):
        rec = [str(NOMINAL_YEAR), str(w.month[i]), str(w.day[i]), str(w.hour[i]), "60", "?9?9?9?9E0?9?9?9?9?9?9?9?9?9?9?9?9?9?9*9*9?9?9?9"]
        for col in range(6, 35):
            name = cols.get(col)
            if name is None:
                rec.append("0" if col == 26 else "999999999")
                continue
            v = w.data[name][i]
            if not np.isfinite(v):
                rec.append(f"{_SENTINEL_OUT[name]:g}")
            elif name in ("dry_bulb", "dew_point"):
                rec.append(f"{v:.1f}")
            elif name == "aerosol_depth":
                rec.append(f"{v:.3f}")
            elif name == "albedo":
                rec.append(f"{v:.2f}")
            else:
                rec.append(f"{v:.0f}")
        lines.append(",".join(rec))
    out = Path(path)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ── cache ────────────────────────────────────────────────────────────────────

_CACHE: dict[tuple[str, float, int], Weather] = {}


def load(path: str | os.PathLike) -> Weather:
    """read_epw with a small in-process cache keyed by path, modification time and size."""
    p = Path(path).expanduser().resolve()
    st = p.stat() if p.is_file() else None
    if st is None:
        raise EPWError(f"No weather file at {p}.")
    key = (str(p), st.st_mtime, st.st_size)
    w = _CACHE.get(key)
    if w is None:
        w = read_epw(p)
        if len(_CACHE) > 8:
            _CACHE.clear()
        _CACHE[key] = w
    return w
