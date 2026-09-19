import importlib.util
import json
import os
import tempfile
from pathlib import Path


SERVER_PATH = Path(__file__).resolve().parents[1] / "almond_mcp" / "server.py"
FURNITURE_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "IkeaFurniturefiles" / "manifest.json"
)


def manifest_asset_count() -> int:
    manifest = json.loads(FURNITURE_MANIFEST_PATH.read_text(encoding="utf-8"))
    return len(manifest["assets"])


def load_server_module():
    os.environ["RHINO_MCP_FURNITURE_DIR"] = str(
        Path(__file__).resolve().parents[1] / "IkeaFurniturefiles"
    )
    os.environ["RHINO_MCP_STATE_DB"] = tempfile.mktemp(suffix=".sqlite3")
    spec = importlib.util.spec_from_file_location("almond_server_test", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_furniture_manifest_indexes_optional_downloads(tmp_path):
    server = load_server_module()
    # Every manifest entry must be indexed; the library grows over time, so the
    # expected count comes from the manifest itself instead of a magic number.
    expected = manifest_asset_count()
    assert expected >= 5
    assert not hasattr(server, "furniture_indexer")
    # Community downloads are intentionally absent from clean checkouts and
    # release packages. Exercise both states without needing licensed files.
    (tmp_path / "manifest.json").write_bytes(FURNITURE_MANIFEST_PATH.read_bytes())
    index = server.AssetLibraryIndexer(str(tmp_path), "ikea", "test furniture")
    assert len(index.assets) == expected
    assert not any(asset["file_available"] for asset in index.assets.values())

    first = next(iter(index.assets.values()))
    fixture = tmp_path / first["file"]
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_bytes(b"availability-test-only; not model geometry")
    index = server.AssetLibraryIndexer(str(tmp_path), "ikea", "test furniture")
    assert {a["asset_id"] for a in index.assets.values() if a["file_available"]} == {first["asset_id"]}


def test_search_filters_by_category_dimensions_and_match_quality():
    server = load_server_module()
    index = server.AssetLibraryIndexer(str(FURNITURE_MANIFEST_PATH.parent), "ikea", "historical fixture")
    matches = index.search(
        query="compact living room",
        category="sofa",
        max_width_mm=2000,
        exact_dimensions_only=True,
    )
    assert [asset["asset_id"] for asset in matches] == ["ikea-sg-klippan-s49010615"]


def test_public_tool_output_does_not_expose_resolved_paths():
    server = load_server_module()
    payload = json.loads(server.search_generated_assets(query="chair"))
    # The hit count drifts as the catalogue grows; what matters here is that
    # matches exist and none of them leak local paths or supplier URLs.
    assert payload["total"] >= 1
    assert payload["assets"]
    assert all("_resolved_file" not in asset for asset in payload["assets"])
    assert all("warehouse_url" not in asset for asset in payload["assets"])

def test_retired_supplier_has_no_public_tools_or_active_catalogue():
    server = load_server_module()
    for name in ("list_ikea_furniture", "search_ikea_furniture", "get_ikea_furniture", "place_ikea_furniture"):
        assert not hasattr(server, name)
    assert server.retrieval_store.asset_stats("ikea")["total"] == 0
