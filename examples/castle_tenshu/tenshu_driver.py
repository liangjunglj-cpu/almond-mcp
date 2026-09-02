"""Almond Tenshu - techno Japanese castle, aggregated outwards.

Remodel of the infinity castle after the user's reference images: the
massing of a Japanese castle (battered ishigaki stone base, a 6-tier
tenshu whose stepped roofs flare OUTWARD with deep eaves, corner yagura
turrets, and three concentric baileys - honmaru / ninomaru / sannomaru -
aggregating outward through a south gatehouse chain), rendered in a dense
techno-megastructure style: charcoal panel bodies, off-white panel
inlays, vermilion accent panels and soffits, greeble ribs and pipes, and
hot white neon lines along every eave and wall cap. Orange-glow lanterns
orbit the keep, two angular tech rings counter-rotate overhead, and a
radar-like apex array spins on the tenshu.

Phases (live Rhino mm document, bridge on 5000):
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py CLEAR   # wipe the doc (v1 castle is saved)
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py SUN     # sun + view + ground
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py T1      # ishigaki base + tenshu + annex wings
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py T2      # honmaru walls + yagura + gate
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py T3      # ninomaru + sannomaru + gates + bridge
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py T4      # rings, lanterns, apex array, pipes
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py MAT     # embed materials + roles
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py ALL     # SUN + T1..T4 + MAT
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py EXPORT  # per-assembly/material GLBs
  uv run --no-sync python examples/castle_tenshu/tenshu_driver.py SAVE3DM

Moving assemblies exported as tns-<assembly>__<matkey>.glb; "glow" is the
white neon, "gloworange" the lantern/ring accent glow. Sun matches the
v2 session's panel values. ALMOND_DRY=1 dry-runs; ALMOND_CAPTURE=1 snaps
per-batch frames.
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

SCRATCH = os.environ.get("ALMOND_TNS_SCRATCH") or os.path.join(
    tempfile.gettempdir(), "almond_tenshu")
os.makedirs(SCRATCH, exist_ok=True)
GUIDS_PATH = os.path.join(SCRATCH, "tenshu_guids.json")
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

# ══════════════ batch accumulators ══════════════
B_OBL, B_CYL, B_BOX = {}, {}, {}
LAYERS = {}

def obl(batch, layer, rec):
    B_OBL.setdefault(batch, []).append(rec); LAYERS[batch] = layer

def cyl(batch, layer, rec):
    B_CYL.setdefault(batch, []).append(rec); LAYERS[batch] = layer

def box(batch, layer, rec):
    B_BOX.setdefault(batch, []).append(rec); LAYERS[batch] = layer

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

def det(i, j, k):
    """Deterministic pseudo-random 0..99 for panel patterns."""
    return ((i * 73856093) ^ (j * 19349663) ^ (k * 83492791)) % 100

# ══════════════ THE TENSHU KIT ══════════════
L_BASE = "Tenshu::Stone"
L_KEEP = "Tenshu::Keep"
L_ROOF = "Tenshu::Roofs"
L_PANEL = "Tenshu::Panels"
L_GLOW = "Tenshu::Neon"
L_WALL = "Tenshu::Walls"
L_YAG = "Tenshu::Yagura"
L_GATE = "Tenshu::Gates"
L_GREEB = "Tenshu::Greeble"

def ishigaki(cx, cy, z0, L, W, H, steps=5, batch="st_base"):
    """Battered stone base: stepped stack, each step inset (slope ~0.55H)."""
    inset = 0.55 * H
    for k in range(steps):
        t = k / steps
        Lk = L - 2 * inset * t
        Wk = W - 2 * inset * t
        obl(batch, L_BASE, [cx, cy, z0 + H * t, Lk, Wk, H / steps * 1.06, 0, 0])
    return z0 + H, L - 2 * inset, W - 2 * inset

def roof(cx, cy, z, L, W, yaw, sc=1.0, neon=True, finial=True):
    """Flared stepped hip roof: 3 shrinking slabs + pitched eave skirts +
    vermilion soffit strips + neon eave lines + ridge finials."""
    ov = max(2600 * sc, 900)
    t = max(560 * sc, 220)
    obl("r_slab", L_ROOF, [cx, cy, z, L + 2 * ov, W + 2 * ov, t, yaw, 0])
    obl("r_slab", L_ROOF, [cx, cy, z + t, L + 1.1 * ov, W + 1.1 * ov, t, yaw, 0])
    obl("r_slab", L_ROOF, [cx, cy, z + 2 * t, L + 0.35 * ov, W + 0.35 * ov, t, yaw, 0])
    # eave skirts, tipped outward-down
    sk = ov * 1.55
    for ex, ey, ang, run in ((1, 0, 0, W + 2 * ov), (-1, 0, 180, W + 2 * ov),
                             (0, 1, 90, L + 2 * ov), (0, -1, 270, L + 2 * ov)):
        half = (L / 2 + ov * 0.72) if ex else (W / 2 + ov * 0.72)
        dx, dy = rot2(ex * half, ey * half, yaw)
        obl("r_skirt", L_ROOF, [cx + dx, cy + dy, z + t * 0.55, sk, run * 0.94,
                                max(200 * sc, 90), yaw + ang, 22])
    # vermilion soffit strips under the eave edge
    for ex, ey, ang, run in ((1, 0, 90, W + 2 * ov), (-1, 0, 90, W + 2 * ov),
                             (0, 1, 0, L + 2 * ov), (0, -1, 0, L + 2 * ov)):
        half = (L / 2 + ov * 0.92) if ex else (W / 2 + ov * 0.92)
        dx, dy = rot2(ex * half, ey * half, yaw)
        obl("r_soffit", L_ROOF, [cx + dx, cy + dy, z - max(170 * sc, 80),
                                 run * 0.9, max(320 * sc, 130), max(170 * sc, 80), yaw + ang, 0])
    if neon:
        for ex, ey, ang, run in ((1, 0, 90, W + 2 * ov), (-1, 0, 90, W + 2 * ov),
                                 (0, 1, 0, L + 2 * ov), (0, -1, 0, L + 2 * ov)):
            half = (L / 2 + ov) if ex else (W / 2 + ov)
            dx, dy = rot2(ex * half, ey * half, yaw)
            obl("glow", L_GLOW, [cx + dx, cy + dy, z + t * 0.9, run * 0.96,
                                 max(150 * sc, 70), max(150 * sc, 70), yaw + ang, 0])
    if finial:
        along = L >= W
        off = (L * 0.22) if along else (W * 0.22)
        for s in (-1, 1):
            dx, dy = rot2(s * off if along else 0, 0 if along else s * off, yaw)
            obl("r_fin", L_ROOF, [cx + dx, cy + dy, z + 3 * t,
                                  max(360 * sc, 150), max(140 * sc, 70), max(1000 * sc, 380), yaw, 0])
    return z + 3 * t

def tier(cx, cy, z, L, W, h, yaw, ti, sc=1.0, density=100):
    """One keep storey: charcoal body + panel inlays + window band + roof."""
    obl("t_body", L_KEEP, [cx, cy, z, L, W, h, yaw, 0])
    for face, run, dep in ((0, L, W), (1, W, L)):
        n = max(int(run / (3600 * max(sc, 0.55))), 2)
        cell = run / n
        for side in (-1, 1):
            for i in range(n):
                r = det(ti * 7 + face, i, side + 3)
                if r >= density: continue
                u = (i + 0.5) * cell - run / 2
                dx, dy = rot2(u if face == 0 else side * (dep / 2 + 80),
                              side * (dep / 2 + 80) if face == 0 else u, yaw)
                px, py = cx + dx, cy + dy
                ang = yaw if face == 0 else yaw + 90
                if r < 34:
                    obl("p_light", L_PANEL, [px, py, z + h * 0.18, cell * 0.72, 160, h * 0.55, ang, 0])
                elif r < 52:
                    obl("p_verm", L_PANEL, [px, py, z + h * 0.22, cell * 0.62, 170, h * 0.42, ang, 0])
                elif r < 66:
                    obl("p_glow", L_GLOW, [px, py, z + h * 0.62, cell * 0.5, 130, h * 0.12, ang, 0])
                elif r < 80:
                    obl("p_dark", L_PANEL, [px, py, z + h * 0.12, cell * 0.8, 120, h * 0.68, ang, 0])
    # dark window band near the top of the storey
    for ex, ey, ang in ((0, 1, 0), (0, -1, 0), (1, 0, 90), (-1, 0, 90)):
        half = (W / 2 + 60) if ey else (L / 2 + 60)
        dx, dy = rot2(ex * half, ey * half, yaw)
        run = (L if ey else W) * 0.78
        obl("t_win", L_KEEP, [cx + dx, cy + dy, z + h * 0.8, run, 110, h * 0.13, yaw + ang, 0])
    return roof(cx, cy, z + h, L, W, yaw, sc)

def yagura(cx, cy, z0, s, yaw=0.0, tiers=2):
    """Corner turret: a mini-tenshu at scale s."""
    F = 15000 * s
    zt, Lb, Wb = ishigaki(cx, cy, z0, F * 1.5, F * 1.35, 5200 * s, steps=3, batch="y_base")
    L, W = F, F * 0.88
    for ti in range(tiers):
        h = 4600 * s * (0.9 ** ti)
        zt = tier(cx, cy, zt, L, W, h, yaw, ti + 11, sc=s * 0.8, density=62)
        L, W = L * 0.8, W * 0.8
    return zt

def wall_run(x0, y0, x1, y1, rib_step=5200, tag=0):
    """Bailey wall: stone strip base, plaster body, dark cap with skirts,
    neon top line, greeble ribs and vermilion accents on the outer face."""
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    yaw = math.degrees(math.atan2(dy, dx))
    cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
    # outward = away from origin
    nx, ny = -dy / ln, dx / ln
    if nx * cxm + ny * cym < 0:
        nx, ny = -nx, -ny
    obl("w_base", L_BASE, [cxm, cym, 0, ln, 3600, 2600, yaw, 0])
    obl("w_base", L_BASE, [cxm, cym, 2600, ln, 2800, 1300, yaw, 0])
    obl("w_body", L_WALL, [cxm, cym, 3900, ln, 1700, 4400, yaw, 0])
    obl("w_cap", L_WALL, [cxm, cym, 8300, ln * 1.012, 3000, 420, yaw, 0])
    # eave skirts: local X is the outward cross dimension so the pitch tips
    # the skirt edge down, not the whole run
    yaw_n = math.degrees(math.atan2(ny, nx))
    for s in (-1, 1):
        obl("w_skirt", L_WALL, [cxm + nx * s * 1550, cym + ny * s * 1550, 8500,
                                1500, ln * 0.99, 170, yaw_n if s > 0 else yaw_n + 180, 20])
    obl("glow", L_GLOW, [cxm, cym, 8760, ln * 0.99, 150, 150, yaw, 0])
    n_rib = int(ln / rib_step)
    for i in range(n_rib):
        u = (i + 0.5) * rib_step - ln / 2
        px = cxm + (dx / ln) * u + nx * 1000
        py = cym + (dy / ln) * u + ny * 1000
        obl("w_rib", L_GREEB, [px, py, 3900, 260, 300, 3300, yaw, 0])
        if det(tag, i, 5) < 30:
            obl("p_verm", L_PANEL, [px, py, 4700, 1900, 150, 1900, yaw, 0])
    return ln

def gatehouse(cx, cy, yaw=0.0, s=1.0):
    """Gatehouse: stone flanks, deck, roofed tower, vermilion doors, neon."""
    w = 11000 * s
    for sgn in (-1, 1):
        fx, fy = rot2(sgn * (w / 2 + 4200 * s), 0, yaw)
        ishigaki(cx + fx, cy + fy, 0, 8000 * s, 7000 * s, 7800 * s, steps=3, batch="g_base")
    dxc, dyc = rot2(0, 0, yaw)
    obl("g_deck", L_GATE, [cx + dxc, cy + dyc, 7800 * s, w + 9500 * s, 7400 * s, 1500 * s, yaw, 0])
    zt = tier(cx, cy, 9300 * s, w + 7000 * s, 6200 * s, 4300 * s, yaw, 23, sc=0.62 * s, density=55)
    for sgn in (-1, 1):
        dx2, dy2 = rot2(sgn * w / 4, 0, yaw)
        obl("g_door", L_GATE, [cx + dx2, cy + dy2, 0, w / 2 * 0.92, 420 * s, 6800 * s, yaw, 0])
    obl("glow", L_GLOW, [cx, cy, 7050 * s, w * 1.04, 260 * s, 240 * s, yaw, 0])
    for sgn in (-1, 1):
        dx3, dy3 = rot2(sgn * (w / 2 + 350 * s), 0, yaw)
        obl("glow", L_GLOW, [cx + dx3, cy + dy3, 0, 240 * s, 240 * s, 7000 * s, yaw, 0])
    for sgn in (-1, 1):
        dx4, dy4 = rot2(sgn * (w / 2 + 4200 * s), 3800 * s, yaw)
        obl("g_banner", L_GATE, [cx + dx4, cy + dy4, 8100 * s, 1500 * s, 220 * s, 5200 * s, yaw, 0])
    return zt

# all bailey wall runs (x0, y0, x1, y1) - shared by T2/T3 and FIX1
GW = 12000
RUNS = [
    (-48000, -42000, -GW / 2 - 5800, -42000), (GW / 2 + 5800, -42000, 48000, -42000),
    (-48000, 42000, 48000, 42000), (-48000, -42000, -48000, 42000), (48000, -42000, 48000, 42000),
    (-72000, -64000, -GW / 2 - 5800, -64000), (GW / 2 + 5800, -64000, 72000, -64000),
    (-72000, 64000, 72000, 64000), (-72000, -64000, -72000, 64000),
    (72000, -64000, 72000, -GW / 2 - 5800), (72000, GW / 2 + 5800, 72000, 64000),
    (-98000, -88000, -GW / 2 - 5800, -88000), (GW / 2 + 5800, -88000, 98000, -88000),
    (-98000, 88000, 98000, 88000), (-98000, -88000, -98000, 88000), (98000, -88000, 98000, 88000),
]

def emit_skirts(x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
    nx, ny = -dy / ln, dx / ln
    if nx * cxm + ny * cym < 0:
        nx, ny = -nx, -ny
    yaw_n = math.degrees(math.atan2(ny, nx))
    for s in (-1, 1):
        obl("w_skirt", L_WALL, [cxm + nx * s * 1550, cym + ny * s * 1550, 8500,
                                1500, ln * 0.99, 170, yaw_n if s > 0 else yaw_n + 180, 20])

def phase_fix1():
    """Replace the mis-pitched wall skirts (giant diagonal blades)."""
    log("=== FIX1: re-pitch wall skirts ===")
    ids = G.get("w_skirt", [])
    if ids and not DRY:
        arr = ", ".join(f'"{g}"' for g in ids)
        run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    foreach (string s in new[] { ARR }) {
      var obj = doc.Objects.FindId(new Guid(s));
      if (obj != null) doc.Objects.Delete(obj.Id, true);
    }
    doc.Views.Redraw();
    return new List<Guid>();
  }
}""".replace("ARR", arr))
    G["w_skirt"] = []
    for (x0, y0, x1, y1) in RUNS:
        emit_skirts(x0, y0, x1, y1)
    n = flush()
    save()
    log(f"FIX1 DONE: {n} skirts re-emitted")

# ══════════════ CLEAR ══════════════
def phase_clear():
    log("=== CLEAR: wipe doc (previous castle already saved to 3dm) ===")
    global G
    if not DRY:
        run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var kill = new List<Guid>();
    foreach (var o in doc.Objects) kill.Add(o.Id);
    foreach (var id in kill) doc.Objects.Delete(id, true);
    doc.Views.Redraw();
    return new List<Guid>();
  }
}""")
    G = {}
    json.dump(G, open(GUIDS_PATH, "w"))
    log("doc cleared")

# ══════════════ SUN ══════════════
SUN_STATE = os.path.join(SCRATCH, "sun_state.json")

def phase_sun():
    log("=== SUN + VIEW ===")
    if not G.get("g_ground"):
        add_boxes("g_ground", "Tenshu::Site::Ground",
                  [[-320000, -320000, -380, 320000, 320000, -80]])
        add_boxes("g_apron", "Tenshu::Site::Apron",
                  [[-112000, -102000, -80, 112000, 102000, 40]])
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
    vp.SetCameraLocations(new Point3d(0, 0, 30000), new Point3d(195000, -160000, 85000));
    vp.Camera35mmLensLength = 40;
    var mode = Rhino.Display.DisplayModeDescription.FindByName("Rendered");
    if (mode != null) vp.DisplayMode = mode;
    view.Redraw();
    return new List<Guid>();
  }
}""".replace("SUNSTATE", SUN_STATE)))
    log(f"sun set: {r.get('status')}; state -> {SUN_STATE}")
    save()

# ══════════════ T1: base + tenshu + annex wings ══════════════
def phase_t1():
    log("=== T1: ISHIGAKI BASE + TENSHU + ANNEX WINGS ===")
    zt, Lb, Wb = ishigaki(0, 0, 0, 42000, 37000, 14000, steps=5)
    L, W = 24500, 20500
    for ti in range(6):
        h = 6500 * (0.88 ** ti)
        sc = L / 24500
        zt = tier(0, 0, zt, L, W, h, 0, ti, sc=max(sc, 0.42), density=82)
        L, W = L * 0.84, W * 0.84
    json.dump({"apex_z": zt}, open(os.path.join(SCRATCH, "apex.json"), "w"))
    # annex wings: terraces aggregating outward east + west
    for sx in (-1, 1):
        for k, (off, fh) in enumerate(((25500, 10500), (33500, 7200), (40500, 4200))):
            ax = sx * off
            obl("t_body", L_KEEP, [ax, 0, 0, 12500, 14500 - k * 1800, fh, 0, 0])
            roof(ax, 0, fh, 12500, 14500 - k * 1800, 0, sc=0.5, finial=False)
            if k == 0:
                obl("p_verm", L_PANEL, [ax, -(14500 / 2 + 90), fh * 0.35, 8000, 180, fh * 0.4, 0, 0])
    n = flush()
    save()
    log(f"T1 DONE: {n} objects, tenshu apex z={zt/1000:.1f} m")

# ══════════════ T2: honmaru ══════════════
def phase_t2():
    log("=== T2: HONMARU WALLS + YAGURA + GATE ===")
    X, Y, GW = 48000, 42000, 12000
    wall_run(-X, -Y, -GW / 2 - 5800, -Y, tag=1)
    wall_run(GW / 2 + 5800, -Y, X, -Y, tag=2)
    wall_run(-X, Y, X, Y, tag=3)
    wall_run(-X, -Y, -X, Y, tag=4)
    wall_run(X, -Y, X, Y, tag=5)
    for cx, cy in ((-X, -Y), (X, -Y), (-X, Y), (X, Y)):
        yagura(cx, cy, 0, 0.5)
    gatehouse(0, -Y, yaw=0, s=1.0)
    n = flush()
    save()
    log(f"T2 DONE: {n} objects")

# ══════════════ T3: ninomaru + sannomaru + bridge ══════════════
def phase_t3():
    log("=== T3: NINOMARU + SANNOMARU + GATES + BRIDGE ===")
    X2, Y2, GW = 72000, 64000, 12000
    wall_run(-X2, -Y2, -GW / 2 - 5800, -Y2, rib_step=6200, tag=6)
    wall_run(GW / 2 + 5800, -Y2, X2, -Y2, rib_step=6200, tag=7)
    wall_run(-X2, Y2, X2, Y2, rib_step=6200, tag=8)
    wall_run(-X2, -Y2, -X2, Y2, rib_step=6200, tag=9)
    wall_run(X2, -Y2, X2, -GW / 2 - 5800, rib_step=6200, tag=10)
    wall_run(X2, GW / 2 + 5800, X2, Y2, rib_step=6200, tag=11)
    for cx, cy in ((-X2, -Y2), (X2, -Y2), (-X2, Y2), (X2, Y2)):
        yagura(cx, cy, 0, 0.38)
    gatehouse(0, -Y2, yaw=0, s=0.85)
    gatehouse(X2, 0, yaw=90, s=0.8)
    X3, Y3 = 98000, 88000
    wall_run(-X3, -Y3, -GW / 2 - 5800, -Y3, rib_step=7000, tag=12)
    wall_run(GW / 2 + 5800, -Y3, X3, -Y3, rib_step=7000, tag=13)
    wall_run(-X3, Y3, X3, Y3, rib_step=7000, tag=14)
    wall_run(-X3, -Y3, -X3, Y3, rib_step=7000, tag=15)
    wall_run(X3, -Y3, X3, Y3, rib_step=7000, tag=16)
    for cx, cy in ((-X3, -Y3), (X3, -Y3), (-X3, Y3), (X3, Y3)):
        yagura(cx, cy, 0, 0.3)
    gatehouse(0, -Y3, yaw=0, s=0.75)
    # approach bridge south, neon-edged
    box("b_deck", "Tenshu::Site::Bridge", [-4200, -158000, 2400, 4200, -88000, 3600])
    for sx in (-1, 1):
        box("glow", L_GLOW, [sx * 4200, -158000, 3500, sx * 4520, -88000, 3760])
    for k in range(6):
        cyl("b_post", "Tenshu::Site::Bridge", [0, -152000 + k * 11000, 0, 0, 0, 1, 2400, 900])
    n = flush()
    save()
    log(f"T3 DONE: {n} objects")

# ══════════════ T4: motion assemblies + greeble ══════════════
def phase_t4():
    log("=== T4: RINGS + LANTERNS + APEX ARRAY + PIPES ===")
    apex = json.load(open(os.path.join(SCRATCH, "apex.json")))["apex_z"] \
        if os.path.exists(os.path.join(SCRATCH, "apex.json")) else 52000.0
    # two angular tech rings
    for name, z, R, N in (("ring1", 52000.0, 64000.0, 30), ("ring2", 74000.0, 42000.0, 24)):
        seg = 2 * math.pi * R / N * 0.66
        for k in range(N):
            a = 360.0 * k / N
            x, y = R * math.cos(math.radians(a)), R * math.sin(math.radians(a))
            obl(f"{name}_body", f"Tenshu::Rings::{name}", [x, y, z, seg, 2700, 1150, a + 90, 0])
            obl(f"{name}_glow", f"Tenshu::Rings::{name}", [x, y, z - 460, seg * 0.55, 900, 420, a + 90, 0])
    # lantern swarm: orange cubes with dark caps, at 15deg spacing
    for k in range(24):
        a = k * 15.0
        R = 52000 + (det(k, 3, 9) % 50) * 1000
        z = 16000 + (det(k, 5, 7) % 46) * 1000
        x, y = R * math.cos(math.radians(a)), R * math.sin(math.radians(a))
        obl("lan_glow", "Tenshu::Lanterns", [x, y, z, 1350, 1350, 1350, a, 0])
        obl("lan_cap", "Tenshu::Lanterns", [x, y, z + 1350, 1650, 1650, 280, a, 0])
    # rotating apex array on the tenshu
    cyl("ap_mast", "Tenshu::Apex", [0, 0, apex, 0, 0, 1, 7500, 420])
    for k in range(8):
        a = 360.0 * k / 8
        x, y = 3300 * math.cos(math.radians(a)), 3300 * math.sin(math.radians(a))
        obl("ap_fin", "Tenshu::Apex", [x, y, apex + 2100, 1250, 260, 4300, a, 0])
        obl("ap_glow", "Tenshu::Apex", [x * 1.16, y * 1.16, apex + 3100, 800, 170, 2500, a, 0])
    cyl("ap_glow", "Tenshu::Apex", [0, 0, apex + 7500, 0, 0, 1, 700, 520])
    # pipe runs along the sannomaru base + vertical stacks
    for k in range(8):
        y = -86000 + k * 1100
        cyl("pipes", L_GREEB, [-60000, y, 900 + k * 380, 1, 0, 0, 120000, 260])
    for k in range(10):
        x = -81000 + k * 18000
        cyl("pipes", L_GREEB, [x, -85200, 0, 0, 0, 1, 6200 + (det(k, 2, 4) % 30) * 100, 420])
    n = flush()
    save()
    log(f"T4 DONE: {n} objects")

# ══════════════ MAT ══════════════
MAT = [
    ("g_ground",  "concrete-smooth",        "site_ground"),
    ("g_apron",   "rubber-black",           "dark_apron"),
    ("st_base",   "concrete-boardformed",   "ishigaki_base"),
    ("y_base",    "concrete-boardformed",   "ishigaki_base"),
    ("w_base",    "concrete-boardformed",   "wall_base"),
    ("g_base",    "concrete-boardformed",   "gate_base"),
    ("t_body",    "steel-painted-charcoal", "keep_storey"),
    ("t_win",     "rubber-black",           "window_band"),
    ("r_slab",    "steel-painted-charcoal", "roof_slab"),
    ("r_skirt",   "steel-painted-charcoal", "eave_skirt"),
    ("r_soffit",  "steel-painted-vermilion", "eave_soffit"),
    ("r_fin",     "steel-painted-vermilion", "ridge_finial"),
    ("p_light",   "aluminium-anodized",     "panel_inlay"),
    ("p_verm",    "steel-painted-vermilion", "accent_panel"),
    ("p_dark",    "rubber-black",           "recessed_panel"),
    ("w_body",    "plaster-white",          "bailey_wall"),
    ("w_cap",     "steel-painted-charcoal", "wall_cap"),
    ("w_skirt",   "steel-painted-charcoal", "wall_eave"),
    ("w_rib",     "steel-galvanized",       "wall_rib"),
    ("g_deck",    "steel-painted-charcoal", "gate_deck"),
    ("g_door",    "steel-painted-vermilion", "gate_door"),
    ("g_banner",  "steel-painted-vermilion", "gate_banner"),
    ("b_deck",    "concrete-smooth",        "approach_bridge"),
    ("b_post",    "steel-painted-charcoal", "bridge_post"),
    ("pipes",     "steel-galvanized",       "service_pipe"),
    ("glow",      "polycarbonate-opal",     "neon_line"),
    ("p_glow",    "polycarbonate-opal",     "neon_slit"),
    ("ring1_body", "steel-painted-charcoal", "tech_ring"),
    ("ring1_glow", "brick-red",             "ring_glow"),
    ("ring2_body", "steel-painted-charcoal", "tech_ring"),
    ("ring2_glow", "brick-red",             "ring_glow"),
    ("lan_glow",  "brick-red",              "lantern"),
    ("lan_cap",   "steel-painted-charcoal", "lantern_cap"),
    ("ap_mast",   "steel-galvanized",       "apex_mast"),
    ("ap_fin",    "steel-painted-charcoal", "apex_fin"),
    ("ap_glow",   "brick-red",              "apex_glow"),
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

# ══════════════ EXPORT ══════════════
ASSEMBLIES = {
    "ring1": ["ring1_body", "ring1_glow"],
    "ring2": ["ring2_body", "ring2_glow"],
    "lanterns": ["lan_glow", "lan_cap"],
    "apex": ["ap_mast", "ap_fin", "ap_glow"],
}
GLOW_WHITE = {"glow", "p_glow"}
GLOW_ORANGE = {"ring1_glow", "ring2_glow", "lan_glow", "ap_glow"}

def _matkey(batch):
    if batch in GLOW_WHITE: return "glow"
    if batch in GLOW_ORANGE: return "gloworange"
    return next(mt for b, mt, _ in MAT if b == batch)

def phase_export():
    log("=== EXPORT: per-assembly/material GLBs -> Blender ===")
    glb_dir = os.path.join(SCRATCH, "tns_glb")
    os.makedirs(glb_dir, exist_ok=True)
    exporter = fn(m.export_asset_contract)
    special = {b for bs in ASSEMBLIES.values() for b in bs}
    jobs = {}
    for asm, batches in ASSEMBLIES.items():
        for b in batches:
            jobs.setdefault(f"tns-{asm}__{_matkey(b)}", []).extend(G.get(b, []))
    for batch, mat, _ in MAT:
        if batch in special: continue
        jobs.setdefault(f"tns-static__{_matkey(batch)}", []).extend(G.get(batch, []))
    for key, ids in sorted(jobs.items()):
        if not ids: continue
        r = json.loads(exporter(ids, key, output_dir=glb_dir))
        log(f"  {key}: {r.get('status')} ({len(ids)} objects)")
    log(f"EXPORT DONE -> {glb_dir}")

def phase_save3dm():
    out = os.path.join(os.path.expanduser("~"), "Documents", "almond_infinity",
                       "almond_tenshu.3dm")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = json.loads(run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    doc.SaveAs(@"OUT");
    return new List<Guid>();
  }
}""".replace("OUT", out)))
    log(f"SAVE3DM: {r.get('status')} -> {out}")

PHASES = {"CLEAR": phase_clear, "SUN": phase_sun, "T1": phase_t1, "T2": phase_t2,
          "T3": phase_t3, "T4": phase_t4, "MAT": phase_mat, "FIX1": phase_fix1,
          "EXPORT": phase_export, "SAVE3DM": phase_save3dm}

if PHASE == "ALL":
    for p in ("SUN", "T1", "T2", "T3", "T4", "MAT"):
        PHASES[p]()
elif PHASE in PHASES:
    PHASES[PHASE]()
else:
    log(f"unknown phase {PHASE}; use {'|'.join(PHASES)}|ALL")
