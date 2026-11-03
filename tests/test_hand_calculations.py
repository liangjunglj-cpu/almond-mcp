"""Independent hand calculations for the native engine and its results tables (validate(detail=True)).

Each case is a textbook closed form worked here from first principles, not from the solver's own
code, so a wrong formula in the engine cannot also hide in the expected value."""
import math

import numpy as np
import pytest

from almond_mcp import ec3
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
    """5.3.2(3)b: m counts the columns in a row (one vertical plane parallel to the sway). Four columns
    on a 6 x 5 grid stand in two rows of two either way: m = 2, alpha_m = sqrt(0.5 (1 + 1/2)) = 0.866;
    h = 3.085 m gives alpha_h = 2 / sqrt(3.085) = 1.139 -> 1.0. phi = 1/200 x 0.866 = 0.004330."""
    f = fs.Frame()
    for x, y in ((0, 0), (6, 0), (0, 5), (6, 5)):
        a, t = f.add_node((x, y, 0)), f.add_node((x, y, 3.085))
        f.add_element(a, t, S, fs.material("Steel"))
    imp = ns.sway_imperfection(f)
    assert imp["m_x"] == imp["m_y"] == 2
    assert imp["phi_x"] == imp["phi_y"] == pytest.approx(1 / 200 * math.sqrt(0.5 * (1 + 1 / 2)), rel=1e-9)


def test_second_order_between_alpha_cr_1_and_10():
    """EN 1993-1-1 5.2.1(3): alpha_cr = 6.7 (< 10) must switch the ULS analysis to second order."""
    r = ns.validate(portal_model(139.7, 5.0), "frame", 40, fixed_supports=False, self_weight=False)
    st = r["results"]["stability"]
    assert 5 < st["min_alpha_cr"] < 10 and st["method"] == "second-order (P-Delta)"
    stiff = ns.validate(portal_model(168.3, 5.0), "frame", 40, fixed_supports=False, self_weight=False)
    assert stiff["results"]["stability"]["min_alpha_cr"] >= 10
    assert stiff["results"]["stability"]["method"] == "first-order"


# ------------------------------------------------------------------ 5.3.2(3)b: m counts loaded columns only
def row_of_columns(xs, h=4.0):
    f = fs.Frame()
    for x in xs:
        a, t = f.add_node((x, 0, 0)), f.add_node((x, 0, h))
        f.add_element(a, t, S, fs.material("Steel"))
    return f


def test_sway_m_counts_columns_with_half_the_average_load():
    """EN 1993-1-1 5.3.2(3)b: m = columns carrying N_Ed >= 50 % of the average in the plane considered.
    Row of three, N_Ed = 10, 100, 10 kN: average 40, half 20 -> only the middle one counts, m = 1,
    alpha_m = 1.0. h = 4 m: alpha_h = 2 / sqrt(4) = 1.0, so phi_x = 1/200. With 30, 100, 30 kN the
    average is 53.3 (half 26.7) and all three count: m = 3, alpha_m = sqrt(0.5 (1 + 1/3)) = 0.8165."""
    f = row_of_columns([0, 5, 10])
    imp = ns.sway_imperfection(f, np.array([-10.0, -100.0, -10.0]))
    assert imp["m_x"] == 1 and imp["phi_x"] == pytest.approx(1 / 200, rel=1e-12)
    imp = ns.sway_imperfection(f, np.array([-30.0, -100.0, -30.0]))
    assert imp["m_x"] == 3 and imp["phi_x"] == pytest.approx(1 / 200 * math.sqrt(0.5 * (1 + 1 / 3)), rel=1e-12)
    # sway along y: each column is its own plane (a row of one), m = 1, phi_y = 1/200
    assert imp["m_y"] == 1 and imp["phi_y"] == pytest.approx(1 / 200, rel=1e-12)


def test_sway_m_from_the_combination_loads():
    """The analysis counts m from the ULS axial forces: 10 kN on each outer column, 100 kN in the middle
    (G, x 1.35): the outer columns carry 13.5 kN < 0.5 x 54 kN, so m_x = 1 and phi_x = 1/200."""
    f = row_of_columns([0, 5, 10])
    for top, p in ((1, 10.0), (3, 100.0), (5, 10.0)):
        f.load(top, fz=-p, case="G")
        f.fix(top, (True, True, False, False, False, False))
    for base in (0, 2, 4):
        f.fix(base)
    _, _, _, rep = ns._solve_design(f, "en1990", None)
    imp = rep["sway_imperfections"]["ULS 6.10"]
    assert imp["m_x"] == 1 and imp["phi_x"] == pytest.approx(1 / 200)


# ------------------------------------------------------------------ 6.2.6 shear, 6.2.8 bending and shear
@pytest.mark.parametrize("section, av_y_mm2, av_z_mm2", [
    # rolled I without root radii, (a): A - 2 b tf + tw tf = 5188.06 - 3210 + 75.97 = 2054.03 >= hw tw = 1978.06;
    # parallel to the flanges, (e): A - hw tw = 2 b tf = 3210
    (fs.i_section(300, 150, 7.1, 10.7), 3210.0, 2054.03),
    # RHS 200 x 100 x 8, (f): A = 4544; A h / (b + h) = 3029.33 along the depth, A b / (b + h) = 1514.67
    (fs.rhs(200, 100, 8), 1514.67, 3029.33),
    # CHS 219.1 x 8, (g): A = 5305.5; 2 A / pi = 3377.6
    (fs.chs(219.1, 8), 3377.6, 3377.6),
    # solid bar 100 x 200, (h): A = 20000
    (fs.rect(100, 200), 20000.0, 20000.0),
])
def test_shear_areas_6_2_6_3(section, av_y_mm2, av_z_mm2):
    av_y, av_z = ec3.shear_areas(section)
    assert av_y * 1e6 == pytest.approx(av_y_mm2, abs=0.01) and av_z * 1e6 == pytest.approx(av_z_mm2, abs=0.01)


def short_box_beam(L=0.3, P=200.0):
    """RHS 200 x 100 x 5 (S235), simply supported, point load P at midspan (Q, x 1.5 at ULS)."""
    m = model([[0, 0, 3], [L / 2, 0, 3], [L, 0, 3]], [[0, 0, 3], [L, 0, 3]], L)
    m["members"][0]["section"] = {"shape": "box", "height": 0.2, "width": 0.1, "wall": 0.005}
    return ns.validate(m, "beam", P, fixed_supports=False, self_weight=False, stability="off", detail=True)


def test_shear_resistance_6_2_6():
    """EN 1993-1-1 6.2.6(2), (6.18): V_pl,Rd = A_v (fy / sqrt 3) / gamma_M0. RHS 200 x 100 x 5: A = 2900 mm2,
    A_v = A h / (b + h) = 1933.3 mm2 (6.2.6(3)f), V_pl,Rd = 1933.3 x 235 / sqrt 3 = 262.31 kN.
    P = 100 kN at midspan: V_Ed = 1.5 x 100 / 2 = 75 kN, utilization 75 / 262.31 = 0.2859."""
    row = short_box_beam(P=100.0)["members"][0]
    vpl = 2900e-6 * 200 / 300 * 235e3 / math.sqrt(3)
    assert vpl == pytest.approx(262.31, abs=0.01)
    assert row["v_pl_rd_kn"][1] == pytest.approx(vpl, abs=1e-3)
    assert row["shear_utilization"] == pytest.approx(75.0 / vpl, rel=1e-3)
    assert row["shear_rho"] == 0.0 and row["shear_buckling"] is False      # hw/t = 190/5 = 38 <= 72


def test_bending_with_high_shear_6_2_8():
    """EN 1993-1-1 6.2.8(3): V_Ed = 1.5 x 280 / 2 = 210 kN > 0.5 V_pl,Rd = 131.2 kN, so
    rho = (2 x 210 / 262.31 - 1)^2 = 0.3626 and the elastic resistance falls to (1 - rho) W_el fy:
    W_el = I / (h/2) = 15.224e6 / 100 = 152242 mm3, M_el,Rd = 35.78 kNm, M_V,Rd = 22.80 kNm.
    M_Ed = 210 x 0.15 = 31.5 kNm at midspan: utilization 31.5 / 22.80 = 1.381 (1.5 x 280 x 0.3 / 4)."""
    row = short_box_beam(P=280.0)["members"][0]
    vpl = 262.31
    rho = (2 * 210.0 / vpl - 1) ** 2
    mv = (1 - rho) * 152241.67e-9 * 235e3
    assert row["shear_rho"] == pytest.approx(rho, rel=1e-3)
    assert row["cross_section_utilization"] == pytest.approx(31.5 / mv, rel=1e-3)
    assert row["shear_utilization"] == pytest.approx(210.0 / vpl, rel=1e-3)


def test_i_section_major_axis_6_30():
    """EN 1993-1-1 6.2.8(5), (6.30), plastic I-section 300 x 150 x 7.1 x 10.7 (Class 1 in bending, S235):
    W_pl,y = b tf (h - tf) + tw hw^2 / 4 = 150 x 10.7 x 289.3 + 7.1 x 278.6^2 / 4 = 602,098 mm3;
    V_pl,Rd = 2054.03 x 235 / sqrt 3 = 278.69 kN. V_Ed = 0.8 V_pl,Rd -> rho = (1.6 - 1)^2 = 0.36;
    M_y,V,Rd = (W_pl,y - rho A_w^2 / (4 tw)) fy = (602,098 - 0.36 x 137,772) x 235 = 129.84 kNm."""
    sec = fs.i_section(300, 150, 7.1, 10.7)
    steel = fs.material("S235")
    vpl = 2054.03e-6 * 235e3 / math.sqrt(3)
    wpl = (150 * 10.7 * 289.3 + 7.1 * 278.6 ** 2 / 4) * 1e-9
    mv = (wpl - 0.36 * 7.1 * 278.6 ** 2 / 4 * 1e-9) * 235e3
    assert mv == pytest.approx(129.84, abs=0.01)
    t, z = np.linspace(0, 1, 3), np.zeros(3)
    M, V = np.full(3, 100.0), np.full(3, 0.8 * vpl)
    det = ec3.member_check(sec, steel, 4.0, t, z, M, z, plastic=True, Vy=z, Vz=V)["detail"]
    assert det["moduli"] == "plastic" and det["rho"] == pytest.approx(0.36, rel=1e-5)
    assert det["cross_section"] == pytest.approx(100.0 / mv, rel=1e-4)
    # below half of V_pl,Rd shear does not reduce the moment resistance (6.2.8(2))
    det = ec3.member_check(sec, steel, 4.0, t, z, M, z, plastic=True, Vy=z, Vz=np.full(3, 0.49 * vpl))["detail"]
    assert det["rho"] == 0.0 and det["cross_section"] == pytest.approx(100.0 / (wpl * 235e3), rel=1e-4)
    # just past half: V_Ed = 0.55 V_pl,Rd, rho = (1.1 - 1)^2 = 0.01
    det = ec3.member_check(sec, steel, 4.0, t, z, M, z, plastic=True, Vy=z, Vz=np.full(3, 0.55 * vpl))["detail"]
    assert det["rho"] == pytest.approx(0.01, rel=1e-3)


@pytest.mark.parametrize("section, fy, flagged", [
    (fs.i_section(600, 200, 5, 15), 235e3, True),        # hw/tw = 570 / 5 = 114 > 72
    (fs.i_section(300, 150, 4.3, 10), 235e3, False),     # hw/tw = 280 / 4.3 = 65.1 <= 72
    (fs.i_section(300, 150, 4.3, 10), 355e3, True),      # 65.1 > 72 x sqrt(235/355) = 58.6
    (fs.rhs(300, 100, 3), 235e3, True),                  # (300 - 2 x 3) / 3 = 98 > 72
    (fs.chs(219.1, 8), 235e3, False),                    # tubes: EN 1993-1-6, not this rule
])
def test_shear_buckling_flag_6_2_6_6(section, fy, flagged):
    """EN 1993-1-1 6.2.6(6), (6.22): webs without stiffeners with hw/tw > 72 epsilon / eta (eta = 1.0, the
    6.2.6(3) Note's conservative value) need EN 1993-1-5; flagged as not covered."""
    assert ec3.shear_buckling(section, fy) is flagged


def test_shear_along_a_uniformly_loaded_beam():
    """Simply supported 6 m CHS under self weight (ULS 1.35 w): V = 1.35 w (L/2 - x), so 1.35 w L / 2 at the
    supports and zero at midspan."""
    f = fs.Frame()
    a, b = f.add_node((0, 0, 0)), f.add_node((6, 0, 0))
    f.add_element(a, b, S, fs.material("Steel"))
    f.fix(a, (True, True, True, True, False, False))
    f.fix(b, (False, True, True, False, False, False))
    f.gravity = (0, 0, -1)
    er = fs.solve(f, stations=13, combination={"G": 1.35}).elements[0]
    x = np.linspace(0, 6, 13)
    assert np.abs(er.Vz) == pytest.approx(np.abs(1.35 * W * (3 - x)), abs=1e-9)
    assert np.abs(er.Vy).max() == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------------------ 5.3.2(6)-(7) local bow imperfections
def test_bow_amplitudes_table_5_1():
    """Table 5.1, elastic analysis: e0/L = 1/350 (a0), 1/300 (a), 1/250 (b), 1/200 (c), 1/150 (d)."""
    for curve, denom in (("a0", 350), ("a", 300), ("b", 250), ("c", 200), ("d", 150)):
        assert ec3.bow_imperfection(curve, 6.0) == pytest.approx(6.0 / denom, rel=1e-12)


def column_frame(base="fixed", L=6.0):
    """Vertical CHS 219.1 x 8 column (S235), fixed or pinned at the base, held laterally at the top."""
    f = fs.Frame()
    b, t = f.add_node((0, 0, 0)), f.add_node((0, 0, L))
    f.add_element(b, t, S, fs.material("Steel"))
    f.fix(b, (True,) * 6 if base == "fixed" else (True, True, True, False, False, False))
    f.fix(t, (True, True, False, False, False, False))
    return f, b, t


NCR_H = math.pi ** 2 * E * I / 6.0 ** 2                      # 1703.94 kN: CHS 219.1 x 8, 6 m, hinged ends


def test_bow_condition_5_3_2_6():
    """5.3.2(6): bows where lambda_bar > 0.5 sqrt(A fy / N_Ed) and a moment-resistant end.
    CHS 219.1 x 8, L = 6 m: N_pl = 5305.5 x 235 = 1246.8 kN, N_cr (hinged) = 1703.9 kN,
    lambda_bar = sqrt(1246.8 / 1703.9) = 0.8554. N_Ed = 0.30 N_cr = 511.2 kN: limit 0.5 sqrt(1246.8 / 511.2)
    = 0.7809 < 0.8554 -> bow. N_Ed = 0.20 N_cr = 340.8 kN: limit 0.9563 -> no bow (the condition is
    N_Ed > N_cr / 4)."""
    need, lam, limit = ec3.bow_required(S, FY, E, 6.0, 0.30 * NCR_H, "y")
    assert need and lam == pytest.approx(0.8554, abs=1e-4) and limit == pytest.approx(0.7809, abs=1e-4)
    need, _, limit = ec3.bow_required(S, FY, E, 6.0, 0.20 * NCR_H, "y")
    assert not need and limit == pytest.approx(0.9563, abs=1e-4)
    f, _, _ = column_frame()                                 # fixed base: a moment-resistant end
    bows, skipped = ns.bow_plan(f, ec3.groups(f), np.array([-0.30 * NCR_H]))
    assert [a["axis"] for a in bows[0]["axes"]] == ["y", "z"] and bows[0]["axes"][0]["e0"] == pytest.approx(6.0 / 200)
    _, skipped = ns.bow_plan(f, ec3.groups(f), np.array([-0.20 * NCR_H]))
    assert skipped == {"lambda_bar <= 0.5 sqrt(A fy / N_Ed)": 2}
    f, _, _ = column_frame(base="pinned")                    # pinned at both ends: no moment-resistant end
    bows, skipped = ns.bow_plan(f, ec3.groups(f), np.array([-0.30 * NCR_H]))
    assert bows == [] and skipped == {"no moment-resistant end": 2}


def test_bow_equivalent_loads_first_order():
    """Figure 5.4: e0 as a uniform load 8 N e0 / L^2 with 4 N e0 / L against it at each end. On a column
    fixed at the base and held at the top (propped cantilever), the first-order base moment of the
    uniform load is q L^2 / 8 = N e0: N = 500 kN, e0 = 6 / 200 = 0.03 m -> 15 kNm."""
    f, base, _ = column_frame()
    bows, _ = ns.bow_plan(f, ec3.groups(f), np.array([-500.0]))
    asm = fs.prepare(f)
    H, w = ns.bow_loads(bows, (1, 0, 0), asm.ndof)
    assert H.reshape(-1, 6)[:, 0].sum() == pytest.approx(-8 * 500 * 0.03 / 6.0)          # ends: 2 x 4 N e0 / L
    assert w[0][0] * 6.0 == pytest.approx(8 * 500 * 0.03 / 6.0)                         # load: 8 N e0 / L
    r = fs.solve_linear(asm, {}, extra=H, member_loads=w)
    assert abs(r.reactions[base, 4]) == pytest.approx(500 * 0.03, rel=1e-9)
    assert np.abs(r.reactions[:, :3].sum(axis=0)).max() < 1e-9                          # self-equilibrating


def test_bow_in_the_second_order_analysis():
    """alpha_cr < 10 -> second order with the bow. Propped cantilever (fixed base, top held), N_Ed = 1.5 P
    = 0.3 N_cr,hinged = 511.2 kN: alpha_cr = 2.046 / 0.3 = 6.8. e0 = L/200 (cold-formed CHS, curve c) =
    30 mm, q = 8 N e0 / L^2. Base moment from the closed form of EI v'''' + N v'' = q with
    v(0) = v'(0) = 0, v(L) = v''(L) = 0: v = C1 + C2 x + C3 cos kx + C4 sin kx + q x^2 / (2N), k^2 = N/EI,
    M(0) = EI v''(0)."""
    L, N = 6.0, 0.3 * NCR_H
    f, base, top = column_frame()
    f.load(top, fz=-N / 1.5, case="Q")
    _, reps, _, rep = ns._solve_design(f, "en1990", None)
    assert 1 < rep["min_alpha_cr"] < 10 and rep["method"] == "second-order (P-Delta)"
    bow = rep["bow_imperfection"]["applied"]
    assert {b["axis"] for b in bow} == {"y", "z"} and all(b["e0_mm"] == pytest.approx(30.0) for b in bow)
    assert bow[0]["e0_over_l"] == "1/200" and bow[0]["n_ed_kn"] == pytest.approx(N, rel=1e-6)
    k = math.sqrt(N / (E * I))
    q = 8 * N * (L / 200) / L ** 2
    c, s_ = math.cos(k * L), math.sin(k * L)
    A_ = np.array([[1, 0, 1, 0], [0, 1, 0, k], [1, L, c, s_], [0, 0, -k * k * c, -k * k * s_]])
    C = np.linalg.solve(A_, [0, 0, -q * L ** 2 / (2 * N), -q / N])
    m_base = abs(E * I * (-k * k * C[2] + q / N))
    assert N * L / 200 < m_base < N * L / 200 / (1 - 1 / 6.8)                         # N e0, amplified
    got = max(abs(r.reactions[base, 3:5]).max() for _, _, r in reps)
    assert got == pytest.approx(m_base, rel=0.01)


def test_element_check_divides_buckling_resistance_by_gamma_m1():
    """EN 1993-1-1 6.3.1.1(3), (6.47): N_b,Rd = chi A fy / gamma_M1. frame_solver's element-level check (the
    one fs.solve applies) on a pin-ended 4 m CHS 219.1 x 8 under 300 kN, curve a (alpha 0.21), with
    gamma_M1 = 1.1: lambda = sqrt(A fy / (pi^2 E I / L^2)), utilization = 300 x 1.1 / (chi A fy)."""
    L, P = 4.0, 300.0
    f = fs.Frame()
    a, b = f.add_node((0, 0, 0)), f.add_node((0, 0, L))
    f.add_element(a, b, S, fs.material("Steel"))
    f.fix(a, (True, True, True, True, False, False))
    f.fix(b, (True, True, False, False, False, False))
    f.load(b, fz=-P, case="Q")
    f.gamma_m = (1.0, 1.1)
    lam = math.sqrt(A * FY / (math.pi ** 2 * E * I / L ** 2))
    phi = 0.5 * (1 + 0.21 * (lam - 0.2) + lam ** 2)
    chi = 1 / (phi + math.sqrt(phi ** 2 - lam ** 2))
    det = fs.solve(f).elements[0].util_detail
    assert det["buckling"] == pytest.approx(P * 1.1 / (chi * A * FY), rel=1e-6)


def test_member_table_deflection_is_relative_to_the_member_ends():
    """Without the support-path deflections, the results table measures a member's sag from its own displaced
    ends: a 6 m beam on sprung pins (kz = 2000 kN/m) under self weight sags 5 w L^4 / (384 EI) between its
    ends, while the springs settle a further w L / 2 / kz that must not count."""
    L, kz = 6.0, 2000.0
    m = model([[0, 0, 3], [L, 0, 3]], [[0, 0, 3], [L, 0, 3]], L)
    m["supports"] = [{"point_m": [0, 0, 3], "spec": f"pinned kz={kz:g}"}, {"point_m": [L, 0, 3], "spec": f"pinned kz={kz:g}"}]
    frame, _, _ = ns.build_frame(m, 0.0, "Steel", False, True)
    sls, _, envelope, _ = ns._solve_design(frame, "en1990", None, stability="off")
    row = ns.member_table(m, frame, sls, envelope)[0]
    assert row["deflection_mm"] == pytest.approx(5 * W * L ** 4 / (384 * E * I) * 1000, rel=2e-3)
    assert row["max_displacement_mm"] == pytest.approx((5 * W * L ** 4 / (384 * E * I) + W * L / 2 / kz) * 1000, rel=2e-3)


# ------------------------------------------------------------------ 6.3.2 lateral-torsional buckling
from almond_mcp import ltb  # noqa: E402

IPE = fs.i_section(300, 150, 7.1, 10.7)                     # I 300 x 150 x 7.1 x 10.7, no root radii
GS = 80.76e6                                                 # kN/m2, the solver's shear modulus for S235


def one_piece(L, M, q=0.0, n=201):
    s = np.linspace(0, L, n)
    return [{"s0": 0.0, "s1": L, "s": s, "M": M(s), "q0": q, "q1": q}]


def test_warping_constant_of_an_i_section():
    """Iw = tf b^3 (h - tf)^2 / 24 for two equal flanges: 10.7 x 150^3 x 289.3^2 / 24 = 1.2593e11 mm6."""
    assert IPE.Iw * 1e18 == pytest.approx(10.7 * 150 ** 3 * 289.3 ** 2 / 24, rel=1e-12)
    assert IPE.Iw * 1e18 == pytest.approx(1.2593e11, rel=1e-4)


def test_m_cr_uniform_moment_is_exact():
    """Uniform moment, fork supports (Timoshenko & Gere): M_cr = pi/L sqrt(E Iz G It (1 + pi^2 E Iw / (L^2 G It))).
    L = 6 m: 83.163 kNm."""
    L = 6.0
    exact = math.pi / L * math.sqrt(E * IPE.Iz * GS * IPE.J * (1 + math.pi ** 2 * E * IPE.Iw / (L ** 2 * GS * IPE.J)))
    assert exact == pytest.approx(83.163, abs=1e-3)
    r = ltb.critical_moment(E, GS, IPE.Iz, IPE.J, IPE.Iw, one_piece(L, np.ones_like))
    assert r["m_cr"] == pytest.approx(exact, rel=1e-6)


def test_m_cr_uniform_load_c1_and_load_height():
    """UDL on a simply supported span (ECCS / NCCI SN003, k = kw = 1): C1 = 1.13 at the shear centre; on the top
    flange (z_g = h/2 = 0.15 m) M_cr = C1 (pi^2 E Iz / L^2) [sqrt(Iw/Iz + L^2 G It / (pi^2 E Iz) + (C2 z_g)^2)
    - C2 z_g] with C2 = 0.454: 70.80 kNm. Below the shear centre the same load is stabilising."""
    L = 6.0
    k = math.pi ** 2 * E * IPE.Iz / L ** 2
    root = IPE.Iw / IPE.Iz + L ** 2 * GS * IPE.J / (math.pi ** 2 * E * IPE.Iz)
    diagram = one_piece(L, lambda s: s * (L - s) / 2, q=1.0)
    centre = ltb.critical_moment(E, GS, IPE.Iz, IPE.J, IPE.Iw, diagram)["m_cr"]
    assert centre / (k * math.sqrt(root)) == pytest.approx(1.13, rel=5e-3)
    top = ltb.critical_moment(E, GS, IPE.Iz, IPE.J, IPE.Iw, diagram, zg=0.15)["m_cr"]
    eccs = 1.127 * k * (math.sqrt(root + (0.454 * 0.15) ** 2) - 0.454 * 0.15)
    assert eccs == pytest.approx(70.80, abs=0.01)
    assert top == pytest.approx(eccs, rel=0.01)
    assert ltb.critical_moment(E, GS, IPE.Iz, IPE.J, IPE.Iw, diagram, zg=-0.15)["m_cr"] > centre > top


def test_m_cr_cantilever_tip_load():
    """Narrow rectangle (Iw ~ 0) cantilever, tip load at the shear centre (Timoshenko & Gere):
    P_cr = 4.013 sqrt(E Iz G It) / L^2; 20 x 200 mm, L = 3 m: 14.989 kN, M_cr = P_cr L."""
    L = 3.0
    R = fs.rect(20, 200)
    s = np.linspace(0, L, 61)
    r = ltb.critical_moment(E, GS, R.Iz, R.J, 0.0, [{"s0": 0.0, "s1": L, "s": s, "M": -(L - s), "q0": 0.0, "q1": 0.0}],
                            points=[(L, 1.0)], ends=("root", "free"))
    p_cr = 4.013 * math.sqrt(E * R.Iz * GS * R.J) / L ** 2
    assert p_cr == pytest.approx(14.989, abs=1e-3)
    assert r["m_cr"] / L == pytest.approx(p_cr, rel=1e-3)


def i_beam(L=6.0, P=40.0, extra=(), **kw):
    """Simply supported I 300 x 150 x 7.1 x 10.7 (S235) drawn with a midspan point, point load P there (Q)."""
    sec = {"shape": "i", "height": 0.3, "width": 0.15, "web": 0.0071, "flange": 0.0107}
    m = model([[0, 0, 3], [L / 2, 0, 3], [L, 0, 3]], [[0, 0, 3], [L, 0, 3]], L)
    m["members"][0]["section"] = sec
    m["members"] += [{"source_guids": [f"x{i}"], "points": pts, "section": sec} for i, pts in enumerate(extra)]
    m["anchor_points"] += [pts[-1] for pts in extra]
    return ns.validate(m, "beam", P, fixed_supports=False, self_weight=False, stability="off", detail=True, **kw)


def test_ltb_midspan_point_load_on_the_top_flange():
    """EN 1993-1-1 6.3.2.1-6.3.2.2. L = 6 m, P = 40 kN at midspan on the top flange: M_Ed = 1.5 x 40 x 6 / 4
    = 90 kNm. M_cr against ECCS (C1 = 1.365, C2 = 0.553, z_g = 0.15 m): 80.83 kNm, within 2 %.
    W_el,y = I_y / (h/2) = 79.99e6 / 150 = 533,266 mm3 (Class 1 but elastic design): lambda_LT = sqrt(W fy / M_cr); curve a (h/b = 2,
    Table 6.4, alpha_LT = 0.21); chi_LT from (6.56); M_b,Rd = chi_LT W fy; utilization 90 / M_b,Rd.
    The beam drawn in two pieces is one segment between its supports (forks at both ends)."""
    row = i_beam()["members"][0]
    L = 6.0
    k = math.pi ** 2 * E * IPE.Iz / L ** 2
    eccs = 1.365 * k * (math.sqrt(IPE.Iw / IPE.Iz + L ** 2 * GS * IPE.J / (math.pi ** 2 * E * IPE.Iz) + (0.553 * 0.15) ** 2)
                        - 0.553 * 0.15)
    assert eccs == pytest.approx(80.83, abs=0.01)
    assert row["m_cr_knm"] == pytest.approx(eccs, rel=0.02)
    assert row["ltb_length_m"] == pytest.approx(6.0) and row["ltb_ends"] == ["fork", "fork"] and row["ltb_curve"] == "a"
    wel = IPE.Wel_y
    assert wel * 1e9 == pytest.approx(533266, rel=1e-4)
    lam = math.sqrt(wel * FY / row["m_cr_knm"])
    phi = 0.5 * (1 + 0.21 * (lam - 0.2) + lam ** 2)
    chi = 1 / (phi + math.sqrt(phi ** 2 - lam ** 2))
    assert row["lambda_lt"] == pytest.approx(lam, abs=2e-3) and row["chi_lt"] == pytest.approx(chi, abs=2e-3)
    assert row["ltb_utilization"] == pytest.approx(90.0 / (chi * wel * FY), rel=2e-3)
    assert row["governing_check"] == "LTB 6.3.2" and row["utilization"] == row["ltb_utilization"]


def test_ltb_shear_centre_c1_point_load():
    """Same diagram with the load at the shear centre: C1 = 1.365 (ECCS, midspan point load), within 1 %."""
    L = 6.0
    s = np.linspace(0, L, 201)
    M = np.where(s < L / 2, s / 2, (L - s) / 2)
    pieces = [{"s0": 0.0, "s1": 3.0, "s": s[s <= 3], "M": M[s <= 3], "q0": 0.0, "q1": 0.0},
              {"s0": 3.0, "s1": 6.0, "s": s[s >= 3], "M": M[s >= 3], "q0": 0.0, "q1": 0.0}]
    k = math.pi ** 2 * E * IPE.Iz / L ** 2
    base = k * math.sqrt(IPE.Iw / IPE.Iz + L ** 2 * GS * IPE.J / (math.pi ** 2 * E * IPE.Iz))
    r = ltb.critical_moment(E, GS, IPE.Iz, IPE.J, IPE.Iw, pieces, [(3.0, 1.0)])
    assert r["m_cr"] / base == pytest.approx(1.365, rel=0.01)


def test_a_beam_framing_in_restrains_the_segment():
    """A secondary beam at midspan is a lateral restraint: two 3 m segments, forks at each end, M_cr far higher."""
    free = i_beam()["members"][0]
    held = i_beam(extra=[[[3.0, 0, 3], [3.0, 2.0, 3]]])["members"][0]
    assert held["ltb_length_m"] == pytest.approx(3.0) and held["m_cr_knm"] > 2.5 * free["m_cr_knm"]


def test_continuous_restraint_and_hollow_sections_skip_ltb():
    row = i_beam(lateral_restraint="continuous")["members"][0]
    assert row["ltb_utilization"] is None and row["governing_check"] == "cross-section"
    assert short_box_beam(P=100.0)["members"][0]["ltb_utilization"] is None        # RHS: not susceptible
    with pytest.raises(ValueError):
        ec3.apply(fs.Frame(), None, {}, lateral_restraint="sometimes")


def test_annex_b_table_b2_kzy_for_unrestrained_members():
    """EN 1993-1-1 Annex B, Table B.2 (members susceptible to torsional deformation), Class 3 (elastic):
    k_zy = 1 - 0.05 lambda_z n_z / (C_mLT - 0.25) >= 1 - 0.05 n_z / (C_mLT - 0.25), and M_y,Rk carries chi_LT
    in (6.61)/(6.62). I 300 x 150 x 7.1 x 10.7, L = 4 m, N = 100 kN, uniform My = 30 kNm (C_mLT = 1.0),
    M_cr = 120 kNm."""
    sec, steel, L = IPE, fs.material("S235"), 4.0
    t = np.linspace(0, 1, 5)
    N, My, z = np.full(5, -100.0), np.full(5, 30.0), np.zeros(5)
    det = ec3.member_check(sec, steel, L, t, N, My, z, ltb={"m_cr": 120.0, "m_ed": 30.0, "cm_lt": 1.0, "length": L,
                                                         "ends": ("fork", "fork"), "zg": 0.0})["detail"]
    lam_z = math.sqrt(sec.A * FY / (math.pi ** 2 * E * sec.Iz / L ** 2))
    phi = 0.5 * (1 + 0.34 * (lam_z - 0.2) + lam_z ** 2)                       # curve b about z (h/b > 1.2)
    chi_z = 1 / (phi + math.sqrt(phi ** 2 - lam_z ** 2))
    n_z = 100.0 / (chi_z * sec.A * FY)
    kzy = max(1 - 0.05 * lam_z * n_z / 0.75, 1 - 0.05 * n_z / 0.75)
    lam_lt = math.sqrt(sec.Wel_y * FY / 120.0)
    p = 0.5 * (1 + 0.21 * (lam_lt - 0.2) + lam_lt ** 2)                        # curve a (h/b = 2)
    chi_lt = 1 / (p + math.sqrt(p ** 2 - lam_lt ** 2))
    assert det["kzy"] == pytest.approx(kzy, rel=1e-9)
    assert det["eq_6_62"] == pytest.approx(n_z + kzy * 30.0 / (chi_lt * sec.Wel_y * FY), rel=1e-9)
    assert det["ltb"] == pytest.approx(30.0 / (chi_lt * sec.Wel_y * FY), rel=1e-9)


def test_cantilever_i_beam_is_rooted_and_free():
    """A cantilever's segment: held (v = v' = phi = 0) at the root support, free at the tip."""
    sec = {"shape": "i", "height": 0.3, "width": 0.15, "web": 0.0071, "flange": 0.0107}
    m = model([[0, 0, 3], [3, 0, 3]], [[0, 0, 3]], 3.0)
    m["members"][0]["section"] = sec
    row = ns.validate(m, "beam", 10.0, fixed_supports=True, self_weight=False, stability="off", detail=True)["members"][0]
    assert row["ltb_ends"] == ["root", "free"] and math.isfinite(row["m_cr_knm"]) and row["m_cr_knm"] > 0
