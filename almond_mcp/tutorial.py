"""The simulation tutorial model (BETA): a small annotated scene that shows what each analysis needs.

One data spec, in metres, drives everything:

* ``script(part, origin)`` - the C# RhinoCommon script that places it (run by the bridge's ``execute``,
  by the panel's "Place tutorial model" button and by the ``place_simulation_tutorial`` MCP tool);
* ``export_like(part)`` - the JSON the environment export would write for it, so tests can run the real
  engines on exactly what the tutorial places.

Parts:

* ``environment`` - an enclosed room (closed volume) with a window, an open loggia (closed curve +
  height), a neighbouring block as context, a north arrow and numbered text dots: room, glazing, open
  room, context, site (weather file) and how to run.
* ``structure`` - a 6 x 4 m single-bay frame: four columns and four beams as line axes, four support
  points, and text dots for members, supports, loads and how to run.

Everything sits on ``Almond Tutorial::<Part>::...`` layers. Placing a part again replaces that part's
previous objects (so the room names stay unique); nothing else in the document is touched.
"""
from __future__ import annotations

import json

ROOT = "Almond Tutorial"
PARTS = ("environment", "structure")
TITLE = "Almond simulation tutorial (BETA)"

# Layer colours: Rhino-neutral greys, with glazing a light blue as Rhino draws glass.
_LAYERS = {
    "Environment::Rooms": (150, 150, 150), "Environment::Glazing": (120, 170, 210),
    "Environment::Roof": (110, 110, 110), "Environment::Context": (190, 190, 190),
    "Environment::Notes": (60, 60, 60), "Structure::Members": (40, 40, 40),
    "Structure::Supports": (40, 40, 40), "Structure::Notes": (60, 60, 60),
}

ENV_ROOM = "Tutorial Studio"
ENV_LOGGIA = "Tutorial Loggia"
BEAM_SECTION = "box 100x200x6"      # almond:section, mm: width x depth x wall (RHS 200 x 100 x 6)
COLUMN_SECTION = "box 150x150x8"    # SHS 150 x 150 x 8: with the beams it passes 10 kN + 2.0/1.0 kN/m2
STRUCTURE_X = 32.0          # the structure part sits beside the environment part and its notes
NOTE_HEIGHT = 0.28          # m: the notes block's text height


def _environment() -> dict:
    return {
        "boxes": [
            {"layer": "Environment::Rooms", "name": ENV_ROOM, "min": (0, 0, 0), "max": (6, 5, 3),
             "tags": {"room": ENV_ROOM, "room_use": "living", "room_set": "eu_new_build"}},
            {"layer": "Environment::Context", "name": "Neighbour", "min": (-2, -14, 0), "max": (8, -10, 9), "tags": {}},
        ],
        "surfaces": [
            # on the south face of the room volume (y = 0); a closed room keeps its own windows clear
            {"layer": "Environment::Glazing", "name": "Window S",
             "corners": [(1.2, 0, 0.9), (4.8, 0, 0.9), (4.8, 0, 2.4), (1.2, 0, 2.4)],
             "tags": {"construction": "win_triple_lowe_ar_timber"}},
            {"layer": "Environment::Roof", "name": "Loggia roof",
             "corners": [(6, 0, 3), (9, 0, 3), (9, 5, 3), (6, 5, 3)], "tags": {}},
        ],
        "curves": [
            {"layer": "Environment::Rooms", "name": ENV_LOGGIA,
             "points": [(6, 0, 0), (9, 0, 0), (9, 5, 0), (6, 5, 0), (6, 0, 0)],
             "tags": {"room": ENV_LOGGIA, "room_use": "outdoor", "room_height": "3"}},
        ],
        "lines": [
            {"layer": "Environment::Notes", "name": "North", "a": (-3, 0, 0), "b": (-3, 3, 0)},
            {"layer": "Environment::Notes", "name": "North", "a": (-3, 3, 0), "b": (-3.4, 2.4, 0)},
            {"layer": "Environment::Notes", "name": "North", "a": (-3, 3, 0), "b": (-2.6, 2.4, 0)},
        ],
        "points": [],
        "texts": [
            {"layer": "Environment::Notes", "text": TITLE + " - Climate, Rooms & Comfort", "at": (-3, -6, 0), "height": 0.45},
            {"layer": "Environment::Notes", "text": "N", "at": (-3.25, 3.3, 0), "height": 0.5},
        ],
        "notes_at": (11.5, 8.0, 0),
        "dots": [
            {"layer": "Environment::Notes", "at": (3, 2.5, 3.4), "text":
             "1 ROOM - a closed volume\nTagged as a room: Rooms tab > Define room from selection.\n"
             "Use: living. Construction set: Europe, new build."},
            {"layer": "Environment::Notes", "at": (3, -0.4, 1.65), "text":
             "2 GLAZING - a planar surface on the wall face\nA layer or name with 'Glazing' or 'Window' makes it glass.\n"
             "Construction: triple low-e window (Constructions tab > Assign)."},
            {"layer": "Environment::Notes", "at": (7.5, 2.5, 1.5), "text":
             "3 OPEN ROOM - a closed curve + height (3 m)\nRooms may be open: assessed as semi-outdoor comfort (SET*).\n"
             "The roof surface above shades it."},
            {"layer": "Environment::Notes", "at": (3, -12, 9.4), "text":
             "4 CONTEXT - any visible object\nShades and reflects in every study.\nHide a layer to leave it out."},
            {"layer": "Environment::Notes", "at": (-3, 1.5, 0.3), "text":
             "5 SITE - a weather file (.epw), not geometry\nSite tab > Choose weather file (climate.onebuilding.org).\n"
             "North = Rhino Sun panel north (default +Y)."},
            {"layer": "Environment::Notes", "at": (11.5, 8.8, 0), "text":
             "6 RUN - Study tab\nThermal: rooms + weather file.\nDaylight factor: rooms + glazing. Annual daylight: + weather file.\n"
             "Hide or delete 'Almond Tutorial' before analysing your own model."},
        ],
    }


def _structure() -> dict:
    x = STRUCTURE_X
    base = [(x, 0, 0), (x + 6, 0, 0), (x + 6, 4, 0), (x, 4, 0)]
    top = [(p[0], p[1], 3.0) for p in base]
    columns = [{"layer": "Structure::Members", "name": f"Column {i + 1}", "a": b, "b": t, "tags": {"section": COLUMN_SECTION}}
               for i, (b, t) in enumerate(zip(base, top))]
    beams = [{"layer": "Structure::Members", "name": f"Beam {i + 1}", "a": top[i], "b": top[(i + 1) % 4],
              "tags": {"section": BEAM_SECTION}} for i in range(4)]
    return {
        "boxes": [], "surfaces": [], "curves": [],
        "lines": columns + beams,
        "points": [{"layer": "Structure::Supports", "name": f"Support {i + 1}", "at": p} for i, p in enumerate(base)],
        "texts": [{"layer": "Structure::Notes", "text": TITLE + " - Structure", "at": (x, -6, 0), "height": 0.45}],
        "notes_at": (x + 8.5, 6.0, 0),
        "dots": [
            {"layer": "Structure::Notes", "at": (x + 3, 0, 3.4), "text":
             "1 MEMBERS - lines or curves on the member axes\nColumns and beams share end points: snap them.\n"
             "Each carries its section as user text almond:section\n"
             f"(beams {BEAM_SECTION}, columns {COLUMN_SECTION}, mm). Material: Structure tab > Model."},
            {"layer": "Structure::Notes", "at": (x, 0, -0.4), "text":
             "2 SUPPORTS - point objects at the bases\nFixed or pinned: Structure tab > Supports."},
            {"layer": "Structure::Notes", "at": (x + 3, 2, 3.2), "text":
             "3 LOADS - Structure tab > Loads\nThe 6 x 4 m bay enclosed by beams takes a floor load (kN/m2):\n"
             "open Floor loads and model loads. Self-weight is included by default.\n"
             "With 10 kN + 2.0 / 1.0 kN/m2 these sections pass; without them (CHS 114.3 x 4) it fails."},
            {"layer": "Structure::Notes", "at": (x + 8.5, 6.8, 0), "text":
             "4 RUN - select the members and support points\n(SelLayer 'Almond Tutorial::Structure::*'), then\n"
             "Model > Use Rhino selection > Run native analysis."},
        ],
    }


def spec(part: str = "all") -> dict:
    """The tutorial in metres: {part: {boxes, surfaces, curves, lines, points, texts, dots}}."""
    parts = PARTS if part == "all" else (part,)
    if any(p not in PARTS for p in parts):
        raise ValueError(f"part must be all, {' or '.join(PARTS)}")
    build = {"environment": _environment, "structure": _structure}
    out = {p: build[p]() for p in parts}
    for name, part in out.items():
        # In the model each dot is a short numbered label; the full explanation of every number is one flat
        # notes block beside the part, so the dots stay readable when the model is zoomed out.
        layer = part["dots"][0]["layer"]
        for d in part["dots"]:
            d["label"] = d["text"].split("\n")[0].split(" - ")[0]         # "1 ROOM": the notes block says the rest
        heading = "WHAT EACH NUMBER MEANS - " + ("Climate, Rooms & Comfort" if name == "environment" else "Structural Validation")
        part["texts"].append({"layer": layer, "at": part.pop("notes_at"), "height": NOTE_HEIGHT, "top": True,
                              "text": heading + "\n\n" + "\n\n".join(d["text"] for d in part["dots"])})
    return out


def requirements() -> dict:
    """What each analysis needs before it can run, as the tutorial's dots teach it."""
    return {
        "thermal": ["at least one room (closed volume, bounding surfaces, or closed curve + height), tagged almond:room",
                    "a weather file (.epw) for the site",
                    "optional: constructions on walls/windows (almond:construction) or a room construction set"],
        "daylight_factor": ["at least one room", "glazing: surfaces whose layer, name or material says glass/glazing/window, "
                            "or a window construction", "no weather file needed"],
        "daylight_annual": ["as daylight_factor", "a weather file (.epw)"],
        "solar_radiation": ["the surfaces to analyse (any visible geometry)", "a weather file (.epw)"],
        "structure": ["member axes as lines or curves that share end points", "point objects at the supports "
                      "(else the lowest nodes are supported)", "a load: total load, floor load on bays enclosed by beams, "
                      "or self-weight"],
    }


# --- C# script ---------------------------------------------------------------------------------------

def _cs(s: str) -> str:
    return json.dumps(s, ensure_ascii=True)   # a valid C# string literal for plain text


def _pt(p) -> str:
    return f"P({float(p[0])!r}, {float(p[1])!r}, {float(p[2])!r})"


def _tags(tags: dict) -> str:
    return "new string[] { " + ", ".join(f"{_cs(k)}, {_cs(v)}" for k, v in tags.items()) + " }"


_CS = r'''
using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

public static class AlmondTutorial
{
  static double S; static Vector3d O; static RhinoDoc D; static List<Guid> Made = new List<Guid>();
  static Point3d P(double x, double y, double z) { return new Point3d(O.X + x * S, O.Y + y * S, O.Z + z * S); }
  static int Layer(string path, int r, int g, int b) {
    int idx = D.Layers.FindByFullPath(path, -1);
    if (idx >= 0) return idx;
    int parent = -1; string[] names = path.Split(new[] { "::" }, StringSplitOptions.None); string cur = "";
    for (int i = 0; i < names.Length; i++) {
      cur = i == 0 ? names[0] : cur + "::" + names[i];
      int found = D.Layers.FindByFullPath(cur, -1);
      if (found < 0) {
        var l = new Layer { Name = names[i], Color = i == names.Length - 1 ? System.Drawing.Color.FromArgb(r, g, b) : System.Drawing.Color.Black };
        if (parent >= 0) l.ParentLayerId = D.Layers[parent].Id;
        found = D.Layers.Add(l);
      }
      parent = found;
    }
    return parent;
  }
  static ObjectAttributes A(int layer, string name, string[] tags) {
    var a = new ObjectAttributes { LayerIndex = layer, Name = name };
    for (int i = 0; i + 1 < tags.Length; i += 2) a.SetUserString("almond:" + tags[i], tags[i + 1]);
    return a;
  }
  static void Keep(Guid id) { if (id != Guid.Empty) Made.Add(id); }
  static void Clear(string root) {
    foreach (var l in D.Layers.ToList()) {
      if (l.IsDeleted || !(l.FullPath == root || l.FullPath.StartsWith(root + "::", StringComparison.Ordinal))) continue;
      foreach (var o in D.Objects.FindByLayer(l)) D.Objects.Delete(o, true);
    }
  }
  public static List<Guid> Run(RhinoDoc doc) {
    D = doc; Made.Clear();
    S = RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem);
    double tol = doc.ModelAbsoluteTolerance;
    O = new Vector3d(__OX__ * S, __OY__ * S, __OZ__ * S);
    if (__AUTO__) {
      // beside the visible model, so the tutorial never overlaps the user's geometry
      var es = new ObjectEnumeratorSettings { HiddenObjects = false, DeletedObjects = false };
      var box = BoundingBox.Empty;
      foreach (var o in doc.Objects.GetObjectList(es)) {
        int li = o.Attributes.LayerIndex;
        string lp = li >= 0 && li < doc.Layers.Count ? doc.Layers[li].FullPath : "";
        if (lp.StartsWith("__ROOT__", StringComparison.Ordinal) || lp.StartsWith("Almond::", StringComparison.Ordinal)) continue;
        box.Union(o.Geometry.GetBoundingBox(true));
      }
      if (box.IsValid) O = new Vector3d(box.Max.X + 10 * S + 4 * S, box.Min.Y, box.Min.Z);
    }
__BODY__
    doc.Views.Redraw();
    return Made;
  }
}
'''


def script(part: str = "all", origin: tuple[float, float, float] | None = None) -> str:
    """The C# script that places the tutorial (origin in metres; None = beside the visible model)."""
    data = spec(part)
    body: list[str] = []
    for p in data:
        body.append(f"    Clear({_cs(ROOT + '::' + p.capitalize())});")
    for name, rgb in _LAYERS.items():
        if name.split("::")[0].lower() in data:
            body.append(f"    int L_{name.replace('::', '_')} = Layer({_cs(ROOT + '::' + name)}, {rgb[0]}, {rgb[1]}, {rgb[2]});")

    def lay(layer: str) -> str:
        return "L_" + layer.replace("::", "_")

    for p in data.values():
        for b in p["boxes"]:
            body.append(f"    Keep(doc.Objects.AddBrep(new Box(new BoundingBox({_pt(b['min'])}, {_pt(b['max'])})).ToBrep(), "
                        f"A({lay(b['layer'])}, {_cs(b['name'])}, {_tags(b['tags'])})));")
        for s in p["surfaces"]:
            c = s["corners"]
            body.append(f"    Keep(doc.Objects.AddBrep(Brep.CreateFromCornerPoints({_pt(c[0])}, {_pt(c[1])}, {_pt(c[2])}, {_pt(c[3])}, tol), "
                        f"A({lay(s['layer'])}, {_cs(s['name'])}, {_tags(s['tags'])})));")
        for c in p["curves"]:
            pts = ", ".join(_pt(q) for q in c["points"])
            body.append(f"    Keep(doc.Objects.AddPolyline(new Polyline(new[] {{ {pts} }}), "
                        f"A({lay(c['layer'])}, {_cs(c['name'])}, {_tags(c['tags'])})));")
        for ln in p["lines"]:
            body.append(f"    Keep(doc.Objects.AddLine(new Line({_pt(ln['a'])}, {_pt(ln['b'])}), "
                        f"A({lay(ln['layer'])}, {_cs(ln['name'])}, {_tags(ln.get('tags') or {})})));")
        for pt in p["points"]:
            body.append(f"    Keep(doc.Objects.AddPoint({_pt(pt['at'])}, A({lay(pt['layer'])}, {_cs(pt['name'])}, new string[0])));")
        for t in p["texts"]:
            top = " TextVerticalAlignment = TextVerticalAlignment.Top," if t.get("top") else ""
            body.append(f"    {{ var te = new TextEntity {{ Plane = new Plane({_pt(t['at'])}, Vector3d.ZAxis), PlainText = {_cs(t['text'])},{top} "
                        f"TextHeight = {float(t['height'])!r} * S, "
                        # a white mask behind dark text: readable on any viewport background, light or dark
                        f"MaskEnabled = true, MaskUsesViewportColor = false, MaskColor = System.Drawing.Color.White, "
                        f"MaskOffset = 0.12 * S }}; "
                        f"Keep(doc.Objects.AddText(te, A({lay(t['layer'])}, \"Tutorial text\", new string[0]))); }}")
        for d in p["dots"]:
            body.append(f"    {{ var dot = new TextDot({_cs(d['label'])}, {_pt(d['at'])}) {{ FontHeight = 12 }}; "
                        f"Keep(doc.Objects.AddTextDot(dot, A({lay(d['layer'])}, \"Tutorial note\", new string[0]))); }}")
    o = origin or (0.0, 0.0, 0.0)
    return (_CS.replace("__BODY__", "\n".join(body)).replace("__ROOT__", ROOT)
            .replace("__OX__", repr(float(o[0]))).replace("__OY__", repr(float(o[1]))).replace("__OZ__", repr(float(o[2])))
            .replace("__AUTO__", "false" if origin is not None else "true"))


# --- what the environment export sees ----------------------------------------------------------------

def _box_mesh(lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]   # outward normals
    return v, [t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))]


def export_like(part: str = "environment") -> dict:
    """The environment export JSON for the tutorial (metres, origin at 0), as rhino.export_script writes it."""
    objects = []
    for pname, p in spec(part).items():
        for i, b in enumerate(p["boxes"]):
            v, f = _box_mesh(b["min"], b["max"])
            objects.append({"guid": f"{pname}-box-{i}", "layer": f"{ROOT}::{b['layer']}", "name": b["name"], "material": "",
                            "transparency": 0.0, "env_material": "", **b["tags"],
                            "vertices": [c for q in v for c in q], "faces": [c for t in f for c in t]})
        for i, s in enumerate(p["surfaces"]):
            objects.append({"guid": f"{pname}-srf-{i}", "layer": f"{ROOT}::{s['layer']}", "name": s["name"], "material": "",
                            "transparency": 0.0, "env_material": "", **s["tags"],
                            "vertices": [c for q in s["corners"] for c in q], "faces": [0, 1, 2, 0, 2, 3]})
        for i, c in enumerate(p["curves"]):
            objects.append({"guid": f"{pname}-crv-{i}", "layer": f"{ROOT}::{c['layer']}", "name": c["name"], **c["tags"],
                            "boundary": [x for q in c["points"] for x in q], "vertices": [], "faces": []})
    return {"units_to_m": 1.0, "units": "Meters", "rhino_north_deg": 90.0, "objects": objects,
            "missing": [], "skipped": [], "skipped_rooms": []}


def structure_model() -> dict:
    """The structure part as the line model validate_structure's native path reads (metres)."""
    p = spec("structure")["structure"]
    def section(text: str) -> dict:          # almond:section box W x D x T (mm) as the bridge exports it (m)
        w, d, t = (float(v) / 1000 for v in text.split()[1].split("x"))
        return {"shape": "box", "width": w, "height": d, "wall": t, "source": "user"}
    members = [{"source_guids": [ln["name"]], "points": [list(ln["a"]), list(ln["b"])], "section": section(ln["tags"]["section"])}
               for ln in p["lines"]]
    return {"members": members, "anchor_points": [list(q["at"]) for q in p["points"]], "tolerance_m": 0.001,
            "max_member_span_m": 6.0, "max_span_m": 6.0, "warnings": []}
