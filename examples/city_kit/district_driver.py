"""Almond District - city-scale test with a consistent architectural detail kit.

Four city blocks + plaza (~140 x 100 m), ten buildings across five
construction systems, every building detailed by the SAME kit functions
(windows, curtain bands, balconies, cores, entrances, parapets, roof
plant, street furniture), so the architectural language stays consistent
at city scale while each typology keeps its own system.

Pipeline per building (the Almond workflow):
  1. get_construction_guidance     -> spans, depths, spacings
  2. generate via kit functions    -> consistent detail everywhere
  3. assign_material + roles       -> construction intent on the objects
  4. validate_structure / capsule  -> one span group per system (trial cap!)
  5. check_egress                  -> exits, separation, widths
  6. get_typology_narrative        -> lineage for the district dossier

Run phases from the repo root against a running Rhino (mm document):
  uv run --no-sync python examples/city_kit/district_driver.py A   # north blocks
  uv run --no-sync python examples/city_kit/district_driver.py B   # south blocks + urban
  uv run --no-sync python examples/city_kit/district_driver.py C   # checks + dossier + captures

State: GUIDs in <scratch>/district_guids.json; dossier + captures land in
the same scratch directory (set ALMOND_DISTRICT_SCRATCH to override).
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
validate = fn(m.validate_structure)

SCRATCH = os.environ.get("ALMOND_DISTRICT_SCRATCH") or os.path.join(
    tempfile.gettempdir(), "almond_district")
os.makedirs(SCRATCH, exist_ok=True)
GUIDS_PATH = os.path.join(SCRATCH, "district_guids.json")
G = json.load(open(GUIDS_PATH)) if os.path.exists(GUIDS_PATH) else {}
PHASE = (sys.argv[1] if len(sys.argv) > 1 else "A").upper()

def log(msg): print(msg, flush=True)
def fmt(vals): return ",".join(f"{v:.2f}" for v in vals)

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

def _run(batch, cs):
    r = json.loads(run_script(cs))
    if r.get("status") != "success":
        log(f"  !! {batch} FAILED: {r.get('message','')[:200]}"); return []
    G[batch] = G.get(batch, []) + r["guids"]
    return r["guids"]

def add_boxes(batch, layer, boxes):
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

def add_lines(batch, layer, lines):
    out = []
    for i in range(0, len(lines), 180):
        data = ";".join(fmt(l) for l in lines[i:i+180])
        out += _run(batch, CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var ids = new List<Guid>();
    var att = new Rhino.DocObjects.ObjectAttributes { LayerIndex = Layer(doc, "LAYER") };
    foreach (var rec in "DATA".Split(';')) {
      var v = Array.ConvertAll(rec.Split(','), double.Parse);
      ids.Add(doc.Objects.AddLine(new Line(new Point3d(v[0],v[1],v[2]), new Point3d(v[3],v[4],v[5])), att));
    }
    doc.Views.Redraw();
    return ids;
  }
}""".replace("LAYER", layer).replace("DATA", data))
    return out

def add_cylinders(batch, layer, cyls):
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

# ══════════════ THE KIT: consistent detail language ══════════════
MODULE = 3000.0        # facade module
SILL, HEAD = 900.0, 2500.0

def punched_windows(boxes_frames, boxes_glass, x0, y0, x1, y1, zb, face, depth=180):
    """Punched window units along one wall face, one per module (frame + glass)."""
    if face in ("s", "n"):
        y = y0 if face == "s" else y1
        d = -1 if face == "s" else 1
        n = int((x1 - x0) / MODULE)
        for i in range(n):
            wx = x0 + i * MODULE + 450
            boxes_frames.append([wx, y + d*10, zb + SILL - 80,
                                 wx + MODULE - 900, y + d*depth, zb + HEAD + 80])
            boxes_glass.append([wx + 80, y + d*40, zb + SILL,
                                wx + MODULE - 980, y + d*80, zb + HEAD])
    else:
        x = x0 if face == "w" else x1
        d = -1 if face == "w" else 1
        n = int((y1 - y0) / MODULE)
        for i in range(n):
            wy = y0 + i * MODULE + 450
            boxes_frames.append([x + d*10, wy, zb + SILL - 80,
                                 x + d*depth, wy + MODULE - 900, zb + HEAD + 80])
            boxes_glass.append([x + d*40, wy + 80, zb + SILL,
                                x + d*80, wy + MODULE - 980, zb + HEAD])

def curtain_band(mullions, glass, spandrels, x0, y0, x1, y1, zb, H):
    """Full-perimeter curtain band for one story: glass + mullions + spandrel."""
    glass += [[x0+60, y0-70, zb+400, x1-60, y0-40, zb+H-200],
              [x0+60, y1+40, zb+400, x1-60, y1+70, zb+H-200],
              [x0-70, y0+60, zb+400, x0-40, y1-60, zb+H-200],
              [x1+40, y0+60, zb+400, x1+70, y1-60, zb+H-200]]
    spandrels += [[x0, y0-90, zb, x1, y0, zb+400], [x0, y1, zb, x1, y1+90, zb+400],
                  [x0-90, y0, zb, x0, y1, zb+400], [x1, y0, zb, x1+90, y1, zb+400]]
    for x in range(int(x0), int(x1)+1, int(MODULE)):
        mullions += [[x-30, y0-90, zb, x+30, y0, zb+H], [x-30, y1, zb, x+30, y1+90, zb+H]]
    for y in range(int(y0), int(y1)+1, int(MODULE)):
        mullions += [[x0-90, y-30, zb, x0, y+30, zb+H], [x1, y-30, zb, x1+90, y+30, zb+H]]

def balcony(slabs, rails, x, y_face, zb, w=2400, d=1500, south=True):
    dd = -1 if south else 1
    slabs.append([x, y_face + dd*d, zb - 150, x + w, y_face, zb])
    rails.append([x, y_face + dd*d - dd*60, zb, x + 60, y_face, zb + 1050])
    rails.append([x + w - 60, y_face + dd*d - dd*60, zb, x + w, y_face, zb + 1050])
    rails.append([x, y_face + dd*d, zb + 990, x + w, y_face + dd*d + dd*60, zb + 1050])

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
    return (x0 + door_offset + 500, y0)     # door center for egress checks

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

def street_lamp(posts, heads, x, y):
    posts.append([x, y, 0, 0, 0, 1, 4500, 60])
    heads.append([x-350, y-120, 4350, x+350, y+120, 4520])

def tree(trunks, crowns, x, y):
    trunks.append([x, y, 0, 0, 0, 1, 2800, 150])
    crowns.append([x-1700, y-1700, 2800, x+1700, y+1700, 5800])

# ══════════════ district geometry ══════════════
H_RES, H_TWR, H_POD = 3000.0, 3200.0, 4500.0
BLK = {"NW": (0.0, 56000.0), "NE": (74000.0, 56000.0),
       "SW": (0.0, 0.0), "SE": (74000.0, 0.0)}
BW, BH = 64000.0, 44000.0

if PHASE == "A":
    log("=== DISTRICT PHASE A: north blocks (perimeter housing + tower podium) ===")
    g = json.loads(fn(m.get_construction_guidance)(material="Concrete", structure_type="shell", span_m=6.0))
    log("flat-plate guidance ok" if g["total"] else "!! guidance failed")

    # ── NW: 6F perimeter housing, U around courtyard (wings 13 m deep) ──
    ax, ay = BLK["NW"]
    wings = [(0, 31000, 64000, 44000), (0, 0, 13000, 31000), (51000, 0, 64000, 31000)]
    cols, slabs, wframes, wglass, balc_s, balc_r, para = [], [], [], [], [], [], []
    for (wx0, wy0, wx1, wy1) in wings:
        xs = [wx0 + i*6000 for i in range(int((wx1-wx0)/6000)+1)]
        ys = [wy0 + i*6500 for i in range(int((wy1-wy0)/6500)+1)]
        for s in range(6):
            zb = s * H_RES
            for x in xs:
                for y in ys:
                    cols.append([ax+x-175, ay+y-175, zb, ax+x+175, ay+y+175, zb+H_RES])
            slabs.append([ax+wx0, ay+wy0, zb+H_RES-200, ax+wx1, ay+wy1, zb+H_RES])
    for s in range(6):
        zb = s * H_RES
        punched_windows(wframes, wglass, ax, ay+31000, ax+64000, ay+44000, zb, "n")
        punched_windows(wframes, wglass, ax, ay, ax+13000, ay+31000, zb, "w")
        punched_windows(wframes, wglass, ax+51000, ay, ax+64000, ay+31000, zb, "e")
        if s > 0:  # courtyard balconies on the north wing's south face
            for i in range(6):
                balcony(balc_s, balc_r, ax+16000+i*5400, ay+31000, zb, south=True)
    parapet(para, ax, ay+31000, ax+64000, ay+44000, 6*H_RES)
    parapet(para, ax, ay, ax+13000, ay+31000, 6*H_RES)
    parapet(para, ax+51000, ay, ax+64000, ay+31000, 6*H_RES)
    core_walls, exit_signs = [], []
    d1 = stair_core(core_walls, exit_signs, ax+14000, ay+32000, 6, H_RES)
    d2 = stair_core(core_walls, exit_signs, ax+46000, ay+32000, 6, H_RES)
    canop, cposts, cdoors, csigns = [], [], [], []
    entrance(canop, cposts, cdoors, csigns, ax+32000, ay+44000, south=False)
    add_boxes("nw_cols", "District::NW-Perimeter::Structure", cols)
    add_boxes("nw_slabs", "District::NW-Perimeter::Structure", slabs)
    add_boxes("nw_wframes", "District::NW-Perimeter::Facade", wframes)
    add_boxes("nw_wglass", "District::NW-Perimeter::Facade", wglass)
    add_boxes("nw_balc", "District::NW-Perimeter::Balconies", balc_s)
    add_boxes("nw_rails", "District::NW-Perimeter::Balconies", balc_r)
    add_boxes("nw_parapet", "District::NW-Perimeter::Roof", para)
    add_boxes("nw_cores", "District::NW-Perimeter::Cores", core_walls)
    add_boxes("nw_exit", "District::NW-Perimeter::Wayfinding", exit_signs)
    add_boxes("nw_canopy", "District::NW-Perimeter::Entrance", canop)
    add_cylinders("nw_cposts", "District::NW-Perimeter::Entrance", cposts)
    add_boxes("nw_doors", "District::NW-Perimeter::Entrance", cdoors)
    add_boxes("nw_esign", "District::NW-Perimeter::Entrance", csigns)
    json.dump({"nw_doors_xy": [d1, d2]}, open(os.path.join(SCRATCH, "nw_meta.json"), "w"))
    log(f"NW perimeter housing: {len(cols)} cols, {len(wframes)} window units, "
        f"{len(balc_s)} balconies, 2 cores")

    # ── NE: 2F retail podium + 12F & 8F towers, consistent curtain kit ──
    bx, by = BLK["NE"]
    pcols, pslabs, mull, glas, span = [], [], [], [], []
    for s in range(2):
        zb = s * H_POD
        for x in range(0, 64001, 8000):
            for y in range(0, 44001, 8000):
                if x <= 64000 and y <= 44000:
                    pcols.append([bx+x-200, by+y-200, zb, bx+x+200, by+y+200, zb+H_POD])
        pslabs.append([bx, by, zb+H_POD-150, bx+64000, by+44000, zb+H_POD])
        curtain_band(mull, glas, span, bx, by, bx+64000, by+44000, zb, H_POD)
    towers = [("T1", bx+4000, by+9000, 26000, 26000, 12), ("T2", bx+38000, by+9000, 20000, 26000, 8)]
    tcols, tslabs, braces = [], [], []
    for (nm, tx, ty, tw, th_, nf) in towers:
        for s in range(nf):
            zb = 2*H_POD + s*H_TWR
            for x in range(0, int(tw)+1, 8000 if tw > 24000 else int(tw//2)):
                for y in range(0, int(th_)+1, 8000 if th_ > 24000 else int(th_//2)):
                    tcols.append([tx+x-200, ty+y-200, zb, tx+x+200, ty+y+200, zb+H_TWR])
            tslabs.append([tx, ty, zb+H_TWR-150, tx+tw, ty+th_, zb+H_TWR])
            curtain_band(mull, glas, span, tx, ty, tx+tw, ty+th_, zb, H_TWR)
            for (p, q) in (((tx, ty+th_, zb), (tx+8000, ty+th_, zb+H_TWR)),
                           ((tx+8000, ty+th_, zb), (tx, ty+th_, zb+H_TWR))):
                d = (q[0]-p[0], q[1]-p[1], q[2]-p[2]); ln = math.sqrt(sum(v*v for v in d))
                braces.append(list(p) + list(d) + [ln, 70])
        parapet(tslabs, tx, ty, tx+tw, ty+th_, 2*H_POD + nf*H_TWR)
    tcores, texits = [], []
    td1 = stair_core(tcores, texits, bx+6000, by+18000, 14, H_TWR)
    td2 = stair_core(tcores, texits, bx+21000, by+18000, 14, H_TWR)
    plant = [[bx+8000, by+14000, 2*H_POD+12*H_TWR, bx+14000, by+19000, 2*H_POD+12*H_TWR+2400]]
    ecad, ecp, ecd, ecs = [], [], [], []
    entrance(ecad, ecp, ecd, ecs, bx+17000, by, south=True)
    entrance(ecad, ecp, ecd, ecs, bx+48000, by, south=True)
    add_boxes("ne_pcols", "District::NE-Towers::Podium", pcols)
    add_boxes("ne_pslabs", "District::NE-Towers::Podium", pslabs)
    add_boxes("ne_tcols", "District::NE-Towers::Structure", tcols)
    add_boxes("ne_tslabs", "District::NE-Towers::Structure", tslabs)
    add_cylinders("ne_braces", "District::NE-Towers::Structure", braces)
    add_boxes("ne_mullions", "District::NE-Towers::Facade", mull)
    add_boxes("ne_glass", "District::NE-Towers::Facade", glas)
    add_boxes("ne_spandrels", "District::NE-Towers::Facade", span)
    add_boxes("ne_cores", "District::NE-Towers::Cores", tcores)
    add_boxes("ne_exit", "District::NE-Towers::Wayfinding", texits)
    add_boxes("ne_plant", "District::NE-Towers::Roof", plant)
    add_boxes("ne_canopy", "District::NE-Towers::Entrance", ecad)
    add_cylinders("ne_cposts", "District::NE-Towers::Entrance", ecp)
    add_boxes("ne_doors", "District::NE-Towers::Entrance", ecd)
    add_boxes("ne_esign", "District::NE-Towers::Entrance", ecs)
    json.dump({"tower_doors_xy": [td1, td2]}, open(os.path.join(SCRATCH, "ne_meta.json"), "w"))
    log(f"NE towers: podium + 12F/8F, {len(tcols)} tower cols, {len(mull)} mullions, twin cores")
    json.dump(G, open(GUIDS_PATH, "w"))
    log(f"PHASE A DONE: {sum(len(v) for v in G.values())} objects")
    sys.exit(0)

if PHASE == "B":
    log("=== DISTRICT PHASE B: south blocks + urban realm ===")
    # ── SW: 2 terrace rows (2F, masonry + I-joists) + 5F glulam mid-rise ──
    ax, ay = BLK["SW"]
    twalls, tjoists, trafters, twf, twg, jaxes = [], [], [], [], [], []
    for (ry, run) in ((2000.0, 4), (24000.0, 4)):
        for u in range(run + 1):
            px = ax + 2000 + u*6000
            twalls.append([px-90, ay+ry, 0, px+90, ay+ry+11000, 5800])
        for u in range(run):
            ux = ax + 2000 + u*6000
            for j in range(9):
                py = ay + ry + 900 + j*1150
                tjoists.append([ux, py-45, 2900-305, ux+6000, py+45, 2900])
                if u == 0 and ry == 2000.0 and j < 5:
                    jaxes.append([ux, py, 2900-152, ux+6000, py, 2900-152])
            for r in range(6):
                py = ay + ry + r*2100
                for (xa, xb) in ((ux, ux+3000), (ux+6000, ux+3000)):
                    d = (xb-xa, 0, 1700.0); ln = math.sqrt(d[0]*d[0]+d[2]*d[2])
                    trafters.append([xa, py, 5800, d[0], 0, d[2], ln, 60])
            for s in range(2):
                punched_windows(twf, twg, ux, ay+ry, ux+6000, ay+ry+11000, s*2900, "s")
    dposts, dbeams, ddecks, dwf, dwg, dbal_s, dbal_r, daxes = [], [], [], [], [], [], [], []
    dx, dy = ax + 36000, ay + 2000
    for s in range(5):
        zb = s * H_RES
        for x in range(0, 24001, 6000):
            for y in range(0, 16001, 8000):
                dposts.append([dx+x-105, dy+y-105, zb, dx+x+105, dy+y+105, zb+H_RES])
        for y in (0, 8000, 16000):
            for i in range(4):
                dbeams.append([dx+i*6000, dy+y-70, zb+H_RES-500, dx+(i+1)*6000, dy+y+70, zb+H_RES-100])
                if s == 1 and y == 8000 and i < 2:
                    daxes.append([dx+i*6000, dy+y, zb+H_RES-300, dx+(i+1)*6000, dy+y, zb+H_RES-300])
        ddecks.append([dx, dy, zb+H_RES-100, dx+24000, dy+16000, zb+H_RES])
        punched_windows(dwf, dwg, dx, dy, dx+24000, dy+16000, zb, "s")
        if s > 0:
            for i in range(3):
                balcony(dbal_s, dbal_r, dx+2500+i*8000, dy, zb, south=True)
    dpar = []; parapet(dpar, dx, dy, dx+24000, dy+16000, 5*H_RES)
    dcore, dexit = [], []
    ddoor = stair_core(dcore, dexit, dx+9000, dy+9000, 5, H_RES)
    add_boxes("sw_twalls", "District::SW-Terraces::Walls", twalls)
    add_boxes("sw_tjoists", "District::SW-Terraces::Joists", tjoists)
    add_cylinders("sw_trafters", "District::SW-Terraces::Rafters", trafters)
    add_boxes("sw_twf", "District::SW-Terraces::Facade", twf)
    add_boxes("sw_twg", "District::SW-Terraces::Facade", twg)
    add_lines("sw_jaxes", "District::SW-Terraces::Axes", jaxes)
    add_boxes("sw_dposts", "District::SW-Timber::Structure", dposts)
    add_boxes("sw_dbeams", "District::SW-Timber::Structure", dbeams)
    add_boxes("sw_ddecks", "District::SW-Timber::Structure", ddecks)
    add_boxes("sw_dwf", "District::SW-Timber::Facade", dwf)
    add_boxes("sw_dwg", "District::SW-Timber::Facade", dwg)
    add_boxes("sw_dbal", "District::SW-Timber::Balconies", dbal_s)
    add_boxes("sw_drail", "District::SW-Timber::Balconies", dbal_r)
    add_boxes("sw_dpar", "District::SW-Timber::Roof", dpar)
    add_boxes("sw_dcore", "District::SW-Timber::Cores", dcore)
    add_boxes("sw_dexit", "District::SW-Timber::Wayfinding", dexit)
    add_lines("sw_daxes", "District::SW-Timber::Axes", daxes)
    log(f"SW: 8 terrace units + 5F glulam mid-rise ({len(dposts)} posts)")

    # ── SE: civic pair - 24 m truss market hall + 3F timber library, plaza ──
    bx, by = BLK["SE"]
    hx, hy = bx + 2000, by + 2000
    hcols, htruss, haxes, hroof = [], [], [], []
    tys = [hy + i*6000 for i in range(6)]
    for py in tys:
        for px in (hx, hx+24000):
            hcols.append([px-160, py-160, 0, px+160, py+160, 7000])
    first = True
    for py in tys:
        bot = [(hx + i*6000, 7000.0) for i in range(5)]
        top = [(hx + 3000 + i*6000, 9200.0) for i in range(4)]
        mems = [(bot[i], bot[i+1]) for i in range(4)] + [(top[i], top[i+1]) for i in range(3)]
        for i in range(4):
            mems += [(bot[i], top[min(i, 3)]), (top[min(i, 3)], bot[i+1])]
        for (a, b) in mems:
            p, q = (a[0], py, a[1]), (b[0], py, b[1])
            d = (q[0]-p[0], q[1]-p[1], q[2]-p[2]); ln = math.sqrt(sum(v*v for v in d))
            htruss.append(list(p) + list(d) + [ln, 80])
            if first: haxes.append(list(p) + list(q))
        first = False
    hroof.append([hx-800, hy-800, 9300, hx+24800, hy+30800, 9500])
    lx, ly = bx + 34000, by + 2000
    lposts, lbeams, ldecks, lwf, lwg = [], [], [], [], []
    for s in range(3):
        zb = s * 3400
        for x in range(0, 24001, 6000):
            for y in range(0, 20001, 6667):
                lposts.append([lx+x-105, ly+y-105, zb, lx+x+105, ly+y+105, zb+3400])
        for y in (0, 6667, 13333, 20000):
            for i in range(4):
                lbeams.append([lx+i*6000, ly+y-70, zb+3400-500, lx+(i+1)*6000, ly+y+70, zb+3400-100])
        ldecks.append([lx, ly, zb+3400-100, lx+24000, ly+20000, zb+3400])
        punched_windows(lwf, lwg, lx, ly, lx+24000, ly+20000, zb, "s")
        punched_windows(lwf, lwg, lx, ly, lx+24000, ly+20000, zb, "n")
    lpar = []; parapet(lpar, lx, ly, lx+24000, ly+20000, 3*3400)
    lcore, lexit = [], []
    ldoor = stair_core(lcore, lexit, lx+9500, ly+8000, 3, 3400)
    add_boxes("se_hcolsb", "District::SE-Civic::HallColumns", hcols)
    add_cylinders("se_htruss", "District::SE-Civic::HallTrusses", htruss)
    add_lines("se_haxes", "District::SE-Civic::Axes", haxes)
    add_boxes("se_hroof", "District::SE-Civic::HallRoof", hroof)
    add_boxes("se_lposts", "District::SE-Civic::Library", lposts)
    add_boxes("se_lbeams", "District::SE-Civic::Library", lbeams)
    add_boxes("se_ldecks", "District::SE-Civic::Library", ldecks)
    add_boxes("se_lwf", "District::SE-Civic::Facade", lwf)
    add_boxes("se_lwg", "District::SE-Civic::Facade", lwg)
    add_boxes("se_lpar", "District::SE-Civic::Roof", lpar)
    add_boxes("se_lcore", "District::SE-Civic::Cores", lcore)
    add_boxes("se_lexit", "District::SE-Civic::Wayfinding", lexit)
    log(f"SE civic: 6x 24 m trusses + 3F library")

    # ── urban realm: streets, sidewalks, plaza, lamps, trees, labels ──
    streets = [[0, 44000, -60, 138000, 56000, 0], [64000, 0, -60, 74000, 100000, 0]]
    sidewalks = [[0, 44000-2500, -20, 138000, 44000, 40], [0, 56000, -20, 138000, 58500, 40],
                 [64000-2500, 0, -20, 64000, 100000, 40], [74000, 0, -20, 76500, 100000, 40]]
    plaza = [[bx+28000, by, -20, bx+33000, by+30000, 40],
             [ax+16000, ay+33000, -20, ax+48000, ay+31000+13000, 40]]
    lampsP, lampsH, trunks, crowns = [], [], [], []
    for x in range(6000, 138001, 22000):
        street_lamp(lampsP, lampsH, x, 50000)
    for y in range(6000, 100001, 22000):
        street_lamp(lampsP, lampsH, 69000, y)
    for (tx, ty) in ((20000, 50000), (44000, 50000), (95000, 50000), (120000, 50000),
                     (69000, 20000), (69000, 80000), (104000, 16000), (104000, 26000)):
        tree(trunks, crowns, tx, ty)
    add_boxes("u_streets", "District::Urban::Streets", streets)
    add_boxes("u_sidewalks", "District::Urban::Sidewalks", sidewalks)
    add_boxes("u_plaza", "District::Urban::Plaza", plaza)
    add_cylinders("u_lampp", "District::Urban::Lamps", lampsP)
    add_boxes("u_lamph", "District::Urban::Lamps", lampsH)
    add_cylinders("u_trunks", "District::Urban::Trees", trunks)
    add_boxes("u_crowns", "District::Urban::Trees", crowns)
    add_texts("u_labels", "District::Urban::Labels", [
        (10000, 92000, 0, 1600, "PERIMETER HOUSING 6F"),
        (80000, 92000, 0, 1600, "TOWERS 12F+8F ON PODIUM"),
        (4000, 15000, 0, 1400, "TERRACES 2F"),
        (38000, 20000, 0, 1400, "TIMBER 5F"),
        (78000, 34000, 0, 1400, "MARKET HALL"),
        (110000, 24000, 0, 1400, "LIBRARY 3F"),
        (103000, 8000, 0, 1200, "PLAZA"),
    ])
    json.dump({"library_door": ldoor, "timber_door": ddoor},
              open(os.path.join(SCRATCH, "sw_se_meta.json"), "w"))
    json.dump(G, open(GUIDS_PATH, "w"))
    log(f"PHASE B DONE: {sum(len(v) for v in G.values())} objects")
    sys.exit(0)

# ══════════════ PHASE C: materials, checks, narration, dossier ══════════════
log("=== DISTRICT PHASE C: materials, validation, egress, narration ===")
MAT = [
    ("nw_cols", "concrete-smooth", "column", "concrete-column-grid"),
    ("nw_slabs", "concrete-smooth", "flat_plate_slab", "concrete-flat-plate"),
    ("nw_cores", "concrete-boardformed", "shear_wall", "concrete-bearing-wall"),
    ("nw_wframes", "aluminium-anodized", "window_frame", ""),
    ("nw_wglass", "glass-clear", "window", ""),
    ("nw_balc", "concrete-smooth", "balcony_slab", ""),
    ("nw_rails", "steel-galvanized", "railing", ""),
    ("nw_parapet", "concrete-smooth", "parapet", ""),
    ("nw_exit", "steel-painted-sage", "exit_sign", ""),
    ("nw_canopy", "concrete-smooth", "entrance_canopy", ""),
    ("nw_cposts", "steel-painted-sage", "canopy_post", ""),
    ("nw_doors", "glass-laminated", "entrance_door", ""),
    ("nw_esign", "aluminium-anodized", "signage", ""),
    ("ne_pcols", "concrete-smooth", "column", "concrete-column-grid"),
    ("ne_pslabs", "concrete-smooth", "flat_plate_slab", "concrete-flat-plate"),
    ("ne_tcols", "steel-painted-sage", "column", "steel-column-frame"),
    ("ne_tslabs", "concrete-smooth", "deck_slab", "steel-wide-flange-floor"),
    ("ne_braces", "steel-galvanized", "diagonal_brace", "steel-column-frame"),
    ("ne_mullions", "aluminium-anodized", "mullion", ""),
    ("ne_glass", "glass-clear", "curtain_wall_glazing", ""),
    ("ne_spandrels", "aluminium-anodized", "spandrel", ""),
    ("ne_cores", "concrete-boardformed", "shear_wall", "concrete-bearing-wall"),
    ("ne_exit", "steel-painted-sage", "exit_sign", ""),
    ("ne_plant", "metal-corrugated", "air_handler", ""),
    ("ne_canopy", "steel-painted-sage", "entrance_canopy", ""),
    ("ne_cposts", "steel-painted-sage", "canopy_post", ""),
    ("ne_doors", "glass-laminated", "entrance_door", ""),
    ("ne_esign", "aluminium-anodized", "signage", ""),
    ("sw_twalls", "brick-red", "party_wall", "cmu-reinforced-wall"),
    ("sw_tjoists", "wood-birch-ply", "i_joist", "wood-i-joist-floor"),
    ("sw_trafters", "wood-oak", "rafter", "wood-rafter-roof"),
    ("sw_twf", "wood-oak", "window_frame", ""),
    ("sw_twg", "glass-clear", "window", ""),
    ("sw_dposts", "wood-walnut", "post", "wood-plank-and-beam-floor"),
    ("sw_dbeams", "wood-walnut", "glulam_beam", "wood-plank-and-beam-floor"),
    ("sw_ddecks", "wood-birch-ply", "plank_deck", "wood-plank-and-beam-floor"),
    ("sw_dwf", "wood-oak", "window_frame", ""),
    ("sw_dwg", "glass-clear", "window", ""),
    ("sw_dbal", "wood-birch-ply", "balcony_slab", ""),
    ("sw_drail", "steel-galvanized", "railing", ""),
    ("sw_dpar", "wood-oak", "parapet", ""),
    ("sw_dcore", "concrete-boardformed", "shear_wall", "concrete-bearing-wall"),
    ("sw_dexit", "steel-painted-sage", "exit_sign", ""),
    ("se_hcolsb", "steel-painted-sage", "column", "steel-column-frame"),
    ("se_htruss", "steel-painted-sage", "truss_member", "steel-truss-roof"),
    ("se_hroof", "metal-corrugated", "roof_deck", "steel-truss-roof"),
    ("se_lposts", "wood-walnut", "post", "wood-plank-and-beam-floor"),
    ("se_lbeams", "wood-walnut", "glulam_beam", "wood-plank-and-beam-floor"),
    ("se_ldecks", "wood-birch-ply", "plank_deck", "wood-plank-and-beam-floor"),
    ("se_lwf", "wood-oak", "window_frame", ""),
    ("se_lwg", "glass-clear", "window", ""),
    ("se_lpar", "wood-oak", "parapet", ""),
    ("se_lcore", "concrete-boardformed", "shear_wall", "concrete-bearing-wall"),
    ("se_lexit", "steel-painted-sage", "exit_sign", ""),
    ("u_streets", "rubber-black", "street", ""),
    ("u_sidewalks", "concrete-smooth", "sidewalk", ""),
    ("u_plaza", "concrete-smooth", "plaza", ""),
    ("u_lampp", "steel-galvanized", "lamp_post", ""),
    ("u_lamph", "aluminium-anodized", "lamp_head", ""),
    ("u_trunks", "wood-oak", "tree_trunk", ""),
    ("u_crowns", "wood-birch-ply", "tree_crown", ""),
]
warned = 0
for batch, mat, role, system in MAT:
    ids = G.get(batch, [])
    if not ids: continue
    r = json.loads(assign(ids, mat, structural_role=role, construction_system=system))
    if r.get("warnings"): warned += 1
log(f"materials: {len(MAT)} batches assigned ({warned} typicality warnings)")
n = stamp(G.get("nw_cores", []) + G.get("ne_cores", []) + G.get("sw_dcore", []) + G.get("se_lcore", []),
          {"almond:fire_rating": "4-hr capable (200 mm solid RC; BCI A.12)",
           "almond:fire_rating_required": "2-hr shaft enclosure (4+ stories served)"})
log(f"fire ratings stamped on {n} core panels")

log("--- validation (one span group per system; trial-safe sizes) ---")
def vreport(label, guids, stype, load, matr, expect):
    v = json.loads(validate(guids, stype, load, matr))
    res, cc = v.get("results", {}), v.get("construction_check", {})
    fit = next((s.get("fits_span") for s in cc.get("matching_systems", []) if s["system_id"] == expect), "?")
    log(f"{label}: {v.get('status')} [{res.get('analysis_method')}/{v.get('confidence')}] "
        f"span={res.get('span_m')} basis={res.get('span_basis')} {expect} fits={fit}")

vreport("SW I-joists", G["sw_jaxes"], "beam", 12.0, "Wood", "wood-i-joist-floor")
vreport("SW glulam", G["sw_daxes"], "beam", 40.0, "Wood", "wood-plank-and-beam-floor")
vreport("SE hall truss (24 m)", G["se_haxes"], "truss", 120.0, "Steel", "steel-truss-roof")
r = json.loads(run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var ids = new List<Guid>();
    var plane = new Plane(new Point3d(20000, 90000, 3000), Vector3d.ZAxis);
    var mesh = Mesh.CreateFromPlane(plane, new Interval(0, 6000), new Interval(0, 6500), 4, 4);
    ids.Add(doc.Objects.AddMesh(mesh));
    foreach (var p in new[]{ new double[]{0,0}, new double[]{6000,0}, new double[]{6000,6500}, new double[]{0,6500} })
      ids.Add(doc.Objects.AddPoint(new Point3d(20000+p[0], 90000+p[1], 3000)));
    return ids;
  }
}"""))
gp = r["guids"]
vs = json.loads(fn(m.run_gh_definition)("karamba_shell_v1",
    {"ALMOND_IN_MESH": {"guids": [gp[0]]}, "ALMOND_IN_SUPPORTS": {"guids": gp[1:]},
     "ALMOND_IN_LOAD_KNM2": -3.9}, timeout_s=240.0))
o = vs.get("outputs", {})
log(f"NW flat plate (shell capsule, -3.9 kN/m2): {vs.get('status')} "
    f"disp={float(o.get('ALMOND_OUT_DISP_MM') or 0)*10:.1f} mm mass={o.get('ALMOND_OUT_MASS_KG') or 0:.0f} kg")
run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    foreach (string s in new[] { %s }) doc.Objects.Delete(new Guid(s), true);
    return new List<Guid>();
  }
}""" % ", ".join(f'"{x}"' for x in gp))

log("--- egress ---")
ce = fn(m.check_egress)
ax, ay = BLK["NW"]; bx, by = BLK["NE"]
t = json.loads(ce(plate_bounds_mm=[bx+4000, by+9000, bx+30000, by+35000],
    exits=[{"name": "stair W", "x_mm": bx+7700, "y_mm": by+18000, "width_mm": 1120},
           {"name": "stair E", "x_mm": bx+22700, "y_mm": by+18000, "width_mm": 1120}],
    occupancy="residential", stories=12, sprinklered=True))
log(f"T1 tower: occ={t['occupant_load']}/floor passed={t['passed']}")
w = json.loads(ce(plate_bounds_mm=[ax, ay+31000, ax+64000, ay+44000],
    exits=[{"name": "core W", "x_mm": ax+15700, "y_mm": ay+32000, "width_mm": 1120},
           {"name": "core E", "x_mm": ax+47700, "y_mm": ay+32000, "width_mm": 1120}],
    occupancy="residential", stories=6, sprinklered=True))
log(f"NW north wing: occ={w['occupant_load']}/floor passed={w['passed']}")
h = json.loads(ce(plate_bounds_mm=[74000+2000, 2000, 74000+26000, 32000],
    exits=[{"name": "S doors", "x_mm": 74000+14000, "y_mm": 2000, "width_mm": 3600},
           {"name": "N doors", "x_mm": 74000+14000, "y_mm": 32000, "width_mm": 3600}],
    occupancy="assembly_unconcentrated", stories=1, sprinklered=True))
log(f"Market hall (assembly): occ={h['occupant_load']} passed={h['passed']}")

log("--- narration (get_typology_narrative) ---")
narr = fn(m.get_typology_narrative)
dossier = ["# Almond District dossier", "",
           "Generated by examples/city_kit/district_driver.py. Narratives from",
           "the typology library (A Global History of Architecture, page refs in",
           "gha_ref); structures validated per system; narration never drove geometry.", ""]
for (title, kwargs) in [
    ("NW - Perimeter housing 6F (concrete flat plate)", {"query": "courtyard"}),
    ("NE - Towers on podium (steel frame)", {"construction_system": "steel-column-frame", "query": "skyscraper"}),
    ("SW - Terraces (party walls + I-joists)", {"query": "party-wall"}),
    ("SW - Timber mid-rise (glulam)", {"query": "timber hall"}),
    ("SE - Market hall (24 m trusses)", {"query": "civic hall"}),
]:
    result = json.loads(narr(limit=1, **kwargs))
    if result["entries"]:
        e = result["entries"][0]
        dossier += [f"## {title}", "",
                    f"**Lineage: {e['name']}** ({e['era']}, {e.get('region','')}; GHA pp. {e['gha_ref']})",
                    "", e["narrative"], "", f"*Urban role:* {e.get('urban_role','')}", ""]
        log(f"  {title} <- {e['typology_id']}")
open(os.path.join(SCRATCH, "district_dossier.md"), "w", encoding="utf-8").write("\n".join(dossier))

sc = json.loads(fn(m.create_design_scene)("Almond District"))
sid = sc["scene"]["scene_id"]
for name, b in [
    ("NW perimeter housing", [0, 56000, 0, 64000, 100000, 18000]),
    ("NE towers + podium", [74000, 56000, 0, 138000, 100000, 47400]),
    ("SW terraces + timber", [0, 0, 0, 64000, 44000, 15000]),
    ("SE civic + plaza", [74000, 0, 0, 138000, 44000, 10200]),
]:
    json.loads(fn(m.upsert_design_room)(sid, name, b))
lv = json.loads(fn(m.validate_scene_layout)(sid))
log(f"scene: 4 blocks registered, layout passed={lv.get('passed')}")

cap1 = os.path.join(SCRATCH, "district_axon.png")
cap2 = os.path.join(SCRATCH, "district_plan.png")
run_script(CS_HEAD + """
  public static List<Guid> Run(RhinoDoc doc) {
    var view = doc.Views.ActiveView; var vp = view.ActiveViewport;
    vp.ChangeToPerspectiveProjection(true, 50);
    vp.SetCameraLocations(new Point3d(69000, 50000, 10000), new Point3d(200000, -80000, 90000));
    vp.ZoomBoundingBox(new BoundingBox(new Point3d(-6000,-6000,0), new Point3d(144000,106000,52000)));
    view.Redraw();
    var mode = Rhino.Display.DisplayModeDescription.FindByName("Rendered");
    view.CaptureToBitmap(new System.Drawing.Size(1700, 1050), mode).Save(@"CAP1");
    vp.SetProjection(Rhino.Display.DefinedViewportProjection.Top, null, true);
    vp.ChangeToParallelProjection(true);
    vp.ZoomBoundingBox(new BoundingBox(new Point3d(-4000,-4000,0), new Point3d(142000,104000,52000)));
    view.Redraw();
    view.CaptureToBitmap(new System.Drawing.Size(1700, 1250), mode).Save(@"CAP2");
    return new List<Guid>();
  }
}""".replace("CAP1", cap1).replace("CAP2", cap2))
log(f"captures: {os.path.exists(cap1)} {os.path.exists(cap2)}")
json.dump(G, open(GUIDS_PATH, "w"))
log(f"PHASE C DONE: {sum(len(v) for v in G.values())} district objects; dossier at {SCRATCH}")
