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
def test_equivalent_moment_factor():
    t = np.linspace(0, 1, 11)
    assert ec3.equivalent_moment_factor(t, np.full(11, 50.0)) == pytest.approx(1.0)          # uniform, psi = 1
    assert ec3.equivalent_moment_factor(t, 50.0 * (1 - t)) == pytest.approx(0.6)             # psi = 0
    assert ec3.equivalent_moment_factor(t, 50.0 * (1 - 2 * t)) == pytest.approx(0.4)         # psi = -1 -> 0.2, floor 0.4
    assert ec3.equivalent_moment_factor(t, 50.0 * t * (1 - t)) == pytest.approx(1.0)         # transverse load
    assert ec3.equivalent_moment_factor(t, np.zeros(11)) == 1.0


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
