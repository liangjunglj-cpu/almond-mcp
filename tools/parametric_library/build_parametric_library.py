"""Build (or check) the annotated parametric library in ParametricLibrary/.

Inputs (tracked):   ParametricLibrary/lessons/*.lesson.json
                    ParametricLibrary/upstream/<owner>__<repo>/<path>   (as downloaded; plus .ghx when binary)
                    ParametricLibrary/LICENSES/<owner>__<repo>.txt
Outputs (tracked):  ParametricLibrary/definitions/<id>.ghx, catalogue.json, source-register.json
                    ParametricLibrary/previews/<id>.png  (--previews, needs matplotlib)
                    ParametricLibrary/capsules/<id>.harnessed.ghx + <capsule_id>.capsule.json
                    (for lessons with a "harness" block; see harness_ghx.py)

    python tools/parametric_library/build_parametric_library.py            # rebuild
    python tools/parametric_library/build_parametric_library.py --check    # verify, write nothing

The build is deterministic and needs no Rhino: binary upstream .gh files are
converted to .ghx once with gh_convert.ps1 (Rhino 8 GH_IO) and the .ghx is kept
beside the original. Nothing in a definition is ever solved or executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from annotate_ghx import annotate  # noqa: E402
from ghx_inspect import inspect  # noqa: E402
from harness_ghx import harness, manifest_for  # noqa: E402
from logic_fingerprint import fingerprint  # noqa: E402

LIBRARY = HERE.parents[1] / "ParametricLibrary"
ACCESS_DATE = "2026-10-11"
GEOMETRY_PARAMS = {"Curve", "Surface", "Brep", "Geometry", "Point", "Mesh", "Line", "Circle", "Plane"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copyright_line(licence_text: str) -> str | None:
    for line in licence_text.splitlines():
        if line.lower().startswith("copyright (c)") or line.startswith("Copyright ©"):
            return line.strip()
    return None


def build(library: Path, out: Path) -> tuple[dict, dict, list[str]]:
    entries, register, problems = [], [], []
    for lesson_path in sorted((library / "lessons").glob("*.lesson.json")):
        lesson = json.loads(lesson_path.read_text(encoding="utf-8"))
        src = lesson["source"]
        key = src["repo"].replace("/", "__")
        original = library / "upstream" / key / src["path"]
        upstream = original.with_suffix(".ghx")
        licence_file = library / "LICENSES" / f"{key}.txt"
        licence_text = licence_file.read_text(encoding="utf-8")
        target = out / "definitions" / f"{lesson['id']}.ghx"
        log = annotate(upstream, lesson, target, licence_text)
        before, after = fingerprint(upstream, log["overrides"]), fingerprint(target)
        if before != after:
            problems.append(f"{lesson['id']}: logic fingerprint changed")
        info = inspect(target)
        plugins = [lib["Name"] for lib in info["libraries"] if lib["Name"] not in ("Grasshopper",)]
        entries.append({
            "id": lesson["id"], "title": lesson["title"], "category": lesson["category"], "level": lesson["level"],
            "summary": lesson["summary"], "definition": f"definitions/{lesson['id']}.ghx",
            "lesson": f"lessons/{lesson_path.name}", "preview": f"previews/{lesson['id']}.png",
            "steps": [s["title"] for s in lesson["steps"]],
            "inputs": [i["nickname"] for i in info["inputs"]],
            "geometry_inputs": [i["nickname"] for i in info["inputs"] if i["type"] in GEOMETRY_PARAMS],
            "plugins": plugins,
            "scripts": [{"language": s["language"], "imports": s["imports"]} for s in info["scripts"]],
            "author": src["author"], "licence": src["licence"], "source_id": f"gh:{src['repo']}@{src['commit'][:12]}:{src['path']}",
        })
        capsule = None
        if lesson.get("harness"):
            # Runnable derivative: the teaching file plus ALMOND_IN_*/ALMOND_OUT_* sockets (harness_ghx.py).
            spec = lesson["harness"]
            harnessed = out / "capsules" / f"{lesson['id']}.harnessed.ghx"
            manifest_path = out / "capsules" / f"{spec['capsule_id']}.capsule.json"
            capsule_log = harness(target, lesson, harnessed)
            mapped = fingerprint(harnessed, drop=capsule_log["objects"], substitutions=capsule_log["substitutions"])
            if mapped != after:
                problems.append(f"{lesson['id']}: harnessed capsule does not map back onto the teaching logic")
            manifest = manifest_for(lesson, capsule_log, harnessed.name)
            write_json(manifest_path, manifest)
            entries[-1]["capsule"] = {"capsule_id": spec["capsule_id"], "capability": manifest["capability"],
                                      "definition": f"capsules/{harnessed.name}", "manifest": f"capsules/{manifest_path.name}",
                                      "audited": manifest["audited"]}
            capsule = {
                "capsule_id": spec["capsule_id"], "definition": f"capsules/{harnessed.name}",
                "manifest": f"capsules/{manifest_path.name}", "audited": manifest["audited"],
                "derivation": {
                    "step": "harness", "tool": "tools/parametric_library/harness_ghx.py",
                    "input": f"definitions/{lesson['id']}.ghx", "input_sha256": sha256(target),
                    "output_sha256": sha256(harnessed), "manifest_sha256": sha256(manifest_path),
                    "changes": "ALMOND_IN_*/ALMOND_OUT_* params, a group, titles and a note added; every wire leaving a "
                               "replaced input moved to its ALMOND_IN_* param; replaced sliders and params left in place, "
                               "disconnected; no component, value or script changed",
                    "replaced": capsule_log["replaced"], "rewired_sources": capsule_log["rewired_sources"],
                    "defaults": capsule_log["defaults"], "harness_objects": capsule_log["objects"],
                    "substitutions": capsule_log["substitutions"],
                    "logic_fingerprint_unchanged_after_mapping": mapped == after,
                },
            }
        derivation = []
        if original.suffix == ".gh":
            derivation.append({"step": "convert", "tool": "tools/parametric_library/gh_convert.ps1 (Rhino 8 GH_IO.dll)",
                               "note": "archive-level .gh -> .ghx conversion; nothing instantiated or solved",
                               "input_sha256": sha256(original), "output_sha256": sha256(upstream)})
        derivation.append({"step": "annotate", "tool": "tools/parametric_library/annotate_ghx.py",
                           "lesson": f"lessons/{lesson_path.name}", "input_sha256": sha256(upstream),
                           "output_sha256": sha256(target),
                           "changes": "objects moved into stage blocks; nicknames relabelled per lesson; groups, scribbles, "
                                      "README/LICENCE/step panels added; original groups split across stages and listed "
                                      "notes removed",
                           "relabelled": log["relabelled"], "dropped_groups": log["dropped_groups"],
                           "dropped_notes": lesson.get("drop_notes", []),
                           "value_overrides": log["overrides"],
                           "logic_fingerprint_unchanged_except_overrides": before == after, "logic_objects": len(before)})
        register.append({
            "id": lesson["id"],
            "source": {"repo_url": f"https://github.com/{src['repo']}", "path": src["path"], "commit": src["commit"],
                       "raw_url": f"https://raw.githubusercontent.com/{src['repo']}/{src['commit']}/"
                                  f"{urllib.parse.quote(src['path'])}",
                       "author": src["author"], "access_date": ACCESS_DATE, "upstream_sha256": sha256(original)},
            "rights": {"licence": src["licence"], "licence_url": src["licence_url"],
                       "licence_file": f"LICENSES/{key}.txt", "copyright": copyright_line(licence_text),
                       "adaptation": "permitted by licence", "redistribution": "permitted by licence",
                       "obligations": "keep the licence text and copyright notice with every copy (embedded in the "
                                      "definition's LICENCE panel and in LICENSES/)"},
            "relationship": "adapted_definition",
            "derivation": derivation,
        })
        if capsule:
            register[-1]["harnessed"] = capsule
    catalogue = {"schema": "almond-parametric-catalogue/1",
                 "description": "Annotated teaching versions of openly licensed Grasshopper definitions. "
                                "Logic is unchanged from upstream; see source-register.json.",
                 "entries": entries}
    return catalogue, {"schema": "almond-parametric-source-register/1", "items": register}, problems


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--library", type=Path, default=LIBRARY)
    ap.add_argument("--check", action="store_true", help="rebuild in a temp dir and compare; write nothing")
    ap.add_argument("--previews", action="store_true", help="also render canvas previews (needs matplotlib)")
    a = ap.parse_args()
    if a.check:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue, register, problems = build(a.library, Path(tmp))
            for entry in catalogue["entries"]:
                outputs = [entry["definition"]]
                if entry.get("capsule"):
                    outputs += [entry["capsule"]["definition"], entry["capsule"]["manifest"]]
                for rel in outputs:
                    built, tracked = Path(tmp) / rel, a.library / rel
                    if not tracked.exists() or sha256(built) != sha256(tracked):
                        problems.append(f"{rel} is stale; rebuild")
            for name, data in (("catalogue.json", catalogue), ("source-register.json", register)):
                tracked = a.library / name
                if not tracked.exists() or json.loads(tracked.read_text(encoding="utf-8")) != data:
                    problems.append(f"{name} is stale; rebuild (upstream hashes are part of the register)")
        for p in problems:
            print("FAIL", p)
        print("check:", "ok" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    catalogue, register, problems = build(a.library, a.library)
    write_json(a.library / "catalogue.json", catalogue)
    write_json(a.library / "source-register.json", register)
    if a.previews:
        import subprocess
        (a.library / "previews").mkdir(exist_ok=True)
        for entry in catalogue["entries"]:
            subprocess.run([sys.executable, str(HERE / "render_canvas.py"), str(a.library / entry["definition"]),
                            str(a.library / entry["preview"])], check=True)
    for p in problems:
        print("FAIL", p)
    print(f"built {len(catalogue['entries'])} definitions", "" if not problems else f"with {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
