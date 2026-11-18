"""Independent hand calculations for the native engine and its results tables (validate(detail=True)).

Each case is a textbook closed form worked here from first principles, not from the solver's own
code, so a wrong formula in the engine cannot also hide in the expected value."""
import math

import numpy as np

import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from tests.test_stability import portal_model

E, FY, GAM = 210e6, 235e3, 78.5                       # kN/m2, kN/m2, kN/m3 (S235)
SEC = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.008}
S = fs.chs(219.1, 8.0)
A, I, WEL = S.A, S.Iy, S.Wel_y
W = GAM * A                                           # self weight per metre, kN/m


def model(points, anchors, span):
    return {"status": "ok", "shells": 0, "tolerance_m": 0.001, "max_member_span_m": span, "max_span_m": span,
            "warnings": [], "anchor_points": anchors,
            "members": [{"source_guids": ["m"], "points": points, "section": SEC}]}


def simply_supported(L=6.0, **kw):
    m = model([[0, 0, 3], [L, 0, 3]], [[0, 0, 3], [L, 0, 3]], L)
    return ns.validate(m, "beam", 0.0, fixed_supports=False, self_weight=True, stability="off", detail=True, **kw)


def test_simply_supported_beam_under_self_weight():
    L = 6.0
    r = simply_supported(L)
    b = r["members"][0]
    assert b["m_max_knm"] == pytest.approx(1.35 * W * L ** 2 / 8, rel=2e-3)
    assert b["v_max_kn"] == pytest.approx(1.35 * W * L / 2, rel=2e-3)
    assert b["deflection_mm"] == pytest.approx(5 * W * L ** 4 / (384 * E * I) * 1000, rel=2e-3)
    assert b["deflection_ratio"] == pytest.approx(L / (5 * W * L ** 4 / (384 * E * I)), rel=5e-3)
    assert b["utilization"] == pytest.approx(1.35 * W * L ** 2 / 8 / (WEL * FY), rel=5e-3)
    assert sum(s["sls"]["Fz"] for s in r["supports"]) == pytest.approx(W * L, rel=2e-3)
    assert sum(s["uls"]["ULS 6.10"]["Fz"] for s in r["supports"]) == pytest.approx(1.35 * W * L, rel=2e-3)


def test_cantilever_tip_load():
    L, P = 3.0, 10.0
    r = ns.validate(model([[0, 0, 3], [L, 0, 3]], [[0, 0, 3]], L), "beam", P, fixed_supports=True,
                    self_weight=False, stability="off", detail=True)
    c = r["members"][0]
    tip = P * L ** 3 / (3 * E * I)
    assert c["m_max_knm"] == pytest.approx(1.5 * P * L, rel=1e-3)
    assert c["v_max_kn"] == pytest.approx(1.5 * P, rel=1e-3)
    assert c["max_displacement_mm"] == pytest.approx(tip * 1000, rel=1e-3)
    # deflection relative to what supports the member: a cantilever's root, so the full tip deflection (its
    # displaced chord turns with it and would read only 0.19 x tip)
    assert c["deflection_mm"] == pytest.approx(tip * 1000, rel=1e-3)
    assert r["results"]["max_deflection_mm"] == pytest.approx(tip * 1000, rel=1e-3)
    assert abs(r["supports"][0]["uls"]["ULS 6.10"]["My"]) == pytest.approx(1.5 * P * L, rel=1e-3)


def test_shear_is_read_at_both_member_ends():
    """A cantilever drawn from its tip to its base: zero shear at the start, 1.35 wL at the end."""
    L = 3.0
    r = ns.validate(model([[L, 0, 3], [0, 0, 3]], [[0, 0, 3]], L), "beam", 0.0, fixed_supports=True,
                    self_weight=True, stability="off", detail=True)
    assert r["members"][0]["v_max_kn"] == pytest.approx(1.35 * W * L, rel=2e-3)


@pytest.mark.parametrize("fabrication, alpha", [("hot_finished", 0.21), ("cold_formed", 0.49)])
@pytest.mark.parametrize("stability", ["off", "auto"])
def test_column_flexural_buckling(fabrication, alpha, stability):
    """Curve a (hot-finished) or c (cold-formed, the default); the buckling length is the whole
    4 m member also when the stability check splits it into pieces."""
    L, P = 4.0, 300.0
    r = ns.validate(model([[0, 0, 0], [0, 0, L]], [[0, 0, 0]], L), "frame", P, fixed_supports=True,
                    self_weight=False, stability=stability, detail=True, fabrication=fabrication)
    k = r["members"][0]
    lam = math.sqrt(A * FY / (math.pi ** 2 * E * I / L ** 2))
    phi = 0.5 * (1 + alpha * (lam - 0.2) + lam ** 2)
    chi = 1 / (phi + math.sqrt(phi ** 2 - lam ** 2))
    assert k["n_compression_kn"] == pytest.approx(1.5 * P, rel=1e-6)
    assert k["buckling_length_m"] == pytest.approx(L)
    assert k["slenderness"] == pytest.approx(lam, abs=2e-3)
    assert k["chi"] == pytest.approx(chi, abs=2e-3)
    if stability == "off":                                     # no imperfection moments: N/(chi A fy)
        assert k["utilization"] == pytest.approx(1.5 * P / (chi * A * FY), rel=5e-3)


def test_en1990_6_10a_and_6_10b_totals():
    L, Q = 6.0, 10.0
    m = model([[0, 0, 3], [L / 2, 0, 3], [L, 0, 3]], [[0, 0, 3], [L, 0, 3]], L)
    r = ns.validate(m, "beam", Q, fixed_supports=False, self_weight=True, stability="off", uls="6.10ab", detail=True)
    G = W * L
    total = {k: sum(s["uls"][k]["Fz"] for s in r["supports"]) for k in r["supports"][0]["uls"]}
    assert total["ULS 6.10a"] == pytest.approx(1.35 * G + 0.7 * 1.5 * Q, rel=2e-3)
    assert total["ULS 6.10b"] == pytest.approx(0.85 * 1.35 * G + 1.5 * Q, rel=2e-3)


def test_sway_imperfection_four_columns():
    f = fs.Frame()
    for x, y in ((0, 0), (6, 0), (0, 5), (6, 5)):
        a, t = f.add_node((x, y, 0)), f.add_node((x, y, 3.085))
        f.add_element(a, t, S, fs.material("Steel"))
    assert ns.sway_imperfection(f)["phi"] == pytest.approx(1 / 200 * math.sqrt(0.5 * (1 + 1 / 4)), rel=1e-9)


def test_second_order_between_alpha_cr_1_and_10():
    """EN 1993-1-1 5.2.1(3): alpha_cr = 6.7 (< 10) must switch the ULS analysis to second order."""
    r = ns.validate(portal_model(139.7, 5.0), "frame", 40, fixed_supports=False, self_weight=False)
    st = r["results"]["stability"]
    assert 5 < st["min_alpha_cr"] < 10 and st["method"] == "second-order (P-Delta)"
    stiff = ns.validate(portal_model(168.3, 5.0), "frame", 40, fixed_supports=False, self_weight=False)
    assert stiff["results"]["stability"]["min_alpha_cr"] >= 10
    assert stiff["results"]["stability"]["method"] == "first-order"


# ------------------------------------------------------------------ EN 1993-1-1 Table B.3 Cm, one case per row
# Each frame is a single steel member (one or more analysis elements, one lineage) under axial compression;
# Cm and eq. (6.61) are worked here from the closed-form moment diagram and the standard's text.
STEEL = fs.Material("S235", E, 80.76e6, GAM, FY, "steel")
PIN_A, ROLLER_B = (True, True, True, True, False, False), (False, True, True, False, False, False)


def chi_c(lam):
    """6.3.1.2, curve c (cold-formed hollow section), written out independently."""
    phi = 0.5 * (1 + 0.49 * (lam - 0.2) + lam ** 2)
    return 1.0 if lam <= 0.2 else min(1.0, 1 / (phi + math.sqrt(phi ** 2 - lam ** 2)))


def eq_6_61(L, ned, med, cm):
    """N/(chi N_Rk) + kyy M/M_Rk for a CHS, elastic moduli, Annex B Table B.1 (Class 3 column)."""
    lam = math.sqrt(A * FY / (math.pi ** 2 * E * I / L ** 2))
    n = ned / (chi_c(lam) * A * FY)
    kyy = cm * min(1 + 0.6 * lam * n, 1 + 0.6 * n)
    return n + kyy * med / (WEL * FY)


def member_frame(points, supports, P):
    """One member through ``points`` (x, 0, z), compressed by P along x at its last point."""
    f = fs.Frame()
    ns_ = [f.add_node(p) for p in points]
    for a, b in zip(ns_, ns_[1:]):
        f.add_element(a, b, S, STEEL, group=0)
    for n, dofs in supports.items():
        f.fix(ns_[n], dofs)
    f.load(ns_[-1], fx=-P)
    return f, ns_


def checked(f):
    r = fs.solve(f, combination={"Q": 1.0})
    from almond_mcp import ec3
    ec3.apply(f, r)
    return r.elements[0].util_detail, r


def test_table_b3_row1_linear_end_moments():
    """End moments M and psi M, no transverse load: Cm = 0.6 + 0.4 psi (psi = 0.5 -> 0.8)."""
    L, P, M = 4.0, 300.0, 20.0
    f, n = member_frame([(0, 0, 0), (L, 0, 0)], {0: PIN_A, 1: ROLLER_B}, P)
    f.load(n[0], my=M)
    f.load(n[1], my=-0.5 * M)
    d, _ = checked(f)
    assert d["cm_y"] == pytest.approx(0.6 + 0.4 * 0.5) and d["cm_y_basis"].startswith("linear")
    assert d["eq_6_61"] == pytest.approx(eq_6_61(L, P, M, 0.8), rel=1e-6)


def test_table_b3_row2_udl_with_end_moments():
    """Fixed-ended member, UDL q: Mh = -qL^2/12 at both ends (psi = 1), Ms = +qL^2/24, alpha_s = -1/2:
    uniform load, psi >= 0: Cm = 0.1 - 0.8 alpha_s = 0.5 (the 2 % rule read 1.0)."""
    L, P, q = 4.0, 300.0, 10.0
    fixed, slide = (True,) * 6, (False, True, True, True, True, True)
    f, n = member_frame([(0, 0, 0), (L / 2, 0, 0), (L, 0, 0)], {0: fixed, 2: slide}, P)
    for ei in range(len(f.elements)):
        f.udl(ei, (0, 0, -q))
    d, _ = checked(f)
    assert d["cm_y"] == pytest.approx(0.1 - 0.8 * (-0.5), rel=1e-6)
    assert "uniform" in d["cm_y_basis"] and "alpha_s = -0.50" in d["cm_y_basis"]
    assert d["eq_6_61"] == pytest.approx(eq_6_61(L, P, q * L ** 2 / 12, 0.5), rel=1e-6)


def test_table_b3_row3_point_load_at_mid_span():
    """Pin-ended member, point load F at mid-span (a joint between its two elements): Mh = 0,
    Ms = FL/4, alpha_h = 0, concentrated load: Cm = 0.90 + 0.10 alpha_h = 0.90."""
    L, P, F = 4.0, 300.0, 20.0
    f, n = member_frame([(0, 0, 0), (L / 2, 0, 0), (L, 0, 0)], {0: PIN_A, 2: ROLLER_B}, P)
    f.load(n[1], fz=-F)
    d, _ = checked(f)
    assert d["cm_y"] == pytest.approx(0.90) and d["cm_y_basis"].startswith("concentrated")
    assert d["eq_6_61"] == pytest.approx(eq_6_61(L, P, F * L / 4, 0.90), rel=1e-6)


def test_table_b3_cantilever_sways():
    """Flagpole: fixed base, free top, axial P and a horizontal tip load H. The diagram is linear
    (psi = 0, non-sway row 1 would give 0.6) but the member buckles in a sway mode: Cm = 0.9."""
    L, P, H = 3.0, 200.0, 5.0
    f = fs.Frame()
    a, b = f.add_node((0, 0, 0)), f.add_node((0, 0, L))
    f.add_element(a, b, S, STEEL)
    f.fix(a)
    f.load(b, fz=-P, fx=H)
    d, _ = checked(f)
    assert d["cm_y"] == pytest.approx(0.9) and "sway" in d["cm_y_basis"]
    assert d["eq_6_61"] == pytest.approx(eq_6_61(L, P, H * L, 0.9), rel=1e-6)


def test_table_b3_curved_member_like_vault_m56():
    """A curved member as four chords (the diagrid vault's M56 shape): N = 32 kN along the chord,
    rise e = 70 mm at mid-span, pinned ends. M = N z(x): zero at the ends, N e = 2.24 kNm at
    mid-span, kinked at three chord joints -> distributed load (more than two kinks), row 3 with
    alpha_h = 0: Cm = 0.95 instead of the old 1.0. The chords carry the thrust N along their own axes,
    N cos(theta) (no vertical reaction), most in the two middle chords."""
    L, N, e = 2.0, 32.0, 0.070
    R = (L ** 2 / 4 + e ** 2) / (2 * e)                       # circle through the ends and the crown
    xs = np.linspace(0, L, 5)
    pts = [(x, 0, math.sqrt(R ** 2 - (x - L / 2) ** 2) - (R - e)) for x in xs]
    f, n = member_frame(pts, {0: PIN_A, 4: ROLLER_B}, N)
    d, r = checked(f)
    my = max(float(np.max(np.abs(er.My))) for er in r.elements)
    assert my == pytest.approx(N * e, rel=1e-6)
    assert d["cm_y"] == pytest.approx(0.95) and d["cm_y_basis"].startswith("uniform")
    theta = math.atan2(pts[2][2] - pts[1][2], xs[2] - xs[1])
    assert d["eq_6_61"] == pytest.approx(eq_6_61(L, N * math.cos(theta), N * e, 0.95), rel=1e-6)
