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
