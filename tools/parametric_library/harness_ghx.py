"""Derive a runnable Almond capsule from an annotated teaching definition.

A capsule is a Grasshopper file plus a typed contract: floating params with
reserved nicknames (``ALMOND_IN_*`` / ``ALMOND_OUT_*``) that the bridge's
GhDefinitionRunner binds by exact name (see capsules/AUTHORING.md). This tool
adds that harness at XML level, driven by the lesson's ``harness`` block, so
nothing is opened in Grasshopper and the result is reproducible:

  * one input param per declared port, carrying the replaced slider's saved
    value (or the replaced geometry param's internalised sample) as its
    persistent data, so the file still solves on open;
  * every wire that left the replaced object is moved to the new param;
  * one output param per declared port, sourced from the named outputs;
  * a group, title and explanation panel around the harness.

The replaced sliders and params stay on the canvas, disconnected. That keeps
the derivation checkable: dropping the harness objects and mapping each harness
param back to the object it replaces gives exactly the teaching file's logic
fingerprint (``logic_fingerprint.fingerprint(path, drop=..., substitutions=...)``).

Usage:  python harness_ghx.py <teaching.ghx> <lesson.json> <out.harnessed.ghx> [--manifest <out.capsule.json>]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from annotate_ghx import Obj, _chunk, _item, _new_object, _recount, make_group, make_panel, make_scribble  # noqa: E402
from ghx_inspect import first, items, text  # noqa: E402

# Floating parameter types, as saved by Grasshopper 8 (GUIDs read from real files).
PARAM_TYPES = {
    "number": ("3e8ca6be-fda8-4aaf-b5c0-3c54c8bb7312", "Number", "number", "gh_double", 6),
    "integer": ("2e3ab970-8545-46bb-836c-1c11e5610bce", "Integer", "integer", "gh_int32", 3),
    "curve": ("d5967b9f-e8ee-436b-a8ad-29fdcecf32d5", "Curve", None, None, None),
    "brep": ("919e146f-30ae-4aae-be34-4d72f555e7da", "Brep", None, None, None),
    "point": ("fbac3e32-f100-4292-8692-77240a42fd1a", "Point", None, None, None),
}
GEOMETRY_TYPES = {"curve", "brep", "point"}
HARNESS_COLOUR = "150;255;170;170"
COLUMN_WIDTH, ROW, GAP = 460.0, 34.0, 90.0


class HarnessError(ValueError):
    pass


def _base_type(port_type: str) -> str:
    base = port_type.replace("[]", "")
    if base not in PARAM_TYPES:
        raise HarnessError(f"unsupported port type {port_type!r}; supported: {sorted(PARAM_TYPES)}")
    return base


def _resolve(prefix: str, candidates: dict, what: str) -> str:
    if prefix in candidates:
        return prefix
    hits = [g for g in candidates if g.startswith(prefix)]
    if len(hits) != 1:
        raise HarnessError(f"{what} prefix {prefix!r} matches {len(hits)} objects")
    return hits[0]


def _persistent_number(container, type_key: str, value) -> None:
    _, _, item_name, type_name, type_code = PARAM_TYPES[type_key]
    pd = _chunk(container, "PersistentData")
    _item(pd.find("items"), "Count", "gh_int32", 3, 1)
    branch = _chunk(pd, "Branch", index=0)
    _item(branch.find("items"), "Count", "gh_int32", 3, 1)
    _item(branch.find("items"), "Path", "gh_string", 10, "{0}")
    leaf = _chunk(branch, "Item", index=0)
    _item(leaf.find("items"), item_name, type_name, type_code, value)
    for ch in (leaf, branch, pd):
        _recount(ch)


def _slider_value(obj: Obj):
    slider = first(obj.container, "Slider")
    if slider is None:
        return None
    value = float(text(slider, "Value"))
    return int(value) if value.is_integer() else value


def _make_param(guid: str, type_key: str, nickname: str, description: str, x: float, y: float,
                sources=(), hidden=False):
    type_guid, type_name, *_ = PARAM_TYPES[type_key]
    obj, container = _new_object(type_guid, type_name)
    its = container.find("items")
    _item(its, "Description", "gh_string", 10, description)
    if hidden:
        _item(its, "Hidden", "gh_bool", 1, "true")
    _item(its, "InstanceGuid", "gh_guid", 9, guid)
    _item(its, "Name", "gh_string", 10, type_name)
    _item(its, "NickName", "gh_string", 10, nickname)
    _item(its, "Optional", "gh_bool", 1, "true")
    for i, source in enumerate(sources):
        _item(its, "Source", "gh_guid", 9, source, index=i)
    _item(its, "SourceCount", "gh_int32", 3, len(sources))
    attrs = _chunk(container, "Attributes")
    width = max(120.0, len(nickname) * 7.0 + 24.0)
    _item(attrs.find("items"), "Bounds", "gh_drawing_rectanglef", 35,
          {"X": round(x, 3), "Y": round(y, 3), "W": round(width, 3), "H": 20})
    _item(attrs.find("items"), "Pivot", "gh_drawing_pointf", 31, {"X": round(x + width / 2, 3), "Y": round(y + 10, 3)})
    _recount(attrs)
    return obj, container


def harness(src: Path, lesson: dict, out: Path) -> dict:
    """Write the harnessed definition and return the derivation log."""
    spec = lesson["harness"]
    tree = ET.parse(src)
    root = tree.getroot()
    definition = first(root, "Definition")
    dobj = first(definition, "DefinitionObjects")
    block = dobj.find("chunks")
    objs = [Obj(el) for el in block.findall("chunk") if el.get("name") == "Object" and first(el, "Container") is not None]
    by_guid = {o.guid: o for o in objs}
    output_params = {}  # wire-source guid -> (owner object, output name)
    for o in objs:
        for p in o.outputs:
            output_params[text(p, "InstanceGuid")] = (o, text(p, "Name"))
        if not o.inputs and not o.outputs:  # floating param: its own guid is the wire source
            output_params[o.guid] = (o, o.nickname)

    ns = uuid.uuid5(uuid.NAMESPACE_URL, "almond-parametric/" + lesson["id"])
    gid = lambda key: str(uuid.uuid5(ns, "harness/" + key))  # noqa: E731

    bounds = [o.bounds() for o in objs if o.bounds()]
    left = min(b[0] for b in bounds) if bounds else 0.0
    top = min(b[1] for b in bounds) if bounds else 0.0
    x = left - COLUMN_WIDTH - GAP
    new_objects, harness_guids, substitutions, rewired = [], [], {}, {}
    ports_in, ports_out, defaults, replaced = [], [], {}, []

    title_obj, tb = make_scribble(gid("title"), "ALMOND HARNESS", x, top - 20, size=28)
    new_objects.append(title_obj)
    harness_guids.append(gid("title"))
    y = tb[1] + tb[3] + 16

    # ---- inputs
    inputs_label, lb = make_scribble(gid("inputs-label"), "INPUTS  (ALMOND_IN_*)", x, y, size=18)
    new_objects.append(inputs_label)
    harness_guids.append(gid("inputs-label"))
    y = lb[1] + lb[3] + 10
    seen_names = set()
    for port in spec["inputs"]:
        name = port["name"]
        if not name.startswith("ALMOND_IN_") or name in seen_names:
            raise HarnessError(f"bad or duplicate input port name {name!r}")
        seen_names.add(name)
        type_key = _base_type(port["type"])
        target_guid = _resolve(port["replaces"], by_guid, "replaces")
        target = by_guid[target_guid]
        guid = gid("in/" + name)
        obj, container = _make_param(guid, type_key, name, f"Almond harness input: {port.get('description', '')}".strip(),
                                     x, y, hidden=type_key in GEOMETRY_TYPES)
        default = None
        if type_key in GEOMETRY_TYPES:
            if port.get("default") == "sample":
                sample = first(target.container, "PersistentData")
                if sample is None:
                    raise HarnessError(f"{name}: {target.nickname!r} has no internalised sample to copy")
                container.find("chunks").append(copy.deepcopy(sample))
                defaults[name] = {"sample_copied_from": target_guid}
        else:
            default = port.get("default", _slider_value(target))
            if default is None:
                raise HarnessError(f"{name}: no default given and {target.nickname!r} is not a slider")
            _persistent_number(container, type_key, default)
            defaults[name] = default
        _recount(container)
        _recount(obj)
        # move every wire that left the replaced object onto the harness param
        count = 0
        for item in dobj.iter("item"):
            if item.get("name") == "Source" and item.text == target_guid:
                item.text = guid
                count += 1
        if count == 0:
            raise HarnessError(f"{name}: nothing consumes {target.nickname!r} ({target_guid})")
        substitutions[guid] = target_guid
        rewired[name] = count
        replaced.append({"port": name, "object": target_guid, "type": target.type, "nickname": target.nickname})
        new_objects.append(obj)
        harness_guids.append(guid)
        manifest_port = {"name": name, "type": port["type"], "units": port.get("units", "document"),
                         "required": bool(port.get("required", False)), "description": port.get("description", "")}
        if default is not None:
            manifest_port["default"] = default
        ports_in.append(manifest_port)
        y += ROW

    # ---- outputs
    y += 20
    outputs_label, lb = make_scribble(gid("outputs-label"), "OUTPUTS  (ALMOND_OUT_*)", x, y, size=18)
    new_objects.append(outputs_label)
    harness_guids.append(gid("outputs-label"))
    y = lb[1] + lb[3] + 10
    for port in spec["outputs"]:
        name = port["name"]
        if not name.startswith("ALMOND_OUT_") or name in seen_names:
            raise HarnessError(f"bad or duplicate output port name {name!r}")
        seen_names.add(name)
        type_key = _base_type(port["type"])
        sources = [_resolve(p, output_params, "from") for p in port["from"]]
        guid = gid("out/" + name)
        obj, container = _make_param(guid, type_key, name, f"Almond harness output: {port.get('description', '')}".strip(),
                                     x, y, sources=sources, hidden=True)
        _recount(container)
        _recount(obj)
        new_objects.append(obj)
        harness_guids.append(guid)
        ports_out.append({"name": name, "type": port["type"], "units": port.get("units", "document"),
                          "semantics": port.get("semantics", ""), "description": port.get("description", ""),
                          "sources": [f"{output_params[s][0].type}.{output_params[s][1]} ({s[:8]})" for s in sources]})
        y += ROW

    # ---- explanation panel and group
    note = "\n".join([
        "ALMOND HARNESS - machine sockets for run_gh_definition",
        "",
        "Almond binds these params by their exact nicknames. The green INPUTS sliders and the",
        "sample geometry to the right are DISCONNECTED in this copy: each one is replaced by the",
        "ALMOND_IN_* param of the same value, which is what Almond writes to.",
        "",
        *[f"{r['port']}  <-  {r['type']} '{r['nickname']}'" for r in replaced],
        "",
        "Outputs collect the results Almond bakes:",
        *[f"{p['name']}  <-  {', '.join(p['sources'])}" for p in ports_out],
        "",
        "The logic is the teaching file's, unchanged. To learn the definition, open",
        f"definitions/{lesson['id']}.ghx instead.",
    ])
    panel_obj, _ = make_panel(gid("note"), "ALMOND HARNESS", note, x, y + 10, width=COLUMN_WIDTH)
    new_objects.append(panel_obj)
    harness_guids.append(gid("note"))
    new_objects.append(make_group(gid("group"), "ALMOND HARNESS", HARNESS_COLOUR, list(harness_guids)))
    harness_guids.append(gid("group"))

    for el in new_objects:
        block.append(el)
    for i, el in enumerate(c for c in block.findall("chunk") if c.get("name") == "Object"):
        el.set("index", str(i))
    _recount(dobj)
    oc = items(dobj).get("ObjectCount")
    if oc:
        oc[0].text = str(len(block.findall("chunk")))
    props = first(definition, "DefinitionProperties")
    if props is not None and items(props).get("Name"):
        items(props)["Name"][0].text = out.name

    ET.indent(tree, space="  ")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n')
        tree.write(fh, encoding="utf-8", xml_declaration=False)
    return {"objects": harness_guids, "substitutions": substitutions, "rewired_sources": rewired,
            "replaced": replaced, "defaults": defaults, "inputs": ports_in, "outputs": ports_out}


def manifest_for(lesson: dict, log: dict, definition_file: str) -> dict:
    """The capsule sidecar, generated from the lesson's harness block and the derivation log."""
    spec = lesson["harness"]
    src = lesson["source"]
    audited = bool(spec.get("audited", False))
    outputs = [{k: v for k, v in p.items() if k != "sources"} for p in log["outputs"]]
    description = spec["description_for_llm"].strip() + (
        f" Derived from the Almond parametric teaching definition '{lesson['id']}' "
        f"({src['author']}, {src['repo']} @ {src['commit'][:10]}, {src['licence']}); the geometric logic is "
        "unchanged, only the harness params were added (see ParametricLibrary/source-register.json)."
    )
    return {
        "capsule_id": spec["capsule_id"],
        "version": int(spec.get("version", 1)),
        "capability": spec.get("capability", "generate"),
        "structure_type": spec.get("structure_type", ""),
        "plugin_dependencies": [],
        "definition_file": definition_file,
        "title": lesson["title"],
        "description_for_llm": description,
        "inputs": log["inputs"],
        "outputs": outputs,
        "binding": "reserved_nicknames",
        "audited": audited,
        "audit": {"status": "verified by a live run" if audited else "not run live yet; run_gh_definition refuses it",
                  "note": spec.get("audit_note", "")},
        "source": {"parametric_definition": lesson["id"], "teaching_definition": f"definitions/{lesson['id']}.ghx",
                   "author": src["author"], "repo": src["repo"], "path": src["path"], "commit": src["commit"],
                   "licence": src["licence"], "licence_url": src["licence_url"]},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("lesson", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--manifest", type=Path)
    a = ap.parse_args()
    lesson = json.loads(a.lesson.read_text(encoding="utf-8"))
    log = harness(a.src, lesson, a.out)
    if a.manifest:
        a.manifest.write_text(json.dumps(manifest_for(lesson, log, a.out.name), indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    print(json.dumps(log, indent=1))


if __name__ == "__main__":
    main()
