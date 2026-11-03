"""validate_structure history and export_structural_report: what a run records and how it reads."""
import inspect
import json
import sqlite3

import pytest

from almond_mcp import native_structure as ns
from almond_mcp.retrieval_store import AlmondStore
from tests.test_capsules import _load_server
from tests.test_validate_engines import KARAMBA, PORTAL

CHS = {"shape": "circular_hollow", "diameter": 0.1937, "wall": 0.008}
CORNERS = [[0, 0], [4, 0], [4, 3], [0, 3]]


def bay_frame():
    """One 4 x 3 m bay: four columns and four beams enclosing a floor at z = 3 m."""
    cols = [{"source_guids": [f"col{i}"], "points": [[x, y, 0], [x, y, 3]], "section": CHS}
            for i, (x, y) in enumerate(CORNERS)]
    beams = [{"source_guids": [f"beam{i}"], "points": [[*CORNERS[i], 3], [*CORNERS[(i + 1) % 4], 3]], "section": CHS}
             for i in range(4)]
    return {"status": "ok", "shells": 0, "tolerance_m": 0.001, "max_span_m": 5.0, "max_member_span_m": 4.0,
            "warnings": [], "anchor_points": [[x, y, 0] for x, y in CORNERS], "members": cols + beams}


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    return _load_server(monkeypatch, tmp_path, cap)


def use_model(server, monkeypatch, model):
    def fake(payload, timeout=60.0):
        msg = json.loads(payload.decode("utf-8"))
        return json.dumps(model if msg["type"] == "structure_model" else KARAMBA)
    monkeypatch.setattr(server, "_send_and_receive", fake)


def report(server, tmp_path):
    out = json.loads(server.export_structural_report(path=str(tmp_path / "report.md")))
    assert out["status"] == "success"
    return (tmp_path / "report.md").read_text(encoding="utf-8")


def test_indicative_runs_are_recorded_and_labelled(server, monkeypatch, tmp_path):
    use_model(server, monkeypatch, PORTAL)
    out = json.loads(server.validate_structure(guids=["c1", "c2", "b"], structure_type="frame", load_kn=5,
                                               material="Concrete"))
    assert out["status"] == "indicative" and out["passed"] is None and out["confidence"] == "low"
    assert "construction_check" in out
    run = server.retrieval_store.list_validation_runs()[0]
    assert run["status"] == "indicative" and run["passed"] is None
    text = report(server, tmp_path)
    assert "| low |" in text and "| INDICATIVE |" in text
    assert "(INDICATIVE, no pass/fail)" in text and "FAIL" not in text.split("## Run details")[1].split("verdict")[0]


def test_native_verdict_prefix_follows_confidence():
    model = {k: v for k, v in PORTAL.items() if k != "status"}
    timber = ns.validate(model, "frame", 5, "Wood")
    steel = ns.validate(model, "frame", 5, "Steel")
    assert timber["confidence"] == "low"
    assert timber["verdict"].startswith("[ALMOND NATIVE FEA (LINEAR 3D FRAME), LOW CONFIDENCE] ")
    assert steel["confidence"] == "high" and steel["verdict"].startswith(ns.METHOD_PREFIX)
    assert ns.method_prefix("high") == ns.METHOD_PREFIX
    # a stability or mechanism failure on an indicative material is low confidence too
    loose = dict(model, anchor_points=[[0, 0, 0]])
    mech = ns.validate(loose, "frame", 5, "Aluminium", fixed_supports=False)
    assert mech["status"] == "fail" and mech["verdict"].startswith("[ALMOND NATIVE FEA (LINEAR 3D FRAME), LOW CONFIDENCE]")


def test_report_lists_floor_loads_design_code_connections_and_stability(server, monkeypatch, tmp_path):
    use_model(server, monkeypatch, bay_frame())
    guids = [f"col{i}" for i in range(4)] + [f"beam{i}" for i in range(4)] + ["pt0", "pt1", "pt2", "pt3"]
    out = json.loads(server.validate_structure(guids=guids, structure_type="frame", load_kn=0, floor_load_kn_m2=2.0,
                                               floor_dead_kn_m2=1.0, connections="simple"))
    assert out["status"] in ("pass", "fail")
    assert out["floor_loads"]["total_kn"] == pytest.approx(36.0)        # 3 kN/m2 x 12 m2
    run = server.retrieval_store.list_validation_runs()[0]
    assert run["member_count"] == 8 and run["object_count"] == 12       # support points are not members
    st = run["settings"]
    assert st["applied_by"] == "native" and st["floor_load_kn_m2"] == 2.0 and st["connections"] == "simple"
    text = report(server, tmp_path)
    assert "- input: 8 member(s) from 12 object(s), 4 support point(s)" in text
    assert "point load 0.0 kN, floor 2 kN/m2 imposed + 1 kN/m2 dead (36.0 kN over 12.0 m2)" in text
    assert "- design: Eurocode" in text and "basis en1990, ULS 6.10, deflection limit span/250" in text
    assert "- connections: simple (" in text and "pinned member end(s)" in text
    assert "- stability: auto, " in text and "alpha_cr" in text
    assert "**native**" in text and "**Karamba**" in text                # header covers both routes


def test_karamba_runs_say_native_settings_were_not_applied(server, monkeypatch, tmp_path):
    use_model(server, monkeypatch, PORTAL)
    server.validate_structure(guids=["x"], engine="karamba")
    run = server.retrieval_store.list_validation_runs()[0]
    assert run["settings"]["applied_by"] == "karamba"
    assert "Karamba route: unfactored G + Q, deflection limit L/250" in report(server, tmp_path)


def test_unrecorded_statuses_stay_out_of_the_history(server, monkeypatch):
    use_model(server, monkeypatch, PORTAL)
    monkeypatch.setattr(server, "_send_and_receive", lambda payload, timeout=60.0: json.dumps(
        {"status": "unavailable", "passed": False, "verdict": "Karamba could not solve this setup."}))
    server.validate_structure(guids=["x"], engine="karamba")
    assert server.retrieval_store.list_validation_runs() == []


def test_validate_structure_docstring_lists_every_status(server):
    doc = inspect.getdoc(getattr(server.validate_structure, "fn", server.validate_structure))
    for status in ('"pass"', '"fail"', '"indicative"', '"unavailable"', '"incomplete"', '"error"'):
        assert status in doc


def test_old_history_rows_survive_the_schema_upgrade(tmp_path):
    db = tmp_path / "state.sqlite3"
    AlmondStore(db)
    with sqlite3.connect(db) as conn:                       # roll the table back to the 0.7.0rc2 schema
        conn.execute("DROP TABLE validation_runs")
        conn.execute("""CREATE TABLE validation_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ran_at TEXT NOT NULL,
            structure_type TEXT NOT NULL, material TEXT NOT NULL, load_kn REAL NOT NULL, member_count INTEGER NOT NULL,
            analysis_method TEXT NOT NULL, confidence TEXT NOT NULL, passed INTEGER NOT NULL, span_m REAL NOT NULL,
            max_deflection_mm REAL NOT NULL, deflection_limit_mm REAL NOT NULL, utilization_ratio REAL NOT NULL,
            max_stress_mpa REAL NOT NULL, yield_stress_mpa REAL NOT NULL, reactions_kn REAL NOT NULL,
            verdict TEXT NOT NULL, warnings_json TEXT NOT NULL, guids_json TEXT NOT NULL)""")
        conn.execute("""INSERT INTO validation_runs VALUES (NULL, '2026-10-01T00:00:00Z', 'beam', 'Steel', 10, 2,
            'api', 'high', 1, 4, 1, 16, 0.2, 40, 235, 10, 'PASSED', '[]', '["a","b"]')""")
    store = AlmondStore(db)
    old = store.list_validation_runs()[0]
    assert old["status"] == "pass" and old["passed"] is True and old["object_count"] == 2 and old["settings"] == {}
    from almond_mcp import server as srv
    assert "not recorded for this older run" in srv._render_validation_report([old])


def test_execute_script_adds_a_dimension_only_on_request(server, monkeypatch):
    sent = []
    monkeypatch.setattr(server, "_send_and_receive",
                        lambda payload, timeout=60.0: sent.append(json.loads(payload)) or '{"status": "success"}')
    run = getattr(server.execute_rhino_script, "fn", server.execute_rhino_script)
    run(script="class S {}")
    run(script="class S {}", add_dimension=True)
    assert "add_dimension" not in sent[0] and sent[1]["add_dimension"] is True


def slender_box_frame():
    """Four CHS columns carrying more utilization than two thin 300x300x3 boxes, which are Class 4 in S355."""
    box = {"shape": "box", "height": 0.30, "width": 0.30, "wall": 0.003}
    col = {"shape": "circular_hollow", "diameter": 0.0889, "wall": 0.0032}
    m = bay_frame()
    m["members"] = ([dict(c, section=col) for c in m["members"][:4]] +
                    [dict(b, section=box) for b in m["members"][4:6]])
    return {k: v for k, v in m.items() if k != "status"}


def test_failing_members_rank_first_in_worst_member_guids():
    out = ns.validate(slender_box_frame(), "frame", 40, "S355", detail=True)
    status = {m["source_guids"][0]: (m["status"], m["utilization"]) for m in out["members"]}
    assert status["beam0"][0] == status["beam1"][0] == "fail"
    assert max(u for s, u in status.values() if s == "fail") < min(status[f"col{i}"][1] for i in range(4))
    assert out["worst_member_guids"][:2] == ["beam0", "beam1"]


def test_class4_hint_follows_the_section_family():
    out = ns.validate(slender_box_frame(), "frame", 40, "S355")
    hints = [s for s in out["suggestions"] if "Class 4" in s]
    assert len(hints) == 1 and "RHS" in hints[0] and "CHS" not in hints[0] and "34.2" in hints[0]
    from almond_mcp import ec3
    chs = ns._class4_hint("chs", type("M", (), {"fy": 355e3, "name": "S355"})())
    assert "CHS" in chs and "59.6" in chs and ec3.epsilon(355e3) == pytest.approx(0.8136, abs=1e-4)


def test_reading_the_numbers_covers_native_runs():
    from almond_mcp import server as srv
    run = {"id": 1, "ran_at": "2026-11-03T00:00:00Z", "structure_type": "frame", "analysis_method": "native",
           "confidence": "high", "span_m": 4, "max_deflection_mm": 1, "deflection_limit_mm": 16,
           "utilization_ratio": 0.3, "reactions_kn": 10, "member_count": 3, "object_count": 3, "status": "pass",
           "passed": True, "material": "Steel", "load_kn": 10, "settings": {}, "verdict": "ok", "warnings": []}
    notes = " ".join(srv._render_validation_report([run]).split("## Reading the numbers")[1].split())
    assert "Only **api**" not in notes and "native and **api** runs are finite element analysis" in notes
    assert "Karamba **api** runs only" in notes and "does not affect native runs" in notes
