"""asset_loads on validate_structure / visualize_structure, and loads in asset passports."""
import json

import pytest

from tests.test_capsules import _load_server

BEAM = {"status": "ok", "shells": 0, "tolerance_m": 0.001, "max_span_m": 6.0, "max_member_span_m": 6.0, "warnings": [],
        "anchor_points": [[0, 0, 3], [6, 0, 3]],
        "members": [{"source_guids": ["beam"], "points": [[0, 0, 3], [6, 0, 3]],
                     "section": {"shape": "circular_hollow", "diameter": 0.1143, "wall": 0.004}}]}
TUB = {"id": "tub-guid", "asset_id": "gen-bathtub-1", "min": [2.15, -0.375, 3.1], "max": [3.85, 0.375, 3.68],
       "scale": 1.0, "source": "rhino"}


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    return _load_server(monkeypatch, tmp_path, cap)


def bridge(server, monkeypatch, placements=None, placements_supported=True):
    sent = []

    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        sent.append(msg)
        if msg["type"] == "structure_model":
            return json.dumps(BEAM)
        if msg["type"] == "asset_placements":
            if not placements_supported:
                return json.dumps({"status": "compile_error", "message": "unknown"})
            return json.dumps({"status": "ok", "placements": placements or []})
        if msg["type"] == "structure_draw":
            return json.dumps({"status": "fail", "analysis_method": "native"})
        return json.dumps({"status": "pass", "analysis_method": "api", "warnings": []})
    monkeypatch.setattr(server, "_send_and_receive", fake)
    return sent


def test_validate_with_rhino_asset_loads(server, monkeypatch):
    bridge(server, monkeypatch, [TUB])
    plain = json.loads(server.validate_structure(guids=["beam"], load_kn=0.001))
    out = json.loads(server.validate_structure(guids=["beam"], load_kn=0.001, asset_loads=True))
    rep = out["asset_loads"]
    assert rep["applied"] == 1 and rep["placements"][0]["asset_id"] == "gen-bathtub-1"
    assert rep["placements"][0]["carried_by"][0]["source_guids"] == ["beam"]
    assert rep["total_kn"] == pytest.approx((45 + 260) * 9.81 / 1000, abs=1e-3)   # reported to 3 decimals
    assert out["results"]["max_deflection_mm"] > plain["results"]["max_deflection_mm"]


def test_validate_with_scene_ledger_placements(server, monkeypatch):
    sent = bridge(server, monkeypatch)
    scene = json.loads(server.create_design_scene(name="loads"))["scene"]["scene_id"]
    server.register_scene_instance(scene_id=scene, asset_id="gen-bathtub-1", x_mm=3000, y_mm=0, z_mm=3100)
    out = json.loads(server.validate_structure(guids=["beam"], load_kn=0.001, asset_loads=True, scene_id=scene))
    assert out["asset_loads"]["applied"] == 1 and out["asset_loads"]["placements"][0]["source"] == "scene"
    assert "asset_placements" not in [m["type"] for m in sent]
    bad = json.loads(server.validate_structure(guids=["beam"], asset_loads=True, scene_id="nope"))
    assert bad["status"] == "error" and "nope" in bad["message"]


def test_asset_loads_need_native_and_a_capable_bridge(server, monkeypatch):
    bridge(server, monkeypatch, [TUB])
    out = json.loads(server.validate_structure(guids=["beam"], asset_loads=True, engine="karamba"))
    assert out["status"] == "error" and "native" in out["message"]
    bridge(server, monkeypatch, placements_supported=False)
    out = json.loads(server.validate_structure(guids=["beam"], asset_loads=True))
    assert out["status"] == "error" and "update almondbridge" in out["message"]


def test_visualize_with_asset_loads_draws_load_points(server, monkeypatch):
    sent = bridge(server, monkeypatch, [TUB])
    out = json.loads(server.visualize_structure(guids=["beam"], load_kn=0.001, asset_loads=True))
    draw = next(m for m in sent if m["type"] == "structure_draw")
    assert "asset_loads" not in draw["result"]
    assert draw["load_label"] == "1 assets 3.0 kN + self weight"          # no generic load term when load_kn is 0
    assert [3.0, 0.0, 3.0] in [[round(v, 6) for v in p] for p in draw["result"]["loaded_points_m"]]
    assert out["asset_loads"]["applied"] == 1


def test_passport_includes_structural_loads(server):
    out = server.get_generated_asset_passport("gen-bathtub-1")
    loads = out["structural_loads"]
    assert loads["self_kg"] == 45 and loads["use_kg"] == 260 and "estimate" in loads["basis"]
