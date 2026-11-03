"""Sun position and sun paths.

The algorithm is NOAA's solar calculator (after Meeus, "Astronomical Algorithms", 1991): about 0.01 deg
between 1950 and 2050, with standard atmospheric refraction. Angles are degrees; azimuth is measured
clockwise from north (0 = N, 90 = E). Model axes: +Y is north, +X is east, +Z is up, unless a
``north_deg`` rotation says otherwise (the angle from +Y to true north, counter-clockwise positive,
the usual convention of a "north" input in daylighting software).
"""
from __future__ import annotations

import math

import numpy as np

from .epw import HOURS, MONTH_START, NOMINAL_YEAR


def _julian_day(year: int, day_of_year: np.ndarray, hours_ut: np.ndarray) -> np.ndarray:
    # JD at 0h UT on 1 January of ``year`` (Gregorian), then add days.
    y, m = year - 1, 13
    a = y // 100
    b = 2 - a + a // 4
    jd0 = math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + 1 + b - 1524.5
    return jd0 + (day_of_year - 1) + hours_ut / 24.0


def sun_position(latitude: float, longitude: float, time_zone: float, day_of_year, hour_local,
                 year: int = NOMINAL_YEAR, refraction: bool = True) -> dict[str, np.ndarray]:
    """Sun altitude/azimuth/zenith (deg), declination and equation of time (min) for local standard
    times. ``hour_local`` is decimal hours (12.5 = 12:30) on day ``day_of_year`` (1..365)."""
    doy = np.asarray(day_of_year, dtype=float)
    hl = np.asarray(hour_local, dtype=float)
    doy, hl = np.broadcast_arrays(doy, hl)
    hours_ut = hl - time_zone
    jd = _julian_day(year, doy, hours_ut)
    jc = (jd - 2451545.0) / 36525.0
    l0 = np.mod(280.46646 + jc * (36000.76983 + jc * 0.0003032), 360.0)
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = np.radians(m)
    c = (np.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
         + np.sin(2 * mr) * (0.019993 - 0.000101 * jc) + np.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * np.sin(np.radians(omega))
    mean_obliq = 23.0 + (26.0 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60.0) / 60.0
    obliq = mean_obliq + 0.00256 * np.cos(np.radians(omega))
    decl = np.degrees(np.arcsin(np.sin(np.radians(obliq)) * np.sin(np.radians(app_long))))
    vy = np.tan(np.radians(obliq / 2.0)) ** 2
    l0r = np.radians(l0)
    eot = 4.0 * np.degrees(vy * np.sin(2 * l0r) - 2 * e * np.sin(mr) + 4 * e * vy * np.sin(mr) * np.cos(2 * l0r)
                           - 0.5 * vy * vy * np.sin(4 * l0r) - 1.25 * e * e * np.sin(2 * mr))
    true_solar_min = np.mod(hl * 60.0 + eot + 4.0 * longitude - 60.0 * time_zone, 1440.0)
    hour_angle = true_solar_min / 4.0 - 180.0
    lat = math.radians(latitude)
    dr = np.radians(decl)
    har = np.radians(hour_angle)
    cos_z = np.clip(math.sin(lat) * np.sin(dr) + math.cos(lat) * np.cos(dr) * np.cos(har), -1.0, 1.0)
    zen = np.degrees(np.arccos(cos_z))
    sin_z = np.sin(np.radians(zen))
    with np.errstate(invalid="ignore", divide="ignore"):
        cos_az = (math.sin(lat) * cos_z - np.sin(dr)) / (math.cos(lat) * sin_z)
    cos_az = np.clip(np.nan_to_num(cos_az, nan=1.0), -1.0, 1.0)
    acos_deg = np.degrees(np.arccos(cos_az))
    az = np.where(hour_angle > 0, np.mod(acos_deg + 180.0, 360.0), np.mod(540.0 - acos_deg, 360.0))
    # Exactly at a pole or zenith, azimuth is undefined: use the hour angle.
    az = np.where(sin_z < 1e-9, np.mod(hour_angle + 180.0, 360.0), az)
    alt = 90.0 - zen
    if refraction:
        alt = alt + _refraction(alt)
    return {"altitude": alt, "azimuth": az, "zenith": 90.0 - alt, "declination": decl,
            "equation_of_time": eot, "hour_angle": hour_angle}


def _refraction(alt: np.ndarray) -> np.ndarray:
    """NOAA's piecewise atmospheric refraction correction, degrees."""
    a = np.asarray(alt, dtype=float)
    out = np.zeros_like(a)
    te = np.tan(np.radians(np.clip(a, -5.0, 89.9)))
    hi = (a > 5) & (a <= 85)
    out[hi] = (58.1 / te[hi] - 0.07 / te[hi] ** 3 + 0.000086 / te[hi] ** 5) / 3600.0
    mid = (a > -0.575) & (a <= 5)
    out[mid] = (1735.0 + a[mid] * (-518.2 + a[mid] * (103.4 + a[mid] * (-12.79 + a[mid] * 0.711)))) / 3600.0
    lo = a <= -0.575
    out[lo] = (-20.772 / te[lo]) / 3600.0
    return out


def sun_positions_for(weather, mid_hour: bool = True) -> dict[str, np.ndarray]:
    """Sun position for every hour of a Weather year: at the middle of each EPW interval by default
    (hour ending h -> h - 0.5), which is what the hourly radiation sums refer to."""
    loc = weather.location
    hour = weather.hour - (0.5 if mid_hour else 0.0)
    return sun_position(loc.latitude, loc.longitude, loc.time_zone, weather.day_of_year, hour)


def direction_vector(altitude_deg, azimuth_deg, north_deg: float = 0.0) -> np.ndarray:
    """Unit vector(s) pointing *towards* the sun in model coordinates (N, 3)."""
    alt = np.radians(np.asarray(altitude_deg, dtype=float))
    az = np.radians(np.asarray(azimuth_deg, dtype=float) - north_deg)
    # azimuth clockwise from +Y: x = sin(az), y = cos(az)
    return np.stack([np.cos(alt) * np.sin(az), np.cos(alt) * np.cos(az), np.sin(alt)], axis=-1)


def vector_to_alt_az(v: np.ndarray, north_deg: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    v = np.asarray(v, dtype=float)
    alt = np.degrees(np.arcsin(np.clip(v[..., 2], -1, 1)))
    az = np.mod(np.degrees(np.arctan2(v[..., 0], v[..., 1])) + north_deg, 360.0)
    return alt, az


def sun_path(latitude: float, longitude: float, time_zone: float, north_deg: float = 0.0,
             step_minutes: int = 20) -> dict:
    """Sun path diagram data: the solstice/equinox day arcs (21st of each month) and the hourly
    analemmas, as altitude/azimuth lists (only above-horizon points)."""
    months = {}
    t = np.arange(0, 24 * 60 + 1, step_minutes) / 60.0
    for mi in range(12):
        doy = MONTH_START[mi] + 21
        sp = sun_position(latitude, longitude, time_zone, np.full_like(t, doy), t)
        up = sp["altitude"] > 0
        months[mi + 1] = {"day_of_year": int(doy),
                          "altitude": np.round(sp["altitude"][up], 2).tolist(),
                          "azimuth": np.round(sp["azimuth"][up], 2).tolist(),
                          "hour": np.round(t[up], 3).tolist()}
    days = np.arange(1, 366)
    analemmas = {}
    for h in range(24):
        sp = sun_position(latitude, longitude, time_zone, days, np.full(days.shape, float(h)))
        up = sp["altitude"] > 0
        if up.any():
            analemmas[h] = {"altitude": np.round(sp["altitude"][up][::7], 2).tolist(),
                            "azimuth": np.round(sp["azimuth"][up][::7], 2).tolist()}
    return {"months": months, "analemmas": analemmas, "north_deg": north_deg}


def day_events(latitude: float, longitude: float, time_zone: float, day_of_year: int) -> dict:
    """Sunrise, solar noon and sunset (local standard time, decimal hours) and day length, by
    scanning the day at one-minute resolution (robust at high latitudes: polar day/night reported)."""
    t = np.arange(0, 24 * 60) / 60.0
    sp = sun_position(latitude, longitude, time_zone, np.full_like(t, day_of_year), t)
    alt = sp["altitude"] + 0.2667       # upper limb (solar semi-diameter)
    up = alt > 0
    noon = float(t[int(np.argmax(sp["altitude"]))])
    if up.all():
        return {"polar": "day", "solar_noon": noon, "day_length_h": 24.0,
                "max_altitude": float(sp["altitude"].max())}
    if not up.any():
        return {"polar": "night", "solar_noon": noon, "day_length_h": 0.0,
                "max_altitude": float(sp["altitude"].max())}
    rises = np.flatnonzero(~up[:-1] & up[1:])
    sets = np.flatnonzero(up[:-1] & ~up[1:])
    return {"sunrise": float(t[rises[0] + 1]) if rises.size else None,
            "sunset": float(t[sets[-1] + 1]) if sets.size else None,
            "solar_noon": noon, "day_length_h": round(float(up.sum()) / 60.0, 3),
            "max_altitude": round(float(sp["altitude"].max()), 3)}


def hour_index(month: int, day: int, hour: float) -> int:
    """Index into an 8760 year for local standard ``hour`` (0..24) on ``month``/``day``: the EPW
    interval that contains it (12:30 -> the record for hour ending 13)."""
    if not 1 <= month <= 12:
        raise ValueError("month must be 1..12")
    from .epw import MONTH_DAYS
    if not 1 <= day <= MONTH_DAYS[month - 1]:
        raise ValueError(f"day must be 1..{MONTH_DAYS[month - 1]} for month {month}")
    if not 0 <= hour <= 24:
        raise ValueError("hour must be 0..24")
    i = (int(MONTH_START[month - 1]) + day - 1) * 24 + min(23, int(math.floor(hour)))
    return max(0, min(HOURS - 1, i))
