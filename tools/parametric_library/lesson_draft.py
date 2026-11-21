"""Print a definition's wired objects by depth to help write a lesson spec."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import xml.etree.ElementTree as ET
from annotate_ghx import Obj, build_graph, is_input, is_output, is_note, first, items, text
root = ET.parse(sys.argv[1]).getroot()
dobj = first(first(root, "Definition"), "DefinitionObjects")
objs = [Obj(el) for el in dobj.find("chunks").findall("chunk") if first(el, "Container") is not None]
build_graph(objs)
owner = {}
for o in objs:
    owner[o.guid] = (o, "")
    for p in o.outputs:
        owner[text(p, "InstanceGuid")] = (o, text(p, "Name"))
for o in sorted(objs, key=lambda o: (o.depth, o.type)):
    tag = "IN " if is_input(o) else "OUT" if is_output(o) else "NOTE" if is_note(o) else "   "
    extra = ""
    if o.type == "Scribble": extra = text(o.container, "Text")
    if o.type == "Panel": extra = (text(o.container, "UserText") or "")[:60].replace("\n", " / ")
    if o.type == "Group": extra = f"members={len(items(o.container).get('ID', []))}"
    if "Slider" in (o.type or ""):
        s = first(o.container, "Slider"); extra = "" if s is None else f"{text(s,'Min')}..{text(s,'Max')} = {text(s,'Value')}"
    print(f"{o.depth:3} {tag:4} {o.type[:26]:26} {repr(o.nickname)[:24]:24} {o.guid[:8]} {extra[:70]}")
    for p in o.inputs:
        srcs = [s.text for s in items(p).get("Source", [])]
        names = [f"{owner[s][0].type}.{owner[s][1]}({owner[s][0].guid[:8]})" for s in srcs if s in owner]
        pd = " [internal]" if first(p, "PersistentData") is not None and not srcs else ""
        if names or pd: print(f"            {text(p,'Name')}: {', '.join(names)}{pd}")
    floating = [s.text for s in items(o.container).get("Source", [])]
    if floating and not o.inputs:
        print("            <- " + ", ".join(f"{owner[s][0].type}.{owner[s][1]}({owner[s][0].guid[:8]})" for s in floating if s in owner))
