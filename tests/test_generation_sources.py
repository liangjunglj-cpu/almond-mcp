"""Source history must remain honest and detect stale or conflicting evidence."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_doc", ROOT / "tools/document_generation_sources.py")
source_doc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_doc)


def test_shipped_source_register_matches_evidence():
    library = ROOT / "GeneratedAssetfiles"
    result = source_doc.build_register(library)
    assert not result["errors"]
    assert result["asset_count"] == 52
    assert result == json.loads((library / "source-register.json").read_text())
    assert all(a["external_reference_ids"] == [] and a["evidence_gaps"] for a in result["assets"])
    higgsfield = [a for a in result["assets"] if a["image_generation"]["provider"] == "higgsfield"]
    assert len(higgsfield) == 20
    assert all(a["image_generation"]["id_type"] == "image_job_id" for a in higgsfield)
    assert "cloudfront.net" not in source_doc.serialise(result)


def test_missing_and_conflicting_history_is_reported(tmp_path):
    for name in ("manifest.json", "catalogue.json", "provenance.json"):
        data = json.loads((ROOT / "GeneratedAssetfiles" / name).read_text())
        if name == "provenance.json":
            first = next(iter(data["assets"].values()))
            first["mesh_task_id"] = "incorrect-task"
        if name == "manifest.json":
            del data["assets"][0]["geometry_source"]["parameters"]["image_task_id"]
        (tmp_path / name).write_text(json.dumps(data))
    result = source_doc.build_register(tmp_path)
    assert result["status"] == "inconsistent"
    assert any("missing recorded fields: image_generation_id" in error for error in result["errors"])
    assert any("provenance mesh_task_id differs" in error for error in result["errors"])
