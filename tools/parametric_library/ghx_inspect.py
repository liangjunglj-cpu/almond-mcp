"""Structural inspection of Grasshopper .ghx (XML) archives.

Reads the archive tree only. Nothing is executed; script component source is
measured, never run. Usage:
    python -I ghx_inspect.py <ghx file|dir> <out.json>
"""
import base64
import binascii
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

SCRIPT_HINTS = ("script", "python", "c#", "vb ", "ghpython", "ironpython")
INPUT_KINDS = {"Number Slider", "Boolean Toggle", "Panel", "Value List", "Digit Scroller",
               "MD Slider", "Gradient", "Colour Swatch", "Button", "Graph Mapper", "Control Knob"}


def items(chunk):
    """Map item name -> list of (index, element) for a chunk's <items>."""
    out = defaultdict(list)
    block = chunk.find("items")
    if block is not None:
        for it in block.findall("item"):
            out[it.get("name")].append(it)
    return out


def text(chunk, name, default=None):
    found = items(chunk).get(name)
    if not found:
        return default
    el = found[0]
    return el.text if el.text is not None else "".join(el.itertext()).strip()


def sub(chunk, name):
    block = chunk.find("chunks")
    if block is None:
        return []
    return [c for c in block.findall("chunk") if c.get("name") == name]


def first(chunk, name):
    found = sub(chunk, name)
    return found[0] if found else None


def pivot(container):
    attrs = first(container, "Attributes")
    if attrs is None:
        return None
    p = items(attrs).get("Pivot")
    if not p:
        return None
    x, y = p[0].find("X"), p[0].find("Y")
    return [float(x.text), float(y.text)] if x is not None and y is not None else None


def param_record(chunk):
    it = items(chunk)
    return {
        "guid": text(chunk, "InstanceGuid"),
        "name": text(chunk, "Name"),
        "nickname": text(chunk, "NickName"),
        "description": text(chunk, "Description"),
        "sources": [s.text for s in it.get("Source", [])],
        "access": text(chunk, "Access"),
        "has_persistent": first(chunk, "PersistentData") is not None,
    }


def script_params(container, kind):
    """Rhino 8 script components keep their params under ParameterData."""
    data = first(container, "ParameterData")
    return sub(data, kind) if data is not None else []


def script_source(container):
    """Return (language, source) for a script component without running it."""
    legacy = text(container, "CodeInput") or text(container, "ScriptSource")
    if legacy:
        return "python2/csharp (legacy)", legacy
    script = first(container, "Script")
    if script is None:
        return None, ""
    raw = text(script, "Text") or ""
    try:
        src = base64.b64decode(raw).decode("utf-8", "replace")
    except (ValueError, binascii.Error):
        src = raw
    spec = first(script, "LanguageSpec")
    lang = f"{text(spec, 'Taxon')} {text(spec, 'Version')}" if spec is not None else None
    return lang, src


def imports(src):
    found = set()
    for line in src.splitlines():
        t = line.strip()
        if t.startswith("# r:"):
            found.update("pip:" + x.strip() for x in t[4:].split(","))
        elif t.startswith("import ") or t.startswith("from "):
            found.add(t.split()[1].split(".")[0].rstrip(","))
        elif t.startswith("using ") and t.endswith(";"):
            found.add(t[6:-1].split(".")[0])
    return sorted(found)


def libraries(definition):
    libs = []
    block = first(definition, "GHALibraries")
    if block is None:
        return libs
    for lib in sub(block, "Library"):
        rec = {k: text(lib, k) for k in ("Name", "Author", "Version", "Id", "AssemblyFullName")}
        if not rec["Name"] and rec["AssemblyFullName"]:
            rec["Name"] = rec["AssemblyFullName"].split(",")[0]
        if rec not in libs:
            libs.append(rec)
    return libs


def inspect(path: Path) -> dict:
    root = ET.parse(path).getroot()
    definition = first(root, "Definition")
    props = first(definition, "DefinitionProperties")
    objects_chunk = first(definition, "DefinitionObjects")
    objs, groups, scribbles, panels, sliders, scripts, clusters = [], [], [], [], [], [], []
    param_owner = {}
    for obj in sub(objects_chunk, "Object"):
        type_guid, type_name = text(obj, "GUID"), text(obj, "Name")
        c = first(obj, "Container")
        if c is None:
            continue
        rec = {
            "type_guid": type_guid,
            "type": type_name,
            "guid": text(c, "InstanceGuid"),
            "nickname": text(c, "NickName"),
            "description": text(c, "Description"),
            "pivot": pivot(c),
            "inputs": [param_record(p) for p in sub(c, "param_input") + script_params(c, "InputParam")],
            "outputs": [param_record(p) for p in sub(c, "param_output") + script_params(c, "OutputParam")],
        }
        if not rec["inputs"] and not rec["outputs"]:  # floating parameter object
            rec["sources"] = [s.text for s in items(c).get("Source", [])]
        param_owner[rec["guid"]] = rec["guid"]
        for p in rec["inputs"] + rec["outputs"]:
            param_owner[p["guid"]] = rec["guid"]
        tl = (type_name or "").lower()
        if type_name == "Group":
            groups.append({"guid": rec["guid"], "nickname": rec["nickname"],
                           "members": [i.text for i in items(c).get("ID", [])],
                           "colour": "".join(items(c)["Colour"][0].itertext()).strip() if items(c).get("Colour") else None})
            continue
        if type_name == "Scribble":
            scribbles.append({"text": text(c, "Text"), "pivot": rec["pivot"]})
        elif type_name == "Panel":
            panels.append({"nickname": rec["nickname"], "text": text(c, "UserText"),
                           "sources": rec.get("sources", []), "pivot": rec["pivot"]})
        elif "slider" in tl:
            s = first(c, "Slider")
            sliders.append({"nickname": rec["nickname"], "guid": rec["guid"],
                            **({k: text(s, k) for k in ("Value", "Min", "Max", "Digits", "Interval")} if s is not None else {})})
        lang, code = script_source(c)
        if code or any(h in tl for h in SCRIPT_HINTS):
            scripts.append({"type": type_name, "nickname": rec["nickname"], "language": lang,
                            "code_lines": len(code.splitlines()), "imports": imports(code)})
        if "cluster" in tl:
            clusters.append({"nickname": rec["nickname"], "guid": rec["guid"]})
        objs.append(rec)

    # wiring graph between objects
    edges = set()
    for rec in objs:
        srcs = [s for p in rec["inputs"] for s in p["sources"]] + rec.get("sources", [])
        for s in srcs:
            owner = param_owner.get(s)
            if owner and owner != rec["guid"]:
                edges.add((owner, rec["guid"]))
    preds, succs = defaultdict(set), defaultdict(set)
    for a, b in edges:
        succs[a].add(b)
        preds[b].add(a)
    depth = {}

    def dep(g, seen=()):
        if g in depth:
            return depth[g]
        if g in seen:
            return 0
        d = 0 if not preds[g] else 1 + max(dep(p, seen + (g,)) for p in preds[g])
        depth[g] = d
        return d

    for rec in objs:
        rec["depth"] = dep(rec["guid"])
    by_guid = {r["guid"]: r for r in objs}
    in_groups = {m for g in groups for m in g["members"]}
    type_counts = defaultdict(int)
    for r in objs:
        type_counts[r["type"]] += 1
    entry = [r for r in objs if not preds[r["guid"]] and (r["type"] in INPUT_KINDS or not r["inputs"])]
    terminal = [r for r in objs if not succs[r["guid"]] and (r["inputs"] or r.get("sources"))]
    return {
        "file": path.name,
        "name": text(props, "Name") if props is not None else None,
        "description": text(props, "Description") if props is not None else None,
        "plugin_version": ".".join(t.text for t in items(definition)["plugin_version"][0]) if items(definition).get("plugin_version") else None,
        "libraries": libraries(definition),
        "counts": {"objects": len(objs), "wires": len(edges), "groups": len(groups),
                   "scribbles": len(scribbles), "panels": len(panels), "sliders": len(sliders),
                   "scripts": len(scripts), "clusters": len(clusters),
                   "ungrouped_objects": sum(1 for r in objs if r["guid"] not in in_groups),
                   "max_depth": max((r["depth"] for r in objs), default=0)},
        "component_types": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
        "inputs": [{"type": r["type"], "nickname": r["nickname"]} for r in entry],
        "sliders": sliders,
        "terminals": [{"type": r["type"], "nickname": r["nickname"], "depth": r["depth"]} for r in terminal],
        "groups": [{"nickname": g["nickname"], "size": len(g["members"])} for g in groups],
        "scribbles": scribbles,
        "panels": [p for p in panels if p["text"]],
        "scripts": scripts,
        "clusters": clusters,
        "objects": [{k: r[k] for k in ("type", "nickname", "guid", "pivot", "depth")} for r in objs],
        "edges": sorted(edges),
    }


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    files = sorted(src.rglob("*.ghx")) if src.is_dir() else [src]
    report = []
    for f in files:
        try:
            r = inspect(f)
            r["path"] = str(f.relative_to(src)) if src.is_dir() else f.name
            report.append(r)
        except Exception as exc:  # malformed archive: record and continue
            report.append({"path": str(f), "error": repr(exc)})
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    for r in report:
        if "error" in r:
            print(f"ERR {r['path']}: {r['error']}")
        else:
            c = r["counts"]
            libs = ",".join(l["Name"] or "?" for l in r["libraries"]) or "-"
            print(f"{r['path']}: {c['objects']} obj, {c['wires']} wires, depth {c['max_depth']}, "
                  f"groups {c['groups']}, scribbles {c['scribbles']}, scripts {c['scripts']}, plugins {libs}")


if __name__ == "__main__":
    main()
