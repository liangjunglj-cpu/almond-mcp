"""The generated (Meshy) asset library: manifest truthfulness, contracts,
GLB normalisation, and server-side indexing/search."""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIBRARY = REPO / "GeneratedAssetfiles"
MANIFEST = LIBRARY / "manifest.json"
CATALOGUE = LIBRARY / "catalogue.json"
SERVER_PATH = REPO / "almond_mcp" / "server.py"

for extra in (REPO, REPO / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from almond_mcp import exchange  # noqa: E402
import build_generated_assets as build  # noqa: E402


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def catalogue() -> dict:
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_manifest_covers_every_catalogue_entry_with_present_files():
    ids_manifest = [a["asset_id"] for a in manifest()["assets"]]
    ids_catalogue = [a["asset_id"] for a in catalogue()["assets"]]
    assert ids_manifest == ids_catalogue
    assert len(ids_manifest) >= 30
    for asset in manifest()["assets"]:
        glb = LIBRARY / asset["file"]
        assert glb.is_file(), asset["asset_id"]
        assert sha256(glb) == asset["sha256"], asset["asset_id"]
        assert asset["license"] == "CC-BY-4.0"
        assert asset["geometry_source"]["generator"] == "meshy"
        assert asset["geometry_source"]["parameters"]["mesh_task_id"]
        assert asset["download_url"].endswith(asset["file"].split("/")[-1])


def test_contracts_load_and_agree_with_manifest():
    for asset in manifest()["assets"]:
        contract = exchange.load_contract(LIBRARY / asset["contract_file"])
        assert contract["asset_id"] == asset["asset_id"]
        assert contract["library_id"] == "generated_assets"
        assert contract["dimensions_mm"] == asset["dimensions_mm"]
        assert contract["materials"][0]["material_id"] == asset["render_material_id"]
        assert contract["spatial"]["clearance_mm"] == asset["spatial"]["clearance_mm"]


def test_glbs_are_normalised_to_bottom_centre_and_measured_dimensions():
    """Width is X, height is Y (glTF up), depth is Z; bottom-centre at origin."""
    for asset in manifest()["assets"]:
        gltf, binary = build.read_glb(LIBRARY / asset["file"])
        lo, hi, _ = build.world_bounds(gltf, binary)
        width, height, depth = (hi[a] - lo[a] for a in range(3))
        dims = asset["dimensions_mm"]
        assert width == pytest.approx(dims["width"], abs=1.0), asset["asset_id"]
        assert height == pytest.approx(dims["height"], abs=1.0), asset["asset_id"]
        assert depth == pytest.approx(dims["depth"], abs=1.0), asset["asset_id"]
        assert lo[1] == pytest.approx(0.0, abs=1.0), asset["asset_id"]
        assert (lo[0] + hi[0]) / 2 == pytest.approx(0.0, abs=1.0), asset["asset_id"]
        assert (lo[2] + hi[2]) / 2 == pytest.approx(0.0, abs=1.0), asset["asset_id"]
        # height is the catalogue height exactly (the axis we scale on)
        nominal = next(c for c in catalogue()["assets"] if c["asset_id"] == asset["asset_id"])
        assert dims["height"] == pytest.approx(nominal["dimensions_mm"]["height"], abs=0.5)


def test_glb_materials_carry_the_almond_identity():
    for asset in manifest()["assets"]:
        gltf, _ = build.read_glb(LIBRARY / asset["file"])
        names = {m.get("name") for m in gltf.get("materials", [])}
        assert names == {exchange.material_name(asset["render_material_id"])}, asset["asset_id"]
        for mesh in gltf["meshes"]:
            for prim in mesh["primitives"]:
                assert "material" in prim


def test_render_material_ids_exist_in_material_library():
    materials = json.loads((REPO / "Materialfiles" / "manifest.json").read_text(encoding="utf-8"))
    known = {m["material_id"] for m in materials["materials"]}
    for asset in manifest()["assets"]:
        assert asset["render_material_id"] in known, asset["asset_id"]


def load_server_module():
    os.environ["RHINO_MCP_GENERATED_ASSET_DIR"] = str(LIBRARY)
    os.environ["RHINO_MCP_STATE_DB"] = tempfile.mktemp(suffix=".sqlite3")
    spec = importlib.util.spec_from_file_location("almond_server_generated_test", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_server_indexes_and_searches_generated_library():
    server = load_server_module()
    expected = len(manifest()["assets"])
    assert len(server.generated_asset_indexer.assets) == expected
    assert all(a["file_available"] for a in server.generated_asset_indexer.assets.values())

    listing = json.loads(server.list_generated_assets(limit=50))
    assert listing["library_id"] == "generated_assets"
    assert listing["total"] == expected

    hits = json.loads(server.search_generated_assets(query="bench"))
    ids = [row["asset_id"] for row in hits["assets"]]
    assert "gen-park-bench-1" in ids

    low = json.loads(server.search_generated_assets(max_height_mm=1200, limit=50))
    low_ids = {row["asset_id"] for row in low["assets"]}
    assert "gen-tree-conifer-1" not in low_ids
    assert "gen-litter-bin-1" in low_ids

    one = json.loads(server.get_generated_asset("gen-door-single-1"))
    assert one["status"] == "success"
    assert one["asset"]["dimensions_mm"]["height"] == 2150

    # generated assets never leak into the IKEA search
    ikea = json.loads(server.search_ikea_furniture(query="bench"))
    assert all(not row["asset_id"].startswith("gen-")
               for row in ikea["assets"])

    status = json.loads(server.get_retrieval_status())
    assert status["generated_asset_index"]["total"] == expected


def test_place_generated_asset_rejects_bad_input_before_touching_rhino():
    server = load_server_module()
    unknown = json.loads(server.place_generated_asset("gen-does-not-exist"))
    assert unknown["status"] == "error"
    nan = json.loads(server.place_generated_asset("gen-park-bench-1", x_mm=float("nan")))
    assert nan["status"] == "error"
