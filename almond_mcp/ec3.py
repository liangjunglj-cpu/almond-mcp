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
  equivalent moment factors Cm from Table B.3, read from the member's own moment diagram: end
  moments Mh and psi Mh, mid-span moment Ms, and the transverse load on the member (none, uniform or
  concentrated) from the change of slope between its stations (``moment_diagram``); Cm >= 0.4.
  A member with a free end (a cantilever) buckles in a sway mode: Cm = 0.9 (Table B.3 note). Frame
  sway is in the global second-order analysis (5.2.2(3)b), so other members take the non-sway rows.
  Diagrams the table does not draw (a concentrated moment inside the member, a peak away from both
  the ends and mid-span) take its upper bound 1.0.
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


JUMP_TOL = 0.02          # a step in M under 2 % of the peak moment is not a concentrated moment
NOISE = 1e-6             # transverse load below 1e-6 of the peak moment's worth is round-off: no load
SWAY_CM = 0.9            # Table B.3 note: members with a sway buckling mode


def moment_diagram(t: np.ndarray, M: np.ndarray) -> dict:
    """What Table B.3 needs from a member's moment diagram, read from its stations alone.

    ``t`` (0..1 along the member, ascending) and ``M`` are the stations of the member's analysis
    elements in order; a station repeated at the same t is a joint between two elements. Between
    stations the change of slope is transverse load: spread evenly over the stations it is a
    distributed load, standing out at single stations it is a point load (a load at a joint, a
    member framing in, the kink of a curved member's chords under axial force). A step in M at a
    joint is a concentrated moment, which Table B.3 does not cover.

    Returns mh (the larger end moment), psi (other end / mh), ms (moment at mid-span), peak, load
    ("none", "uniform" or "concentrated") and jump (a concentrated moment inside the member)."""
    t, M = np.asarray(t, float), np.asarray(M, float)
    peak = float(np.max(np.abs(M))) if len(M) else 0.0
    m0, m1 = (float(M[0]), float(M[-1])) if len(M) else (0.0, 0.0)
    mh, mo = (m0, m1) if abs(m0) >= abs(m1) else (m1, m0)
    out = {"mh": mh, "psi": mo / mh if abs(mh) > 1e-12 * max(peak, 1.0) else 1.0, "ms": 0.0, "peak": peak,
           "load": "none", "jump": False}
    if peak < 1e-9 or len(M) < 2:
        return out
    dt, dM = np.diff(t), np.diff(M)
    joint = dt <= 1e-9
    out["jump"] = bool(np.any(np.abs(dM[joint]) > JUMP_TOL * peak))
    keep = np.concatenate([[True], ~joint])                   # one station per position (equal unless a jump)
    tu, Mu = t[keep], M[keep]
    out["ms"] = float(np.interp(0.5, tu, Mu))
    if len(tu) < 3:
        return out
    h = np.diff(tu)
    slope = np.diff(Mu) / h
    kink = np.abs(np.diff(slope))                              # transverse load at each interior station (t units)
    width = 0.5 * (h[:-1] + h[1:])
    spread = float(np.median(kink / width)) if len(kink) >= 3 else 0.0
    even = np.minimum(kink, spread * width)
    point = kink - even
    distributed, concentrated = float(np.sum(even)), float(np.sum(point))
    # moment each would put at mid-span of a simple span: q/8 for a distributed load, P/4 for a point load
    effect_q, effect_p = distributed / 8.0, concentrated / 4.0
    if effect_q + effect_p <= NOISE * peak:                   # rows 2/3 meet row 1 as the load goes to zero,
        return out                                            # so no threshold beyond round-off is needed
    points = int(np.sum(point > 0.1 * concentrated)) if concentrated > 0 else 0
    out["load"] = "concentrated" if effect_q <= 0.05 * effect_p and points <= 2 else "uniform"
    return out


def table_b3(mh: float, psi: float, ms: float, load: str) -> float:
    """EN 1993-1-1 Table B.3 Cm (non-sway). Row 1 (load "none"): linear diagram, Mh and psi Mh at the
    ends. Rows 2 and 3 (uniform or concentrated transverse load): the end moments with the mid-span
    moment Ms, alpha_s = Ms/Mh when |Ms| < |Mh| and alpha_h = Mh/Ms otherwise. Cm >= 0.4."""
    if load == "none":
        return max(0.4, 0.6 + 0.4 * psi)
    uniform = load != "concentrated"                          # anything but clear point loads: the higher column
    if abs(ms) < abs(mh):                                     # row 2: the end moment governs
        a = ms / mh
        if a >= 0:
            cm = 0.2 + 0.8 * a
        elif psi >= 0:
            cm = 0.1 - 0.8 * a if uniform else -0.8 * a
        else:
            cm = 0.1 * (1 - psi) - 0.8 * a if uniform else -0.2 * psi - 0.8 * a
        return max(0.4, cm)
    a = mh / ms if abs(ms) > 0 else 0.0                       # row 3: the span moment governs
    if a < 0 and psi < 0:
        a *= 1 + 2 * psi
    return max(0.4, 0.95 + 0.05 * a if uniform else 0.90 + 0.10 * a)


def moment_factor(t: np.ndarray, M: np.ndarray, sway: bool = False) -> tuple[float, str]:
    """Cm about one axis and the Table B.3 case it came from."""
    d = moment_diagram(t, M)
    if d["peak"] < 1e-9:
        return 1.0, "no moment"
    if sway:
        return SWAY_CM, "sway buckling mode (free end)"
    if d["jump"]:
        return 1.0, "concentrated moment in the span: outside Table B.3, upper bound"
    if d["load"] != "none" and max(abs(d["mh"]), abs(d["ms"])) < 0.4 * d["peak"]:
        return 1.0, "peak away from the ends and mid-span: outside Table B.3, upper bound"
    cm = table_b3(d["mh"], d["psi"], d["ms"], d["load"])
    psi = f", psi = {d['psi']:.2f}" if abs(d["mh"]) > 1e-9 * d["peak"] else ""
    if d["load"] == "none":
        return cm, f"linear{psi}"
    if abs(d["ms"]) < abs(d["mh"]):
        return cm, f"{d['load']} load, alpha_s = {d['ms'] / d['mh']:.2f}{psi}"
    return cm, f"{d['load']} load, alpha_h = {d['mh'] / d['ms']:.2f}{psi}"


def equivalent_moment_factor(t: np.ndarray, M: np.ndarray, sway: bool = False) -> float:
    """Table B.3 equivalent uniform moment factor of one moment diagram (see ``moment_factor``)."""
    return moment_factor(t, M, sway)[0]


def member_check(section, material, length: float, t: np.ndarray, N: np.ndarray, My: np.ndarray, Mz: np.ndarray,
                 gamma_m0: float = 1.0, gamma_m1: float = 1.0, plastic: bool = False,
                 fabrication: str = "cold_formed", sway: bool = False) -> dict:
    """Utilization and the working of one steel member: stations ordered along the member
    (t in 0..1; a repeated t is a joint between analysis elements), forces N (tension +), My, Mz in
    kN and kNm. ``sway``: the member buckles in a sway mode (a free end), Cm = 0.9."""
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
        (cm_y, basis_y), (cm_z, basis_z) = moment_factor(t, My, sway), moment_factor(t, Mz, sway)
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
                    "chi_z": chi_z, "cm_y": cm_y, "cm_z": cm_z, "cm_y_basis": basis_y, "cm_z_basis": basis_z,
                    "kyy": kyy, "kzz": kzz, "kyz": kyz, "kzy": kzy,
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


def free_end(frame, idx: list, touching: dict | None = None) -> bool:
    """Does the member (its analysis elements ``idx``) have an end that nothing holds: no support
    or spring that restrains a translation, and no other element attached (a cantilever's tip)?"""
    if touching is None:
        touching = _touching(frame)
    own = [n for i in idx for n in (frame.elements[i].n1, frame.elements[i].n2)]
    for n in {n for n in own if own.count(n) == 1}:
        held = any(frame.supports.get(n, (False,) * 6)[:3]) or any(k > 0 for k in frame.springs.get(n, (0.0,) * 6)[:3])
        if not held and touching.get(n, 0) <= own.count(n):
            return True
    return False


def _touching(frame) -> dict:
    out: dict = {}
    for e in frame.elements:
        for n in (e.n1, e.n2):
            out[n] = out.get(n, 0) + 1
    return out


def apply(frame, result, member_groups: dict | None = None, plastic: bool = False,
          fabrication: str = "cold_formed") -> None:
    """Replace the element-level checks of steel members in ``result`` by member checks (in place)."""
    gm0, gm1 = getattr(frame, "gamma_m", (1.0, 1.0))
    touching = _touching(frame)
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
        res = member_check(e0.section, e0.material, L, t[order], N, My, Mz, gm0, gm1, plastic, fabrication,
                           sway=free_end(frame, idx, touching))
        for er in ers:
            er.utilization = res["utilization"]
            er.util_detail = dict(res["detail"])
