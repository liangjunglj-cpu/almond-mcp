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
  transverse load take the table's upper bound 1.0).
Not checked: lateral-torsional buckling, shear (6.2.6), torsion, local bow imperfections in the
global analysis, aluminium to EN 1999 (aluminium members use these steel rules, flagged)."""
from __future__ import annotations

import math

import numpy as np

ALPHA = {"a0": 0.13, "a": 0.21, "b": 0.34, "c": 0.49, "d": 0.76}
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
                 fabrication: str = "cold_formed") -> dict:
    """Utilization and the working of one steel member: stations ordered along the member
    (t in 0..1), forces N (tension +), My, Mz in kN and kNm."""
    fy, E, s = material.fy, material.E, section
    cls = classify(s, fy, N, My, Mz)
    use_plastic = bool(plastic) and cls is not None and cls <= 2
    Wy, Wz = (s.Wpl_y, s.Wpl_z) if use_plastic else (s.Wel_y, s.Wel_z)
    if s.shape == "chs":
        m_cs = np.hypot(My, Mz) / (Wy * fy / gamma_m0)
    else:
        m_cs = np.abs(My) / (Wy * fy / gamma_m0) + np.abs(Mz) / (Wz * fy / gamma_m0)
    cross = float(np.max(np.abs(N) / (s.A * fy / gamma_m0) + m_cs))
    sig = np.abs(N) / s.A + (np.hypot(My, Mz) / s.Wel_y if s.shape == "chs"
                             else np.abs(My) / s.Wel_y + np.abs(Mz) / s.Wel_z)
    out = {"class": cls, "moduli": "plastic" if use_plastic else "elastic", "cross_section": cross,
           "max_stress_mpa": float(np.max(sig)) / 1000.0, "length_cr_m": length, "fabrication": fabrication}
    util, check = cross, "cross-section"
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
    out["governing_check"] = check
    return {"utilization": util, "detail": out}


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
        res = member_check(e0.section, e0.material, L, t[order], N, My, Mz, gm0, gm1, plastic, fabrication)
        for er in ers:
            er.utilization = res["utilization"]
            er.util_detail = dict(res["detail"])
