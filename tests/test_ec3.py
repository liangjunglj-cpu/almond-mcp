"""EN 1993-1-1 member checks (almond_mcp/ec3.py), each expectation worked from the standard's text."""
import math

import numpy as np
import pytest

from almond_mcp import ec3
from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from tests.test_hand_calculations import model

S235, S355 = fs.Material("S235", 210e6, 80.76e6, 78.5, 235e3, "steel"), fs.Material("S355", 210e6, 80.76e6, 78.5, 355e3, "steel")


# ------------------------------------------------------------------ Table 6.2 curves, 6.3.1.2 chi
@pytest.mark.parametrize("section, fy, fab, curves", [
    (fs.chs(219.1, 8), 235e3, "cold_formed", ("c", "c")),
    (fs.chs(219.1, 8), 355e3, "hot_finished", ("a", "a")),
    (fs.chs(219.1, 8), 460e3, "hot_finished", ("a0", "a0")),
    (fs.rhs(200, 100, 8), 235e3, "cold_formed", ("c", "c")),
    (fs.i_section(300, 150, 7.1, 10.7), 235e3, "cold_formed", ("a", "b")),     # rolled, h/b > 1.2, tf <= 40
    (fs.i_section(200, 200, 9, 15), 235e3, "cold_formed", ("b", "c")),        # h/b <= 1.2
])
def test_buckling_curves(section, fy, fab, curves):
    assert ec3.buckling_curves(section, fy, fab) == curves


def test_chi_values_at_lambda_one():
    """chi at lambda_bar = 1: a0 0.725, a 0.666, b 0.597, c 0.540, d 0.467."""
    for curve, want in (("a0", 0.725), ("a", 0.666), ("b", 0.597), ("c", 0.540), ("d", 0.467)):
        assert ec3.chi(1.0, curve) == pytest.approx(want, abs=1e-3)
    assert ec3.chi(0.2, "c") == 1.0


# ------------------------------------------------------------------ Table 5.2 classes
@pytest.mark.parametrize("d, t, mat, cls", [
    (219.1, 8.0, S235, 1),        # d/t = 27
    (219.1, 3.6, S235, 2),        # d/t = 60.9: 50 < 60.9 <= 70
    (219.1, 2.9, S235, 3),        # d/t = 75.6: <= 90
    (219.1, 2.9, S355, 4),        # 75.6 > 90 x 235/355 = 59.6
    (219.1, 2.3, S235, 4),        # d/t = 95 > 90
])
def test_chs_class_scales_with_fy(d, t, mat, cls):
    z = np.zeros(3)
    assert ec3.classify(fs.chs(d, t), mat.fy, -np.ones(3), z, z) == cls


def test_rhs_class_compression_and_bending():
    shs = fs.rhs(200, 200, 5)                          # c/t = (200 - 3 x 5) / 5 = 37
    z, one = np.zeros(1), np.ones(1)
    compression = -1000.0 * one                       # uniform compression in every wall
    assert ec3.classify(shs, 235e3, compression, z, z) == 2      # 33 < 37 <= 38
    assert ec3.classify(shs, 355e3, compression, z, z) == 4      # 42 x 0.814 = 34.2 < 37
    # pure bending about y: flanges in uniform compression (Class 2 in S235), webs in bending (limit 72)
    assert ec3.classify(shs, 235e3, z, 100.0 * one, z) == 2
    tension = 1000.0 * one
    assert ec3.classify(shs, 355e3, tension, z, z) == 1           # nothing in compression


# ------------------------------------------------------------------ Table B.3 Cm
T21 = np.linspace(0, 1, 21)
T_JOINT = np.concatenate([np.linspace(0, 0.5, 11), np.linspace(0.5, 1, 11)])     # two elements, joint at mid-span


def udl(m0, m1, q):
    """End moments m0, m1 plus a uniform load q (t units: mid-span moment q/8)."""
    return T21, m0 + (m1 - m0) * T21 + q * T21 * (1 - T21) / 2


def point(m0, m1, P):
    """End moments m0, m1 plus a point load P at the mid-span joint (mid-span moment P/4)."""
    return T_JOINT, m0 + (m1 - m0) * T_JOINT + P * np.minimum(T_JOINT, 1 - T_JOINT) / 2


def test_equivalent_moment_factor_row_1_linear():
    t = np.linspace(0, 1, 11)
    assert ec3.equivalent_moment_factor(t, np.full(11, 50.0)) == pytest.approx(1.0)          # uniform, psi = 1
    assert ec3.equivalent_moment_factor(t, 50.0 * (1 - t)) == pytest.approx(0.6)             # psi = 0
    assert ec3.equivalent_moment_factor(t, 50.0 * (1 - 2 * t)) == pytest.approx(0.4)         # psi = -1 -> 0.2, floor 0.4
    assert ec3.equivalent_moment_factor(t, np.zeros(11)) == 1.0


# expected values worked by hand from Table B.3 with Ms = (m0 + m1)/2 + q/8 (uniform) or + P/4 (point)
@pytest.mark.parametrize("diagram, cm", [
    (udl(100, 60, 80), 0.2 + 0.8 * 0.9),                      # row 2, Ms = 90, alpha_s = 0.9
    (udl(-100, -100, 1280), 0.1 - 0.8 * (-0.6)),              # row 2, Ms = 60, alpha_s = -0.6, psi = 1
    (udl(-100, 50, 560), 0.1 * 1.5 - 0.8 * (-0.45)),          # row 2, psi = -0.5, Ms = 45, alpha_s = -0.45
    (udl(-100, 50, 400), 0.4),                                # row 2, psi = -0.5, alpha_s = -0.25 -> 0.35, floor 0.4
    (udl(40, 20, 800), 0.95 + 0.05 * 40 / 130),               # row 3, Ms = 130, alpha_h = 0.308
    (udl(-40, -20, 1280), 0.95 - 0.05 * 40 / 130),            # row 3, alpha_h = -0.308, psi = 0.5
    (udl(-40, 10, 1200), 0.95 + 0.05 * (-40 / 135) * 0.5),    # row 3, alpha_h = -0.296, psi = -0.25
    (udl(0, 0, 80), 0.95),                                    # simply supported UDL, alpha_h = 0
    (point(-100, -100, 720), -0.8 * (-0.8)),                  # row 2, Ms = 80, alpha_s = -0.8, psi = 1
    (point(-100, 50, 400), -0.2 * (-0.5) - 0.8 * (-0.75)),    # row 2, psi = -0.5, Ms = 75, alpha_s = -0.75
    (point(20, 10, 400), 0.90 + 0.10 * 20 / 115),             # row 3, Ms = 115, alpha_h = 0.174
    (point(-20, 5, 480), 0.90 + 0.10 * (-20 / 112.5) * 0.5),  # row 3, alpha_h = -0.178, psi = -0.25
    (point(0, 0, 40), 0.90),                                  # simply supported, point load at mid-span
])
def test_equivalent_moment_factor_rows_2_and_3(diagram, cm):
    t, M = diagram
    assert ec3.equivalent_moment_factor(t, M) == pytest.approx(cm, abs=1e-9)
    assert ec3.equivalent_moment_factor(t, -M) == pytest.approx(cm, abs=1e-9)                  # sign-free


def test_load_type_read_from_the_stations():
    assert ec3.moment_diagram(*udl(10, 5, 0))["load"] == "none"
    assert ec3.moment_diagram(*udl(10, 5, 40))["load"] == "uniform"
    assert ec3.moment_diagram(*point(10, 5, 40))["load"] == "concentrated"
    t, M = point(0, 0, 400)
    assert ec3.moment_diagram(t, M + 8 * t * (1 - t) / 2)["load"] == "concentrated"        # + light self weight
    assert ec3.moment_diagram(t, M + 400 * t * (1 - t) / 2)["load"] == "uniform"           # mixed: the higher column
    thirds = np.concatenate([np.linspace(0, 1 / 3, 6), np.linspace(1 / 3, 2 / 3, 6), np.linspace(2 / 3, 1, 6)])
    assert ec3.moment_diagram(thirds, 30 * np.minimum(np.minimum(thirds, 1 / 3), 1 - thirds))["load"] == "concentrated"
    quarters = np.concatenate([np.linspace(k / 4, (k + 1) / 4, 6) for k in range(4)])     # chords of a curved member
    assert ec3.moment_diagram(quarters, np.interp(quarters, [0, .25, .5, .75, 1], [0, 1.5, 2, 1.5, 0]))["load"] == "uniform"


def test_no_cliff_as_transverse_load_grows():
    """The old rule jumped from 0.6 + 0.4 psi to 1.0 once the diagram was 2 % off linear; Table B.3 rows
    2/3 meet row 1 as the load goes to zero, so Cm now moves smoothly with the load."""
    cms = [ec3.equivalent_moment_factor(*udl(100, 0, q)) for q in np.linspace(0, 80, 41)]
    assert cms[0] == pytest.approx(0.6)
    assert max(abs(b - a) for a, b in zip(cms, cms[1:])) < 0.01
    assert cms[-1] == pytest.approx(0.2 + 0.8 * 0.6)                                       # Ms = 60, alpha_s = 0.6


def test_outside_table_b3_takes_the_upper_bound():
    t = T_JOINT
    step = np.where(np.arange(len(t)) < 11, 50.0 * t, 50.0 * t - 20.0)                       # concentrated moment at the joint
    assert ec3.moment_factor(t, step)[0] == 1.0
    anti = 100 * np.sin(2 * np.pi * T21)                                                     # zero at the ends and mid-span
    assert ec3.moment_factor(T21, anti)[0] == 1.0


def test_sway_mode_and_free_ends():
    t = np.linspace(0, 1, 11)
    assert ec3.equivalent_moment_factor(t, 50.0 * (1 - t), sway=True) == pytest.approx(0.9)
    assert ec3.equivalent_moment_factor(t, np.zeros(11), sway=True) == 1.0                  # no moment: nothing to factor
    f = fs.Frame()
    a, b, c = f.add_node((0, 0, 0)), f.add_node((0, 0, 3)), f.add_node((4, 0, 3))
    col, beam = f.add_element(a, b, fs.chs(219.1, 8), S235), f.add_element(b, c, fs.chs(219.1, 8), S235)
    f.fix(a)
    assert not ec3.free_end(f, [col])                                                        # the beam holds its top
    assert ec3.free_end(f, [beam])                                                           # cantilever tip
    f.spring(c, kz=1e3)
    assert not ec3.free_end(f, [beam])                                                       # sprung tip: held


# ------------------------------------------------------------------ 6.3.3 with Annex B
def test_annex_b_interaction_exceeds_k_equal_one():
    """CHS, uniform moment (Cm = 1), elastic design (Class 3 factors): kyy = 1 + 0.6 lambda nY,
    capped at 1 + 0.6 nY. With nY near 0.5 the check exceeds the old k = 1 sum by about 15 %."""
    s, m = fs.chs(219.1, 8.0), S235
    lam_target = 1.0
    L = math.pi * math.sqrt(m.E * s.Iy / (s.A * m.fy)) * lam_target       # lambda_bar = 1 exactly
    chi_c = ec3.chi(lam_target, "c")
    ned = 0.5 * chi_c * s.A * m.fy                                        # nY = 0.5
    my = 0.5 * s.Wel_y * m.fy                                             # half the elastic moment
    t = np.linspace(0, 1, 13)
    res = ec3.member_check(s, m, L, t, np.full(13, -ned), np.full(13, my), np.zeros(13))
    kyy = min(1 + 0.6 * 1.0 * 0.5, 1 + 0.6 * 0.5)                         # 1.30
    d = res["detail"]
    assert d["lambda_y"] == pytest.approx(1.0, rel=1e-9) and d["kyy"] == pytest.approx(kyy)
    assert d["eq_6_61"] == pytest.approx(0.5 + kyy * 0.5)                 # 1.15
    assert res["utilization"] == pytest.approx(1.15)
    assert d["kzy"] == pytest.approx(0.8 * kyy) and d["kyz"] == pytest.approx(d["kzz"])


def test_plastic_design_uses_class_1_2_factors():
    s, m = fs.chs(219.1, 8.0), S235
    L = 4.0
    t = np.linspace(0, 1, 13)
    res = ec3.member_check(s, m, L, t, np.full(13, -400.0), np.full(13, 30.0), np.zeros(13), plastic=True)
    d = res["detail"]
    lam = d["lambda_y"]
    n = 400.0 / (d["chi_y"] * s.A * m.fy)
    assert d["moduli"] == "plastic"
    assert d["kyy"] == pytest.approx(min(1 + (lam - 0.2) * n, 1 + 0.8 * n))
    assert d["eq_6_61"] == pytest.approx(n + d["kyy"] * 30.0 / (s.Wpl_y * m.fy))


def test_slender_section_never_uses_plastic_moduli():
    s, m = fs.chs(219.1, 2.9), S355                                       # Class 4 in S355
    t = np.linspace(0, 1, 5)
    res = ec3.member_check(s, m, 3.0, t, np.full(5, -10.0), np.full(5, 1.0), np.zeros(5), plastic=True)
    assert res["detail"]["class"] == 4 and res["detail"]["moduli"] == "elastic"
    assert res["detail"]["governing_check"].startswith("class 4")


# ------------------------------------------------------------------ through the solver
def test_member_check_uses_the_whole_member_after_subdivision():
    """Regression: the stability check splits compression members into 4 elements; buckling must
    still use the 4 m member, not a 1 m piece."""
    L = 4.0
    m = model([[0, 0, 0], [0, 0, L]], [[0, 0, 0]], L)
    off = ns.validate(m, "frame", 300, fixed_supports=True, self_weight=False, stability="off", detail=True)
    auto = ns.validate(m, "frame", 300, fixed_supports=True, self_weight=False, stability="auto", detail=True)
    a, o = auto["members"][0], off["members"][0]
    assert a["elements"] == 4 and a["buckling_length_m"] == pytest.approx(L)
    assert a["chi"] == pytest.approx(o["chi"]) and a["slenderness"] == pytest.approx(o["slenderness"])


def test_class_4_member_fails_validation():
    sec = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.0029}
    m = model([[0, 0, 3], [6, 0, 3]], [[0, 0, 3], [6, 0, 3]], 6.0)
    m["members"][0]["section"] = sec
    ok = ns.validate(m, "beam", 0.0, material="S235", fixed_supports=False, self_weight=True, detail=True)
    bad = ns.validate(m, "beam", 0.0, material="S355", fixed_supports=False, self_weight=True, detail=True)
    assert ok["members"][0]["section_class"] == 3
    assert bad["members"][0]["section_class"] == 4 and bad["members"][0]["status"] == "fail"
    assert bad["status"] == "fail" and "Class 4" in bad["verdict"]


def test_fabrication_choice_is_validated_and_reported():
    m = model([[0, 0, 0], [0, 0, 4]], [[0, 0, 0]], 4.0)
    r = ns.validate(m, "frame", 300, fixed_supports=True, self_weight=False, fabrication="hot_finished")
    assert r["results"]["fabrication"] == "hot_finished"
    assert any("hot-finished" in a for a in r["assumptions"])
    bad = ns.validate(m, "frame", 300, fabrication="welded")
    assert bad["status"] == "error" and "fabrication" in bad["verdict"]


def test_solid_rectangular_sections_from_the_model():
    """Concrete and timber members arrive as solid rectangles (width x depth in metres), not hollow boxes."""
    sec, notes = ns.section_from_spec({"shape": "rect", "width": 0.30, "height": 0.64})
    assert sec.shape == "rect" and sec.A == pytest.approx(0.30 * 0.64) and not notes
    assert sec.Iy == pytest.approx(0.30 * 0.64 ** 3 / 12)                 # depth along local z
    box, _ = ns.section_from_spec({"shape": "box", "width": 0.30, "height": 0.64})
    assert box.shape == "rhs" and box.A < sec.A                            # a box stays hollow


def beam_with_midspan(span=6.0, sec=None):
    m = model([[0, 0, 3], [span / 2, 0, 3], [span, 0, 3]], [[0, 0, 3], [span, 0, 3]], span)
    if sec:
        m["members"][0]["section"] = sec
    return m


RECT = {"shape": "rect", "width": 0.30, "height": 0.60}


def test_concrete_and_timber_get_no_capacity_verdict():
    """Without EN 1992/EN 1995 there is no pass/fail on capacity: forces and deflection only."""
    for material in ("Concrete", "Wood"):
        r = ns.validate(beam_with_midspan(6.0, RECT), "beam", 50.0, material=material, fixed_supports=False)
        assert r["status"] == "indicative" and r["passed"] is None
        assert "INDICATIVE ONLY" in r["verdict"] and "no pass/fail" in r["verdict"]
        assert r["results"]["utilization_ratio"] > 0                       # still reported, for comparison
    # far beyond the characteristic strength but within the deflection limit: still no capacity FAIL
    heavy = ns.validate(beam_with_midspan(6.0, RECT), "beam", 400.0, material="Concrete", fixed_supports=False,
                        stability="off")
    assert heavy["results"]["utilization_ratio"] > 1
    assert heavy["results"]["max_deflection_mm"] < heavy["results"]["deflection_limit_mm"]
    assert heavy["status"] == "indicative"
    # excessive deflection is a real failure whatever the material
    soft = ns.validate(beam_with_midspan(12.0, {"shape": "rect", "width": 0.20, "height": 0.25}), "beam", 400.0,
                       material="Concrete", fixed_supports=False, stability="off")
    assert soft["results"]["max_deflection_mm"] > soft["results"]["deflection_limit_mm"]
    assert soft["status"] == "fail" and "Deflection" in soft["verdict"]


def test_steel_verdicts_are_unchanged():
    assert ns.validate(beam_with_midspan(), "beam", 10.0, material="Steel", fixed_supports=False)["status"] == "pass"
    assert ns.validate(beam_with_midspan(), "beam", 2000.0, material="Steel", fixed_supports=False)["status"] == "fail"


def test_overlay_is_labelled_indicative_for_concrete():
    from almond_mcp import structure_study as st
    sec = {"shape": "rect", "width": 0.30, "height": 0.60}
    m = model([[0, 0, 3], [6, 0, 3]], [[0, 0, 3], [6, 0, 3]], 6.0)
    m["members"][0]["section"] = sec
    concrete = st.run({"model": m, "settings": {"structure": "beam", "material": "Concrete", "load_kn": 50}})
    steel = st.run({"model": model([[0, 0, 3], [6, 0, 3]], [[0, 0, 3], [6, 0, 3]], 6.0),
                    "settings": {"structure": "beam", "load_kn": 10}})
    assert concrete["status"] == "indicative" and concrete["draw"]["verdict_label"] == "INDICATIVE"
    assert "verdict_label" not in steel["draw"] and "indicative" not in steel["draw"]["result"]
