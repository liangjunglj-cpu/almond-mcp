"""Stability: geometric stiffness, alpha_cr, second-order P-Delta, sway imperfections, tools."""
import json
import math

import numpy as np
import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from tests.test_capsules import _load_server

STEEL, SEC = fs.material("Steel"), fs.chs(114.3, 4.0)
EI = STEEL.E * SEC.Iy


def column(n=8, L=4.0, top="pin", P=100.0, H=0.0, releases=False):
    f = fs.Frame()
    ids = [f.add_node((0, 0, L * i / n)) for i in range(n + 1)]
    for i in range(n):
        rel = fs.release_mask(i == 0, i == n - 1) if releases else None
        f.add_element(ids[i], ids[i + 1], SEC, STEEL, releases=rel)
    if releases:
        f.fix(ids[0]); f.fix(ids[-1], (True, True, False, True, True, True))
    else:
        f.fix(ids[0]) if top == "free" else f.fix(ids[0], (True, True, True, True, False, False))
        if top == "pin":
            f.fix(ids[-1], (True, True, False, False, False, False))
    f.load(ids[-1], fz=-P)
    if H:
        f.load(ids[-1], fx=H)
    return f, ids


def test_euler_pinned_column_converges():
    L, P = 4.0, 100.0
    exact = math.pi ** 2 * EI / L ** 2 / P
    assert fs.critical_load_factor(column(1)[0], {"Q": 1})[0] == pytest.approx(12 / math.pi ** 2 * exact, rel=1e-9)
    assert fs.critical_load_factor(column(8)[0], {"Q": 1})[0] == pytest.approx(exact, rel=1e-4)


def test_cantilever_column_effective_length_2L():
    alpha, mode = fs.critical_load_factor(column(8, top="free")[0], {"Q": 1})
    assert alpha == pytest.approx(math.pi ** 2 * EI / (4 * 16) / 100, rel=1e-4)
    assert np.abs(mode.reshape(-1, 6)[:, :3]).max() == pytest.approx(1.0)


def test_column_pinned_through_end_releases_is_euler():
    alpha, _ = fs.critical_load_factor(column(8, releases=True)[0], {"Q": 1})
    assert alpha == pytest.approx(math.pi ** 2 * EI / 16 / 100, rel=1e-3)


def planar_portal(col_sec=SEC, P=50.0, beam_sec=None):
    f = fs.Frame()
    a, b = f.add_node((0, 0, 0)), f.add_node((6, 0, 0))
    tops = []
    for x0, base in ((0, a), (6, b)):
        nodes = [base] + [f.add_node((x0, 0, 3 * i / 8)) for i in range(1, 9)]
        for i in range(8):
            f.add_element(nodes[i], nodes[i + 1], col_sec, STEEL)
        tops.append(nodes[-1])
    f.add_element(tops[0], tops[1], beam_sec or fs.chs(1000, 50), STEEL)
    f.fix(a); f.fix(b)
    for t in tops:
        f.load(t, fz=-P)
    for n in range(len(f.nodes)):
        if n not in (a, b):
            f.fix(n, (False, True, False, True, False, True))       # planar
    return f, tops


def test_portal_sway_buckling():
    alpha, _ = fs.critical_load_factor(planar_portal()[0], {"Q": 1})
    assert alpha == pytest.approx(math.pi ** 2 * EI / 9 / 50, rel=2e-3)


def test_second_order_cantilever_matches_exact_amplification():
    L, P, H = 4.0, 30.0, 2.0
    f, ids = column(8, L, top="free", P=P, H=H)
    r = fs.solve_second_order(f, {"Q": 1})
    k = math.sqrt(P / EI)
    exact = H / (P * k) * (math.tan(k * L) - k * L)
    assert r.displacements[ids[-1], 0] == pytest.approx(exact, rel=1e-5) and r.converged
    assert abs(r.reactions[ids[0], 4]) == pytest.approx(H * L + P * exact, rel=1e-5)


def test_second_order_beyond_buckling_raises():
    with pytest.raises(fs.MechanismError, match="Instability"):
        fs.solve_second_order(column(8, top="free", P=100.0, H=1.0)[0], {"Q": 1})


def test_no_compression_means_no_buckling():
    f = fs.Frame()
    a, b = f.add_node((0, 0, 0)), f.add_node((0, 0, -3))
    f.add_element(a, b, SEC, STEEL)
    f.fix(a); f.load(b, fz=-10.0)                                   # hanging rod: tension
    assert math.isinf(fs.critical_load_factor(f, {"Q": 1})[0])


def test_geometric_stiffness_is_symmetric_and_scales_with_N():
    e = fs.Element(0, 1, SEC, STEEL)
    kg = fs.geometric_stiffness(e, 2.0, -50.0)
    assert np.allclose(kg, kg.T) and np.allclose(fs.geometric_stiffness(e, 2.0, -100.0), 2 * kg)


@pytest.mark.parametrize("h,m,phi", [(4.0, 2, 1 / 200 * 1.0 * math.sqrt(0.75)),
                                     (16.0, 1, 1 / 200 * (2 / 3) * 1.0)])
def test_sway_imperfection_formula(h, m, phi):
    f = fs.Frame()
    for i in range(m):
        a, b = f.add_node((5.0 * i, 0, 0)), f.add_node((5.0 * i, 0, h))
        f.add_element(a, b, SEC, STEEL)
    assert ns.sway_imperfection(f)["phi"] == pytest.approx(phi, rel=1e-9)


def test_imperfection_forces_total_phi_times_vertical_load():
    f, tops = planar_portal(P=40.0)
    asm = fs.prepare(f)
    loads = ns._imperfection_loads(asm, f, {"Q": 1.0}, 0.004)
    assert set(loads) == {"+x", "-x", "+y", "-y"}
    assert loads["+x"].reshape(-1, 6)[:, 0].sum() == pytest.approx(0.004 * 80.0)


def portal_model(d_mm, t_mm=None):
    """Free-standing portal with pinned bases and a rigid beam: sways."""
    sec = {"shape": "circular_hollow", "diameter": d_mm / 1000, "wall": (t_mm or d_mm / 20) / 1000}
    m = [{"source_guids": ["c1"], "points": [[0, 0, 0], [0, 0, 4]], "section": sec},
         {"source_guids": ["c2"], "points": [[6, 0, 0], [6, 0, 4]], "section": sec},
         {"source_guids": ["c3"], "points": [[0, 3, 0], [0, 3, 4]], "section": sec},
         {"source_guids": ["c4"], "points": [[6, 3, 0], [6, 3, 4]], "section": sec},
         {"source_guids": ["b1"], "points": [[0, 0, 4], [6, 0, 4]], "section": sec},
         {"source_guids": ["b2"], "points": [[0, 3, 4], [6, 3, 4]], "section": sec},
         {"source_guids": ["b3"], "points": [[0, 0, 4], [0, 3, 4]], "section": sec},
         {"source_guids": ["b4"], "points": [[6, 0, 4], [6, 3, 4]], "section": sec}]
    return {"members": m, "anchor_points": [[0, 0, 0], [6, 0, 0], [0, 3, 0], [6, 3, 0]], "tolerance_m": 0.001,
            "max_member_span_m": 6, "max_span_m": 6}


def test_three_regimes_first_order_second_order_unstable():
    kw = dict(structure_type="frame", fixed_supports=False, self_weight=False)
    stiff = ns.validate(portal_model(323.9, 10), load_kn=40, **kw)
    assert stiff["results"]["stability"]["min_alpha_cr"] >= 10 and stiff["results"]["stability"]["method"] == "first-order"
    sway = ns.validate(portal_model(114.3, 4), load_kn=40, **kw)
    st = sway["results"]["stability"]
    assert 1 < st["min_alpha_cr"] < 10 and st["method"] == "second-order (P-Delta)" and st["iterations"] >= 1
    off = ns.validate(portal_model(114.3, 4), load_kn=40, stability="off", **kw)
    assert sway["results"]["utilization_ratio"] > off["results"]["utilization_ratio"]       # P-Delta + imperfection
    assert "sway" in sway["results"]["utilization_combination"]
    unstable = ns.validate(portal_model(60.3, 3), load_kn=400, **kw)
    assert unstable["status"] == "fail" and "alpha_cr" in unstable["verdict"]
    assert unstable["results"]["stability"]["method"] == "unstable"


def test_view_result_buckling_mode():
    res, _ = ns.view_result(portal_model(114.3, 4), load_kn=40, fixed_supports=False, self_weight=False, view="buckling")
    assert res["buckling"]["alpha_cr"] > 1 and all(e["utilization"] is None for e in res["elements"])
    # every piece of every member is drawn (the refined columns included)
    tops = [e["end_m"] for e in res["elements"] if e["source_guids"][0].startswith("c")]
    assert sum(1 for p in tops if abs(p[2] - 4.0) < 1e-9) == 4
    assert res["max_displacement_mm"] == pytest.approx(1000.0, rel=0.01)      # normalised at nodes; stations interpolate


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    srv = _load_server(monkeypatch, tmp_path, cap)
    sent = []

    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        sent.append(msg)
        if msg["type"] == "structure_model":
            return json.dumps(dict(portal_model(114.3, 4), status="ok", shells=0))
        return json.dumps({"status": "pass", "analysis_method": "native"})
    monkeypatch.setattr(srv, "_send_and_receive", fake)
    srv._sent = sent
    return srv


def test_tools_take_stability_and_buckling_view(server):
    out = json.loads(server.validate_structure(guids=["x"], structure_type="frame", load_kn=40, fixed_supports=False))
    assert out["results"]["stability"]["method"] == "second-order (P-Delta)"
    v = json.loads(server.visualize_structure(guids=["x"], load_kn=40, fixed_supports=False, view="buckling"))
    draw = server._sent[-1]
    assert draw["buckling_alpha"] == v["buckling"]["alpha_cr"] and draw["color_by"] == "displacement"
    assert "BUCKLING" in draw["title"]
    assert "stability" in json.loads(server.validate_structure(guids=["x"], stability="maybe"))["message"]
    assert "native" in json.loads(server.visualize_structure(guids=["x"], view="buckling", engine="karamba"))["message"]
