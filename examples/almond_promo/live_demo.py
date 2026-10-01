"""Live screen recording of the native structural engine driving the Rhino overlay (A07 mezzanine frame).

Rhino is kept topmost with the cursor parked; ffmpeg (ddagrab) records the Rhino window area while the real
MCP tool code (almond_mcp.server.visualize_structure) runs a design sequence against the live bridge:
floor-load sizing loop -> simple connections -> buckling modes. Run from the repo root:

    uv run python examples/almond_promo/live_demo.py
"""
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
from bridge import run_cs                      # noqa: E402
import shot, sv                                 # noqa: E402
from almond_mcp import server                  # noqa: E402

OUT = Path(r"C:\Users\liang\Documents\almond_promo\ui")
F = json.load(open(r"C:\Users\liang\Documents\almond_promo\frame_ids.json"))
GUIDS = F["beams"] + F["columns"] + F["wall"] + F["bases"]
BASE = dict(guids=GUIDS, load_kn=0, fixed_supports=False, span_m=6.2, floor_load_kn_m2=2.0, floor_dead_kn_m2=1.0,
            color_by="utilization", scale=10)
user32 = ctypes.windll.user32
LOG = []

HIDE = r'''var lay = doc.Layers.FindName("A07 / 16 Structure"); if (lay != null) { lay.IsVisible = false; lay.CommitChanges(); }
doc.Objects.UnselectAll(); doc.Views.Redraw(); log.Append("ok");'''


def topmost(on=True):
    h = shot.rhino_hwnd()[0][0]
    shot.front(h)
    user32.SetWindowPos(h, -1 if on else -2, 0, 0, 0, 0, 0x0003)
    user32.SetCursorPos(1300, 700)


def step(hold, **kw):
    out = json.loads(server.visualize_structure(**{**BASE, **kw}))
    row = {k: out.get(k) for k in ("status", "max_displacement_mm", "max_utilization")}
    row.update(title=kw.get("title"), alpha=(out.get("buckling") or {}).get("alpha_cr"),
               method=(out.get("stability") or {}).get("method"))
    LOG.append(row)
    print(row, flush=True)
    time.sleep(hold)


def main():
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    run_cs(HIDE, quiet=True)
    run_cs('RhinoApp.RunScript("_Almond", false); RhinoApp.ClearCommandHistoryWindow(); log.Append("ok");', quiet=True)
    sv.request({"type": "structure_view", "clear": True})
    topmost(True)
    time.sleep(1.5)
    mp4 = OUT / "native_live_demo.mp4"
    rec = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "ddagrab=output_idx=0:framerate=30,hwdownload,format=bgra",
         "-vf", "crop=2560:1520:0:0,scale=1920:1140:flags=lanczos,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(mp4)],
        stdin=subprocess.PIPE)
    try:
        time.sleep(2.5)                                            # the bare model
        for i, (d, w) in enumerate(((168.3, 6.3), (193.7, 8.0), (219.1, 8.0))):
            step(3.5, beam_diameter_mm=d, beam_wall_mm=w,
                 title=f"ALMOND  //  FLOOR 2.0+1.0 kN/m²  ·  SIZING {i + 1}/3  ·  CHS {d}x{w}")
        step(3.5, beam_diameter_mm=219.1, beam_wall_mm=8.0, connections="simple",
             title="ALMOND  //  SIMPLE CONNECTIONS  ·  CHS 219.1x8")
        step(3.5, beam_diameter_mm=244.5, beam_wall_mm=10.0, connections="simple",
             title="ALMOND  //  SIMPLE CONNECTIONS  ·  CHS 244.5x10")
        step(4.0, beam_diameter_mm=244.5, beam_wall_mm=10.0, connections="simple", view="buckling")
        step(4.0, beam_diameter_mm=114.3, beam_wall_mm=4.0, connections="simple", view="buckling")
        step(4.0, beam_diameter_mm=114.3, beam_wall_mm=4.0, connections="simple",
             title="ALMOND  //  SLENDER CHS 114.3x4  ·  SECOND ORDER")
    finally:
        rec.communicate(b"q", timeout=60)
        topmost(False)
    (OUT / "native_live_demo.json").write_text(json.dumps(LOG, indent=1))
    print(mp4)


if __name__ == "__main__":
    main()
