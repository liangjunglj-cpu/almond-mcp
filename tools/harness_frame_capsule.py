"""Harness Karamba's 01_SimpleFrame.ghx for the karamba_frame_v1 capsule.

Reproduces the 2026-08-29 harnessing without opening Grasshopper: the
Karamba example ships as a BINARY archive misnamed .ghx, so this script
drives GH_IO.dll (no Rhino/GH editor needed) to convert it to XML, adds
the reserved ALMOND_* harness params by direct XML synthesis, rewires the
definition, and writes an XML .ghx into the harnessed/ folder that
GhDefinitionRunner prefers.

Harness contract (mirrors capsules/karamba_frame_v1.capsule.json):
  ALMOND_IN_LINES     Param_Curve  -> Create Linear Element "Line" input
                      (replaces the template's internal parametric geometry)
  ALMOND_IN_LOAD_KN   Param_Number -> Unit-Z load vector factor
                      (replaces the vertical load slider; the template's
                      built-in lateral -2 kN/m load in X remains)
  ALMOND_IN_SUPPORTS  Param_Point  -> both Support components' "Pos|Ind"
                      (replaces internal support points; the validator
                      supplies lowest-Z nodes when the caller doesn't)
  ALMOND_OUT_DISP_MM  Param_Number <- Analyse "Maximum Displacement [cm]"
                      (manifest declares units "cm"; converted downstream)
  ALMOND_OUT_MASS_KG  Param_Number <- Assemble Model "Mass [kg]"

Requires Windows with Rhino 8 installed (for GH_IO.dll) and pythonnet OR
PowerShell for the binary<->XML conversion steps; the XML surgery itself
is pure stdlib. Run from the repo root:

    python tools/harness_frame_capsule.py

Verified live 2026-08-29: an 8 m x 4 m portal (3 lines) with 10 kN/m and
two base support points returned disp 0.234 cm and mass 1413 kg via
run_gh_definition, with no rigid-body-mode warnings.
"""
from __future__ import annotations

import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

GH_IO = Path(r"C:\Program Files\Rhino 8\Plug-ins\Grasshopper\GH_IO.dll")
SOURCE = Path(r"C:\Users\liang\OneDrive\Documents\Almond\Grasshopperfiles"
              r"\Karambafileswithmodel\01_SimpleFrame.ghx")
DEST = Path(r"C:\Users\liang\OneDrive\Documents\Almond\Grasshopperfiles"
            r"\Karambafiles\harnessed\01_SimpleFrame.ghx")

# GH core param component type guids (verified via reflection in Rhino 8).
PARAM_CURVE = "d5967b9f-e8ee-436b-a8ad-29fdcecf32d5"
PARAM_NUMBER = "3e8ca6be-fda8-4aaf-b5c0-3c54c8bb7312"
PARAM_POINT = "fbac3e32-f100-4292-8692-77240a42fd1a"

# Instance guids inside 01_SimpleFrame.ghx (stable: they are saved in the file).
MERGE2_RESULT = "c99c0e66-e7f3-4e7f-b513-ab7c2f5c4e9c"   # merged frame lines
LOAD_SLIDER = "c5dca863-75d0-4a77-a13b-2bb7defa936b"     # vertical load slider (5)
ANALYSE_DISP_OUT = "c1633359-3ae4-43c1-9709-be5a2e13d990"  # Max Displacement [cm]
ASSEMBLE_MASS_OUT = "85fffb18-8816-486d-a0a8-5a0465add6a5"  # Mass [kg]


def powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True, check=True)
    return result.stdout


def binary_ghx_to_xml(path: Path) -> str:
    tmp = path.with_suffix(".exported.xml")
    powershell(f"""
Add-Type -Path "{GH_IO}"
$a = New-Object GH_IO.Serialization.GH_Archive
$bytes = [IO.File]::ReadAllBytes("{path}")
if (-not $a.Deserialize_Binary($bytes)) {{ throw "binary deserialize failed" }}
[IO.File]::WriteAllText("{tmp}", $a.Serialize_Xml(), [Text.Encoding]::UTF8)
""")
    xml = tmp.read_text(encoding="utf-8")
    tmp.unlink()
    return xml


def normalize_and_write(xml_text: str, dest: Path) -> None:
    tmp = dest.with_suffix(".pending.xml")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(xml_text, encoding="utf-8")
    powershell(f"""
Add-Type -Path "{GH_IO}"
$a = New-Object GH_IO.Serialization.GH_Archive
if (-not $a.Deserialize_Xml([IO.File]::ReadAllText("{tmp}"))) {{ throw "xml round-trip failed" }}
[IO.File]::WriteAllText("{dest}", $a.Serialize_Xml(), [Text.Encoding]::UTF8)
""")
    tmp.unlink()


def make_param(idx: int, type_guid: str, type_name: str, nick: str,
               desc: str, source: str | None, x: int, y: int) -> ET.Element:
    inst = str(uuid.uuid4())
    obj = ET.Element("chunk", {"name": "Object", "index": str(idx)})
    items = ET.SubElement(obj, "items", {"count": "2"})

    def item(parent, name, text, tn="gh_string", tc="10", extra=None):
        attrs = {"name": name, "type_name": tn, "type_code": tc}
        if extra:
            attrs.update(extra)
        e = ET.SubElement(parent, "item", attrs)
        e.text = text
        return e

    item(items, "GUID", type_guid, "gh_guid", "9")
    item(items, "Name", type_name)
    chunks = ET.SubElement(obj, "chunks", {"count": "1"})
    cont = ET.SubElement(chunks, "chunk", {"name": "Container"})
    citems = ET.SubElement(cont, "items",
                           {"count": str(7 + (1 if source else 0))})
    item(citems, "Description", desc)
    item(citems, "InstanceGuid", inst, "gh_guid", "9")
    item(citems, "Mapping", "1", "gh_int32", "3")
    item(citems, "Name", type_name)
    item(citems, "NickName", nick)
    item(citems, "Optional", "true", "gh_bool", "1")
    if source:
        item(citems, "Source", source, "gh_guid", "9", {"index": "0"})
    item(citems, "SourceCount", "1" if source else "0", "gh_int32", "3")
    cchunks = ET.SubElement(cont, "chunks", {"count": "1"})
    att = ET.SubElement(cchunks, "chunk", {"name": "Attributes"})
    aitems = ET.SubElement(att, "items", {"count": "2"})
    bounds = ET.SubElement(aitems, "item", {
        "name": "Bounds", "type_name": "gh_drawing_rectanglef", "type_code": "35"})
    for tag, val in (("X", str(x)), ("Y", str(y)), ("W", "160"), ("H", "24")):
        ET.SubElement(bounds, tag).text = val
    pivot = ET.SubElement(aitems, "item", {
        "name": "Pivot", "type_name": "gh_drawing_pointf", "type_code": "31"})
    for tag, val in (("X", str(x + 80)), ("Y", str(y + 12))):
        ET.SubElement(pivot, tag).text = val
    obj.set("data-inst", inst)   # scratch attribute, stripped below
    return obj


def main() -> None:
    xml_text = binary_ghx_to_xml(SOURCE)
    root = ET.fromstring(xml_text)

    defobjs = next(c for c in root.iter("chunk")
                   if c.get("name") == "DefinitionObjects")
    oc = next(it for it in defobjs.find("items").iter("item")
              if it.get("name") == "ObjectCount")
    count = int(oc.text)
    holder = defobjs.find("chunks")

    params = [
        make_param(count + 0, PARAM_CURVE, "Curve", "ALMOND_IN_LINES",
                   "Almond harness: frame member axis curves in metres.",
                   None, 60, 40),
        make_param(count + 1, PARAM_NUMBER, "Number", "ALMOND_IN_LOAD_KN",
                   "Almond harness: vertical line-load magnitude, drives the "
                   "Unit-Z load vector.", None, 60, 110),
        make_param(count + 2, PARAM_NUMBER, "Number", "ALMOND_OUT_DISP_MM",
                   "Almond harness: max displacement from Analyse (cm).",
                   ANALYSE_DISP_OUT, 60, 180),
        make_param(count + 3, PARAM_NUMBER, "Number", "ALMOND_OUT_MASS_KG",
                   "Almond harness: structural mass from Assemble Model [kg].",
                   ASSEMBLE_MASS_OUT, 60, 250),
        make_param(count + 4, PARAM_POINT, "Point", "ALMOND_IN_SUPPORTS",
                   "Almond harness: support node positions in metres; the "
                   "validator supplies lowest-Z nodes when empty.", None, 60, 320),
    ]
    g_lines = params[0].get("data-inst")
    g_load = params[1].get("data-inst")
    g_supports = params[4].get("data-inst")
    for p in params:
        del p.attrib["data-inst"]
        holder.append(p)
    holder.set("count", str(count + len(params)))
    oc.text = str(count + len(params))

    rewired = {"lines": 0, "load": 0, "supports": 0}
    for it in root.iter("item"):
        if it.get("name") != "Source":
            continue
        if it.text == MERGE2_RESULT:
            it.text = g_lines
            rewired["lines"] += 1
        elif it.text == LOAD_SLIDER:
            it.text = g_load
            rewired["load"] += 1
    for pc in root.iter("chunk"):
        if pc.get("name") != "param_input":
            continue
        pits = pc.find("items")
        if pits is None:
            continue
        name = next((it.text for it in pits.iter("item")
                     if it.get("name") == "Name"), None)
        if name != "Pos|Ind":
            continue
        sources = [it for it in pits.findall("item")
                   if it.get("name") == "Source"]
        for i, it in enumerate(sources):
            if i == 0:
                it.text = g_supports
                it.set("index", "0")
            else:
                pits.remove(it)
        sc = next((it for it in pits.iter("item")
                   if it.get("name") == "SourceCount"), None)
        if sc is not None:
            sc.text = "1"
        pits.set("count", str(len(pits.findall("item"))))
        rewired["supports"] += 1

    assert rewired == {"lines": 1, "load": 1, "supports": 2}, rewired
    normalize_and_write(
        ET.tostring(root, encoding="unicode"), DEST)
    print(f"harnessed -> {DEST}")
    print("Now verify a run (run_gh_definition with 3 portal lines, load, "
          "2 base points) BEFORE trusting audited=true.")


if __name__ == "__main__":
    main()
