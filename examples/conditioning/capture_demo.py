"""Capture a conditioning pass (RGB + edge + depth) from the live Rhino document.

Usage (bridge on 5000, a model open in Rhino):

  uv run --no-sync python examples/conditioning/capture_demo.py ORBIT  <out_dir> [frames] [deg0] [deg1]
  uv run --no-sync python examples/conditioning/capture_demo.py FROMVIEW <out_dir> [frames] [sweep_deg]

ORBIT    orbits the document's bounding box: camera at 1.6x the box's largest
         side, at 45% of that above the box centre, looking at the centre.
FROMVIEW starts from the CURRENT viewport camera and sweeps `sweep_deg`
         (default 30) around the current target - the quickest way to turn a
         view you have already composed into a shot.

Frames default to 81 (5 s at 16 fps). Wan models want 4n+1 frames.
Env: ALMOND_COND_W / ALMOND_COND_H (default 832x480), ALMOND_COND_PASSES
(default rgb,edge,depth), ALMOND_FFMPEG (path to ffmpeg if not on PATH).
"""
import importlib.util
import json
import math
import os
import sys
import tempfile
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
os.environ.setdefault("RHINO_MCP_STATE_DB", tempfile.mktemp(suffix=".sqlite3"))
spec = importlib.util.spec_from_file_location(f"srv_{uuid.uuid4().hex}", os.path.join(REPO, "almond_mcp", "server.py"))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)
from almond_mcp import conditioning as cond  # noqa: E402


def log(msg):
    print(msg, flush=True)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    mode, out_dir = sys.argv[1].upper(), sys.argv[2]
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 81
    width = int(os.environ.get("ALMOND_COND_W", 832))
    height = int(os.environ.get("ALMOND_COND_H", 480))
    passes = tuple(os.environ.get("ALMOND_COND_PASSES", "rgb,edge,depth").split(","))

    # read the document once to size the shot
    probe = os.path.join(tempfile.gettempdir(), f"almond_cond_probe_{uuid.uuid4().hex}")
    os.makedirs(probe, exist_ok=True)
    payload = json.dumps({"type": "execute", "script": cond.render_doc_info_script(probe), "timeout_s": 60.0}).encode("utf-8")
    r = json.loads(srv._send_and_receive(payload, 90.0))
    if r.get("status") != "success":
        log(f"bridge error: {r.get('message', '')[:300]}")
        sys.exit(1)
    info = json.load(open(os.path.join(probe, "doc.json"), encoding="utf-8"))
    log(f"document: {info.get('document') or '(untitled)'} · {info.get('units')} · view {info.get('view')} · {info.get('display_mode')}")

    lo, hi = info["bbox_min"], info["bbox_max"]
    if hi[0] < lo[0]:
        log("document is empty - nothing to capture")
        sys.exit(1)
    center = [(lo[i] + hi[i]) / 2 for i in range(3)]
    size = max(hi[i] - lo[i] for i in range(3))

    if mode == "ORBIT":
        deg0 = float(sys.argv[4]) if len(sys.argv) > 4 else 200.0
        deg1 = float(sys.argv[5]) if len(sys.argv) > 5 else 290.0
        path = cond.orbit_path(center, radius=1.6 * size, height=center[2] + 0.45 * size, frames=frames,
                               start_deg=deg0, end_deg=deg1, lens=32.0)
    elif mode == "FROMVIEW":
        sweep = float(sys.argv[4]) if len(sys.argv) > 4 else 30.0
        cam, tgt = info["camera"], info["target"]
        dx, dy = cam[0] - tgt[0], cam[1] - tgt[1]
        radius = math.hypot(dx, dy)
        a0 = math.degrees(math.atan2(dy, dx))
        path = cond.orbit_path(tgt, radius=radius, height=cam[2], frames=frames,
                               start_deg=a0, end_deg=a0 + sweep, lens=info.get("lens_mm", 35.0), target_height=tgt[2])
    else:
        print(__doc__)
        sys.exit(2)

    log(f"capturing {frames} frames · {width}x{height} · passes {','.join(passes)} -> {out_dir}")
    summary = cond.capture_conditioning_pass(path, out_dir, srv._send_and_receive, width=width, height=height,
                                             passes=passes, chunk=16, fps=16, log=log)
    log(json.dumps({k: summary[k] for k in ("status", "frames_captured", "videos", "camera_json")}, indent=1))
    sys.exit(0 if summary["status"] == "success" else 1)


if __name__ == "__main__":
    main()
