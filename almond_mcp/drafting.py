"""Traceable static-mesh silhouettes in millimetres; no Rhino required."""
from __future__ import annotations

import hashlib
import html
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
import re
import struct

import numpy as np
import shapely
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from almond_mcp.asset_passport import read_glb_chunks

ENGINE_VERSION = 2
MAX_TRIANGLES = 250_000
LIMITATIONS = [
    "Projected silhouettes only: internal visible/hidden edges and construction layers are not inferred.",
    "Front is the declared coordinate direction, not a verified product front.",
    "Dimensions describe mesh geometry, not a manufacturer-verified product.",
]


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    publisher: str = Field(min_length=1, max_length=200)
    author: str = Field(default="unknown", max_length=200)
    locator: str = Field(min_length=1, max_length=300)
    accessed_on: date
    relationship: str = Field(pattern=r"^(background_reading|dimensional_reference|assembly_reference|post_generation_reference)$")
    used_for: str = Field(min_length=1, max_length=500)
    terms_url: HttpUrl
    redistribution: str = Field(default="unreviewed", pattern=r"^(unreviewed|metadata_only|permitted|restricted)$")
    evidence_status: str = Field(default="user_supplied_unverified", pattern=r"^(user_supplied_unverified|reviewed)$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        matrix = np.asarray(node["matrix"], dtype=float).reshape(4, 4, order="F")
    else:
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        if not math.isclose(x*x+y*y+z*z+w*w, 1, abs_tol=1e-4):
            raise ValueError("Node rotation is not a unit quaternion")
        matrix = np.array([
            [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), 0],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), 0],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), 0],
            [0, 0, 0, 1]], dtype=float)
        matrix[:3, :3] *= np.asarray(node.get("scale", [1, 1, 1]))
        matrix[:3, 3] = node.get("translation", [0, 0, 0])
    if not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0, 0, 0, 1]):
        raise ValueError("Non-finite or non-affine node transform")
    return matrix


def load_triangles(path: Path, units: str, up_axis: str = "y", *, data: bytes | None = None) -> np.ndarray:
    """Decode a bounded, static, uncompressed triangle GLB. Fail on unsupported features."""
    if units not in {"mm", "m"} or up_axis not in {"y", "z"}:
        raise ValueError("Explicit input units (mm/m) and up axis (y/z) are required")
    if path.stat().st_size > 100_000_000:
        raise ValueError("GLB exceeds 100 MB limit")
    chunks = read_glb_chunks(path.read_bytes() if data is None else data)
    gltf = json.loads(chunks[0][1])
    bins = [p for k, p in chunks if k == 0x004E4942]
    if len(bins) != 1 or len(gltf.get("buffers", [])) != 1 or gltf["buffers"][0].get("uri"):
        raise ValueError("Only one embedded GLB buffer is supported")
    if gltf.get("animations") or gltf.get("skins") or gltf.get("extensionsRequired"):
        raise ValueError("Animated, skinned or required-extension GLBs are unsupported; export a static uncompressed mesh")
    binary = bins[0]
    if gltf["buffers"][0]["byteLength"] > len(binary):
        raise ValueError("Truncated GLB binary buffer")

    def accessor(index, positions=False):
        a = gltf["accessors"][index]
        if a.get("sparse") or a.get("normalized"):
            raise ValueError("Sparse/normalized accessors are unsupported")
        types = {5121: "<u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
        kind = a["componentType"]
        if kind not in types or a["type"] != ("VEC3" if positions else "SCALAR"):
            raise ValueError("Unsupported position/index accessor")
        if positions and kind != 5126 or not positions and kind == 5126:
            raise ValueError("Positions must be float32; indices must be unsigned integers")
        view = gltf["bufferViews"][a["bufferView"]]
        if view.get("buffer", 0) != 0 or view.get("extensions"):
            raise ValueError("Only uncompressed embedded buffer views are supported")
        dtype = np.dtype(types[kind])
        width = 3 if positions else 1
        stride = view.get("byteStride", dtype.itemsize * width)
        start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
        count = a["count"]
        end = start + (count-1)*stride + dtype.itemsize*width
        if (count < 1 or count > MAX_TRIANGLES*3 or stride < dtype.itemsize*width
                or start < view.get("byteOffset", 0) or end > len(binary)
                or end > view.get("byteOffset", 0)+view["byteLength"]):
            raise ValueError("Invalid or oversized accessor bounds")
        data = np.ndarray((count, width), dtype=dtype, buffer=binary, offset=start,
                          strides=(stride, dtype.itemsize)).copy()
        if not np.isfinite(data).all():
            raise ValueError("Non-finite geometry")
        return data

    scene = gltf.get("scenes", [])[gltf.get("scene", 0)]
    stack = [(n, np.eye(4), frozenset()) for n in scene.get("nodes", [])]
    triangles, count, visited = [], 0, 0
    while stack:
        index, parent, ancestors = stack.pop()
        visited += 1
        if index in ancestors or visited > 10000:
            raise ValueError("Cyclic or oversized scene graph")
        node = gltf["nodes"][index]
        world = parent @ _matrix(node)
        if "skin" in node or node.get("weights"):
            raise ValueError("Skinning/morph weights are unsupported")
        if "mesh" in node:
            for primitive in gltf["meshes"][node["mesh"]]["primitives"]:
                if primitive.get("mode", 4) != 4 or primitive.get("targets") or primitive.get("extensions"):
                    raise ValueError("Only static, uncompressed TRIANGLES primitives are supported")
                p = accessor(primitive["attributes"]["POSITION"], True).astype(float)
                ids = accessor(primitive["indices"]).ravel() if "indices" in primitive else np.arange(len(p))
                if len(ids) % 3 or ids.max() >= len(p):
                    raise ValueError("Invalid triangle indices")
                count += len(ids)//3
                if count > MAX_TRIANGLES:
                    raise ValueError("Mesh exceeds 250,000 triangle limit")
                p = p @ world[:3, :3].T + world[:3, 3]
                triangles.append(p[ids].reshape(-1, 3, 3))
        stack.extend((c, world, ancestors | {index}) for c in node.get("children", []))
    if not triangles:
        raise ValueError("No triangle geometry in default scene")
    result = np.concatenate(triangles) * (1000 if units == "m" else 1)
    if up_axis == "y":
        # Standard right-handed Y-up -> right-handed Z-up. Front looks along +Y.
        result = result[:, :, [0, 2, 1]] * [1, -1, 1]
    if not np.isfinite(result).all() or np.abs(result).max() > 1e9:
        raise ValueError("Geometry outside supported finite millimetre range")
    return result


def geometry_hash(triangles: np.ndarray) -> str:
    return sha(np.asarray(triangles, dtype="<f8").tobytes())


def _raster_outline(points, bounds):
    """Bounded approximation for dense foliage; retain explicit resolution metadata."""
    from PIL import Image, ImageDraw
    import contourpy
    x0, y0, x1, y1 = bounds
    pixel_mm = max(x1-x0, y1-y0)/2044
    if pixel_mm <= 0:
        raise ValueError("Degenerate projection")
    width, height = int(math.ceil((x1-x0)/pixel_mm))+5, int(math.ceil((y1-y0)/pixel_mm))+5
    mask = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    screen = (points-[x0,y0])/pixel_mm+2
    for triangle in screen:
        draw.polygon([tuple(p) for p in triangle], fill=1)
    contours, offsets = contourpy.contour_generator(
        z=np.asarray(mask, dtype=float), fill_type="OuterOffset").filled(.5, 1.5)
    polygons = []
    for coordinates, boundaries in zip(contours, offsets):
        world = (coordinates-2)*pixel_mm+[x0,y0]
        rings = [world[a:b] for a,b in zip(boundaries[:-1],boundaries[1:])]
        polygons.append(shapely.Polygon(rings[0], rings[1:]))
    if not polygons:
        raise ValueError("No raster silhouette")
    return shapely.MultiPolygon(polygons), pixel_mm


def project(triangles: np.ndarray, view: str, tolerance_mm: float) -> dict:
    axes = {"plan": (0, 1), "front": (0, 2), "right": (1, 2)}
    if view not in axes or not math.isfinite(tolerance_mm) or tolerance_mm < 0:
        raise ValueError("Invalid view or tolerance")
    points = triangles[:, :, axes[view]]
    # Orient right elevation consistently with a view from +X.
    if view == "right":
        points = points.copy()
        points[:, :, 0] *= -1
    a, b = points[:, 1]-points[:, 0], points[:, 2]-points[:, 0]
    area = np.abs(a[:, 0]*b[:, 1]-a[:, 1]*b[:, 0])
    points = points[area > 1e-10]
    if not len(points):
        raise ValueError(f"No projected surface area in {view}")
    bounds = [float(points[:,:,0].min()), float(points[:,:,1].min()),
              float(points[:,:,0].max()), float(points[:,:,1].max())]
    # Mesh-order batches dissolve adjacent triangles before the global union.
    # A 0.01 mm precision grid avoids numerical slivers in overlapping foliage.
    if len(triangles) > 30000:
        union, pixel_mm = _raster_outline(points, bounds)
        method = "raster_to_vector_silhouette"
    else:
        faces = shapely.polygons(points)
        union = shapely.union_all([
            shapely.union_all(faces[i:i+512], grid_size=0.01)
            for i in range(0, len(faces), 512)
        ], grid_size=0.01)
        pixel_mm, method = None, "projected_triangle_union"
    # Dense foliage uses a deliberate drafting approximation: small openings
    # may collapse. Avoid quadratic topology preservation across thousands of holes.
    outline = union.simplify(tolerance_mm, preserve_topology=not bool(pixel_mm))
    if outline.is_empty or (pixel_mm is None and not outline.is_valid):
        raise ValueError("Projection produced invalid geometry")
    polygons = list(outline.geoms) if outline.geom_type == "MultiPolygon" else [outline]
    rings = []
    for poly in polygons:
        for role, ring in [("exterior", poly.exterior), *[("hole", r) for r in poly.interiors]]:
            rings.append({"role": role, "points": [[float(x), float(y)] for x, y in ring.coords]})
    return {"view": view, "bounds_mm": bounds,
            "method": method, "raster_pixel_mm": pixel_mm,
            "approximation_note": "Subpixel openings/features can disappear; raster boundary plus simplification error is not independently measured" if pixel_mm else None,
            "precision_grid_mm": None if pixel_mm else 0.01,
            "simplification_tolerance_mm": tolerance_mm,
            "preserve_topology": not bool(pixel_mm),
            "area_mm2": outline.area, "rings": rings,
            "deviation_basis": "raster_and_simplification_approximation" if pixel_mm else "topology_preserving_simplification_tolerance_not_independently_measured"}


def _path(rings, scale=1, dx=0, dy=0):
    return " ".join("M " + " L ".join(f"{dx+x/scale:.5f},{dy-y/scale:.5f}" for x, y in r["points"]) + " Z" for r in rings)


def svg_view(view, scale, metadata):
    x0, y0, x1, y1 = view["bounds_mm"]
    width, height = (x1-x0)/scale+10, (y1-y0)/scale+10
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.5f}mm" height="{height:.5f}mm" viewBox="0 0 {width:.5f} {height:.5f}">'
            f'<metadata>{html.escape(json.dumps(metadata))}</metadata>'
            f'<title>{html.escape(metadata["asset_id"])} / {view["view"]} / 1:{scale}</title>'
            f'<path d="{_path(view["rings"], scale, 5-x0/scale, 5+y1/scale)}" fill="none" stroke="#111" stroke-width="0.25"/></svg>')


def write_dxf(path: Path, view: dict, asset_id: str):
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.units = 4  # INSUNITS millimetres; DXF geometry always full size.
    doc.layers.new("ALMOND-DRAW-PROFILE", dxfattribs={"color": 7, "lineweight": 25})
    for ring in view["rings"]:
        doc.modelspace().add_lwpolyline(ring["points"][:-1], close=True,
                                      dxfattribs={"layer": "ALMOND-DRAW-PROFILE"})
    doc.header["$PROJECTNAME"] = asset_id
    doc.saveas(path)


def sheet_svg(views, scale, metadata, title):
    """A3 landscape. Refuse to shrink an oversized view silently."""
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">',
             '<rect width="420" height="297" fill="white"/>',
             f'<metadata>{html.escape(json.dumps(metadata))}</metadata>',
             '<g font-family="Arial, sans-serif" fill="#20252b">',
             f'<text x="15" y="21" font-size="6">ALMOND / {html.escape(title[:65])}</text>',
             f'<text x="15" y="30" font-size="3.5">Mesh silhouettes / 1:{scale} / measured geometry / mm</text>']
    for i, view in enumerate(views):
        x0, y0, x1, y1 = view["bounds_mm"]
        w, h = (x1-x0)/scale, (y1-y0)/scale
        if w > 115 or h > 180:
            raise ValueError(f"{view['view']} does not fit A3 at 1:{scale}; choose a larger scale denominator")
        left = 15+i*130
        parts.extend([
            f'<text x="{left}" y="48" font-size="4">{view["view"].upper()}</text>',
            f'<path d="{_path(view["rings"], scale, left+(115-w)/2-x0/scale, 58+h+y0/scale)}" fill="none" stroke="#111" stroke-width="0.25"/>',
            f'<text x="{left}" y="251" font-size="3">Extent {(x1-x0):.1f} x {(y1-y0):.1f} mm</text>',
        ])
    parts.extend([
        f'<text x="15" y="263" font-size="2.7">Source: {html.escape(metadata["asset_id"])} / geometry {metadata["geometry_sha256"][:16]}</text>',
        '<text x="15" y="270" font-size="2.7">Outlines only. Dense meshes use raster approximation; see manifest. Front requires review.</text>',
        '<text x="15" y="277" font-size="2.7">Print at 100% / actual size. This calibration line must measure 50 mm on paper.</text>',
        '<path d="M 15 285 H 65 M 15 283 V 287 M 65 283 V 287" stroke="#111" stroke-width="0.25" fill="none"/>',
        '</g></svg>',
    ])
    return "".join(parts)


def create_package(model: Path, output: Path, *, asset_id: str, name: str,
                   units: str, up_axis: str = "y", scales=(50, 100),
                   references=(), source_record=None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", asset_id) or asset_id in {".", ".."}:
        raise ValueError("Invalid asset ID")
    if not scales or len(scales) > 4 or len(set(scales)) != len(scales) or any(type(s) is not int or s < 5 or s > 1000 for s in scales):
        raise ValueError("Supply 1-4 distinct integer scale denominators between 5 and 1000")
    if len(references) > 30:
        raise ValueError("At most 30 source references per drawing package")
    refs = [SourceReference.model_validate(r).model_dump(mode="json") for r in references]
    if len({r["source_id"] for r in refs}) != len(refs):
        raise ValueError("Duplicate source reference ID")
    if output.exists():
        raise ValueError("Output directory already exists; select a new directory to preserve prior revisions")
    if model.stat().st_size > 100_000_000:
        raise ValueError("GLB exceeds 100 MB limit")
    data = model.read_bytes()
    triangles = load_triangles(model, units, up_axis, data=data)
    meta = {"asset_id": asset_id, "geometry_sha256": geometry_hash(triangles),
            "model_sha256": sha(data), "units": "mm", "input_units": units,
            "input_up_axis": up_axis, "coordinate_transform": "X,-Z,Y" if up_axis == "y" else "identity",
            "view_axes": {"plan": "X,Y", "front": "X,Z; looking +Y", "right": "-Y,Z; looking -X"},
            "dimension_basis": "measured_mesh_geometry", "engine_version": ENGINE_VERSION,
            "method": "triangle_union_or_dense_mesh_raster_projection; see per-view method and resolution",
            "source_references": refs,
            "reference_relationship_scope": "attached_to_this_drawing; not original mesh-generation inputs",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "attribution": "Almond generated asset library" if source_record and source_record.get("declared_license") else "User-supplied mesh; rights unverified",
            "derived_asset_license": source_record.get("declared_license", "unknown") if source_record else "unknown",
            "generation_record": source_record,
            "limitations": LIMITATIONS}
    files, representations = {}, []
    for scale in scales:
        views = [project(triangles, v, min(0.05*scale, 5.0)) for v in ("plan", "front", "right")]
        for view in views:
            key = f'{view["view"]}-1-{scale}'
            files[f"{key}.svg"] = svg_view(view, scale, {**meta, "drawing_view": {k:v for k,v in view.items() if k != "rings"}})
            representations.append({**view, "scale": scale, "svg": f"{key}.svg", "dxf": f"{key}.dxf"})
        try:
            files[f"sheet-A3-1-{scale}.svg"] = sheet_svg(views, scale, {**meta, "drawing_views": [{k:v for k,v in v.items() if k != "rings"} for v in views]}, name)
        except ValueError as exc:
            meta.setdefault("sheet_warnings", []).append(str(exc))
    files["views.json"] = json.dumps(representations, separators=(",", ":"))
    output.mkdir(parents=True)
    for filename, content in files.items():
        (output/filename).write_text(content, encoding="utf-8")
    for view in representations:
        write_dxf(output/view["dxf"], view, asset_id)
    manifest = {"schema_version": 1, "name": name, "source": meta,
                "triangle_count": len(triangles), "scales": list(scales),
                "representations": [{k: v for k, v in r.items() if k != "rings"} for r in representations],
                "files": {p.name: sha(p.read_bytes()) for p in sorted(output.iterdir())}}
    (output/"drawing.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"status": "success", "package_dir": str(output.resolve()), "manifest": manifest}


def audit_package(package: Path, source_model: Path | None = None) -> dict:
    manifest = json.loads((package/"drawing.json").read_text(encoding="utf-8"))
    failures = []
    for filename, checksum in manifest["files"].items():
        path = (package/filename).resolve()
        try:
            path.relative_to(package.resolve())
            if sha(path.read_bytes()) != checksum:
                failures.append(f"Changed output: {filename}")
        except (OSError, ValueError):
            failures.append(f"Missing or unsafe output: {filename}")
    source_state = "not_checked"
    if source_model is not None:
        meta = manifest["source"]
        triangles = load_triangles(source_model, meta["input_units"], meta["input_up_axis"])
        source_state = "current" if geometry_hash(triangles) == meta["geometry_sha256"] else "stale"
        if source_state == "stale":
            failures.append("Source geometry changed; regenerate drawing views")
    return {"status": "error" if failures else "success", "source_geometry": source_state,
            "asset_id": manifest["source"]["asset_id"], "checked_files": len(manifest["files"]),
            "failures": failures}
