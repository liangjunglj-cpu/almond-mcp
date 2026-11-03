"""Licence scan for commercial distribution: what ships with almond-mcp and almondbridge, and under which terms.

    python tools/license_scan.py [--json]

Checks, against one allow-list of licences that permit commercial redistribution:
  1. the Python runtime dependency closure of almond-mcp (installed metadata; the optional `fast` extra too),
  2. the plugin's NuGet packages and the files vendored into the panel UI,
  3. every source behind the bundled environment data (almond_mcp/environment/data/sources.json).

Exit status 1 when anything is denied (copyleft that would bind the product, non-commercial or
no-derivatives terms) or unknown; "review" items (weak copyleft used unmodified, method citations) are
listed but do not fail. This is an engineering check, not legal advice.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "PSF-2.0", "Python-2.0", "0BSD", "Unlicense",
         "CC0-1.0", "CC-BY-4.0", "OGL-UK-3.0", "Zlib", "HPND", "MIT-CMU",
         "LicenseRef-EnergyPlus", "LicenseRef-PublicDomain-DE-UrhG-5", "LicenseRef-SG-ODL-1.0"}
REVIEW = {"MPL-2.0", "LGPL-2.1", "LGPL-3.0", "LicenseRef-Method-Cited", "LicenseRef-McNeel-SDK"}
DENY = re.compile(r"(?i)\b(A?GPL|SSPL|BUSL|CC-BY-(NC|ND|SA)|CC-BY-NC|non-?commercial)\b")
CLASSIFIER = {"MIT License": "MIT", "BSD License": "BSD-3-Clause", "Apache Software License": "Apache-2.0",
              "ISC License (ISCL)": "ISC", "Python Software Foundation License": "PSF-2.0",
              "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.1",
              "GNU General Public License v3 (GPLv3)": "GPL-3.0", "Historical Permission Notice and Disclaimer (HPND)": "HPND",
              "The Unlicense (Unlicense)": "Unlicense", "zlib/libpng License": "Zlib"}
TEXT = [(re.compile(r"(?i)^mit\b|mit license"), "MIT"), (re.compile(r"(?i)apache"), "Apache-2.0"),
        (re.compile(r"(?i)bsd.*3|3.?clause|new bsd|modified bsd"), "BSD-3-Clause"), (re.compile(r"(?i)bsd.*2|2.?clause|simplified bsd"), "BSD-2-Clause"),
        (re.compile(r"(?i)^bsd"), "BSD-3-Clause"), (re.compile(r"(?i)\bisc\b"), "ISC"), (re.compile(r"(?i)psf|python software"), "PSF-2.0"),
        (re.compile(r"(?i)mpl.?2|mozilla"), "MPL-2.0"), (re.compile(r"(?i)\blgpl"), "LGPL-2.1"), (re.compile(r"(?i)\bagpl"), "AGPL-3.0"),
        (re.compile(r"(?i)\bgpl"), "GPL-3.0"), (re.compile(r"(?i)hpnd|historical permission"), "HPND"), (re.compile(r"(?i)unlicense"), "Unlicense")]
# Dependencies whose metadata carries the licence only in a file: recorded after reading it.
KNOWN = {"numpy": "BSD-3-Clause", "numba": "BSD-2-Clause", "llvmlite": "BSD-2-Clause", "pillow": "MIT-CMU", "shapely": "BSD-3-Clause",
         "contourpy": "BSD-3-Clause", "certifi": "MPL-2.0", "typing-extensions": "PSF-2.0", "pywin32": "PSF-2.0"}
NUGET = {"Newtonsoft.Json": "MIT", "Microsoft.CodeAnalysis.CSharp": "MIT",
         "RhinoCommon": "LicenseRef-McNeel-SDK", "Grasshopper": "LicenseRef-McNeel-SDK"}
VENDORED = {"almond_mcp/library_ui/vendor/model-viewer.min.js": "Apache-2.0"}


def classify(expr: str) -> str:
    if not expr:
        return "unknown"
    parts = [p.strip("() ") for p in re.split(r"\s+(?:OR|AND|WITH)\s+|/", expr) if p.strip("() ")]
    if parts and all(p in ALLOW for p in parts):
        return "allow"
    if any(DENY.search(p) for p in parts) and not any(p in ALLOW for p in parts if " OR " in expr):
        return "deny"
    if any(p in REVIEW for p in parts):
        return "review"
    return "allow" if any(p in ALLOW for p in parts) and " OR " in expr else "unknown"


def dist_licence(d: metadata.Distribution) -> str:
    m = d.metadata
    name = (m["Name"] or "").lower()
    if name in KNOWN:
        return KNOWN[name]
    expr = m.get("License-Expression")
    if expr:
        return expr
    found = [CLASSIFIER.get(c.split(" :: ")[-1], c.split(" :: ")[-1]) for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
    found = [f for f in found if f not in ("OSI Approved",)]
    if found:
        return " OR ".join(dict.fromkeys(found))
    text = (m.get("License") or "").strip().splitlines()[0] if m.get("License") else ""
    for pat, spdx in TEXT:
        if pat.search(text):
            return spdx
    return text[:60]


def closure(root: str = "almond-mcp", extras: tuple[str, ...] = ("fast",)) -> dict[str, metadata.Distribution]:
    seen: dict[str, metadata.Distribution] = {}
    todo = [(root, set(extras))]
    while todo:
        name, ex = todo.pop()
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in seen:
            continue
        try:
            d = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = d
        for req in d.requires or []:
            spec, _, marker = req.partition(";")
            rname = re.split(r"[\s\[<>=!~;(]", spec.strip(), 1)[0]
            if marker:
                m_extra = re.search(r"extra\s*==\s*['\"]([^'\"]+)", marker)
                if m_extra and m_extra.group(1) not in ex:
                    continue
                if "sys_platform" in marker and "win32" not in marker and sys.platform == "win32" and "!=" not in marker:
                    continue
            todo.append((rname, set()))
    seen.pop("almond-mcp", None)
    return seen


def scan() -> dict:
    rows = []
    for key, d in sorted(closure().items()):
        lic = dist_licence(d)
        rows.append({"component": f"{d.metadata['Name']} {d.version}", "kind": "python", "licence": lic, "verdict": classify(lic)})
    csproj = (ROOT / "RhinoAlmondBridge" / "RhinoAlmondBridge.csproj").read_text(encoding="utf-8")
    for pkg, ver in re.findall(r'PackageReference Include="([^"]+)" Version="([^"]+)"', csproj):
        lic = NUGET.get(pkg, "unknown")
        shipped = "ExcludeAssets=\"runtime\"" not in re.search(rf'<PackageReference Include="{re.escape(pkg)}"[^>]*>', csproj).group(0)
        rows.append({"component": f"{pkg} {ver}", "kind": "nuget" + ("" if shipped else " (compile only, not shipped)"),
                     "licence": lic, "verdict": classify(lic) if shipped else "allow"})
    for rel, lic in VENDORED.items():
        rows.append({"component": rel, "kind": "vendored", "licence": lic,
                     "verdict": classify(lic) if (ROOT / rel).exists() else "unknown"})
    src = json.loads((ROOT / "almond_mcp/environment/data/sources.json").read_text(encoding="utf-8"))["sources"]
    for s in src:
        rows.append({"component": f"data: {s['id']}", "kind": "environment data", "licence": s["licence"], "verdict": classify(s["licence"])})
    bad = [r for r in rows if r["verdict"] in ("deny", "unknown")]
    return {"components": rows, "denied_or_unknown": bad, "review": [r for r in rows if r["verdict"] == "review"],
            "ok": not bad, "note": "Engineering licence check for commercial distribution; not legal advice."}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = scan()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report["components"]:
            print(f"{r['verdict']:7s}  {r['licence'][:34]:34s}  {r['kind']:28s}  {r['component']}")
        print(f"\n{'OK' if report['ok'] else 'FAIL'}: {len(report['denied_or_unknown'])} denied/unknown, {len(report['review'])} to review")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
