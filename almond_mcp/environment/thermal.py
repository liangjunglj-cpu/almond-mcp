"""Hourly zone thermal model: ISO 13790:2008 simple hourly method (5R1C, Annex C).

Each zone is one air node, one surface node and one thermal-mass node, joined by five
conductances (ventilation, windows, surface-to-mass, mass-to-outside, air-to-surface) and one
capacitance. The equations are integrated with ISO 13790's Crank-Nicolson step; the heating /
cooling need comes from the standard's linear "10 W/m2 test" (C.4), so it is exact for the model.

Inputs that matter most, and what is assumed when they are not given, are reported with every result:
U-values and thermal mass (from a construction preset), infiltration and ventilation, internal gains
and their schedule, set-points (none = free-running). Solar gains are not estimated from a
transposition model: they are ray-traced on each window and wall of the actual geometry (with every
overhang, fin and neighbouring building in the scene), from the same EPW year.

Scope: a design-stage model for comparing options and judging comfort risk, not a replacement for a
detailed simulation (EnergyPlus) in compliance work. No moisture balance (indoor humidity = outdoor
absolute humidity), no interzone heat flow (zone boundaries are adiabatic), constant air density.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import comfort
from .epw import HOURS
from .scene import pane_faces, principal_normal

H_IS = 3.45          # W/m2K  air node to surface node, per m2 of A_t
H_MS = 9.1           # W/m2K  surface node to mass node, per m2 of A_m
LAMBDA_AT = 4.5      # A_t = 4.5 A_f
RHO_CA = 1200.0      # J/m3K  volumetric heat capacity of air
R_SE = 0.04          # m2K/W  external surface resistance
H_R_EXT = 4.5        # W/m2K  external radiative coefficient (5 x emissivity 0.9)
DT_SKY = 11.0        # K      mean air-to-sky temperature difference (ISO 13790 11.4.6)
F_W = 0.9            # non-normal incidence correction on g (ISO 13790 11.4.2)

MASS_CLASSES = {     # ISO 13790 Table 12: (A_m / A_f, C_m / A_f in J/m2K)
    "very_light": (2.5, 80_000.0), "light": (2.5, 110_000.0), "medium": (2.5, 165_000.0),
    "heavy": (3.0, 260_000.0), "very_heavy": (3.5, 370_000.0),
}

CONSTRUCTIONS = {    # U-values W/m2K, external solar absorptance, thermal mass class
    "insulated": {"wall": 0.25, "roof": 0.18, "ground_floor": 0.25, "exposed_floor": 0.25,
                  "absorptance_wall": 0.6, "absorptance_roof": 0.7, "mass": "medium"},
    "typical": {"wall": 0.5, "roof": 0.35, "ground_floor": 0.45, "exposed_floor": 0.45,
                "absorptance_wall": 0.6, "absorptance_roof": 0.7, "mass": "medium"},
    "uninsulated_masonry": {"wall": 1.8, "roof": 2.2, "ground_floor": 1.2, "exposed_floor": 1.5,
                            "absorptance_wall": 0.6, "absorptance_roof": 0.75, "mass": "heavy"},
    "lightweight_tropical": {"wall": 2.5, "roof": 1.5, "ground_floor": 1.5, "exposed_floor": 2.0,
                             "absorptance_wall": 0.5, "absorptance_roof": 0.6, "mass": "light"},
}

SCHEDULES = ("office", "school", "residential", "always")
# Fresh-air supply when occupied, l/s per m2 of floor - indicative EN 16798-1:2019 Category II values
# (offices 7 l/s per person at 10 m2 + 0.7 l/s m2 for a low-polluting building; dwellings ~0.42).
# Per floor area, not per volume, so a double-height room is not ventilated twice as hard.
VENTILATION_L_S_M2 = {"office": 1.4, "school": 4.0, "residential": 0.42, "always": 0.42}


@dataclass
class Surface:
    kind: str                       # wall | roof | ground_floor | exposed_floor | window | adiabatic
    area: float                     # m2 (walls net of windows)
    normal: tuple[float, float, float]
    u_value: float = 0.0
    absorptance: float = 0.6
    g_value: float = 0.0            # windows: total solar energy transmittance at normal incidence
    frame_fraction: float = 0.0     # windows
    name: str = ""
    samples: np.ndarray | None = None       # (k, 3) points on the surface for solar ray tracing
    irradiance: np.ndarray | None = None    # (8760,) W/m2 incident on the outside, filled by solar_on_surfaces

    @property
    def tilt_cos(self) -> float:
        return float(self.normal[2])


@dataclass
class Zone:
    name: str
    floor_area: float
    volume: float
    surfaces: list[Surface] = field(default_factory=list)
    source: dict = field(default_factory=dict)

    def validate(self) -> None:
        if not self.floor_area > 0:
            raise ValueError(f"Zone {self.name}: floor area must be positive (is the zone closed and does it have a floor?)")
        if not self.volume > 0:
            raise ValueError(f"Zone {self.name}: volume must be positive (is the zone a closed volume?)")
        if self.floor_area < 2.0:
            raise ValueError(f"Zone {self.name}: {self.floor_area:.2f} m2 of floor is not a room - pass closed room "
                             "volumes (one per zone), not walls or slabs")
        width = self.source.get("plan_min_width_m")
        if width is not None and width < 1.0:
            raise ValueError(f"Zone {self.name}: only {width:.2f} m wide in plan - pass closed room volumes, not walls or slabs")
        mean_h = self.volume / self.floor_area
        if not 1.5 <= mean_h <= 50:
            raise ValueError(f"Zone {self.name}: mean height {mean_h:.2f} m is implausible - check units and that the zone is one storey or one space")

    def areas(self) -> dict:
        out: dict[str, float] = {}
        for s in self.surfaces:
            out[s.kind] = round(out.get(s.kind, 0.0) + s.area, 3)
        return out


@dataclass
class Settings:
    construction: str = "typical"
    u_values: dict = field(default_factory=dict)          # overrides per surface kind
    mass: str | None = None                               # overrides the construction's class
    infiltration_ach: float = 0.3
    ventilation_ach: float | None = None                  # fresh air when occupied; None = per floor area below
    ventilation_l_s_m2: float | None = None               # None = by schedule (VENTILATION_L_S_M2)
    heating_setpoint: float | None = 20.0
    cooling_setpoint: float | None = 26.0
    setback: bool = True                                  # set-points only in occupied hours
    schedule: str = "office"
    occupancy_w_m2: float = 7.5                           # sensible heat from people at full occupancy
    equipment_w_m2: float = 10.0
    lighting_w_m2: float = 8.0
    natural_ventilation_ach: float = 0.0                  # extra air change when windows open
    natural_ventilation_on_above: float = 24.0            # indoor air degC
    natural_ventilation_min_outdoor: float = 12.0
    shading_g_factor: float = 1.0                         # g multiplier when movable shading is down
    shading_on_above_w_m2: float = 300.0                  # incident on the window
    shading_min_outdoor_c: float | None = None            # only when the day's mean outdoor temp is above (summer mode)
    window_u: float | None = None
    window_g: float | None = None
    frame_fraction: float = 0.2
    clothing_summer: float = 0.5
    clothing_winter: float = 1.0
    metabolic_rate: float = 1.2
    air_speed: float = 0.1

    def validate(self) -> None:
        if self.construction not in CONSTRUCTIONS:
            raise ValueError(f"construction must be one of {', '.join(CONSTRUCTIONS)}")
        if self.schedule not in SCHEDULES:
            raise ValueError(f"schedule must be one of {', '.join(SCHEDULES)}")
        if self.mass is not None and self.mass not in MASS_CLASSES:
            raise ValueError(f"mass must be one of {', '.join(MASS_CLASSES)}")
        for k, v in self.u_values.items():
            if k not in ("wall", "roof", "ground_floor", "exposed_floor", "window"):
                raise ValueError(f"u_values key '{k}' is not a surface kind")
            if not 0.05 <= float(v) <= 8.0:
                raise ValueError(f"U-value {v} for {k} is outside 0.05..8 W/m2K")
        if (self.heating_setpoint is not None and self.cooling_setpoint is not None
                and self.heating_setpoint >= self.cooling_setpoint):
            raise ValueError("heating set-point must be below the cooling set-point")
        if (self.infiltration_ach < 0 or (self.ventilation_ach or 0) < 0 or (self.ventilation_l_s_m2 or 0) < 0
                or self.natural_ventilation_ach < 0):
            raise ValueError("air change rates cannot be negative")
        if not 0.0 <= self.shading_g_factor <= 1.0:
            raise ValueError("shading_g_factor must be 0..1")
        if not 0.0 <= self.frame_fraction < 1.0:
            raise ValueError("frame_fraction must be 0..1")


def occupancy(weather, schedule: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(occupancy fraction, equipment fraction, lighting fraction) per hour."""
    hod = weather.hour_of_day
    wd = weather.weekday()
    workday = wd < 5
    if schedule == "office":
        occ = np.where(workday & (hod >= 8) & (hod < 18), 1.0, 0.0)
        occ = np.where(workday & (hod == 12), 0.5, occ)
        equip = np.where(occ > 0, 0.9, 0.2)
        light = np.where(occ > 0, 0.9, 0.05)
    elif schedule == "school":
        term = ~np.isin(weather.month, [7, 8])
        occ = np.where(workday & term & (hod >= 8) & (hod < 16), 1.0, 0.0)
        equip = np.where(occ > 0, 0.8, 0.1)
        light = np.where(occ > 0, 0.8, 0.0)
    elif schedule == "residential":
        occ = np.where((hod < 8) | (hod >= 18), 1.0, np.where(workday, 0.2, 0.7))
        equip = np.where((hod >= 6) & (hod < 22), 0.5, 0.2)
        light = np.where((hod >= 18) & (hod < 23), 0.8, np.where((hod >= 6) & (hod < 8), 0.4, 0.05))
    elif schedule == "always":
        occ = np.ones(HOURS)
        equip = np.ones(HOURS)
        light = np.ones(HOURS) * 0.5
    else:
        raise ValueError(f"Unknown schedule '{schedule}'")
    return occ, equip, light


def apply_construction(zone: Zone, st: Settings, glazing_props: dict | None = None) -> list[str]:
    """Fill U-values / absorptance / g from the construction preset and overrides. Returns notes."""
    c = CONSTRUCTIONS[st.construction]
    notes = []
    for s in zone.surfaces:
        if s.kind == "window":
            u = st.u_values.get("window", st.window_u if st.window_u is not None else s.u_value or 2.0)
            s.u_value = float(u)
            s.g_value = float(st.window_g if st.window_g is not None else (s.g_value or 0.5))
            s.frame_fraction = st.frame_fraction
        elif s.kind in ("wall", "roof", "ground_floor", "exposed_floor"):
            s.u_value = float(st.u_values.get(s.kind, c[s.kind]))
            s.absorptance = c["absorptance_roof"] if s.kind == "roof" else c["absorptance_wall"]
    if st.window_g is None and any(s.kind == "window" for s in zone.surfaces):
        notes.append("window g-values come from the glazing material (or 0.5 when it has none)")
    return notes


def solar_gains(zone: Zone, weather, st: Settings) -> tuple[np.ndarray, np.ndarray, dict]:
    """(solar gain W (8760,), window shading state (8760,) bool, breakdown) for ISO 13790."""
    phi = np.zeros(HOURS)
    shaded = np.zeros(HOURS, dtype=bool)
    win_total = np.zeros(HOURS)
    opaque_total = np.zeros(HOURS)
    for s in zone.surfaces:
        if s.irradiance is None or s.kind in ("adiabatic", "ground_floor"):
            continue
        I = np.asarray(s.irradiance, dtype=float)
        if s.kind == "window":
            g = F_W * s.g_value
            down = I > st.shading_on_above_w_m2 if st.shading_g_factor < 1.0 else np.zeros(HOURS, dtype=bool)
            if st.shading_min_outdoor_c is not None:
                down = down & (np.repeat(weather.daily_mean("dry_bulb"), 24) > st.shading_min_outdoor_c)
            shaded |= down
            gain = np.where(down, g * st.shading_g_factor, g) * (1 - s.frame_fraction) * s.area * I
            win_total += gain
        else:
            f_r = 0.5 * (1 + s.tilt_cos)           # view factor to the sky
            gain = s.absorptance * R_SE * s.u_value * s.area * I - f_r * R_SE * s.u_value * s.area * H_R_EXT * DT_SKY
            opaque_total += gain
        phi += gain
    return phi, shaded, {"windows_kwh": float(win_total.sum() / 1000), "opaque_kwh": float(opaque_total.sum() / 1000)}


def simulate(zone: Zone, weather, st: Settings, warmup_days: int = 30) -> dict:
    """Run the 5R1C model for one year. Returns hourly arrays and annual figures."""
    zone.validate()
    st.validate()
    mass = st.mass or CONSTRUCTIONS[st.construction]["mass"]
    am_ratio, cm_per = MASS_CLASSES[mass]
    Af = zone.floor_area
    A_m = am_ratio * Af
    C_m = cm_per * Af
    A_t = LAMBDA_AT * Af
    H_tr_is = H_IS * A_t
    H_tr_ms = H_MS * A_m
    H_tr_w = sum(s.u_value * s.area for s in zone.surfaces if s.kind == "window")
    H_op = sum(s.u_value * s.area for s in zone.surfaces if s.kind in ("wall", "roof", "exposed_floor"))
    H_gr = sum(s.u_value * s.area for s in zone.surfaces if s.kind == "ground_floor")
    H_op_total = H_op + H_gr
    if H_op_total > 0:
        if 1.0 / H_op_total - 1.0 / H_tr_ms <= 0:
            raise ValueError(f"Zone {zone.name}: its opaque envelope conducts {H_op_total:.0f} W/K, more than its thermal "
                             f"mass can exchange ({H_tr_ms:.0f} W/K) - the zone is too small or too thin for the model "
                             "(is it a wall or a slab rather than a room?)")
        H_tr_em = 1.0 / (1.0 / H_op_total - 1.0 / H_tr_ms)
    else:
        H_tr_em = 1e-6
    t_out = np.asarray(weather["dry_bulb"], dtype=float)
    # ground-coupled floors see the monthly ground temperature, folded into an equivalent outdoor temperature
    g = weather.ground_temperatures[0]["monthly_c"] if weather.ground_temperatures else None
    t_ground = np.asarray(g, dtype=float)[weather.month - 1] if g is not None else t_out
    t_e = (H_op * t_out + H_gr * t_ground) / H_op_total if H_op_total > 0 else t_out
    occ, equip, light = occupancy(weather, st.schedule)
    phi_int = Af * (st.occupancy_w_m2 * occ + st.equipment_w_m2 * equip + st.lighting_w_m2 * light)
    phi_sol, shaded, sol_info = solar_gains(zone, weather, st)
    V = zone.volume
    if st.ventilation_ach is not None:
        vent_ach = float(st.ventilation_ach)
        vent_rate = vent_ach * V / 3.6 / Af
    else:
        vent_rate = st.ventilation_l_s_m2 if st.ventilation_l_s_m2 is not None else VENTILATION_L_S_M2[st.schedule]
        vent_ach = vent_rate * Af * 3.6 / V                      # l/s m2 -> air changes per hour
    base_ach = st.infiltration_ach + np.where(occ > 0, vent_ach, 0.0)
    nv_ach = st.natural_ventilation_ach

    occupied = occ > 0
    heat_sp = st.heating_setpoint
    cool_sp = st.cooling_setpoint

    t_air = np.zeros(HOURS)
    t_s = np.zeros(HOURS)
    t_m_out = np.zeros(HOURS)
    q_hc = np.zeros(HOURS)
    vent_open = np.zeros(HOURS, dtype=bool)

    # ISO 13790 C.2 split of internal and solar gains
    phi_ia = 0.5 * phi_int
    f_m = A_m / A_t
    f_st = 1.0 - A_m / A_t - H_tr_w / (9.1 * A_t)
    phi_m = f_m * (0.5 * phi_int + phi_sol)
    phi_st = f_st * (0.5 * phi_int + phi_sol)

    t_m_prev = float(np.mean(t_out[:24 * 7])) if warmup_days else 20.0
    order = list(range(HOURS - warmup_days * 24, HOURS)) + list(range(HOURS))
    record_from = warmup_days * 24
    cm3600 = C_m / 3600.0

    def step(i: int, h_ve: float, phi_hc: float, t_m_p: float) -> tuple[float, float, float, float]:
        te = t_e[i]
        h1 = 1.0 / (1.0 / h_ve + 1.0 / H_tr_is)
        h2 = h1 + H_tr_w
        h3 = 1.0 / (1.0 / h2 + 1.0 / H_tr_ms)
        phi_mtot = (phi_m[i] + H_tr_em * te + h3 * (phi_st[i] + H_tr_w * t_out[i]
                    + h1 * ((phi_ia[i] + phi_hc) / h_ve + t_out[i])) / h2)
        tm = (t_m_p * (cm3600 - 0.5 * (h3 + H_tr_em)) + phi_mtot) / (cm3600 + 0.5 * (h3 + H_tr_em))
        tm_avg = 0.5 * (tm + t_m_p)
        ts = (H_tr_ms * tm_avg + phi_st[i] + H_tr_w * t_out[i] + h1 * (t_out[i] + (phi_ia[i] + phi_hc) / h_ve)) / (H_tr_ms + H_tr_w + h1)
        ta = (H_tr_is * ts + h_ve * t_out[i] + phi_ia[i] + phi_hc) / (H_tr_is + h_ve)
        return ta, ts, tm, tm_avg

    for n, i in enumerate(order):
        ach = base_ach[i]
        h_ve = max(RHO_CA * ach * V / 3600.0, 1e-3)
        ta0, ts0, tm0, tma0 = step(i, h_ve, 0.0, t_m_prev)
        opened = False
        if nv_ach > 0 and ta0 > st.natural_ventilation_on_above and st.natural_ventilation_min_outdoor <= t_out[i] < ta0 - 1.0:
            h_ve_nv = RHO_CA * (ach + nv_ach) * V / 3600.0
            ta_nv, ts_nv, tm_nv, tma_nv = step(i, h_ve_nv, 0.0, t_m_prev)
            # do not ventilate below the heating set-point
            if heat_sp is None or ta_nv >= heat_sp:
                h_ve, (ta0, ts0, tm0, tma0), opened = h_ve_nv, (ta_nv, ts_nv, tm_nv, tma_nv), True
        hs = heat_sp if heat_sp is not None and (occupied[i] or not st.setback) else None
        cs = cool_sp if cool_sp is not None and (occupied[i] or not st.setback) else None
        phi = 0.0
        ta, ts, tm, tma = ta0, ts0, tm0, tma0
        target = None
        if hs is not None and ta0 < hs:
            target = hs
        elif cs is not None and ta0 > cs:
            target = cs
        if target is not None:
            phi10 = 10.0 * Af
            ta10 = step(i, h_ve, phi10, t_m_prev)[0]
            phi = phi10 * (target - ta0) / (ta10 - ta0) if ta10 != ta0 else 0.0
            ta, ts, tm, tma = step(i, h_ve, phi, t_m_prev)
        t_m_prev = tm
        if n >= record_from:
            t_air[i], t_s[i], t_m_out[i], q_hc[i], vent_open[i] = ta, ts, tma, phi, opened
    t_op = 0.3 * t_air + 0.7 * t_s
    heating = np.maximum(q_hc, 0.0)
    cooling = np.maximum(-q_hc, 0.0)
    return {
        "t_air": t_air, "t_surface": t_s, "t_mass": t_m_out, "t_op": t_op, "heating_w": heating, "cooling_w": cooling,
        "solar_w": phi_sol, "internal_w": phi_int, "occupied": occupied, "window_shading": shaded,
        "natural_ventilation": vent_open,
        "model": {"ventilation_l_s_m2_occupied": round(float(vent_rate), 3), "infiltration_ach": st.infiltration_ach,
                  "H_ve_base_w_k": round(float(RHO_CA * base_ach.mean() * V / 3600.0), 2), "H_tr_w_w_k": round(H_tr_w, 2),
                  "H_tr_op_w_k": round(H_op, 2), "H_ground_w_k": round(H_gr, 2), "H_tr_em_w_k": round(H_tr_em, 2),
                  "H_tr_ms_w_k": round(H_tr_ms, 2), "H_tr_is_w_k": round(H_tr_is, 2), "C_m_mj_k": round(C_m / 1e6, 2),
                  "mass_class": mass, "solar": sol_info},
    }


def summarize(zone: Zone, res: dict, weather, st: Settings) -> dict:
    Af = zone.floor_area
    occ = res["occupied"]
    t_op = res["t_op"]
    out = {
        "zone": zone.name, "floor_area_m2": round(Af, 2), "volume_m3": round(zone.volume, 2), "areas_m2": zone.areas(),
        "heating_kwh": round(float(res["heating_w"].sum() / 1000), 1),
        "cooling_kwh": round(float(res["cooling_w"].sum() / 1000), 1),
        "heating_kwh_m2": round(float(res["heating_w"].sum() / 1000 / Af), 1),
        "cooling_kwh_m2": round(float(res["cooling_w"].sum() / 1000 / Af), 1),
        "peak_heating_w_m2": round(float(res["heating_w"].max() / Af), 1),
        "peak_cooling_w_m2": round(float(res["cooling_w"].max() / Af), 1),
        "solar_gain_kwh_m2": round(float(np.maximum(res["solar_w"], 0).sum() / 1000 / Af), 1),
        "internal_gain_kwh_m2": round(float(res["internal_w"].sum() / 1000 / Af), 1),
        "operative_temperature_c": {"min": round(float(t_op.min()), 1), "mean": round(float(t_op.mean()), 1),
                                    "max": round(float(t_op.max()), 1),
                                    "occupied_mean": round(float(t_op[occ].mean()), 1) if occ.any() else None},
        "occupied_hours": int(occ.sum()),
        "hours_above_26c_occupied": int((t_op[occ] > 26).sum()),
        "hours_above_28c_occupied": int((t_op[occ] > 28).sum()),
        "natural_ventilation_hours": int(res["natural_ventilation"].sum()),
        "window_shading_hours": int(res["window_shading"].sum()),
        "model": res["model"],
    }
    daily = weather.daily_mean("dry_bulb")
    t_rm = comfort.running_mean_outdoor(daily, 0.8)
    free_running = st.heating_setpoint is None and st.cooling_setpoint is None
    if occ.any():
        a = comfort.adaptive_ashrae55(t_op, t_rm, st.air_speed)
        e = comfort.adaptive_en16798(t_op, t_rm, "II")
        app = a["applicable"] & occ
        out["adaptive_ashrae55"] = {
            "comfortable_80_pct": round(100 * float(a["comfortable_80"][occ].mean()), 1),
            "too_warm_pct": round(100 * float((a["status_80"][occ] > 0).mean()), 1),
            "too_cool_pct": round(100 * float((a["status_80"][occ] < 0).mean()), 1),
            "applicable_pct_of_occupied": round(100 * float(app.sum() / occ.sum()), 1),
            "note": "valid for occupant-controlled, naturally conditioned spaces" + ("" if free_running else
                    " - this zone has set-points, so treat as indicative"),
        }
        out["adaptive_en16798_cat_ii"] = {
            "comfortable_pct": round(100 * float(e["comfortable"][occ].mean()), 1),
            "too_warm_pct": round(100 * float((e["status"][occ] > 0).mean()), 1),
            "too_cool_pct": round(100 * float((e["status"][occ] < 0).mean()), 1),
        }
        out["tm52"] = comfort.tm52(t_op, t_rm, occ, weather.month)
        # PMV with indoor air humidity equal to the outdoor absolute humidity (no moisture model)
        w_out = comfort.humidity_ratio(weather["dry_bulb"], weather["rel_humidity"], weather["pressure"])
        rh_in = np.clip(comfort.rh_from_humidity_ratio(res["t_air"], w_out, weather["pressure"]), 0, 100)
        clo = np.where(np.repeat(t_rm, 24) > 15.0, st.clothing_summer, st.clothing_winter)
        t_r = np.clip(2 * t_op - res["t_air"], -20, 60)          # mean radiant from operative (0.5/0.5)
        pm = comfort.pmv_ppd(res["t_air"][occ], t_r[occ], st.air_speed, rh_in[occ], st.metabolic_rate, clo[occ])
        pmv = pm["pmv"]
        out["pmv"] = {"mean": round(float(pmv.mean()), 2), "within_0_5_pct": round(100 * float((np.abs(pmv) <= 0.5).mean()), 1),
                      "warm_gt_0_5_pct": round(100 * float((pmv > 0.5).mean()), 1),
                      "cool_lt_minus_0_5_pct": round(100 * float((pmv < -0.5).mean()), 1),
                      "mean_ppd": round(float(pm["ppd"].mean()), 1),
                      "indoor_rh_mean": round(float(rh_in[occ].mean()), 1),
                      "assumptions": f"met {st.metabolic_rate}, clo {st.clothing_summer}/{st.clothing_winter} (warm/cool season), air speed {st.air_speed} m/s"}
    return out


# ── zones from geometry ──────────────────────────────────────────────────────

def _surface_samples(tri_pts: np.ndarray, normal: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """n points spread over a set of coplanar triangles (area-weighted), offset outward 1 cm."""
    a, b, c = tri_pts[:, 0], tri_pts[:, 1], tri_pts[:, 2]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    if area.sum() <= 0:
        return (a.mean(axis=0) + normal * 0.01)[None]
    pick = rng.choice(len(a), size=n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    pts = (1 - s)[:, None] * a[pick] + (s * (1 - r2))[:, None] * b[pick] + (s * r2)[:, None] * c[pick]
    return pts + normal * 0.01


def _clip_triangles_to_box(tris: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """The parts of triangles (k, 3, 3) inside an axis-aligned box, re-triangulated (Sutherland-Hodgman)."""
    out = []
    for tri in tris:
        poly = [p for p in tri]
        for axis in range(3):
            for bound, keep_above in ((lo[axis], True), (hi[axis], False)):
                if not poly:
                    break
                clipped = []
                for i in range(len(poly)):
                    p, q = poly[i], poly[(i + 1) % len(poly)]
                    pin = p[axis] >= bound if keep_above else p[axis] <= bound
                    qin = q[axis] >= bound if keep_above else q[axis] <= bound
                    if pin:
                        clipped.append(p)
                    if pin != qin:
                        t = (bound - p[axis]) / (q[axis] - p[axis])
                        clipped.append(p + t * (q - p))
                poly = clipped
        for i in range(1, len(poly) - 1):
            out.append([poly[0], poly[i], poly[i + 1]])
    return np.asarray(out, dtype=float).reshape(-1, 3, 3)


def zone_from_mesh(name: str, vertices: np.ndarray, triangles: np.ndarray, windows: list[dict],
                   other_zones: list[tuple[np.ndarray, np.ndarray]] | None = None, ground_z: float | None = None,
                   samples_per_surface: int = 9, seed: int = 0, window_tolerance: float = 0.3) -> Zone:
    """A Zone from a closed triangle mesh (metres). ``windows``: [{"vertices", "triangles", "name",
    "g_value", "u_value"}] - glazing parallel to a zone face and within ``window_tolerance`` of it (set
    back in the wall depth) is subtracted from that face, clipped to the zone's extent. Faces shared
    with ``other_zones`` are adiabatic; faces facing down at the lowest level (or at ``ground_z``) are
    ground floors."""
    v = np.asarray(vertices, dtype=float)
    t = np.asarray(triangles, dtype=np.int64)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    keep = area > 1e-9
    a, b, c, cr, area = a[keep], b[keep], c[keep], cr[keep], area[keep]
    normal = cr / (2 * area[:, None])
    vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
    if vol < 0:
        normal = -normal
        b, c = c, b
        vol = -vol
    if vol <= 0:
        raise ValueError(f"Zone {name}: the mesh encloses no volume (is it closed?)")
    # closedness: every edge shared by exactly two triangles (after welding at 1 mm)
    key = np.round(np.vstack([a, b, c]) / 0.001).astype(np.int64)
    _, vid = np.unique(key, axis=0, return_inverse=True)
    vid = vid.reshape(3, -1).T
    edges = np.sort(np.concatenate([vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 0]]]), axis=1)
    _, ecount = np.unique(edges, axis=0, return_counts=True)
    open_edges = int((ecount == 1).sum())
    cen = (a + b + c) / 3.0
    zmin = float(min(a[:, 2].min(), b[:, 2].min(), c[:, 2].min()))
    gz = zmin if ground_z is None else ground_z
    kind = np.where(normal[:, 2] > 0.7, "roof", np.where(normal[:, 2] < -0.7, "floor", "wall")).astype(object)
    floor_area = float(area[kind == "floor"].sum())
    is_ground = (kind == "floor") & (np.abs(cen[:, 2] - gz) < 0.05)
    kind[(kind == "floor") & is_ground] = "ground_floor"
    kind[kind == "floor"] = "exposed_floor"
    # adiabatic: faces whose outside lies inside another zone
    if other_zones:
        from .raytrace import BVH
        probe = cen + normal * 0.05
        inside_any = np.zeros(len(cen), dtype=bool)
        for ov, ot in other_zones:
            ov = np.asarray(ov, dtype=float)
            ot = np.asarray(ot, dtype=np.int64)
            bvh = BVH(ov[ot[:, 0]], ov[ot[:, 1]], ov[ot[:, 2]])
            inside_any |= _inside(bvh, probe)
        kind[inside_any] = "adiabatic"
    rng = np.random.default_rng(seed)
    surfaces: list[Surface] = []
    plane_key = np.concatenate([np.round(normal * 100).astype(np.int64),
                                np.round(np.einsum("ij,ij->i", normal, a) / 0.02).astype(np.int64)[:, None]], axis=1)
    # windows: assign each to the zone face plane it lies on (glass is often set back in the wall
    # depth, so within ``window_tolerance``), keeping only the part inside the zone's extent - a pane
    # running past two storeys is shared between the two zones
    win_area_by_plane: dict[tuple, float] = {}
    zlo = np.minimum(np.minimum(a, b), c).min(axis=0)
    zhi = np.maximum(np.maximum(a, b), c).max(axis=0)
    for w in windows:
        wv = np.asarray(w["vertices"], dtype=float)
        wt = np.asarray(w["triangles"], dtype=np.int64)
        tris = np.stack([wv[wt[:, 0]], wv[wt[:, 1]], wv[wt[:, 2]]], axis=1)
        full = 0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
        if full.sum() <= 0:
            continue
        cr_w = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        ar_w = 0.5 * np.linalg.norm(cr_w, axis=1)
        nw = cr_w / np.maximum(2 * ar_w[:, None], 1e-12)
        wn = principal_normal(nw, ar_w)                # also right for a pane modelled as a thin solid
        side = pane_faces(nw, ar_w)                    # one side of the pane only (its area, not twice it)
        back = (nw @ wn) < -0.9
        if side.sum() < len(side) and back.any() and not (side & back).any():
            # a thin solid: of its two big faces keep the one farther from the zone (the outer one),
            # so the solar samples start outside the glass
            centre = 0.5 * (zlo + zhi)
            d_side = abs(float((tris[side].mean(axis=(0, 1)) - centre) @ wn))
            d_back = abs(float((tris[back].mean(axis=(0, 1)) - centre) @ wn))
            if d_back > d_side:
                side = back
        tris = tris[side]
        pad = window_tolerance * np.abs(wn) + 1e-6
        tris = _clip_triangles_to_box(tris, zlo - pad, zhi + pad)
        if not len(tris):
            continue
        wa, wb, wc = tris[:, 0], tris[:, 1], tris[:, 2]
        warea = 0.5 * np.linalg.norm(np.cross(wb - wa, wc - wa), axis=1)
        if warea.sum() <= 1e-6:
            continue
        wcen = ((wa + wb + wc) / 3.0 * warea[:, None]).sum(axis=0) / warea.sum()
        # nearest parallel exterior zone face
        dist = np.abs(np.einsum("ij,j->i", normal, wcen) - np.einsum("ij,ij->i", normal, a))
        par = np.abs(normal @ wn) > 0.95
        cand = np.flatnonzero(par & (dist < window_tolerance) & np.isin(kind, ["wall", "roof"]))
        if not cand.size:
            continue
        j = cand[np.argmin(np.linalg.norm(cen[cand] - wcen, axis=1))]
        out_n = normal[j]
        pk = tuple(plane_key[j])
        win_area_by_plane[pk] = win_area_by_plane.get(pk, 0.0) + float(warea.sum())
        tri_pts = np.stack([wa, wb, wc], axis=1)
        surfaces.append(Surface(kind="window", area=float(warea.sum()), normal=tuple(out_n), name=w.get("name", "window"),
                                g_value=float(w.get("g_value") or 0.0), u_value=float(w.get("u_value") or 0.0),
                                samples=_surface_samples(tri_pts, out_n, samples_per_surface, rng)))
    # opaque surfaces grouped by plane
    for k in ("wall", "roof", "ground_floor", "exposed_floor", "adiabatic"):
        sel = np.flatnonzero(kind == k)
        if not sel.size:
            continue
        uniq, inv = np.unique(plane_key[sel], axis=0, return_inverse=True)
        for gi in range(len(uniq)):
            s2 = sel[inv.reshape(-1) == gi]
            A = float(area[s2].sum())
            pk = tuple(uniq[gi])
            A_net = A - win_area_by_plane.get(pk, 0.0)
            if A_net <= 1e-6:
                continue
            nrm = (normal[s2] * area[s2, None]).sum(axis=0)
            nrm /= max(np.linalg.norm(nrm), 1e-12)
            tri_pts = np.stack([a[s2], b[s2], c[s2]], axis=1)
            surfaces.append(Surface(kind=k, area=A_net, normal=tuple(nrm), name=f"{k} {gi}",
                                    samples=_surface_samples(tri_pts, nrm, samples_per_surface, rng) if k in ("wall", "roof", "exposed_floor") else None))
    pts_all = np.vstack([a, b, c])
    ext = np.ptp(pts_all[:, :2], axis=0)
    z = Zone(name=name, floor_area=floor_area, volume=vol, surfaces=surfaces,
             source={"plan_min_width_m": round(float(ext.min()), 3), "open_edges": open_edges, "windows_assigned": sum(1 for s in surfaces if s.kind == "window"),
                     "windows_given": len(windows)})
    if open_edges:
        z.source["warning"] = f"{open_edges} open mesh edges: the zone is not watertight, so its volume may be wrong"
    return z


def _inside(bvh, points: np.ndarray) -> np.ndarray:
    """Point-in-closed-mesh by majority vote of three ray parities (robust to grazing hits)."""
    votes = np.zeros(len(points), dtype=int)
    for d in (np.array([0.5773, 0.5774, 0.5773]), np.array([-0.6, 0.3, 0.742]), np.array([0.21, -0.83, -0.516])):
        d = d / np.linalg.norm(d)
        count = np.zeros(len(points), dtype=int)
        o = points.copy()
        alive = np.arange(len(points))
        for _ in range(64):
            if not alive.size:
                break
            t, tri = bvh.intersect(o[alive], np.repeat(d[None], len(alive), axis=0))
            hit = tri >= 0
            alive, t = alive[hit], t[hit]
            count[alive] += 1
            o[alive] = o[alive] + d * (t + 1e-5)[:, None]
        votes += count % 2
    return votes >= 2


def solar_on_surfaces(zones: list[Zone], scene, weather, north_deg: float = 0.0, ground_reflectance: float = 0.2) -> dict:
    """Hourly incident solar irradiance (W/m2) on every sampled zone surface, ray traced against the
    scene (context shading included): diffuse sky + ground from direct sky coefficients, and the sun
    exactly. Stores it on each Surface.irradiance."""
    from . import sky as skymod
    from .daylight import EPS, Quality, Tracer
    surfs = [s for z in zones for s in z.surfaces if s.samples is not None and len(s.samples)]
    if not surfs:
        return {"surfaces": 0}
    pts = np.vstack([s.samples for s in surfs])
    nrm = np.vstack([np.repeat(np.asarray(s.normal, dtype=float)[None], len(s.samples), axis=0) for s in surfs])
    owner = np.concatenate([np.full(len(s.samples), i) for i, s in enumerate(surfs)])
    tracer = Tracer(scene)
    q = Quality(rays=1, bounces=0, patch_samples=2, ground_samples=12, cache_cell=0.5, mf=1)
    rng = np.random.default_rng(0)
    p = skymod.patches(1)
    D = tracer.direct_coefficients(pts, nrm, p, q, rng).sum(axis=0).astype(np.float64)   # (n, P)
    sm = skymod.sky_matrix(weather, mf=1, kind="solar", north_deg=north_deg, ground_reflectance=ground_reflectance)
    diffuse = sm.sky @ D.T                                                              # (8760, n)
    sun = np.zeros_like(diffuse)
    up = np.flatnonzero(sm.sun_normal > 0)
    cos = sm.sun_dir[up] @ nrm.T
    hi, si = np.nonzero(cos > 1e-6)
    if hi.size:
        T, _ = tracer.transmit(pts[si] + nrm[si] * EPS, sm.sun_dir[up][hi])
        sun[up[hi], si] = cos[hi, si] * T * sm.sun_normal[up][hi]
    total = diffuse + sun
    for i, s in enumerate(surfs):
        s.irradiance = total[:, owner == i].mean(axis=1)
    return {"surfaces": len(surfs), "sample_points": len(pts)}


def zone_from_shoebox(box, scene, glazing) -> Zone:
    """The Zone of a Shoebox room (adiabatic except the glazed facade and the roof, as for an
    intermediate-floor room in a larger building: set ``roof=True``-style variations by editing)."""
    W, D, H = box.width, box.depth, box.height
    x0, x1, z0, z1 = box.window_rect()
    win_area = (x1 - x0) * (z1 - z0)
    out_n = np.array([math.sin(math.radians(box.orientation)), math.cos(math.radians(box.orientation)), 0.0])
    rng = np.random.default_rng(0)
    win_mask = box.part_mask(scene, "window")
    fac_mask = box.part_mask(scene, "facade")
    def samples(mask):
        pts = scene.vertices[scene.triangles[mask]]
        return _surface_samples(pts, out_n, 9, rng) if len(pts) else None
    surfaces = [Surface(kind="window", area=win_area, normal=tuple(out_n), name="window",
                        g_value=glazing.g_value or 0.5, u_value=glazing.u_value or 2.0, samples=samples(win_mask))]
    if W * H - win_area > 1e-6:
        surfaces.append(Surface(kind="wall", area=W * H - win_area, normal=tuple(out_n), name="facade", samples=samples(fac_mask)))
    surfaces.append(Surface(kind="adiabatic", area=2 * D * H + W * H + 2 * W * D, normal=(0, 0, 1), name="internal boundaries"))
    return Zone(name="shoebox", floor_area=W * D, volume=W * D * H, surfaces=surfaces,
                source={"type": "shoebox", "boundary": "facade exposed; side walls, back wall, floor and ceiling adiabatic"})
