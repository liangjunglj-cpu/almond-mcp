"""Fingerprint a .ghx definition's logic, ignoring layout, nicknames and notes.

Two definitions with equal fingerprints have the same components, wires,
internalised data, slider settings and script source. Usage:
    python logic_fingerprint.py <a.ghx> <b.ghx>   -> exit 0 when equal
"""
import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghx_inspect import first, sub, text  # noqa: E402

IGNORED_ITEMS = {"Bounds", "Pivot", "NickName", "Ca", "Cb", "Cc", "Cd", "MarginLeft", "MarginRight", "MarginTop"}
NOTE_TYPES = {"Group", "Scribble"}


def canon(el):
    """Canonical string of an element, dropping layout and nickname items."""
    if el.tag == "item" and el.get("name") in IGNORED_ITEMS:
        return ""
    kids = [canon(c) for c in el if not (c.tag == "item" and c.get("name") in IGNORED_ITEMS)]
    attrs = {k: v for k, v in el.attrib.items() if k not in ("count", "index")}
    return f"<{el.tag} {sorted(attrs.items())}>{(el.text or '').strip()}{''.join(kids)}</{el.tag}>"


def apply_overrides(objs, overrides):
    """Set container items, e.g. {"<guid>": {"ToggleValue": "false"}}; returns the guids touched."""
    touched = set()
    for obj in sub(objs, "Object"):
        c = first(obj, "Container")
        guid = text(c, "InstanceGuid") if c is not None else None
        for name, value in (overrides or {}).get(guid, {}).items():
            if name == "reason":
                continue
            hits = [i for i in c.find("items").findall("item") if i.get("name") == name]
            if not hits:
                raise KeyError(f"override {name!r} not found on {guid}")
            hits[0].text = str(value)
            touched.add(guid)
    return touched


def fingerprint(path, overrides=None, drop=(), substitutions=None):
    """Hash every logic object. ``overrides`` are applied first (lesson-declared safe defaults).

    ``drop`` removes objects (by instance guid) before hashing and ``substitutions``
    maps wire sources {harness_guid: original_guid}. Together they undo a capsule
    harness, so a harnessed file can be checked against the teaching file it came from.
    """
    root = ET.parse(path).getroot()
    objs = first(first(root, "Definition"), "DefinitionObjects")
    apply_overrides(objs, overrides)
    if drop:
        block = objs.find("chunks")
        for obj in sub(objs, "Object"):
            c = first(obj, "Container")
            if c is not None and text(c, "InstanceGuid") in set(drop):
                block.remove(obj)
    for item in objs.iter("item"):
        if item.get("name") == "Source" and item.text in (substitutions or {}):
            item.text = substitutions[item.text]
    referenced = {i.text for i in objs.iter("item") if i.get("name") == "Source"}
    out = {}
    for obj in sub(objs, "Object"):
        kind = text(obj, "Name")
        c = first(obj, "Container")
        if kind in NOTE_TYPES or c is None:
            continue
        guid = text(c, "InstanceGuid")
        if kind == "Panel" and guid not in referenced and not [i for i in c.iter("item") if i.get("name") == "Source"]:
            continue  # panels that neither receive nor feed data are notes
        out[guid] = hashlib.sha256(canon(obj).encode()).hexdigest()
    return out


if __name__ == "__main__":
    a, b = fingerprint(sys.argv[1]), fingerprint(sys.argv[2])
    missing, added = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    changed = sorted(g for g in set(a) & set(b) if a[g] != b[g])
    print(f"objects {len(a)} vs {len(b)}; missing {missing}; added {added}; changed {changed}")
    sys.exit(0 if not (missing or added or changed) else 1)
