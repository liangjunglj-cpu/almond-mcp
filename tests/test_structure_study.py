"""almond-mcp solve: the Rhino panel's native structural study (JSON in, JSON out)."""
import io
import json
import os
import subprocess
import sys

import pytest

from almond_mcp import native_structure as ns
from almond_mcp import structure_study as st
from tests.test_asset_load_tools import BEAM, TUB
from tests.test_stability import portal_model


def model(d=114.3, t=4.0):
    return dict(portal_model(d, t), status="ok", shells=0)


def solve(request):
    out = io.StringIO()
    code = st.main(io.StringIO(json.dumps(request)), out)
    return code, json.loads(out.getvalue())


def test_study_matches_validate_and_draws_the_overlay():
    s = {"load_kn": 40, "fixed_rotations": False, "self_weight": False}
    code, out = solve({"protocol": 1, "model": model(323.9, 10), "settings": s})
    ref = ns.validate(model(323.9, 10), "frame", 40, fixed_supports=False, self_weight=False)
    assert code == 0 and out["status"] == ref["status"]
    assert out["validation"]["results"]["utilization_ratio"] == ref["results"]["utilization_ratio"]
    draw = out["draw"]
    assert draw["type"] == "structure_draw" and draw["engine"] == "native" and draw["color_by"] == "utilization"
    assert draw["span_m"] == out["validation"]["results"]["span_m"]
    assert draw["result"]["elements"] and "u: ULS" in draw["title"]
    assert "combinations" not in draw["result"] and "stability" not in draw["result"]


def test_study_takes_every_native_option():
    s = {"load_kn": 0, "floor_imposed_kn_m2": 2.0, "floor_dead_kn_m2": 1.0, "connections": "simple",
         "design_basis": "en1990", "uls_combination": "6.10ab", "stability": "auto", "fixed_rotations": True,
         "diameter_mm": 219.1, "wall_mm": 8.0, "span_m": 6.0}
    _, out = solve({"model": model(), "settings": s})
    v = out["validation"]
    assert v["floor_loads"]["area_m2"] == pytest.approx(18.0)
    assert v["results"]["connections"]["mode"] == "simple" and v["results"]["span_m"] == 6.0
    assert v["results"]["design_basis"] == "en1990" and "ULS 6.10b" in [c["name"] for c in v["results"]["combinations"]]
    assert "floor 3 kN/m2" in out["draw"]["load_label"]


def test_buckling_view_status_follows_validation_and_reports_alpha():
    _, out = solve({"model": model(), "settings": {"load_kn": 40, "fixed_rotations": False, "self_weight": False,
                                                  "view": "buckling"}})
    assert out["buckling"]["alpha_cr"] > 1 and out["draw"]["buckling_alpha"] == out["buckling"]["alpha_cr"]
    assert out["draw"]["color_by"] == "displacement" and "BUCKLING" in out["draw"]["title"]
    assert out["status"] == out["validation"]["status"]


def test_unstable_frame_reports_without_a_drawing():
    _, out = solve({"model": model(60.3, 3), "settings": {"load_kn": 400, "fixed_rotations": False}})
    assert out["status"] == "fail" and "draw" not in out and "Buckling mode" in out["message"]
    assert out["validation"]["results"]["stability"]["method"] == "unstable"


def test_asset_loads_from_rhino_placements():
    beam = dict(BEAM)
    _, plain = solve({"model": beam, "settings": {"structure": "beam", "load_kn": 0.001}})
    _, out = solve({"model": beam, "placements": [TUB], "settings": {"structure": "beam", "load_kn": 0.001,
                                                                     "asset_loads": True}})
    rep = out["validation"]["asset_loads"]
    assert rep["applied"] == 1 and rep["placements"][0]["asset_id"] == "gen-bathtub-1"
    assert out["validation"]["results"]["max_deflection_mm"] > plain["validation"]["results"]["max_deflection_mm"]
    assert "1 assets" in out["draw"]["load_label"]


@pytest.mark.parametrize("request_, needle", [
    ({"protocol": 2, "model": BEAM}, "protocol"),
    ({"settings": {}}, "No exported structural model"),
    ({"model": dict(BEAM, shells=2)}, "Karamba engine for shells"),
    ({"model": dict(BEAM, members=[])}, "No line members"),
    ({"model": BEAM, "settings": {"connections": "welded"}}, "connections"),
    ({"model": BEAM, "settings": {"diameter_mm": 100}}, "diameter"),
    ({"model": BEAM, "settings": {"floor_dead_kn_m2": -1}}, "non-negative"),
])
def test_bad_requests_are_errors_not_crashes(request_, needle):
    code, out = solve(request_)
    assert code == 1 and out["status"] == "error" and needle in out["message"]


def test_ping_and_garbage():
    assert solve({"ping": True})[1]["status"] == "ok"
    out = io.StringIO()
    assert st.main(io.StringIO("not json"), out) == 1 and "Bad request" in json.loads(out.getvalue())["message"]


def test_cli_subprocess_round_trip_utf8():
    req = {"model": dict(BEAM, warnings=["Träger · 梁"]), "settings": {"structure": "beam"}}
    env = dict(os.environ, PYTHONIOENCODING="cp1252")              # a hostile console encoding
    proc = subprocess.run([sys.executable, "-m", "almond_mcp", "solve"], input=json.dumps(req).encode("utf-8"),
                          capture_output=True, env=env, timeout=120)
    out = json.loads(proc.stdout.decode("utf-8"))
    assert proc.returncode == 0 and out["status"] in ("pass", "fail")
    assert "Träger · 梁" in out["validation"]["warnings"]


def test_cli_accepts_a_byte_order_mark():
    """.NET prefixes a child's stdin with a UTF-8 BOM when the console encoding is UTF-8 (CI's pwsh)."""
    payload = b"\xef\xbb\xbf" + json.dumps({"ping": True}).encode("utf-8")
    proc = subprocess.run([sys.executable, "-m", "almond_mcp", "solve"], input=payload, capture_output=True, timeout=120)
    assert proc.returncode == 0 and json.loads(proc.stdout.decode("utf-8"))["status"] == "ok"
    out = io.StringIO()
    assert st.main(io.StringIO("\ufeff" + json.dumps({"ping": True})), out) == 0


def test_study_reports_every_member_and_support():
    _, out = solve({"model": model(219.1, 8), "settings": {"load_kn": 40, "fixed_rotations": False}})
    v = out["validation"]
    members, supports = v["members"], v["supports"]
    assert len(members) == 8 and {m["role"] for m in members} == {"column", "beam"}
    worst = max(members, key=lambda m: m["utilization"])
    assert worst["utilization"] == pytest.approx(v["results"]["utilization_ratio"], abs=1e-4)
    col = next(m for m in members if m["role"] == "column")
    assert col["n_compression_kn"] > 0 and col["length_m"] == pytest.approx(4.0) and col["elements"] >= 1
    assert col["governing_check"] in ("cross-section", "flexural buckling") and col["chi"] is not None
    beam = next(m for m in members if m["role"] == "beam")
    assert beam["m_max_knm"] > 0 and beam["deflection_mm"] > 0 and beam["deflection_ratio"] > 0
    assert len(supports) == 4 and all(s["restraint"] == "pinned" for s in supports)
    # the vertical reactions balance the load at SLS
    assert sum(s["sls"]["Fz"] for s in supports) == pytest.approx(v["results"]["reactions_kn"], rel=1e-6)
    assert set(supports[0]["uls"]) == {c["name"] for c in v["results"]["combinations"][1:]}
    json.dumps(out, allow_nan=False)                                    # plain JSON, nothing non-finite


def test_member_names_and_layers_come_from_the_model():
    m = model(219.1, 8)
    m["members"][0].update(name="C-01", layer="Structure::Columns")
    _, out = solve({"model": m, "settings": {"load_kn": 10}})
    row = next(r for r in out["validation"]["members"] if r["source_guids"] == ["c1"])
    assert row["id"] == "C-01" and row["layer"] == "Structure::Columns"


def test_study_passes_the_tube_fabrication():
    hot = solve({"model": model(219.1, 8), "settings": {"load_kn": 40, "fabrication": "hot_finished"}})[1]
    cold = solve({"model": model(219.1, 8), "settings": {"load_kn": 40}})[1]
    assert hot["validation"]["results"]["fabrication"] == "hot_finished"
    assert cold["validation"]["results"]["fabrication"] == "cold_formed"
    col = lambda o: max((m for m in o["validation"]["members"] if m["role"] == "column"), key=lambda m: m["utilization"])
    assert col(cold)["buckling_curves"] == ["c", "c"] and col(hot)["buckling_curves"] == ["a", "a"]
    assert col(cold)["chi"] <= col(hot)["chi"]
    assert solve({"model": model(219.1, 8), "settings": {"fabrication": "welded"}})[1]["status"] == "error"
