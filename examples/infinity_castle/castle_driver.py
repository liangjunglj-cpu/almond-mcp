"""Almond Infinity - fractal futuristic castle for an "infinite scale" film.

Where city kit v2 was a modernist district, this kit is ONE building that
tries to look endless: a castle whose four corner towers each carry a sky
platform with a complete miniature copy of the castle (two recursion
levels, 21 modules), whose central keep is an endless spiral ziggurat
(6-tier groups shrinking geometrically, each group rotated 22.5deg, so the
silhouette converges toward a vanishing point), ringed by three floating
counter-rotating halos, six orbiting islet-castles on inverted rock cones,
and a rotating crown of fins at the apex. Cyan light bands ("glow"
batches) become emissive strips in Blender.

Phases (live Rhino mm document, bridge on 5000):
  uv run --no-sync python examples/infinity_castle/castle_driver.py SUN     # sun + view + ground
  uv run --no-sync python examples/infinity_castle/castle_driver.py C1      # plinth, void moat, approach bridge
  uv run --no-sync python examples/infinity_castle/castle_driver.py C2      # the fractal castle (recursive)
  uv run --no-sync python examples/infinity_castle/castle_driver.py C3      # halo rings 1-3
  uv run --no-sync python examples/infinity_castle/castle_driver.py C4      # orbiting islets + apex crown
  uv run --no-sync python examples/infinity_castle/castle_driver.py MAT     # embed materials + roles
  uv run --no-sync python examples/infinity_castle/castle_driver.py ALL     # SUN + C1..C4 + MAT
  uv run --no-sync python examples/infinity_castle/castle_driver.py EXPORT  # per-assembly/material GLBs
  uv run --no-sync python examples/infinity_castle/castle_driver.py SAVE3DM # save the Rhino doc

Moving assemblies are exported as separate GLB files named
inf-<assembly>__<matkey>.glb (assembly "static" for the fixed fabric), so
the Blender script can parent each assembly to its own animated empty.

Sun matches the user's panel from the v2 session: North 209.2,
azimuth 168.3, altitude 22.4, intensity 2.22. ALMOND_DRY=1 dry-runs.
ALMOND_CAPTURE=1 snaps a rendered-view frame after every batch.
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

SCRATCH = os.environ.get("ALMOND_INF_SCRATCH") or os.path.join(
    tempfile.gettempdir(), "almond_infinity")
os.makedirs(SCRATCH, exist_ok=True)
GUIDS_PATH = os.path.join(SCRATCH, "infinity_guids.json")
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
    """Oriented boxes: cx, cy, zb, L, W, H, rotZ_deg, pitch_deg."""
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

def save():
    purge_dims()
    json.dump(G, open(GUIDS_PATH, "w"))

def purge_dims():
    """The bridge stamps a LinearDimension per create/assign batch; sweep them."""
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

# ══════════════ batch accumulators (flush per phase) ══════════════
PREFIX = ""                        # "isl_" while emitting islet mini-castles
B_OBL, B_CYL, B_BOX = {}, {}, {}
LAYERS = {}

def obl(batch, layer, rec):
    b = PREFIX + batch
    B_OBL.setdefault(b, []).append(rec); LAYERS[b] = layer

def cyl(batch, layer, rec):
    b = PREFIX + batch
    B_CYL.setdefault(b, []).append(rec); LAYERS[b] = layer

def box(batch, layer, rec):
    b = PREFIX + batch
    B_BOX.setdefault(b, []).append(rec); LAYERS[b] = layer

def flush():
    n = 0
    for b, recs in B_BOX.items():
        add_boxes(b, LAYERS[b], recs); n += len(recs)
    for b, recs in B_OBL.items():
        add_obl_boxes(b, LAYERS[b], recs); n += len(recs)
    for b, recs in B_CYL.items():
        add_cylinders(b, LAYERS[b], recs); n += len(recs)
    B_BOX.clear(); B_OBL.clear(); B_CYL.clear()
    return n

def rot2(dx, dy, yaw_deg):
    a = math.radians(yaw_deg)
    return dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)

# ══════════════ THE FRACTAL CASTLE KIT ══════════════
W0 = 30000.0                       # level-0 half-span: corner towers at +/-30 m
Z_PLINTH = 4000.0                  # plinth top = castle datum
CHILD = 0.36                       # corner-child scale ratio
L_KEEP  = "Infinity::Castle::Keep"
L_GLASS = "Infinity::Castle::Glazing"
L_TWR   = "Infinity::Castle::Towers"
L_WALL  = "Infinity::Castle::Walls"
L_GLOW  = "Infinity::Castle::Glow"
L_PLAT  = "Infinity::Castle::Platforms"

def keep_chain(cx, cy, z0, side0, yaw, max_groups, glass_ok, glow_ok):
    """Endless spiral ziggurat: 6-tier groups shrinking 0.8/tier, each group
    rotated +22.5deg, next group seeded from the last tier's width. Returns
    (apex_z, last_side)."""
    side, z, g, rot = side0, z0, 0, yaw
    while side > 900 and g < max_groups:
        tiers = 6 if side > 4000 else 4
        s = side
        for i in range(tiers):
            s = side * (0.80 ** i)
            h = 0.42 * s
            r = rot + (45.0 if i % 2 else 0.0)
            obl("c_tier", L_KEEP, [cx, cy, z, s, s, h, r, 0])
            if glass_ok and s > 2500:
                obl("c_tglass", L_GLASS, [cx, cy, z + h * 0.66, s * 1.03, s * 1.03, h * 0.22, r, 0])
            if glow_ok and s > 6000 and i % 2 == 0:
                t = max(0.02 * s, 80)
                obl("glow", L_GLOW, [cx, cy, z + h - t, s * 1.05, s * 1.05, t, r, 0])
            z += h
        side = s * 0.76
        rot += 22.5
        g += 1
    return z, s

def needle(cx, cy, z, ref, glow_tip=True):
    cyl("c_needle", L_TWR, [cx, cy, z, 0, 0, 1, 3.0 * ref, 0.08 * ref])
    if glow_tip:
        cyl("glow", L_GLOW, [cx, cy, z + 3.0 * ref, 0, 0, 1, 0.35 * ref, 0.14 * ref])

def module(cx, cy, z0, W, yaw=0.0, gate=False):
    """One castle module. Detail from absolute size:
    full >= 10 m half-span, simple >= 4 m, else mini. Corner towers of
    full modules carry sky platforms with recursive child modules."""
    full = W >= 10000
    simple = 4000 <= W < 10000
    mini = W < 4000

    # central keep: the endless spiral ziggurat (full modules get a wider,
    # taller keep so the central spire always out-tops its children)
    apex_z, last_side = keep_chain(
        cx, cy, z0, (1.25 if full else 1.1) * W, yaw,
        max_groups=4 if full else (2 if simple else 1),
        glass_ok=not mini, glow_ok=full)
    needle(cx, cy, apex_z, last_side, glow_tip=not mini)

    # four corner towers
    r_t, h_t = 0.15 * W, 1.35 * W
    for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        dx, dy = rot2(sx * W, sy * W, yaw)
        tx, ty = cx + dx, cy + dy
        cyl("t_shaft", L_TWR, [tx, ty, z0, 0, 0, 1, h_t, r_t])
        if not mini:
            for f in (0.32, 0.56, 0.80):
                cyl("t_fin", L_TWR, [tx, ty, z0 + h_t * f, 0, 0, 1, 0.03 * W, 1.35 * r_t])
        cyl("t_crown", L_TWR, [tx, ty, z0 + h_t, 0, 0, 1, 0.06 * W, 1.5 * r_t])
        zt = z0 + h_t + 0.06 * W
        if not mini:
            cyl("t_glass", L_GLASS, [tx, ty, zt, 0, 0, 1, 0.16 * W, 1.15 * r_t])
            zt += 0.16 * W
        cyl("t_cap", L_TWR, [tx, ty, zt, 0, 0, 1, 0.04 * W, 1.35 * r_t])
        zt += 0.04 * W
        if full:
            # sky platform carrying a complete miniature castle
            wc = CHILD * W
            ps = 2.9 * wc
            obl("t_plat", L_PLAT, [tx, ty, zt, ps, ps, 0.05 * W, yaw, 0])
            zp = zt + 0.05 * W
            for ex, ey, ang in ((0, 1, 0), (0, -1, 0), (1, 0, 90), (-1, 0, 90)):
                px, py = rot2(ex * ps * 0.485, ey * ps * 0.485, yaw)
                obl("t_par", L_PLAT, [tx + px, ty + py, zp, ps * 0.97, 0.03 * W, 0.07 * W, yaw + ang, 0])
            module(tx, ty, zp, wc, yaw)
        else:
            cyl("t_needle", L_TWR, [tx, ty, zt, 0, 0, 1, 0.30 * W, 0.035 * W])

    # curtain walls (full modules only)
    if full:
        hw, tw = 0.5 * W, 0.06 * W
        for ex, ey, ang in ((0, 1, 0), (1, 0, 90), (-1, 0, 90)):
            mx, my = rot2(ex * W, ey * W, yaw)
            obl("w_wall", L_WALL, [cx + mx, cy + my, z0, 1.7 * W, tw, hw, yaw + ang, 0])
            obl("w_cap", L_WALL, [cx + mx, cy + my, z0 + hw, 1.74 * W, tw * 1.3, 0.03 * W, yaw + ang, 0])
        # south wall with gate (or solid when not the main module)
        mx, my = rot2(0, -W, yaw)
        if gate:
            for off in (-0.55, 0.55):
                gx, gy = rot2(off * W, -W, yaw)
                obl("w_wall", L_WALL, [cx + gx, cy + gy, z0, 0.6 * W, tw, hw, yaw, 0])
                obl("w_cap", L_WALL, [cx + gx, cy + gy, z0 + hw, 0.62 * W, tw * 1.3, 0.03 * W, yaw, 0])
            for off in (-0.28, 0.28):
                gx, gy = rot2(off * W, -W, yaw)
                obl("g_frame", L_WALL, [cx + gx, cy + gy, z0, 0.12 * W, 0.2 * W, 0.55 * W, yaw, 0])
            obl("g_frame", L_WALL, [cx + mx, cy + my, z0 + 0.55 * W, 0.68 * W, 0.18 * W, 0.08 * W, yaw, 0])
            obl("g_door", L_WALL, [cx + mx, cy + my, z0, 0.5 * W, 0.03 * W, 0.5 * W, yaw, 0])
            obl("glow", L_GLOW, [cx + mx, cy + my, z0 + 0.63 * W, 0.68 * W, 0.19 * W, 0.025 * W, yaw, 0])
        else:
            obl("w_wall", L_WALL, [cx + mx, cy + my, z0, 1.7 * W, tw, hw, yaw, 0])
            obl("w_cap", L_WALL, [cx + mx, cy + my, z0 + hw, 1.74 * W, tw * 1.3, 0.03 * W, yaw, 0])
    return apex_z

# ══════════════ SUN ══════════════
SUN_STATE = os.path.join(SCRATCH, "sun_state.json")

def phase_sun():
    log("=== SUN + VIEW: v2 sun panel values, SE perspective ===")
    if not G.get("g_ground"):
        add_boxes("g_ground", "Infinity::Site::Ground",
                  [[-260000, -260000, -380, 260000, 260000, -80]])
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
    vp.SetCameraLocations(new Point3d(0, 0, 45000), new Point3d(175000, -135000, 95000));
    vp.Camera35mmLensLength = 40;
    var mode = Rhino.Display.DisplayModeDescription.FindByName("Rendered");
    if (mode != null) vp.DisplayMode = mode;
    view.Redraw();
    return new List<Guid>();
  }
}""".replace("SUNSTATE", SUN_STATE)))
    log(f"sun set: {r.get('status')}; state -> {SUN_STATE}")
    save()

# ══════════════ C1: plinth, void moat, bridge ══════════════
def phase_c1():
    log("=== C1: PLINTH + VOID MOAT + BRIDGE ===")
    cyl("p_plinth", "Infinity::Site::Plinth", [0, 0, 0, 0, 0, 1, Z_PLINTH, 58000])
    cyl("p_plinth", "Infinity::Site::Plinth", [0, 0, 0, 0, 0, 1, 1600, 64000])
    cyl("p_moat", "Infinity::Site::Moat", [0, 0, 60, 0, 0, 1, 240, 74000])
    # approach bridge from the south, with cyan edge strips
    box("p_bridge", "Infinity::Site::Bridge", [-3200, -110000, 2600, 3200, -56000, 4000])
    for sx in (-1, 1):
        box("glow", L_GLOW, [sx * 3200, -110000, 3800, sx * 3500, -56000, 4100])
    # ring of plaza pylons on the plinth step
    for k in range(12):
        a = math.radians(k * 30 + 15)
        px, py = 61000 * math.cos(a), 61000 * math.sin(a)
        cyl("p_pylon", "Infinity::Site::Pylons", [px, py, 1600, 0, 0, 1, 5200, 700])
        cyl("glow", L_GLOW, [px, py, 6800, 0, 0, 1, 500, 850])
    n = flush()
    save()
    log(f"C1 DONE: {n} objects")

# ══════════════ C2: the fractal castle ══════════════
def phase_c2():
    log("=== C2: FRACTAL CASTLE (recursive) ===")
    apex = module(0, 0, Z_PLINTH, W0, yaw=0.0, gate=True)
    json.dump({"apex_z": apex}, open(os.path.join(SCRATCH, "apex.json"), "w"))
    n = flush()
    save()
    log(f"C2 DONE: {n} objects, apex at z={apex/1000:.1f} m")

# ══════════════ C3: halo rings ══════════════
RINGS = [
    # (name, z_mm, radius_mm, segments, seg_w, seg_h)
    ("ring1", 24000.0, 52000.0, 36, 3000.0, 1500.0),
    ("ring2", 48000.0, 38000.0, 30, 2600.0, 1250.0),
    ("ring3", 66000.0, 24000.0, 24, 2200.0, 1050.0),
]

def phase_c3():
    log("=== C3: HALO RINGS ===")
    for name, z, R, N, w, h in RINGS:
        seg = 2 * math.pi * R / N * 0.78
        for k in range(N):
            a = 360.0 * k / N
            x, y = R * math.cos(math.radians(a)), R * math.sin(math.radians(a))
            obl(f"{name}_body", f"Infinity::Rings::{name}", [x, y, z, seg, w, h, a + 90, 0])
            obl(f"{name}_glow", f"Infinity::Rings::{name}", [x, y, z - 520, seg * 0.9, w * 0.35, 480, a + 90, 0])
    n = flush()
    save()
    log(f"C3 DONE: {n} objects")

# ══════════════ C4: orbiting islets + apex crown ══════════════
ISLETS = [
    # (angle_deg, radius_mm, z_mm)
    (15, 80000, 30000), (75, 86000, 44000), (135, 78000, 36000),
    (195, 90000, 56000), (255, 82000, 48000), (315, 88000, 64000),
]

def phase_c4():
    global PREFIX
    log("=== C4: ORBITING ISLETS + APEX CROWN ===")
    for ang, R, z in ISLETS:
        x, y = R * math.cos(math.radians(ang)), R * math.sin(math.radians(ang))
        PREFIX = "isl_"
        # inverted rock cone
        cyl("rock", "Infinity::Islets::Rock", [x, y, z - 2600, 0, 0, 1, 2600, 5200])
        cyl("rock", "Infinity::Islets::Rock", [x, y, z - 5200, 0, 0, 1, 2600, 3400])
        cyl("rock", "Infinity::Islets::Rock", [x, y, z - 8600, 0, 0, 1, 3400, 1800])
        cyl("glow", "Infinity::Islets::Glow", [x, y, z - 10600, 0, 0, 1, 2000, 750])
        cyl("disc", "Infinity::Islets::Deck", [x, y, z, 0, 0, 1, 900, 6400])
        module(x, y, z + 900, 3500, yaw=ang)
        PREFIX = ""
    # apex crown: rotating ring of fins around the spire tip
    apex = json.load(open(os.path.join(SCRATCH, "apex.json")))["apex_z"] \
        if os.path.exists(os.path.join(SCRATCH, "apex.json")) else 88000.0
    zc = apex - 3000
    for k in range(12):
        a = 360.0 * k / 12
        x, y = 9000 * math.cos(math.radians(a)), 9000 * math.sin(math.radians(a))
        obl("crown_body", "Infinity::Crown", [x, y, zc, 1500, 380, 7200, a, 0])
        obl("crown_glow", "Infinity::Crown", [x * 1.13, y * 1.13, zc + 1400, 900, 220, 4400, a, 0])
    n = flush()
    save()
    log(f"C4 DONE: {n} objects (crown at z={zc/1000:.1f} m)")

# ══════════════ MAT: embed materials + roles ══════════════
MAT = [
    ("g_ground",  "concrete-smooth",      "site_ground"),
    ("p_plinth",  "concrete-smooth",      "plinth"),
    ("p_moat",    "rubber-black",         "void_moat"),
    ("p_bridge",  "concrete-smooth",      "approach_bridge"),
    ("p_pylon",   "aluminium-anodized",   "plaza_pylon"),
    ("c_tier",    "plaster-white",        "keep_tier"),
    ("c_tglass",  "glass-clear",          "glazed_band"),
    ("c_needle",  "steel-galvanized",     "spire_needle"),
    ("t_shaft",   "aluminium-anodized",   "tower_shaft"),
    ("t_fin",     "steel-galvanized",     "tower_fin"),
    ("t_crown",   "steel-galvanized",     "tower_crown"),
    ("t_glass",   "glass-clear",          "observatory_drum"),
    ("t_cap",     "aluminium-anodized",   "tower_cap"),
    ("t_plat",    "concrete-smooth",      "sky_platform"),
    ("t_par",     "aluminium-anodized",   "platform_parapet"),
    ("t_needle",  "steel-galvanized",     "spire_needle"),
    ("w_wall",    "concrete-smooth",      "curtain_wall"),
    ("w_cap",     "aluminium-anodized",   "wall_cap"),
    ("g_frame",   "steel-galvanized",     "gate_frame"),
    ("g_door",    "rubber-black",         "gate_door"),
    ("glow",      "polycarbonate-opal",   "light_band"),
    ("ring1_body", "aluminium-anodized",  "halo_ring"),
    ("ring1_glow", "polycarbonate-opal",  "halo_light"),
    ("ring2_body", "aluminium-anodized",  "halo_ring"),
    ("ring2_glow", "polycarbonate-opal",  "halo_light"),
    ("ring3_body", "aluminium-anodized",  "halo_ring"),
    ("ring3_glow", "polycarbonate-opal",  "halo_light"),
    ("isl_rock",  "concrete-boardformed", "islet_rock"),
    ("isl_disc",  "concrete-smooth",      "islet_deck"),
    ("isl_glow",  "polycarbonate-opal",   "islet_light"),
    ("isl_c_tier", "plaster-white",       "keep_tier"),
    ("isl_c_needle", "steel-galvanized",  "spire_needle"),
    ("isl_t_shaft", "aluminium-anodized", "tower_shaft"),
    ("isl_t_crown", "steel-galvanized",   "tower_crown"),
    ("isl_t_cap", "aluminium-anodized",   "tower_cap"),
    ("isl_t_needle", "steel-galvanized",  "spire_needle"),
    ("crown_body", "aluminium-anodized",  "crown_fin"),
    ("crown_glow", "polycarbonate-opal",  "crown_light"),
]

def phase_mat():
    log("=== MAT: EMBED MATERIALS + ROLES ===")
    for bi, (batch, mat, role) in enumerate(MAT):
        ids = G.get(batch, [])
        if not ids or DRY: continue
        json.loads(assign(ids, mat, structural_role=role))
        if bi % 5 == 0:
            snap_frame()
    log(f"  materials embedded on {len(MAT)} batches")
    save()
    log(f"MAT DONE: {sum(len(v) for v in G.values())} objects total")

# ══════════════ EXPORT: per-assembly/material GLBs ══════════════
# moving assemblies each get their own files so Blender can animate them
ASSEMBLIES = {
    "ring1": ["ring1_body", "ring1_glow"],
    "ring2": ["ring2_body", "ring2_glow"],
    "ring3": ["ring3_body", "ring3_glow"],
    "crown": ["crown_body", "crown_glow"],
    "islets": ["isl_rock", "isl_disc", "isl_glow", "isl_c_tier", "isl_c_needle",
               "isl_t_shaft", "isl_t_crown", "isl_t_cap", "isl_t_needle"],
}
GLOW_BATCHES = {b for b, mat, _ in MAT if mat == "polycarbonate-opal"}

def _matkey(batch):
    mat = next(mt for b, mt, _ in MAT if b == batch)
    return "glow" if batch in GLOW_BATCHES else mat

def phase_export():
    log("=== EXPORT: per-assembly/material GLBs -> Blender ===")
    glb_dir = os.path.join(SCRATCH, "inf_glb")
    os.makedirs(glb_dir, exist_ok=True)
    exporter = fn(m.export_asset_contract)
    special = {b for bs in ASSEMBLIES.values() for b in bs}
    jobs = {}
    for asm, batches in ASSEMBLIES.items():
        for b in batches:
            key = f"inf-{asm}__{_matkey(b)}"
            jobs.setdefault(key, []).extend(G.get(b, []))
    for batch, mat, _ in MAT:
        if batch in special: continue
        key = f"inf-static__{_matkey(batch)}"
        jobs.setdefault(key, []).extend(G.get(batch, []))
    for key, ids in sorted(jobs.items()):
        if not ids: continue
        r = json.loads(exporter(ids, key, output_dir=glb_dir))
        log(f"  {key}: {r.get('status')} ({len(ids)} objects)")
    log(f"EXPORT DONE -> {glb_dir}")

def phase_save3dm():
    out = os.path.join(os.path.expanduser("~"), "Documents", "almond_infinity",
                       "almond_infinity.3dm")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = json.loads(run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    doc.SaveAs(@"OUT");
    return new List<Guid>();
  }
}""".replace("OUT", out)))
    log(f"SAVE3DM: {r.get('status')} -> {out}")

PHASES = {"SUN": phase_sun, "C1": phase_c1, "C2": phase_c2, "C3": phase_c3,
          "C4": phase_c4, "MAT": phase_mat, "EXPORT": phase_export,
          "SAVE3DM": phase_save3dm}

if PHASE == "ALL":
    for p in ("SUN", "C1", "C2", "C3", "C4", "MAT"):
        PHASES[p]()
elif PHASE in PHASES:
    PHASES[PHASE]()
else:
    log(f"unknown phase {PHASE}; use {'|'.join(PHASES)}|ALL")
