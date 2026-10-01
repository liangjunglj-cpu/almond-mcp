"""Native structural check: Karamba cross-check benchmarks and the validation result contract.

Reference values (tests/data/karamba_reference.json) were recorded from live Karamba3D 3.1
runs on the same geometry and conventions. Karamba uses Timoshenko beams (shear
deformation) and the native solver Euler-Bernoulli, so deflections may differ by up to ~2 %
for these member slendernesses; utilization uses the same elastic design basis."""
import json
import math
from pathlib import Path

import pytest

from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns

REF = json.loads((Path(__file__).parent / "data" / "karamba_reference.json").read_text())
CASES = {c["id"]: c for c in REF["cases"]}


def model(case):
    mm = lambda p: [c / 1000 for c in p]
    members = [{"source_guids": [f"m{i}"], "points": [mm(p) for p in m]} for i, m in enumerate(case["members"])]
    spans = [math.dist(mm(m[0]), mm(m[1])) for m in case["members"]]
    return {"members": members, "anchor_points": [mm(p) for p in case["anchors"]], "tolerance_m": 0.001,
            "max_member_span_m": max(spans), "max_span_m": max(spans), "warnings": []}


RUNS = [(cid, i) for cid, c in CASES.items() for i in range(len(c["runs"]))]


@pytest.mark.parametrize("cid,i", RUNS)
def test_matches_karamba(cid, i):
    case, run = CASES[cid], CASES[cid]["runs"][i]
    frame, _, _ = ns.build_frame(model(case), run["load_kn"], "Steel", case["fixed_supports"], True, *run["section"])
    res = fs.solve(frame)
    assert res.max_displacement * 1000 == pytest.approx(run["max_displacement_mm"], rel=0.02)
    k_util = run.get("max_utilization") or max(run["utilization"])
    assert res.max_utilization == pytest.approx(k_util, rel=0.05)
    assert res.equilibrium_error() < 1e-6


def test_portal_nodes_and_members_match_karamba():
    case = CASES["portal_cantilever"]
    run = case["runs"][0]
    frame, _, _ = ns.build_frame(model(case), 10, "Steel", True, True, 114.3, 4.0)
    res = fs.solve(frame)
    for key, (dx, dy, dz) in run["nodes_m"].items():
        p = [float(v) for v in key.split(",")]
        n = min(range(len(frame.nodes)), key=lambda j: math.dist(frame.nodes[j], p))
        assert res.displacements[n, 0] == pytest.approx(dx, abs=3e-4)
        assert res.displacements[n, 2] == pytest.approx(dz, abs=max(3e-4, 0.02 * abs(dz)))
    # bending-governed members match closely; compression members use EN 1993 6.3 linear
    # interaction here and Karamba's own interaction factors there, so allow 15 %
    for er, k in zip(res.elements, run["utilization"]):
        compressed = er.util_detail.get("buckling") is not None
        assert er.utilization == pytest.approx(k, rel=0.15 if compressed else 0.05)


def test_section_iteration_reaches_the_same_answer():
    """Almond's sizing loop must stop at the same section with either engine (CHS 193.7x8)."""
    case = CASES["mezzanine"]
    passing = []
    for run in case["runs"][:5]:
        out = ns.validate(model(case), "frame", run["load_kn"], "Steel", False, True, *run["section"], span_m=6.2)
        assert out["results"]["span_basis"] == "user" and out["results"]["deflection_limit_mm"] == pytest.approx(24.8)
        passing.append(out["passed"])
    assert passing == [False, False, False, True, True]


def test_validation_result_contract():
    case = CASES["mezzanine"]
    out = ns.validate(model(case), "frame", 150, "Steel", fixed_supports=False, diameter_mm=114.3, wall_mm=4.0)
    assert out["status"] == "fail" and out["passed"] is False
    assert out["verdict"].startswith(ns.METHOD_PREFIX + "FAILED")
    r = out["results"]
    assert r["analysis_method"] == "native" and r["span_basis"] == "member"
    assert r["deflection_limit_mm"] == pytest.approx(3100 / 250)       # longest member 3.1 m
    assert r["max_deflection_mm"] == pytest.approx(183.013, rel=0.02)
    assert len(r["per_element_utilization"]) == 20
    assert r["support_mode"] == "pinned" and len(r["support_points_m"]) == 9
    assert r["reactions_kn"] > 150                                    # imposed load + self weight
    assert out["worst_member_guids"] and all(g.startswith("m") for g in out["worst_member_guids"])
    assert out["suggestions"] and out["confidence"] == "high"


def test_mechanism_returns_fail_not_crash():
    m = {"members": [{"source_guids": ["a"], "points": [[0, 0, 0], [4, 0, 0]]}],
         "anchor_points": [[0, 0, 0]], "tolerance_m": 0.001, "max_member_span_m": 4, "max_span_m": 4}
    out = ns.validate(m, "beam", 5, fixed_supports=False)
    assert out["status"] == "fail" and "Mechanism" in out["verdict"]


def test_far_anchor_is_ignored_with_warning_and_lowest_nodes_used():
    m = {"members": [{"source_guids": ["c"], "points": [[0, 0, 0], [0, 0, 3]]}],
         "anchor_points": [[5, 5, 5]], "tolerance_m": 0.001, "max_member_span_m": 3, "max_span_m": 3}
    out = ns.validate(m, "frame", 10)
    assert any("ignored" in w for w in out["warnings"])
    assert any("lowest-Z" in w for w in out["warnings"])
    assert out["results"]["support_points_m"] == [[0.0, 0.0, 0.0]]


def test_box_and_default_sections_from_spec():
    sec, _ = ns.section_from_spec({"shape": "box", "height": 0.2, "width": 0.1, "wall": 0.006})
    assert sec.shape == "rhs" and sec.dims_mm == pytest.approx((200, 100, 6))
    sec, _ = ns.section_from_spec(None)
    assert sec.name == "CHS 114.3x4"
    sec, notes = ns.section_from_spec({"shape": "circular_hollow", "diameter": 0.1, "wall": 0.08})
    assert sec.name == "CHS 114.3x4" and notes
