"""Thermal comfort and psychrometrics.

* Psychrometrics: ASHRAE Handbook - Fundamentals (2017) ch. 1, Hyland-Wexler saturation pressure.
* PMV / PPD: ISO 7730:2005 Annex D (the reference algorithm, vectorised). Air speed is the relative
  air speed; ISO 7730's validity range is reported with every result.
* Adaptive comfort: ASHRAE 55-2020 section 5.4 (prevailing mean outdoor temperature, 80 / 90 %
  acceptability, elevated air speed allowance) and EN 16798-1:2019 Annex B (running mean outdoor
  temperature, categories I-III).
* Overheating: CIBSE TM52 (2013) three criteria for free-running buildings.
* Heat index: NOAA (Rothfusz 1990 regression with Steadman adjustments), outdoors.
"""
from __future__ import annotations

import numpy as np

# ── psychrometrics ───────────────────────────────────────────────────────────

def saturation_pressure(t_c) -> np.ndarray:
    """Saturation vapour pressure (Pa) over water (t >= 0) or ice (t < 0), Hyland & Wexler."""
    t = np.asarray(t_c, dtype=float) + 273.15
    t = np.clip(t, 173.15, 473.15)
    over_ice = (-5.6745359e3 / t + 6.3925247 - 9.6778430e-3 * t + 6.2215701e-7 * t ** 2
                + 2.0747825e-9 * t ** 3 - 9.4840240e-13 * t ** 4 + 4.1635019 * np.log(t))
    over_water = (-5.8002206e3 / t + 1.3914993 - 4.8640239e-2 * t + 4.1764768e-5 * t ** 2
                  - 1.4452093e-8 * t ** 3 + 6.5459673 * np.log(t))
    return np.exp(np.where(t < 273.15, over_ice, over_water))


def humidity_ratio(t_c, rh_pct, pressure=101325.0) -> np.ndarray:
    """kg water / kg dry air."""
    pw = np.clip(np.asarray(rh_pct, dtype=float), 0, 100) / 100.0 * saturation_pressure(t_c)
    return 0.621945 * pw / (np.asarray(pressure, dtype=float) - pw)


def rh_from_humidity_ratio(t_c, w, pressure=101325.0) -> np.ndarray:
    w = np.asarray(w, dtype=float)
    pw = w * np.asarray(pressure, dtype=float) / (0.621945 + w)
    return 100.0 * pw / saturation_pressure(t_c)


def enthalpy(t_c, w) -> np.ndarray:
    """kJ/kg dry air."""
    t = np.asarray(t_c, dtype=float)
    return 1.006 * t + np.asarray(w, dtype=float) * (2501.0 + 1.86 * t)


def dew_point(t_c, rh_pct) -> np.ndarray:
    """Dew point (degC) by bisection on the saturation pressure (exact to 0.001 K)."""
    t = np.asarray(t_c, dtype=float)
    pw = np.clip(np.asarray(rh_pct, dtype=float), 0.01, 100) / 100.0 * saturation_pressure(t)
    lo = np.full(np.broadcast(t, pw).shape, -100.0)
    hi = np.broadcast_to(t, lo.shape).astype(float) + 0.001
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        below = saturation_pressure(mid) < pw
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    return 0.5 * (lo + hi)


def rh_from_dew_point(t_c, dp_c) -> np.ndarray:
    return 100.0 * saturation_pressure(dp_c) / saturation_pressure(t_c)


def wet_bulb(t_c, rh_pct, pressure=101325.0) -> np.ndarray:
    """Thermodynamic wet-bulb temperature (degC), solving the psychrometric equation by bisection."""
    t = np.asarray(t_c, dtype=float)
    p = np.asarray(pressure, dtype=float)
    w = humidity_ratio(t, rh_pct, p)
    lo = np.broadcast_to(dew_point(t, rh_pct), np.broadcast(t, w).shape).astype(float) - 0.01
    hi = np.broadcast_to(t, lo.shape).astype(float) + 0.01
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        ws = 0.621945 * saturation_pressure(mid) / (p - saturation_pressure(mid))
        w_calc = ((2501 - 2.326 * mid) * ws - 1.006 * (t - mid)) / (2501 + 1.86 * t - 4.186 * mid)
        too_wet = w_calc > w
        hi = np.where(too_wet, mid, hi)
        lo = np.where(too_wet, lo, mid)
    return 0.5 * (lo + hi)


# ── PMV / PPD ────────────────────────────────────────────────────────────────

def pmv_ppd(ta, tr, vel, rh, met, clo, wme=0.0) -> dict[str, np.ndarray]:
    """ISO 7730:2005 PMV and PPD. ta, tr in degC; vel relative air speed m/s; rh %; met; clo."""
    ta, tr, vel, rh, met, clo, wme = np.broadcast_arrays(*(np.asarray(x, dtype=float) for x in (ta, tr, vel, rh, met, clo, wme)))
    pa = rh * 10.0 * np.exp(16.6536 - 4030.183 / (ta + 235.0))
    icl = 0.155 * clo
    m = met * 58.15
    w = wme * 58.15
    mw = m - w
    fcl = np.where(icl <= 0.078, 1.0 + 1.29 * icl, 1.05 + 0.645 * icl)
    hcf = 12.1 * np.sqrt(np.maximum(vel, 0.0))
    taa = ta + 273.0
    tra = tr + 273.0
    tcla = taa + (35.5 - ta) / (3.5 * icl + 0.1)
    p1 = icl * fcl
    p2 = p1 * 3.96
    p3 = p1 * 100.0
    p4 = p1 * taa
    p5 = 308.7 - 0.028 * mw + p2 * (tra / 100.0) ** 4
    xn = tcla / 100.0
    xf = tcla / 50.0
    hc = hcf.copy()
    for _ in range(150):                      # ISO 7730 Annex D: iterate until |XN - XF| <= 0.00015
        active = np.abs(xn - xf) > 0.00015
        if not active.any():
            break
        xf = np.where(active, (xf + xn) / 2.0, xf)
        hcn = 2.38 * np.abs(100.0 * xf - taa) ** 0.25
        hc_new = np.maximum(hcf, hcn)
        xn_new = (p5 + p4 * hc_new - p2 * xf ** 4) / (100.0 + p3 * hc_new)
        hc = np.where(active, hc_new, hc)
        xn = np.where(active, xn_new, xn)
    tcl = 100.0 * xn - 273.0
    hl1 = 3.05e-3 * (5733.0 - 6.99 * mw - pa)
    hl2 = np.where(mw > 58.15, 0.42 * (mw - 58.15), 0.0)
    hl3 = 1.7e-5 * m * (5867.0 - pa)
    hl4 = 0.0014 * m * (34.0 - ta)
    hl5 = 3.96 * fcl * (xn ** 4 - (tra / 100.0) ** 4)
    hl6 = fcl * hc * (tcl - ta)
    ts = 0.303 * np.exp(-0.036 * m) + 0.028
    pmv = ts * (mw - hl1 - hl2 - hl3 - hl4 - hl5 - hl6)
    ppd = 100.0 - 95.0 * np.exp(-0.03353 * pmv ** 4 - 0.2179 * pmv ** 2)
    valid = ((ta >= 10) & (ta <= 30) & (tr >= 10) & (tr <= 40) & (vel <= 1.0) & (met >= 0.8) & (met <= 4.0)
             & (clo <= 2.0) & (pa <= 2700) & (np.abs(pmv) <= 2.0))
    return {"pmv": pmv, "ppd": ppd, "within_iso7730_range": valid, "clothing_temperature": tcl}


def _psat_mmhg(t_c) -> np.ndarray:
    return np.exp(18.6686 - 4030.183 / (np.asarray(t_c, dtype=float) + 235.0))


def set_star(ta, tr, vel, rh, met, clo, wme=0.0) -> np.ndarray:
    """Standard Effective Temperature SET* (degC) by the two-node model of Gagge, Fobelets and Berglund
    (1986, ASHRAE Transactions 92-2B): one hour of 1-minute steps for core and skin temperature with
    vasomotor, sweating and shivering control, then the temperature of the standard environment (50 % RH,
    still air, standard clothing for the activity) giving the same skin heat loss and wettedness. Works
    outdoors too, where mean radiant temperature includes the sun (see rooms.semi_outdoor_mrt)."""
    ta, tr, vel, rh, met, clo, wme = np.broadcast_arrays(*(np.asarray(x, dtype=float) for x in (ta, tr, vel, rh, met, clo, wme)))
    vp = rh / 100.0 * _psat_mmhg(ta)                       # mmHg
    body_weight, body_area = 69.9, 1.8258
    lr = 2.2                                              # Lewis relation, K/mmHg
    sigma = 5.67e-8
    t_sk = np.full(ta.shape, 33.7)
    t_cr = np.full(ta.shape, 36.8)
    alfa = np.full(ta.shape, 0.1)
    skbf = np.full(ta.shape, 6.3)
    rm = met * 58.2
    m = rm.copy()
    wk = wme * 58.2
    esk = 0.1 * met
    rcl = 0.155 * clo
    facl = 1.0 + 0.15 * clo
    icl = 0.45
    wcrit = 0.85
    chc = np.maximum(3.0, 8.600001 * np.maximum(vel, 0.0) ** 0.53)
    chr_ = np.full(ta.shape, 4.7)
    ctc = chr_ + chc
    top = (chr_ * tr + chc * ta) / ctc
    pwet = np.zeros(ta.shape)
    tcl = top + (t_sk - top) / (ctc * (1.0 / (facl * ctc) + rcl))
    for _ in range(60):
        for _ in range(8):                                # clothing surface temperature / radiative coefficient
            chr_ = 4.0 * 0.72 * sigma * ((tcl + tr) / 2.0 + 273.15) ** 3
            ctc = chr_ + chc
            ra = 1.0 / (facl * ctc)
            top = (chr_ * tr + chc * ta) / ctc
            tcl = (ra * t_sk + rcl * top) / (ra + rcl)
        dry = (t_sk - top) / (ra + rcl)
        hfcs = (t_cr - t_sk) * (5.28 + 1.163 * skbf)
        eres = 0.0023 * m * (44.0 - vp)
        cres = 0.0014 * m * (34.0 - ta)
        scr = m - hfcs - eres - cres - wk
        ssk = hfcs - dry - esk
        tcsk = 0.97 * alfa * body_weight
        tccr = 0.97 * (1.0 - alfa) * body_weight
        t_sk = t_sk + ssk * body_area / (tcsk * 60.0)
        t_cr = t_cr + scr * body_area / (tccr * 60.0)
        t_b = alfa * t_sk + (1.0 - alfa) * t_cr
        sksig, crsig, bdsig = t_sk - 33.7, t_cr - 36.8, t_b - 36.49
        warms, colds = np.maximum(sksig, 0), np.maximum(-sksig, 0)
        warmc, coldc = np.maximum(crsig, 0), np.maximum(-crsig, 0)
        warmb = np.maximum(bdsig, 0)
        skbf = np.clip((6.3 + 200.0 * warmc) / (1.0 + 0.5 * colds), 0.5, 90.0)
        alfa = 0.0417737 + 0.7451833 / (skbf + 0.585417)
        regsw = np.minimum(170.0 * warmb * np.exp(warms / 10.7), 500.0)
        ersw = 0.68 * regsw
        rea = 1.0 / (lr * facl * chc)
        recl = rcl / (lr * icl)
        emax = (_psat_mmhg(t_sk) - vp) / (rea + recl)
        with np.errstate(divide="ignore", invalid="ignore"):
            prsw = np.where(emax > 0, ersw / np.where(emax > 0, emax, 1.0), wcrit)
        pwet = 0.06 + 0.94 * prsw
        edif = pwet * emax - ersw
        over = (pwet > wcrit) & (emax > 0)
        pwet = np.where(over, wcrit, pwet)
        prsw = np.where(over, wcrit / 0.94, prsw)
        ersw = np.where(over, prsw * emax, ersw)
        edif = np.where(over, 0.06 * (1.0 - prsw) * emax, edif)
        neg = emax < 0
        edif = np.where(neg, 0.0, edif)
        ersw = np.where(neg, 0.0, ersw)
        pwet = np.where(neg, wcrit, pwet)
        esk = np.where(neg, emax, ersw + edif)
        m = rm + 19.4 * colds * coldc                     # shivering
    hsk = dry + esk
    # standard environment for this activity
    chcs = np.where(met < 0.85, 3.0, np.maximum(3.0, 5.66 * np.maximum(met - 0.85, 0.0) ** 0.39))
    ctcs = chcs + chr_
    rclos = 1.52 / (met + 0.6944) - 0.1835
    rcls = 0.155 * rclos
    facls = 1.0 + 0.25 * rclos
    fcls = 1.0 / (1.0 + 0.155 * facls * ctcs * rclos)
    ims = 0.45
    icls = ims * chcs / ctcs * (1.0 - fcls) / (chcs / ctcs - fcls * ims)
    ras = 1.0 / (facls * ctcs)
    reas = 1.0 / (lr * facls * chcs)
    recls = rcls / (lr * icls)
    hd_s = 1.0 / (ras + rcls)
    he_s = 1.0 / (reas + recls)
    lo, hi = np.full(ta.shape, -40.0), np.full(ta.shape, 80.0)
    psk = _psat_mmhg(t_sk)
    for _ in range(60):                                   # bisection: heat loss falls as SET rises
        mid = 0.5 * (lo + hi)
        f = hsk - hd_s * (t_sk - mid) - pwet * he_s * (psk - 0.5 * _psat_mmhg(mid))
        hi = np.where(f > 0, mid, hi)                      # skin loses less than this SET implies: lower it
        lo = np.where(f > 0, lo, mid)
    return 0.5 * (lo + hi)


def operative_temperature(ta, tr, vel=0.1) -> np.ndarray:
    """ASHRAE 55 simplified operative temperature: mean of air and radiant at low air speed, weighted
    towards air temperature above 0.2 m/s."""
    vel = np.asarray(vel, dtype=float)
    a = np.where(vel < 0.2, 0.5, np.where(vel < 0.6, 0.6, 0.7))
    return a * np.asarray(ta, dtype=float) + (1 - a) * np.asarray(tr, dtype=float)


# ── adaptive comfort ─────────────────────────────────────────────────────────

def running_mean_outdoor(daily_mean: np.ndarray, alpha: float = 0.8) -> np.ndarray:
    """Exponentially weighted running mean of the *previous* days' mean outdoor temperature
    (EN 16798-1 B.2.2): theta_rm(d) = (1 - alpha) theta_ed(d-1) + alpha theta_rm(d-1). The year is
    treated as cyclic (a 60-day warm-up from December) so 1 January is not biased."""
    t = np.asarray(daily_mean, dtype=float)
    if not 0 <= alpha < 1:
        raise ValueError("alpha must be in [0, 1)")
    rm = float(t[-60:].mean())
    for v in t[-60:]:
        rm = (1 - alpha) * v + alpha * rm
    out = np.empty_like(t)
    for d in range(len(t)):
        out[d] = rm
        rm = (1 - alpha) * t[d] + alpha * rm
    return out


ASHRAE_AIR_SPEED_BONUS = ((0.6, 1.2), (0.9, 1.8), (1.2, 2.2))   # (m/s, K) allowed above 25 degC operative


def adaptive_ashrae55(t_op: np.ndarray, t_pma_daily: np.ndarray, air_speed: float = 0.3) -> dict:
    """ASHRAE 55-2020 adaptive model, hourly. ``t_pma_daily`` is the prevailing mean outdoor
    temperature per day (365,); results are per hour (8760)."""
    t_pma = np.repeat(np.asarray(t_pma_daily, dtype=float), 24)
    t_comf = 0.31 * t_pma + 17.8
    bonus = 0.0
    for v, k in ASHRAE_AIR_SPEED_BONUS:
        if air_speed >= v:
            bonus = k
    applicable = (t_pma >= 10.0) & (t_pma <= 33.5)
    t_op = np.asarray(t_op, dtype=float)
    up80 = t_comf + 3.5 + np.where(t_op > 25.0, bonus, 0.0)
    up90 = t_comf + 2.5 + np.where(t_op > 25.0, bonus, 0.0)
    lo80, lo90 = t_comf - 3.5, t_comf - 2.5
    status = np.where(t_op > up80, 1, np.where(t_op < lo80, -1, 0))
    return {"neutral": t_comf, "upper_80": up80, "lower_80": lo80, "upper_90": up90, "lower_90": lo90,
            "status_80": status, "comfortable_80": status == 0,
            "comfortable_90": (t_op <= up90) & (t_op >= lo90), "applicable": applicable,
            "air_speed_bonus_k": bonus}


EN16798_CATEGORIES = {"I": (2.0, 3.0), "II": (3.0, 4.0), "III": (4.0, 5.0)}
# PMV range per EN 16798-1 / ISO 7730 category for mechanically conditioned spaces
PMV_CATEGORIES = {"I": 0.2, "II": 0.5, "III": 0.7, "IV": 1.0}


def temperature_for_pmv(target: float, met: float, clo: float, rh: float = 50.0, vel: float = 0.1,
                        radiant_offset_k: float = 0.0) -> float:
    """The operative temperature (air temperature with mean radiant = air + radiant_offset_k) at which
    PMV equals ``target``, by bisection (PMV rises with temperature)."""
    def f(t):
        return float(pmv_ppd(t, t + radiant_offset_k, vel, rh, met, clo)["pmv"]) - target
    lo, hi = 0.0, 45.0
    if f(lo) > 0 or f(hi) < 0:
        raise ValueError(f"No temperature in 0..45 degC gives PMV {target:+.1f} for {met} met and {clo} clo")
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    t = 0.5 * (lo + hi)
    return float(operative_temperature(t, t + radiant_offset_k, vel))


def pmv_setpoints(met: float, clo_heating: float = 1.0, clo_cooling: float = 0.5, rh: float = 50.0,
                  vel: float = 0.1, category: str = "II", radiant_offset_k: float = 0.0) -> dict:
    """Design set-points from PMV: the lowest operative temperature that keeps PMV at or above the
    category's lower limit with winter clothing (heating) and the highest that keeps it at or below the
    upper limit with summer clothing (cooling)."""
    if category not in PMV_CATEGORIES:
        raise ValueError("category must be I, II, III or IV")
    lim = PMV_CATEGORIES[category]
    heat = temperature_for_pmv(-lim, met, clo_heating, rh, vel, radiant_offset_k)
    cool = temperature_for_pmv(lim, met, clo_cooling, rh, vel, radiant_offset_k)
    return {"category": category, "pmv_range": [-lim, lim],
            "heating_setpoint_c": round(heat, 1), "cooling_setpoint_c": round(cool, 1),
            "inputs": {"met": met, "clo_heating": clo_heating, "clo_cooling": clo_cooling, "rh_pct": rh,
                       "air_speed_m_s": vel, "mean_radiant_minus_air_k": radiant_offset_k},
            "method": "PMV (ISO 7730) solved for the category limit; temperatures are operative."}


def adaptive_en16798(t_op: np.ndarray, t_rm_daily: np.ndarray, category: str = "II") -> dict:
    if category not in EN16798_CATEGORIES:
        raise ValueError("category must be I, II or III")
    up, lo = EN16798_CATEGORIES[category]
    t_rm = np.repeat(np.asarray(t_rm_daily, dtype=float), 24)
    t_c = 0.33 * t_rm + 18.8
    t_op = np.asarray(t_op, dtype=float)
    upper, lower = t_c + up, t_c - lo
    status = np.where(t_op > upper, 1, np.where(t_op < lower, -1, 0))
    return {"neutral": t_c, "upper": upper, "lower": lower, "status": status, "comfortable": status == 0,
            "applicable_upper": (t_rm > 10) & (t_rm < 30), "applicable_lower": (t_rm > 15) & (t_rm < 30),
            "category": category}


def tm52(t_op: np.ndarray, t_rm_daily: np.ndarray, occupied: np.ndarray, month: np.ndarray) -> dict:
    """CIBSE TM52 overheating criteria for the non-heating season (May-September), occupied hours.
    A room fails when it fails two or more of the three criteria."""
    t_rm = np.repeat(np.asarray(t_rm_daily, dtype=float), 24)
    t_max = 0.33 * t_rm + 21.8
    dT = np.round(np.asarray(t_op, dtype=float) - t_max)
    season = (month >= 5) & (month <= 9) & np.asarray(occupied, dtype=bool)
    occ_hours = int(season.sum())
    if occ_hours == 0:
        return {"applicable": False, "reason": "no occupied hours between May and September"}
    exceed = int(((dT >= 1) & season).sum())
    c1_pct = 100.0 * exceed / occ_hours
    day = np.repeat(np.arange(365), 24)
    we = np.bincount(day, weights=np.where(season & (dT > 0), dT, 0.0), minlength=365)
    c2_max = float(we.max())
    c3_max = float(np.where(season, dT, -99).max())
    fails = [c1_pct > 3.0, c2_max > 6.0, c3_max > 4.0]
    return {"applicable": True, "occupied_hours": occ_hours,
            "criterion_1": {"hours_exceeding": exceed, "pct": round(c1_pct, 2), "limit_pct": 3.0, "pass": not fails[0]},
            "criterion_2": {"max_daily_weighted_exceedance": round(c2_max, 1), "limit": 6.0,
                            "days_over": int((we > 6.0).sum()), "pass": not fails[1]},
            "criterion_3": {"max_delta_t": c3_max, "limit": 4.0, "pass": not fails[2]},
            "pass": sum(fails) < 2, "failed_criteria": [i + 1 for i, f in enumerate(fails) if f]}


def heat_index(t_c, rh_pct) -> np.ndarray:
    """NOAA heat index (degC) - outdoor apparent temperature in shade, meaningful above ~27 degC."""
    t = np.asarray(t_c, dtype=float) * 9 / 5 + 32
    r = np.asarray(rh_pct, dtype=float)
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + r * 0.094)
    full = (-42.379 + 2.04901523 * t + 10.14333127 * r - 0.22475541 * t * r - 6.83783e-3 * t * t
            - 5.481717e-2 * r * r + 1.22874e-3 * t * t * r + 8.5282e-4 * t * r * r - 1.99e-6 * t * t * r * r)
    adj = np.where((r < 13) & (t >= 80) & (t <= 112),
                   -((13 - r) / 4) * np.sqrt(np.maximum(0, (17 - np.abs(t - 95.0)) / 17)), 0.0)
    adj = np.where((r > 85) & (t >= 80) & (t <= 87), ((r - 85) / 10) * ((87 - t) / 5), adj)
    hi = np.where((simple + t) / 2 >= 80, full + adj, simple)
    return (hi - 32) * 5 / 9
