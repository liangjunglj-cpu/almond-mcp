"""Almond Celestia - floating sky-citadel: Genshin-style visuals x cyber-tech.

Third castle generation, greater volume, different style. A ~190 m
floating island on an inverted rock cone (glowing crystals beneath,
waterfalls pouring into a sea of stylized clouds), carrying a ~137 m
cylindrical drum-spire citadel with tiered glazed-teal pagoda roofs,
polished-brass trim rings, cyan glow bands and window slits. Six radial
towers hold sky platforms with miniature citadels (the infinity
recursion), arc bridges span back to the core, rim pylons carry beacons,
and a ~300-house terraced village with meadow grass, mint trees, marble
avenues and gold lantern orbs fills the island. Ten satellite islands
with their own mini-citadels orbit the whole. Motion: three horizontal
energy rings + a vertical gold halo behind the spire, a drifting crystal
swarm, spinning sigil discs and an apex crown.

Phases (live Rhino mm document, bridge on 5000; the doc should be EMPTY):
  uv run --no-sync python examples/castle_celestia/celestia_driver.py ALL     # SUN + S1..S5 + MAT
  uv run --no-sync python examples/castle_celestia/celestia_driver.py EXPORT  # sky-<asm>__<matkey>.glb
  uv run --no-sync python examples/castle_celestia/celestia_driver.py SAVE3DM

Sky scene - deliberately no ground plane; the island floats over the
viewport gradient (clouds are added Blender-side). Sun matches the
established panel values. ALMOND_DRY=1 dry-runs; ALMOND_CAPTURE=1 snaps
per-batch frames. State in %TEMP%/almond_celestia (ALMOND_SKY_SCRATCH).
"""
import importlib.util, json, math, os, random, sys, tempfile, uuid

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("RHINO_MCP_STATE_DB", tempfile.mktemp(suffix=".sqlite3"))
spec = importlib.util.spec_from_file_location(
    f"srv_{uuid.uuid4().hex}", os.path.join(REPO, "almond_mcp", "server.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fn = lambda t: getattr(t, "fn", t)
run_script = fn(m.execute_rhino_script)
assign = fn(m.assign_material)

SCRATCH = os.environ.get("ALMOND_SKY_SCRATCH") or os.path.join(
    tempfile.gettempdir(), "almond_celestia")
os.makedirs(SCRATCH, exist_ok=True)
GUIDS_PATH = os.path.join(SCRATCH, "celestia_guids.json")
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

# ══════════════ accumulators + helpers ══════════════
PREFIX = ""                      # "o_" while emitting orbit islands
B_OBL, B_CYL = {}, {}
LAYERS = {}

def obl(batch, layer, rec):
    b = PREFIX + batch
    B_OBL.setdefault(b, []).append(rec); LAYERS[b] = layer

def cyl(batch, layer, rec):
    b = PREFIX + batch
    B_CYL.setdefault(b, []).append(rec); LAYERS[b] = layer

def flush():
    n = 0
    for b, recs in B_OBL.items():
        add_obl_boxes(b, LAYERS[b], recs); n += len(recs)
    for b, recs in B_CYL.items():
        add_cylinders(b, LAYERS[b], recs); n += len(recs)
    B_OBL.clear(); B_CYL.clear()
    return n

def rot2(dx, dy, yaw_deg):
    a = math.radians(yaw_deg)
    return dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)

def det(i, j, k):
    return ((i * 73856093) ^ (j * 19349663) ^ (k * 83492791)) % 100

L_ISL = "Celestia::Island"
L_CIT = "Celestia::Citadel"
L_VIL = "Celestia::Village"
L_RING = "Celestia::Rings"
L_GLOW = "Celestia::Glow"

# ══════════════ THE CELESTIA KIT ══════════════
def crystal(x, y, z, s, tilt, yaw, batch="crys_static"):
    obl(batch, L_GLOW, [x, y, z, 1400 * s, 1400 * s, 3600 * s, yaw + 45, tilt])

def island_mass(cx, cy, ztop, r, n_rock=8):
    """Floating island: top disc + inverted rock cone + rim cliffs."""
    cyl("i_top", L_ISL, [cx, cy, ztop - 2500, 0, 0, 1, 2500, r])
    z = ztop - 2500
    rr = r
    for k in range(n_rock):
        h = (7000 + 400 * k) * (r / 95000)
        rr *= (0.90 - 0.035 * k)
        z -= h
        cyl("i_rock", L_ISL, [cx, cy, z, 0, 0, 1, h * 1.05, rr])
    n_cliff = max(int(r / 9000), 5)
    for k in range(n_cliff):
        a = 360.0 * k / n_cliff + (r % 17)
        px, py = cx + (r - 1500) * math.cos(math.radians(a)), cy + (r - 1500) * math.sin(math.radians(a))
        obl("i_rock", L_ISL, [px, py, ztop - 7500, 9000 * r / 95000, 12000 * r / 95000,
                              8500 * r / 95000, a + 90, 12])
    return z

def waterfall(cx, cy, ztop, r, a_deg):
    px = cx + (r - 800) * math.cos(math.radians(a_deg))
    py = cy + (r - 800) * math.sin(math.radians(a_deg))
    drop = 40000 * r / 95000
    obl("w_fall", L_ISL, [px, py, ztop - drop, 6500 * r / 95000, 900, drop, a_deg + 90, 0])
    cyl("w_mist", L_ISL, [px, py, ztop - drop - 900, 0, 0, 1, 800, 5200 * r / 95000])

def tree(x, y, s=1.0):
    cyl("g_trunk", L_VIL, [x, y, 0, 0, 0, 1, 2600 * s, 210 * s])
    cyl("g_leaf", L_VIL, [x, y, 2200 * s, 0, 0, 1, 1500 * s, 1900 * s])
    cyl("g_leaf", L_VIL, [x + 150 * s, y - 100 * s, 3500 * s, 0, 0, 1, 1200 * s, 1300 * s])

def lamp(x, y):
    cyl("l_post", L_VIL, [x, y, 0, 0, 0, 1, 4200, 150])
    cyl("l_orb", L_VIL, [x, y, 4200, 0, 0, 1, 900, 460])

def house(x, y, ang, hi):
    obl("h_body", L_VIL, [x, y, 0, 5200, 4300, 3200 + hi, ang, 0])
    obl("h_roof", L_VIL, [x, y, 3200 + hi, 6300, 5300, 900, ang, 0])
    obl("h_roof", L_VIL, [x, y, 4100 + hi, 4400, 3600, 750, ang, 0])
    ex, ey = rot2(0, 4300 / 2 + 70, ang)
    obl("h_win", L_VIL, [x + ex, y + ey, 900, 1000, 130, 800, ang, 0])
    if det(int(x) % 997, int(y) % 991, 3) < 35:
        obl("h_trim", L_VIL, [x, y, 2900 + hi, 5450, 4550, 240, ang, 0])

def citadel(cx, cy, z0, s, depth):
    """Drum-spire citadel. depth 0 = the main one (8 tier groups + radial
    towers with recursive minis); 1 = tower minis (5 groups + drumlets);
    2 = satellite islands (4 groups)."""
    # podium
    zp = z0
    for k, pr in enumerate((26000, 22000, 18500)):
        cyl("p_pod", L_CIT, [cx, cy, zp, 0, 0, 1, 3000 * s, pr * s])
        cyl("c_trim", L_CIT, [cx, cy, zp + 3000 * s - 450 * s, 0, 0, 1, 450 * s, pr * s + 350 * s])
        zp += 3000 * s
    cyl("c_glowband", L_GLOW, [cx, cy, zp - 550 * s, 0, 0, 1, 550 * s, 18700 * s])
    zc = zp
    n_g = 8 if depth == 0 else (5 if depth == 1 else 4)
    for g in range(n_g):
        r = 16000 * s * (0.82 ** g)
        h = 16000 * s * (0.92 ** g)
        cyl("c_drum", L_CIT, [cx, cy, zc, 0, 0, 1, h, r])
        if depth <= 1:
            for k in range(8):
                a = 360.0 * k / 8 + g * 22.5
                wx = cx + (r + 90) * math.cos(math.radians(a))
                wy = cy + (r + 90) * math.sin(math.radians(a))
                obl("c_win", L_GLOW, [wx, wy, zc + h * 0.35, 720 * s, 170, h * 0.3, a + 90, 0])
        cyl("c_glowband", L_GLOW, [cx, cy, zc + h - 520 * s, 0, 0, 1, 520 * s, r * 1.02])
        cyl("c_trim", L_CIT, [cx, cy, zc + h, 0, 0, 1, 420 * s, r * 1.30])
        cyl("c_roof", L_CIT, [cx, cy, zc + h + 420 * s, 0, 0, 1, 1500 * s, r * 1.42])
        cyl("c_roof", L_CIT, [cx, cy, zc + h + 1920 * s, 0, 0, 1, 950 * s, r * 1.08])
        if depth == 0 and g % 2 == 0:
            for k in range(8):
                a = 360.0 * k / 8 + 22.5
                fx = cx + r * 1.52 * math.cos(math.radians(a))
                fy = cy + r * 1.52 * math.sin(math.radians(a))
                obl("c_fin", L_CIT, [fx, fy, zc + h * 0.18, 2300 * s, 320 * s, h * 0.52, a, 0])
        zc += h + 2870 * s
    cyl("c_needle", L_CIT, [cx, cy, zc, 0, 0, 1, 9000 * s, 650 * s])
    cyl("c_apexglow", L_GLOW, [cx, cy, zc + 9000 * s, 0, 0, 1, 1500 * s, 1050 * s])
    return zc

def radial_tower(a_deg):
    tx = 45000 * math.cos(math.radians(a_deg))
    ty = 45000 * math.sin(math.radians(a_deg))
    cyl("t_shaft", L_CIT, [tx, ty, 0, 0, 0, 1, 46000, 6500])
    for f in (0.3, 0.55, 0.8):
        cyl("c_trim", L_CIT, [tx, ty, 46000 * f, 0, 0, 1, 600, 7300])
    cyl("c_glowband", L_GLOW, [tx, ty, 44800, 0, 0, 1, 550, 6700])
    cyl("c_roof", L_CIT, [tx, ty, 46000, 0, 0, 1, 1400, 9500])
    cyl("p_plat", L_CIT, [tx, ty, 47400, 0, 0, 1, 2400, 14500])
    for k in range(16):
        a = 360.0 * k / 16
        px = tx + 13700 * math.cos(math.radians(a))
        py = ty + 13700 * math.sin(math.radians(a))
        obl("p_par", L_CIT, [px, py, 49800, 3400, 300, 1300, a + 90, 0])
    citadel(tx, ty, 49800, 0.30, 1)
    # arc bridge back to the core, sagging gently upward
    for k in range(10):
        t = (k + 0.5) / 10
        rr = 38500 - 18500 * t
        bx = rr * math.cos(math.radians(a_deg))
        by = rr * math.sin(math.radians(a_deg))
        bz = 30000 + math.sin(t * math.pi) * 2600
        obl("b_deck", L_CIT, [bx, by, bz, 2100, 3300, 700, a_deg, 0])
        for sgn in (-1, 1):
            ox, oy = rot2(0, sgn * 1550, a_deg)
            obl("b_rail", L_CIT, [bx + ox, by + oy, bz + 700, 2100, 180, 800, a_deg, 0])
        if k % 2 == 0:
            obl("b_glow", L_GLOW, [bx, by, bz - 280, 1900, 900, 260, a_deg, 0])

# ══════════════ SUN ══════════════
SUN_STATE = os.path.join(SCRATCH, "sun_state.json")

def phase_sun():
    log("=== SUN + VIEW (sky scene, no ground) ===")
    if DRY: return
    r = json.loads(run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var sun = doc.Lights.Sun;
    sun.Enabled = true;
    sun.ManualControlOn = true;
    sun.North = 209.2;
    sun.Azimuth = 168.3;
    sun.Altitude = 38.0;
    try { sun.Intensity = 2.0; } catch (Exception) {}
    doc.Lights.Skylight.Enabled = true;
    var rs = doc.RenderSettings;
    rs.BackgroundStyle = Rhino.Display.BackgroundStyle.Gradient;
    rs.BackgroundColorTop = System.Drawing.Color.FromArgb(62, 126, 219);
    rs.BackgroundColorBottom = System.Drawing.Color.FromArgb(245, 230, 200);
    doc.RenderSettings = rs;
    var v = sun.Vector;
    System.IO.File.WriteAllText(@"SUNSTATE",
      "{\\"vector\\": [" + v.X + ", " + v.Y + ", " + v.Z + "]," +
      "\\"azimuth\\": " + sun.Azimuth + ", \\"altitude\\": " + sun.Altitude +
      ", \\"north\\": " + sun.North + ", \\"intensity\\": 2.0}");
    var view = doc.Views.ActiveView;
    var vp = view.ActiveViewport;
    vp.ChangeToPerspectiveProjection(true, 45);
    vp.SetCameraLocations(new Point3d(0, 0, 40000), new Point3d(265000, -215000, 30000));
    vp.Camera35mmLensLength = 38;
    var mode = Rhino.Display.DisplayModeDescription.FindByName("Rendered");
    if (mode != null) vp.DisplayMode = mode;
    view.Redraw();
    return new List<Guid>();
  }
}""".replace("SUNSTATE", SUN_STATE)))
    log(f"sun set: {r.get('status')}; state -> {SUN_STATE}")
    save()

# ══════════════ S1: the great island ══════════════
def phase_s1():
    log("=== S1: THE GREAT ISLAND ===")
    rng = random.Random(11)
    island_mass(0, 0, 0, 95000)
    for _ in range(14):
        a = rng.uniform(0, 360)
        rr = rng.uniform(9000, 52000)
        z = -rng.uniform(30000, 60000)
        crystal(rr * math.cos(math.radians(a)), rr * math.sin(math.radians(a)),
                z, rng.uniform(1.6, 3.4), rng.uniform(140, 220), a, batch="i_crys")
    for k in range(6):
        crystal(rng.uniform(-6000, 6000), rng.uniform(-6000, 6000),
                -66000 - k * 1500, 2.6, 180, k * 60, batch="i_crys")
    for k in range(8):
        waterfall(0, 0, 0, 95000, k * 45 + 12)
    n = flush()
    save()
    log(f"S1 DONE: {n} objects")

# ══════════════ S2: citadel + towers + bridges + pylons ══════════════
def phase_s2():
    log("=== S2: CITADEL + RADIAL TOWERS + BRIDGES + PYLONS ===")
    apex = citadel(0, 0, 0, 1.0, 0)
    json.dump({"apex_z": apex}, open(os.path.join(SCRATCH, "apex.json"), "w"))
    for k in range(6):
        radial_tower(k * 60)
    for k in range(6):
        a = k * 60 + 30
        px, py = 88000 * math.cos(math.radians(a)), 88000 * math.sin(math.radians(a))
        cyl("t_shaft", L_CIT, [px, py, 0, 0, 0, 1, 22000, 3800])
        cyl("c_trim", L_CIT, [px, py, 15000, 0, 0, 1, 550, 4400])
        cyl("c_roof", L_CIT, [px, py, 22000, 0, 0, 1, 1100, 5600])
        cyl("bea_glow", L_GLOW, [px, py, 23100, 0, 0, 1, 2400, 1500])
    n = flush()
    save()
    log(f"S2 DONE: {n} objects, citadel apex z={apex/1000:.1f} m")

# ══════════════ S3: village + terraces + trees + lamps ══════════════
def phase_s3():
    log("=== S3: VILLAGE + TERRACES + TREES + LAMPS ===")
    # marble ring paths + radial avenues
    for ring_r in (30000, 60000, 88000):
        for k in range(36):
            a = 360.0 * k / 36
            px, py = ring_r * math.cos(math.radians(a)), ring_r * math.sin(math.radians(a))
            obl("s_pave", L_VIL, [px, py, 0, 2 * math.pi * ring_r / 36 * 0.98, 5500, 350, a + 90, 0])
            if k % 3 == 0:
                obl("v_curb", L_VIL, [px, py, 350, 2 * math.pi * ring_r / 36 * 0.5, 700, 220, a + 90, 0])
    for k in range(4):
        a = k * 90 + 45
        mx, my = 56000 * math.cos(math.radians(a)), 56000 * math.sin(math.radians(a))
        obl("s_pave", L_VIL, [mx, my, 0, 66000, 7000, 350, a, 0])
    # houses in six sectors, skipping paths
    n_h = 0
    for sec in range(6):
        for k in range(50):
            a = sec * 60 + 8 + (det(sec, k, 1) % 100) / 100 * 44
            rr = 34000 + (det(sec, k, 2) % 100) / 100 * 48000
            if abs(rr - 60000) < 5200 or abs(rr - 88000) < 5200:
                continue
            aa = a % 90
            if abs(aa - 45) < 5:
                continue
            x, y = rr * math.cos(math.radians(a)), rr * math.sin(math.radians(a))
            house(x, y, a + 90 + (det(sec, k, 3) % 21) - 10, (det(sec, k, 4) % 14) * 100)
            n_h += 1
    # trees + lamps
    rng = random.Random(17)
    for k in range(40):
        a = rng.uniform(0, 360)
        rr = rng.uniform(33000, 90000)
        aa = a % 90
        if abs(aa - 45) < 6 or abs(rr - 60000) < 5000 or abs(rr - 88000) < 5000:
            continue
        tree(rr * math.cos(math.radians(a)), rr * math.sin(math.radians(a)), rng.uniform(0.8, 1.5))
    for k in range(24):
        a = k * 15 + 7.5
        for rr in (31500, 61500):
            if k % 2 == (0 if rr < 40000 else 1):
                lamp(rr * math.cos(math.radians(a)), rr * math.sin(math.radians(a)))
    n = flush()
    save()
    log(f"S3 DONE: {n} objects ({n_h} houses)")

# ══════════════ S4: rings, halo, crystal swarm, sigils, crown ══════════════
RINGS = [("ring1", 40000.0, 66000.0, 40, 2400.0, 950.0),
         ("ring2", 74000.0, 46000.0, 32, 2100.0, 850.0),
         ("ring3", 104000.0, 30000.0, 24, 1900.0, 780.0)]

def phase_s4():
    log("=== S4: RINGS + VERTICAL HALO + CRYSTALS + SIGILS + CROWN ===")
    for name, z, R, N, w, h in RINGS:
        seg = 2 * math.pi * R / N * 0.7
        for k in range(N):
            a = 360.0 * k / N
            x, y = R * math.cos(math.radians(a)), R * math.sin(math.radians(a))
            obl(f"{name}_body", L_RING, [x, y, z, seg, w, h, a + 90, 0])
            obl(f"{name}_glow", L_RING, [x, y, z - 400, seg * 0.6, w * 0.4, 380, a + 90, 0])
    # vertical gold halo behind the spire (plane XZ, center offset north)
    VR, VZ, VY, NV = 27000.0, 96000.0, 19000.0, 44
    for k in range(NV):
        a = 360.0 * k / NV
        x = VR * math.sin(math.radians(a))
        z = VZ + VR * math.cos(math.radians(a))
        seg = 2 * math.pi * VR / NV * 0.72
        obl("vring_body", L_RING, [x, VY, z, seg, 1050, 850, 0, a])
        obl("vring_glow", L_RING, [x * (1 - 900 / VR), VY, VZ + (z - VZ) * (1 - 900 / VR),
                                   seg * 0.6, 500, 420, 0, a])
    rng = random.Random(29)
    for k in range(24):
        a = rng.uniform(0, 360)
        rr = rng.uniform(22000, 58000)
        crystal(rr * math.cos(math.radians(a)), rr * math.sin(math.radians(a)),
                rng.uniform(15000, 95000), rng.uniform(1.0, 2.4),
                rng.uniform(15, 70), a, batch="crys")
    for k in range(12):
        a = rng.uniform(0, 360)
        rr = rng.uniform(30000, 75000)
        tilt = math.radians(rng.uniform(10, 40))
        cyl("sigil", L_RING, [rr * math.cos(math.radians(a)), rr * math.sin(math.radians(a)),
                              rng.uniform(25000, 85000),
                              math.sin(tilt) * math.cos(math.radians(a)),
                              math.sin(tilt) * math.sin(math.radians(a)),
                              math.cos(tilt), 280, rng.uniform(2400, 4600)])
    apex = json.load(open(os.path.join(SCRATCH, "apex.json")))["apex_z"] \
        if os.path.exists(os.path.join(SCRATCH, "apex.json")) else 128000.0
    for k in range(8):
        a = 360.0 * k / 8
        x, y = 4500 * math.cos(math.radians(a)), 4500 * math.sin(math.radians(a))
        obl("crown_body", L_RING, [x, y, apex + 1500, 1400, 260, 4200, a, 0])
        obl("crown_glow", L_RING, [x * 1.2, y * 1.2, apex + 2400, 850, 170, 2500, a, 0])
    n = flush()
    save()
    log(f"S4 DONE: {n} objects")

# ══════════════ S5: orbiting satellite islands ══════════════
def phase_s5():
    global PREFIX
    log("=== S5: ORBITING SATELLITE ISLANDS ===")
    rng = random.Random(41)
    for k in range(10):
        a = k * 36 + 10
        R = 128000 + (det(k, 2, 5) % 100) / 100 * 68000
        ztop = -12000 + (det(k, 4, 7) % 100) / 100 * 80000
        ri = 14000 + (det(k, 6, 9) % 100) / 100 * 18000
        cx, cy = R * math.cos(math.radians(a)), R * math.sin(math.radians(a))
        PREFIX = "o_"
        island_mass(cx, cy, ztop, ri, n_rock=5)
        citadel(cx, cy, ztop, min(ri / 60000, 0.4), 2)
        for t in range(3):
            ta = rng.uniform(0, 360)
            tr = rng.uniform(ri * 0.45, ri * 0.8)
            tree(cx + tr * math.cos(math.radians(ta)), cy + tr * math.sin(math.radians(ta)),
                 rng.uniform(0.7, 1.2))
        for c in range(2):
            crystal(cx + rng.uniform(-ri * 0.3, ri * 0.3), cy + rng.uniform(-ri * 0.3, ri * 0.3),
                    ztop - rng.uniform(12000, 26000) * ri / 32000, rng.uniform(1.2, 2.2),
                    rng.uniform(140, 220), a, batch="crys_o")
        if ri > 22000:
            waterfall(cx, cy, ztop, ri, a + 160)
            for hh in range(6):
                ha = rng.uniform(0, 360)
                hr = rng.uniform(ri * 0.45, ri * 0.82)
                house(cx + hr * math.cos(math.radians(ha)), cy + hr * math.sin(math.radians(ha)),
                      ha + 90, 0)
        PREFIX = ""
    n = flush()
    save()
    log(f"S5 DONE: {n} objects")

# ══════════════ MAT ══════════════
MATD = {
    "i_top":     ("grass-meadow",         "island_meadow"),
    "i_rock":    ("concrete-boardformed", "island_rock"),
    "i_crys":    ("polycarbonate-opal",   "under_crystal"),
    "w_fall":    ("polycarbonate-opal",   "waterfall"),
    "w_mist":    ("polycarbonate-opal",   "mist"),
    "p_pod":     ("stone-granite-paving", "podium"),
    "p_plat":    ("stone-granite-paving", "sky_platform"),
    "p_par":     ("brass-polished",       "parapet"),
    "c_drum":    ("plaster-white",        "citadel_drum"),
    "c_trim":    ("brass-polished",       "trim_ring"),
    "c_roof":    ("ceramic-teal",         "pagoda_roof"),
    "c_fin":     ("brass-polished",       "radial_fin"),
    "c_needle":  ("brass-polished",       "spire_needle"),
    "c_glowband": ("polycarbonate-opal",  "glow_band"),
    "c_win":     ("polycarbonate-opal",   "window_slit"),
    "c_apexglow": ("brass-polished",      "apex_orb"),
    "t_shaft":   ("plaster-white",        "tower_shaft"),
    "b_deck":    ("stone-granite-paving", "arc_bridge"),
    "b_rail":    ("brass-polished",       "bridge_rail"),
    "b_glow":    ("polycarbonate-opal",   "bridge_glow"),
    "bea_glow":  ("brass-polished",       "beacon"),
    "s_pave":    ("stone-granite-paving", "avenue"),
    "v_curb":    ("brass-polished",       "curb_trim"),
    "h_body":    ("plaster-white",        "house_body"),
    "h_roof":    ("ceramic-teal",         "house_roof"),
    "h_trim":    ("brass-polished",       "house_trim"),
    "h_win":     ("brass-polished",       "house_window"),
    "g_trunk":   ("wood-walnut",          "tree_trunk"),
    "g_leaf":    ("foliage-pine",         "tree_canopy"),
    "l_post":    ("brass-polished",       "lantern_post"),
    "l_orb":     ("brass-polished",       "lantern_orb"),
    "ring1_body": ("brass-polished",      "energy_ring"),
    "ring1_glow": ("polycarbonate-opal",  "ring_glow"),
    "ring2_body": ("brass-polished",      "energy_ring"),
    "ring2_glow": ("polycarbonate-opal",  "ring_glow"),
    "ring3_body": ("brass-polished",      "energy_ring"),
    "ring3_glow": ("polycarbonate-opal",  "ring_glow"),
    "vring_body": ("brass-polished",      "halo_ring"),
    "vring_glow": ("brass-polished",      "halo_glow"),
    "crys":      ("polycarbonate-opal",   "sky_crystal"),
    "crys_o":    ("polycarbonate-opal",   "sky_crystal"),
    "crys_static": ("polycarbonate-opal", "sky_crystal"),
    "sigil":     ("brass-polished",       "sigil_disc"),
    "crown_body": ("brass-polished",      "crown_fin"),
    "crown_glow": ("brass-polished",      "crown_glow"),
}

def matfor(batch):
    return MATD.get(batch[2:] if batch.startswith("o_") else batch)

def phase_mat():
    log("=== MAT: EMBED MATERIALS + ROLES ===")
    done = 0
    for batch, ids in sorted(G.items()):
        entry = matfor(batch)
        if not entry or not ids or DRY:
            continue
        json.loads(assign(ids, entry[0], structural_role=entry[1]))
        done += 1
        if done % 6 == 0:
            snap_frame()
    log(f"  materials embedded on {done} batches")
    save()
    log(f"MAT DONE: {sum(len(v) for v in G.values())} objects total")

# ══════════════ EXPORT ══════════════
# glow matkeys: cyan for crystals/bands/windows, gold for halo/sigil/crown/
# lantern orbs/beacons, plus soft special keys for waterfall + mist
GLOW_CYAN = {"i_crys", "c_glowband", "c_win", "b_glow", "crys", "crys_o",
             "crys_static", "ring1_glow", "ring2_glow", "ring3_glow"}
GLOW_GOLD = {"vring_glow", "sigil", "crown_glow", "l_orb", "bea_glow",
             "c_apexglow", "h_win"}
SPECIAL = {"w_fall": "waterfall", "w_mist": "mist"}
ASSEMBLIES = {
    "ring1": ["ring1_body", "ring1_glow"],
    "ring2": ["ring2_body", "ring2_glow"],
    "ring3": ["ring3_body", "ring3_glow"],
    "vring": ["vring_body", "vring_glow"],
    "crown": ["crown_body", "crown_glow"],
    "crys": ["crys"],
    "sigil": ["sigil"],
}

def _matkey(batch):
    base = batch[2:] if batch.startswith("o_") else batch
    if base in SPECIAL: return SPECIAL[base]
    if base in GLOW_CYAN: return "glowcyan"
    if base in GLOW_GOLD: return "glowgold"
    return matfor(batch)[0]

def phase_export():
    log("=== EXPORT: per-assembly/material GLBs -> Blender ===")
    glb_dir = os.path.join(SCRATCH, "sky_glb")
    os.makedirs(glb_dir, exist_ok=True)
    exporter = fn(m.export_asset_contract)
    special = {b for bs in ASSEMBLIES.values() for b in bs}
    jobs = {}
    for asm, batches in ASSEMBLIES.items():
        for b in batches:
            jobs.setdefault(f"sky-{asm}__{_matkey(b)}", []).extend(G.get(b, []))
    for batch, ids in G.items():
        if batch in special or not matfor(batch):
            continue
        asm = "islands" if batch.startswith("o_") else "static"
        jobs.setdefault(f"sky-{asm}__{_matkey(batch)}", []).extend(ids)
    for key, ids in sorted(jobs.items()):
        if not ids: continue
        r = json.loads(exporter(ids, key, output_dir=glb_dir))
        log(f"  {key}: {r.get('status')} ({len(ids)} objects)")
    log(f"EXPORT DONE -> {glb_dir}")

def phase_save3dm():
    out = os.path.join(os.path.expanduser("~"), "Documents", "almond_infinity",
                       "almond_celestia.3dm")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = json.loads(run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    doc.SaveAs(@"OUT");
    return new List<Guid>();
  }
}""".replace("OUT", out)))
    log(f"SAVE3DM: {r.get('status')} -> {out}")

PHASES = {"SUN": phase_sun, "S1": phase_s1, "S2": phase_s2, "S3": phase_s3,
          "S4": phase_s4, "S5": phase_s5, "MAT": phase_mat,
          "EXPORT": phase_export, "SAVE3DM": phase_save3dm}

if PHASE == "ALL":
    for p in ("SUN", "S1", "S2", "S3", "S4", "S5", "MAT"):
        PHASES[p]()
elif PHASE in PHASES:
    PHASES[PHASE]()
else:
    log(f"unknown phase {PHASE}; use {'|'.join(PHASES)}|ALL")
