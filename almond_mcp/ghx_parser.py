"""
GHX/GH Parser for Rhino AI MCP Plugin (v1.2)

Grasshopper files (.gh/.ghx) are DEFLATE-compressed .NET BinaryFormatter blobs.
This parser decompresses them and extracts readable component names, parameter
descriptions, and structural context using binary string scanning.
"""
import os
import zlib
import json
import re
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Tuple

# ── Data Models ──────────────────────────────────────────────────────────────

class PhysicsComponent(BaseModel):
    """A detected Kangaroo2 or Karamba3D component."""
    name: str = Field(description="Component name, e.g., Solver, Anchor, Assemble Model")
    category: str = Field(default="unknown", description="Category: kangaroo, karamba, grasshopper, or unknown")
    descriptions: List[str] = Field(default_factory=list, description="Associated description strings found near this component")

class GHPhysicsContext(BaseModel):
    """Extracted physics context from a Grasshopper file."""
    file_name: str = Field(description="Source file name")
    components: List[PhysicsComponent] = Field(default_factory=list)
    all_descriptions: List[str] = Field(default_factory=list, description="All meaningful description strings found")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extra metadata from JSON sidecar if available")

# ── Known Component Keywords ─────────────────────────────────────────────────

KANGAROO_COMPONENTS = {
    'Solver', 'BouncySolver', 'KangarooSolver', 'Zombie',
    'Anchor', 'OnCurve', 'OnMesh', 'OnPlane', 'OnLine', 'OnSurface',
    'EdgeLengths', 'Length', 'LengthLine', 'LengthSnap',
    'Spring', 'Unary', 'CatenaryCustom',
    'Angle', 'Hinge', 'Rod', 'Cable',
    'Pressure', 'Load', 'Wind', 'Gravity',
    'Floor', 'Collide', 'SphereCollide',
    'Inflate', 'Volume', 'SoapFilm',
    'Rigid', 'RigidBody', 'RigidPointSet',
    'Shear', 'Plastic', 'PlasticAnchor',
    'ClampedEnd', 'Rest', 'Grab',
    'Show', 'MeshMachine', 'Remesh',
    'EqualizeLength', 'Planarize', 'Tangential',
    'CurvatureFlow', 'Laplacian', 'Smoothing',
}

KARAMBA_COMPONENTS = {
    'Analyze', 'Analyse', 'Assemble', 'AssembleModel',
    'ModelView', 'BeamView', 'ShellView',
    'CrossSection', 'CrossSectionSelector', 'CrossSectionRange',
    'Support', 'PointLoad', 'LineLoad', 'MeshLoad',
    'Disassemble', 'DisassembleModel',
    'Optimize', 'BESO', 'Utilization',
    'Deformation', 'Material', 'MaterialSelection',
    'LinearElement', 'CreateLinearElement',
    'Loads', 'DefineLoads', 'DefineSupports', 'DefineMaterials',
    'BucklingLength', 'Buckling',
    'LargeDeformation', 'FormFinding', 'Membrane',
    'PrincipalStress', 'ForceFlow',
}

# ── Capsule Manifests ────────────────────────────────────────────────────────
# A capsule is a GH definition plus a sidecar manifest (<name>.capsule.json)
# declaring a typed input/output contract bound by reserved ALMOND_IN_* /
# ALMOND_OUT_* NickNames. See capsules/capsule.schema.json for the full schema.
# Validation here is a small manual check (no jsonschema runtime dependency).

CAPSULE_REQUIRED_KEYS = ("capsule_id", "capability", "definition_file", "inputs", "outputs", "audited")
CAPSULE_CAPABILITIES = {"analyze", "generate", "form_find", "aggregate"}
from almond_mcp import paths as _paths

CAPSULES_DIR = _paths.resolve_dir("RHINO_MCP_CAPSULE_DIR")


def validate_capsule_manifest(manifest: Any) -> List[str]:
    """Manually validate a capsule manifest against the required contract.

    Returns a list of human-readable errors; an empty list means valid.
    Intentionally dependency-light: mirrors the required keys and port name
    rules of capsules/capsule.schema.json without pulling in jsonschema.
    """
    errors: List[str] = []
    if not isinstance(manifest, dict):
        return ["Manifest must be a JSON object."]

    for key in CAPSULE_REQUIRED_KEYS:
        if key not in manifest:
            errors.append(f"Missing required key: {key}")
    if errors:
        return errors

    if not isinstance(manifest["capsule_id"], str) or not manifest["capsule_id"].strip():
        errors.append("capsule_id must be a non-empty string.")
    if manifest["capability"] not in CAPSULE_CAPABILITIES:
        errors.append(
            f"capability must be one of {sorted(CAPSULE_CAPABILITIES)}, "
            f"got {manifest['capability']!r}."
        )
    definition_file = manifest["definition_file"]
    if not isinstance(definition_file, str) or not definition_file.lower().endswith((".gh", ".ghx")):
        errors.append("definition_file must be a .gh or .ghx filename.")
    if not isinstance(manifest["audited"], bool):
        errors.append("audited must be a boolean.")

    for field, prefix in (("inputs", "ALMOND_IN_"), ("outputs", "ALMOND_OUT_")):
        ports = manifest[field]
        if not isinstance(ports, list):
            errors.append(f"{field} must be a list.")
            continue
        for index, port in enumerate(ports):
            label = f"{field}[{index}]"
            if not isinstance(port, dict):
                errors.append(f"{label} must be an object.")
                continue
            name = port.get("name")
            if not isinstance(name, str) or not name.startswith(prefix):
                errors.append(f"{label}.name must be a string starting with {prefix}.")
            if not isinstance(port.get("type"), str) or not port.get("type"):
                errors.append(f"{label}.type must be a non-empty string.")
    return errors


def find_capsule_manifest(file_path: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Locate the capsule sidecar for a GH/GHX file.

    Looks for <stem>.capsule.json next to the file first, then scans the
    plugin's capsules/ directory for a manifest whose definition_file matches
    the file's basename. Returns (manifest_path, manifest) or None.
    """
    file_name = os.path.basename(file_path)
    candidates: List[str] = []

    sidecar_path = os.path.splitext(file_path)[0] + ".capsule.json"
    if os.path.isfile(sidecar_path):
        candidates.append(sidecar_path)

    if os.path.isdir(CAPSULES_DIR):
        for entry in sorted(os.listdir(CAPSULES_DIR)):
            if entry.lower().endswith(".capsule.json"):
                candidates.append(os.path.join(CAPSULES_DIR, entry))

    for candidate in candidates:
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        if not isinstance(manifest, dict):
            continue
        # The adjacent sidecar always wins; capsules/ entries match by filename.
        if candidate == sidecar_path or manifest.get("definition_file") == file_name:
            return candidate, manifest
    return None


# ── Parser ───────────────────────────────────────────────────────────────────

class GHParser:
    """Parses Grasshopper .gh/.ghx binary files by decompressing and scanning strings."""

    SUPPORTED_EXTENSIONS = {'.gh', '.ghx'}

    def __init__(self, file_path: str):
        self.file_path = file_path

    def _decompress(self) -> bytes:
        """Decompress the DEFLATE-compressed Grasshopper file."""
        with open(self.file_path, 'rb') as f:
            raw = f.read()

        # Check if it's already plain XML (unlikely but handle gracefully)
        if raw[:5] == b'<?xml' or raw[:8] == b'<Archive':
            return raw

        # Try raw DEFLATE (most common for GH/GHX)
        try:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
        except zlib.error:
            pass

        # Try gzip
        try:
            return zlib.decompress(raw, zlib.MAX_WBITS | 16)
        except zlib.error:
            pass

        # Try standard zlib
        try:
            return zlib.decompress(raw, zlib.MAX_WBITS)
        except zlib.error:
            pass

        raise ValueError(f"Cannot decompress file: {self.file_path}. Not a recognized Grasshopper format.")

    def _extract_strings(self, data: bytes, min_len: int = 5) -> List[str]:
        """Extract readable ASCII strings from binary data."""
        results = []
        current = []
        for b in data:
            if 32 <= b < 127:
                current.append(chr(b))
            else:
                if len(current) >= min_len:
                    results.append(''.join(current))
                current = []
        if len(current) >= min_len:
            results.append(''.join(current))
        return results

    def _classify_component(self, name: str) -> str:
        """Classify a component string as kangaroo, karamba, or grasshopper."""
        name_lower = name.lower()
        if 'karamba' in name_lower:
            return 'karamba'
        for kw in KANGAROO_COMPONENTS:
            if kw.lower() == name_lower or kw.lower() in name_lower:
                return 'kangaroo'
        for kw in KARAMBA_COMPONENTS:
            if kw.lower() == name_lower or kw.lower() in name_lower:
                return 'karamba'
        return 'grasshopper'

    def _clean_string(self, s: str) -> str:
        """Strip leading non-alphabetic garbage from .NET BinaryFormatter length-prefix leaks."""
        # Skip leading chars that aren't letters or spaces (e.g., '7Length...' → 'Length...')
        i = 0
        while i < len(s) and not s[i].isalpha():
            i += 1
        return s[i:] if i < len(s) else s

    def _is_description(self, s: str) -> bool:
        """Check if a string looks like a meaningful description vs noise."""
        if ' ' not in s:
            return False
        alpha_ratio = sum(c.isalpha() or c.isspace() for c in s) / len(s)
        if alpha_ratio < 0.6:
            return False
        if len(s) < 15:
            return False
        return True

    def parse(self) -> GHPhysicsContext:
        """Parse the Grasshopper file and extract physics context."""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"File not found: {self.file_path}")

        ext = os.path.splitext(self.file_path)[1].lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type '{ext}'. Expected .gh or .ghx")

        context = GHPhysicsContext(file_name=os.path.basename(self.file_path))

        # Load JSON sidecar metadata if it exists
        base_no_ext = os.path.splitext(self.file_path)[0]
        for sidecar_ext in ['.json']:
            sidecar_path = base_no_ext + sidecar_ext
            if os.path.exists(sidecar_path):
                try:
                    with open(sidecar_path, 'r') as f:
                        context.metadata = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass

        # Load capsule manifest (adjacent <stem>.capsule.json or capsules/ dir)
        capsule_hit = find_capsule_manifest(self.file_path)
        if capsule_hit:
            manifest_path, manifest = capsule_hit
            capsule_errors = validate_capsule_manifest(manifest)
            if capsule_errors:
                context.metadata["capsule_errors"] = {
                    "manifest_path": manifest_path,
                    "errors": capsule_errors,
                }
            else:
                context.metadata["capsule"] = manifest
                context.metadata["capsule_manifest_path"] = manifest_path

        # Decompress and extract strings
        data = self._decompress()
        strings = self._extract_strings(data, min_len=5)
        unique_strings = list(dict.fromkeys(strings))  # preserve order, deduplicate

        # Build keyword sets for matching (lowercase)
        all_keywords = KANGAROO_COMPONENTS | KARAMBA_COMPONENTS

        # Detect components
        seen_components = set()
        for s in unique_strings:
            cleaned = self._clean_string(s.strip())
            if not cleaned:
                continue

            # Direct match against known component names
            for kw in all_keywords:
                if kw.lower() in cleaned.lower() and cleaned not in seen_components:
                    category = self._classify_component(cleaned)
                    context.components.append(PhysicsComponent(
                        name=cleaned,
                        category=category,
                    ))
                    seen_components.add(cleaned)
                    break

        # Collect meaningful descriptions
        for s in unique_strings:
            cleaned = self._clean_string(s.strip())
            if self._is_description(cleaned) and cleaned not in seen_components:
                context.all_descriptions.append(cleaned)

        return context


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        parser = GHParser(sys.argv[1])
        try:
            res = parser.parse()
            print(res.model_dump_json(indent=2))
        except Exception as e:
            print(f"Error parsing: {e}")

