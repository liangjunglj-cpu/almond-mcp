"""A synthetic but physically consistent weather year for the environmental tests (no EPW file is
redistributed with the repository). Clear-sky global irradiance (Haurwitz) thinned by a seeded cloud
series, split into direct and diffuse with the Erbs correlation; temperature from annual and daily
sinusoids; constant relative humidity. Written out as a real EPW and read back, so the parser is
exercised too."""
from __future__ import annotations

import numpy as np

from almond_mcp.environment import epw, solar


def synthetic_weather(latitude=1.35, longitude=103.99, time_zone=8.0, elevation=16.0, mean_t=27.5,
                      annual_amp=1.0, daily_amp=3.5, rh=78.0, cloudiness=0.65, seed=7, city="Synthetic"):
    hours = np.arange(epw.HOURS)
    month = np.repeat(np.repeat(np.arange(1, 13), epw.MONTH_DAYS), 24)
    day = np.concatenate([np.repeat(np.arange(1, d + 1), 24) for d in epw.MONTH_DAYS])
    hour = np.tile(np.arange(1, 25), 365)
    doy = epw.MONTH_START[month - 1] + day
    sp = solar.sun_position(latitude, longitude, time_zone, doy, hour - 0.5)
    cz = np.clip(np.cos(np.radians(sp["zenith"])), 0, 1)
    ghi_clear = np.where(cz > 0.01, 1098.0 * cz * np.exp(-0.057 / np.maximum(cz, 0.01)), 0.0)
    rng = np.random.default_rng(seed)
    daily_cloud = np.clip(rng.normal(cloudiness, 0.25, 365), 0, 0.95)
    cloud = np.repeat(daily_cloud, 24) * (0.8 + 0.4 * rng.random(epw.HOURS))
    ghi = ghi_clear * (1 - 0.75 * np.clip(cloud, 0, 1) ** 3.4 * 1.0)
    i0 = 1367.0 * (1 + 0.033 * np.cos(2 * np.pi * doy / 365.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        kt = np.where(cz > 0.01, ghi / (i0 * cz), 0.0)
    kt = np.clip(kt, 0, 1)
    fd = np.where(kt <= 0.22, 1 - 0.09 * kt,
                  np.where(kt <= 0.8, 0.9511 - 0.1604 * kt + 4.388 * kt ** 2 - 16.638 * kt ** 3 + 12.336 * kt ** 4, 0.165))
    dhi = ghi * fd
    with np.errstate(invalid="ignore", divide="ignore"):
        dni = np.where(cz > 0.05, (ghi - dhi) / cz, 0.0)
    dni = np.clip(dni, 0, 1100)
    hod = hour - 1
    t = (mean_t + annual_amp * np.cos(2 * np.pi * (doy - 200) / 365.0)
         + daily_amp * np.cos(2 * np.pi * (hod - 15) / 24.0))
    rhv = np.clip(rh - 15 * np.cos(2 * np.pi * (hod - 15) / 24.0), 20, 100)
    from almond_mcp.environment import comfort
    dp = comfort.dew_point(t, rhv)
    data = {name: np.full(epw.HOURS, np.nan) for name in epw.FIELD_NAMES}
    data.update({"dry_bulb": np.round(t, 1), "dew_point": np.round(dp, 1), "rel_humidity": np.round(rhv),
                 "pressure": np.full(epw.HOURS, 101000.0), "ghi": np.round(ghi), "dni": np.round(dni),
                 "dhi": np.round(dhi), "horizontal_ir": np.full(epw.HOURS, 400.0),
                 "wind_direction": np.round(rng.uniform(0, 360, epw.HOURS)), "wind_speed": np.round(2 + rng.random(epw.HOURS) * 3, 1),
                 "total_sky_cover": np.round(np.clip(cloud * 10, 0, 10)), "opaque_sky_cover": np.round(np.clip(cloud * 8, 0, 10))})
    loc = epw.Location(city=city, country="XX", source="synthetic", wmo="000000", latitude=latitude,
                       longitude=longitude, time_zone=time_zone, elevation=elevation)
    w = epw.Weather(location=loc, data=data, month=month, day=day, hour=hour, comments=["synthetic test year"])
    del hours
    return w


def synthetic_epw(path, **kw):
    """Write a synthetic year to ``path`` and return the parsed Weather."""
    epw.write_epw(synthetic_weather(**kw), path)
    return epw.read_epw(path)
