"""Conditioning pass: RGB + edge + depth frames along a camera path.

Why this exists
---------------
Generative video models that accept structure (Wan VACE, ControlNet-style
models) want three things per frame, all taken from the *same* camera:

  rgb    a normal rendered view  (what the beauty pass looks like)
  edge   a clean line drawing    (Rhino's "Technical" display mode)
  depth  a grayscale depth image (near = bright by default)

Rhino already knows the exact geometry, so these are not estimated - they are
read straight off the model. Every frame is recorded in ``camera.json`` so the
generated video can later be re-projected against the source model.

Nothing here talks to Rhino directly: the capture builds C# RhinoCommon
scripts and hands them to a ``send`` callable (the Almond bridge). That keeps
this module importable and testable without Rhino.

Layout of an output folder::

    <out_dir>/
      rgb/f0000.png ...      edge/f0000.png ...      depth/f0000.png ...
      rgb.mp4  edge.mp4  depth.mp4        (if ffmpeg is available)
      camera.json                         (per-frame camera receipt)
      zrange.csv                          (frame, minZ, maxZ, hits)
      doc.json                            (document name, units, bbox)
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from typing import Callable, Iterable, Sequence

PASSES = ("rgb", "edge", "depth")
DEFAULT_MODES = {"rgb": "Rendered", "edge": "Technical"}
CAMERA_SCHEMA = "building0.camera/0.1"

Vec = Sequence[float]
Sender = Callable[[bytes, float], str]


# ── camera paths ────────────────────────────────────────────────────────────

def _lerp(a: Vec, b: Vec, t: float) -> list[float]:
    return [a[i] + (b[i] - a[i]) * t for i in range(3)]


def _frame(i: int, camera: Vec, target: Vec, lens: float) -> dict:
    return {
        "frame": i,
        "camera": [float(round(c, 3)) for c in camera],
        "target": [float(round(c, 3)) for c in target],
        "lens_mm": float(lens),
    }


def orbit_path(center: Vec, radius: float, height: float, frames: int,
               start_deg: float = 0.0, end_deg: float = 360.0, lens: float = 35.0,
               target_height: float | None = None) -> list[dict]:
    """Camera circles ``center`` at ``radius`` and ``height`` (model units),
    always looking at the center (at ``target_height`` if given)."""
    if frames < 1:
        raise ValueError("frames must be >= 1")
    tz = center[2] if target_height is None else target_height
    out = []
    for i in range(frames):
        t = 0.0 if frames == 1 else i / (frames - 1)
        a = math.radians(start_deg + (end_deg - start_deg) * t)
        cam = [center[0] + radius * math.cos(a), center[1] + radius * math.sin(a), height]
        out.append(_frame(i, cam, [center[0], center[1], tz], lens))
    return out


def track_path(cam0: Vec, cam1: Vec, target0: Vec, target1: Vec, frames: int,
               lens: float = 35.0) -> list[dict]:
    """Straight dolly from cam0 to cam1 while the look-at slides target0 -> target1."""
    if frames < 1:
        raise ValueError("frames must be >= 1")
    out = []
    for i in range(frames):
        t = 0.0 if frames == 1 else i / (frames - 1)
        out.append(_frame(i, _lerp(cam0, cam1, t), _lerp(target0, target1, t), lens))
    return out


def keyframe_path(keyframes: Sequence[dict], frames: int) -> list[dict]:
    """Piecewise-linear path through keyframes ``{"camera", "target", "lens"}``,
    evenly spaced in time."""
    if len(keyframes) < 1:
        raise ValueError("need at least one keyframe")
    if frames < 1:
        raise ValueError("frames must be >= 1")
    if len(keyframes) == 1:
        k = keyframes[0]
        return [_frame(i, k["camera"], k["target"], k.get("lens", 35.0)) for i in range(frames)]
    segs = len(keyframes) - 1
    out = []
    for i in range(frames):
        t = 0.0 if frames == 1 else i / (frames - 1)
        pos = t * segs
        s = min(int(pos), segs - 1)
        u = pos - s
        a, b = keyframes[s], keyframes[s + 1]
        lens = a.get("lens", 35.0) + (b.get("lens", 35.0) - a.get("lens", 35.0)) * u
        out.append(_frame(i, _lerp(a["camera"], b["camera"], u), _lerp(a["target"], b["target"], u), lens))
    return out


def build_path(shot: dict) -> list[dict]:
    """Turn a shot description into frames. ``shot["type"]`` is one of
    ``orbit`` | ``track`` | ``keyframes``; other keys are that builder's args."""
    kind = shot.get("type", "orbit")
    if kind == "orbit":
        return orbit_path(shot["center"], shot["radius"], shot["height"], int(shot.get("frames", 81)),
                          shot.get("start_deg", 0.0), shot.get("end_deg", 360.0), shot.get("lens", 35.0),
                          shot.get("target_height"))
    if kind == "track":
        return track_path(shot["cam0"], shot["cam1"], shot["target0"], shot["target1"],
                          int(shot.get("frames", 81)), shot.get("lens", 35.0))
    if kind == "keyframes":
        return keyframe_path(shot["keyframes"], int(shot.get("frames", 81)))
    raise ValueError(f"unknown shot type: {kind!r}")


# ── C# scripts ──────────────────────────────────────────────────────────────

_CS_DOC_INFO = r'''
using System;
using System.Collections.Generic;
using System.IO;
using Rhino;
using Rhino.Geometry;
public class Script {
  public static List<Guid> Run(RhinoDoc doc) {
    var bb = BoundingBox.Empty;
    foreach (var o in doc.Objects) { if (o.IsHidden) continue; var b = o.Geometry.GetBoundingBox(true); if (b.IsValid) bb.Union(b); }
    var view = doc.Views.ActiveView;
    var vp = view.ActiveViewport;
    string name = doc.Name ?? "";
    string json = "{\"document\":\"" + name.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\","
      + "\"units\":\"" + doc.ModelUnitSystem.ToString() + "\","
      + "\"view\":\"" + view.ActiveViewport.Name + "\","
      + "\"display_mode\":\"" + vp.DisplayMode.EnglishName + "\","
      + "\"viewport_size\":[" + vp.Size.Width + "," + vp.Size.Height + "],"
      + "\"bbox_min\":[" + bb.Min.X.ToString("R") + "," + bb.Min.Y.ToString("R") + "," + bb.Min.Z.ToString("R") + "],"
      + "\"bbox_max\":[" + bb.Max.X.ToString("R") + "," + bb.Max.Y.ToString("R") + "," + bb.Max.Z.ToString("R") + "],"
      + "\"camera\":[" + vp.CameraLocation.X.ToString("R") + "," + vp.CameraLocation.Y.ToString("R") + "," + vp.CameraLocation.Z.ToString("R") + "],"
      + "\"target\":[" + vp.CameraTarget.X.ToString("R") + "," + vp.CameraTarget.Y.ToString("R") + "," + vp.CameraTarget.Z.ToString("R") + "],"
      + "\"lens_mm\":" + vp.Camera35mmLensLength.ToString("R") + "}";
    Directory.CreateDirectory(@"__OUT__");
    File.WriteAllText(Path.Combine(@"__OUT__", "doc.json"), json);
    return new List<Guid>();
  }
}
'''

_CS_CAPTURE = r'''
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using Rhino;
using Rhino.Display;
using Rhino.Geometry;
public class Script {
  static Bitmap Invert(Bitmap src) {
    var dst = new Bitmap(src.Width, src.Height, PixelFormat.Format24bppRgb);
    var cm = new ColorMatrix(new float[][] {
      new float[] {-1, 0, 0, 0, 0}, new float[] {0, -1, 0, 0, 0}, new float[] {0, 0, -1, 0, 0},
      new float[] {0, 0, 0, 1, 0}, new float[] {1, 1, 1, 0, 1} });
    using (var ia = new ImageAttributes()) {
      ia.SetColorMatrix(cm);
      using (var g = Graphics.FromImage(dst))
        g.DrawImage(src, new Rectangle(0, 0, src.Width, src.Height), 0, 0, src.Width, src.Height, GraphicsUnit.Pixel, ia);
    }
    return dst;
  }
  static Bitmap CropToAspect(Bitmap src, int w, int h) {
    double want = (double)w / h, have = (double)src.Width / src.Height;
    if (Math.Abs(want - have) < 0.002) return src;
    int cw = src.Width, ch = src.Height;
    if (have > want) cw = (int)Math.Round(src.Height * want); else ch = (int)Math.Round(src.Width / want);
    var rect = new Rectangle((src.Width - cw) / 2, (src.Height - ch) / 2, cw, ch);
    return src.Clone(rect, src.PixelFormat);
  }
  static void SaveDepth(RhinoView view, string path, int w, int h, bool invert, bool curves, System.Text.StringBuilder log, int frame) {
    using (var zb = new ZBufferCapture(view.ActiveViewport)) {
      zb.ShowCurves(curves); zb.ShowIsocurves(false); zb.ShowMeshWires(false);
      zb.ShowPoints(false); zb.ShowAnnotations(false); zb.ShowLights(false);
      var dib = zb.GrayscaleDib();
      if (dib == null) { log.AppendLine(frame + ",,,0"); return; }
      Bitmap cur = CropToAspect(dib, w, h);
      if (cur.Width != w || cur.Height != h) { var r = new Bitmap(cur, new Size(w, h)); if (!ReferenceEquals(cur, dib)) cur.Dispose(); cur = r; }
      if (invert) { var inv = Invert(cur); if (!ReferenceEquals(cur, dib)) cur.Dispose(); cur = inv; }
      cur.Save(path, ImageFormat.Png);
      log.AppendLine(frame + "," + zb.MinZ().ToString("R") + "," + zb.MaxZ().ToString("R") + "," + zb.HitCount());
      if (!ReferenceEquals(cur, dib)) cur.Dispose();
      dib.Dispose();
    }
  }
  static void SaveView(RhinoView view, ViewCapture vc, DisplayModeDescription mode, string path) {
    var vp = view.ActiveViewport;
    if (mode != null && vp.DisplayMode.Id != mode.Id) vp.DisplayMode = mode;
    view.Redraw(); RhinoApp.Wait();
    var b = vc.CaptureToBitmap(view);
    if (b != null) { b.Save(path, ImageFormat.Png); b.Dispose(); }
  }
  public static List<Guid> Run(RhinoDoc doc) {
    var view = doc.Views.ActiveView;
    var vp = view.ActiveViewport;
    var originalMode = vp.DisplayMode;
    var rgbMode = DisplayModeDescription.FindByName("__RGBMODE__");
    var edgeMode = DisplayModeDescription.FindByName("__EDGEMODE__");
    var depthMode = DisplayModeDescription.FindByName("Shaded") ?? rgbMode;   // a filled mode so the z-buffer is populated
    int W = __W__, H = __H__;
    var vc = new ViewCapture { Width = W, Height = H, ScaleScreenItems = false, DrawAxes = false,
      DrawGrid = false, DrawGridAxes = false, TransparentBackground = false };
    var zlog = new System.Text.StringBuilder();
    string outDir = @"__OUT__";
    foreach (var rec in "__DATA__".Split(';')) {
      var v = rec.Split(',');
      int f = int.Parse(v[0]);
      var cam = new Point3d(double.Parse(v[1]), double.Parse(v[2]), double.Parse(v[3]));
      var tgt = new Point3d(double.Parse(v[4]), double.Parse(v[5]), double.Parse(v[6]));
      vp.SetCameraLocations(tgt, cam);
      vp.Camera35mmLensLength = double.Parse(v[7]);
      view.Redraw(); RhinoApp.Wait();
      string name = "f" + f.ToString("D4") + ".png";
      if (__DO_RGB__) SaveView(view, vc, rgbMode, Path.Combine(outDir, "rgb", name));
      if (__DO_EDGE__) SaveView(view, vc, edgeMode, Path.Combine(outDir, "edge", name));
      if (__DO_DEPTH__) {
        if (depthMode != null && vp.DisplayMode.Id != depthMode.Id) vp.DisplayMode = depthMode;
        view.Redraw(); RhinoApp.Wait();
        SaveDepth(view, Path.Combine(outDir, "depth", name), W, H, __INVERT__, __DEPTH_CURVES__, zlog, f);
      }
    }
    if (originalMode != null && vp.DisplayMode.Id != originalMode.Id) vp.DisplayMode = originalMode;
    view.Redraw(); RhinoApp.Wait();
    File.AppendAllText(Path.Combine(outDir, "zrange.csv"), zlog.ToString());
    return new List<Guid>();
  }
}
'''


def _cs(v: bool) -> str:
    return "true" if v else "false"


def render_capture_script(frames: Iterable[dict], out_dir: str, width: int, height: int,
                          passes: Sequence[str], rgb_mode: str, edge_mode: str, invert_depth: bool,
                          depth_curves: bool = True) -> str:
    rows = [f"{f['frame']},{f['camera'][0]:.3f},{f['camera'][1]:.3f},{f['camera'][2]:.3f},"
            f"{f['target'][0]:.3f},{f['target'][1]:.3f},{f['target'][2]:.3f},{f['lens_mm']:.3f}" for f in frames]
    return (_CS_CAPTURE
            .replace("__RGBMODE__", rgb_mode).replace("__EDGEMODE__", edge_mode)
            .replace("__W__", str(int(width))).replace("__H__", str(int(height)))
            .replace("__OUT__", out_dir).replace("__DATA__", ";".join(rows))
            .replace("__DO_RGB__", _cs("rgb" in passes)).replace("__DO_EDGE__", _cs("edge" in passes))
            .replace("__DO_DEPTH__", _cs("depth" in passes)).replace("__INVERT__", _cs(invert_depth))
            .replace("__DEPTH_CURVES__", _cs(depth_curves)))


def render_doc_info_script(out_dir: str) -> str:
    return _CS_DOC_INFO.replace("__OUT__", out_dir)


_CS_RESTORE_VIEW = r'''
using System;
using System.Collections.Generic;
using Rhino;
using Rhino.Geometry;
public class Script {
  public static List<Guid> Run(RhinoDoc doc) {
    var view = doc.Views.ActiveView; var vp = view.ActiveViewport;
    vp.SetCameraLocations(new Point3d(__TX__, __TY__, __TZ__), new Point3d(__CX__, __CY__, __CZ__));
    vp.Camera35mmLensLength = __LENS__;
    view.Redraw(); RhinoApp.Wait();
    return new List<Guid>();
  }
}
'''


def render_restore_view_script(camera: Sequence[float], target: Sequence[float], lens_mm: float) -> str:
    s = _CS_RESTORE_VIEW
    for tok, val in (("__CX__", camera[0]), ("__CY__", camera[1]), ("__CZ__", camera[2]),
                     ("__TX__", target[0]), ("__TY__", target[1]), ("__TZ__", target[2]), ("__LENS__", lens_mm)):
        s = s.replace(tok, repr(float(val)))
    return s


# ── ffmpeg ──────────────────────────────────────────────────────────────────

def find_ffmpeg() -> str | None:
    env = os.environ.get("ALMOND_FFMPEG")
    if env and os.path.isfile(env):
        return env
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    for cand in (os.path.join(os.path.expanduser("~"), "WanGP", "ffmpeg_bins", "ffmpeg.exe"),):
        if os.path.isfile(cand):
            return cand
    return None


def assemble_video(frames_dir: str, out_mp4: str, fps: int, ffmpeg: str | None = None) -> bool:
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return False
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
           "-i", os.path.join(frames_dir, "f%04d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", out_mp4]
    return subprocess.run(cmd, capture_output=True).returncode == 0


# ── the pass ────────────────────────────────────────────────────────────────

def write_camera_receipt(path: str, frames: Sequence[dict], width: int, height: int, fps: int,
                         passes: Sequence[str], rgb_mode: str, edge_mode: str, invert_depth: bool,
                         doc_info: dict | None) -> dict:
    receipt = {
        "schema": CAMERA_SCHEMA,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": {"application": "Rhino 8", "via": "almond-mcp",
                   "document": (doc_info or {}).get("document", ""),
                   "units": (doc_info or {}).get("units", ""),
                   "view": (doc_info or {}).get("view", ""),
                   "bbox_min": (doc_info or {}).get("bbox_min"),
                   "bbox_max": (doc_info or {}).get("bbox_max")},
        "resolution": [int(width), int(height)],
        "fps": int(fps),
        "passes": list(passes),
        "display_modes": {"rgb": rgb_mode, "edge": edge_mode},
        # Rhino's ZBufferCapture is near = bright natively; invert_depth flips that.
        "depth": {"encoding": "grayscale-8bit", "near_is_bright": not bool(invert_depth),
                  "z_range_per_frame": "zrange.csv"},
        "frame_count": len(frames),
        "frames": list(frames),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
    return receipt


def capture_conditioning_pass(frames: Sequence[dict], out_dir: str, send: Sender, *,
                              width: int = 832, height: int = 480,
                              passes: Sequence[str] = PASSES,
                              rgb_mode: str = DEFAULT_MODES["rgb"],
                              edge_mode: str = DEFAULT_MODES["edge"],
                              invert_depth: bool = False, depth_curves: bool = True,
                              chunk: int = 16, fps: int = 16,
                              assemble: bool = True, chunk_timeout_s: float = 300.0,
                              restore_view: bool = True,
                              log: Callable[[str], None] | None = None) -> dict:
    """Capture every frame of ``frames`` from the live Rhino document.

    ``send(payload_bytes, timeout)`` must deliver a bridge ``execute`` payload
    and return the JSON response text (Almond's ``_send_and_receive``).
    Depth is near = bright unless ``invert_depth``. With ``restore_view`` the
    viewport camera is put back where the user had it when the pass finishes.
    Returns a summary dict; the same content is written to ``summary.json``.
    """
    passes = tuple(p for p in passes if p in PASSES)
    if not passes:
        raise ValueError("passes must include at least one of rgb, edge, depth")
    if width % 2 or height % 2:
        raise ValueError("width and height must be even (video encoders need it)")
    out_dir = os.path.abspath(out_dir)
    for p in passes:
        os.makedirs(os.path.join(out_dir, p), exist_ok=True)
    say = log or (lambda m: None)

    # document info first (also proves the bridge is alive)
    doc_info = None
    payload = json.dumps({"type": "execute", "script": render_doc_info_script(out_dir), "timeout_s": 60.0}).encode("utf-8")
    r = json.loads(send(payload, 90.0))
    if r.get("status") != "success":
        return {"status": "error", "stage": "doc_info", "message": r.get("message", "")[:400]}
    try:
        with open(os.path.join(out_dir, "doc.json"), encoding="utf-8") as fh:
            doc_info = json.load(fh)
    except (OSError, ValueError):
        doc_info = None

    zr = os.path.join(out_dir, "zrange.csv")
    if os.path.exists(zr):
        os.remove(zr)

    done, errors = 0, []
    frames = list(frames)
    for c0 in range(0, len(frames), max(1, chunk)):
        part = frames[c0:c0 + chunk]
        script = render_capture_script(part, out_dir, width, height, passes, rgb_mode, edge_mode, invert_depth, depth_curves)
        payload = json.dumps({"type": "execute", "script": script, "timeout_s": chunk_timeout_s}).encode("utf-8")
        try:
            r = json.loads(send(payload, chunk_timeout_s + 20.0))
        except Exception as e:  # noqa: BLE001 - report, don't crash mid-pass
            r = {"status": "error", "message": str(e)}
        if r.get("status") != "success":
            errors.append({"frames": [part[0]["frame"], part[-1]["frame"]], "message": r.get("message", "")[:400]})
            say(f"  !! chunk {part[0]['frame']}-{part[-1]['frame']} failed: {r.get('message', '')[:160]}")
            break
        done += len(part)
        say(f"  captured {done}/{len(frames)} frames")

    if restore_view and doc_info and doc_info.get("camera") and doc_info.get("target"):
        try:
            send(json.dumps({"type": "execute", "script": render_restore_view_script(
                doc_info["camera"], doc_info["target"], float(doc_info.get("lens_mm", 50.0))),
                "timeout_s": 30.0}).encode("utf-8"), 60.0)
        except Exception:  # noqa: BLE001 - restoring the view is best-effort
            pass

    receipt = write_camera_receipt(os.path.join(out_dir, "camera.json"), frames, width, height, fps,
                                   passes, rgb_mode, edge_mode, invert_depth, doc_info)

    videos = {}
    if assemble and done == len(frames):
        for p in passes:
            mp4 = os.path.join(out_dir, f"{p}.mp4")
            videos[p] = mp4 if assemble_video(os.path.join(out_dir, p), mp4, fps) else None

    summary = {
        "status": "success" if not errors else "partial",
        "out_dir": out_dir, "frames_requested": len(frames), "frames_captured": done,
        "passes": list(passes), "resolution": [width, height], "fps": fps,
        "camera_json": os.path.join(out_dir, "camera.json"), "videos": videos,
        "document": receipt["source"], "errors": errors,
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    return summary
