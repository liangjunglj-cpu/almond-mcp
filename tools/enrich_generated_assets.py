"""Upgrade existing normalised models without regenerating or moving geometry."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from almond_mcp import __version__
from almond_mcp.asset_passport import AssetPassport, enrich_asset


def main():
    library = REPO / "GeneratedAssetfiles"
    manifest_path = library / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for asset in manifest["assets"]:
        path = library / asset["contract_file"]
        contract = json.loads(path.read_text(encoding="utf-8"))
        enrich_asset(asset, contract, library / asset["file"], path)
    manifest["asset_pack_version"] = __version__
    manifest["passport_schema_version"] = 1
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (library / "passport.schema.json").write_text(
        json.dumps(AssetPassport.model_json_schema(), indent=2) + "\n", encoding="utf-8")
    print(f"Embedded passports in {len(manifest['assets'])} models; geometry unchanged.")


if __name__ == "__main__":
    main()
