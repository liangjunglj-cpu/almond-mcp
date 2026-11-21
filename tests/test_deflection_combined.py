"""The two deflection fixes together (release 0.8.0): deflection is measured member-relative (a column from
the chord through the floors that hold it, sway checked as storey drift; fix/deflection-verdicts) AND each
member is judged against its own span (the governing member named; PR #37), with one verdict for
validate_structure, the panel's overlay and visualize_structure."""
import json

import pytest

from almond_mcp import native_structure as ns
from almond_mcp import structure_study as st
from tests.test_deflection_verdicts import FLOOR, leaning_frame, old_bridge, server  # noqa: F401 (fixture)

H, LEAN = 3.5, 0.02


def girder_and_joist():
    """A 12 m girder (L/675 under self weight) and a soft 3 m joist (L/580): the joist governs against its own
    span. Judged against one fixed 3 m span, the girder would fail (17.8 mm > 12 mm)."""
    stiff = {"shape": "circular_hollow", "diameter": 0.2191, "wall": 0.006}
    soft = {"shape": "circular_hollow", "diameter": 0.0269, "wall": 0.0023}
    members = [{"source_guids": ["girder"], "name": "G1", "points": [[0, 0, 0], [12, 0, 0]], "section": stiff},
               {"source_guids": ["joist"], "name": "J1", "points": [[0, 5, 0], [3, 5, 0]], "section": soft}]
    return {"members": members, "anchor_points": [[0, 0, 0], [12, 0, 0], [0, 5, 0], [3, 5, 0]],
            "tolerance_m": 0.001, "max_member_span_m": 12.0, "max_span_m": 13.0, "warnings": [], "status": "ok",
            "shells": 0}


KW = dict(fixed_supports=False, stability="off")


def test_columns_are_measured_floor_to_floor_against_the_storey_height():
    """A four-storey column line is one member (its pieces run on in line). Held by every floor, it is measured
    from the chord through the floors (its sway is the storey drift) and judged against the storey height:
    neither as a cantilever of twice the building height nor with the sway counted as deflection."""
    m = leaning_frame(4, h=H, lean=LEAN)
    out = ns.validate(m, "frame", 0, floor_loads=FLOOR, stability="off", detail=True)
    storey = H * (1 + LEAN ** 2) ** 0.5
    cols = [r for r in out["members"] if r["source_guids"][0].startswith("c")]
    assert len(cols) == 16
    for r in cols:
        assert r["deflection_span_m"] == pytest.approx(storey, rel=1e-3)          # not 2 x 14 m
    upper = [r for r in cols if not r["source_guids"][0].endswith("_0")]
    assert all(r["deflection_mm"] < 0.2 * r["max_displacement_mm"] for r in upper)  # the sway is not deflection
    drift = out["results"]["storey_drift"]
    assert drift["checked"] and len(drift["storeys"]) == 4 and drift["max_drift_mm"] > 0
    g = out["results"]["governing_deflection"]
    assert g["kind"] == "member" and g["member"].startswith("M") and g["span_m"] == pytest.approx(6.0)
    assert out["results"]["span_m"] == pytest.approx(6.0) and out["status"] == "pass"


def test_each_member_against_its_own_span_in_validate_the_overlay_and_the_panel(server, monkeypatch):  # noqa: F811
    m = girder_and_joist()
    ref = ns.validate(m, "beam", 0.0, **KW)
    r = ref["results"]
    assert ref["status"] == "pass" and r["governing_deflection"]["member"] == "J1"
    assert r["span_m"] == pytest.approx(3.0) and r["deflection_limit_mm"] == pytest.approx(12.0)
    assert r["largest_deflection_mm"] > r["deflection_limit_mm"]               # the girder's, on its 12 m span
    # one fixed span for every member would fail the girder: the overlay must not do that
    assert ns.validate(m, "beam", 0.0, span_m=3.0, **KW)["status"] == "fail"

    res, span = ns.view_result(m, 0.0, structure_type="beam", **KW)
    v = res["verdict"]
    assert v["status"] == "pass" and v["governing_deflection"]["member"] == "J1" and span == pytest.approx(3.0)
    assert v["max_deflection_mm"] == pytest.approx(r["max_deflection_mm"], rel=1e-6)
    assert v["deflection_limit_mm"] == pytest.approx(r["deflection_limit_mm"])

    panel = st.run({"protocol": 1, "model": m, "settings": {"structure": "beam", "load_kn": 0, "stability": "off",
                                                             "fixed_rotations": False}})
    assert panel["validation"]["status"] == "pass" and panel["draw"]["verdict_status"] == "pass"
    assert panel["draw"]["span_m"] == pytest.approx(3.0)
    assert panel["draw"]["result"]["deflection_limit_mm"] == pytest.approx(12.0)

    old_bridge(server, monkeypatch, m, "fail")
    out = json.loads(server.visualize_structure(guids=["x"], load_kn=0, fixed_supports=False, stability="off"))
    assert out["status"] == "pass" and out["governing_deflection"]["member"] == "J1"
    assert out["deflection_limit_mm"] == pytest.approx(12.0)


def test_one_verdict_names_the_member_span_and_the_storey_drift():
    """A swaying portal with soft beams: the beam fails against its own 6 m span (named), and the sway fails as
    storey drift; the overlay's verdict lists the same failures."""
    m = leaning_frame(1, lean=0.2, beam=(0.1143, 0.0036))
    out = ns.validate(m, "frame", 400, **KW)
    assert out["status"] == "fail"
    assert "(span 6.00 m) exceeds L/250 limit (24.0mm)" in out["verdict"] and "Storey drift" in out["verdict"]
    res, span = ns.view_result(m, 400, structure_type="frame", **KW)
    v = res["verdict"]
    assert v["status"] == "fail" and span == pytest.approx(6.0)
    kinds = [f.split(" ")[0] for f in v["failures"]]
    assert kinds == [f.split(" ")[0] for f in out["verdict"].split("FAILED: ")[1].split("; ")]
    assert kinds == ["Deflection", "Utilization", "Storey"]
    assert v["governing_deflection"]["member"] == out["results"]["governing_deflection"]["member"]
    assert v["storey_drift"]["governing"]["drift_mm"] == pytest.approx(
        out["results"]["storey_drift"]["governing"]["drift_mm"])
