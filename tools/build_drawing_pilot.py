"""Build ten traceable plan/elevation packages, without changing source models."""
import html
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from almond_mcp import __version__, drafting

IDS = ["gen-park-bench-1", "gen-office-chair-1", "gen-dining-table-rect-1",
       "gen-sofa-3-seat-1", "gen-bed-double-1", "gen-washbasin-pedestal-1",
       "gen-street-lamp-1", "gen-tree-conifer-1", "gen-person-standing-1",
       "gen-stool-bent-birch-3leg-1"]


def main():
    library, target = REPO/"GeneratedAssetfiles", REPO/"Draftingfiles"
    assets = {a["asset_id"]: a for a in json.loads((library/"manifest.json").read_text())["assets"]}
    sources = {a["asset_id"]: a for a in json.loads((library/"source-register.json").read_text())["assets"]}
    records = []
    for aid in IDS:
        asset = assets[aid]
        out = target/"pilot"/aid
        if out.exists():
            audit = drafting.audit_package(out, library/asset["file"])
            if audit["status"] != "success":
                raise ValueError(f"Existing pilot requires a new revision: {audit}")
            manifest = json.loads((out/"drawing.json").read_text())
        else:
            result = drafting.create_package(library/asset["file"], out, asset_id=aid,
                name=asset["product"], units="mm", source_record=sources[aid])
            manifest = result["manifest"]
        records.append({"asset_id": aid, "name": asset["product"],
                        "package": f"pilot/{aid}", "scales": manifest["scales"],
                        "geometry_sha256": manifest["source"]["geometry_sha256"]})
        print(aid, flush=True)
    (target/"manifest.json").write_text(json.dumps({"schema_version": 1,
        "asset_pack_version": __version__, "assets": records}, indent=2), encoding="utf-8")
    cards = []
    for r in records:
        for scale in r["scales"]:
            rel = f'{r["package"]}/sheet-A3-1-{scale}.svg'
            if (target/rel).exists():
                cards.append(f'<section><h2>{html.escape(r["name"])} / 1:{scale}</h2><a href="{rel}"><img src="{rel}" alt="{html.escape(r["name"])} drawing sheet" loading="lazy"></a></section>')
    (target/"index.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Almond drafting pilot</title><style>body{background:#eef0ef;color:#182526;font:16px Arial;margin:40px auto;max-width:1150px}h1{font-size:36px}section{margin:40px 0}h2{font-size:18px}img{width:100%;background:white;box-shadow:0 5px 24px #0001}p{line-height:1.6}</style><h1>Almond / Drawing library</h1><p>Ten generated models. Measured mesh outlines in plan and elevation, with full-size DXF, scaled SVG, and source records. Print the individual A3 SVG at actual size. Internal construction and hidden edges are not inferred.</p>'+"".join(cards)+"</html>", encoding="utf-8")


if __name__ == "__main__":
    main()
