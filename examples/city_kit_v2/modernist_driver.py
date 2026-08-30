"""Almond Modern - city generation v2: modernist district around a transit concourse.

Second-generation city workflow. Where v1 (examples/city_kit) tested five
construction systems with one detail kit, v2 explores MODERNIST social
architecture: alternation and play of volume (slab on pilotis, ziggurat
terraces, a glass cylinder tower, interlocking bars), facade/building
systems (egg-crate brise-soleil, vertical fins, ribbon windows, curtain
walls, PV arrays, wind cowls, plant rooms), and a public spine that fuses
a below-grade METRO STATION, an at-grade BUS INTERCHANGE and a glazed
CONCOURSE HALL, with rooftop terraces and corner shops binding the blocks
to the street.

Phases (run against a live Rhino mm document, bridge on 5000):
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py SUN     # sun to the user's panel + SE perspective + ground
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py M1      # metro level (box, platforms, tracks, train, stairs, escalators)
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py M2      # concourse hall + bus interchange
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py M3      # block A: slab on pilotis, egg-crate, sky garden, drawers
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py M4      # block B: stepped terraces (ziggurat)
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py M5      # block C: cylinder tower on podium
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py M6      # block D: interlocking bars + sky bridge
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py M7      # corner shops, plaza, streets, trees, lamps
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py M8      # materials + roles + guidance + egress
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py ALL     # SUN + M1..M8 in one continuous run (for recording)
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py EXPORT  # per-material GLBs for Blender
  uv run --no-sync python examples/city_kit_v2/modernist_driver.py PAN 1|2 # rendered-view panning frames

Sun matches the user's Rhino Sun panel: North 209.2, azimuth 168.3,
altitude 22.4, intensity 2.22, manual control. ALMOND_DRY=1 dry-runs the
Python geometry (no bridge calls).
"""
import importlib.util, json, math, os, sys, tempfile, uuid

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("RHINO_MCP_STATE_DB", tempfile.mktemp(suffix=".sqlite3"))
spec = importlib.util.spec_from_file_location(
    f"srv_{uuid.uuid4().hex}", os.path.join(REPO, "almond_mcp", "server.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fn = lambda t: getattr(t, "fn", t)
run_script = fn(m.execute_rhino_script)
assign = fn(m.assign_material)

SCRATCH = os.environ.get("ALMOND_MODERN_SCRATCH") or os.path.join(
    tempfile.gettempdir(), "almond_modern")
os.makedirs(SCRATCH, exist_ok=True)
GUIDS_PATH = os.path.join(SCRATCH, "modern_guids.json")
G = json.load(open(GUIDS_PATH)) if os.path.exists(GUIDS_PATH) else {}
PHASE = (sys.argv[1] if len(sys.argv) > 1 else "ALL").upper()
DRY = os.environ.get("ALMOND_DRY") == "1"

def log(msg): print(msg, flush=True)
def fmt(vals): return ",".join(f"{v:.2f}" for v in vals)

CAPTURE = os.environ.get("ALMOND_CAPTURE") == "1"
GEN_FRAMES = os.path.join(SCRATCH, "genframes")
if CAPTURE:
    os.makedirs(GEN_FRAMES, exist_ok=True)
import glob as _glob
_frame_no = len(_glob.glob(os.path.join(GEN_FRAMES, "g*.png"))) if CAPTURE else 0

CS_HEAD = """
using System;
using System.Collections.Generic;
using Rhino;
using Rhino.Geometry;
public class Script {
  static int Layer(RhinoDoc doc, string path) {
    int i = doc.Layers.FindByFullPath(path, -1);
    if (i >= 0) return i;
    string[] parts = path.Split(new[]{"::"}, StringSplitOptions.None);
    string acc = ""; int parent = -1;
    foreach (var p in parts) {
      acc = acc.Length == 0 ? p : acc + "::" + p;
      int f = doc.Layers.FindByFullPath(acc, -1);
      if (f < 0) {
        var lay = new Rhino.DocObjects.Layer { Name = p };
        if (parent >= 0) lay.ParentLayerId = doc.Layers[parent].Id;
        f = doc.Layers.Add(lay);
      }
      parent = f;
    }
    return parent;
  }
"""

SNAP_CS = CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var vc = new Rhino.Display.ViewCapture {
      Width = 1280, Height = 720, ScaleScreenItems = false, DrawAxes = false,
      DrawGrid = false, DrawGridAxes = false, TransparentBackground = false };
    var bmp = vc.CaptureToBitmap(doc.Views.ActiveView);
    if (bmp != null) { bmp.Save(@"OUT"); bmp.Dispose(); }
    return new List<Guid>();
  }
}"""

def snap_frame():
    """One rendered-view timelapse frame of the generation in progress."""
    global _frame_no
    if DRY or not CAPTURE: return
    out = os.path.join(GEN_FRAMES, f"g{_frame_no:05d}.png")
    r = json.loads(run_script(SNAP_CS.replace("OUT", out)))
    if r.get("status") == "success":
        _frame_no += 1

def _run(batch, cs):
    if DRY: return []
    r = json.loads(run_script(cs))
    if r.get("status") != "success":
        log(f"  !! {batch} FAILED: {r.get('message','')[:220]}"); return []
    G[batch] = G.get(batch, []) + r["guids"]
    snap_frame()
    return r["guids"]

def _dry(batch, n):
    G[batch] = G.get(batch, []) + [f"dry-{batch}-{len(G.get(batch, []))+i}" for i in range(n)]

def add_boxes(batch, layer, boxes):
    if DRY: _dry(batch, len(boxes)); return []
    out = []
    for i in range(0, len(boxes), 140):
        data = ";".join(fmt(b) for b in boxes[i:i+140])
        out += _run(batch, CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var ids = new List<Guid>();
    var att = new Rhino.DocObjects.ObjectAttributes { LayerIndex = Layer(doc, "LAYER") };
    foreach (var rec in "DATA".Split(';')) {
      var v = Array.ConvertAll(rec.Split(','), double.Parse);
      var lo = new Point3d(Math.Min(v[0],v[3]), Math.Min(v[1],v[4]), Math.Min(v[2],v[5]));
      var hi = new Point3d(Math.Max(v[0],v[3]), Math.Max(v[1],v[4]), Math.Max(v[2],v[5]));
      ids.Add(doc.Objects.AddBox(new Box(new BoundingBox(lo, hi)), att));
    }
    doc.Views.Redraw();
    return ids;
  }
}""".replace("LAYER", layer).replace("DATA", data))
    return out

def add_obl_boxes(batch, layer, boxes):
    """Oriented boxes: cx, cy, zb, L, W, H, rotZ_deg, pitch_deg.
    Box spans [-L/2..L/2]x[-W/2..W/2]x[0..H] locally; pitch rotates about
    local Y (positive tips the +X end down), then yaw about Z, then the
    center-bottom lands on (cx, cy, zb)."""
    if DRY: _dry(batch, len(boxes)); return []
    out = []
    for i in range(0, len(boxes), 110):
        data = ";".join(fmt(b) for b in boxes[i:i+110])
        out += _run(batch, CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var ids = new List<Guid>();
    var att = new Rhino.DocObjects.ObjectAttributes { LayerIndex = Layer(doc, "LAYER") };
    foreach (var rec in "DATA".Split(';')) {
      var v = Array.ConvertAll(rec.Split(','), double.Parse);
      var box = new Box(Plane.WorldXY, new Interval(-v[3]/2, v[3]/2),
                        new Interval(-v[4]/2, v[4]/2), new Interval(0, v[5]));
      var brep = box.ToBrep();
      var xf = Transform.Translation(v[0], v[1], v[2])
             * Transform.Rotation(RhinoMath.ToRadians(v[6]), Vector3d.ZAxis, Point3d.Origin)
             * Transform.Rotation(RhinoMath.ToRadians(v[7]), Vector3d.YAxis, Point3d.Origin);
      brep.Transform(xf);
      ids.Add(doc.Objects.AddBrep(brep, att));
    }
    doc.Views.Redraw();
    return ids;
  }
}""".replace("LAYER", layer).replace("DATA", data))
    return out

def add_cylinders(batch, layer, cyls):
    if DRY: _dry(batch, len(cyls)); return []
    out = []
    for i in range(0, len(cyls), 100):
        data = ";".join(fmt(c) for c in cyls[i:i+100])
        out += _run(batch, CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var ids = new List<Guid>();
    var att = new Rhino.DocObjects.ObjectAttributes { LayerIndex = Layer(doc, "LAYER") };
    foreach (var rec in "DATA".Split(';')) {
      var v = Array.ConvertAll(rec.Split(','), double.Parse);
      var dir = new Vector3d(v[3],v[4],v[5]); dir.Unitize();
      var cyl = new Cylinder(new Circle(new Plane(new Point3d(v[0],v[1],v[2]), dir), v[7]), v[6]);
      ids.Add(doc.Objects.AddBrep(cyl.ToBrep(true, true), att));
    }
    doc.Views.Redraw();
    return ids;
  }
}""".replace("LAYER", layer).replace("DATA", data))
    return out

def add_texts(batch, layer, texts):
    if DRY: _dry(batch, len(texts)); return []
    data = ";".join(f"{x:.1f},{y:.1f},{z:.1f},{h:.1f},{s}" for x,y,z,h,s in texts)
    return _run(batch, CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var ids = new List<Guid>();
    var att = new Rhino.DocObjects.ObjectAttributes { LayerIndex = Layer(doc, "LAYER") };
    foreach (var rec in "DATA".Split(';')) {
      var v = rec.Split(',');
      var pl = Plane.WorldXY;
      pl.Origin = new Point3d(double.Parse(v[0]), double.Parse(v[1]), double.Parse(v[2]));
      ids.Add(doc.Objects.AddText(v[4], pl, double.Parse(v[3]), "Arial", false, false, att));
    }
    doc.Views.Redraw();
    return ids;
  }
}""".replace("LAYER", layer).replace("DATA", data))

def stamp(guids, kv):
    if DRY: return len(guids)
    total = 0
    sets = "\n      ".join(f'obj.Attributes.SetUserString("{k}", "{v}");' for k, v in kv.items())
    for i in range(0, len(guids), 200):
        arr = ", ".join(f'"{g}"' for g in guids[i:i+200])
        r = json.loads(run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var done = new List<Guid>();
    foreach (string s in new[] { ARR }) {
      var obj = doc.Objects.FindId(new Guid(s));
      if (obj == null) continue;
      SETS
      obj.CommitChanges(); done.Add(obj.Id);
    }
    return done;
  }
}""".replace("ARR", arr).replace("SETS", sets)))
        total += len(r.get("guids", [])) if r.get("status") == "success" else 0
    return total

def save():
    purge_dims()
    json.dump(G, open(GUIDS_PATH, "w"))

def purge_dims():
    """The bridge stamps a LinearDimension per create/assign batch; sweep them.
    Driver-made labels are TextEntity objects, which this leaves alone."""
    if DRY: return
    run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var kill = new List<Guid>();
    foreach (var o in doc.Objects)
      if (o.Geometry is LinearDimension) kill.Add(o.Id);
    foreach (var id in kill) doc.Objects.Delete(id, true);
    doc.Views.Redraw();
    return new List<Guid>();
  }
}""")

# ══════════════ THE MODERNIST KIT ══════════════
MOD = 3000.0

def glass_wall(glass, mullions, x0, x1, y, zb, zt, face="s", module=MOD, skip=None):
    """Full-height storefront glazing along an X-run wall at y, with mullions."""
    d = -1 if face == "s" else 1
    n = int(round((x1 - x0) / module))
    for i in range(n):
        mx = x0 + i * module
        if skip and skip(mx): continue
        glass.append([mx + 90, y + d*20, zb + 120, mx + module - 90, y + d*80, zt - 120])
    for i in range(n + 1):
        mx = x0 + i * module
        mullions.append([mx - 40, y, zb, mx + 40, y + d*110, zt])
    mullions.append([x0, y, zt - 120, x1, y + d*110, zt])
    mullions.append([x0, y, zb, x1, y + d*110, zb + 120])

def glass_wall_y(glass, mullions, y0, y1, x, zb, zt, face="w", module=MOD):
    d = -1 if face == "w" else 1
    n = int(round((y1 - y0) / module))
    for i in range(n):
        my = y0 + i * module
        glass.append([x + d*20, my + 90, zb + 120, x + d*80, my + module - 90, zt - 120])
    for i in range(n + 1):
        my = y0 + i * module
        mullions.append([x, my - 40, zb, x + d*110, my + 40, zt])
    mullions.append([x, y0, zt - 120, x + d*110, y1, zt])
    mullions.append([x, y0, zb, x + d*110, y1, zb + 120])

def ribbon(glass, frames, x0, x1, y, zb, face="n"):
    """Continuous modernist ribbon window: one glass band + slim rails."""
    d = -1 if face == "s" else 1
    glass.append([x0, y + d*20, zb + 900, x1, y + d*70, zb + 2400])
    frames.append([x0, y + d*10, zb + 810, x1, y + d*90, zb + 900])
    frames.append([x0, y + d*10, zb + 2400, x1, y + d*90, zb + 2490])

def ribbon_y(glass, frames, y0, y1, x, zb, face="e"):
    d = -1 if face == "w" else 1
    glass.append([x + d*20, y0, zb + 900, x + d*70, y1, zb + 2400])
    frames.append([x + d*10, y0, zb + 810, x + d*90, y1, zb + 900])
    frames.append([x + d*10, y0, zb + 2400, x + d*90, y1, zb + 2490])

def stair_core(walls, signs, x0, y0, floors, H, door_offset=1200):
    x1, y1 = x0 + 3200, y0 + 6200
    for s in range(floors):
        zb = s * H; zt = zb + H
        d0, d1 = x0 + door_offset, x0 + door_offset + 1000
        walls += [[x0, y0, zb, d0, y0+200, zt], [d1, y0, zb, x1, y0+200, zt],
                  [d0, y0, zb+2100, d1, y0+200, zt],
                  [x0, y1-200, zb, x1, y1, zt],
                  [x0, y0+200, zb, x0+200, y1-200, zt], [x1-200, y0+200, zb, x1, y1-200, zt]]
        signs.append([d0+150, y0-60, zb+2200, d0+650, y0, zb+2400])
    return (x0 + door_offset + 500, y0)

def entrance(canopies, posts, doors, signs, xc, y_face, south=True):
    d = -1 if south else 1
    canopies.append([xc-3000, y_face + d*2500, 3200, xc+3000, y_face, 3450])
    posts.append([xc-2900, y_face + d*2500, 0, 0, 0, 1, 3200, 90])
    posts.append([xc+2900, y_face + d*2500, 0, 0, 0, 1, 3200, 90])
    doors += [[xc-950+i*1000, y_face + d*20, 0, xc-50+i*1000, y_face + d*70, 2400] for i in range(2)]
    signs.append([xc-800, y_face + d*2550, 2600, xc+800, y_face + d*2500, 2950])

def parapet(boxes, x0, y0, x1, y1, z, h=1100, t=200):
    boxes += [[x0, y0, z, x1, y0+t, z+h], [x0, y1-t, z, x1, y1, z+h],
              [x0, y0+t, z, x0+t, y1-t, z+h], [x1-t, y0+t, z, x1, y1-t, z+h]]

def roof_garden(decks, planters, hedges, posts, slats, x0, y0, x1, y1, z):
    t, hh = 500.0, 550.0
    decks.append([x0 + t, y0 + t, z, x1 - t, y1 - t, z + 80])
    planters += [[x0, y0, z, x1, y0 + t, z + hh], [x0, y1 - t, z, x1, y1, z + hh],
                 [x0, y0 + t, z, x0 + t, y1 - t, z + hh], [x1 - t, y0 + t, z, x1, y1 - t, z + hh]]
    hedges += [[x0 + 60, y0 + 60, z + hh, x1 - 60, y0 + t - 60, z + hh + 700],
               [x0 + 60, y1 - t + 60, z + hh, x1 - 60, y1 - 60, z + hh + 700],
               [x0 + 60, y0 + t, z + hh, x0 + t - 60, y1 - t, z + hh + 700],
               [x1 - t + 60, y0 + t, z + hh, x1 - 60, y1 - t, z + hh + 700]]
    px0, px1 = x0 + (x1 - x0) * 0.55, x1 - t - 800
    py0, py1 = y0 + t + 800, y1 - t - 800
    if px1 - px0 > 3000 and py1 - py0 > 3000:
        for (px, py) in ((px0, py0), (px1, py0), (px1, py1), (px0, py1)):
            posts.append([px - 60, py - 60, z, px + 60, py + 60, z + 2600])
        for i in range(int((px1 - px0) / 600)):
            slats.append([px0 + i * 600, py0 - 120, z + 2600, px0 + i * 600 + 120, py1 + 120, z + 2750])

def corner_shop(glass, frames, fascia, signs, awnings, counters, x0, y0, w, d, face="s"):
    """Double-height glazed corner unit: storefront wrap + fascia + tilted awning."""
    x1, y1 = x0 + w, y0 + d
    for (a, b, y, f) in ((x0, x1, y0, "s"), (x0, x1, y1, "n")):
        glass_wall(glass, frames, a, b, y, 150, 3900, face=f, module=w/2 if w <= 6000 else MOD)
    glass_wall_y(glass, frames, y0, y1, x0, 150, 3900, face="w", module=d/2 if d <= 6000 else MOD)
    glass_wall_y(glass, frames, y0, y1, x1, 150, 3900, face="e", module=d/2 if d <= 6000 else MOD)
    fascia.append([x0 - 150, y0 - 150, 3900, x1 + 150, y1 + 150, 4650])
    yf = y0 if face == "s" else y1
    dd = -1 if face == "s" else 1
    signs.append([x0 + w/2 - 1600, yf + dd*160, 4050, x0 + w/2 + 1600, yf + dd*150, 4500])
    awnings.append([x0 + w/2, yf + dd*750, 2900, 1500, 3200, 60, 90 if face == "s" else -90, -18])
    counters.append([x0 + w*0.25, y0 + d*0.35, 0, x0 + w*0.75, y0 + d*0.45, 950])

def pv_array(panels, x0, y0, z, rows, cols, pitch_x=2300, pitch_y=1900):
    """South-facing photovoltaic field: tilted plates on a roof."""
    for r in range(rows):
        for c in range(cols):
            panels.append([x0 + c*pitch_x, y0 + r*pitch_y, z + 150,
                           1400, 2000, 70, 90, -24])   # north edge lifted -> faces south

def street_lamp(posts, heads, x, y):
    posts.append([x, y, 0, 0, 0, 1, 4500, 60])
    heads.append([x-350, y-120, 4350, x+350, y+120, 4520])

def tree(trunks, crowns, x, y):
    trunks.append([x, y, 0, 0, 0, 1, 2800, 150])
    crowns.append([x-1700, y-1700, 2800, x+1700, y+1700, 5800])

def bench(seats, x, y, along_x=True):
    if along_x:
        seats.append([x, y, 0, x + 1800, y + 550, 450])
        seats.append([x, y + 470, 450, x + 1800, y + 550, 900])
    else:
        seats.append([x, y, 0, x + 550, y + 1800, 450])
        seats.append([x, y, 450, x + 80, y + 1800, 900])

# ══════════════ site constants ══════════════
H = 3200.0
CX, CY = 122000.0, 20000.0            # cylinder tower center
SUN_STATE = os.path.join(SCRATCH, "sun_state.json")

def phase_sun():
    log("=== SUN + VIEW: user's sun panel, SE perspective, rendered ground ===")
    if not G.get("g_ground"):
        add_boxes("g_ground", "Modern::Site::Ground",
                  [[-100000, -80000, -380, 260000, 190000, -80]])
    if DRY: return
    r = json.loads(run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var sun = doc.Lights.Sun;
    sun.Enabled = true;
    sun.ManualControlOn = true;
    sun.North = 209.2;
    sun.Azimuth = 168.3;
    sun.Altitude = 22.4;
    try { sun.Intensity = 2.22; } catch (Exception) {}
    doc.Lights.Skylight.Enabled = true;
    var rs = doc.RenderSettings;
    rs.BackgroundStyle = Rhino.Display.BackgroundStyle.Gradient;
    rs.BackgroundColorTop = System.Drawing.Color.FromArgb(96, 148, 210);
    rs.BackgroundColorBottom = System.Drawing.Color.FromArgb(214, 228, 240);
    doc.RenderSettings = rs;
    var v = sun.Vector;
    System.IO.File.WriteAllText(@"SUNSTATE",
      "{\\"vector\\": [" + v.X + ", " + v.Y + ", " + v.Z + "]," +
      "\\"azimuth\\": " + sun.Azimuth + ", \\"altitude\\": " + sun.Altitude +
      ", \\"north\\": " + sun.North + ", \\"intensity\\": 2.22}");
    var view = doc.Views.ActiveView;
    var vp = view.ActiveViewport;
    vp.ChangeToPerspectiveProjection(true, 45);
    vp.SetCameraLocations(new Point3d(75000, 54000, 9000), new Point3d(262000, -112000, 102000));
    vp.Camera35mmLensLength = 45;
    var mode = Rhino.Display.DisplayModeDescription.FindByName("Rendered");
    if (mode != null) vp.DisplayMode = mode;
    view.Redraw();
    return new List<Guid>();
  }
}""".replace("SUNSTATE", SUN_STATE)))
    log(f"sun set: {r.get('status')}; state -> {SUN_STATE}")
    if G.get("g_ground"):
        json.loads(assign(G["g_ground"], "concrete-smooth", structural_role="site_ground"))
    save()

# ══════════════ M1: metro level ══════════════
def phase_m1():
    log("=== M1: METRO LEVEL (station box, island platform, tracks, train) ===")
    g = json.loads(fn(m.get_construction_guidance)(material="Concrete", structure_type="wall", span_m=8.0))
    log(f"  retaining/bearing wall guidance entries: {g.get('total', 0)}")
    MX0, MX1, MY0, MY1 = 30000.0, 110000.0, 49000.0, 59000.0
    walls = [[MX0, MY0, -8500, MX1, MY0+400, -300], [MX0, MY1-400, -8500, MX1, MY1, -300],
             [MX0, MY0+400, -8500, MX0+400, MY1-400, -300],
             [MX1-400, MY0+400, -8500, MX1, MY1-400, -300]]
    beds = [[MX0+400, MY0+400, -7900, MX1-400, 52600, -7600],
            [MX0+400, 55400, -7900, MX1-400, MY1-400, -7600]]
    rails = [[MX0+400, y-60, -7600, MX1-400, y+60, -7380] for y in (50200, 51800, 56200, 57800)]
    platform = [[MX0+400, 52600, -7600, MX1-400, 55400, -6500]]
    strips = [[MX0+400, 52600, -6500, MX1-400, 52900, -6470],
              [MX0+400, 55100, -6500, MX1-400, 55400, -6470]]
    pcols = []
    for px in range(34000, 106001, 7000):
        for py in (53400, 54600):
            pcols.append([px, py, -6500, 0, 0, 1, 6200, 250])
    # concourse deck with three openings over the platform
    OPEN = [(45000, 53000), (71000, 79000), (97000, 105000)]
    deck = [[MX0, MY0, -300, MX1, 52600, 0], [MX0, 55400, -300, MX1, MY1, 0]]
    seams = [MX0] + [v for o in OPEN for v in o] + [MX1]
    for i in range(0, len(seams), 2):
        if seams[i+1] > seams[i]:
            deck.append([seams[i], 52600, -300, seams[i+1], 55400, 0])
    # stairs down at openings 1 and 3 (20 risers of 325, straight flights)
    stairs, srails = [], []
    for (sx, eastward) in ((45500, True), (104500, False)):
        for s in range(20):
            x0 = sx + s*300 if eastward else sx - (s+1)*300
            zt = -s * 325.0
            stairs.append([x0, 52900, zt - 325, x0 + 300, 55100, zt])
        run = 20 * 300
        x_far = sx + run if eastward else sx - run
        srails.append([min(sx, x_far), 52860, -6500, max(sx, x_far), 52900, 1100])
        srails.append([min(sx, x_far), 55100, -6500, max(sx, x_far), 55140, 1100])
    # escalator pair at the central opening (bodies run beneath the deck)
    esc, ebal = [], []
    for ey in (53550, 54450):
        esc.append([77200, ey, -3900, 13400, 850, 1050, 0, 26])
        ebal.append([77200, ey, -2850, 12600, 90, 950, 0, 26])
    # a train berthed on the south track
    tbody, tglass, tdoor = [], [], []
    for car in range(3):
        cx0 = 55000 + car * 15000
        tbody.append([cx0, 49800, -7380, cx0 + 14400, 52200, -4200])
        tglass.append([cx0 + 600, 49740, -6300, cx0 + 13800, 49800, -5000])
        for dx in (2500, 7000, 11500):
            tdoor.append([cx0 + dx, 52140, -7300, cx0 + dx + 1300, 52260, -5000])
    add_boxes("m_walls", "Modern::Metro::Box", walls)
    add_boxes("m_beds", "Modern::Metro::Track", beds)
    add_boxes("m_rails", "Modern::Metro::Track", rails)
    add_boxes("m_platform", "Modern::Metro::Platform", platform)
    add_boxes("m_strips", "Modern::Metro::Platform", strips)
    add_cylinders("m_pcols", "Modern::Metro::Structure", pcols)
    add_boxes("m_deck", "Modern::Metro::Deck", deck)
    add_boxes("m_stairs", "Modern::Metro::Stairs", stairs)
    add_boxes("m_srails", "Modern::Metro::Stairs", srails)
    add_obl_boxes("m_esc", "Modern::Metro::Escalators", esc)
    add_obl_boxes("m_ebal", "Modern::Metro::Escalators", ebal)
    add_boxes("m_tbody", "Modern::Metro::Train", tbody)
    add_boxes("m_tglass", "Modern::Metro::Train", tglass)
    add_boxes("m_tdoor", "Modern::Metro::Train", tdoor)
    save()
    log(f"  metro: {len(pcols)} platform columns, {len(stairs)} treads, 3-car train")

# ══════════════ M2: concourse hall + bus interchange ══════════════
def phase_m2():
    log("=== M2: CONCOURSE HALL + BUS INTERCHANGE ===")
    g = json.loads(fn(m.get_construction_guidance)(material="Steel", structure_type="frame", span_m=8.0))
    log(f"  frame guidance entries: {g.get('total', 0)}")
    HX0, HX1, HY0, HY1 = 40000.0, 110000.0, 47500.0, 60500.0
    paving = [[14000, 46000, -60, 136000, 62000, 0]]
    cols = []
    for px in range(43000, 107001, 8000):
        for py in (51000, 57000):
            cols.append([px, py, 0, 0, 0, 1, 6900, 300])
    roof = [[HX0-2000, HY0-2000, 6900, HX1+2000, HY1+2000, 7500]]
    upstand = [[HX0, HY0-100, 0, HX1, HY0, 600], [HX0, HY1, 0, HX1, HY1+100, 600],
               [HX0-100, HY0, 0, HX0, HY1, 600], [HX1, HY0, 0, HX1+100, HY1, 600]]
    hglass, hmull = [], []
    door_gap = lambda mx: 72500 <= mx < 77500
    glass_wall(hglass, hmull, HX0, HX1, HY0, 600, 6900, face="s", module=2500, skip=door_gap)
    glass_wall(hglass, hmull, HX0, HX1, HY1, 600, 6900, face="n", module=2500, skip=door_gap)
    glass_wall_y(hglass, hmull, HY0, HY1, HX0, 600, 6900, face="w", module=2600)
    glass_wall_y(hglass, hmull, HY0, HY1, HX1, 600, 6900, face="e", module=2600)
    fins = [[fx-70, HY0-800, 900, fx+70, HY0-100, 6900]
            for fx in range(int(HX0), int(HX1)+1, 2500)]
    sky_c, sky_g = [], []
    for (ox0, ox1) in ((45000, 53000), (71000, 79000), (97000, 105000)):
        sky_c.append([ox0-300, 52300, 7500, ox1+300, 55700, 7800])
        sky_g.append([ox0-100, 52500, 7800, ox1+100, 55500, 8600])
    gates = [[66000+i*1400, 53200, 0, 66000+i*1400+900, 55800, 1200] for i in range(5)]
    kiosks = [[58000, 49000, 0, 62000, 51500, 2700], [88000, 56500, 0, 92000, 59000, 2700]]
    totems = [[tx, 54600, 0, tx+300, 54900, 3400] for tx in (44000, 62000, 82000, 102000)]
    seats = []
    for bx in (48000, 60000, 84000, 96000):
        bench(seats, bx, 58800); bench(seats, bx, 48800)
    pv = []; pv_array(pv, 44000, 48800, 7500, 5, 8)
    cowls = [[cxx, 57500, 7500, 0, 0, 1, 1800, 380] for cxx in (92000, 96000, 100000, 104000)]
    caps = [[cxx-550, 56950, 9250, cxx+550, 58050, 9500] for cxx in (92000, 96000, 100000, 104000)]
    plant = [[100000, 48500, 7500, 107000, 52500, 10000]]
    louv = [[100000, 48440, 7800+i*400, 107000, 48500, 8050+i*400] for i in range(5)]
    ecan, epost, edoor, esign = [], [], [], []
    entrance(ecan, epost, edoor, esign, 75000, HY0, south=True)
    entrance(ecan, epost, edoor, esign, 75000, HY1, south=False)
    add_boxes("h_paving", "Modern::Concourse::Paving", paving)
    add_cylinders("h_cols", "Modern::Concourse::Structure", cols)
    add_boxes("h_roof", "Modern::Concourse::Roof", roof)
    add_boxes("h_upstand", "Modern::Concourse::Facade", upstand)
    add_boxes("h_glass", "Modern::Concourse::Facade", hglass)
    add_boxes("h_mull", "Modern::Concourse::Facade", hmull)
    add_boxes("h_fins", "Modern::Concourse::Shading", fins)
    add_boxes("h_skyc", "Modern::Concourse::Skylights", sky_c)
    add_boxes("h_skyg", "Modern::Concourse::Skylights", sky_g)
    add_boxes("h_gates", "Modern::Concourse::Interior", gates)
    add_boxes("h_kiosks", "Modern::Concourse::Interior", kiosks)
    add_boxes("h_totems", "Modern::Concourse::Interior", totems)
    add_boxes("h_seats", "Modern::Concourse::Interior", seats)
    add_obl_boxes("h_pv", "Modern::Concourse::Climate", pv)
    add_cylinders("h_cowls", "Modern::Concourse::Climate", cowls)
    add_boxes("h_caps", "Modern::Concourse::Climate", caps)
    add_boxes("h_plant", "Modern::Concourse::Climate", plant)
    add_boxes("h_louv", "Modern::Concourse::Climate", louv)
    add_boxes("h_ecan", "Modern::Concourse::Entrance", ecan)
    add_cylinders("h_epost", "Modern::Concourse::Entrance", epost)
    add_boxes("h_edoor", "Modern::Concourse::Entrance", edoor)
    add_boxes("h_esign", "Modern::Concourse::Entrance", esign)
    # bus interchange west of the hall
    basphalt = [[14000, 46000, -70, 38000, 62000, -10]]
    island = [[15000, 52000, -10, 37000, 56000, 150]]
    bcan = [[15000, 52000, 3400, 37000, 56000, 3700]]
    bcols = [[bx2, by2, 150, 0, 0, 1, 3250, 150]
             for bx2 in range(16000, 36001, 5000) for by2 in (53000, 55000)]
    bglass = [[17000+i*5200, 53950, 300, 19500+i*5200, 54050, 2400] for i in range(4)]
    bseats = []
    for i in range(4):
        bench(bseats, 17300+i*5200, 54300)
    bstripes = [[16500+i*3800, 48200, 2, 4200, 250, 12, 32, 0]  # saw-tooth bay markings
                for i in range(6)]
    bsignp = [[bx3, 51600, 150, 0, 0, 1, 2800, 40] for bx3 in (17000, 22200, 27400, 32600)]
    bsignh = [[bx3-350, 51500, 2950, bx3+350, 51700, 3450] for bx3 in (17000, 22200, 27400, 32600)]
    bus_body, bus_glass, bus_wheel = [], [], []
    for bx4 in (16500, 29500):
        bus_body.append([bx4, 47500, 350, bx4+11800, 50050, 3350])
        bus_glass.append([bx4+500, 47440, 1500, bx4+11300, 47500, 2900])
        bus_glass.append([bx4+500, 50050, 1500, bx4+11300, 50110, 2900])
        for wx in (bx4+2200, bx4+9400):
            for wy in (47900, 49650):
                bus_wheel.append([wx, wy, 500, 0, 1, 0, 400, 480])
    add_boxes("b_asphalt", "Modern::Bus::Lanes", basphalt)
    add_boxes("b_island", "Modern::Bus::Island", island)
    add_boxes("b_canopy", "Modern::Bus::Canopy", bcan)
    add_cylinders("b_cols", "Modern::Bus::Canopy", bcols)
    add_boxes("b_glass", "Modern::Bus::Shelter", bglass)
    add_boxes("b_seats", "Modern::Bus::Shelter", bseats)
    add_obl_boxes("b_stripes", "Modern::Bus::Markings", bstripes)
    add_cylinders("b_signp", "Modern::Bus::Signs", bsignp)
    add_boxes("b_signh", "Modern::Bus::Signs", bsignh)
    add_boxes("b_body", "Modern::Bus::Vehicles", bus_body)
    add_boxes("b_bglass", "Modern::Bus::Vehicles", bus_glass)
    add_cylinders("b_wheel", "Modern::Bus::Vehicles", bus_wheel)
    save()
    log(f"  hall: {len(cols)} pilotis, {len(hglass)} glass panels, {len(pv)} PV panels; "
        f"bus: {len(bcols)} canopy columns, 2 buses")

# ══════════════ M3: block A - slab on pilotis ══════════════
def phase_m3():
    log("=== M3: BLOCK A - SLAB ON PILOTIS (egg-crate, sky garden, drawers) ===")
    g = json.loads(fn(m.get_construction_guidance)(material="Concrete", structure_type="shell", span_m=6.0))
    log(f"  flat-plate guidance entries: {g.get('total', 0)}")
    AX0, AX1, AY0, AY1 = 8000.0, 62000.0, 80000.0, 95000.0
    HRES = 3000.0
    pilotis = [[px, py, 0, 0, 0, 1, 6000, 450]
               for px in range(int(AX0)+2000, int(AX1)-1999, 6000) for py in (83000, 92000)]
    slabs = [[AX0, AY0, 5700, AX1, AY1, 6000]]
    for f in range(9):
        zb = 6000 + f * HRES
        y0 = AY0 if f < 7 else 85000.0
        slabs.append([AX0, y0, zb + HRES - 200, AX1, AY1, zb + HRES])
    void = lambda mx, zb: 30000 <= mx < 42000 and 15000 <= zb < 21000
    shelf, fins_a, aglass = [], [], []
    for f in range(7):
        zb = 6000 + f * HRES
        shelf.append([AX0, 79200, zb + 2750, AX1, 80100, zb + 2950])
        for i in range(int((AX1 - AX0) / MOD) + 1):
            fx = AX0 + i * MOD
            if void(fx - 1, zb) and void(fx - MOD + 1, zb): continue
            fins_a.append([fx - 70, 79200, zb, fx + 70, 80100, zb + 3000])
        for i in range(int((AX1 - AX0) / MOD)):
            mx = AX0 + i * MOD
            if void(mx, zb): continue
            aglass.append([mx + 150, 80550, zb + 150, mx + MOD - 150, 80630, zb + 2800])
    setg, setm = [], []
    for f in (7, 8):
        zb = 6000 + f * HRES
        glass_wall(setg, setm, AX0 + 300, AX1 - 300, 85000, zb + 150, zb + 2800, face="s", module=2980)
    nglass, nframes = [], []
    for f in range(9):
        zb = 6000 + f * HRES
        ribbon(nglass, nframes, AX0 + 300, AX1 - 300, AY1, zb, face="n")
    endw = [[AX0, AY0, 6000, AX0+300, AY1, 27000], [AX1-300, AY0, 6000, AX1, AY1, 27000],
            [AX0, 85000, 27000, AX0+300, AY1, 33000], [AX1-300, 85000, 27000, AX1, AY1, 33000]]
    # sky garden: two-storey void with rail + potted trees
    vrail = [[30000, 79950, 15000, 42000, 80010, 16100]]
    vpots = [[31500+i*3000, 81000, 15000, 32700+i*3000, 82200, 15550] for i in range(4)]
    vtrunk = [[32100+i*3000, 81600, 15550, 0, 0, 1, 1600, 90] for i in range(4)]
    vcrown = [[31300+i*3000, 80800, 17150, 32900+i*3000, 82400, 18500] for i in range(4)]
    # drawer volumes cantilevering from the south face
    drawers = [[14000, 78000, 12000, 20000, 80000, 14700],
               [48000, 78000, 18000, 54000, 80000, 20700],
               [26000, 78000, 24000, 32000, 80000, 26700]]
    dglass = [[b[0]+200, b[1]+80, b[2]+250, b[3]-200, b[1]+160, b[5]-250] for b in drawers]
    # setback terrace at level 7 + roof
    tdeck = [[AX0+300, AY0+300, 27000, AX1-300, 84700, 27080]]
    tplant = [[AX0+300, AY0, 27000, AX1-300, AY0+500, 27550]]
    thedge = [[AX0+400, AY0+80, 27550, AX1-400, AY0+430, 28250]]
    gd, gp, gh, gpost, gslat = [], [], [], [], []
    roof_garden(gd, gp, gh, gpost, gslat, 10000, 85500, 40000, 94500, 33000)
    pav = [[44000, 87000, 33000, 52000, 93000, 33150]]
    pavg, pavm = [], []
    glass_wall(pavg, pavm, 44500, 51500, 87500, 33150, 35700, face="s", module=2333)
    pavroof = [[43500, 86500, 35700, 52500, 93500, 36000]]
    apar = []; parapet(apar, AX0, 85000, AX1, AY1, 33000)
    bulk = [[18000, 84000, 33000, 21200, 90200, 34800], [44000, 84000, 33000, 47200, 90200, 34800],
            [30600, 86000, 0, 33800, 92000, 34500]]
    core_w, core_s = [], []
    stair_core(core_w, core_s, 18000, 84000, 11, HRES)
    stair_core(core_w, core_s, 44000, 84000, 11, HRES)
    aecan, aepost, aedoor, aesign = [], [], [], []
    entrance(aecan, aepost, aedoor, aesign, 32000, AY1, south=False)
    sg, sf, sfa, ss, saw, sco = [], [], [], [], [], []
    corner_shop(sg, sf, sfa, ss, saw, sco, 53000, 81000, 8000, 13000, face="s")
    add_cylinders("a_pilotis", "Modern::BlockA::Structure", pilotis)
    add_boxes("a_slabs", "Modern::BlockA::Structure", slabs)
    add_boxes("a_shelf", "Modern::BlockA::Shading", shelf)
    add_boxes("a_fins", "Modern::BlockA::Shading", fins_a)
    add_boxes("a_glass", "Modern::BlockA::Facade", aglass)
    add_boxes("a_setg", "Modern::BlockA::Facade", setg)
    add_boxes("a_setm", "Modern::BlockA::Facade", setm)
    add_boxes("a_nglass", "Modern::BlockA::Facade", nglass)
    add_boxes("a_nframes", "Modern::BlockA::Facade", nframes)
    add_boxes("a_endw", "Modern::BlockA::Walls", endw)
    add_boxes("a_vrail", "Modern::BlockA::SkyGarden", vrail)
    add_boxes("a_vpots", "Modern::BlockA::SkyGarden", vpots)
    add_cylinders("a_vtrunk", "Modern::BlockA::SkyGarden", vtrunk)
    add_boxes("a_vcrown", "Modern::BlockA::SkyGarden", vcrown)
    add_boxes("a_drawers", "Modern::BlockA::Volumes", drawers)
    add_boxes("a_dglass", "Modern::BlockA::Volumes", dglass)
    add_boxes("a_tdeck", "Modern::BlockA::Terrace", tdeck)
    add_boxes("a_tplant", "Modern::BlockA::Terrace", tplant)
    add_boxes("a_thedge", "Modern::BlockA::Terrace", thedge)
    add_boxes("a_rgdeck", "Modern::BlockA::Roof", gd)
    add_boxes("a_rgplant", "Modern::BlockA::Roof", gp)
    add_boxes("a_rghedge", "Modern::BlockA::Roof", gh)
    add_boxes("a_rgpost", "Modern::BlockA::Roof", gpost)
    add_boxes("a_rgslat", "Modern::BlockA::Roof", gslat)
    add_boxes("a_pav", "Modern::BlockA::Roof", pav)
    add_boxes("a_pavg", "Modern::BlockA::Roof", pavg)
    add_boxes("a_pavm", "Modern::BlockA::Roof", pavm)
    add_boxes("a_pavroof", "Modern::BlockA::Roof", pavroof)
    add_boxes("a_par", "Modern::BlockA::Roof", apar)
    add_boxes("a_bulk", "Modern::BlockA::Roof", bulk)
    add_boxes("a_core", "Modern::BlockA::Cores", core_w)
    add_boxes("a_coresign", "Modern::BlockA::Wayfinding", core_s)
    add_boxes("a_ecan", "Modern::BlockA::Entrance", aecan)
    add_cylinders("a_epost", "Modern::BlockA::Entrance", aepost)
    add_boxes("a_edoor", "Modern::BlockA::Entrance", aedoor)
    add_boxes("a_esign", "Modern::BlockA::Entrance", aesign)
    add_boxes("a_shopg", "Modern::BlockA::Shop", sg)
    add_boxes("a_shopf", "Modern::BlockA::Shop", sf)
    add_boxes("a_shopfa", "Modern::BlockA::Shop", sfa)
    add_boxes("a_shops", "Modern::BlockA::Shop", ss)
    add_obl_boxes("a_shopaw", "Modern::BlockA::Shop", saw)
    add_boxes("a_shopco", "Modern::BlockA::Shop", sco)
    save()
    log(f"  block A: {len(pilotis)} pilotis, {len(fins_a)} egg-crate fins, "
        f"3 drawer volumes, sky garden void, roof pavilion")

# ══════════════ M4: block B - stepped terraces ══════════════
def phase_m4():
    log("=== M4: BLOCK B - STEPPED TERRACES (ziggurat) ===")
    g = json.loads(fn(m.get_construction_guidance)(material="Concrete", structure_type="frame", span_m=6.0))
    log(f"  concrete frame guidance entries: {g.get('total', 0)}")
    BX0, BX1, BY1 = 84000.0, 142000.0, 104000.0
    STEP = 4800.0
    cols, slabs, sglass, smull, walls = [], [], [], [], []
    tdeck, tplant, thedge, trail, tdiv = [], [], [], [], []
    nglass, nframes = [], []
    for lv in range(5):
        y0 = 80000.0 + lv * STEP
        zb = lv * H
        for px in range(int(BX0)+2000, int(BX1)-1999, 7000):
            py = y0 + 2000
            while py <= BY1 - 1500:
                cols.append([px-150, py-150, zb, px+150, py+150, zb+3000])
                py += 6000
        slabs.append([BX0, y0 - 1500, zb + 3000, BX1, BY1, zb + 3200])
        glass_wall(sglass, smull, BX0 + 300, BX1 - 300, y0, zb + 150, zb + 3000,
                   face="s", module=2870)
        walls += [[BX0, y0 - 1500, zb, BX0+300, BY1, zb + 3200],
                  [BX1-300, y0 - 1500, zb, BX1, BY1, zb + 3200]]
        ribbon(nglass, nframes, BX0 + 300, BX1 - 300, BY1, zb, face="n")
        if lv >= 1:
            fy = y0 - 6300
            tdeck.append([BX0+300, fy + 200, zb, BX1-300, y0 - 100, zb + 80])
            tplant.append([BX0+300, fy + 100, zb, BX1-300, fy + 600, zb + 550])
            thedge.append([BX0+400, fy + 180, zb + 550, BX1-400, fy + 520, zb + 1250])
            trail.append([BX0+300, fy, zb, BX1-300, fy + 60, zb + 1150])
            for dx in (98500, 113000, 127500):
                tdiv.append([dx-60, fy + 150, zb, dx+60, y0 - 400, zb + 1800])
    roofz = 5 * H
    pergola_p = [[124000+px, 100000+py, roofz, 124000+px+120, 100000+py+120, roofz+2600]
                 for px in (0, 8000) for py in (0, 3000)]
    pergola_s = [[124000 + i*600, 99880, roofz+2600, 124000 + i*600 + 120, 103120, roofz+2750]
                 for i in range(14)]
    bpv = []; pv_array(bpv, 86000, 100200, roofz, 2, 8)
    bpar = []; parapet(bpar, BX0, 99200 - 1500, BX1, BY1, roofz)
    core_w, core_s = [], []
    stair_core(core_w, core_s, 95000, 97300, 5, H)
    stair_core(core_w, core_s, 120000, 97300, 5, H)
    becan, bepost, bedoor, besign = [], [], [], []
    for ex in (92000, 113000, 134000):
        entrance(becan, bepost, bedoor, besign, ex, BY1, south=False)
    sg, sf, sfa, ss, saw, sco = [], [], [], [], [], []
    corner_shop(sg, sf, sfa, ss, saw, sco, 84300, 80300, 8000, 8000, face="s")
    add_boxes("bb_cols", "Modern::BlockB::Structure", cols)
    add_boxes("bb_slabs", "Modern::BlockB::Structure", slabs)
    add_boxes("bb_sglass", "Modern::BlockB::Facade", sglass)
    add_boxes("bb_smull", "Modern::BlockB::Facade", smull)
    add_boxes("bb_walls", "Modern::BlockB::Walls", walls)
    add_boxes("bb_nglass", "Modern::BlockB::Facade", nglass)
    add_boxes("bb_nframes", "Modern::BlockB::Facade", nframes)
    add_boxes("bb_tdeck", "Modern::BlockB::Terraces", tdeck)
    add_boxes("bb_tplant", "Modern::BlockB::Terraces", tplant)
    add_boxes("bb_thedge", "Modern::BlockB::Terraces", thedge)
    add_boxes("bb_trail", "Modern::BlockB::Terraces", trail)
    add_boxes("bb_tdiv", "Modern::BlockB::Terraces", tdiv)
    add_boxes("bb_perp", "Modern::BlockB::Roof", pergola_p)
    add_boxes("bb_pers", "Modern::BlockB::Roof", pergola_s)
    add_obl_boxes("bb_pv", "Modern::BlockB::Climate", bpv)
    add_boxes("bb_par", "Modern::BlockB::Roof", bpar)
    add_boxes("bb_core", "Modern::BlockB::Cores", core_w)
    add_boxes("bb_coresign", "Modern::BlockB::Wayfinding", core_s)
    add_boxes("bb_ecan", "Modern::BlockB::Entrance", becan)
    add_cylinders("bb_epost", "Modern::BlockB::Entrance", bepost)
    add_boxes("bb_edoor", "Modern::BlockB::Entrance", bedoor)
    add_boxes("bb_esign", "Modern::BlockB::Entrance", besign)
    add_boxes("bb_shopg", "Modern::BlockB::Shop", sg)
    add_boxes("bb_shopf", "Modern::BlockB::Shop", sf)
    add_boxes("bb_shopfa", "Modern::BlockB::Shop", sfa)
    add_boxes("bb_shops", "Modern::BlockB::Shop", ss)
    add_obl_boxes("bb_shopaw", "Modern::BlockB::Shop", saw)
    add_boxes("bb_shopco", "Modern::BlockB::Shop", sco)
    save()
    log(f"  block B: 5 stepped levels, {len(tdeck)} terrace decks, {len(bpv)} PV panels")

# ══════════════ M5: block C - cylinder tower on podium ══════════════
def phase_m5():
    log("=== M5: BLOCK C - CYLINDER TOWER (drum floors, radial fins, sky deck) ===")
    g = json.loads(fn(m.get_construction_guidance)(material="Steel", structure_type="highrise", span_m=9.0))
    log(f"  high-rise guidance entries: {g.get('total', 0)}")
    PX0, PY0, PX1, PY1 = 106000.0, 6000.0, 138000.0, 34000.0
    HPOD = 4500.0
    pcols, pslabs = [], []
    for s in range(2):
        zb = s * HPOD
        for px in range(108000, 136001, 7000):
            for py in range(8000, 32001, 8000):
                pcols.append([px-200, py-200, zb, px+200, py+200, zb+HPOD])
        pslabs.append([PX0, PY0, zb+HPOD-200, PX1, PY1, zb+HPOD])
    pglass, pmull = [], []
    glass_wall(pglass, pmull, PX0+300, PX1-300, PY0, 150, 4300, face="s", module=3140)
    glass_wall(pglass, pmull, PX0+300, PX1-300, PY1, 150, 4300, face="n", module=3140)
    glass_wall_y(pglass, pmull, PY0+300, PY1-300, PX0, 150, 4300, face="w", module=3050)
    glass_wall_y(pglass, pmull, PY0+300, PY1-300, PX1, 150, 4300, face="e", module=3050)
    gd, gp, gh, gpost, gslat = [], [], [], [], []
    roof_garden(gd, gp, gh, gpost, gslat, PX0+500, PY0+500, 111500, PY1-500, 2*HPOD)
    roof_garden(gd, gp, gh, gpost, gslat, 132500, PY0+500, PX1-500, PY1-500, 2*HPOD)
    ppar = []; parapet(ppar, PX0, PY0, PX1, PY1, 2*HPOD)
    core = [[CX, CY, 0, 0, 0, 1, 51800, 3000]]
    tcols = []
    for k in range(12):
        th = math.radians(k * 30)
        tcols.append([CX + 8200*math.cos(th), CY + 8200*math.sin(th), 9000, 0, 0, 1, 41600, 220])
    tslabs = [[CX, CY, 8600, 0, 0, 1, 400, 9800]]
    drums = []
    SKY = (6, 7)                       # two open-air sky-deck storeys
    for i in range(13):
        zb = 9000.0 + i * H
        tslabs.append([CX, CY, zb + 2950, 0, 0, 1, 250, 9300])
        if i not in SKY:
            drums.append([CX, CY, zb, 0, 0, 1, 2950, 8700])
    fins_c = []
    for k in range(20):
        th = k * 18.0
        fins_c.append([CX + 9750*math.cos(math.radians(th)),
                       CY + 9750*math.sin(math.radians(th)), 9000, 900, 140, 41600, th, 0])
    ring_r, seg = 9221.0, 24
    crown, skyrail = [], []
    for k in range(seg):
        th = k * 360.0 / seg
        px = CX + ring_r*math.cos(math.radians(th)); py = CY + ring_r*math.sin(math.radians(th))
        crown.append([px, py, 50600, 2450, 150, 1100, th + 90, 0])
        for i in SKY:
            skyrail.append([px, py, 9000.0 + i * H, 2450, 80, 1100, th + 90, 0])
    skyplant, skyhedge = [], []
    for k in range(8):
        th = k * 45.0
        px = CX + 7600*math.cos(math.radians(th)); py = CY + 7600*math.sin(math.radians(th))
        skyplant.append([px, py, 9000.0 + SKY[0]*H, 2400, 800, 500, th + 90, 0])
        skyhedge.append([px, py, 9000.0 + SKY[0]*H + 500, 2250, 650, 700, th + 90, 0])
    troof = [[CX, CY, 50600, 0, 0, 1, 80, 8700]]
    tcowls = []
    for k in range(4):
        th = math.radians(45 + k * 90)
        tcowls.append([CX + 5000*math.cos(th), CY + 5000*math.sin(th), 50680, 0, 0, 1, 2000, 350])
    tplant = [[CX, CY, 50680, 0, 0, 1, 1800, 1500]]
    core_w, core_s = [], []
    stair_core(core_w, core_s, 112000, 22000, 2, HPOD)
    cecan, cepost, cedoor, cesign = [], [], [], []
    entrance(cecan, cepost, cedoor, cesign, 122000, PY0, south=True)
    sg1, sf1, sfa1, ss1, saw1, sco1 = [], [], [], [], [], []
    corner_shop(sg1, sf1, sfa1, ss1, saw1, sco1, 107000, 7000, 8000, 6000, face="s")
    sg2, sf2, sfa2, ss2, saw2, sco2 = [], [], [], [], [], []
    corner_shop(sg2, sf2, sfa2, ss2, saw2, sco2, 129000, 27000, 8000, 6000, face="n")
    add_boxes("c_pcols", "Modern::BlockC::Podium", pcols)
    add_boxes("c_pslabs", "Modern::BlockC::Podium", pslabs)
    add_boxes("c_pglass", "Modern::BlockC::Podium", pglass)
    add_boxes("c_pmull", "Modern::BlockC::Podium", pmull)
    add_boxes("c_rgdeck", "Modern::BlockC::PodiumRoof", gd)
    add_boxes("c_rgplant", "Modern::BlockC::PodiumRoof", gp)
    add_boxes("c_rghedge", "Modern::BlockC::PodiumRoof", gh)
    add_boxes("c_rgpost", "Modern::BlockC::PodiumRoof", gpost)
    add_boxes("c_rgslat", "Modern::BlockC::PodiumRoof", gslat)
    add_boxes("c_ppar", "Modern::BlockC::PodiumRoof", ppar)
    add_cylinders("c_core", "Modern::BlockC::Core", core)
    add_cylinders("c_tcols", "Modern::BlockC::Structure", tcols)
    add_cylinders("c_tslabs", "Modern::BlockC::Structure", tslabs)
    add_cylinders("c_drums", "Modern::BlockC::Facade", drums)
    add_obl_boxes("c_fins", "Modern::BlockC::Shading", fins_c)
    add_obl_boxes("c_crown", "Modern::BlockC::Roof", crown)
    add_obl_boxes("c_skyrail", "Modern::BlockC::SkyDeck", skyrail)
    add_obl_boxes("c_skyplant", "Modern::BlockC::SkyDeck", skyplant)
    add_obl_boxes("c_skyhedge", "Modern::BlockC::SkyDeck", skyhedge)
    add_cylinders("c_troof", "Modern::BlockC::Roof", troof)
    add_cylinders("c_tcowls", "Modern::BlockC::Climate", tcowls)
    add_cylinders("c_tplant", "Modern::BlockC::Climate", tplant)
    add_boxes("c_corew", "Modern::BlockC::Cores", core_w)
    add_boxes("c_coresign", "Modern::BlockC::Wayfinding", core_s)
    add_boxes("c_ecan", "Modern::BlockC::Entrance", cecan)
    add_cylinders("c_epost", "Modern::BlockC::Entrance", cepost)
    add_boxes("c_edoor", "Modern::BlockC::Entrance", cedoor)
    add_boxes("c_esign", "Modern::BlockC::Entrance", cesign)
    for tag, lists in (("1", (sg1, sf1, sfa1, ss1, saw1, sco1)), ("2", (sg2, sf2, sfa2, ss2, saw2, sco2))):
        add_boxes(f"c_shopg{tag}", "Modern::BlockC::Shops", lists[0])
        add_boxes(f"c_shopf{tag}", "Modern::BlockC::Shops", lists[1])
        add_boxes(f"c_shopfa{tag}", "Modern::BlockC::Shops", lists[2])
        add_boxes(f"c_shops{tag}", "Modern::BlockC::Shops", lists[3])
        add_obl_boxes(f"c_shopaw{tag}", "Modern::BlockC::Shops", lists[4])
        add_boxes(f"c_shopco{tag}", "Modern::BlockC::Shops", lists[5])
    save()
    log(f"  block C: 13 drum floors, {len(fins_c)} radial fins, 2-storey sky deck, "
        f"podium roof gardens, 2 corner shops")

# ══════════════ M6: block D - interlocking bars + sky bridge ══════════════
def phase_m6():
    log("=== M6: BLOCK D - INTERLOCKING BARS + SKY BRIDGE ===")
    g = json.loads(fn(m.get_construction_guidance)(material="Concrete", structure_type="frame", span_m=6.5))
    log(f"  frame guidance entries: {g.get('total', 0)}")
    # bar 1: low long east-west bar
    B1X0, B1X1, B1Y0, B1Y1 = 8000.0, 60000.0, 8000.0, 21000.0
    # bar 2: taller north-south bar sliding through it
    B2X0, B2X1, B2Y0, B2Y1 = 40000.0, 56000.0, 8000.0, 35000.0
    cols, slabs = [], []
    for f in range(5):
        zb = f * H
        for px in range(10000, 55501, 6500):
            for py in (10000, 14500, 19000):
                cols.append([px-150, py-150, zb, px+150, py+150, zb+3000])
        slabs.append([B1X0, B1Y0, zb+3000, B1X1, B1Y1, zb+3200])
    for f in range(8):
        zb = f * H
        for px in (42000, 48500, 55000):
            for py in (9500, 15500, 21500, 27500, 33500):
                if f < 5 and py < 21000: continue
                cols.append([px-150, py-150, zb, px+150, py+150, zb+3000])
        slabs.append([B2X0, B2Y0, zb+3000, B2X1, B2Y1, zb+3200])
    shelf, d1glass, d1mull = [], [], []
    for f in range(5):
        zb = f * H
        shelf.append([B1X0, 7300, zb + 2750, B1X1, 8100, zb + 2950])
        glass_wall(d1glass, d1mull, B1X0 + 300, B1X1 - 300, B1Y0, zb + 150, zb + 3000,
                   face="s", module=3220)
    for f in range(5, 8):
        zb = f * H
        shelf.append([B2X0, 7300, zb + 2750, B2X1, 8100, zb + 2950])
        glass_wall(d1glass, d1mull, B2X0 + 300, B2X1 - 300, B2Y0, zb + 150, zb + 3000,
                   face="s", module=3060)
    fins_d = [[39300, fy-70, 0, 40100, fy+70, 25600]
              for fy in range(11000, 33001, 3000)]
    wribbon_g, wribbon_f = [], []
    for f in range(8):
        zb = f * H
        ribbon_y(wribbon_g, wribbon_f, B2Y0 + 300, B2Y1 - 300, B2X0, zb, face="w")
        ribbon_y(wribbon_g, wribbon_f, B2Y0 + 300, B2Y1 - 300, B2X1, zb, face="e")
    nribbon_g, nribbon_f = [], []
    for f in range(5):
        zb = f * H
        ribbon(nribbon_g, nribbon_f, B1X0 + 300, 39700, B1Y1, zb, face="n")
    for f in range(8):
        zb = f * H
        ribbon(nribbon_g, nribbon_f, B2X0 + 300, B2X1 - 300, B2Y1, zb, face="n")
    endw = [[B1X0, B1Y0, 4800, B1X0+300, B1Y1, 16000],
            [B1X1-300, B1Y0, 0, B1X1, B1Y1, 16000]]
    gd, gp, gh, gpost, gslat = [], [], [], [], []
    roof_garden(gd, gp, gh, gpost, gslat, 10000, 8500, 38000, 20500, 5*H)
    d1deck = [[56300, 8300, 5*H, 59700, 20700, 5*H+80]]
    d2pv = []; pv_array(d2pv, 41500, 9500, 8*H, 5, 3, pitch_y=2100)
    d2par = []; parapet(d2par, B2X0, B2Y0, B2X1, B2Y1, 8*H)
    d2plant = [[43000, 29000, 8*H, 47500, 33000, 8*H+2200]]
    core_w, core_s = [], []
    stair_core(core_w, core_s, 24000, 11000, 5, H)
    stair_core(core_w, core_s, 46000, 26000, 8, H)
    # sky bridge north to the concourse spine + landing pavilion with stairs
    bfloor = [[46000, 35000, 6400, 49600, 46200, 6600]]
    bglass = [[46000, 35000, 6600, 46080, 46200, 8800], [49520, 35000, 6600, 49600, 46200, 8800]]
    broof = [[45800, 35000, 8800, 49800, 46200, 9000]]
    bcols = [[46800, 40600, 0, 0, 0, 1, 6400, 250], [48800, 40600, 0, 0, 0, 1, 6400, 250]]
    lpav_g, lpav_m = [], []
    glass_wall(lpav_g, lpav_m, 46000, 49600, 49200, 150, 8800, face="n", module=1800)
    glass_wall_y(lpav_g, lpav_m, 46200, 49200, 46000, 150, 8800, face="w", module=1500)
    glass_wall_y(lpav_g, lpav_m, 46200, 49200, 49600, 150, 8800, face="e", module=1500)
    lroof = [[45800, 46000, 8800, 49800, 49400, 9000]]
    lsteps = []
    for s in range(16):
        zt = 6400.0 - s * 400
        lsteps.append([46300, 46400 + s * 165, zt - 400, 49300, 46400 + (s+1) * 165, zt])
    decan, depost, dedoor, design = [], [], [], []
    entrance(decan, depost, dedoor, design, 30000, B1Y0, south=True)
    sg, sf, sfa, ss, saw, sco = [], [], [], [], [], []
    corner_shop(sg, sf, sfa, ss, saw, sco, 8500, 8300, 7500, 6500, face="s")
    add_boxes("d_cols", "Modern::BlockD::Structure", cols)
    add_boxes("d_slabs", "Modern::BlockD::Structure", slabs)
    add_boxes("d_shelf", "Modern::BlockD::Shading", shelf)
    add_boxes("d_fins", "Modern::BlockD::Shading", fins_d)
    add_boxes("d_sglass", "Modern::BlockD::Facade", d1glass)
    add_boxes("d_smull", "Modern::BlockD::Facade", d1mull)
    add_boxes("d_wrg", "Modern::BlockD::Facade", wribbon_g)
    add_boxes("d_wrf", "Modern::BlockD::Facade", wribbon_f)
    add_boxes("d_nrg", "Modern::BlockD::Facade", nribbon_g)
    add_boxes("d_nrf", "Modern::BlockD::Facade", nribbon_f)
    add_boxes("d_endw", "Modern::BlockD::Walls", endw)
    add_boxes("d_rgdeck", "Modern::BlockD::Roof", gd)
    add_boxes("d_rgplant", "Modern::BlockD::Roof", gp)
    add_boxes("d_rghedge", "Modern::BlockD::Roof", gh)
    add_boxes("d_rgpost", "Modern::BlockD::Roof", gpost)
    add_boxes("d_rgslat", "Modern::BlockD::Roof", gslat)
    add_boxes("d_deck2", "Modern::BlockD::Roof", d1deck)
    add_obl_boxes("d_pv", "Modern::BlockD::Climate", d2pv)
    add_boxes("d_par", "Modern::BlockD::Roof", d2par)
    add_boxes("d_plant", "Modern::BlockD::Climate", d2plant)
    add_boxes("d_core", "Modern::BlockD::Cores", core_w)
    add_boxes("d_coresign", "Modern::BlockD::Wayfinding", core_s)
    add_boxes("d_bfloor", "Modern::BlockD::Bridge", bfloor)
    add_boxes("d_bglass", "Modern::BlockD::Bridge", bglass)
    add_boxes("d_broof", "Modern::BlockD::Bridge", broof)
    add_cylinders("d_bcols", "Modern::BlockD::Bridge", bcols)
    add_boxes("d_lpavg", "Modern::BlockD::Bridge", lpav_g)
    add_boxes("d_lpavm", "Modern::BlockD::Bridge", lpav_m)
    add_boxes("d_lroof", "Modern::BlockD::Bridge", lroof)
    add_boxes("d_lsteps", "Modern::BlockD::Bridge", lsteps)
    add_boxes("d_ecan", "Modern::BlockD::Entrance", decan)
    add_cylinders("d_epost", "Modern::BlockD::Entrance", depost)
    add_boxes("d_edoor", "Modern::BlockD::Entrance", dedoor)
    add_boxes("d_esign", "Modern::BlockD::Entrance", design)
    add_boxes("d_shopg", "Modern::BlockD::Shop", sg)
    add_boxes("d_shopf", "Modern::BlockD::Shop", sf)
    add_boxes("d_shopfa", "Modern::BlockD::Shop", sfa)
    add_boxes("d_shops", "Modern::BlockD::Shop", ss)
    add_obl_boxes("d_shopaw", "Modern::BlockD::Shop", saw)
    add_boxes("d_shopco", "Modern::BlockD::Shop", sco)
    save()
    log(f"  block D: two interlocking bars, {len(fins_d)} west fins, sky bridge to concourse")

# ══════════════ M7: corner shops, plaza, urban realm ══════════════
def phase_m7():
    log("=== M7: URBAN REALM (streets, plaza, kiosk, trees, lamps, labels) ===")
    roads = [[0, 66000, -80, 150000, 74000, 0], [0, 38000, -80, 150000, 44000, 0],
             [66000, 0, -80, 74000, 38000, 0], [66000, 74000, -80, 74000, 108000, 0]]
    sidewalks = [[0, 63000, 0, 150000, 66000, 60], [0, 74000, 0, 150000, 77500, 60],
                 [0, 35000, 0, 150000, 38000, 60], [0, 44000, 0, 66000, 46000, 60],
                 [74000, 44000, 0, 150000, 46000, 60],
                 [63000, 0, 0, 66000, 35000, 60], [74000, 0, 0, 77500, 35000, 60],
                 [63000, 77500, 0, 66000, 108000, 60], [74000, 77500, 0, 77500, 108000, 60]]
    plaza = [[110000, 46000, -10, 136000, 62000, 50], [0, 77500, -10, 63000, 80000, 50],
             [77500, 77500, -10, 150000, 80000, 50]]
    cross = []
    for (cx0, cy0, along_x) in ((67000, 63200, False), (67000, 74200, False),
                                (60500, 66800, True), (75000, 39000, True)):
        for i in range(6):
            if along_x:
                cross.append([cx0 + i*1200, cy0, 2, cx0 + i*1200 + 600, cy0 + 4600, 14])
            else:
                cross.append([cx0 + i*1200, cy0, 2, cx0 + i*1200 + 600, cy0 + 2600, 14])
    kiosk_body = [[121000, 53000, 0, 4200, 3400, 3100, 30, 0]]
    kiosk_fascia = [[121000, 53000, 3100, 4600, 3800, 600, 30, 0]]
    kiosk_glass = [[121000 - 1500*math.sin(math.radians(30)), 53000 - 1500*math.cos(math.radians(30)),
                    300, 3800, 90, 2400, 30, 0]]
    racks = [[16000 + i*800, 60500, 150, 900, 70, 750, 0, 0] for i in range(8)]
    lampsP, lampsH, trunks, crowns, seats = [], [], [], [], []
    for x in range(10000, 150001, 18000):
        street_lamp(lampsP, lampsH, x, 65000)
    for x in range(14000, 150001, 18000):
        street_lamp(lampsP, lampsH, x, 45000)
    for (tx, ty) in [(12000+i*12000, 78600) for i in range(5)] + \
                    [(88000+i*13000, 78600) for i in range(5)] + \
                    [(114000, 50000), (118000, 58500), (128000, 49500), (132000, 58000)] + \
                    [(15000+i*15000, 36500) for i in range(4)] + \
                    [(80000, 36500), (95000, 36500)]:
        tree(trunks, crowns, tx, ty)
    for bx in (112500, 117500, 126500, 131500):
        bench(seats, bx, 47500)
    bench(seats, 133500, 52000, along_x=False)
    bench(seats, 111500, 52000, along_x=False)
    add_boxes("u_roads", "Modern::Urban::Roads", roads)
    add_boxes("u_sidewalks", "Modern::Urban::Sidewalks", sidewalks)
    add_boxes("u_plaza", "Modern::Urban::Plaza", plaza)
    add_boxes("u_cross", "Modern::Urban::Markings", cross)
    add_obl_boxes("u_kioskb", "Modern::Urban::Kiosk", kiosk_body)
    add_obl_boxes("u_kioskf", "Modern::Urban::Kiosk", kiosk_fascia)
    add_obl_boxes("u_kioskg", "Modern::Urban::Kiosk", kiosk_glass)
    add_obl_boxes("u_racks", "Modern::Urban::BikeRacks", racks)
    add_cylinders("u_lampp", "Modern::Urban::Lamps", lampsP)
    add_boxes("u_lamph", "Modern::Urban::Lamps", lampsH)
    add_cylinders("u_trunks", "Modern::Urban::Trees", trunks)
    add_boxes("u_crowns", "Modern::Urban::Trees", crowns)
    add_boxes("u_seats", "Modern::Urban::Benches", seats)
    add_texts("u_labels", "Modern::Urban::Labels", [
        (10000, 99000, 0, 1600, "SLAB ON PILOTIS 9F"),
        (86000, 107000, 0, 1600, "STEPPED TERRACES 5L"),
        (10000, 30000, 0, 1400, "INTERLOCKING BARS 5F+8F"),
        (107000, 1500, 0, 1400, "CYLINDER TOWER 13F"),
        (42000, 63200, 0, 1300, "TRANSIT CONCOURSE + METRO"),
        (15000, 43000, 0, 1200, "BUS INTERCHANGE"),
        (118000, 44000, 0, 1200, "PLAZA"),
    ])
    save()
    log(f"  urban: 4 roads, {len(trunks)} trees, {len(lampsP)} lamps, rotated kiosk")

# ══════════════ M8: materials + roles + checks ══════════════
MAT = [
    # (batch, material, role, construction_system)
    ("g_ground", "concrete-smooth", "site_ground", ""),
    ("m_walls", "concrete-boardformed", "retaining_wall", "concrete-bearing-wall"),
    ("m_beds", "rubber-black", "track_bed", ""),
    ("m_rails", "steel-galvanized", "rail", ""),
    ("m_platform", "concrete-smooth", "platform_slab", "concrete-flat-plate"),
    ("m_strips", "steel-painted-sage", "tactile_strip", ""),
    ("m_pcols", "concrete-smooth", "column", "concrete-column-grid"),
    ("m_deck", "concrete-smooth", "flat_plate_slab", "concrete-flat-plate"),
    ("m_stairs", "concrete-smooth", "stair", ""),
    ("m_srails", "glass-laminated", "railing", ""),
    ("m_esc", "steel-galvanized", "escalator", ""),
    ("m_ebal", "glass-laminated", "balustrade", ""),
    ("m_tbody", "aluminium-anodized", "vehicle", ""),
    ("m_tglass", "glass-clear", "vehicle_glazing", ""),
    ("m_tdoor", "steel-painted-sage", "vehicle_door", ""),
    ("h_paving", "concrete-smooth", "plaza", ""),
    ("h_cols", "concrete-smooth", "column", "concrete-column-grid"),
    ("h_roof", "concrete-smooth", "flat_plate_slab", "concrete-flat-plate"),
    ("h_upstand", "concrete-smooth", "upstand", ""),
    ("h_glass", "glass-clear", "curtain_wall_glazing", ""),
    ("h_mull", "aluminium-anodized", "mullion", ""),
    ("h_fins", "aluminium-anodized", "brise_soleil", ""),
    ("h_skyc", "concrete-smooth", "skylight_curb", ""),
    ("h_skyg", "glass-laminated", "skylight", ""),
    ("h_gates", "steel-galvanized", "fare_gate", ""),
    ("h_kiosks", "wood-oak", "kiosk", ""),
    ("h_totems", "steel-painted-sage", "signage", ""),
    ("h_seats", "wood-oak", "bench", ""),
    ("h_pv", "rubber-black", "pv_panel", ""),
    ("h_cowls", "steel-galvanized", "vent_cowl", ""),
    ("h_caps", "metal-corrugated", "vent_cap", ""),
    ("h_plant", "metal-corrugated", "air_handler", ""),
    ("h_louv", "aluminium-anodized", "louver", ""),
    ("h_ecan", "concrete-smooth", "entrance_canopy", ""),
    ("h_epost", "steel-painted-sage", "canopy_post", ""),
    ("h_edoor", "glass-laminated", "entrance_door", ""),
    ("h_esign", "aluminium-anodized", "signage", ""),
    ("b_asphalt", "rubber-black", "bus_lane", ""),
    ("b_island", "concrete-smooth", "platform_slab", ""),
    ("b_canopy", "polycarbonate-opal", "canopy", ""),
    ("b_cols", "steel-painted-sage", "canopy_post", ""),
    ("b_glass", "glass-laminated", "windbreak", ""),
    ("b_seats", "wood-oak", "bench", ""),
    ("b_stripes", "plaster-white", "lane_marking", ""),
    ("b_signp", "steel-galvanized", "sign_post", ""),
    ("b_signh", "steel-painted-sage", "signage", ""),
    ("b_body", "steel-painted-sage", "vehicle", ""),
    ("b_bglass", "glass-clear", "vehicle_glazing", ""),
    ("b_wheel", "rubber-black", "wheel", ""),
    ("a_pilotis", "concrete-smooth", "column", "concrete-column-grid"),
    ("a_slabs", "concrete-smooth", "flat_plate_slab", "concrete-flat-plate"),
    ("a_shelf", "concrete-smooth", "brise_soleil", ""),
    ("a_fins", "concrete-smooth", "brise_soleil", ""),
    ("a_glass", "glass-clear", "window", ""),
    ("a_setg", "glass-clear", "window", ""),
    ("a_setm", "aluminium-anodized", "mullion", ""),
    ("a_nglass", "glass-clear", "ribbon_window", ""),
    ("a_nframes", "aluminium-anodized", "window_frame", ""),
    ("a_endw", "plaster-white", "shear_wall", "concrete-bearing-wall"),
    ("a_vrail", "glass-laminated", "railing", ""),
    ("a_vpots", "concrete-boardformed", "planter", ""),
    ("a_vtrunk", "wood-oak", "tree_trunk", ""),
    ("a_vcrown", "wood-birch-ply", "tree_crown", ""),
    ("a_drawers", "plaster-white", "cantilever_volume", ""),
    ("a_dglass", "glass-clear", "window", ""),
    ("a_tdeck", "wood-oak", "roof_deck_boards", ""),
    ("a_tplant", "concrete-boardformed", "planter", ""),
    ("a_thedge", "steel-painted-sage", "hedge", ""),
    ("a_rgdeck", "wood-oak", "roof_deck_boards", ""),
    ("a_rgplant", "concrete-boardformed", "planter", ""),
    ("a_rghedge", "steel-painted-sage", "hedge", ""),
    ("a_rgpost", "wood-walnut", "pergola_post", ""),
    ("a_rgslat", "wood-walnut", "pergola_slat", ""),
    ("a_pav", "concrete-smooth", "pavilion_slab", ""),
    ("a_pavg", "glass-clear", "window", ""),
    ("a_pavm", "aluminium-anodized", "mullion", ""),
    ("a_pavroof", "plaster-white", "roof_slab", ""),
    ("a_par", "plaster-white", "parapet", ""),
    ("a_bulk", "plaster-white", "bulkhead", ""),
    ("a_core", "concrete-boardformed", "shear_wall", "concrete-bearing-wall"),
    ("a_coresign", "steel-painted-sage", "exit_sign", ""),
    ("a_ecan", "plaster-white", "entrance_canopy", ""),
    ("a_epost", "steel-painted-sage", "canopy_post", ""),
    ("a_edoor", "glass-laminated", "entrance_door", ""),
    ("a_esign", "aluminium-anodized", "signage", ""),
    ("a_shopg", "glass-clear", "storefront", ""),
    ("a_shopf", "aluminium-anodized", "mullion", ""),
    ("a_shopfa", "plaster-white", "fascia", ""),
    ("a_shops", "steel-painted-sage", "signage", ""),
    ("a_shopaw", "polycarbonate-opal", "awning", ""),
    ("a_shopco", "wood-walnut", "counter", ""),
    ("bb_cols", "concrete-smooth", "column", "concrete-column-grid"),
    ("bb_slabs", "concrete-smooth", "flat_plate_slab", "concrete-flat-plate"),
    ("bb_sglass", "glass-clear", "window", ""),
    ("bb_smull", "aluminium-anodized", "mullion", ""),
    ("bb_walls", "plaster-white", "shear_wall", "concrete-bearing-wall"),
    ("bb_nglass", "glass-clear", "ribbon_window", ""),
    ("bb_nframes", "aluminium-anodized", "window_frame", ""),
    ("bb_tdeck", "wood-oak", "roof_deck_boards", ""),
    ("bb_tplant", "concrete-boardformed", "planter", ""),
    ("bb_thedge", "steel-painted-sage", "hedge", ""),
    ("bb_trail", "glass-laminated", "railing", ""),
    ("bb_tdiv", "plaster-white", "privacy_wall", ""),
    ("bb_perp", "wood-walnut", "pergola_post", ""),
    ("bb_pers", "wood-walnut", "pergola_slat", ""),
    ("bb_pv", "rubber-black", "pv_panel", ""),
    ("bb_par", "plaster-white", "parapet", ""),
    ("bb_core", "concrete-boardformed", "shear_wall", "concrete-bearing-wall"),
    ("bb_coresign", "steel-painted-sage", "exit_sign", ""),
    ("bb_ecan", "plaster-white", "entrance_canopy", ""),
    ("bb_epost", "steel-painted-sage", "canopy_post", ""),
    ("bb_edoor", "glass-laminated", "entrance_door", ""),
    ("bb_esign", "aluminium-anodized", "signage", ""),
    ("bb_shopg", "glass-clear", "storefront", ""),
    ("bb_shopf", "aluminium-anodized", "mullion", ""),
    ("bb_shopfa", "plaster-white", "fascia", ""),
    ("bb_shops", "steel-painted-sage", "signage", ""),
    ("bb_shopaw", "polycarbonate-opal", "awning", ""),
    ("bb_shopco", "wood-walnut", "counter", ""),
    ("c_pcols", "concrete-smooth", "column", "concrete-column-grid"),
    ("c_pslabs", "concrete-smooth", "flat_plate_slab", "concrete-flat-plate"),
    ("c_pglass", "glass-clear", "curtain_wall_glazing", ""),
    ("c_pmull", "aluminium-anodized", "mullion", ""),
    ("c_rgdeck", "wood-oak", "roof_deck_boards", ""),
    ("c_rgplant", "concrete-boardformed", "planter", ""),
    ("c_rghedge", "steel-painted-sage", "hedge", ""),
    ("c_rgpost", "wood-walnut", "pergola_post", ""),
    ("c_rgslat", "wood-walnut", "pergola_slat", ""),
    ("c_ppar", "concrete-smooth", "parapet", ""),
    ("c_core", "concrete-boardformed", "core_wall", "concrete-bearing-wall"),
    ("c_tcols", "steel-painted-sage", "column", "steel-column-frame"),
    ("c_tslabs", "concrete-smooth", "deck_slab", "steel-wide-flange-floor"),
    ("c_drums", "glass-clear", "curtain_wall_glazing", ""),
    ("c_fins", "aluminium-anodized", "vertical_fin", ""),
    ("c_crown", "plaster-white", "parapet", ""),
    ("c_skyrail", "glass-laminated", "railing", ""),
    ("c_skyplant", "concrete-boardformed", "planter", ""),
    ("c_skyhedge", "steel-painted-sage", "hedge", ""),
    ("c_troof", "concrete-smooth", "roof_slab", ""),
    ("c_tcowls", "steel-galvanized", "vent_cowl", ""),
    ("c_tplant", "metal-corrugated", "air_handler", ""),
    ("c_corew", "concrete-boardformed", "shear_wall", "concrete-bearing-wall"),
    ("c_coresign", "steel-painted-sage", "exit_sign", ""),
    ("c_ecan", "concrete-smooth", "entrance_canopy", ""),
    ("c_epost", "steel-painted-sage", "canopy_post", ""),
    ("c_edoor", "glass-laminated", "entrance_door", ""),
    ("c_esign", "aluminium-anodized", "signage", ""),
    ("c_shopg1", "glass-clear", "storefront", ""), ("c_shopf1", "aluminium-anodized", "mullion", ""),
    ("c_shopfa1", "plaster-white", "fascia", ""), ("c_shops1", "steel-painted-sage", "signage", ""),
    ("c_shopaw1", "polycarbonate-opal", "awning", ""), ("c_shopco1", "wood-walnut", "counter", ""),
    ("c_shopg2", "glass-clear", "storefront", ""), ("c_shopf2", "aluminium-anodized", "mullion", ""),
    ("c_shopfa2", "plaster-white", "fascia", ""), ("c_shops2", "steel-painted-sage", "signage", ""),
    ("c_shopaw2", "polycarbonate-opal", "awning", ""), ("c_shopco2", "wood-walnut", "counter", ""),
    ("d_cols", "concrete-smooth", "column", "concrete-column-grid"),
    ("d_slabs", "concrete-smooth", "flat_plate_slab", "concrete-flat-plate"),
    ("d_shelf", "concrete-smooth", "brise_soleil", ""),
    ("d_fins", "aluminium-anodized", "vertical_fin", ""),
    ("d_sglass", "glass-clear", "window", ""),
    ("d_smull", "aluminium-anodized", "mullion", ""),
    ("d_wrg", "glass-clear", "ribbon_window", ""),
    ("d_wrf", "aluminium-anodized", "window_frame", ""),
    ("d_nrg", "glass-clear", "ribbon_window", ""),
    ("d_nrf", "aluminium-anodized", "window_frame", ""),
    ("d_endw", "plaster-white", "shear_wall", "concrete-bearing-wall"),
    ("d_rgdeck", "wood-oak", "roof_deck_boards", ""),
    ("d_rgplant", "concrete-boardformed", "planter", ""),
    ("d_rghedge", "steel-painted-sage", "hedge", ""),
    ("d_rgpost", "wood-walnut", "pergola_post", ""),
    ("d_rgslat", "wood-walnut", "pergola_slat", ""),
    ("d_deck2", "wood-oak", "roof_deck_boards", ""),
    ("d_pv", "rubber-black", "pv_panel", ""),
    ("d_par", "plaster-white", "parapet", ""),
    ("d_plant", "metal-corrugated", "air_handler", ""),
    ("d_core", "concrete-boardformed", "shear_wall", "concrete-bearing-wall"),
    ("d_coresign", "steel-painted-sage", "exit_sign", ""),
    ("d_bfloor", "concrete-smooth", "bridge_deck", ""),
    ("d_bglass", "glass-laminated", "bridge_glazing", ""),
    ("d_broof", "plaster-white", "roof_slab", ""),
    ("d_bcols", "concrete-smooth", "column", "concrete-column-grid"),
    ("d_lpavg", "glass-laminated", "curtain_wall_glazing", ""),
    ("d_lpavm", "aluminium-anodized", "mullion", ""),
    ("d_lroof", "plaster-white", "roof_slab", ""),
    ("d_lsteps", "concrete-smooth", "stair", ""),
    ("d_ecan", "plaster-white", "entrance_canopy", ""),
    ("d_epost", "steel-painted-sage", "canopy_post", ""),
    ("d_edoor", "glass-laminated", "entrance_door", ""),
    ("d_esign", "aluminium-anodized", "signage", ""),
    ("d_shopg", "glass-clear", "storefront", ""),
    ("d_shopf", "aluminium-anodized", "mullion", ""),
    ("d_shopfa", "plaster-white", "fascia", ""),
    ("d_shops", "steel-painted-sage", "signage", ""),
    ("d_shopaw", "polycarbonate-opal", "awning", ""),
    ("d_shopco", "wood-walnut", "counter", ""),
    ("u_roads", "rubber-black", "street", ""),
    ("u_sidewalks", "concrete-smooth", "sidewalk", ""),
    ("u_plaza", "concrete-smooth", "plaza", ""),
    ("u_cross", "plaster-white", "crosswalk", ""),
    ("u_kioskb", "plaster-white", "kiosk", ""),
    ("u_kioskf", "steel-painted-sage", "fascia", ""),
    ("u_kioskg", "glass-clear", "storefront", ""),
    ("u_racks", "steel-galvanized", "bike_rack", ""),
    ("u_lampp", "steel-galvanized", "lamp_post", ""),
    ("u_lamph", "aluminium-anodized", "lamp_head", ""),
    ("u_trunks", "wood-oak", "tree_trunk", ""),
    ("u_crowns", "wood-birch-ply", "tree_crown", ""),
    ("u_seats", "wood-oak", "bench", ""),
]

def phase_m8():
    log("=== M8: MATERIALS + ROLES + EGRESS ===")
    warned = 0
    for bi, (batch, mat, role, system) in enumerate(MAT):
        ids = G.get(batch, [])
        if not ids: continue
        if DRY: continue
        r = json.loads(assign(ids, mat, structural_role=role, construction_system=system))
        if r.get("warnings"): warned += 1
        if bi % 4 == 0:
            snap_frame()
    log(f"  materials: {len(MAT)} batches ({warned} typicality warnings)")
    if DRY: return
    n = stamp(G.get("a_core", []) + G.get("bb_core", []) + G.get("d_core", []) + G.get("c_core", []),
              {"almond:fire_rating": "4-hr capable (200 mm solid RC; BCI A.12)",
               "almond:fire_rating_required": "2-hr shaft enclosure (4+ stories served)"})
    log(f"  fire ratings stamped on {n} core panels")
    ce = fn(m.check_egress)
    hall = json.loads(ce(plate_bounds_mm=[40000, 47500, 110000, 60500],
        exits=[{"name": "S doors", "x_mm": 75000, "y_mm": 47500, "width_mm": 4800},
               {"name": "N doors", "x_mm": 75000, "y_mm": 60500, "width_mm": 4800},
               {"name": "E end", "x_mm": 110000, "y_mm": 54000, "width_mm": 1800}],
        occupancy="assembly_unconcentrated", stories=1, sprinklered=True))
    log(f"  concourse hall egress: occ={hall.get('occupant_load')} passed={hall.get('passed')}")
    slab = json.loads(ce(plate_bounds_mm=[8000, 80000, 62000, 95000],
        exits=[{"name": "core W", "x_mm": 19700, "y_mm": 84000, "width_mm": 1120},
               {"name": "core E", "x_mm": 45700, "y_mm": 84000, "width_mm": 1120}],
        occupancy="residential", stories=9, sprinklered=True))
    log(f"  block A floor egress: occ={slab.get('occupant_load')}/floor passed={slab.get('passed')}")
    tower = json.loads(ce(plate_bounds_mm=[113000, 11000, 131000, 29000],
        exits=[{"name": "core stair A", "x_mm": 120000, "y_mm": 18500, "width_mm": 1120},
               {"name": "core stair B", "x_mm": 124000, "y_mm": 21500, "width_mm": 1120}],
        occupancy="business", stories=13, sprinklered=True))
    log(f"  tower floor egress: occ={tower.get('occupant_load')}/floor passed={tower.get('passed')}")
    save()
    log(f"M8 DONE: {sum(len(v) for v in G.values())} objects total")

# ══════════════ EXPORT: per-material GLBs for Blender ══════════════
EXPORT_GROUPS = {
    "foliage": ["a_vcrown", "u_crowns", "a_thedge", "a_rghedge", "bb_thedge",
                "c_rghedge", "c_skyhedge", "d_rghedge"],
    "lampheads": ["u_lamph"],
    "pv": ["h_pv", "bb_pv", "d_pv"],
}

def phase_export():
    log("=== EXPORT: per-material GLBs -> Blender ===")
    glb_dir = os.path.join(SCRATCH, "modern_glb_mat")
    os.makedirs(glb_dir, exist_ok=True)
    special = {b for bs in EXPORT_GROUPS.values() for b in bs}
    by_mat = {}
    for batch, mat, _, _ in MAT:
        if batch in special: continue
        by_mat.setdefault(mat, []).extend(G.get(batch, []))
    exporter = fn(m.export_asset_contract)
    for key, batches in EXPORT_GROUPS.items():
        ids = [g for b in batches for g in G.get(b, [])]
        if not ids: continue
        r = json.loads(exporter(ids, f"modern-{key}", output_dir=glb_dir))
        log(f"  modern-{key}: {r.get('status')} ({len(ids)} objects)")
    for mat, ids in sorted(by_mat.items()):
        if not ids: continue
        r = json.loads(exporter(ids, f"modern-mat-{mat}", output_dir=glb_dir))
        log(f"  modern-mat-{mat}: {r.get('status')} ({len(ids)} objects)")
    log(f"EXPORT DONE -> {glb_dir}")

# ══════════════ PAN: rendered-view panning frames ══════════════
def phase_pan(pass_no):
    """Parallel tracking shots in the Rendered viewport, written as PNG frames."""
    frames_dir = os.path.join(SCRATCH, f"pan{pass_no}")
    os.makedirs(frames_dir, exist_ok=True)
    N = 240
    if pass_no == 1:      # aerial track west->east along the south front
        cam0, cam1 = (5000.0, -68000.0, 46000.0), (145000.0, -68000.0, 46000.0)
        off = (0.0, 118000.0, -38000.0)
    else:                 # eye-level track along the north street, looking SSW
        cam0, cam1 = (4000.0, 70500.0, 2600.0), (146000.0, 70500.0, 2600.0)
        off = (6000.0, -22000.0, 5000.0)
    CHUNK = 24
    done = 0
    for c0 in range(0, N, CHUNK):
        c1 = min(c0 + CHUNK, N)
        rows = []
        for i in range(c0, c1):
            t = i / (N - 1)
            cx = cam0[0] + (cam1[0] - cam0[0]) * t
            cy = cam0[1] + (cam1[1] - cam0[1]) * t
            cz = cam0[2] + (cam1[2] - cam0[2]) * t
            rows.append(f"{i},{cx:.1f},{cy:.1f},{cz:.1f},{cx+off[0]:.1f},{cy+off[1]:.1f},{cz+off[2]:.1f}")
        cs = CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var view = doc.Views.ActiveView;
    var vp = view.ActiveViewport;
    var mode = Rhino.Display.DisplayModeDescription.FindByName("Rendered");
    if (mode != null && vp.DisplayMode.Id != mode.Id) vp.DisplayMode = mode;
    var vc = new Rhino.Display.ViewCapture {
      Width = 1600, Height = 900, ScaleScreenItems = false, DrawAxes = false,
      DrawGrid = false, DrawGridAxes = false, TransparentBackground = false };
    foreach (var rec in "DATA".Split(';')) {
      var v = rec.Split(',');
      vp.SetCameraLocations(
        new Point3d(double.Parse(v[4]), double.Parse(v[5]), double.Parse(v[6])),
        new Point3d(double.Parse(v[1]), double.Parse(v[2]), double.Parse(v[3])));
      vp.Camera35mmLensLength = 32;
      view.Redraw();
      var bmp = vc.CaptureToBitmap(view);
      bmp.Save(System.IO.Path.Combine(@"FRAMES", "f" + int.Parse(v[0]).ToString("D4") + ".png"));
      bmp.Dispose();
    }
    return new List<Guid>();
  }
}""".replace("DATA", ";".join(rows)).replace("FRAMES", frames_dir)
        payload = json.dumps({"type": "execute", "script": cs, "timeout_s": 300.0}).encode("utf-8")
        r = json.loads(m._send_and_receive(payload, timeout=320.0))
        if r.get("status") != "success":
            log(f"  !! pan chunk {c0}-{c1} failed: {r.get('message','')[:200]}"); break
        done = c1
        log(f"  pan{pass_no}: {done}/{N} frames")
    log(f"PAN {pass_no} DONE -> {frames_dir}")

def phase_fix1():
    """Remediation: tower egress failed (core stairs too close together) ->
    add a secondary stair shaft inside the drum, max distance from the core;
    also add the bus bay stripes whose first batch was malformed."""
    log("=== FIX1: tower secondary egress stair + bus bay stripes ===")
    if not G.get("b_stripes"):
        bstripes = [[16500+i*3800, 48200, 2, 4200, 250, 12, 32, 0] for i in range(6)]
        add_obl_boxes("b_stripes", "Modern::Bus::Markings", bstripes)
        if not DRY:
            json.loads(assign(G["b_stripes"], "plaster-white", structural_role="lane_marking"))
    # secondary stair shaft: 3.0 x 5.0 m at (115500, 20000), z 9000..50600
    shaft = [[114000, 17500, 9000, 114300, 22500, 50600],
             [116700, 17500, 9000, 117000, 22500, 50600],
             [114300, 17500, 9000, 116700, 17800, 50600],
             [114300, 22200, 9000, 116700, 22500, 50600]]
    signs = [[115200, 22500, 9000 + i * H + 2200, 115800, 22560, 9000 + i * H + 2400]
             for i in range(13)]
    add_boxes("c_shaft2", "Modern::BlockC::Cores", shaft)
    add_boxes("c_shaft2sign", "Modern::BlockC::Wayfinding", signs)
    if not DRY:
        json.loads(assign(G["c_shaft2"], "concrete-boardformed",
                          structural_role="shear_wall", construction_system="concrete-bearing-wall"))
        json.loads(assign(G["c_shaft2sign"], "steel-painted-sage", structural_role="exit_sign"))
        stamp(G["c_shaft2"],
              {"almond:fire_rating": "4-hr capable (200 mm solid RC; BCI A.12)",
               "almond:fire_rating_required": "2-hr shaft enclosure (4+ stories served)"})
        tower = json.loads(fn(m.check_egress)(plate_bounds_mm=[113000, 11000, 131000, 29000],
            exits=[{"name": "core stair NE", "x_mm": 124600, "y_mm": 22200, "width_mm": 1120},
                   {"name": "drum stair W", "x_mm": 115500, "y_mm": 20000, "width_mm": 1120}],
            occupancy="business", stories=13, sprinklered=True))
        log(f"  tower floor egress RECHECK: occ={tower.get('occupant_load')}/floor "
            f"passed={tower.get('passed')}")
    save()
    log("FIX1 DONE")

PHASES = {"SUN": phase_sun, "M1": phase_m1, "M2": phase_m2, "M3": phase_m3,
          "M4": phase_m4, "M5": phase_m5, "M6": phase_m6, "M7": phase_m7, "M8": phase_m8,
          "FIX1": phase_fix1}

if PHASE == "ALL":
    for name in ("SUN", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"):
        PHASES[name]()
    log(f"ALL DONE: {sum(len(v) for v in G.values())} objects")
elif PHASE == "EXPORT":
    phase_export()
elif PHASE == "PAN":
    phase_pan(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
elif PHASE in PHASES:
    PHASES[PHASE]()
    log(f"{PHASE} DONE: {sum(len(v) for v in G.values())} objects")
else:
    log(f"unknown phase {PHASE}")
