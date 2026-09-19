"""Analytic geometry, unit correctness, revision checks and MCP drafting flow."""
import asyncio
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

import ezdxf
import numpy as np
import pytest

from almond_mcp import drafting as d
from test_generated_assets import load_server_module


def box_glb(path, *, xscale=1, metadata="", bad_indices=False):
    # Y-up box: 2 wide, 3 high, 4 deep.
    points = np.array([[x, y, z] for x in (0, 2) for y in (0, 3) for z in (0, 4)], dtype="<f4")
    faces = np.array([[0,1,3],[0,3,2],[4,6,7],[4,7,5], [0,4,5],[0,5,1],
                      [2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]], dtype="<u2")
    if bad_indices:
        faces[0,0] = 999
    binary = points.tobytes()+faces.tobytes()
    gltf = {"asset": {"version":"2.0", "extras": {"note":metadata}},
            "buffers":[{"byteLength":len(binary)}],
            "bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":points.nbytes},
                           {"buffer":0,"byteOffset":points.nbytes,"byteLength":faces.nbytes}],
            "accessors":[{"bufferView":0,"componentType":5126,"count":8,"type":"VEC3"},
                         {"bufferView":1,"componentType":5123,"count":36,"type":"SCALAR"}],
            "meshes":[{"primitives":[{"attributes":{"POSITION":0},"indices":1}]}],
            "nodes":[{"mesh":0,"scale":[xscale,1,1]}], "scenes":[{"nodes":[0]}],"scene":0}
    payload = json.dumps(gltf).encode()
    payload += b" "*(-len(payload)%4)
    body = struct.pack("<II",len(payload),0x4E4F534A)+payload+struct.pack("<II",len(binary),0x004E4942)+binary
    path.write_bytes(struct.pack("<III",0x46546C67,2,len(body)+12)+body)
    return path


def test_projection_matches_analytic_box_units_and_node_transform(tmp_path):
    model = box_glb(tmp_path/"box.glb", xscale=2)
    triangles = d.load_triangles(model, "m")
    plan = d.project(triangles, "plan", 0)
    assert plan["bounds_mm"] == pytest.approx([0,-4000,4000,0])
    assert plan["area_mm2"] == pytest.approx(16_000_000)
    front = d.project(triangles, "front", 0)
    assert front["bounds_mm"] == pytest.approx([0,0,4000,3000])
    assert len(plan["rings"]) == 1


def test_union_preserves_real_opening_instead_of_convex_hull():
    triangles = []
    for x0,y0,x1,y1 in [(0,0,10,2),(0,8,10,10),(0,2,2,8),(8,2,10,8)]:
        a,b,c,e = [x0,y0,0],[x1,y0,0],[x1,y1,0],[x0,y1,0]
        triangles += [[a,b,c],[a,c,e]]
    result = d.project(np.array(triangles), "plan", .1)
    assert result["area_mm2"] == pytest.approx(64)
    assert [r["role"] for r in result["rings"]].count("hole") == 1


def test_exports_have_physical_scale_valid_dxf_and_revision_detection(tmp_path):
    model = box_glb(tmp_path/"box.glb")
    output = tmp_path/"drawing"
    result = d.create_package(model, output, asset_id="box", name="Box & <test>", units="m", scales=[50])
    assert result["status"] == "success"
    root = ET.parse(output/"plan-1-50.svg").getroot()
    assert float(root.attrib["width"].removesuffix("mm")) == pytest.approx(50)
    sheet = ET.parse(output/"sheet-A3-1-50.svg").getroot()
    assert sheet.attrib["width"] == "420mm"
    dx = ezdxf.readfile(output/"plan-1-50.dxf")
    assert dx.units == 4
    assert not dx.audit().errors
    line = list(dx.modelspace())[0]
    assert line.closed
    assert max(p[0] for p in line.get_points()) == pytest.approx(2000)
    assert d.audit_package(output, model)["source_geometry"] == "current"
    box_glb(model, metadata="metadata-only update")
    assert d.audit_package(output, model)["source_geometry"] == "current"
    box_glb(model, xscale=2)
    assert d.audit_package(output, model)["source_geometry"] == "stale"
    (output/"plan-1-50.svg").write_text("tampered")
    assert any("Changed output" in x for x in d.audit_package(output)["failures"])


def test_dense_projection_approximation_preserves_resolvable_hole():
    triangles = []
    for x0,y0,x1,y1 in [(0,0,10,2),(0,8,10,10),(0,2,2,8),(8,2,10,8)]:
        a,b,c,e = [x0,y0],[x1,y0],[x1,y1],[x0,y1]
        triangles += [[a,b,c],[a,c,e]]
    geometry, pixel_mm = d._raster_outline(np.array(triangles), [0,0,10,10])
    assert geometry.is_valid
    assert geometry.area == pytest.approx(64, rel=.01)
    assert sum(len(p.interiors) for p in geometry.geoms) == 1
    assert pixel_mm == pytest.approx(10/2044)


def test_rejects_unsafe_or_ambiguous_inputs(tmp_path):
    model = box_glb(tmp_path/"box.glb")
    for units in ("", "cm", "auto"):
        with pytest.raises(ValueError, match="Explicit input units"):
            d.load_triangles(model, units)
    with pytest.raises(ValueError, match="Invalid triangle indices"):
        d.load_triangles(box_glb(model, bad_indices=True), "mm")
    box_glb(model)
    for scales in ([0], [float("nan")], [50,50]):
        with pytest.raises(ValueError, match="scale"):
            d.create_package(model, tmp_path/"out", asset_id="box", name="Box", units="mm", scales=scales)
    with pytest.raises(ValueError, match="already exists"):
        d.create_package(model, tmp_path, asset_id="box", name="Box", units="mm")
    with pytest.raises(ValueError):
        d.create_package(model, tmp_path/"bad-ref", asset_id="box", name="Box", units="mm", references=[{"url":"https://example.org"}])


def test_mcp_custom_mesh_sources_and_drawing_resources(tmp_path, monkeypatch):
    from fastmcp import Client
    from almond_mcp import paths
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path/"user")
    model = box_glb(tmp_path/"custom.glb")
    server = load_server_module()

    async def run():
        async with Client(server.mcp) as client:
            tools = {t.name:t for t in await client.list_tools()}
            assert not tools["generate_asset_drawing_views"].annotations.readOnlyHint
            result = await client.call_tool("search_detail_sources", {"query":"timber"})
            assert "dataholz" in [s["source_id"] for s in result.structured_content["sources"]]
            sources = await client.call_tool("get_generation_sources", {"asset_id":"gen-stool-bent-birch-3leg-1"})
            assert sources.structured_content["record"]["image_generation"]["provider"] == "higgsfield"
            bad = await client.call_tool("generate_asset_drawing_views", {"source_glb":str(model)})
            assert bad.structured_content["status"] == "error"
            result = await client.call_tool("generate_asset_drawing_views", {"source_glb":str(model), "input_units":"m", "scales":[50]})
            assert result.structured_content["status"] == "success", result
            audited = await client.call_tool("audit_asset_drawing", {"package_dir":result.structured_content["package_dir"],"source_glb":str(model)})
            assert audited.structured_content["source_geometry"] == "current"
            svg = await client.read_resource("almond://generated/gen-park-bench-1/drawing/plan/50")
            assert svg[0].mimeType == "image/svg+xml"
    asyncio.run(run())
