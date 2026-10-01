"""Drive the Almond panel's Karamba Validation workspace on the mezzanine frame and screenshot each step."""
import ctypes, json, sys, time
import shot, ui, uishot, sv
from bridge import run_cs

F = json.load(open(r"C:\Users\liang\Documents\almond_promo\frame_ids.json"))
GUIDS = F["beams"] + F["columns"] + F["wall"] + F["bases"]
user32 = ctypes.windll.user32


def topmost(on=True):
    h = shot.rhino_hwnd()[0][0]
    shot.front(h)
    user32.SetWindowPos(h, -1 if on else -2, 0, 0, 0, 0, 0x0003)


def js(code):
    """Run JavaScript in the Almond panel's WebView (form values, button clicks) and return its result."""
    lit = json.dumps(code)
    out = run_cs('var p = Rhino.UI.Panels.GetPanel<RhinoAlmondBridge.AlmondLibraryPanel>(doc); '
                 'var f = typeof(RhinoAlmondBridge.AlmondLibraryPanel).GetField("_view", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance); '
                 'var v = (Eto.Forms.WebView)f.GetValue(p); log.Append(v.ExecuteScript(%s));' % lit, quiet=True)
    return out


def step(name, x=None, y=None, wait=2.0):
    topmost(True)
    if x is not None:
        ui.click(x, y)
    time.sleep(wait)
    user32.SetCursorPos(1300, 700)
    time.sleep(0.5)
    uishot.take(name, settle=0.3)


if __name__ == "__main__":
    which = sys.argv[1]
    if which == "prep":
        sv.request({"type": "structure_view", "clear": True})
        ids = ",".join('new Guid("%s")' % g for g in GUIDS)
        run_cs('doc.Objects.UnselectAll(); foreach (var g in new[]{%s}) doc.Objects.Select(g, true); doc.Views.Redraw(); '
               'log.Append(doc.Objects.GetSelectedObjects(false, false).Count());' % ids)
        run_cs('RhinoApp.RunScript("_AlmondKaramba", false); log.Append("ok");', quiet=True)
        step("k1_open", wait=3)
    else:
        x, y, wait = int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]) if len(sys.argv) > 4 else 3
        step(which, x, y, wait)
    topmost(False)
