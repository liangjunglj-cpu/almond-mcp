"""visualize_structure: request shaping and argument checks (no Rhino required)."""
import json

import pytest

from tests.test_capsules import _load_server


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    return _load_server(monkeypatch, tmp_path, cap)


def _capture(server, monkeypatch, reply=None):
    sent = {}

    def fake(payload, timeout=60.0):
        sent.update(json.loads(payload.decode("utf-8")))
        sent["_timeout"] = timeout
        return json.dumps(reply or {"status": "pass", "max_displacement_mm": 4.2})
    monkeypatch.setattr(server, "_send_and_receive", fake)
    return sent


def test_sends_structure_view_request(server, monkeypatch):
    sent = _capture(server, monkeypatch)
    out = json.loads(server.visualize_structure(guids=["a", "b"], load_kn=20, beam_diameter_mm=168.3,
                                                color_by="utilization", scale=40, title="Mezzanine",
                                                span_m=6.2, fixed_supports=False, display_guids=["b"]))
    assert out["status"] == "pass"
    assert sent["type"] == "structure_view"
    assert sent["guids"] == ["a", "b"] and sent["load_kn"] == 20
    assert sent["beam_diameter_mm"] == 168.3 and sent["beam_wall_mm"] == pytest.approx(168.3 / 20)
    assert sent["color_by"] == "utilization" and sent["scale"] == 40 and sent["title"] == "Mezzanine"
    assert sent["reanalyze"] is True and sent["reveal"] == 1.0
    assert sent["span_m"] == 6.2 and sent["fixed_rotations"] is False and sent["display_guids"] == ["b"]


def test_display_only_update_and_reveal_clamp(server, monkeypatch):
    sent = _capture(server, monkeypatch)
    server.visualize_structure(guids=["a"], reanalyze=False, reveal=3.0, physics=False)
    assert sent["reanalyze"] is False and sent["reveal"] == 1.0 and sent["physics"] is False
    assert "scale" not in sent and "beam_diameter_mm" not in sent and "span_m" not in sent and "display_guids" not in sent


def test_clear_needs_no_guids(server, monkeypatch):
    sent = _capture(server, monkeypatch, {"status": "cleared"})
    assert json.loads(server.visualize_structure(clear=True))["status"] == "cleared"
    assert sent["clear"] is True


def test_rejects_missing_guids_and_bad_colour(server, monkeypatch):
    def forbid(*a, **k):
        raise AssertionError("bridge must not be called")
    monkeypatch.setattr(server, "_send_and_receive", forbid)
    assert json.loads(server.visualize_structure())["status"] == "error"
    assert json.loads(server.visualize_structure(guids=["a"], color_by="stress"))["status"] == "error"
