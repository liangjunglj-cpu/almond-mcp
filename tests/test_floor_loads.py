"""Floor area loads: bay finding, tributary distribution, closed-form checks, tools."""
import json
import math

import numpy as np
import pytest

from almond_mcp import floor_loads as fl
from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns
from tests.test_capsules import _load_server
from tests.test_native_structure import CASES, model as ref_model

STEEL, SEC = fs.material("Steel"), fs.chs(193.7, 8.0)
EI = STEEL.E * SEC.Iy


def grid(xs, ys, z=3.0):
    """Beams along every grid line at height z; returns frame and node lookup."""
    f = fs.Frame()
    ids = {(x, y): f.add_node((x, y, z)) for x in xs for y in ys}
    for y in ys:
        for a, b in zip(xs, xs[1:]):
            f.add_element(ids[a, y], ids[b, y], SEC, STEEL, tag=[f"x{a}-{b}@y{y}"])
    for x in xs:
        for a, b in zip(ys, ys[1:]):
            f.add_element(ids[x, a], ids[x, b], SEC, STEEL, tag=[f"y{a}-{b}@x{x}"])
    return f, ids


def element_loads(f):
    """Total downward member load per original tag (kN)."""
    out = {}
    for ei, wa, wb in f.member_loads:
        e = f.elements[ei]
        out.setdefault(e.tag[0], 0.0)
        out[e.tag[0]] += -(wa[2] + wb[2]) / 2 * math.dist(f.nodes[e.n1], f.nodes[e.n2])
    return out


def test_bays_of_a_grid_and_dangling_members():
    f, ids = grid([0, 3, 6], [0, 2, 4])
    extra = f.add_node((8, 0, 3))
    f.add_element(ids[6, 0], extra, SEC, STEEL, tag=["stub"])          # dangling: no bay
    bays = fl.find_bays(f, list(range(len(f.elements))))
    assert len(bays) == 4 and all(b["area"] == pytest.approx(6.0) for b in bays)


def test_two_way_square_bay_shares_equally():
    f, ids = grid([0, 4], [0, 4])
    rep = fl.apply(f, imposed_kn_m2=2.0, dead_kn_m2=1.0)
    assert rep["area_m2"] == pytest.approx(16.0) and rep["total_kn"] == pytest.approx(48.0)
    loads = element_loads(f)
    assert all(v == pytest.approx(12.0, rel=1e-9) for v in loads.values())   # four triangles of q*s^2/4


def test_rectangular_two_way_trapezoids():
    f, _ = grid([0, 6], [0, 4])                     # 6 x 4, ratio 1.5
    fl.apply(f, imposed_kn_m2=1.0)
    loads = element_loads(f)
    short, long = 4 ** 2 / 4, 4 * 6 / 2 - 4 ** 2 / 4
    assert loads["y0-4@x0"] == pytest.approx(short) and loads["x0-6@y0"] == pytest.approx(long)


def test_one_way_bay_loads_only_the_long_beams():
    f, _ = grid([0, 6], [0, 2])                     # ratio 3: one-way
    fl.apply(f, imposed_kn_m2=1.0)
    loads = element_loads(f)
    assert loads.get("y0-2@x0", 0.0) == pytest.approx(0.0) and loads["x0-6@y0"] == pytest.approx(6.0)


def test_triangular_shape_matches_closed_form_on_a_simple_beam():
    """Symmetric triangle, total W on a simply supported span: d = W L^3 / 60EI, M = W L / 6."""
    f = fs.Frame()
    L, peak = 4.0, 3.0
    a, b = f.add_node((0, 0, 0)), f.add_node((L, 0, 0))
    f.add_element(a, b, SEC, STEEL)
    f.fix(a, (True, True, True, True, False, False)); f.fix(b, (False, True, True, False, False, False))
    fl.load_member(f, 0, [[(0.0, 0.0), (0.5, peak), (1.0, 0.0)]])
    r = fs.solve(f)
    W = peak * L / 2
    mid = min(range(len(f.nodes)), key=lambda i: abs(f.nodes[i][0] - L / 2))
    assert -r.displacements[mid, 2] == pytest.approx(W * L ** 3 / (60 * EI), rel=1e-9)     # exact
    assert max(np.max(np.abs(er.My)) for er in r.elements) == pytest.approx(W * L / 6, rel=1e-9)
    assert r.reactions[:, 2].sum() == pytest.approx(W, rel=1e-12)


def test_non_rectangular_bay_uses_centroid_fan_and_conserves_load():
    f = fs.Frame()
    pts = [(0, 0), (5, 0), (6, 3), (1, 4)]
    n = [f.add_node((x, y, 3)) for x, y in pts]
    for i in range(4):
        f.add_element(n[i], n[(i + 1) % 4], SEC, STEEL, tag=[f"e{i}"])
    rep = fl.apply(f, imposed_kn_m2=2.0)
    area = 0.5 * abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])))
    assert rep["area_m2"] == pytest.approx(area) and sum(element_loads(f).values()) == pytest.approx(2.0 * area)


def test_bearing_wall_closes_a_bay_and_takes_its_share():
    """Beams on three sides, two wall supports on the fourth: the bay is loaded, the wall edge's
    triangle goes straight into those supports, and equilibrium holds."""
    f = fs.Frame()
    c = {k: f.add_node(p) for k, p in {"a": (0, 0, 3), "b": (4, 0, 3), "w1": (4, 4, 3), "w0": (0, 4, 3)}.items()}
    for u, v in (("a", "b"), ("b", "w1"), ("w0", "a")):
        f.add_element(c[u], c[v], SEC, STEEL, tag=[u + v])
    f.fix(c["w0"]); f.fix(c["w1"])
    col = f.add_node((0, 0, 0)); f.add_element(col, c["a"], SEC, STEEL, tag=["col"]); f.fix(col)
    rep = fl.apply(f, imposed_kn_m2=2.0)
    assert rep["area_m2"] == pytest.approx(16.0) and rep["levels"][0]["bearing_walls"] == 1
    assert rep["wall_kn"] == pytest.approx(2.0 * 4.0, rel=1e-4)           # one of four 45-degree triangles
    r = fs.solve(f)
    assert r.reactions[:, 2].sum() == pytest.approx(32.0, rel=1e-9) and r.equilibrium_error() < 1e-6


def test_frame_without_bays_warns():
    f = fs.Frame()
    a, b = f.add_node((0, 0, 3)), f.add_node((5, 0, 3))
    f.add_element(a, b, SEC, STEEL)
    rep = fl.apply(f, imposed_kn_m2=2.0)
    assert rep["total_kn"] == 0 and "No enclosed floor bays" in rep["warnings"][0]


def test_mezzanine_floor_load_area_and_equilibrium():
    case = CASES["mezzanine"]
    out = ns.validate(ref_model(case), "frame", 0, "Steel", fixed_supports=False, diameter_mm=193.7, wall_mm=8.0,
                      span_m=6.2, floor_loads={"imposed": 2.0, "dead": 1.0})
    fr = out["floor_loads"]
    assert fr["area_m2"] == pytest.approx(62.0) and fr["levels"][0]["bays"] == 8
    assert fr["imposed_kn"] == pytest.approx(124.0) and fr["total_kn"] == pytest.approx(186.0)
    assert out["results"]["equilibrium_error_kn"] < 1e-6
    assert any("Floor loads" in a for a in out["assumptions"])


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    srv = _load_server(monkeypatch, tmp_path, cap)
    case = CASES["mezzanine"]
    m = dict(ref_model(case), status="ok", shells=0)
    sent = []

    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        sent.append(msg)
        if msg["type"] == "structure_model":
            return json.dumps(m)
        if msg["type"] == "structure_draw":
            return json.dumps({"status": "pass", "analysis_method": "native"})
        return json.dumps({"status": "pass", "results": {"analysis_method": "api"}, "warnings": []})
    monkeypatch.setattr(srv, "_send_and_receive", fake)
    srv._sent = sent
    return srv


def test_tools_take_floor_loads(server):
    out = json.loads(server.validate_structure(guids=["x"], structure_type="frame", load_kn=0, fixed_supports=False,
                                               floor_load_kn_m2=2.0, span_m=6.2))
    assert out["floor_loads"]["imposed_kn"] == pytest.approx(124.0)
    v = json.loads(server.visualize_structure(guids=["x"], load_kn=0, fixed_supports=False, floor_load_kn_m2=2.0,
                                              floor_dead_kn_m2=1.0))
    draw = server._sent[-1]
    assert draw["load_label"].startswith("floor 3 kN/m2 x 62 m2") and v["floor_loads"]["total_kn"] == pytest.approx(186.0)


def test_tools_reject_bad_floor_loads(server):
    assert "native" in json.loads(server.validate_structure(guids=["x"], floor_load_kn_m2=2, engine="karamba"))["message"]
    assert "non-negative" in json.loads(server.validate_structure(guids=["x"], floor_load_kn_m2=-1))["message"]
