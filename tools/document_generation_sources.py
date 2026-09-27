"""Document recorded evidence without inventing missing generation history."""
import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def build_register(library: Path) -> dict:
    def read(name):
        return json.loads((library / name).read_text(encoding="utf-8"))

    manifest, catalogue, provenance = map(read, (
        "manifest.json", "catalogue.json", "provenance.json"))
    briefs = {a["asset_id"]: a for a in catalogue["assets"]}
    records, errors = [], []
    seen = set()
    for asset in manifest["assets"]:
        aid = asset["asset_id"]
        if aid in seen:
            errors.append(f"{aid}: duplicate asset ID")
        seen.add(aid)
        brief = briefs.get(aid, {})
        generation = asset.get("geometry_source", {}).get("parameters", {})
        history = provenance.get("assets", {}).get(aid, {})
        image_id = generation.get("image_task_id") or history.get("image_job_id")
        missing = [key for key in (
            "prompt", "image_model", "mesh_task_id",
            "mesh_model", "generated_at") if not generation.get(key)]
        if not image_id:
            missing.append("image_generation_id")
        if missing:
            errors.append(f"{aid}: missing recorded fields: {', '.join(missing)}")
        if not brief or brief.get("prompt") != generation.get("prompt"):
            errors.append(f"{aid}: catalogue prompt missing or differs from manifest")
        for key in ("image_task_id", "image_model", "mesh_task_id", "mesh_model", "generated_at"):
            if history.get(key) != generation.get(key):
                errors.append(f"{aid}: provenance {key} differs from manifest")
        if asset.get("passport", {}).get("provenance") != asset.get("geometry_source"):
            errors.append(f"{aid}: embedded-passport record differs from geometry source")
        records.append({
            "asset_id": aid,
            "name": asset["product"],
            "model_file": asset["file"],
            "model_sha256": asset["sha256"],
            "contract_file": asset["contract_file"],
            "contract_sha256": asset["contract_sha256"],
            "generator": asset.get("geometry_source", {}).get("generator"),
            "recorded_generation": generation,
            "recorded_task_history": {key: history[key] for key in (
                "image_provider", "image_model", "image_task_id", "image_job_id",
                "mesh_provider", "mesh_model", "mesh_task_id", "generated_at", "supersedes"
            ) if key in history},
            "image_generation": {
                "provider": history.get("image_provider", "meshy"),
                "provider_basis": "provenance" if history.get("image_provider") else "catalogue_image_stage_tool",
                "id": image_id,
                "id_type": "image_job_id" if history.get("image_job_id") else "image_task_id",
                "source_image_url_recorded": bool(history.get("image_url")),
                "source_image_url_policy": "Consult original provenance when needed; account-scoped URLs omitted here.",
            },
            "catalogue_recipe_override": brief.get("recipe_override"),
            "recipe_evidence": "catalogue.json#/generation_recipe; recipe intent, not a captured API request",
            "external_reference_status": "not_recorded_in_legacy_generation_evidence",
            "external_reference_ids": [],
            "evidence_gaps": [
                "Exact submitted request, seed and complete per-task settings are not captured in this register.",
                "Input image bytes and checksum are not linked in this register; provider task/job ID is retained.",
                "External design references are not recorded; absence of records does not establish no references were used.",
            ],
            "declared_license": asset.get("license"),
            "rights_evidence": "Existing manifest declaration; generating account entitlement not independently verified by this audit.",
            "missing_recorded_fields": missing,
        })
        captured = generation.get("captured_generation")
        if captured:
            if captured != history.get("captured_generation"):
                errors.append(f"{aid}: captured requests differ from provenance")
            image, mesh = captured["image"], captured["mesh"]
            if image["request"].get("prompt") != brief.get("prompt"):
                errors.append(f"{aid}: submitted image prompt differs from catalogue")
            if image["task_id"] != image_id or mesh["task_id"] != generation["mesh_task_id"] or mesh["request"].get("input_task_id") != image_id:
                errors.append(f"{aid}: captured task chain differs")
            image_path = (library / captured["input_image_file"]).resolve()
            if not image_path.is_relative_to(library.resolve()) or not image_path.is_file() or hashlib.sha256(image_path.read_bytes()).hexdigest() != image["output_sha256"]:
                errors.append(f"{aid}: retained input image checksum mismatch")
            derivation = captured["derivation"]
            if derivation["source_sha256"] != mesh["output_sha256"] or derivation["quality"]["triangles"] != asset["triangle_count"]:
                errors.append(f"{aid}: mesh derivation differs from recorded output")
            records[-1].update(
                recipe_evidence="Exact submitted API requests and downloaded input-image checksum retained in captured_generation.",
                external_reference_status=captured["external_reference_status"],
                evidence_gaps=["Provider seed was not returned where null.",
                               "Dimensions are authored study sizes, not verified physical measurements.",
                               "Mesh self-intersections and fabrication suitability have not been certified."],
                rights_evidence=captured["rights"],
            )
            records[-1]["image_generation"].update(input_file=captured["input_image_file"], sha256=image["output_sha256"])
    return {
        "schema_version": 1,
        "library_id": manifest["library_id"],
        "evidence_basis": ["manifest.json", "catalogue.json", "provenance.json"],
        "scope": "Audit of local records, not verification with Meshy or proof of complete generation history.",
        "status": "inconsistent" if errors else "consistent_with_documented_gaps",
        "asset_count": len(records),
        "errors": errors,
        "assets": records,
    }


def serialise(register: dict) -> str:
    return json.dumps(register, indent=2, ensure_ascii=True) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the saved register is stale or records disagree")
    args = parser.parse_args()
    library = REPO / "GeneratedAssetfiles"
    result = build_register(library)
    target = library / "source-register.json"
    content = serialise(result)
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            raise SystemExit("Source register is stale; run tools/document_generation_sources.py")
    else:
        target.write_text(content, encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("status", "asset_count", "errors")}, indent=2))
    raise SystemExit(bool(result["errors"]))


if __name__ == "__main__":
    main()
