"""Captured Meshy evidence and useful topology survive library packaging."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

from almond_mcp.asset_repository import AssetRepository

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "GeneratedAssetfiles"
spec = importlib.util.spec_from_file_location("organic_sources", ROOT / "tools/document_generation_sources.py")
source_doc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_doc)


def test_organic_assets_preserve_detail_and_generation_chain():
    repo = AssetRepository()
    batch = json.loads((LIBRARY / "batches/organic-2026-09.json").read_text())
    assert repo.search("organic-2026-09")["total"] == 3
    for brief in batch["assets"]:
        if brief["asset_id"] not in batch["release_assets"]:
            continue
        record = repo.records[brief["asset_id"]]
        captured = record["provenance"]["recorded_generation"]["captured_generation"]
        q = captured["derivation"]["quality"]
        assert 70000 <= q["triangles"] <= brief["target_triangles"] + 100
        assert captured["derivation"]["source_triangles"] >= q["triangles"]
        assert not q["nonfinite_coordinates"] and not q["zero_area_faces"]
        assert not q["nonmanifold_edges_excluding_boundary"]
        assert max(q["bounds_relative_change"]) < 0.02
        assert captured["mesh"]["request"]["input_task_id"] == captured["image"]["task_id"]
        assert captured["image"]["request"]["prompt"] == brief["prompt"]
        assert hashlib.sha256(repo.files[record["generation_image"]][1].read_bytes()).hexdigest() == captured["image"]["output_sha256"]


def test_source_audit_rejects_changed_generation_image(tmp_path):
    for name in ("manifest.json", "catalogue.json", "provenance.json"):
        shutil.copyfile(LIBRARY/name, tmp_path/name)
    shutil.copytree(LIBRARY/"batches", tmp_path/"batches")
    image = next((tmp_path/"batches/organic-2026-09").glob("*.png"))
    image.write_bytes(b"changed")
    result = source_doc.build_register(tmp_path)
    assert any("retained input image checksum mismatch" in error for error in result["errors"])
