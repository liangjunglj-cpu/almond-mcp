"""Capture documentation stills of the native structural engine in Rhino (A07 mezzanine frame).

Drives the real MCP tool code (almond_mcp.server.visualize_structure) against the live bridge and
saves 1920x1080 ViewCaptures to ~/Documents/almond_promo/native_doc. Run from the repo root:

    uv run python examples/almond_promo/native_doc_capture.py
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
from bridge import run_cs                      # noqa: E402
import shot                                     # noqa: E402
from almond_mcp import server                  # noqa: E402

OUT = Path(r"C:\Users\liang\Documents\almond_promo\native_doc")
OUT.mkdir(parents=True, exist_ok=True)
F = json.load(open(r"C:\Users\liang\Documents\almond_promo\frame_ids.json"))
GUIDS = F["beams"] + F["columns"] + F["wall"] + F["bases"]
LINE = [F["columns"][1], F["beams"][8], F["beams"][9]]       # frame line y = 5.0 m (section A-A)
SIZES = [(114.3, 4.0), (139.7, 5.0), (168.3, 6.3), (193.7, 8.0)]
LOG = []

CAP = r'''var jpg = System.Drawing.Imaging.ImageCodecInfo.GetImageEncoders().First(c => c.MimeType == "image/jpeg");
var ep = new System.Drawing.Imaging.EncoderParameters(1); ep.Param[0] = new System.Drawing.Imaging.EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 93L);
var lay = doc.Layers.FindName("A07 / 16 Structure"); if (lay != null) { lay.IsVisible = false; lay.CommitChanges(); }
doc.Views.Redraw(); RhinoApp.Wait();
var vc = new Rhino.Display.ViewCapture { Width = 1920, Height = 1080, ScaleScreenItems = false, DrawAxes = false, DrawGrid = false, DrawGridAxes = false };
using (var bmp = vc.CaptureToBitmap(doc.Views.ActiveView)) bmp.Save(@"PATH", jpg, ep);
log.Append("ok");'''

SECTION = r'''foreach (var c in doc.Objects.FindByObjectType(ObjectType.ClipPlane)) doc.Objects.Delete(c, true);
var vp = doc.Views.ActiveView.ActiveViewport;
doc.Objects.AddClippingPlane(new Plane(new Point3d(6400, 5000, 3000), -Vector3d.XAxis, Vector3d.ZAxis), 40000, 30000, vp.Id);
vp.ChangeToParallelProjection(true);
vp.SetCameraLocations(new Point3d(8883, 5000, 3354), new Point3d(8883, -60000, 3354));
double V = 11170, asp = (double)vp.Size.Width / vp.Size.Height; double l, r, b, t, n, f; vp.GetFrustum(out l, out r, out b, out t, out n, out f);
var vi = new ViewportInfo(vp); vi.SetFrustum(-V / 2 * asp, V / 2 * asp, -V / 2, V / 2, n, f); vp.SetViewProjection(vi, true);
doc.Views.Redraw(); log.Append("section");'''

UNCLIP = r'''foreach (var c in doc.Objects.FindByObjectType(ObjectType.ClipPlane)) doc.Objects.Delete(c, true); doc.Modified = false; log.Append("unclip");'''


def view(name, **kw):
    t = time.perf_counter()
    out = json.loads(server.visualize_structure(guids=GUIDS, fixed_supports=False, span_m=6.2,
                                                color_by="utilization", scale=5, **kw))
    ms = (time.perf_counter() - t) * 1000
    run_cs(CAP.replace("PATH", str(OUT / f"{name}.jpg")), quiet=True)
    row = {"name": name, "engine": out.get("analysis_method"), "status": out.get("status"),
           "max_mm": out.get("max_displacement_mm"), "util": out.get("max_utilization"), "ms": round(ms)}
    LOG.append(row)
    print(row, flush=True)


def main():
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    for i, (d, w) in enumerate(SIZES):
        view(f"iter_{i}", load_kn=150, beam_diameter_mm=d, beam_wall_mm=w,
             title=f"ALMOND  //  NATIVE FEA  ·  ITERATION {i + 1}/4  ·  CHS {d}x{w}")
    for q in (0, 25, 50, 75, 100, 125, 150):
        view(f"ramp_{q:03d}", load_kn=max(q, 0.001), beam_diameter_mm=114.3, beam_wall_mm=4.0,
             title=f"ALMOND  //  NATIVE FEA  ·  LOAD {q} kN")
    if not os.environ.get("SKIP_KARAMBA"):   # comparison shot; needs Karamba loaded
        view("karamba_114", load_kn=150, beam_diameter_mm=114.3, beam_wall_mm=4.0, engine="karamba",
             title="ALMOND  //  KARAMBA 3.1  ·  CHS 114.3x4")
    view("native_114", load_kn=150, beam_diameter_mm=114.3, beam_wall_mm=4.0, engine="native",
         title="ALMOND  //  NATIVE FEA  ·  CHS 114.3x4")
    # the whole Rhino window with the native overlay, for context
    run_cs('RhinoApp.ClearCommandHistoryWindow(); RhinoApp.WriteLine("Almond: native FEA, Karamba assemblies loaded: " + '
           'AppDomain.CurrentDomain.GetAssemblies().Count(a => a.GetName().Name.ToLower().Contains("karamba"))); log.Append("ok");', quiet=True)
    h = shot.rhino_hwnd()[0][0]
    shot.front(h)
    time.sleep(1.5)
    shot.grab(str(OUT / "rhino_ui.png"))
    run_cs(SECTION, quiet=True)
    for tag, (d, w) in (("fail", SIZES[0]), ("pass", SIZES[3])):
        view(f"section_{tag}", load_kn=150, beam_diameter_mm=d, beam_wall_mm=w, display_guids=LINE,
             title=f"ALMOND  //  NATIVE FEA  ·  SECTION A-A  ·  CHS {d}x{w}")
    run_cs(UNCLIP, quiet=True)
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    (OUT / "log.json").write_text(json.dumps(LOG, indent=1))


def capture_asset_loads():
    """Placed furniture as loads (asset passports): the as-drawn and resized frames, asset loads only."""
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    rows = []
    for name, (d, w) in (("assets_114", SIZES[0]), ("assets_193", SIZES[3])):
        out = json.loads(server.visualize_structure(
            guids=GUIDS, load_kn=0, fixed_supports=False, span_m=6.2, beam_diameter_mm=d, beam_wall_mm=w,
            color_by="utilization", scale=40, asset_loads=True,
            title=f"ALMOND  //  NATIVE FEA  ·  ASSET LOADS  ·  CHS {d}x{w}"))
        run_cs(CAP.replace("PATH", str(OUT / f"{name}.jpg")), quiet=True)
        rows.append({"name": name, "status": out.get("status"), "max_mm": out.get("max_displacement_mm"),
                     "util": out.get("max_utilization"), "asset_loads": out.get("asset_loads")})
        print(name, out.get("status"), out.get("max_displacement_mm"), out.get("max_utilization"), flush=True)
    (OUT / "assets_log.json").write_text(json.dumps(rows, indent=1))


def capture_floor_loads():
    """Residential floor load on every bay (2.0 imposed + 1.0 build-up kN/m2): lightest failing/passing CHS."""
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    rows = []
    for name, (d, w) in (("floor_193", (193.7, 8.0)), ("floor_219", (219.1, 8.0))):
        out = json.loads(server.visualize_structure(
            guids=GUIDS, load_kn=0, fixed_supports=False, span_m=6.2, beam_diameter_mm=d, beam_wall_mm=w,
            color_by="utilization", scale=10, floor_load_kn_m2=2.0, floor_dead_kn_m2=1.0,
            title=f"ALMOND  //  NATIVE FEA  ·  FLOOR LOADS  ·  CHS {d}x{w}"))
        run_cs(CAP.replace("PATH", str(OUT / f"{name}.jpg")), quiet=True)
        rows.append({"name": name, "status": out.get("status"), "max_mm": out.get("max_displacement_mm"),
                     "util": out.get("max_utilization"), "floor_loads": out.get("floor_loads")})
        print(name, out.get("status"), out.get("max_displacement_mm"), out.get("max_utilization"), flush=True)
    (OUT / "floor_log.json").write_text(json.dumps(rows, indent=1))


def capture_combinations():
    """EN 1990 vs unfactored under the residential floor load, four sections; stills of 193.7 and 219.1."""
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    rows = []
    for d, w in ((168.3, 6.3), (193.7, 8.0), (219.1, 8.0), (244.5, 10.0)):
        for basis, uls in (("unfactored", "6.10"), ("en1990", "6.10"), ("en1990", "6.10ab")):
            out = json.loads(server.visualize_structure(
                guids=GUIDS, load_kn=0, fixed_supports=False, span_m=6.2, beam_diameter_mm=d, beam_wall_mm=w,
                color_by="utilization", scale=10, floor_load_kn_m2=2.0, floor_dead_kn_m2=1.0,
                design_basis=basis, uls_combination=uls))
            rows.append({"d": d, "w": w, "basis": basis, "uls": uls, "status": out.get("status"),
                         "max_mm": out.get("max_displacement_mm"), "util": out.get("max_utilization")})
            print(rows[-1], flush=True)
            if basis == "en1990" and uls == "6.10" and d in (193.7, 219.1):
                run_cs(CAP.replace("PATH", str(OUT / f"combo_{int(d)}.jpg")), quiet=True)
    (OUT / "combo_log.json").write_text(json.dumps(rows, indent=1))


def capture_connections():
    """Rigid joints vs simple (pinned) connections under the residential floor load."""
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    rows = []
    for conn, (d, w) in (("rigid", (219.1, 8.0)), ("simple", (219.1, 8.0)), ("simple", (244.5, 10.0))):
        out = json.loads(server.visualize_structure(
            guids=GUIDS, load_kn=0, fixed_supports=False, span_m=6.2, beam_diameter_mm=d, beam_wall_mm=w,
            color_by="utilization", scale=10, floor_load_kn_m2=2.0, floor_dead_kn_m2=1.0, connections=conn))
        rows.append({"conn": conn, "d": d, "w": w, "status": out.get("status"), "max_mm": out.get("max_displacement_mm"),
                     "util": out.get("max_utilization"), "pinned": (out.get("connections") or {}).get("pinned_ends")})
        run_cs(CAP.replace("PATH", str(OUT / f"conn_{conn}_{int(d)}.jpg")), quiet=True)
        print(rows[-1], flush=True)
    (OUT / "conn_log.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    if "--connections" in sys.argv:
        capture_connections()
    elif "--combos" in sys.argv:
        capture_combinations()
    elif "--floor" in sys.argv:
        capture_floor_loads()
    elif "--assets" in sys.argv:
        capture_asset_loads()
    else:
        main()
