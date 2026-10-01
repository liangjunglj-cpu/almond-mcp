"""Loads from placed library assets: data coverage, placement onto members, closed-form checks."""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from almond_mcp import asset_loads as al
from almond_mcp import frame_solver as fs
from almond_mcp import native_structure as ns

ROOT = Path(__file__).resolve().parents[1]
TABLE = al.LoadTable(ROOT / "GeneratedAssetfiles" / "structural-loads.json")
CATALOGUE = {a["asset_id"]: a for a in json.loads((ROOT / "GeneratedAssetfiles" / "catalogue.json").read_text())["assets"]}
STEEL, SEC = fs.material("Steel"), fs.chs(114.3, 4.0)
EI = STEEL.E * SEC.Iy


def test_every_library_asset_has_load_data():
    for aid, a in CATALOGUE.items():
        entry = TABLE.lookup(aid, a["category"])
        assert entry is not None and entry["source"] == "asset", aid
        assert entry["self_kg"] >= 0 and entry["use_kg"] >= 0, aid
    assert set(TABLE.assets) <= set(CATALOGUE), "load entries for assets that are not in the catalogue"


def beam(L=6.0, z=3.0, y=0.0):
    f = fs.Frame()
    a, b = f.add_node((0, y, z)), f.add_node((L, y, z))
    f.add_element(a, b, SEC, STEEL, tag=[f"beam@{y}"])
    f.fix(a, (True, True, True, True, False, False))
    f.fix(b, (False, True, True, False, False, False))
    return f


def box(asset, cx, cy, z0, w=0.5, d=0.5, h=0.8, scale=1.0):
    return {"id": asset + "@", "asset_id": asset, "min": [cx - w / 2, cy - d / 2, z0], "max": [cx + w / 2, cy + d / 2, z0 + h],
            "scale": scale, "source": "test"}


def kn(asset, scale=1.0):
    e = TABLE.lookup(asset, CATALOGUE[asset]["category"])
    return (e["self_kg"] * scale ** 3 + e["use_kg"]) * al.G / 1000


def test_point_load_at_midspan_matches_closed_form():
    f = beam()
    rep = al.apply(f, [box("gen-bathtub-1", 3.0, 0.0, 3.1)], TABLE, CATALOGUE)
    P = kn("gen-bathtub-1")
    assert rep["applied"] == 1 and rep["total_kn"] == pytest.approx(P, rel=1e-3)
    r = fs.solve(f)
    mid = min(range(len(f.nodes)), key=lambda i: abs(f.nodes[i][0] - 3.0))
    assert r.displacements[mid, 2] == pytest.approx(-P * 6.0 ** 3 / (48 * EI), rel=1e-6)
    assert r.reactions[:, 2].sum() == pytest.approx(P, rel=1e-9)


def test_lever_rule_between_parallel_members():
    f = fs.Frame()
    for y in (0.0, 3.0):
        a, b = f.add_node((0, y, 3)), f.add_node((6, y, 3))
        f.add_element(a, b, SEC, STEEL, tag=[f"beam@{y}"])
    rep = al.apply(f, [box("gen-toilet-1", 3.0, 1.0, 3.1)], TABLE, CATALOGUE)
    shares = {c["source_guids"][0]: c["share"] for c in rep["placements"][0]["carried_by"]}
    assert shares == pytest.approx({"beam@0.0": 2 / 3, "beam@3.0": 1 / 3}, abs=1e-3)
    loads = sum(v[2] for v in f.nodal_loads.values())
    assert loads == pytest.approx(-kn("gen-toilet-1"), rel=1e-9)


def test_ceiling_pendant_hangs_from_the_level_above_and_work_surface_reaches_down():
    f = beam(z=3.0)
    rep = al.apply(f, [box("gen-pendant-lamp-sphere-1", 2.0, 0.0, 2.0, h=0.64),
                       box("gen-task-lamp-balanced-arm-1", 4.0, 0.0, 3.9, h=0.45)], TABLE, CATALOGUE)
    assert [("carried_by" in r) for r in rep["placements"]] == [True, True]
    assert rep["placements"][0]["level_m"] == 3.0


@pytest.mark.parametrize("asset,cx,z0,reason", [
    ("gen-car-sedan-1", 3.0, 3.1, "ground-only"),
    ("gen-shelving-modular-track-1", 3.0, 3.1, "wall mounted"),
    ("gen-column-round-1", 3.0, 3.1, "structural element"),
    ("gen-sofa-3-seat-1", 3.0, 0.0, "no frame level below"),
    ("gen-sofa-3-seat-1", 9.0, 3.1, "outside the frame"),
])
def test_skipped_placements_are_reported(asset, cx, z0, reason):
    f = beam()
    rep = al.apply(f, [box(asset, cx, 0.0, z0)], TABLE, CATALOGUE)
    assert rep["applied"] == 0 and reason in rep["placements"][0]["skipped"]
    assert not f.nodal_loads


def test_unknown_asset_and_category_default():
    f = beam()
    rep = al.apply(f, [box("not-in-library", 3, 0, 3.1)], TABLE, {})
    assert rep["placements"][0]["skipped"] == "no load data for this asset"
    rep = al.apply(f, [box("ikea-something", 3, 0, 3.1)], TABLE, {"ikea-something": {"category": "bed"}})
    assert rep["placements"][0]["load_basis"] == "category_default" and rep["applied"] == 1


def test_loads_are_the_nominal_products_and_odd_sizes_are_flagged():
    cat = {k: dict(v, nominal_mm=v["dimensions_mm"]) for k, v in CATALOGUE.items()}   # catalogue.json sizes are nominal
    f = beam()
    rep = al.apply(f, [box("gen-bed-double-1", 3, 0, 3.1, w=1.65, d=2.1, scale=1.3)], TABLE, cat)
    row = rep["placements"][0]
    assert row["self_kg"] == 90 and row["use_kg"] == 160          # scale corrects meshes, not mass
    assert row["size_ratio"] == pytest.approx(1.0) and "warning" not in row
    rep = al.apply(beam(), [box("gen-bed-double-1", 3, 0, 3.1, w=3.5, d=3.6)], TABLE, cat)
    assert "nominal product" in rep["placements"][0]["warning"]


def test_split_element_does_not_change_the_answer():
    """Splitting at 0.3 L: the new node's deflection equals the unsplit member's exact
    interior deflection there (member loads follow both halves)."""
    def frame():
        f = beam()
        f.gravity = (0, 0, -1)
        f.udl(0, (0, 0, -2.0))
        return f
    whole = fs.solve(frame()).elements[0].disp[3, 2]          # station s = 0.3 of 11
    f = frame()
    k = f.split_element(0, 0.3)
    assert fs.solve(f).displacements[k, 2] == pytest.approx(whole, rel=1e-9)


def test_validate_reports_asset_loads():
    model = {"members": [{"source_guids": ["b"], "points": [[0, 0, 3], [6, 0, 3]]}], "tolerance_m": 0.001,
             "anchor_points": [[0, 0, 3], [6, 0, 3]], "max_member_span_m": 6, "max_span_m": 6}
    base = ns.validate(model, "beam", 0.001)
    out = ns.validate(model, "beam", 0.001, asset_loads={"placements": [box("gen-bathtub-1", 3, 0, 3.1)],
                                                         "table": TABLE, "catalogue": CATALOGUE})
    assert out["asset_loads"]["applied"] == 1 and out["asset_loads"]["total_kn"] > 2.9
    assert out["results"]["max_deflection_mm"] > base["results"]["max_deflection_mm"]
    assert any("Asset loads" in a for a in out["assumptions"])


def test_placements_from_scene_ledger_rows():
    rows = [{"instance_id": "i1", "asset_id": "gen-desk-1", "min_x": 0, "max_x": 1400, "min_y": 0, "max_y": 700,
             "min_z": 3100, "max_z": 3850, "scale": 1}]
    p = al.placements_from_scene(rows)[0]
    assert p["min"] == [0, 0, 3.1] and p["max"] == [1.4, 0.7, 3.85] and p["source"] == "scene"
