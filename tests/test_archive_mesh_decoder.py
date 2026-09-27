"""Compare the production C# importer with independent Python GLB geometry."""
import json
import os
from pathlib import Path
import struct
import subprocess

import numpy as np
import pytest

from almond_mcp.asset_passport import read_glb_chunks
from almond_mcp.drafting import load_triangles

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("ALMOND_ARCHIVE_TEST_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="Build ArchiveHost and set ALMOND_ARCHIVE_TEST_HOST")


@pytest.mark.parametrize("path", sorted((ROOT / "GeneratedAssetfiles/models").glob("*.glb")), ids=lambda p: p.stem)
def test_native_decoder_preserves_every_triangle_in_mm_and_normals(path):
    result = subprocess.run([HOST, "--mesh", str(path), path.stem], capture_output=True, text=True, check=True)
    decoded = json.loads(result.stdout)
    expected = load_triangles(path, "mm", "y")
    actual = np.concatenate([
        np.asarray(p["Vertices"])[p["Indices"]].reshape(-1, 3, 3)
        for p in decoded["Parts"]
    ])
    assert actual.shape == expected.shape
    # Matrix multiplication implementations may differ below floating point precision.
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-7)
    assert decoded["TriangleCount"] == len(expected)
    for part in decoded["Parts"]:
        if part["Normals"] is not None:
            assert len(part["Normals"]) == len(part["Vertices"])
            np.testing.assert_allclose(np.linalg.norm(part["Normals"], axis=1), 1, atol=1e-7)
    assert decoded["Passport"]["asset_id"] == path.stem


@pytest.mark.parametrize("fault", ["identity", "external", "sparse", "bounds", "animation", "cycle", "length"])
def test_native_decoder_rejects_unsupported_or_malformed_assets(tmp_path, fault):
    original = ROOT / "GeneratedAssetfiles/models/gen-office-chair-1.glb"
    chunks = read_glb_chunks(original.read_bytes())
    gltf = json.loads(chunks[0][1])
    if fault == "identity":
        gltf["asset"]["extras"]["almond"]["passport"]["asset_id"] = "wrong"
    elif fault == "external":
        gltf["buffers"][0]["uri"] = "https://example.com/model.bin"
    elif fault == "sparse":
        gltf["accessors"][0]["sparse"] = {}
    elif fault == "bounds":
        gltf["accessors"][0]["count"] = 999999999
    elif fault == "animation":
        gltf["animations"] = [{}]
    elif fault == "cycle":
        root = gltf["scenes"][gltf.get("scene", 0)]["nodes"][0]
        gltf["nodes"][root]["children"] = [root]
    payload = json.dumps(gltf).encode()
    payload += b" " * (-len(payload) % 4)
    body = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    for kind, data in chunks[1:]:
        body += struct.pack("<II", len(data), kind) + data
    blob = struct.pack("<III", 0x46546C67, 2, len(body) + 12) + body
    if fault == "length":
        blob = blob[:-1]
    file = tmp_path / "bad.glb"
    file.write_bytes(blob)
    result = subprocess.run([HOST, "--mesh", str(file), original.stem], capture_output=True, text=True)
    assert result.returncode != 0
