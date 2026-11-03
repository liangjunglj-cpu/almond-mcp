"""Skies: patch discretisation, luminous efficacy, sky luminance distributions and hourly sky matrices.

* Patches: Tregenza (145) and its Reinhart subdivisions (MF 2 -> 577, MF 4 -> 2305), plus one ground
  patch (index ``n_sky``), the same scheme Radiance's gendaymtx uses (patch numbering is our own).
* Luminous efficacy: Perez, Ineichen, Seals, Michalsky & Stewart (1990), "Modeling daylight
  availability and irradiance components from direct and global irradiance", Solar Energy 44(5).
* Sky luminance: Perez, Seals & Michalsky (1993), "All-weather model for sky luminance distribution",
  Solar Energy 50(3); coefficients as tabulated there (and in Radiance gendaylit).
* CIE: the 1955 overcast sky (Moon & Spencer) used for daylight factors, a uniform sky, and the
  15 CIE general standard skies (ISO 15469:2004 / CIE S 011).

A sky matrix holds, for every hour, the luminance (cd/m2, or radiance W/m2/sr for irradiance) of each
patch from the *diffuse* sky only, normalised so that it reproduces the measured diffuse horizontal
value exactly on the discrete patches. The sun is kept separately as a direction and a direct-normal
value, so it can be traced exactly instead of being smeared over a patch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

TREGENZA_ROWS = (30, 30, 24, 24, 18, 12, 6)
SOLAR_CONSTANT = 1367.0          # W/m2
LUMINOUS_EFFICACY_DEFAULT = 179.0   # lm/W, Radiance's white-light convention for irradiance->luminance


@dataclass(frozen=True)
class Patches:
    mf: int
    n_sky: int                    # sky patches; index n_sky is the ground
    altitude: np.ndarray          # centre altitude, deg (n_sky + 1; ground = -90)
    azimuth: np.ndarray           # centre azimuth, deg clockwise from north
    solid_angle: np.ndarray       # sr (ground = 2 pi)
    direction: np.ndarray         # unit vectors (n_sky + 1, 3), model axes with north = +Y
    row_height: float
    row_start: np.ndarray         # first patch index of each row (rows + cap)
    row_count: np.ndarray         # patches per row
    projected: np.ndarray         # exact integral of sin(altitude) d(omega) over each sky patch (n_sky,)

    @property
    def n(self) -> int:
        return self.n_sky + 1

    def index(self, directions: np.ndarray) -> np.ndarray:
        """Patch index for unit direction vectors (model axes, north = +Y). Below the horizon -> ground."""
        d = np.asarray(directions, dtype=float)
        alt = np.degrees(np.arcsin(np.clip(d[..., 2], -1.0, 1.0)))
        az = np.mod(np.degrees(np.arctan2(d[..., 0], d[..., 1])), 360.0)
        return self.index_alt_az(alt, az)

    def index_alt_az(self, alt: np.ndarray, az: np.ndarray) -> np.ndarray:
        alt = np.asarray(alt, dtype=float)
        az = np.asarray(az, dtype=float)
        n_rows = len(self.row_count) - 1
        row = np.clip(np.floor(np.maximum(alt, 0.0) / self.row_height).astype(int), 0, n_rows)
        count = self.row_count[row]
        width = 360.0 / count
        col = np.floor(np.mod(az + 0.5 * width, 360.0) / width).astype(int) % count
        idx = self.row_start[row] + col
        return np.where(alt < 0.0, self.n_sky, idx)


_PATCH_CACHE: dict[int, Patches] = {}


def patches(mf: int = 1) -> Patches:
    """Reinhart sky subdivision with multiplication factor ``mf`` (1 = Tregenza 145)."""
    if mf not in (1, 2, 3, 4, 6):
        raise ValueError("mf must be 1, 2, 3, 4 or 6")
    if mf in _PATCH_CACHE:
        return _PATCH_CACHE[mf]
    n_rows = 7 * mf
    rh = 90.0 / (n_rows + 0.5)
    alt, az, omega, proj, starts, counts = [], [], [], [], [], []
    for r in range(n_rows):
        n = TREGENZA_ROWS[r // mf] * mf
        a0, a1 = r * rh, (r + 1) * rh
        s0, s1 = math.sin(math.radians(a0)), math.sin(math.radians(a1))
        band = 2 * math.pi * (s1 - s0)
        starts.append(len(alt))
        counts.append(n)
        for c in range(n):
            alt.append(0.5 * (a0 + a1))
            az.append(c * 360.0 / n)
            omega.append(band / n)
            proj.append(math.pi * (s1 * s1 - s0 * s0) / n)       # integral of sin(a) cos(a) da dphi
    starts.append(len(alt))
    counts.append(1)
    a0 = n_rows * rh
    s0 = math.sin(math.radians(a0))
    alt.append(90.0)
    az.append(0.0)
    omega.append(2 * math.pi * (1 - s0))
    proj.append(math.pi * (1 - s0 * s0))
    n_sky = len(alt)
    alt.append(-90.0)
    az.append(0.0)
    omega.append(2 * math.pi)
    alt_a, az_a = np.array(alt), np.array(az)
    ar, zr = np.radians(alt_a), np.radians(az_a)
    direction = np.stack([np.cos(ar) * np.sin(zr), np.cos(ar) * np.cos(zr), np.sin(ar)], axis=1)
    p = Patches(mf=mf, n_sky=n_sky, altitude=alt_a, azimuth=az_a, solid_angle=np.array(omega),
                direction=direction, row_height=rh, row_start=np.array(starts), row_count=np.array(counts),
                projected=np.array(proj))
    _PATCH_CACHE[mf] = p
    return p


# ── luminous efficacy (Perez 1990) ───────────────────────────────────────────

EPS_BINS = np.array([1.0, 1.065, 1.230, 1.500, 1.950, 2.800, 4.500, 6.200])
_GLOBAL = np.array([[96.63, -0.47, 11.50, -9.16], [107.54, 0.79, 1.79, -1.19], [98.73, 0.70, 4.40, -6.95],
                    [92.72, 0.56, 8.36, -8.31], [86.73, 0.98, 7.10, -10.94], [88.34, 1.39, 6.06, -7.60],
                    [78.63, 1.47, 4.93, -11.37], [99.65, 1.86, -4.46, -3.15]])
_DIRECT = np.array([[57.20, -4.55, -2.98, 117.12], [98.99, -3.46, -1.21, 12.38], [109.83, -4.90, -1.71, -8.81],
                    [110.34, -5.84, -1.99, -4.56], [106.36, -3.97, -1.75, -6.16], [107.19, -1.25, -1.51, -26.73],
                    [105.75, 0.77, -1.26, -34.44], [101.18, 1.58, -1.10, -8.29]])
_DIFFUSE = np.array([[97.24, -0.46, 12.00, -8.91], [107.22, 1.15, 0.59, -3.95], [104.97, 2.96, -5.53, -8.77],
                     [102.39, 5.59, -13.95, -13.90], [100.71, 5.94, -22.75, -23.74], [106.42, 3.83, -36.15, -28.83],
                     [141.88, 1.90, -53.24, -14.03], [152.23, 0.35, -45.27, -7.98]])


def air_mass(zenith_deg: np.ndarray) -> np.ndarray:
    """Kasten & Young (1989) relative optical air mass."""
    z = np.clip(np.asarray(zenith_deg, dtype=float), 0.0, 90.0)
    return 1.0 / (np.cos(np.radians(z)) + 0.50572 * (96.07995 - z) ** -1.6364)


def extraterrestrial_normal(day_of_year: np.ndarray) -> np.ndarray:
    return SOLAR_CONSTANT * (1.0 + 0.033 * np.cos(2 * np.pi * np.asarray(day_of_year, dtype=float) / 365.0))


def clearness_brightness(dni, dhi, zenith_deg, day_of_year) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Perez sky clearness epsilon, brightness delta and the 0..7 epsilon bin. Night/invalid -> bin 0."""
    dni = np.asarray(dni, dtype=float)
    dhi = np.asarray(dhi, dtype=float)
    z = np.radians(np.clip(np.asarray(zenith_deg, dtype=float), 0.0, 90.0))
    k = 1.041 * z ** 3
    with np.errstate(divide="ignore", invalid="ignore"):
        eps = ((dhi + dni) / dhi + k) / (1.0 + k)
    eps = np.where(dhi > 0, eps, np.where(dni > 0, 12.0, 1.0))
    eps = np.clip(np.nan_to_num(eps, nan=1.0), 1.0, 12.0)
    delta = dhi * air_mass(np.degrees(z)) / extraterrestrial_normal(day_of_year)
    delta = np.clip(np.nan_to_num(delta, nan=0.0), 0.0, 0.6)
    bins = np.clip(np.searchsorted(EPS_BINS, eps, side="right") - 1, 0, 7)
    return eps, delta, bins


def perez_efficacy(ghi, dni, dhi, zenith_deg, dew_point, day_of_year) -> dict[str, np.ndarray]:
    """Global, direct and diffuse luminous efficacy (lm/W) from Perez et al. (1990), clipped to a
    plausible 40..200 lm/W band so a corrupt input hour cannot produce absurd illuminance."""
    eps, delta, b = clearness_brightness(dni, dhi, zenith_deg, day_of_year)
    z = np.radians(np.clip(np.asarray(zenith_deg, dtype=float), 0.0, 90.0))
    w = np.exp(0.07 * np.nan_to_num(np.asarray(dew_point, dtype=float), nan=10.0) - 0.075)   # precipitable water, cm
    ld = np.log(np.maximum(delta, 1e-4))
    g, d, f = _GLOBAL[b], _DIRECT[b], _DIFFUSE[b]
    k_glob = g[:, 0] + g[:, 1] * w + g[:, 2] * np.cos(z) + g[:, 3] * ld
    k_dir = d[:, 0] + d[:, 1] * w + d[:, 2] * np.exp(5.73 * z - 5.0) + d[:, 3] * delta
    k_dif = f[:, 0] + f[:, 1] * w + f[:, 2] * np.cos(z) + f[:, 3] * ld
    return {"global": np.clip(k_glob, 40, 200), "direct": np.clip(k_dir, 0, 200), "diffuse": np.clip(k_dif, 40, 200)}


def perez_illuminance(weather, sun: dict | None = None) -> dict[str, np.ndarray]:
    """Global / direct-normal / diffuse illuminance (lux) for every hour from the weather's irradiance."""
    from .solar import sun_positions_for
    sun = sun or sun_positions_for(weather)
    d = weather.data
    ghi, dni, dhi = (np.nan_to_num(d[k], nan=0.0) for k in ("ghi", "dni", "dhi"))
    eff = perez_efficacy(ghi, dni, dhi, sun["zenith"], d["dew_point"], weather.day_of_year)
    up = sun["altitude"] > 0
    return {"global_illuminance": np.where(up, ghi * eff["global"], 0.0),
            "direct_illuminance": np.where(up, dni * eff["direct"], 0.0),
            "diffuse_illuminance": np.where(up, dhi * eff["diffuse"], 0.0)}


# ── sky luminance distributions ──────────────────────────────────────────────

# Perez 1993 all-weather coefficients: per epsilon bin, a1..a4, b1..b4, c1..c4, d1..d4, e1..e4.
PEREZ_LUMINANCE = np.array([
    [1.3525, -0.2576, -0.2690, -1.4366, -0.7670, 0.0007, 1.2734, -0.1233, 2.8000, 0.6004, 1.2375, 1.0000,
     1.8734, 0.6297, 0.9738, 0.2809, 0.0356, -0.1246, -0.5718, 0.9938],
    [-1.2219, -0.7730, 1.4148, 1.1016, -0.2054, 0.0367, -3.9128, 0.9156, 6.9750, 0.1774, 6.4477, -0.1239,
     -1.5798, -0.5081, -1.7812, 0.1080, 0.2624, 0.0672, -0.2190, -0.4285],
    [-1.1000, -0.2515, 0.8952, 0.0156, 0.2782, -0.1812, -4.5000, 1.1766, 24.7219, -13.0812, -37.7000, 34.8438,
     -5.0000, 1.5218, 3.9229, -2.6204, -0.0156, 0.1597, 0.4199, -0.5562],
    [-0.5484, -0.6654, -0.2672, 0.7117, 0.7234, -0.6219, -5.6812, 2.6297, 33.3389, -18.3000, -62.2500, 52.0781,
     -3.5000, 0.0016, 1.1477, 0.1062, 0.4659, -0.3296, -0.0876, -0.0329],
    [-0.6000, -0.3566, -2.5000, 2.3250, 0.2937, 0.0496, -5.6812, 1.8415, 21.0000, -4.7656, -21.5906, 7.2492,
     -3.5000, -0.1554, 1.4062, 0.3988, 0.0032, 0.0766, -0.0656, -0.1294],
    [-1.0156, -0.3670, 1.0078, 1.4051, 0.2875, -0.5328, -3.8500, 3.3750, 14.0000, -0.9999, -7.1406, 7.5469,
     -3.4000, -0.1078, -1.0750, 1.5702, -0.0672, 0.4016, 0.3017, -0.4844],
    [-1.0000, 0.0211, 0.5025, -0.5119, -0.3000, 0.1922, 0.7023, -1.6317, 19.0000, -5.0000, 1.2438, -1.9094,
     -4.0000, 0.0250, 0.3844, 0.2656, 1.0468, -0.3788, -2.4517, 1.4656],
    [-1.0500, 0.0289, 0.4260, 0.3590, -0.3250, 0.1156, 0.7781, 0.0025, 31.0625, -14.5000, -46.1148, 55.3750,
     -7.2312, 0.4050, 13.3500, 0.6234, 1.5000, -0.6426, 1.8564, 0.5636],
])


def perez_parameters(eps_bin: np.ndarray, delta: np.ndarray, zenith_deg: np.ndarray) -> np.ndarray:
    """(N, 5) Perez a..e for each hour."""
    z = np.radians(np.asarray(zenith_deg, dtype=float))
    delta = np.asarray(delta, dtype=float)
    c = PEREZ_LUMINANCE[np.asarray(eps_bin, dtype=int)].reshape(-1, 5, 4)
    z = np.broadcast_to(z, delta.shape).reshape(-1)
    dl = delta.reshape(-1)
    params = c[:, :, 0] + c[:, :, 1] * z[:, None] + dl[:, None] * (c[:, :, 2] + c[:, :, 3] * z[:, None])
    first = np.asarray(eps_bin).reshape(-1) == 0
    if first.any():
        cc, dd = c[first, 2], c[first, 3]
        zf, df = z[first], dl[first]
        base = np.maximum(df * (cc[:, 0] + cc[:, 1] * zf), 0.0)
        params[first, 2] = np.exp(base ** cc[:, 2]) - cc[:, 3]
        params[first, 3] = -np.exp(df * (dd[:, 0] + dd[:, 1] * zf)) + dd[:, 2] + df * dd[:, 3]
    return params


def _gradation_indicatrix(params: np.ndarray, elem_dirs: np.ndarray, sun_dirs: np.ndarray, cie: bool) -> np.ndarray:
    """Relative luminance (hours, elements). params (H, 5); elem_dirs (E, 3); sun_dirs (H, 3)."""
    cos_zeta = np.clip(elem_dirs[:, 2], 0.01, 1.0)[None, :]
    cos_gamma = np.clip(sun_dirs @ elem_dirs.T, -1.0, 1.0)
    gamma = np.arccos(cos_gamma)
    a, b, c, d, e = (params[:, i:i + 1] for i in range(5))
    grad = 1.0 + a * np.exp(b / cos_zeta)
    if cie:
        ind = 1.0 + c * (np.exp(d * gamma) - np.exp(d * np.pi / 2)) + e * cos_gamma ** 2
    else:
        ind = 1.0 + c * np.exp(d * gamma) + e * cos_gamma ** 2
    return grad * ind


CIE_SKY_TYPES = {   # ISO 15469 / CIE S 011 a, b, c, d, e
    1: (4.0, -0.70, 0, -1.0, 0.00), 2: (4.0, -0.70, 2, -1.5, 0.15), 3: (1.1, -0.8, 0, -1.0, 0.00),
    4: (1.1, -0.8, 2, -1.5, 0.15), 5: (0.0, -1.0, 0, -1.0, 0.00), 6: (0.0, -1.0, 2, -1.5, 0.15),
    7: (0.0, -1.0, 5, -2.5, 0.30), 8: (0.0, -1.0, 10, -3.0, 0.45), 9: (-1.0, -0.55, 2, -1.5, 0.15),
    10: (-1.0, -0.55, 5, -2.5, 0.30), 11: (-1.0, -0.55, 10, -3.0, 0.45), 12: (-1.0, -0.32, 10, -3.0, 0.45),
    13: (-1.0, -0.32, 16, -3.0, 0.30), 14: (-1.0, -0.15, 16, -3.0, 0.30), 15: (-1.0, -0.15, 24, -2.8, 0.15),
}


def _normalise(rel: np.ndarray, p: Patches, horizontal: np.ndarray) -> np.ndarray:
    """Scale relative luminance (H, n_sky) so that the horizontal illuminance of the patch sky, each
    patch uniformly bright, equals ``horizontal`` (H,): sum(L * integral of sin(alt) d(omega))."""
    rel = np.maximum(np.nan_to_num(rel, nan=0.0, posinf=0.0), 0.0)
    w = p.projected
    integral = rel @ w
    bad = integral <= 1e-12
    if bad.any():                     # degenerate distribution: fall back to the CIE overcast shape
        rel[bad] = (1 + 2 * np.sin(np.radians(p.altitude[:p.n_sky])))[None, :] / 3.0
        integral = rel @ w
    return rel * (np.asarray(horizontal, dtype=float) / integral)[:, None]


def cie_overcast(p: Patches, horizontal: float = 1.0) -> np.ndarray:
    """Patch luminance of the CIE overcast sky giving ``horizontal`` unobstructed illuminance (n_sky,)."""
    rel = ((1 + 2 * np.sin(np.radians(p.altitude[:p.n_sky]))) / 3.0)[None, :]
    return _normalise(rel, p, np.array([horizontal]))[0]


def uniform_sky(p: Patches, horizontal: float = 1.0) -> np.ndarray:
    return _normalise(np.ones((1, p.n_sky)), p, np.array([horizontal]))[0]


def cie_standard_sky(p: Patches, sky_type: int, sun_alt: float, sun_az: float, horizontal: float = 1.0) -> np.ndarray:
    """Diffuse patch luminance of a CIE general standard sky (types 1-15) normalised to ``horizontal``
    diffuse illuminance. The sun itself is not included."""
    if sky_type not in CIE_SKY_TYPES:
        raise ValueError("CIE sky type must be 1..15")
    from .solar import direction_vector
    s = direction_vector(np.array([sun_alt]), np.array([sun_az]))
    params = np.array([CIE_SKY_TYPES[sky_type]], dtype=float)
    rel = _gradation_indicatrix(params, p.direction[:p.n_sky], s, cie=True)
    return _normalise(rel, p, np.array([horizontal]))[0]


@dataclass
class SkyMatrix:
    """Hourly skies for a whole year (or a subset of hours)."""
    patches: Patches
    hours: np.ndarray              # indices into the 8760 year
    sky: np.ndarray                # (len(hours), n_patches) luminance cd/m2 (or radiance W/m2/sr); last = ground
    sun_dir: np.ndarray            # (len(hours), 3) unit vector to the sun (model axes)
    sun_normal: np.ndarray         # (len(hours),) direct-normal illuminance lux (or W/m2); 0 when down
    sun_altitude: np.ndarray
    global_horizontal: np.ndarray  # (len(hours),)
    diffuse_horizontal: np.ndarray
    kind: str                      # "visible" | "solar"
    ground_reflectance: float

    def sun_patch_sky(self) -> np.ndarray:
        """The sun as patch luminance (H, n): its direct-normal value spread over the patch that holds
        it, so that a daylight coefficient row reproduces it on average. Used for the sun's
        interreflected contribution only."""
        p = self.patches
        out = np.zeros((len(self.hours), p.n))
        up = self.sun_normal > 0
        if up.any():
            idx = p.index(self.sun_dir[up])
            out[np.flatnonzero(up), idx] = self.sun_normal[up] / p.solid_angle[idx]
        return out


def sky_matrix(weather, mf: int = 1, kind: str = "visible", hours: np.ndarray | None = None,
               north_deg: float = 0.0, ground_reflectance: float = 0.2) -> SkyMatrix:
    """Perez all-weather sky for each hour. ``kind="visible"`` uses the weather's illuminance
    (lux / cd/m2), ``"solar"`` its irradiance (W/m2 / W/m2/sr)."""
    if kind not in ("visible", "solar"):
        raise ValueError("kind must be 'visible' or 'solar'")
    if not 0.0 <= ground_reflectance <= 1.0:
        raise ValueError("ground_reflectance must be 0..1")
    from .solar import direction_vector, sun_positions_for
    p = patches(mf)
    sun = sun_positions_for(weather)
    hrs = np.arange(len(weather.month)) if hours is None else np.asarray(hours, dtype=int)
    d = weather.data
    alt = sun["altitude"][hrs]
    up = alt > 0
    if kind == "visible":
        dh = np.nan_to_num(d["diffuse_illuminance"][hrs], nan=0.0)
        dn = np.nan_to_num(d["direct_illuminance"][hrs], nan=0.0)
    else:
        dh = np.nan_to_num(d["dhi"][hrs], nan=0.0)
        dn = np.nan_to_num(d["dni"][hrs], nan=0.0)
    dh = np.where(up, np.maximum(dh, 0.0), 0.0)
    dn = np.where(up, np.maximum(dn, 0.0), 0.0)
    sun_dir = direction_vector(alt, sun["azimuth"][hrs], north_deg)
    gh = dh + dn * np.sin(np.radians(np.maximum(alt, 0.0)))
    sky = np.zeros((len(hrs), p.n))
    sel = np.flatnonzero(up & (dh > 0))
    # The Perez shape depends on the irradiance (not the illuminance) of the hour.
    eps, delta, bins = clearness_brightness(np.nan_to_num(d["dni"][hrs]), np.nan_to_num(d["dhi"][hrs]),
                                            sun["zenith"][hrs], weather.day_of_year[hrs])
    elem = p.direction[:p.n_sky].copy()
    if north_deg:
        # patch directions are model-axis; the sun vector is already rotated, so patches stay put.
        pass
    for chunk in np.array_split(sel, max(1, len(sel) // 1500 + 1)):
        if chunk.size == 0:
            continue
        params = perez_parameters(bins[chunk], delta[chunk], sun["zenith"][hrs][chunk])
        rel = _gradation_indicatrix(params, elem, sun_dir[chunk], cie=False)
        sky[chunk, :p.n_sky] = _normalise(rel, p, dh[chunk])
    sky[:, p.n_sky] = ground_reflectance * gh / math.pi
    return SkyMatrix(patches=p, hours=hrs, sky=sky, sun_dir=sun_dir, sun_normal=dn, sun_altitude=alt,
                     global_horizontal=gh, diffuse_horizontal=dh, kind=kind, ground_reflectance=ground_reflectance)


def single_sky(p: Patches, diffuse_horizontal: float, ground_global: float, ground_reflectance: float,
               shape: str = "cie_overcast", sun_alt: float = 0.0, sun_az: float = 0.0) -> np.ndarray:
    """One sky vector (n,) including the ground patch, for point-in-time studies."""
    if shape == "cie_overcast":
        v = cie_overcast(p, diffuse_horizontal)
    elif shape == "uniform":
        v = uniform_sky(p, diffuse_horizontal)
    elif shape.startswith("cie_"):
        v = cie_standard_sky(p, int(shape[4:]), sun_alt, sun_az, diffuse_horizontal)
    else:
        raise ValueError("sky shape must be 'cie_overcast', 'uniform' or 'cie_1'..'cie_15'")
    return np.concatenate([v, [ground_reflectance * ground_global / math.pi]])
