"""Rhino captures for the Atelier 07 boards: set up a view in one bridge call, capture it in the next
(capturing in the same call as a display-mode change gets the previous mode)."""
import json, sys
from pathlib import Path
here = Path(__file__).parent
sys.path.insert(0, str(here))
from bridge import run

SETUP = r'''
using System; using System.Collections.Generic; using Rhino; using Rhino.DocObjects; using Rhino.Display; using Rhino.Geometry;
public class Script { public static List<Guid> Run(RhinoDoc doc) {
  double s = RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem);
  var hide = new HashSet<string>(new[] { __HIDE__ });
  var show = new HashSet<string>(new[] { __SHOW__ });
  foreach (var l in doc.Layers) {
    if (l.IsDeleted) continue;
    if (hide.Contains(l.FullPath)) l.IsVisible = false;
    if (show.Contains(l.FullPath)) l.IsVisible = true;
    if (l.FullPath.StartsWith("Almond::Environment::") && !show.Contains(l.FullPath)) l.IsVisible = false;
  }
  foreach (var lo in doc.Objects.GetObjectList(ObjectType.Light)) doc.Objects.Hide(lo, true);   // scene-light gizmos
  foreach (var ao in doc.Objects.GetObjectList(ObjectType.Annotation)) doc.Objects.Hide(ao, true);   // stray dimensions
  var view = doc.Views.Find("Perspective", false) ?? doc.Views.ActiveView;
  doc.Views.ActiveView = view;
  var vp = view.ActiveViewport;
  var dm = DisplayModeDescription.FindByName("__MODE__") ?? DisplayModeDescription.FindByName("Shaded");
  vp.DisplayMode = dm;
  vp.ChangeToPerspectiveProjection(true, __LENS__);
  vp.SetCameraLocations(new Point3d(__TX__ * s, __TY__ * s, __TZ__ * s), new Point3d(__CX__ * s, __CY__ * s, __CZ__ * s));
  view.Redraw();
  return new List<Guid>();
}}'''
CAPTURE = r'''
using System; using System.Collections.Generic; using Rhino; using Rhino.Display;
public class Script { public static List<Guid> Run(RhinoDoc doc) {
  var view = doc.Views.ActiveView; view.Redraw();
  var vc = new ViewCapture { Width = __W__, Height = __H__, DrawAxes = false, DrawGrid = false, TransparentBackground = __TRANSP__, ScaleScreenItems = false };
  vc.CaptureToBitmap(view).Save(@"__OUT__", System.Drawing.Imaging.ImageFormat.Png);
  return new List<Guid>();
}}'''


def shot(out, camera, target, lens=30, mode="Shaded", hide=(), show=(), size=(2400, 1500), transparent=True):
    sub = {"__HIDE__": ", ".join(json.dumps(x) for x in hide) or '""', "__SHOW__": ", ".join(json.dumps(x) for x in show) or '""',
           "__MODE__": mode, "__LENS__": str(lens),
           "__CX__": str(camera[0]), "__CY__": str(camera[1]), "__CZ__": str(camera[2]),
           "__TX__": str(target[0]), "__TY__": str(target[1]), "__TZ__": str(target[2])}
    s = SETUP
    for k, v in sub.items():
        s = s.replace(k, v)
    run(s)
    run(CAPTURE.replace("__W__", str(size[0])).replace("__H__", str(size[1])).replace("__OUT__", str(out))
        .replace("__TRANSP__", "true" if transparent else "false"))


if __name__ == "__main__":
    what = sys.argv[1]
    out = here / "captures"
    out.mkdir(exist_ok=True)
    if what == "context":
        shot(out / "axon_context.png", (38, -30, 26), (6.4, 3.0, 2.5), 32, "Almond | Apartment Day",
             show=["A07 / 12 Roof / hide for cutaway", "A07 / 13 Urban context"], transparent=False)
    elif what == "radiation":
        # the board has its own legend: draw the result once more without one, on its own layer
        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from almond_mcp.environment import rhino, render, studies
        res, arr = studies.load_run(json.loads((here / "results.json").read_text())["radiation"]["run"])
        lo, hi = float(arr["kwh_m2"].min()), float(arr["kwh_m2"].max())
        f = here / "board_radiation.txt"
        f.write_text(rhino.draw_file(arr["cells"], render.colorize(arr["kwh_m2"], lo, hi, "magma"), 0.001, [], None))
        run(rhino.draw_script(str(f), "Atelier 07 board radiation", res["run_id"]))
        shot(out / "axon_radiation.png", (27, -19, 19), (6.4, 4.4, 2.6), 35, "Shaded",
             hide=["A07 / 13 Urban context", "A07 / 14 Meshy library assets"],
             show=["Almond::Environment::Atelier 07 board radiation"], size=(3000, 2000))
    run(r"""using System; using System.Collections.Generic; using Rhino; using Rhino.DocObjects;
public class Script { public static List<Guid> Run(RhinoDoc doc) {
  var es = new ObjectEnumeratorSettings { HiddenObjects = true, ObjectTypeFilter = ObjectType.Light | ObjectType.Annotation };
  foreach (var lo in doc.Objects.GetObjectList(es)) doc.Objects.Show(lo, true);
  doc.Views.Redraw(); return new List<Guid>(); }}""")
    print("captured", what)
