"""Conditioning pass: path maths, script templating and receipts (no Rhino)."""
import json
import math
import os

import pytest

from almond_mcp import conditioning as c


def test_orbit_path_starts_and_ends_on_requested_angles():
    frames = c.orbit_path(center=(0, 0, 0), radius=10, height=5, frames=5, start_deg=0, end_deg=90, lens=28)
    assert len(frames) == 5
    assert frames[0]["camera"] == pytest.approx([10, 0, 5])
    assert frames[-1]["camera"] == pytest.approx([0, 10, 5], abs=1e-6)
    assert all(f["target"] == [0, 0, 0] for f in frames)
    assert all(f["lens_mm"] == 28 for f in frames)
    assert [f["frame"] for f in frames] == [0, 1, 2, 3, 4]


def test_orbit_target_height_override():
    frames = c.orbit_path((100, 200, 0), 50, 30, 3, target_height=12)
    assert frames[1]["target"] == [100, 200, 12]


def test_track_path_interpolates_camera_and_target():
    frames = c.track_path((0, 0, 0), (10, 0, 0), (0, 10, 0), (10, 10, 0), 3)
    assert frames[1]["camera"] == pytest.approx([5, 0, 0])
    assert frames[1]["target"] == pytest.approx([5, 10, 0])


def test_keyframe_path_is_piecewise_linear():
    kf = [{"camera": [0, 0, 0], "target": [1, 0, 0], "lens": 20},
          {"camera": [10, 0, 0], "target": [1, 0, 0], "lens": 40},
          {"camera": [10, 10, 0], "target": [1, 0, 0], "lens": 40}]
    frames = c.keyframe_path(kf, 5)
    assert frames[0]["camera"] == pytest.approx([0, 0, 0])
    assert frames[2]["camera"] == pytest.approx([10, 0, 0])   # exactly on the middle keyframe
    assert frames[4]["camera"] == pytest.approx([10, 10, 0])
    assert frames[1]["lens_mm"] == pytest.approx(30)


def test_build_path_dispatch_and_errors():
    assert len(c.build_path({"type": "orbit", "center": [0, 0, 0], "radius": 1, "height": 1, "frames": 7})) == 7
    with pytest.raises(ValueError):
        c.build_path({"type": "spiral"})
    with pytest.raises(ValueError):
        c.orbit_path((0, 0, 0), 1, 1, 0)


def test_capture_script_has_no_leftover_tokens_and_encodes_frames():
    frames = c.orbit_path((0, 0, 0), 10, 5, 2)
    script = c.render_capture_script(frames, r"C:\tmp\pass", 832, 480, ("rgb", "depth"), "Rendered", "Technical", True)
    assert "__" not in script.replace("__cplusplus", "")
    assert '"Rendered"' in script and '"Technical"' in script
    assert "int W = 832, H = 480;" in script
    assert "if (true) SaveView(view, vc, rgbMode" in script
    assert "if (false) SaveView(view, vc, edgeMode" in script
    assert "0,10.000,0.000,5.000,0.000,0.000,0.000,35.000;1," in script
    assert "ZBufferCapture" in script


def test_doc_info_script_targets_out_dir():
    s = c.render_doc_info_script(r"D:\x\y")
    assert r'@"D:\x\y"' in s and "__OUT__" not in s


def test_camera_receipt_round_trips(tmp_path):
    frames = c.track_path((0, 0, 0), (1, 1, 1), (2, 2, 2), (3, 3, 3), 4)
    path = tmp_path / "camera.json"
    receipt = c.write_camera_receipt(str(path), frames, 832, 480, 16, ("rgb", "edge", "depth"),
                                     "Rendered", "Technical", True, {"document": "a.3dm", "units": "Millimeters"})
    data = json.loads(path.read_text())
    assert data["schema"] == c.CAMERA_SCHEMA
    assert data["frame_count"] == 4 and data["frames"][3]["camera"] == [1, 1, 1]
    assert data["source"]["units"] == "Millimeters"
    assert data["depth"]["near_is_bright"] is False      # invert_depth=True flips Rhino's native near=bright
    assert receipt["resolution"] == [832, 480]


def test_restore_view_script_substitutes_all_tokens():
    s = c.render_restore_view_script([1, 2, 3], [4, 5, 6], 35)
    assert "__" not in s and "35.0" in s and "new Point3d(4.0, 5.0, 6.0), new Point3d(1.0, 2.0, 3.0)" in s


def test_capture_pass_uses_sender_and_reports_partial(tmp_path):
    calls = []

    def fake_send(payload, timeout):
        req = json.loads(payload)
        calls.append(req)
        if "doc.json" in req["script"]:
            os.makedirs(tmp_path, exist_ok=True)
            (tmp_path / "doc.json").write_text('{"document":"t.3dm","units":"Millimeters"}')
            return json.dumps({"status": "success", "guids": []})
        # first capture chunk succeeds, second fails
        return json.dumps({"status": "success", "guids": []} if len(calls) == 2 else {"status": "runtime_error", "message": "boom"})

    frames = c.orbit_path((0, 0, 0), 10, 5, 4)
    summary = c.capture_conditioning_pass(frames, str(tmp_path), fake_send, chunk=2, assemble=False, restore_view=False)
    assert summary["status"] == "partial"
    assert summary["frames_captured"] == 2
    assert summary["errors"][0]["frames"] == [2, 3]
    assert summary["document"]["units"] == "Millimeters"
    assert (tmp_path / "camera.json").exists() and (tmp_path / "summary.json").exists()
    assert len(calls) == 3  # doc info + 2 chunks


def test_capture_pass_rejects_odd_resolution(tmp_path):
    with pytest.raises(ValueError):
        c.capture_conditioning_pass([], str(tmp_path), lambda p, t: "{}", width=833)
