"""visualize_structure on the native engine: solve in Python, draw through structure_draw."""
import json

import pytest

from tests.test_capsules import _load_server
from tests.test_validate_engines import PORTAL


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    return _load_server(monkeypatch, tmp_path, cap)


def bridge(server, monkeypatch, model_reply, draw_ok=True):
    sent = []

    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        sent.append(msg)
        if msg["type"] == "structure_model":
            return json.dumps(model_reply)
        if msg["type"] == "structure_draw" and draw_ok:
            return json.dumps({"status": "pass", "analysis_method": "native", "max_displacement_mm": 1.0})
        if msg["type"] == "structure_draw":
            return json.dumps({"status": "compile_error", "message": "unknown"})
        return json.dumps({"status": "pass", "analysis_method": "api", "warnings": []})
    monkeypatch.setattr(server, "_send_and_receive", fake)
    return sent


def test_native_view_sends_solved_result(server, monkeypatch):
    sent = bridge(server, monkeypatch, PORTAL)
    out = json.loads(server.visualize_structure(guids=["c1", "c2", "b"], load_kn=10, color_by="utilization",
                                                scale=20, span_m=4.0, title="Portal"))
    assert [m["type"] for m in sent] == ["structure_model", "structure_draw"]
    draw = sent[1]
    assert draw["engine"] == "native" and draw["span_m"] == 4.0 and draw["scale"] == 20 and draw["title"] == "Portal"
    res = draw["result"]
    assert {g for e in res["elements"] for g in e["source_guids"]} == {"c1", "c2", "b"}
    assert all(len(e["samples_m"]) == 13 for e in res["elements"])
    assert res["support_points_m"] == [[0.0, 0.0, 0.0], [4.0, 0.0, 0.0]]
    assert res["max_displacement_mm"] > 0
    assert out["status"] == "pass" and out["nodes"] >= 4            # compression members are subdivided for stability


def test_display_only_update_reuses_native_overlay(server, monkeypatch):
    sent = bridge(server, monkeypatch, PORTAL)
    server.visualize_structure(guids=["c1"], load_kn=10)
    server.visualize_structure(guids=["c1"], reanalyze=False, reveal=0.5, physics=False)
    last = sent[-1]
    assert last["type"] == "structure_draw" and "result" not in last
    assert last["reveal"] == 0.5 and last["physics"] is False


def test_falls_back_to_karamba_for_shells_and_old_bridges(server, monkeypatch):
    sent = bridge(server, monkeypatch, dict(PORTAL, shells=1))
    out = json.loads(server.visualize_structure(guids=["x"]))
    assert sent[-1]["type"] == "structure_view" and any("shell" in w for w in out["warnings"])
    sent = bridge(server, monkeypatch, PORTAL, draw_ok=False)
    out = json.loads(server.visualize_structure(guids=["x"]))
    assert sent[-1]["type"] == "structure_view" and any("cannot draw" in w for w in out["warnings"])


def test_karamba_engine_and_mechanism(server, monkeypatch):
    sent = bridge(server, monkeypatch, PORTAL)
    server.visualize_structure(guids=["x"], engine="karamba")
    assert [m["type"] for m in sent] == ["structure_view"]
    out = json.loads(server.visualize_structure(guids=["x"], fixed_supports=False, engine="native"))
    assert out["status"] == "fail" and "Mechanism" in out["message"]
