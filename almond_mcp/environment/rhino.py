"""C# RhinoCommon scripts for the environmental analysis tools (sent through the bridge's ``execute``).

* export: meshes the chosen objects (or every visible object) to a JSON file - vertices, triangles,
  layer path, object name, render material name and transparency, ``almond:env_material`` user text,
  rooms and constructions (``almond:room``, ``almond:room_use``, ``almond:room_set``, ``almond:room_heat_c``,
  ``almond:room_cool_c``, ``almond:room_height``, ``almond:construction``); closed planar curves tagged
  as rooms are exported as boundary polylines,
  block instances flattened with their own nested layers - plus the document's unit scale and the
  Sun panel's north angle.
* draw: reads a small text file of coloured quads and legend labels and adds one vertex-coloured mesh
  plus text dots on ``Almond::Environment::<label>``.
* clear: deletes the objects on that layer (or on every Environment layer).
* tag: sets or removes ``almond:*`` user text on objects (rooms, constructions), as one undoable step.

Result layers live under ``Almond::Environment`` and are never exported as geometry.
"""
from __future__ import annotations

import json
import re

RESULT_ROOT = "Almond::Environment"

_CS_EXPORT = r'''
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

public class Script {
  static CultureInfo C = CultureInfo.InvariantCulture;
  static string Esc(string s) {
    if (s == null) return "";
    var sb = new StringBuilder();
    foreach (char ch in s) {
      if (ch == '"') sb.Append("\\\""); else if (ch == '\\') sb.Append("\\\\");
      else if (ch < ' ') sb.Append("\\u" + ((int)ch).ToString("x4")); else sb.Append(ch);
    }
    return sb.ToString();
  }
  static List<Mesh> Meshes(GeometryBase g, MeshingParameters mp) {
    var res = new List<Mesh>();
    if (g == null) return res;
    if (g is Mesh) { res.Add(((Mesh)g).DuplicateMesh()); return res; }
    Brep b = null;
    if (g is Brep) b = (Brep)g;
    else if (g is Extrusion) b = ((Extrusion)g).ToBrep(true);
    else if (g is Surface) b = ((Surface)g).ToBrep();
    else if (g is SubD) { var sm = Mesh.CreateFromSubD((SubD)g, 2); if (sm != null) res.Add(sm); return res; }
    if (b != null) { var ms = Mesh.CreateFromBrep(b, mp); if (ms != null) res.AddRange(ms); }
    return res;
  }
  static void Emit(StringBuilder sb, ref bool first, RhinoDoc doc, RhinoObject obj, ObjectAttributes attr, string guid,
                   List<Mesh> parts, Transform xf) {
    var m = new Mesh();
    foreach (var p in parts) { if (p != null && p.IsValid) m.Append(p); }
    if (m.Faces.Count == 0) return;
    if (!xf.IsIdentity) m.Transform(xf);
    m.Faces.ConvertQuadsToTriangles();
    m.Compact();
    string layer = "";
    if (attr.LayerIndex >= 0 && attr.LayerIndex < doc.Layers.Count) layer = doc.Layers[attr.LayerIndex].FullPath;
    string matName = ""; double transp = 0.0;
    try {
      var rm = obj != null ? obj.RenderMaterial : null;
      if (rm != null) matName = rm.Name;
      var mat = obj != null ? obj.GetMaterial(true) : null;
      if (mat != null) { if (matName == "") matName = mat.Name; transp = mat.Transparency; }
    } catch { }
    string envMat = attr.GetUserString("almond:env_material") ?? "";
    if (!first) sb.Append(",");
    first = false;
    sb.Append("{\"guid\":\"").Append(guid).Append("\",\"layer\":\"").Append(Esc(layer))
      .Append("\",\"name\":\"").Append(Esc(attr.Name)).Append("\",\"material\":\"").Append(Esc(matName))
      .Append("\",\"transparency\":").Append(transp.ToString("R", C))
      .Append(",\"env_material\":\"").Append(Esc(envMat)).Append("\"");
    Tags(sb, attr);
    sb.Append(",\"vertices\":[");
    for (int i = 0; i < m.Vertices.Count; i++) {
      var v = m.Vertices[i];
      if (i > 0) sb.Append(",");
      sb.Append(((double)v.X).ToString("G9", C)).Append(",").Append(((double)v.Y).ToString("G9", C)).Append(",").Append(((double)v.Z).ToString("G9", C));
    }
    sb.Append("],\"faces\":[");
    for (int i = 0; i < m.Faces.Count; i++) {
      var f = m.Faces[i];
      if (i > 0) sb.Append(",");
      sb.Append(f.A).Append(",").Append(f.B).Append(",").Append(f.C);
    }
    sb.Append("]}");
  }
  static string[] TagKeys = { "construction", "room", "room_use", "room_set", "room_heat_c", "room_cool_c", "room_height" };
  static void Tags(StringBuilder sb, ObjectAttributes attr) {
    foreach (var k in TagKeys) {
      string val = attr.GetUserString("almond:" + k);
      if (!string.IsNullOrEmpty(val)) sb.Append(",\"").Append(k).Append("\":\"").Append(Esc(val)).Append("\"");
    }
  }
  static bool EmitBoundary(StringBuilder sb, ref bool first, RhinoDoc doc, RhinoObject obj, ObjectAttributes attr, string guid, Transform xf) {
    var crv = obj.Geometry as Curve;
    if (crv == null || string.IsNullOrEmpty(attr.GetUserString("almond:room"))) return false;
    if (!crv.IsClosed || !crv.IsPlanar()) return false;
    var c = crv.DuplicateCurve();
    if (!xf.IsIdentity) c.Transform(xf);
    Polyline pl;
    if (!c.TryGetPolyline(out pl)) {
      var pc = c.ToPolyline(0.01 * RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem), 0.05, 0.0, 0.0);
      if (pc == null || !pc.TryGetPolyline(out pl)) return false;
    }
    string layer = "";
    if (attr.LayerIndex >= 0 && attr.LayerIndex < doc.Layers.Count) layer = doc.Layers[attr.LayerIndex].FullPath;
    if (!first) sb.Append(",");
    first = false;
    sb.Append("{\"guid\":\"").Append(guid).Append("\",\"layer\":\"").Append(Esc(layer))
      .Append("\",\"name\":\"").Append(Esc(attr.Name)).Append("\"");
    Tags(sb, attr);
    sb.Append(",\"boundary\":[");
    for (int i = 0; i < pl.Count; i++) {
      if (i > 0) sb.Append(",");
      sb.Append(pl[i].X.ToString("G9", C)).Append(",").Append(pl[i].Y.ToString("G9", C)).Append(",").Append(pl[i].Z.ToString("G9", C));
    }
    sb.Append("],\"vertices\":[],\"faces\":[]}");
    return true;
  }
  static void Walk(StringBuilder sb, ref bool first, RhinoDoc doc, RhinoObject obj, ObjectAttributes attr, string guid,
                   Transform xf, MeshingParameters mp, int depth, ref int count) {
    if (depth > 8) return;
    var inst = obj as InstanceObject;
    if (inst != null) {
      var x = xf * inst.InstanceXform;
      foreach (var sub in inst.InstanceDefinition.GetObjects())
        Walk(sb, ref first, doc, sub, sub.Attributes, guid, x, mp, depth + 1, ref count);
      return;
    }
    if (EmitBoundary(sb, ref first, doc, obj, attr, guid, xf)) { count++; return; }
    var parts = Meshes(obj.Geometry, mp);
    if (parts.Count == 0) return;
    // thin curved parts (railings, balusters, pipes) mesh to thousands of facets that add nothing to
    // a light simulation: re-mesh anything heavy as coarsely as Rhino allows
    int faces = 0;
    foreach (var p in parts) faces += p.Faces.Count;
    if (faces > 4000 && !(obj.Geometry is Mesh)) {
      var coarse = Meshes(obj.Geometry, MeshingParameters.Minimal);
      int cf = 0;
      foreach (var p in coarse) cf += p.Faces.Count;
      if (coarse.Count > 0 && cf < faces) parts = coarse;
    }
    Emit(sb, ref first, doc, obj, attr, guid, parts, xf);
    count++;
  }
  public static List<Guid> Run(RhinoDoc doc) {
    string[] ids = new string[] { __IDS__ };
    string root = "__ROOT__";
    double scale = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters);
    double north = 0.0;
    try { north = doc.Lights.Sun.North; } catch { }
    var mp = MeshingParameters.FastRenderMesh;
    mp.SimplePlanes = true;
    var objs = new List<RhinoObject>();
    var missing = new List<string>();
    if (ids.Length > 0) {
      foreach (var s in ids) {
        Guid g;
        RhinoObject o = Guid.TryParse(s, out g) ? doc.Objects.FindId(g) : null;
        if (o == null || o.IsDeleted) missing.Add(s); else objs.Add(o);
      }
    } else {
      var es = new ObjectEnumeratorSettings();
      es.HiddenObjects = false; es.LockedObjects = true; es.VisibleFilter = true; es.DeletedObjects = false;
      foreach (var o in doc.Objects.GetObjectList(es)) {
        int li = o.Attributes.LayerIndex;
        string lp = (li >= 0 && li < doc.Layers.Count) ? doc.Layers[li].FullPath : "";
        if (lp.StartsWith(root, StringComparison.OrdinalIgnoreCase)) continue;
        objs.Add(o);
      }
    }
    var sb = new StringBuilder();
    sb.Append("{\"units_to_m\":").Append(scale.ToString("R", C)).Append(",\"units\":\"").Append(doc.ModelUnitSystem.ToString())
      .Append("\",\"rhino_north_deg\":").Append(north.ToString("R", C)).Append(",\"objects\":[");
    bool first = true; int count = 0;
    var skipped = new List<string>();
    var skippedRooms = new List<string>();
    foreach (var o in objs) {
      int before = count;
      Walk(sb, ref first, doc, o, o.Attributes, o.Id.ToString(), Transform.Identity, mp, 0, ref count);
      if (count == before) {
        skipped.Add(o.Id.ToString());
        if (!string.IsNullOrEmpty(o.Attributes.GetUserString("almond:room"))) skippedRooms.Add(o.Id.ToString());
      }
    }
    sb.Append("],\"missing\":[");
    sb.Append(string.Join(",", missing.Select(s => "\"" + Esc(s) + "\"")));
    sb.Append("],\"skipped\":[");
    sb.Append(string.Join(",", skipped.Select(s => "\"" + s + "\"")));
    sb.Append("],\"skipped_rooms\":[");
    sb.Append(string.Join(",", skippedRooms.Select(s => "\"" + s + "\"")));
    sb.Append("]}");
    File.WriteAllText(@"__OUT__", sb.ToString(), new UTF8Encoding(false));
    return new List<Guid>();
  }
}
'''

_CS_DRAW = r'''
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

public class Script {
  static int EnsureLayer(RhinoDoc doc, string path) {
    int idx = doc.Layers.FindByFullPath(path, -1);
    if (idx >= 0) return idx;
    string[] parts = path.Split(new[] { "::" }, StringSplitOptions.None);
    Guid parent = Guid.Empty;
    string acc = "";
    for (int i = 0; i < parts.Length; i++) {
      acc = i == 0 ? parts[0] : acc + "::" + parts[i];
      idx = doc.Layers.FindByFullPath(acc, -1);
      if (idx < 0) {
        var l = new Layer { Name = parts[i] };
        if (parent != Guid.Empty) l.ParentLayerId = parent;
        idx = doc.Layers.Add(l);
      }
      parent = doc.Layers[idx].Id;
    }
    return idx;
  }
  public static List<Guid> Run(RhinoDoc doc) {
    var C = CultureInfo.InvariantCulture;
    string layerPath = "__LAYER__";
    string tag = "__TAG__";
    var created = new List<Guid>();
    int li = EnsureLayer(doc, layerPath);
    var layer = doc.Layers[li];
    foreach (var o in doc.Objects.FindByLayer(layer)) doc.Objects.Delete(o, true);
    var mesh = new Mesh();
    var attr = new ObjectAttributes { LayerIndex = li, Name = "__NAME__" };
    attr.SetUserString("almond:env_result", tag);
    foreach (var line in File.ReadLines(@"__IN__")) {
      if (line.Length == 0) continue;
      var f = line.Split(',');
      if (f[0] == "Q") {
        int b = mesh.Vertices.Count;
        var col = Color.FromArgb(int.Parse(f[13], C), int.Parse(f[14], C), int.Parse(f[15], C));
        var q = new Point3d[4];
        for (int k = 0; k < 4; k++) {
          q[k] = new Point3d(double.Parse(f[1 + 3 * k], C), double.Parse(f[2 + 3 * k], C), double.Parse(f[3 + 3 * k], C));
          mesh.Vertices.Add(q[k]);
          mesh.VertexColors.Add(col);
        }
        // a sensor on a curved surface stands for a triangle, sent as a quad with a repeated corner
        if (q[2].DistanceTo(q[3]) < 1e-9) mesh.Faces.AddFace(b, b + 1, b + 2);
        else mesh.Faces.AddFace(b, b + 1, b + 2, b + 3);
      } else if (f[0] == "T") {
        int p = 0;
        for (int k = 0; k < 4; k++) p = line.IndexOf(',', p) + 1;      // the text is everything after x,y,z
        var dot = new TextDot(line.Substring(p), new Point3d(double.Parse(f[1], C), double.Parse(f[2], C), double.Parse(f[3], C)));
        dot.FontHeight = 12;
        var ta = attr.Duplicate();
        created.Add(doc.Objects.AddTextDot(dot, ta));
      }
    }
    if (mesh.Faces.Count > 0) {
      mesh.Faces.CullDegenerateFaces();
      mesh.Normals.ComputeNormals();
      var id = doc.Objects.AddMesh(mesh, attr);
      if (id == Guid.Empty) {
        string log;
        mesh.IsValidWithLog(out log);
        throw new Exception("Rhino refused the result mesh (" + mesh.Faces.Count + " faces): " + log);
      }
      created.Add(id);
    }
    doc.Views.Redraw();
    return created;
  }
}
'''

_CS_CLEAR = r'''
using System;
using System.Collections.Generic;
using Rhino;
using Rhino.DocObjects;

public class Script {
  public static List<Guid> Run(RhinoDoc doc) {
    string root = "__LAYER__";
    var victims = new List<RhinoObject>();
    foreach (var l in doc.Layers) {
      if (l.IsDeleted) continue;
      if (l.FullPath.Equals(root, StringComparison.OrdinalIgnoreCase) || l.FullPath.StartsWith(root + "::", StringComparison.OrdinalIgnoreCase))
        victims.AddRange(doc.Objects.FindByLayer(l));
    }
    foreach (var o in victims) doc.Objects.Delete(o, true);
    doc.Views.Redraw();
    return new List<Guid>();
  }
}
'''

_CS_TAG = r'''
using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.DocObjects;

public class Script {
  public static List<Guid> Run(RhinoDoc doc) {
    // guid, key, value triples; an empty value removes the key
    string[] t = new string[] { __TRIPLES__ };
    string uniqueRoom = __UNIQUE_ROOM__;
    // check everything before changing anything, so a bad request leaves the model untouched
    var objects = new Dictionary<string, RhinoObject>();
    var missing = new List<string>();
    for (int i = 0; i + 2 < t.Length; i += 3) {
      if (objects.ContainsKey(t[i]) || missing.Contains(t[i])) continue;
      Guid g;
      RhinoObject o = Guid.TryParse(t[i], out g) ? doc.Objects.FindId(g) : null;
      if (o == null) missing.Add(t[i]); else objects[t[i]] = o;
    }
    if (missing.Count > 0) throw new Exception("Objects not found (nothing was tagged): " + string.Join(", ", missing));
    if (uniqueRoom.Length > 0) {
      var ids = new HashSet<Guid>(objects.Values.Select(o => o.Id));
      int others = 0;
      foreach (var o in doc.Objects)
        if (!ids.Contains(o.Id) && string.Equals(o.Attributes.GetUserString("almond:room"), uniqueRoom, StringComparison.OrdinalIgnoreCase)) others++;
      if (others > 0)
        throw new Exception("A room named '" + uniqueRoom + "' already exists on " + others + " other object(s) (nothing was tagged). " +
                            "Choose another name, remove that room first, or select all of its objects together.");
    }
    uint undo = doc.BeginUndoRecord("Almond environment tags");
    var done = new List<Guid>();
    try {
      for (int i = 0; i + 2 < t.Length; i += 3) {
        var o = objects[t[i]];
        var attr = o.Attributes.Duplicate();
        if (t[i + 2].Length == 0) attr.DeleteUserString("almond:" + t[i + 1]);
        else attr.SetUserString("almond:" + t[i + 1], t[i + 2]);
        doc.Objects.ModifyAttributes(o, attr, true);
        if (!done.Contains(o.Id)) done.Add(o.Id);
      }
    } finally { doc.EndUndoRecord(undo); }
    doc.Views.Redraw();
    return done;
  }
}
'''

_CS_SUN_VIEWS = r'''
using System;
using System.Collections.Generic;
using Rhino;
using Rhino.Display;

public class Script {
  public static List<Guid> Run(RhinoDoc doc) {
    // (altitude, azimuth clockwise from north, output path) per shot; the document's own north is kept,
    // so the shadows follow the same north as the analysis export
    double[] alt = new double[] { __ALT__ };
    double[] az = new double[] { __AZ__ };
    string[] outs = new string[] { __OUTS__ };
    var view = doc.Views.Find("__VIEW__", false) ?? doc.Views.ActiveView;
    if (view == null) throw new Exception("No viewport to capture");
    var vp = view.ActiveViewport;
    var sun = doc.Lights.Sun;
    bool enabled = sun.Enabled, manual = sun.ManualControl;
    double alt0 = sun.Altitude, az0 = sun.Azimuth;
    var mode0 = vp.DisplayMode;
    var gp = doc.GroundPlane;
    bool gp0 = gp.Enabled;
    var rendered = DisplayModeDescription.FindByName("__MODE__");
    try {
      sun.Enabled = true;
      sun.ManualControl = true;
      if (__GROUND__) gp.Enabled = true;
      if (rendered != null) vp.DisplayMode = rendered;
      for (int i = 0; i < outs.Length; i++) {
        sun.Altitude = alt[i];
        sun.Azimuth = az[i];
        view.Redraw();
        var cap = new ViewCapture { Width = __W__, Height = __H__, ScaleScreenItems = false, DrawAxes = false,
                                    DrawGrid = false, DrawGridAxes = false, TransparentBackground = false };
        using (var bmp = cap.CaptureToBitmap(view)) {
          if (bmp == null) throw new Exception("The viewport capture failed");
          bmp.Save(outs[i], System.Drawing.Imaging.ImageFormat.Png);
        }
      }
    } finally {
      sun.Altitude = alt0; sun.Azimuth = az0; sun.ManualControl = manual; sun.Enabled = enabled;
      gp.Enabled = gp0;
      vp.DisplayMode = mode0;
      view.Redraw();
    }
    return new List<Guid>();
  }
}
'''

TAG_KEYS = ("construction", "room", "room_use", "room_set", "room_heat_c", "room_cool_c", "room_height")

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_SAFE = re.compile(r"[^A-Za-z0-9 _\-.()]")


def _path_literal(path: str) -> str:
    """A path for a C# verbatim string literal (no quotes allowed in it)."""
    p = str(path)
    if '"' in p or "\n" in p:
        raise ValueError("Output paths cannot contain quotes or newlines")
    return p


def safe_label(label: str) -> str:
    s = _SAFE.sub("_", str(label or "result")).strip() or "result"
    return s[:60]


def export_script(guids: list[str], out_path: str) -> str:
    bad = [g for g in guids if not _GUID.match(str(g))]
    if bad:
        raise ValueError(f"Not Rhino object GUIDs: {bad[:3]}")
    ids = ", ".join(json.dumps(str(g)) for g in guids)
    return (_CS_EXPORT.replace("__IDS__", ids).replace("__OUT__", _path_literal(out_path))
            .replace("__ROOT__", RESULT_ROOT))


def draw_script(in_path: str, label: str, tag: str) -> str:
    name = safe_label(label)
    return (_CS_DRAW.replace("__IN__", _path_literal(in_path)).replace("__LAYER__", f"{RESULT_ROOT}::{name}")
            .replace("__TAG__", safe_label(tag)).replace("__NAME__", name))


def sun_views_script(shots: list[tuple[float, float, str]], view: str = "", width: int = 1600, height: int = 1000,
                     mode: str = "Rendered", ground_plane: bool = True) -> str:
    """C# that captures ``view`` with the document sun at each (altitude, azimuth, png path) in turn, in a
    display mode with sun shadows, and restores the sun, ground plane and display mode afterwards."""
    if not shots:
        raise ValueError("No sun positions to capture")
    if not 200 <= int(width) <= 6000 or not 200 <= int(height) <= 6000:
        raise ValueError("width and height must be 200..6000 pixels")
    for name in (view, mode):
        if _SAFE.sub("", name) != name:
            raise ValueError(f"Not a view or display-mode name: {name!r}")
    return (_CS_SUN_VIEWS.replace("__ALT__", ", ".join(f"{float(a):.6f}" for a, _, _ in shots))
            .replace("__AZ__", ", ".join(f"{float(z):.6f}" for _, z, _ in shots))
            .replace("__OUTS__", ", ".join('@"' + _path_literal(p) + '"' for _, _, p in shots))
            .replace("__VIEW__", view).replace("__MODE__", mode).replace("__GROUND__", "true" if ground_plane else "false")
            .replace("__W__", str(int(width))).replace("__H__", str(int(height))))


def clear_script(label: str = "") -> str:
    layer = RESULT_ROOT if not label else f"{RESULT_ROOT}::{safe_label(label)}"
    return _CS_CLEAR.replace("__LAYER__", layer)


def draw_file(cells_m, colors, units_to_m: float, legend: list[tuple[tuple[float, float, float], str]],
              legend_cells: list[tuple[list, tuple[int, int, int]]] | None = None) -> str:
    """Text content for the draw script: quads (model units) with colours, then text dots."""
    import numpy as np
    s = 1.0 / float(units_to_m)
    lines = []
    cells = np.asarray(cells_m, dtype=float) * s
    for quad, col in zip(cells, colors):
        lines.append("Q," + ",".join(f"{v:.6g}" for v in quad.reshape(-1)) + "," + ",".join(str(int(c)) for c in col[:3]))
    for quad, col in (legend_cells or []):
        q = np.asarray(quad, dtype=float) * s
        lines.append("Q," + ",".join(f"{v:.6g}" for v in q.reshape(-1)) + "," + ",".join(str(int(c)) for c in col[:3]))
    for (x, y, z), text in legend:
        clean = str(text).replace("\n", " ").replace("\r", " ")
        lines.append(f"T,{x * s:.6g},{y * s:.6g},{z * s:.6g},{clean}")
    return "\n".join(lines) + "\n"


def tag_script(assignments: dict[str, dict[str, str]], unique_room: str = "") -> str:
    """C# that sets (value) or removes ("") almond:* user text: {guid: {key: value}} with keys from TAG_KEYS.
    Every object is checked before any is changed. ``unique_room``: refuse when another object already carries
    that room name (rooms are grouped by name, so a second room of the same name would merge with the first)."""
    triples = []
    for guid, kv in assignments.items():
        if not _GUID.match(str(guid)):
            raise ValueError(f"Not a Rhino object GUID: {guid}")
        for k, val in kv.items():
            if k not in TAG_KEYS:
                raise ValueError(f"Unknown tag '{k}'. Tags: {', '.join(TAG_KEYS)}")
            val = "" if val is None else str(val)
            if len(val) > 120 or any(ch in val for ch in '"\\\n\r'):
                raise ValueError(f"Tag value for {k} must be plain text up to 120 characters")
            triples += [str(guid), k, val]
    if not triples:
        raise ValueError("Nothing to tag")
    if len(unique_room) > 120:
        raise ValueError("Room names must be up to 120 characters")
    return (_CS_TAG.replace("__TRIPLES__", ", ".join(json.dumps(x) for x in triples))
            .replace("__UNIQUE_ROOM__", json.dumps(str(unique_room))))
