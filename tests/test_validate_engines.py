"""validate_structure engine routing: native by default for line models, Karamba otherwise."""
import json

import pytest

from tests.test_capsules import _load_server

PORTAL = {"status": "ok", "shells": 0, "tolerance_m": 0.001, "max_span_m": 4.0, "max_member_span_m": 4.0,
          "warnings": [], "anchor_points": [[0, 0, 0], [4, 0, 0]],
          "members": [{"source_guids": ["c1"], "points": [[0, 0, 0], [0, 0, 3]], "section": {"shape": "circular_hollow", "diameter": 0.1143, "wall": 0.004}},
                      {"source_guids": ["c2"], "points": [[4, 0, 0], [4, 0, 3]], "section": {"shape": "circular_hollow", "diameter": 0.1143, "wall": 0.004}},
                      {"source_guids": ["b"], "points": [[0, 0, 3], [4, 0, 3]], "section": {"shape": "circular_hollow", "diameter": 0.1143, "wall": 0.004}}]}
KARAMBA = {"status": "pass", "passed": True, "verdict": "[KARAMBA 3.1 API, HIGH CONFIDENCE] PASSED",
           "results": {"analysis_method": "api", "span_m": 4.0}, "warnings": []}


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    return _load_server(monkeypatch, tmp_path, cap)


def bridge(server, monkeypatch, model_reply):
    calls = []

    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        calls.append(msg["type"])
        if msg["type"] == "structure_model":
            return json.dumps(model_reply)
        return json.dumps(KARAMBA)
    monkeypatch.setattr(server, "_send_and_receive", fake)
    return calls


def test_auto_uses_native_for_line_models(server, monkeypatch):
    calls = bridge(server, monkeypatch, PORTAL)
    out = json.loads(server.validate_structure(guids=["c1", "c2", "b"], structure_type="frame", load_kn=10))
    assert calls == ["structure_model"]
    assert out["results"]["analysis_method"] == "native" and out["status"] in ("pass", "fail")
    assert out["verdict"].startswith("[ALMOND NATIVE FEA")
    assert "construction_check" in out


def test_shells_fall_back_to_karamba_with_note(server, monkeypatch):
    calls = bridge(server, monkeypatch, dict(PORTAL, shells=2))
    out = json.loads(server.validate_structure(guids=["x"], structure_type="frame"))
    assert calls == ["structure_model", "validate"]
    assert out["results"]["analysis_method"] == "api"
    assert any("shell" in w and "Karamba" in w for w in out["warnings"])


def test_old_bridge_falls_back(server, monkeypatch):
    calls = bridge(server, monkeypatch, {"status": "error", "message": "unknown message"})
    out = json.loads(server.validate_structure(guids=["x"]))
    assert calls == ["structure_model", "validate"]
    assert any("update almondbridge" in w for w in out["warnings"])


def test_karamba_engine_and_shell_types_skip_native(server, monkeypatch):
    calls = bridge(server, monkeypatch, PORTAL)
    server.validate_structure(guids=["x"], engine="karamba")
    server.validate_structure(guids=["x"], structure_type="gridshell")
    assert calls == ["validate", "validate"]


def test_native_engine_required_reports_errors(server, monkeypatch):
    bridge(server, monkeypatch, dict(PORTAL, shells=1))
    out = json.loads(server.validate_structure(guids=["x"], engine="native"))
    assert out["status"] == "error" and "shell" in out["message"]
    assert json.loads(server.validate_structure(guids=["x"], engine="ansys"))["status"] == "error"


def test_native_options_reach_the_solver(server, monkeypatch):
    bridge(server, monkeypatch, PORTAL)
    out = json.loads(server.validate_structure(guids=["x"], structure_type="frame", load_kn=10,
                                               self_weight=False, span_m=6.0))
    r = out["results"]
    assert r["support_mode"] == "fixed" and r["span_basis"] == "user"
    assert r["deflection_limit_mm"] == pytest.approx(24.0)
    assert r["reactions_kn"] == pytest.approx(10.0, abs=1e-6)        # no self weight


def test_pinned_planar_portal_is_a_mechanism(server, monkeypatch):
    """A single portal on pinned bases can rock out of its plane: reported, not solved."""
    bridge(server, monkeypatch, PORTAL)
    out = json.loads(server.validate_structure(guids=["x"], structure_type="frame", fixed_supports=False))
    assert out["status"] == "fail" and "Mechanism" in out["verdict"]
    assert out["results"]["mechanism_nodes_m"]
