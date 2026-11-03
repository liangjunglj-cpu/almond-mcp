"""EN 1993-1-1 member checks for steel line members, applied per member (not per analysis element).

The analysis may split a member into several elements (joints, kinks of floor loads, the stability
check's subdivision); the buckling length is still the member between its joints (system length,
5.2.2(7)b, with second-order sway effects and imperfections in the global analysis).

Per member, for each analysed combination:
- section class from Table 5.2 for the actual stress state (CHS d/t; RHS and I internal parts with
  psi and alpha; I flange outstands), with epsilon = sqrt(235/fy); Class 4 is flagged as outside
  these checks (effective sections, EN 1993-1-5/-1-6, are not applied);
- cross-section resistance, 6.2.1(7) linear interaction, elastic moduli (plastic moduli only for
  Class 1/2 sections and only when plastic design is requested), resultant moment for CHS;
- flexural buckling about both axes, 6.3.1, curves from Table 6.2: hollow sections cold-formed
  (EN 10219) -> c, hot-finished (EN 10210) -> a (a0 for fy >= 460); rolled I by h/b and tf;
- compression + bending, 6.3.3 eq. (6.61)/(6.62) with Annex B interaction factors for members not
  susceptible to torsional deformation (hollow sections; I-sections with lateral restraint assumed),
  equivalent moment factors Cm from Table B.3 (linear diagrams 0.6 + 0.4 psi >= 0.4; members with
  transverse load take the table's upper bound 1.0);
- shear, 6.2.6: V_pl,Rd = A_v (fy / sqrt 3) / gamma_M0 along both local axes (CHS: the resultant),
  shear areas from 6.2.6(3) (``shear_areas``), eta = 1.0 (the 6.2.6(3) Note's conservative value);
  webs with hw/tw > 72 epsilon / eta (6.2.6(6)) are flagged as outside these checks (shear buckling,
  EN 1993-1-5, is not applied);
- bending and shear, 6.2.8: where V_Ed > 0.5 V_pl,Rd at a station, the bending resistance there uses
  the reduced yield strength (1 - rho) fy on the shear area, rho = (2 V_Ed / V_pl,Rd - 1)^2: eq. (6.30)
  for I-sections about the major axis (and its elastic counterpart), the whole modulus otherwise;
- local bow imperfections e0/L by buckling curve (Table 5.1, elastic analysis), applied as equivalent
  member loads (Figure 5.4) where 5.3.2(6) requires them (``bow_imperfection``, used by the native
  analysis when alpha_cr < 10).
Not checked: lateral-torsional buckling, torsion, aluminium to EN 1999 (aluminium members use these
steel rules, flagged)."""
from __future__ import annotations

import math

import numpy as np

ALPHA = {"a0": 0.13, "a": 0.21, "b": 0.34, "c": 0.49, "d": 0.76}
# Table 5.1, bow imperfection e0/L = 1/value for elastic global analysis
BOW_ELASTIC = {"a0": 350, "a": 300, "b": 250, "c": 200, "d": 150}
# 6.2.6(3) Note: eta (EN 1993-1-5 5.1) may conservatively be taken as 1.0; the recommended 1.2 for
# steels up to S460 is a Nationally Determined Parameter and is not applied
ETA = 1.0
FABRICATION = ("cold_formed", "hot_finished")
STEEL_FAMILIES = ("steel", "aluminium")


def epsilon(fy_kn_m2: float) -> float:
    return math.sqrt(235e3 / fy_kn_m2)


def chi(lam: float, curve: str) -> float:
    """6.3.1.2 reduction factor; 1.0 at or below the plateau (lambda <= 0.2)."""
    if lam <= 0.2:
        return 1.0
    phi = 0.5 * (1 + ALPHA[curve] * (lam - 0.2) + lam ** 2)
    return min(1.0, 1.0 / (phi + math.sqrt(max(phi ** 2 - lam ** 2, 0.0))))


def buckling_curves(section, fy: float, fabrication: str = "cold_formed") -> tuple[str, str]:
    """Table 6.2 curves (about local y, about local z)."""
    if section.shape in ("chs", "rhs"):
        if fabrication == "hot_finished":
            return ("a0", "a0") if fy >= 460e3 else ("a", "a")
        return "c", "c"
    if section.shape == "i":
        h, b, tw, tf = section.dims_mm
        if h / b > 1.2:
            return ("a", "b") if tf <= 40 else ("b", "c")
        return ("b", "c") if tf <= 100 else ("d", "d")
    return "c", "c"


def _internal_class(c_t: float, s1: float, s2: float, eps: float) -> int:
    """Table 5.2 sheet 1, internal compression part with edge stresses s1 >= s2 (compression +)."""
    if s1 <= 0:
        return 1
    psi = s2 / s1
    alpha = 1.0 if s2 >= 0 else s1 / (s1 - s2)
    c1 = 396 * eps / (13 * alpha - 1) if alpha > 0.5 else 36 * eps / alpha
    c2 = 456 * eps / (13 * alpha - 1) if alpha > 0.5 else 41.5 * eps / alpha
    c3 = 42 * eps / (0.67 + 0.33 * psi) if psi > -1 else 62 * eps * (1 - psi) * math.sqrt(-psi)
    return 1 if c_t <= c1 else 2 if c_t <= c2 else 3 if c_t <= c3 else 4


def classify(section, fy: float, N: np.ndarray, My: np.ndarray, Mz: np.ndarray) -> int | None:
    """Worst Table 5.2 class along the member (None for solid sections, which are not classified)."""
    eps = epsilon(fy)
    if section.shape == "chs":
        d, t = section.dims_mm
        r = d / t
        return 1 if r <= 50 * eps ** 2 else 2 if r <= 70 * eps ** 2 else 3 if r <= 90 * eps ** 2 else 4
    comp = -np.asarray(N, float) / section.A                              # axial stress, compression +
    my, mz = np.abs(My), np.abs(Mz)
    worst = 1
    if section.shape == "rhs":
        h, b, t = section.dims_mm
        sy = my * (h / 2000) / section.Iy                                  # bending stress at the faces
        sz = mz * (b / 2000) / section.Iz
        for c_t, a, g in (((b - 3 * t) / t, sy, sz), ((h - 3 * t) / t, sz, sy)):   # flange, web
            for c0, ab, gr in zip(comp, a, g):
                worst = max(worst, _internal_class(c_t, c0 + ab + gr, c0 + ab - gr, eps))
        return worst
    if section.shape == "i":
        h, b, tw, tf = section.dims_mm
        hw = h - 2 * tf
        out_ct = (b - tw) / 2 / tf
        sy_f = my * (h / 2000) / section.Iy
        sz_f = mz * (b / 2000) / section.Iz
        sy_w = my * (hw / 2000) / section.Iy
        for c0, f1, f2, w in zip(comp, sy_f, sz_f, sy_w):
            if c0 + f1 + f2 > 0:                                            # compression flange outstand
                worst = max(worst, 1 if out_ct <= 9 * eps else 2 if out_ct <= 10 * eps else 3 if out_ct <= 14 * eps else 4)
            worst = max(worst, _internal_class(hw / tw, c0 + w, c0 - w, eps))
        return worst
    return None


def shear_areas(section, eta: float = ETA) -> tuple[float, float]:
    """6.2.6(3) shear areas (m2) for shear along local y and along local z (the depth).

    I/H (no root radii, so r = 0): load parallel to the web A - 2 b tf + (tw + 2r) tf >= eta hw tw (a),
    parallel to the flanges A - hw tw (e); RHS of uniform thickness: A h / (b + h) along the depth,
    A b / (b + h) along the width (f); CHS: 2 A / pi (g); solid rectangle (plates and solid bars): A (h)."""
    A = section.A
    if section.shape == "chs":
        return 2 * A / math.pi, 2 * A / math.pi
    if section.shape == "rhs":
        h, b, _ = section.dims_mm
        return A * b / (b + h), A * h / (b + h)
    if section.shape == "i":
        h, b, tw, tf = (v / 1000 for v in section.dims_mm)
        hw = h - 2 * tf
        return A - hw * tw, max(A - 2 * b * tf + tw * tf, eta * hw * tw)
    return A, A


def web_slenderness(section) -> float | None:
    """hw / tw of the plates that carry shear (the worse one for RHS); None for CHS and solid sections."""
    if section.shape == "i":
        h, _, tw, tf = section.dims_mm
        return (h - 2 * tf) / tw
    if section.shape == "rhs":
        h, b, t = section.dims_mm
        return (max(h, b) - 2 * t) / t
    return None


def shear_buckling(section, fy: float, eta: float = ETA) -> bool:
    """6.2.6(6): webs without intermediate stiffeners with hw/tw > 72 epsilon / eta need EN 1993-1-5."""
    r = web_slenderness(section)
    return r is not None and r > 72 * epsilon(fy) / eta


def shear_rho(v_ed: np.ndarray, v_pl: float) -> np.ndarray:
    """6.2.8(3): rho = (2 V_Ed / V_pl,Rd - 1)^2 where V_Ed > 0.5 V_pl,Rd, else 0 (capped at 1)."""
    r = np.abs(np.asarray(v_ed, float)) / v_pl
    return np.where(r > 0.5, np.minimum((2 * r - 1) ** 2, 1.0), 0.0)


def _reduced_moduli(section, Wy: float, Wz: float, use_plastic: bool, rho_y, rho_z):
    """6.2.8: moduli with (1 - rho) fy on the shear area. rho_z (shear along the depth) reduces the
    major-axis modulus Wy, rho_y the minor-axis Wz. I-sections about the major axis: eq. (6.30)
    W_pl,y - rho A_w^2 / (4 tw), A_w = hw tw (elastic: the web's share tw hw^3 / (6 h)); every other
    case reduces the whole modulus, which is on the safe side (the shear area is most of it)."""
    if section.shape == "i":
        h, _, tw, tf = (v / 1000 for v in section.dims_mm)
        hw = h - 2 * tf
        web = hw ** 2 * tw / 4 if use_plastic else tw * hw ** 3 / (6 * h)
        return np.maximum(Wy - rho_z * web, 0.0), Wz * (1 - rho_y)
    return Wy * (1 - rho_z), Wz * (1 - rho_y)


def bow_imperfection(curve: str, length: float) -> float:
    """Table 5.1 (elastic analysis): design bow imperfection e0 = L / {a0 350, a 300, b 250, c 200, d 150}."""
    return length / BOW_ELASTIC[curve]


def bow_required(section, fy: float, E: float, length: float, n_ed: float, axis: str) -> tuple[bool, float, float]:
    """5.3.2(6) second condition for one buckling axis ("y" or "z"): lambda_bar > 0.5 sqrt(A fy / N_Ed),
    lambda_bar in-plane for the member hinged at its ends (L_cr = L). Returns (required, lambda_bar, limit)."""
    if n_ed <= 0:
        return False, 0.0, math.inf
    inertia = section.Iy if axis == "y" else section.Iz
    lam = math.sqrt(section.A * fy / (math.pi ** 2 * E * inertia / length ** 2))
    limit = 0.5 * math.sqrt(section.A * fy / n_ed)
    return lam > limit, lam, limit


def equivalent_moment_factor(t: np.ndarray, M: np.ndarray) -> float:
    """Table B.3: linear diagrams 0.6 + 0.4 psi >= 0.4; any transverse load (curved diagram) -> 1.0,
    the table's upper bound."""
    peak = float(np.max(np.abs(M))) if len(M) else 0.0
    if peak < 1e-9:
        return 1.0
    m0, m1 = float(M[0]), float(M[-1])
    linear = m0 + (m1 - m0) * t
    if float(np.max(np.abs(M - linear))) > 0.02 * peak:
        return 1.0
    mh, mo = (m0, m1) if abs(m0) >= abs(m1) else (m1, m0)
    psi = mo / mh if abs(mh) > 1e-12 else 1.0
    return max(0.4, 0.6 + 0.4 * psi)


def member_check(section, material, length: float, t: np.ndarray, N: np.ndarray, My: np.ndarray, Mz: np.ndarray,
                 gamma_m0: float = 1.0, gamma_m1: float = 1.0, plastic: bool = False,
                 fabrication: str = "cold_formed", Vy: np.ndarray | None = None, Vz: np.ndarray | None = None) -> dict:
    """Utilization and the working of one steel member: stations ordered along the member
    (t in 0..1), forces N (tension +), My, Mz in kN and kNm, shears Vy, Vz in kN (optional: without
    them the shear checks are skipped)."""
    fy, E, s = material.fy, material.E, section
    cls = classify(s, fy, N, My, Mz)
    use_plastic = bool(plastic) and cls is not None and cls <= 2
    Wy, Wz = (s.Wpl_y, s.Wpl_z) if use_plastic else (s.Wel_y, s.Wel_z)
    shear = None
    if Vy is not None and Vz is not None:
        av_y, av_z = shear_areas(s)
        vpl_y, vpl_z = (a * fy / math.sqrt(3) / gamma_m0 for a in (av_y, av_z))
        Vy, Vz = np.abs(np.asarray(Vy, float)), np.abs(np.asarray(Vz, float))
        if s.shape == "chs":                                    # resultant shear on a round tube
            v_res = np.hypot(Vy, Vz)
            ratio = v_res / vpl_z
            rho_y = rho_z = shear_rho(v_res, vpl_z)
        else:
            ratio = np.maximum(Vy / vpl_y, Vz / vpl_z)
            rho_y, rho_z = shear_rho(Vy, vpl_y), shear_rho(Vz, vpl_z)
        Wy, Wz = _reduced_moduli(s, Wy, Wz, use_plastic, rho_y, rho_z)
        shear = {"shear": float(np.max(ratio)), "shear_area_y_m2": av_y, "shear_area_z_m2": av_z,
                 "v_pl_rd_y_kn": vpl_y, "v_pl_rd_z_kn": vpl_z, "v_ed_y_kn": float(np.max(Vy)),
                 "v_ed_z_kn": float(np.max(Vz)), "rho": float(np.max(np.maximum(rho_y, rho_z))),
                 "hw_tw": web_slenderness(s), "shear_buckling_limit": 72 * epsilon(fy) / ETA,
                 "shear_buckling": shear_buckling(s, fy)}
    with np.errstate(divide="ignore", invalid="ignore"):
        if s.shape == "chs":
            m_cs = _ratio(np.hypot(My, Mz), Wy * fy / gamma_m0)
        else:
            m_cs = _ratio(np.abs(My), Wy * fy / gamma_m0) + _ratio(np.abs(Mz), Wz * fy / gamma_m0)
    cross = float(np.max(np.abs(N) / (s.A * fy / gamma_m0) + m_cs))
    sig = np.abs(N) / s.A + (np.hypot(My, Mz) / s.Wel_y if s.shape == "chs"
                             else np.abs(My) / s.Wel_y + np.abs(Mz) / s.Wel_z)
    out = {"class": cls, "moduli": "plastic" if use_plastic else "elastic", "cross_section": cross,
           "max_stress_mpa": float(np.max(sig)) / 1000.0, "length_cr_m": length, "fabrication": fabrication}
    util, check = cross, "cross-section"
    if shear is not None:
        out.update(shear)
        if shear["shear"] > util:
            util, check = shear["shear"], "shear 6.2.6"
    ned = float(max(0.0, -np.min(N)))
    if ned > 0:
        cy, cz = buckling_curves(s, fy, fabrication)
        nrk = s.A * fy
        lam_y = math.sqrt(nrk / (math.pi ** 2 * E * s.Iy / length ** 2))
        lam_z = math.sqrt(nrk / (math.pi ** 2 * E * s.Iz / length ** 2))
        chi_y, chi_z = chi(lam_y, cy), chi(lam_z, cz)
        n_y, n_z = ned / (chi_y * nrk / gamma_m1), ned / (chi_z * nrk / gamma_m1)
        cm_y, cm_z = equivalent_moment_factor(t, My), equivalent_moment_factor(t, Mz)
        if use_plastic:
            kyy = cm_y * min(1 + (lam_y - 0.2) * n_y, 1 + 0.8 * n_y)
            kzz = (cm_z * min(1 + (2 * lam_z - 0.6) * n_z, 1 + 1.4 * n_z) if s.shape == "i"
                   else cm_z * min(1 + (lam_z - 0.2) * n_z, 1 + 0.8 * n_z))
            kyz, kzy = 0.6 * kzz, 0.6 * kyy
        else:
            kyy = cm_y * min(1 + 0.6 * lam_y * n_y, 1 + 0.6 * n_y)
            kzz = cm_z * min(1 + 0.6 * lam_z * n_z, 1 + 0.6 * n_z)
            kyz, kzy = kzz, 0.8 * kyy
        Wy, Wz = (s.Wpl_y, s.Wpl_z) if use_plastic else (s.Wel_y, s.Wel_z)    # member checks: unreduced (6.3.3)
        my_r, mz_r = Wy * fy / gamma_m1, Wz * fy / gamma_m1
        my_ed, mz_ed = float(np.max(np.abs(My))), float(np.max(np.abs(Mz)))
        eq61 = n_y + kyy * my_ed / my_r + kyz * mz_ed / mz_r
        eq62 = n_z + kzy * my_ed / my_r + kzz * mz_ed / mz_r
        out.update({"curve_y": cy, "curve_z": cz, "lambda_y": lam_y, "lambda_z": lam_z, "chi_y": chi_y,
                    "chi_z": chi_z, "cm_y": cm_y, "cm_z": cm_z, "kyy": kyy, "kzz": kzz, "kyz": kyz, "kzy": kzy,
                    "eq_6_61": eq61, "eq_6_62": eq62, "buckling": max(eq61, eq62),
                    "slenderness": max(lam_y, lam_z), "chi": min(chi_y, chi_z)})
        if max(eq61, eq62) > util:
            util, check = max(eq61, eq62), "buckling 6.61" if eq61 >= eq62 else "buckling 6.62"
    if cls == 4:
        check = "class 4 (slender) - not covered"
    elif shear is not None and shear["shear_buckling"]:
        check = "shear buckling (EN 1993-1-5) - not covered"
    out["governing_check"] = check
    return {"utilization": util, "detail": out}


def _ratio(m: np.ndarray, resistance) -> np.ndarray:
    """M / M_Rd per station; a resistance reduced to zero by shear fails wherever there is moment."""
    r = np.broadcast_to(np.asarray(resistance, float), np.shape(m))
    return np.where(r > 0, np.divide(m, np.where(r > 0, r, 1.0)), np.where(m > 1e-12, np.inf, 0.0))


def groups(frame) -> dict:
    """Analysis elements per member: the element's lineage (kept through every split) or itself."""
    out: dict = {}
    for i, e in enumerate(frame.elements):
        out.setdefault(e.group if getattr(e, "group", None) is not None else i, []).append(i)
    return out


def apply(frame, result, member_groups: dict | None = None, plastic: bool = False,
          fabrication: str = "cold_formed") -> None:
    """Replace the element-level checks of steel members in ``result`` by member checks (in place)."""
    gm0, gm1 = getattr(frame, "gamma_m", (1.0, 1.0))
    for idx in (member_groups or groups(frame)).values():
        e0 = frame.elements[idx[0]]
        if e0.material.family not in STEEL_FAMILIES:
            continue
        ers = [result.elements[i] for i in idx]
        ends = [frame.nodes[frame.elements[i].n1] for i in idx] + [frame.nodes[frame.elements[i].n2] for i in idx]
        A, B = max(((p, q) for p in ends for q in ends), key=lambda pq: math.dist(*pq))
        A, B = np.asarray(A, float), np.asarray(B, float)
        chord = B - A
        L = float(np.linalg.norm(chord)) or sum(er.length for er in ers)
        pts = np.vstack([er.stations for er in ers])
        t = np.clip((pts - A) @ chord / L ** 2, 0.0, 1.0)
        order = np.argsort(t, kind="stable")
        N = np.concatenate([er.N for er in ers])[order]
        My = np.concatenate([er.My for er in ers])[order]
        Mz = np.concatenate([er.Mz for er in ers])[order]
        Vy = Vz = None
        if all(getattr(er, "Vy", None) is not None and getattr(er, "Vz", None) is not None for er in ers):
            Vy = np.concatenate([er.Vy for er in ers])[order]
            Vz = np.concatenate([er.Vz for er in ers])[order]
        res = member_check(e0.section, e0.material, L, t[order], N, My, Mz, gm0, gm1, plastic, fabrication, Vy, Vz)
        for er in ers:
            er.utilization = res["utilization"]
            er.util_detail = dict(res["detail"])
