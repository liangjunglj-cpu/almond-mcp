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


def test_furniture_manifest_and_files_are_indexed():
    server = load_server_module()
    # Every manifest entry must be indexed; the library grows over time, so the
    # expected count comes from the manifest itself instead of a magic number.
    expected = manifest_asset_count()
    assert expected >= 5
    assert len(server.furniture_indexer.assets) == expected
    assert all(asset["file_available"] for asset in server.furniture_indexer.assets.values())


def test_search_filters_by_category_dimensions_and_match_quality():
    server = load_server_module()
    matches = server.furniture_indexer.search(
        query="compact living room",
        category="sofa",
        max_width_mm=2000,
        exact_dimensions_only=True,
    )
    assert [asset["asset_id"] for asset in matches] == ["ikea-sg-klippan-s49010615"]


def test_public_tool_output_does_not_expose_resolved_paths():
    server = load_server_module()
    payload = json.loads(server.search_ikea_furniture(query="reading chair"))
    # The hit count drifts as the catalogue grows; what matters here is that
    # matches exist and none of them leak local paths or supplier URLs.
    assert payload["total"] >= 1
    assert payload["assets"]
    assert all("_resolved_file" not in asset for asset in payload["assets"])
    assert all("warehouse_url" not in asset for asset in payload["assets"])
