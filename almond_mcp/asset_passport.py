"""Portable asset meaning and explainable, offline selection. No Rhino needed."""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PASSPORT_VERSION = 1


class Dimensions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    width: float = Field(gt=0)
    depth: float = Field(gt=0)
    height: float = Field(gt=0)


class AssetPassport(BaseModel):
    """Schema for glTF asset.extras.almond.passport and sidecar passport."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: int = Field(default=PASSPORT_VERSION, ge=1, le=1)
    asset_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,80}$")
    library_id: str = "generated_assets"
    name: str
    category: str
    tags: list[str]
    dimensions_mm: Dimensions
    nominal_dimensions_mm: Dimensions
    coordinate_convention: dict
    spatial: dict
    materials: list[dict]
    provenance: dict
    usage: dict
    quality: dict
    rights: dict


def build_passport(asset: dict, contract: dict) -> dict:
    category = asset["category"]
    rooms = {
        "bed": ["bedroom"], "desk": ["office", "bedroom"],
        "sanitary": ["bathroom"], "appliance": ["kitchen"],
        "vegetation": ["landscape"], "site_furniture": ["landscape", "streetscape"],
        "vehicle": ["streetscape"], "human_figure": ["interior", "streetscape"],
        "storage": ["living_room", "office"], "lighting": ["interior"],
        "column": ["architecture"], "railing": ["architecture"],
        "table": ["living_room", "dining_room"], "seating": ["living_room"],
    }.get(category, [])
    label = (asset["product"] + " " + asset.get("variant", "")).lower()
    if category == "seating" and any(t in label for t in ("task", "office")):
        rooms = ["office"]
    elif category in ("seating", "table") and "dining" in label:
        rooms = ["dining_room"]
    deviation = float(asset.get("plan_dimension_deviation", 0))
    warnings = ["Generated representation; not a manufacturer-verified product."]
    if deviation > 0.25:
        warnings.append("Measured width/depth differs from the prompt target by more than 25%.")
    passport = AssetPassport(
        asset_id=asset["asset_id"], name=contract["name"], category=category,
        tags=asset.get("tags", []), dimensions_mm=asset["dimensions_mm"],
        nominal_dimensions_mm=asset["nominal_dimensions_mm"],
        coordinate_convention={
            "contract_axes": "X width, Y depth, Z up",
            "glb_axes": "X width, Y up, Z depth",
            "glb_numeric_units": "mm", "contract_units": "mm",
            "note": "Legacy Almond GLBs use numeric millimetres; generic glTF readers assume metres. Apply 0.001 outside the Almond import workflow.",
        },
        spatial=asset["spatial"], materials=contract["materials"],
        provenance=asset["geometry_source"],
        usage={"suggested_rooms": rooms, "basis": "category_and_label_heuristic",
               "drawing_roles": asset.get("drawing_roles", []),
               "intended_use": ["visualisation", "concept_layout"],
               "clearance_basis": "authored_design_allowance_not_code_certification"},
        quality={"dimension_basis": "measured_normalised_geometry",
                 "plan_dimension_deviation": deviation,
                 "triangle_count": asset["triangle_count"],
                 "topology_review": "not_performed",
                 "warnings": warnings},
        rights={"model_license": asset["license"], "metadata_license": "MIT",
                "attribution": "Almond generated asset library (github.com/liangjunglj-cpu/almond-mcp)"},
    )
    return passport.model_dump()


def read_glb_chunks(data: bytes) -> list[tuple[int, bytes]]:
    """Strict container reader; preserve BIN and unknown chunks byte for byte."""
    if len(data) < 20:
        raise ValueError("Truncated GLB")
    magic, version, length = struct.unpack_from("<III", data)
    if magic != 0x46546C67 or version != 2 or length != len(data):
        raise ValueError("Invalid GLB header or length")
    chunks, offset = [], 12
    while offset < length:
        if offset + 8 > length:
            raise ValueError("Truncated GLB chunk header")
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if size % 4 or offset + size > length:
            raise ValueError("Invalid GLB chunk size")
        chunks.append((kind, data[offset:offset + size]))
        offset += size
    if not chunks or chunks[0][0] != 0x4E4F534A:
        raise ValueError("GLB must start with JSON")
    return chunks


def embed_passport(data: bytes, passport: dict) -> bytes:
    passport = AssetPassport.model_validate(passport).model_dump()
    chunks = read_glb_chunks(data)
    gltf = json.loads(chunks[0][1])
    almond = gltf.setdefault("asset", {}).setdefault("extras", {}).setdefault("almond", {})
    almond["passport"] = passport
    # Node extras are convenient for importers that expose custom properties.
    for node in gltf.get("nodes", []):
        identity = node.setdefault("extras", {}).setdefault("almond", {})
        identity.update(asset_id=passport["asset_id"], library_id=passport["library_id"],
                        passport_schema_version=PASSPORT_VERSION)
    payload = json.dumps(gltf, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
    payload += b" " * (-len(payload) % 4)
    chunks[0] = (chunks[0][0], payload)
    body = b"".join(struct.pack("<II", len(p), k) + p for k, p in chunks)
    return struct.pack("<III", 0x46546C67, 2, len(body) + 12) + body


def read_embedded_passport(path: Path) -> dict:
    gltf = json.loads(read_glb_chunks(path.read_bytes())[0][1])
    return AssetPassport.model_validate(gltf["asset"]["extras"]["almond"]["passport"]).model_dump()


def audit_library(library: Path) -> dict:
    """Offline release/install check; report every broken model, never download."""
    manifest = json.loads((library / "manifest.json").read_text(encoding="utf-8"))
    failures = []
    ids = set()
    for asset in manifest["assets"]:
        asset_id = asset["asset_id"]
        try:
            if asset_id in ids:
                raise ValueError("Duplicate asset id")
            ids.add(asset_id)
            model = (library / asset["file"]).resolve()
            contract_path = (library / asset["contract_file"]).resolve()
            model.relative_to(library.resolve())
            contract_path.relative_to(library.resolve())
            contract_bytes = contract_path.read_bytes()
            contract = json.loads(contract_bytes)
            model_hash = hashlib.sha256(model.read_bytes()).hexdigest().upper()
            if model_hash != asset["sha256"] or model_hash != contract["model_sha256"]:
                raise ValueError("Model checksum mismatch")
            if hashlib.sha256(contract_bytes).hexdigest().upper() != asset["contract_sha256"]:
                raise ValueError("Contract checksum mismatch")
            passport = read_embedded_passport(model)
            if passport != asset["passport"] or passport != contract["passport"]:
                raise ValueError("Embedded, manifest and sidecar passports disagree")
            if passport["asset_id"] != asset_id or contract["asset_id"] != asset_id:
                raise ValueError("Asset identity mismatch")
            if passport["dimensions_mm"] != asset["dimensions_mm"] or passport["dimensions_mm"] != contract["dimensions_mm"]:
                raise ValueError("Dimension metadata mismatch")
            preview = library / "previews" / f"{asset_id}.png"
            if not preview.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Preview is not PNG")
        except (OSError, ValueError, KeyError) as exc:
            failures.append({"asset_id": asset_id, "error": str(exc)})
    return {"status": "error" if failures else "success",
            "asset_pack_version": manifest.get("asset_pack_version"),
            "checked": len(manifest["assets"]), "failures": failures}


def enrich_asset(asset: dict, contract: dict, glb_path: Path, contract_path: Path) -> None:
    """Deterministic upgrade: preserve geometry, update metadata and checksums."""
    passport = build_passport(asset, contract)
    model_bytes = embed_passport(glb_path.read_bytes(), passport)
    contract["passport"] = passport
    contract["spatial"] = asset["spatial"]
    contract["model_sha256"] = hashlib.sha256(model_bytes).hexdigest().upper()
    contract_bytes = (json.dumps(contract, indent=2, allow_nan=False) + "\n").encode()
    # All validation/serialization completes before either file is changed.
    glb_path.write_bytes(model_bytes)
    contract_path.write_bytes(contract_bytes)
    asset.update(passport=passport, sha256=contract["model_sha256"],
                 contract_sha256=hashlib.sha256(contract_bytes).hexdigest().upper(),
                 file_size_bytes=len(model_bytes))


def evaluate_fit(asset: dict, width_mm: float, depth_mm: float,
                 height_mm: float = 0, rotation_degrees: float = 0,
                 include_clearances: bool = True) -> dict:
    """Conservative rotated rectangle envelope, not a room or code validator."""
    values = (width_mm, depth_mm, height_mm, rotation_degrees)
    if not all(math.isfinite(v) for v in values) or width_mm <= 0 or depth_mm <= 0 or height_mm < 0:
        raise ValueError("Width/depth must be positive, height nonnegative, and all values finite.")
    dims = Dimensions.model_validate(asset["dimensions_mm"])
    clearances = asset["spatial"].get("clearance_mm", {}) if include_clearances else {}
    c = {side: float(clearances.get(side, 0)) for side in ("left", "right", "front", "back")}
    if not all(math.isfinite(v) and v >= 0 for v in c.values()):
        raise ValueError("Invalid asset clearance")
    w = dims.width + c["left"] + c["right"]
    d = dims.depth + c["front"] + c["back"]
    angle = math.radians(rotation_degrees % 360)
    cw, sw = abs(math.cos(angle)), abs(math.sin(angle))
    required = {"width": w * cw + d * sw, "depth": w * sw + d * cw, "height": dims.height}
    margins = {"width": width_mm - required["width"], "depth": depth_mm - required["depth"],
               "height": height_mm - dims.height if height_mm else None}
    fits = all(v is None or v >= -1e-7 for v in margins.values())
    return {"asset_id": asset["asset_id"], "fits": fits,
            "rotation_degrees": rotation_degrees % 360,
            "required_envelope_mm": {k: round(v, 2) for k, v in required.items()},
            "remaining_mm": {k: round(v, 2) if v is not None else None for k, v in margins.items()},
            "includes_clearances": include_clearances,
            "support_plane": asset["spatial"].get("support_plane", "floor"),
            "method": "rotated_clearance_rectangle_aabb",
            "scope": "Envelope can fit somewhere in a rectangular space; no scene obstacles, mounting height, circulation or code compliance checked."}


def recommend(assets: list[dict], query: str = "", category: str = "",
              room_type: str = "", width_mm: float = 0, depth_mm: float = 0,
              height_mm: float = 0, max_triangles: int = 0,
              include_clearances: bool = True, limit: int = 5) -> dict:
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    if not all(math.isfinite(v) and v >= 0 for v in (width_mm, depth_mm, height_mm, max_triangles)):
        raise ValueError("Dimensions and triangle budget must be finite and nonnegative")
    if bool(width_mm) != bool(depth_mm):
        raise ValueError("Provide both width_mm and depth_mm to check fit")
    terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    room_type = room_type.strip().lower().replace(" ", "_")
    ranked = []
    for asset in assets:
        if category and asset["category"] != category:
            continue
        if not asset.get("file_available", True):
            continue
        passport = asset.get("passport")
        if not passport:
            continue
        rooms = passport["usage"]["suggested_rooms"]
        if room_type and room_type not in rooms:
            continue
        if max_triangles and asset["triangle_count"] > max_triangles:
            continue
        if height_mm and asset["dimensions_mm"]["height"] > height_mm:
            continue
        text = " ".join([asset["product"], asset.get("variant", ""), asset["category"],
                         *passport["tags"], *rooms]).lower()
        matched = sorted(terms & set(re.findall(r"[a-z0-9]+", text)))
        if terms and not matched:
            continue
        fits = []
        if width_mm:
            fits = [evaluate_fit(asset, width_mm, depth_mm, height_mm, r, include_clearances) for r in (0, 90)]
            fits = [f for f in fits if f["fits"]]
            if not fits:
                continue
        reasons = (["Matched: " + ", ".join(matched)] if matched else [])
        if room_type:
            reasons.append("Suggested room: " + room_type + " (heuristic)")
        if fits:
            reasons.append("Fits supplied rectangle at " + ", ".join(str(int(f["rotation_degrees"])) for f in fits) + " degrees")
        ranked.append({"asset_id": asset["asset_id"], "name": passport["name"],
                       "category": asset["category"], "dimensions_mm": asset["dimensions_mm"],
                       "triangle_count": asset["triangle_count"],
                       "score": len(matched), "reasons": reasons,
                       "fit_options": fits, "quality_notes": passport["quality"]["warnings"],
                       "passport_uri": f"almond://generated/{asset['asset_id']}/passport",
                       "preview_uri": f"almond://generated/{asset['asset_id']}/preview"})
    ranked.sort(key=lambda a: (-a["score"], a["asset_id"]))
    return {"status": "success", "total_matches": len(ranked), "assets": ranked[:limit],
            "ranking": "exact token overlap; explicit category, room, polygon and envelope filters",
            "next_step": "Inspect passport/preview, then place_generated_asset; register placement and validate_scene_layout."}
