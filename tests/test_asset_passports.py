"""Portable identity, geometric fit, MCP discovery and install upgrades."""
import asyncio
import copy
import json
import struct
import shutil
from pathlib import Path

import pytest

from almond_mcp import __version__, asset_passport as ap, paths
from test_generated_assets import load_server_module

LIBRARY = Path(__file__).resolve().parents[1] / "GeneratedAssetfiles"


@pytest.fixture
def asset():
    assets = json.loads((LIBRARY / "manifest.json").read_text(encoding="utf-8"))["assets"]
    return next(a for a in assets if a["asset_id"] == "gen-park-bench-1")


def test_all_shipped_assets_have_consistent_verified_passports():
    result = ap.audit_library(LIBRARY)
    assert result["status"] == "success", result
    assert result["checked"] == 47


def test_audit_detects_tampering_and_contract_load_rejects_model_changes(asset, tmp_path):
    from almond_mcp import exchange
    (tmp_path / "models").mkdir()
    (tmp_path / "previews").mkdir()
    (tmp_path / "manifest.json").write_text(json.dumps({"assets": [asset]}))
    for rel in (asset["file"], asset["contract_file"], f"previews/{asset['asset_id']}.png"):
        shutil.copyfile(LIBRARY / rel, tmp_path / rel)
    assert ap.audit_library(tmp_path)["status"] == "success"
    path = tmp_path / asset["file"]
    data = path.read_bytes()
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    assert ap.audit_library(tmp_path)["failures"][0]["error"] == "Model checksum mismatch"
    with pytest.raises(ValueError, match="checksum"):
        exchange.load_contract(tmp_path / asset["contract_file"])


def test_embedding_is_idempotent_and_preserves_binary_and_unknown_chunks(asset):
    original = (LIBRARY / asset["file"]).read_bytes()
    original_chunks = ap.read_glb_chunks(original)
    unknown = struct.pack("<II", 4, 0x12345678) + b"test"
    original = original[:8] + struct.pack("<I", len(original) + len(unknown)) + original[12:] + unknown
    embedded = ap.embed_passport(original, asset["passport"])
    assert ap.read_glb_chunks(embedded)[1:] == original_chunks[1:] + [(0x12345678, b"test")]
    assert ap.embed_passport(embedded, asset["passport"]) == embedded
    before = json.loads(ap.read_glb_chunks(original)[0][1])
    after = json.loads(ap.read_glb_chunks(embedded)[0][1])
    for key in ("meshes", "accessors", "bufferViews", "buffers", "materials", "scenes"):
        assert after.get(key) == before.get(key)


@pytest.mark.parametrize("data", [b"", b"x" * 20, struct.pack("<III", 0x46546C67, 2, 24) + b"x" * 8])
def test_corrupt_glb_rejected(data):
    with pytest.raises(ValueError):
        ap.read_glb_chunks(data)


def test_fit_uses_asymmetric_clearances_rotation_and_height(asset):
    a = copy.deepcopy(asset)
    a["dimensions_mm"] = {"width": 1000, "depth": 400, "height": 850}
    a["spatial"]["clearance_mm"] = {"left": 100, "right": 200, "front": 500, "back": 50}
    assert ap.evaluate_fit(a, 1300, 950, 850)["fits"]
    assert not ap.evaluate_fit(a, 1299, 950, 850)["fits"]
    assert ap.evaluate_fit(a, 950, 1300, 850, 90)["fits"]
    assert not ap.evaluate_fit(a, 1300, 950, 849)["fits"]
    assert ap.evaluate_fit(a, 1000, 400, include_clearances=False)["fits"]
    rotated = ap.evaluate_fit(a, 2000, 2000, rotation_degrees=45)
    assert rotated["required_envelope_mm"]["width"] == pytest.approx(1590.99, abs=.01)


@pytest.mark.parametrize("width,depth,height,angle", [(0, 100, 0, 0), (100, -1, 0, 0),
    (100, 100, -1, 0), (float("nan"), 100, 0, 0), (100, 100, 0, float("inf"))])
def test_invalid_fit_inputs_fail(asset, width, depth, height, angle):
    with pytest.raises(ValueError):
        ap.evaluate_fit(asset, width, depth, height, angle)


def test_recommendation_respects_budget_room_availability_and_explains(asset):
    result = ap.recommend([asset], query="park bench", room_type="landscape", width_mm=4000, depth_mm=4000)
    row = result["assets"][0]
    assert row["asset_id"] == asset["asset_id"]
    assert row["reasons"] and row["fit_options"] and row["quality_notes"]
    assert ap.recommend([asset], max_triangles=1)["total_matches"] == 0
    assert ap.recommend([asset], room_type="bedroom")["total_matches"] == 0
    assert ap.recommend([asset], query="unfindable")["total_matches"] == 0
    assert ap.recommend([dict(asset, file_available=False)])["total_matches"] == 0
    with pytest.raises(ValueError):
        ap.recommend([asset], width_mm=2000)
    with pytest.raises(ValueError):
        ap.recommend([asset], max_triangles=-1)


def test_upgrade_uses_versioned_pack_and_repairs_missing_files(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "models").mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"current":true}')
    (bundle / "models" / "one.glb").write_bytes(b"test")
    user = tmp_path / "user"
    old = user / "GeneratedAssetfiles"
    old.mkdir(parents=True)
    (old / "manifest.json").write_text("old custom data")
    monkeypatch.delenv("RHINO_MCP_GENERATED_ASSET_DIR", raising=False)
    monkeypatch.setattr(paths, "_repo_dir", lambda name: None)
    monkeypatch.setattr(paths, "_bundled_data", lambda name: bundle)
    monkeypatch.setattr(paths, "user_data_dir", lambda: user)
    target = Path(paths.resolve_dir("RHINO_MCP_GENERATED_ASSET_DIR"))
    assert target == old / "releases" / __version__
    assert (old / "manifest.json").read_text() == "old custom data"
    (target / "models" / "one.glb").unlink()
    paths.resolve_dir("RHINO_MCP_GENERATED_ASSET_DIR")
    assert (target / "models" / "one.glb").read_bytes() == b"test"
    monkeypatch.setenv("RHINO_MCP_GENERATED_ASSET_DIR", str(old))
    assert paths.resolve_dir("RHINO_MCP_GENERATED_ASSET_DIR") == str(old)


def test_mcp_discovery_structured_result_and_preview_resource():
    from fastmcp import Client
    server = load_server_module()

    async def check():
        async with Client(server.mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert tools["recommend_generated_assets"].annotations.readOnlyHint
            assert tools["recommend_generated_assets"].outputSchema
            result = await client.call_tool("recommend_generated_assets", {"query": "bench"})
            assert not result.is_error
            assert result.structured_content["total_matches"] >= 1
            passport = await client.read_resource("almond://generated/gen-park-bench-1/passport")
            assert passport[0].mimeType == "application/json"
            assert json.loads(passport[0].text)["passport"]["asset_id"] == "gen-park-bench-1"
            preview = await client.read_resource("almond://generated/gen-park-bench-1/preview")
            assert preview[0].mimeType == "image/png"
            bad = await client.call_tool("evaluate_generated_asset_fit", {
                "asset_id": "unknown", "width_mm": 1000, "depth_mm": 1000})
            assert bad.structured_content["status"] == "error"
    asyncio.run(check())


def test_rhino_restore_script_contains_portable_metadata(asset):
    server = load_server_module()
    contract = json.loads((LIBRARY / asset["contract_file"]).read_text(encoding="utf-8"))
    contract["_imported_guids"] = []
    script = server._restore_and_place_script(contract, {}, 0, 0, 0, 0, "TEST")
    assert 'SetUserString("almond:passport", @"' in script
    assert '""schema_version"": 1' in script


def test_startup_diagnostics_do_not_pollute_mcp_stdout(capsys):
    load_server_module()
    assert capsys.readouterr().out == ""
