"""Asset contract building/loading and generated cross-app scripts."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from almond_mcp import exchange  # noqa: E402

BOUNDS = {"min": [-900.0, -225.0, 0.0], "max": [900.0, 225.0, 450.0]}
MATERIALS = [{"material_id": "wood-oak", "objects": ["slat_0", "slat_1"]}]


def make_contract(asset_id="bench-01"):
    return exchange.build_contract(
        asset_id=asset_id, name="Slatted bench", glb_filename=f"{asset_id}.glb",
        bounds_mm=BOUNDS, materials=MATERIALS, source_app="blender",
        source_units="m", object_count=7,
    )


def test_material_name_round_trip():
    assert exchange.material_name("wood-oak") == "ALMOND::wood-oak"
    assert exchange.material_id_from_name("ALMOND::wood-oak") == "wood-oak"
    assert exchange.material_id_from_name("Default") == ""
    assert exchange.material_id_from_name("") == ""


def test_srgb_to_linear_matches_reference_points():
    assert exchange.srgb_to_linear(0) == pytest.approx(0.0)
    assert exchange.srgb_to_linear(255) == pytest.approx(1.0)
    # mid grey is famously ~0.2159 linear, never 0.5
    assert exchange.srgb_to_linear(128) == pytest.approx(0.2158, abs=1e-3)


def test_build_contract_records_real_dimensions():
    contract = make_contract()
    assert contract["dimensions_mm"] == {"width": 1800.0, "depth": 450.0, "height": 450.0}
    assert contract["spatial"]["anchor"] == "bottom_center"
    assert contract["schema_version"] == exchange.CONTRACT_VERSION
    assert contract["materials"] == MATERIALS


def test_build_contract_rejects_bad_ids_and_bounds():
    with pytest.raises(ValueError):
        exchange.build_contract("has spaces", "x", "x.glb", BOUNDS, [], "rhino")
    with pytest.raises(ValueError):
        exchange.build_contract("ok-id", "x", "x.glb",
                                {"min": [0, 0], "max": [1, 1, 1]}, [], "rhino")


def test_load_contract_round_trip_and_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        glb, contract_path = exchange.contract_paths(tmp, "bench-01")
        glb.write_bytes(b"glTF-stub")
        contract_path.write_text(json.dumps(make_contract()), encoding="utf-8")

        loaded = exchange.load_contract(contract_path)
        assert loaded["asset_id"] == "bench-01"
        assert Path(loaded["_resolved_file"]).name == "bench-01.glb"

        glb.unlink()
        with pytest.raises(FileNotFoundError):
            exchange.load_contract(contract_path)


def test_load_contract_refuses_newer_schema():
    with tempfile.TemporaryDirectory() as tmp:
        glb, contract_path = exchange.contract_paths(tmp, "future-01")
        glb.write_bytes(b"glTF-stub")
        contract = make_contract("future-01")
        contract["schema_version"] = exchange.CONTRACT_VERSION + 5
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        with pytest.raises(ValueError, match="newer"):
            exchange.load_contract(contract_path)


def test_dimension_report_is_rotation_agnostic():
    contract = make_contract()
    # rotated 90 degrees: width and depth swap, must still pass
    rotated = {"width": 450.0, "depth": 1800.0, "height": 450.0}
    assert exchange.dimension_report(contract, rotated)["status"] == "ok"
    # a real scale error must fail
    wrong = {"width": 900.0, "depth": 225.0, "height": 225.0}
    report = exchange.dimension_report(contract, wrong)
    assert report["status"] == "mismatch"
    assert report["worst_relative_error"] > 0.4


def test_blender_export_script_measures_evaluated_mesh():
    script = exchange.blender_export_script("bench-01", "Bench", r"C:\tmp\out")
    # the whole point: bound_box lies for curves, so vertices are used
    assert "to_mesh()" in script
    assert ".bound_box" not in script          # attribute access, not the comment
    assert "export_scene.gltf" in script
    assert "bench-01" in script
    assert exchange.CONTRACT_SUFFIX in script


def test_blender_material_script_converts_to_linear():
    material = {
        "material_id": "wood-oak", "name": "Oak", "category": "wood",
        "base_color": [200, 170, 130], "metallic": 0.0, "roughness": 0.65,
        "opacity": 1.0, "ue_material_slot": "M_Wood_Oak",
    }
    script = exchange.blender_material_script(
        [material], [{"material_id": "wood-oak", "objects": ["slat_0"]}])
    assert "ALMOND::" in script
    assert "almond:ue_material_slot" in script
    # linear values, not the raw sRGB bytes (200/255 = 0.784 would be naive)
    assert "0.7843" not in script
    assert repr(exchange.srgb_to_linear(200)) in script
    # the sRGB byte string is still carried for metadata fidelity
    assert '"200,170,130"' in script
