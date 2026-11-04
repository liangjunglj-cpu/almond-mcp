"""Shadow plans: the model seen from above with the sun's shadows at a date and time, ray traced on the
analysis scene, drawn in the diagrams' palette.

Each pixel casts a ray down to the first surface it meets (a roof, a terrace or the ground plane at the
lowest point of the model) and a second ray from there towards the sun; the point is in shadow when an
opaque surface is in the way. Glazing does not cast shadows here. Because it uses the same scene as the
daylight and thermal studies, a shadow plan shows exactly the obstructions those studies see, which a
viewport's display settings do not guarantee.
"""
from __future__ import annotations

import math

import numpy as np

from . import diagrams
from .raytrace import BVH

LIT_GROUND = diagrams._hex(diagrams.PAPER)
SHADE_GROUND = (0xb4, 0xb3, 0xaa)
LIT_TOP = (0xdd, 0xdc, 0xd4)
SHADE_TOP = (0x8f, 0x8e, 0x86)
EDGE = diagrams._hex(diagrams.INK)


def _footprint(scene, ground_z: float) -> tuple[np.ndarray, np.ndarray]:
    """xy bounds of everything above the ground (a big modelled ground plane must not set the extent)."""
    a, b, c = scene.corners()
    top = np.maximum(np.maximum(a[:, 2], b[:, 2]), c[:, 2])
    keep = top > ground_z + 0.05
    if not keep.any():
        keep = np.ones(len(a), dtype=bool)
    pts = np.vstack([a[keep], b[keep], c[keep]])
    return pts[:, :2].min(axis=0), pts[:, :2].max(axis=0)


def without_room_volumes(scene, data: dict):
    """The scene without the objects that only describe a room (a zone volume or a boundary curve); a room
    defined by its bounding surfaces (a roof on posts) keeps them, they are building elements."""
    from . import rooms as rm
    from .scene import Scene
    volume = {g.lower() for r in rm.rooms_from_export(data, []) if r.source in ("volume", "boundary") for g in r.guids}
    drop = np.zeros(len(scene.triangles), dtype=bool)
    for k, o in enumerate(scene.objects):
        if str(o.get("guid", "")).lower() in volume:
            drop |= scene.tri_object == k
    if not drop.any():
        return scene
    keep = ~drop
    return Scene(scene.vertices, scene.triangles[keep], scene.tri_material[keep], scene.tri_object[keep],
                 scene.materials, scene.objects, scene.north_deg)


def extent_for(scene, sun_dirs, ground_z: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """One plan extent for several sun positions: the footprint plus the longest shadow, padded."""
    v = scene.vertices
    zmax = float(v[:, 2].max())
    gz = float(v[:, 2].min()) if ground_z is None else float(ground_z)
    lo0, hi0 = _footprint(scene, gz)
    lo, hi = lo0.copy(), hi0.copy()
    for s in sun_dirs:
        s = np.asarray(s, float) / np.linalg.norm(s)
        if s[2] <= 0:
            continue
        reach = min((zmax - gz) / math.tan(math.asin(min(s[2], 1.0))), 3.0 * float(np.max(hi0 - lo0)) + 10.0)
        shift = -s[:2] / max(np.linalg.norm(s[:2]), 1e-9) * reach
        lo, hi = np.minimum(lo, lo0 + shift), np.maximum(hi, hi0 + shift)
    pad = 0.06 * float(np.max(hi - lo)) + 1.0
    return lo - pad, hi + pad


def shadow_plan(scene, sun_dir, pixels: int = 640, extent: tuple[np.ndarray, np.ndarray] | None = None,
                ground_z: float | None = None):
    """(RGB image array, info) of the plan with shadows for one sun direction (unit vector towards the sun,
    model coordinates). ``extent`` = (xy min, xy max); by default the footprint plus the longest shadow."""
    sun = np.asarray(sun_dir, float)
    sun = sun / np.linalg.norm(sun)
    if sun[2] <= 0:
        raise ValueError("The sun is below the horizon")
    v = scene.vertices
    zmin, zmax = float(v[:, 2].min()), float(v[:, 2].max())
    gz = zmin if ground_z is None else float(ground_z)
    lo, hi = extent_for(scene, [sun], gz) if extent is None else (np.asarray(extent[0], float), np.asarray(extent[1], float))
    span = hi - lo
    cell = float(max(span)) / pixels
    nx, ny = max(int(math.ceil(span[0] / cell)), 1), max(int(math.ceil(span[1] / cell)), 1)
    xs = lo[0] + (np.arange(nx) + 0.5) * cell
    ys = hi[1] - (np.arange(ny) + 0.5) * cell                  # image rows run north to south
    X, Y = np.meshgrid(xs, ys)
    n = X.size
    a, b, c = scene.corners()
    kinds = np.array([m.kind for m in scene.materials])[scene.tri_material]
    opaque = kinds == "opaque"
    every = BVH(a, b, c)
    solid = BVH(a[opaque], b[opaque], c[opaque])
    origins = np.column_stack([X.ravel(), Y.ravel(), np.full(n, zmax + 1.0)])
    down = np.tile([0.0, 0.0, -1.0], (n, 1))
    t, tri = every.intersect(origins, down)
    hit = np.isfinite(t) & (tri >= 0)
    p = origins.copy()
    p[:, 2] = np.where(hit, zmax + 1.0 - np.where(hit, t, 0.0), gz)
    normals, _ = scene.normals()
    nrm = np.tile([0.0, 0.0, 1.0], (n, 1))
    nrm[hit] = normals[tri[hit]]
    nrm[hit & (nrm[:, 2] < 0)] *= -1.0                         # face the ray that found it
    lit_face = (nrm @ sun) > 1e-6
    t2, _ = solid.intersect(p + nrm * 1e-3 + sun * 1e-3, np.tile(sun, (n, 1)))
    shaded = np.isfinite(t2) | ~lit_face
    top = hit & (p[:, 2] > gz + 0.05)
    img = np.empty((n, 3), dtype=np.uint8)
    img[:] = LIT_GROUND
    img[shaded] = SHADE_GROUND
    img[top & ~shaded] = LIT_TOP
    img[top & shaded] = SHADE_TOP
    img = img.reshape(ny, nx, 3)
    # outlines where the surface height jumps: plan edges of roofs and walls
    hgt = p[:, 2].reshape(ny, nx)
    jump = max(0.3, 2 * cell)
    edge = np.zeros((ny, nx), dtype=bool)
    edge[:, 1:] |= np.abs(np.diff(hgt, axis=1)) > jump
    edge[1:, :] |= np.abs(np.diff(hgt, axis=0)) > jump
    img[edge] = EDGE
    info = {"extent_m": [lo.round(2).tolist(), hi.round(2).tolist()], "cell_m": round(cell, 3), "pixels": [nx, ny],
            "ground_z_m": round(gz, 3), "shadow_share_of_ground_pct": round(100 * float((shaded & ~top).sum()) / max(int((~top).sum()), 1), 1)}
    return img, info


def plan_sheet(images: list[tuple[np.ndarray, str]], sun_azimuths: list[float], north_deg: float, title: str,
               cell_m: float, path: str) -> str:
    """Lay one or more shadow plans side by side with captions, a sun arrow, a north arrow and a scale bar."""
    from PIL import Image, ImageDraw
    pad, cap_h, head = 24, 46, 44
    w = max(im.shape[1] for im, _ in images)
    h = max(im.shape[0] for im, _ in images)
    W = pad + len(images) * (w + pad)
    H = head + h + cap_h + pad
    sheet = Image.new("RGB", (W, H), LIT_GROUND)
    d = ImageDraw.Draw(sheet)
    d.text((pad, 14), title, fill=EDGE, font=diagrams._font(17, False, True))
    mono = diagrams._font(12, True, False)
    for k, ((im, caption), az) in enumerate(zip(images, sun_azimuths)):
        x0 = pad + k * (w + pad)
        sheet.paste(Image.fromarray(im), (x0, head))
        d.rectangle([x0, head, x0 + im.shape[1] - 1, head + im.shape[0] - 1], outline=diagrams._hex(diagrams.LINE))
        d.text((x0, head + im.shape[0] + 10), caption, fill=EDGE, font=mono)
        # the sun's direction in the plan: a dial with the sun on its rim and a ray towards the centre
        cx, cy, r = x0 + im.shape[1] - 36, head + 36, 24
        a = math.radians(az - north_deg)
        sx, sy = cx + r * math.sin(a), cy - r * math.cos(a)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=diagrams._hex(diagrams.MUTED), width=1)
        d.line([(sx, sy), (cx, cy)], fill=diagrams._hex(diagrams.RED), width=2)
        d.ellipse([sx - 5, sy - 5, sx + 5, sy + 5], fill=diagrams._hex(diagrams.RED))
        d.text((cx - 13, cy + r + 3), "SUN", fill=diagrams._hex(diagrams.MUTED), font=diagrams._font(10, True, False))
    # north arrow and scale bar on the first plan
    nx0, ny0 = pad + 26, head + 30
    na = math.radians(-north_deg)
    tip = (nx0 + 16 * math.sin(na), ny0 - 16 * math.cos(na))
    d.line([(nx0 - 16 * math.sin(na), ny0 + 16 * math.cos(na)), tip], fill=EDGE, width=2)
    d.text((tip[0] - 4, tip[1] - 18), "N", fill=EDGE, font=diagrams._font(13, False, True))
    metres = 10 ** math.floor(math.log10(max(cell_m * w / 4, 1e-3)))
    for m in (5, 2, 1):
        if m * metres <= cell_m * w / 4:
            metres *= m
            break
    L = metres / cell_m
    by = head + h - 18
    d.rectangle([pad + 12, by, pad + 12 + L, by + 5], fill=EDGE)
    d.text((pad + 12, by - 16), f"{metres:g} m", fill=EDGE, font=mono)
    sheet.save(path)
    return path
