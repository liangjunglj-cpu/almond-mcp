"""Turn an upstream Grasshopper .ghx into an annotated teaching definition.

The definition's logic is never changed: no component, wire, value or script is
edited or removed, except values a lesson declares in ``overrides`` (safe
defaults such as a script toggle saved as on, recorded in the source register).
The annotator only
  * moves objects into left-to-right stage blocks (inputs -> steps -> outputs),
  * renames nicknames the lesson explicitly relabels (sliders, params),
  * adds coloured groups, title scribbles, explanation panels, a README panel
    and a licence panel,
  * drops original groups whose members end up split across stages.

Usage:  python annotate_ghx.py <upstream.ghx> <lesson.json> <out.ghx> [--licence <file>]
"""
from __future__ import annotations

import argparse
import json
import math
import textwrap
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ghx_inspect import INPUT_KINDS, first, items, script_params, sub, text  # noqa: E402
from logic_fingerprint import apply_overrides  # noqa: E402

GROUP_TYPE = "c552a431-af5b-46a9-a8a4-0fcbc27ef596"
SCRIBBLE_TYPE = "7f5c6c55-f846-4a08-9c9a-cfdc285cc6fe"
PANEL_TYPE = "59e0b89a-e487-49f8-bab8-b5bab16be14c"
NOTE_TYPES = {"Scribble", "Group"}
LAYOUT_CHUNKS = {"Attributes", "param_input", "param_output", "ParameterData", "InputParam", "OutputParam"}
POINT_ITEMS = {"Pivot", "Ca", "Cb", "Cc", "Cd"}

PALETTE = {  # ARGB, translucent group fills
    "readme": "150;235;235;235",
    "inputs": "150;140;210;140",
    "outputs": "150;130;180;255",
    "steps": ["150;255;215;130", "150;250;185;150", "150;235;200;235", "150;200;225;175", "150;255;235;160"],
}
STAGE_GAP, TITLE_SPACE, PACK_GAP = 90.0, 140.0, 12.0
# Measured on a live Grasshopper 8 canvas (Segoe UI 8 pt, 150 % display): ~6.8 px per character and 21.3 px
# per line in canvas units. Smaller on 100 % displays, where panels simply keep some spare room.
CHAR_W, LINE_H = 7.0, 21.5


# ---------------------------------------------------------------- xml helpers
def _item(parent_items, name, type_name, type_code, value=None, index=None):
    el = ET.SubElement(parent_items, "item", {"name": name})
    if index is not None:
        el.set("index", str(index))
    el.set("type_name", type_name)
    el.set("type_code", str(type_code))
    if isinstance(value, dict):
        for k, v in value.items():
            ET.SubElement(el, k).text = str(v)
    elif value is not None:
        el.text = str(value)
    return el


def _recount(chunk):
    for tag, child in (("items", "item"), ("chunks", "chunk")):
        block = chunk.find(tag)
        if block is not None:
            block.set("count", str(len(block.findall(child))))


def _chunk(parent, name, index=None):
    block = parent.find("chunks")
    if block is None:
        block = ET.SubElement(parent, "chunks")
    c = ET.SubElement(block, "chunk", {"name": name})
    if index is not None:
        c.set("index", str(index))
    ET.SubElement(c, "items")
    return c


def _new_object(type_guid, type_name):
    obj = ET.Element("chunk", {"name": "Object"})
    its = ET.SubElement(obj, "items")
    _item(its, "GUID", "gh_guid", 9, type_guid)
    _item(its, "Name", "gh_string", 10, type_name)
    container = _chunk(obj, "Container")
    return obj, container


def _rect(x, y, w, h):
    return {"X": round(x, 3), "Y": round(y, 3), "W": round(w, 3), "H": round(h, 3)}


def make_group(guid, nickname, colour, members):
    obj, c = _new_object(GROUP_TYPE, "Group")
    its = c.find("items")
    _item(its, "Border", "gh_int32", 3, 1)
    col = _item(its, "Colour", "gh_drawing_color", 36)
    ET.SubElement(col, "ARGB").text = colour
    _item(its, "Description", "gh_string", 10, "A group of Grasshopper objects")
    for i, m in enumerate(members):
        _item(its, "ID", "gh_guid", 9, m, index=i)
    _item(its, "ID_Count", "gh_int32", 3, len(members))
    _item(its, "InstanceGuid", "gh_guid", 9, guid)
    _item(its, "Name", "gh_string", 10, "Group")
    _item(its, "NickName", "gh_string", 10, nickname)
    _chunk(c, "Attributes")
    for ch in (c, obj):
        _recount(ch)
    return obj


def make_scribble(guid, text_value, x, y, size=22.0):
    w, h = max(40.0, len(text_value) * size * 0.55), size * 1.35
    obj, c = _new_object(SCRIBBLE_TYPE, "Scribble")
    its = c.find("items")
    _item(its, "Bold", "gh_bool", 1, "true")
    for name, (px, py) in zip(("Ca", "Cb", "Cc", "Cd"), ((x, y), (x + w, y), (x + w, y + h), (x, y + h))):
        _item(its, name, "gh_drawing_pointf", 31, {"X": round(px, 3), "Y": round(py, 3)})
    _item(its, "Description", "gh_string", 10, "A quick note")
    _item(its, "Font", "gh_string", 10, "Microsoft Sans Serif")
    _item(its, "InstanceGuid", "gh_guid", 9, guid)
    _item(its, "Italic", "gh_bool", 1, "false")
    _item(its, "Name", "gh_string", 10, "Scribble")
    _item(its, "NickName", "gh_string", 10, "Scribble")
    _item(its, "Size", "gh_single", 5, size)
    _item(its, "Text", "gh_string", 10, text_value)
    attrs = _chunk(c, "Attributes")
    a = attrs.find("items")
    _item(a, "Bounds", "gh_drawing_rectanglef", 35, _rect(x - 5, y - 5, w + 10, h + 10))
    _item(a, "Pivot", "gh_drawing_pointf", 31, {"X": round(x, 3), "Y": round(y, 3)})
    for ch in (attrs, c, obj):
        _recount(ch)
    return obj, (x - 5, y - 5, w + 10, h + 10)


def panel_size(body, width):
    cols = max(20, int((width - 12) / CHAR_W))
    lines = sum(len(textwrap.wrap(line, cols)) or 1 for line in body.splitlines()) or 1
    return width, lines * LINE_H + 16 + 22  # + the panel's nickname header strip


def make_panel(guid, nickname, body, x, y, width=380.0, colour="255;255;250;235", max_height=None):
    w, h = panel_size(body, width)
    if max_height:
        h = min(h, max_height)  # Grasshopper panels scroll when the text is longer
    obj, c = _new_object(PANEL_TYPE, "Panel")
    its = c.find("items")
    _item(its, "Description", "gh_string", 10, "A panel for custom notes and text values")
    _item(its, "InstanceGuid", "gh_guid", 9, guid)
    _item(its, "Name", "gh_string", 10, "Panel")
    _item(its, "NickName", "gh_string", 10, nickname)
    _item(its, "Optional", "gh_bool", 1, "false")
    _item(its, "ScrollRatio", "gh_double", 6, 0)
    _item(its, "SourceCount", "gh_int32", 3, 0)
    _item(its, "UserText", "gh_string", 10, body)
    attrs = _chunk(c, "Attributes")
    a = attrs.find("items")
    _item(a, "Bounds", "gh_drawing_rectanglef", 35, _rect(x, y, w, h))
    for m in ("MarginLeft", "MarginRight", "MarginTop"):
        _item(a, m, "gh_int32", 3, 0)
    _item(a, "Pivot", "gh_drawing_pointf", 31, {"X": round(x, 3), "Y": round(y, 3)})
    props = _chunk(c, "PanelProperties")
    p = props.find("items")
    _item(p, "Alignment", "gh_int32", 3, 1)  # GH_Panel.Alignment.Left (0 = default, centred)
    col = _item(p, "Colour", "gh_drawing_color", 36)
    ET.SubElement(col, "ARGB").text = colour
    for name, val in (("DrawIndices", "false"), ("DrawPaths", "false"), ("Multiline", "true"),
                      ("SpecialCodes", "false"), ("Stream", "false"), ("Wrap", "true")):
        _item(p, name, "gh_bool", 1, val)
    font = _chunk(props, "Font")
    f = font.find("items")
    _item(f, "Family", "gh_string", 10, "Segoe UI")
    _item(f, "Size", "gh_single", 5, 8)
    for ch in (font, props, attrs, c, obj):
        _recount(ch)
    return obj, (x, y, w, h)


# ------------------------------------------------------------ object records
class Obj:
    def __init__(self, el):
        self.el = el
        self.type = text(el, "Name")
        self.container = first(el, "Container")
        self.guid = text(self.container, "InstanceGuid")
        self.nickname = text(self.container, "NickName")
        self.inputs = sub(self.container, "param_input") + script_params(self.container, "InputParam")
        self.outputs = sub(self.container, "param_output") + script_params(self.container, "OutputParam")
        self.preds, self.succs = set(), set()
        self.depth = 0

    @property
    def is_group(self):
        return self.type == "Group"

    def bounds(self):
        its = items(self.container)
        if all(k in its for k in ("Ca", "Cc")):
            (a,), (c,) = its["Ca"], its["Cc"]
            ax, ay, cx, cy = (float(e.find(t).text) for e, t in ((a, "X"), (a, "Y"), (c, "X"), (c, "Y")))
            return ax, ay, cx - ax, cy - ay
        attrs = first(self.container, "Attributes")
        b = items(attrs).get("Bounds") if attrs is not None else None
        if b:
            return tuple(float(b[0].find(t).text) for t in ("X", "Y", "W", "H"))
        p = items(attrs).get("Pivot") if attrs is not None else None
        if p:
            return float(p[0].find("X").text), float(p[0].find("Y").text), 50.0, 20.0
        return None

    def translate(self, dx, dy):
        def walk(chunk, top):
            its_block = chunk.find("items")
            for it in (list(its_block) if its_block is not None else []):
                if it.get("name") == "Bounds" or it.get("name") in POINT_ITEMS:
                    x, y = it.find("X"), it.find("Y")
                    if x is not None and y is not None:
                        x.text = repr(round(float(x.text) + dx, 4))
                        y.text = repr(round(float(y.text) + dy, 4))
            ch_block = chunk.find("chunks")
            for ch in (list(ch_block) if ch_block is not None else []):
                if ch.get("name") in LAYOUT_CHUNKS:
                    walk(ch, False)
        walk(self.container, True)

    def set_nickname(self, value):
        its = items(self.container)
        if "NickName" in its:
            its["NickName"][0].text = value
        else:
            _item(self.container.find("items"), "NickName", "gh_string", 10, value)
            _recount(self.container)
        self.nickname = value


def build_graph(objs):
    owner = {}
    for o in objs:
        owner[o.guid] = o
        for p in o.inputs + o.outputs:
            owner[text(p, "InstanceGuid")] = o
    for o in objs:
        sources = [s.text for p in o.inputs for s in items(p).get("Source", [])]
        sources += [s.text for s in items(o.container).get("Source", [])]
        for s in sources:
            src = owner.get(s)
            if src is not None and src is not o:
                o.preds.add(src)
                src.succs.add(o)
    memo = {}

    def depth(o, stack=()):
        if o.guid in memo:
            return memo[o.guid]
        if o in stack:
            return 0
        memo[o.guid] = 0 if not o.preds else 1 + max(depth(p, stack + (o,)) for p in o.preds)
        return memo[o.guid]

    for o in objs:
        o.depth = depth(o)


def is_note(o):
    return o.type in NOTE_TYPES or (o.type == "Panel" and not o.preds and not o.succs)


def is_input(o):
    return not o.preds and o.succs and (o.type in INPUT_KINDS or not o.inputs)


def is_output(o):
    return not o.succs and o.preds and not is_note(o)


# ---------------------------------------------------------------- annotation
def assign_stages(objs, steps):
    stage_of = {}
    wired = [o for o in objs if not is_note(o) and not o.is_group]
    by_nick = defaultdict(list)
    for o in wired:
        by_nick[o.nickname].append(o)
    priority = ("guids", "nicknames", "types", "inputs", "outputs", "depth", "rest")
    for key in priority:
        for si, step in enumerate(steps):
            sel = step.get("select", {})
            if key not in sel:
                continue
            for o in wired:
                if o.guid in stage_of:
                    continue
                hit = ((key == "guids" and o.guid in sel["guids"])
                       or (key == "nicknames" and o.nickname in sel["nicknames"])
                       or (key == "types" and o.type in sel["types"])
                       or (key == "inputs" and is_input(o))
                       or (key == "outputs" and is_output(o))
                       or (key == "depth" and sel["depth"][0] <= o.depth <= sel["depth"][1])
                       or (key == "rest"))
                if hit:
                    stage_of[o.guid] = si
    for o in wired:  # leftovers go to the step whose depth range is closest
        if o.guid not in stage_of:
            ranges = [(si, s["select"]["depth"]) for si, s in enumerate(steps) if "depth" in s.get("select", {})]
            stage_of[o.guid] = min(ranges, key=lambda r: min(abs(o.depth - r[1][0]), abs(o.depth - r[1][1])))[0] if ranges else len(steps) - 1
    return stage_of


def resolve_prefixes(lesson, by_guid):
    """Lessons may name objects by a unique GUID prefix (>= 8 hex chars)."""
    def full(key):
        if key in by_guid or len(key) < 8:
            return key
        hits = [g for g in by_guid if g.startswith(key)]
        if len(hits) != 1:
            raise SystemExit(f"GUID prefix {key!r} matches {len(hits)} objects")
        return hits[0]
    lesson = json.loads(json.dumps(lesson))
    lesson["readme_extra"] = [full(g) for g in lesson.get("readme_extra", [])]
    lesson["drop_notes"] = [full(g) for g in lesson.get("drop_notes", [])]
    lesson["labels"] = {full(k): v for k, v in lesson.get("labels", {}).items()}
    lesson["overrides"] = {full(k): v for k, v in lesson.get("overrides", {}).items()}
    for step in lesson["steps"]:
        if "guids" in step.get("select", {}):
            step["select"]["guids"] = [full(g) for g in step["select"]["guids"]]
    return lesson


def centre(b):
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def annotate(src: Path, lesson: dict, out: Path, licence_text: str | None) -> dict:
    tree = ET.parse(src)
    root = tree.getroot()
    definition = first(root, "Definition")
    dobj = first(definition, "DefinitionObjects")
    block = dobj.find("chunks")
    objs = [Obj(el) for el in block.findall("chunk") if el.get("name") == "Object" and first(el, "Container") is not None]
    build_graph(objs)
    by_guid = {o.guid: o for o in objs}
    lesson = resolve_prefixes(lesson, by_guid)
    steps = lesson["steps"]
    stage_of = assign_stages(objs, steps)
    log = {"dropped_groups": [], "relabelled": [], "notes_moved": 0}

    # readme extras (e.g. the author's credit button) travel with the README block
    readme_members = [by_guid[g] for g in lesson.get("readme_extra", []) if g in by_guid]
    for o in readme_members:
        stage_of[o.guid] = -1

    # original notes follow the nearest wired object; drop list removes notes only
    drop = set(lesson.get("drop_notes", []))
    wired = [o for o in objs if o.guid in stage_of and stage_of[o.guid] >= 0]
    for o in objs:
        if o.guid in stage_of or o.is_group:
            continue
        if o.guid in drop and is_note(o):
            block.remove(o.el)
            continue
        b = o.bounds()
        if b is None or not wired:
            stage_of[o.guid] = 0
            continue
        cx, cy = centre(b)
        near = min(wired, key=lambda w: (lambda wb: (centre(wb)[0] - cx) ** 2 + (centre(wb)[1] - cy) ** 2)(w.bounds() or (0, 0, 0, 0)))
        stage_of[o.guid] = stage_of[near.guid]
        log["notes_moved"] += 1

    # keep original groups only when all members share one stage
    for g in [o for o in objs if o.is_group]:
        members = [i.text for i in items(g.container).get("ID", [])]
        stages = {stage_of.get(m) for m in members if m in by_guid}
        if len(stages) > 1 or g.guid in drop:
            block.remove(g.el)
            log["dropped_groups"].append(g.nickname)
        elif stages:
            stage_of[g.guid] = stages.pop()

    # safe defaults declared by the lesson (e.g. a script toggle saved as on)
    apply_overrides(dobj, lesson["overrides"])
    log["overrides"] = lesson["overrides"]

    # relabel nicknames (by guid or by current nickname)
    for key, label in lesson.get("labels", {}).items():
        targets = [by_guid[key]] if key in by_guid else [o for o in objs if o.nickname == key and not o.is_group]
        for o in targets:
            log["relabelled"].append([o.type, o.nickname, label])
            o.set_nickname(label)

    # ---- layout: README column, then one block per stage
    ns = uuid.uuid5(uuid.NAMESPACE_URL, "almond-parametric/" + lesson["id"])
    gid = lambda key: str(uuid.uuid5(ns, key))  # noqa: E731
    new_objects = []
    placed = [o for o in objs if o.guid in stage_of and not o.is_group]
    all_b = [o.bounds() for o in placed if o.bounds()]
    top = min(b[1] for b in all_b) if all_b else 0.0
    left = min(b[0] for b in all_b) if all_b else 0.0
    cursor = left

    readme = readme_text(lesson)
    title_obj, tb = make_scribble(gid("title"), lesson["title"], cursor, top - 20, size=28)
    panel_obj, pb = make_panel(gid("readme"), "README", readme, cursor, top + 40, width=400)
    new_objects += [title_obj, panel_obj]
    col_bottom = pb[1] + pb[3]
    readme_guids = [gid("title"), gid("readme")]
    if licence_text:
        lic_obj, lb = make_panel(gid("licence"), "LICENCE", licence_text.strip(), cursor, col_bottom + 20,
                                 width=400, colour="255;245;245;245", max_height=170)
        new_objects.append(lic_obj)
        readme_guids.append(gid("licence"))
        col_bottom = lb[1] + lb[3]
    y = col_bottom + 20
    readme_right = max(cursor + 400, tb[0] + tb[2])
    for o in readme_members:
        b = o.bounds()
        if b:
            o.translate(cursor - b[0], y - b[1])
            y += b[3] + PACK_GAP
            readme_right = max(readme_right, cursor + b[2])
            readme_guids.append(o.guid)
    new_objects.append(make_group(gid("group-readme"), "README", PALETTE["readme"], readme_guids))
    cursor = readme_right + STAGE_GAP

    colours = iter(PALETTE["steps"] * 3)
    stage_record = []
    for si, step in enumerate(steps):
        members = [o for o in placed if stage_of.get(o.guid) == si]
        groups_in = [o for o in objs if o.is_group and stage_of.get(o.guid) == si and o.el in list(block)]
        if not members:
            continue
        kind = "inputs" if step.get("select", {}).get("inputs") else "outputs" if step.get("select", {}).get("outputs") else "step"
        colour = PALETTE["inputs"] if kind == "inputs" else PALETTE["outputs"] if kind == "outputs" else next(colours)
        layout = step.get("layout", "pack" if kind in ("inputs", "outputs") else "columns")
        body_top = top + TITLE_SPACE
        head_w = 300.0
        if layout == "pack":
            ordered = sorted(members, key=lambda o: ((o.bounds() or (0, 0))[1], (o.bounds() or (0, 0))[0]))
            yy, width = body_top, 0.0
            for o in ordered:
                b = o.bounds() or (0, 0, 50, 20)
                o.translate(cursor - b[0], yy - b[1])
                yy += b[3] + PACK_GAP
                width = max(width, b[2])
        elif layout == "columns":
            # one column per dependency depth, original top-to-bottom order kept; notes go underneath
            logic = [o for o in members if not is_note(o)]
            notes = [o for o in members if is_note(o)]
            columns = defaultdict(list)
            for o in logic:
                columns[o.depth].append(o)
            x, bottom = cursor, body_top
            for d in sorted(columns):
                col = sorted(columns[d], key=lambda o: (o.bounds() or (0, 0))[1])
                yy, col_w = body_top, 0.0
                for o in col:
                    b = o.bounds() or (0, 0, 50, 20)
                    o.translate(x - b[0], yy - b[1])
                    yy += b[3] + PACK_GAP * 2
                    col_w = max(col_w, b[2])
                bottom = max(bottom, yy)
                x += col_w + 40
            yy = bottom + 20
            for o in sorted(notes, key=lambda o: (o.bounds() or (0, 0))[1]):
                b = o.bounds() or (0, 0, 50, 20)
                o.translate(cursor - b[0], yy - b[1])
                yy += b[3] + PACK_GAP
                x = max(x, cursor + b[2] + 40)
            width = x - cursor - 40
        else:
            bs = [o.bounds() for o in members if o.bounds()]
            bx, by = min(b[0] for b in bs), min(b[1] for b in bs)
            width = max(b[0] + b[2] for b in bs) - bx
            for o in members:
                o.translate(cursor - bx, body_top - by)
        width = max(width, head_w, len(step["title"]) * 20 * 0.55 + 20)
        explain = step.get("explain", "")
        s_obj, _ = make_scribble(gid(f"step-{si}-title"), step["title"], cursor, top, size=20)
        p_obj, pb = make_panel(gid(f"step-{si}-explain"), f"STEP {si + 1}", explain, cursor, top + 34,
                               width=min(max(width, 300.0), 460.0)) if explain else (None, None)
        if pb and pb[1] + pb[3] + 10 > body_top:  # long explanation: push the block down
            shift = pb[1] + pb[3] + 16 - body_top
            for o in members:
                o.translate(0, shift)
        member_guids = [o.guid for o in members] + [g.guid for g in groups_in] + [gid(f"step-{si}-title")]
        new_objects.append(s_obj)
        if p_obj is not None:
            new_objects.append(p_obj)
            member_guids.append(gid(f"step-{si}-explain"))
        new_objects.append(make_group(gid(f"group-{si}"), step["title"], colour, member_guids))
        stage_record.append({"title": step["title"], "kind": kind, "objects": len(members),
                             "components": sorted({o.type for o in members if not is_note(o)})})
        cursor += width + STAGE_GAP

    for el in new_objects:
        block.append(el)
    for i, el in enumerate(c for c in block.findall("chunk") if c.get("name") == "Object"):
        el.set("index", str(i))
    _recount(dobj)
    oc = items(dobj).get("ObjectCount")
    if oc:
        oc[0].text = str(len(block.findall("chunk")))

    props = first(definition, "DefinitionProperties")
    if props is not None and items(props).get("Description"):
        items(props)["Description"][0].text = lesson["summary"]

    ET.indent(tree, space="  ")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n')
        tree.write(fh, encoding="utf-8", xml_declaration=False)
    log["stages"] = stage_record
    log["object_count"] = len(block.findall("chunk"))
    return log


def readme_text(lesson):
    s = lesson["source"]
    lines = [lesson["title"].upper(), "", lesson["summary"], "", "HOW TO USE"]
    lines += [f"{i}. {step}" for i, step in enumerate(lesson.get("how_to_use", []), 1)]
    if lesson.get("concepts"):
        lines += ["", "YOU WILL LEARN", *[f"- {c}" for c in lesson["concepts"]]]
    lines += ["", "READ THE CANVAS LEFT TO RIGHT",
              "Green = inputs you change, coloured boxes = numbered steps, blue = results.", "",
              "SOURCE", f"{s['author']} - {s['repo']}", f"{s['path']} @ {s['commit'][:10]}",
              f"Licence: {s['licence']} (see LICENCE panel)",
              "Modified for the Almond parametric library: regrouped, relabelled and annotated; "
              "the geometric logic is unchanged."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("lesson", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--licence", type=Path)
    a = ap.parse_args()
    lesson = json.loads(a.lesson.read_text(encoding="utf-8"))
    lic = a.licence.read_text(encoding="utf-8") if a.licence else None
    print(json.dumps(annotate(a.src, lesson, a.out, lic), indent=1))


if __name__ == "__main__":
    main()
