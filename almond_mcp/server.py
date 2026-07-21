"""
MCP Server for Rhino AI Plugin (v1.4)

Exposes tools for Claude to:
  1. list_library          — discover available physics archetypes
  2. get_logic_by_id       — retrieve parsed physics context for a specific archetype
  3. execute_rhino_script  — send C# RhinoCommon code to the Rhino bridge
  4. validate_structure    — run Karamba3D structural analysis on generated geometry
"""
import os
import json
import socket
import hashlib
import re
import sys
import tempfile
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from fastmcp import FastMCP
from almond_mcp.ghx_parser import GHParser, validate_capsule_manifest
from almond_mcp.retrieval_store import AlmondStore
from almond_mcp import exchange, paths

# ── Constants ────────────────────────────────────────────────────────────────

DELIMITER = b'\n<<EOF>>\n'
LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_LIBRARY_DIR")
FURNITURE_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_FURNITURE_DIR")
DRAWING_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_DRAWING_ASSET_DIR")
DIAGRAM_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_DIAGRAM_ASSET_DIR")
DRAWING_RECIPE_DIR = paths.resolve_dir("RHINO_MCP_DRAWING_RECIPE_DIR")
CAPSULE_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_CAPSULE_DIR")
MATERIAL_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_MATERIAL_DIR")
STATE_DB_PATH = paths.resolve_state_db()
BRIDGE_HOST = '127.0.0.1'
BRIDGE_PORT = 5000
CHESTNUT_URL = os.environ.get(
    "CHESTNUT_URL",
    "https://chestnut-mnvo.onrender.com",
).rstrip("/")
print(f"Chestnut publish target: {CHESTNUT_URL}", file=sys.stderr)

# ── MCP Server ───────────────────────────────────────────────────────────────

mcp = FastMCP("RhinoAI_Library")

# ── Library Indexer ──────────────────────────────────────────────────────────

class LibraryIndexer:
    """Walks the library directory once at startup, building an O(1) lookup index."""

    INDEXED_EXTENSIONS = {'gh', 'ghx', 'json'}

    def __init__(self, directory: str):
        self.directory = directory
        self.index: dict[str, dict[str, str]] = {}
        self._build_index()

    def _build_index(self):
        print(f"Indexing library from: {self.directory}")
        for root, _, files in os.walk(self.directory):
            for file in files:
                ext = file.rsplit('.', 1)[-1].lower() if '.' in file else ''
                if ext in self.INDEXED_EXTENSIONS:
                    logic_id = file.rsplit('.', 1)[0].lower()
                    if logic_id not in self.index:
                        self.index[logic_id] = {}
                    self.index[logic_id][ext] = os.path.join(root, file)
        print(f"Indexed {len(self.index)} unique logic entities.")

    def list_ids(self) -> list[str]:
        """Return sorted list of all indexed logic IDs."""
        return sorted(self.index.keys())


class AssetLibraryIndexer:
    """Indexes one controlled asset manifest and resolves safe local files."""

    def __init__(self, directory: str, library_id: str, label: str):
        self.directory = Path(directory).resolve()
        self.manifest_path = self.directory / "manifest.json"
        self.library_id = library_id
        self.label = label
        self.assets: dict[str, dict] = {}
        self.catalogue_region = ""
        self.catalogue_checked = ""
        self._load()

    def _load(self):
        if not self.manifest_path.is_file():
            print(f"{self.label} manifest not found: {self.manifest_path}", file=sys.stderr)
            return

        with self.manifest_path.open("r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)

        self.catalogue_region = manifest.get("catalogue_region", "")
        self.catalogue_checked = manifest.get("catalogue_checked", "")
        manifest_library_id = manifest.get("library_id", self.library_id)
        if manifest_library_id != self.library_id:
            print(
                f"Skipping {self.label}: expected library_id {self.library_id}, "
                f"found {manifest_library_id}.",
                file=sys.stderr,
            )
            return
        for asset in manifest.get("assets", []):
            asset_id = str(asset.get("asset_id", "")).strip()
            relative_file = str(asset.get("file", "")).strip()
            if not asset_id or not relative_file:
                continue
            resolved_file = (self.directory / relative_file).resolve()
            try:
                resolved_file.relative_to(self.directory)
            except ValueError:
                print(f"Skipping {self.label} asset outside library root: {asset_id}", file=sys.stderr)
                continue
            record = dict(asset)
            record["library_id"] = self.library_id
            record["_resolved_file"] = str(resolved_file)
            record["file_available"] = resolved_file.is_file()
            self.assets[asset_id] = record

        print(f"Indexed {len(self.assets)} {self.label} assets.", file=sys.stderr)

    def public_record(self, asset: dict) -> dict:
        return {key: value for key, value in asset.items() if not key.startswith("_")}

    def get(self, asset_id: str) -> dict | None:
        return self.assets.get(asset_id)

    def search(
        self,
        query: str = "",
        category: str = "",
        max_width_mm: float = 0,
        max_depth_mm: float = 0,
        max_height_mm: float = 0,
        exact_dimensions_only: bool = False,
        limit: int = 10,
    ) -> list[dict]:
        query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        category = category.lower().strip()
        results = []

        for asset in self.assets.values():
            if category and asset.get("category", "").lower() != category:
                continue
            if exact_dimensions_only and asset.get("match_status") != "exact_dimensions":
                continue

            dimensions = asset.get("dimensions_mm", {})
            if max_width_mm > 0 and dimensions.get("width", 0) > max_width_mm:
                continue
            if max_depth_mm > 0 and dimensions.get("depth", 0) > max_depth_mm:
                continue
            if max_height_mm > 0 and dimensions.get("height", 0) > max_height_mm:
                continue

            searchable = " ".join([
                asset.get("series", ""),
                asset.get("product", ""),
                asset.get("variant", ""),
                asset.get("category", ""),
                " ".join(asset.get("tags", [])),
            ]).lower()
            score = sum(1 for token in query_tokens if token in searchable)
            if query_tokens and score == 0:
                continue
            results.append((score, asset.get("series", ""), self.public_record(asset)))

        results.sort(key=lambda item: (-item[0], item[1], item[2]["asset_id"]))
        return [item[2] for item in results[:max(1, min(limit, 50))]]


class DrawingRecipeIndexer:
    """Loads audited drawing-style recipes from a controlled directory."""

    def __init__(self, directory: str):
        self.directory = Path(directory).resolve()
        self.recipes: dict[str, dict] = {}
        if not self.directory.is_dir():
            print(f"Drawing recipe directory not found: {self.directory}", file=sys.stderr)
            return
        for recipe_path in sorted(self.directory.glob("*.json")):
            try:
                recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
                recipe_id = str(recipe.get("recipe_id", "")).strip()
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", recipe_id):
                    raise ValueError("invalid recipe_id")
                recipe["_source_file"] = str(recipe_path)
                self.recipes[recipe_id] = recipe
            except Exception as exc:
                print(f"Skipping drawing recipe {recipe_path.name}: {exc}", file=sys.stderr)
        print(f"Indexed {len(self.recipes)} drawing recipes.", file=sys.stderr)

    def get(self, recipe_id: str) -> dict | None:
        return self.recipes.get(recipe_id)

    @staticmethod
    def public_record(recipe: dict) -> dict:
        return {key: value for key, value in recipe.items() if not key.startswith("_")}


# Build index once on startup
indexer = LibraryIndexer(LIBRARY_DIR)
furniture_indexer = AssetLibraryIndexer(
    FURNITURE_LIBRARY_DIR,
    library_id="ikea",
    label="IKEA",
)
drawing_asset_indexer = AssetLibraryIndexer(
    DRAWING_LIBRARY_DIR,
    library_id="drawing_assets",
    label="drawing",
)
diagram_asset_indexer = AssetLibraryIndexer(
    DIAGRAM_LIBRARY_DIR,
    library_id="diagram_assets",
    label="diagram",
)
drawing_recipe_indexer = DrawingRecipeIndexer(DRAWING_RECIPE_DIR)


class MaterialLibrary:
    """Curated PBR material definitions (Materialfiles/manifest.json)."""

    REQUIRED = ("material_id", "name", "category", "base_color",
                "metallic", "roughness", "opacity", "ue_material_slot")

    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.materials: dict[str, dict] = {}
        manifest_path = self.directory / "manifest.json"
        if not manifest_path.is_file():
            print(f"Material manifest missing: {manifest_path}", file=sys.stderr)
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Material manifest unreadable: {exc}", file=sys.stderr)
            return
        for material in manifest.get("materials", []):
            if not all(key in material for key in self.REQUIRED):
                continue
            self.materials[material["material_id"]] = material
        print(f"Indexed {len(self.materials)} PBR materials.", file=sys.stderr)

    def get(self, material_id: str) -> dict | None:
        return self.materials.get(material_id)

    def list(self, category: str = "", query: str = "") -> list[dict]:
        needle = query.strip().lower()
        results = []
        for material in self.materials.values():
            if category and material["category"] != category:
                continue
            if needle:
                haystack = " ".join([
                    material["material_id"], material["name"],
                    material.get("description", ""),
                    " ".join(material.get("tags", [])),
                ]).lower()
                if needle not in haystack:
                    continue
            results.append(material)
        return results


material_library = MaterialLibrary(MATERIAL_LIBRARY_DIR)
retrieval_store = AlmondStore(STATE_DB_PATH)
retrieval_store.sync_assets(
    list(drawing_asset_indexer.assets.values()),
    library_id="drawing_assets",
)
retrieval_store.sync_assets(
    list(furniture_indexer.assets.values()),
    library_id="ikea",
)
retrieval_store.sync_assets(
    list(diagram_asset_indexer.assets.values()),
    library_id="diagram_assets",
)


def _sync_capsule_library(store: AlmondStore, capsules_dir: str) -> dict:
    """Scan <capsules_dir>/*.capsule.json sidecars, validate each manifest via
    ghx_parser.validate_capsule_manifest, and sync the valid ones into the
    AlmondStore capsule registry.

    Invalid manifests are skipped loudly (stderr) rather than aborting startup,
    so one bad sidecar cannot take down the whole capsule library. The absolute
    sidecar path is recorded on each manifest (_manifest_path) so run_gh_definition
    can hand it to the bridge.
    """
    manifests: list[dict] = []
    skipped: list[dict] = []
    directory = Path(capsules_dir)
    if not directory.is_dir():
        print(f"Capsule directory not found: {directory}", file=sys.stderr)
        store.sync_capsules([])
        return {"synced": 0, "skipped": skipped}

    for manifest_path in sorted(directory.glob("*.capsule.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            skipped.append({"file": manifest_path.name, "errors": [str(exc)]})
            continue
        errors = validate_capsule_manifest(manifest)
        if errors:
            skipped.append({"file": manifest_path.name, "errors": errors})
            continue
        manifest["_manifest_path"] = str(manifest_path.resolve())
        manifests.append(manifest)

    for entry in skipped:
        print(
            f"Skipping capsule manifest {entry['file']}: {entry['errors']}",
            file=sys.stderr,
        )
    synced = store.sync_capsules(manifests)
    print(f"Synced {synced} capsule manifests from {directory}.", file=sys.stderr)
    return {"synced": synced, "skipped": skipped}


capsule_sync_report = _sync_capsule_library(retrieval_store, CAPSULE_LIBRARY_DIR)

# ── TCP Helpers ──────────────────────────────────────────────────────────────

def _send_and_receive(payload_bytes: bytes, timeout: float = 60.0) -> str:
    """Send payload to the Rhino bridge using a length-prefix protocol and receive response."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((BRIDGE_HOST, BRIDGE_PORT))

        # Length-prefix: send 4-byte big-endian length header, then data
        length = len(payload_bytes)
        s.sendall(length.to_bytes(4, 'big'))
        s.sendall(payload_bytes)

        # Receive: read 4-byte length header, then exact data
        header = b''
        while len(header) < 4:
            chunk = s.recv(4 - len(header))
            if not chunk:
                raise ConnectionError("Bridge closed connection while reading response header.")
            header += chunk

        resp_length = int.from_bytes(header, 'big')
        resp_data = b''
        while len(resp_data) < resp_length:
            chunk = s.recv(min(16384, resp_length - len(resp_data)))
            if not chunk:
                raise ConnectionError("Bridge closed connection while reading response body.")
            resp_data += chunk

        return resp_data.decode('utf-8')
    finally:
        s.close()


_CAPSULE_GEOMETRY_TYPES = {
    "point", "point[]",
    "curve", "curve[]",
    "mesh", "mesh[]",
    "brep", "brep[]",
}


def _capsule_input_error(port: dict, value) -> str | None:
    """Validate one capsule input value against its manifest port declaration.

    Returns a human-readable error string, or None when the value satisfies the
    contract. Geometry ports must arrive as {"guids": [...]} references to
    objects already in the Rhino document; primitive ports must match their
    declared JSON type exactly.
    """
    name = port.get("name", "?")
    port_type = str(port.get("type", ""))
    units = port.get("units", "")
    units_note = f" (units: {units})" if units else ""

    def _is_number(item) -> bool:
        return (
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and abs(item) != float("inf")
            and item == item
        )

    if port_type in _CAPSULE_GEOMETRY_TYPES:
        if (
            not isinstance(value, dict)
            or set(value.keys()) != {"guids"}
            or not isinstance(value.get("guids"), list)
            or not value["guids"]
            or not all(isinstance(guid, str) and guid.strip() for guid in value["guids"])
        ):
            return (
                f'{name} ({port_type}) must be a GUID reference of the exact form '
                '{"guids": ["<rhino-object-guid>", ...]} with at least one GUID string, '
                "referencing objects already in the Rhino document."
            )
        return None

    if port_type == "number":
        if not _is_number(value):
            return f"{name} must be a finite number{units_note}."
    elif port_type == "integer":
        if not (isinstance(value, int) and not isinstance(value, bool)):
            return f"{name} must be an integer{units_note}."
    elif port_type == "bool":
        if not isinstance(value, bool):
            return f"{name} must be a boolean."
    elif port_type == "string":
        if not isinstance(value, str):
            return f"{name} must be a string."
    elif port_type == "number[]":
        if not (isinstance(value, list) and all(_is_number(item) for item in value)):
            return f"{name} must be a flat list of finite numbers{units_note}."
    elif port_type == "integer[]":
        if not (
            isinstance(value, list)
            and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
        ):
            return f"{name} must be a flat list of integers{units_note}."
    elif port_type == "string[]":
        if not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
            return f"{name} must be a flat list of strings."
    else:
        return (
            f"{name} declares unsupported type {port_type!r} in its manifest; "
            "fix the capsule sidecar before running it."
        )
    return None


def _slug(value: str) -> str:
    """Create a filesystem/API-safe identifier without losing stable identity."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "rhino-asset"


def _post_multipart(url: str, fields: dict[str, str], file_path: str) -> dict:
    """POST a GLB and text fields using only the Python standard library."""
    boundary = f"----AlmondMCP{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])

    filename = os.path.basename(file_path)
    with open(file_path, "rb") as glb:
        file_bytes = glb.read()
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: model/gltf-binary\r\n\r\n",
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])

    request = urllib.request.Request(
        url,
        data=b"".join(chunks),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Chestnut returned HTTP {exc.code}: {detail}") from exc

# ── MCP Tools ────────────────────────────────────────────────────────────────

@mcp.tool()
def list_library() -> str:
    """
    Lists all available physics logic archetypes in the Grasshopper library.
    Use this tool first to discover what logic IDs are available before
    calling get_logic_by_id.

    Returns:
        JSON list of logic IDs available (e.g., ["catenary", "bending", "01_simplebeam"]).
    """
    return json.dumps({
        "library_dir": LIBRARY_DIR,
        "total_entries": len(indexer.index),
        "logic_ids": indexer.list_ids(),
    })


@mcp.tool()
def get_logic_by_id(logic_id: str) -> str:
    """
    Retrieves parsed physics context for a specific Kangaroo2 or Karamba3D archetype.
    Returns detected components, descriptions, and metadata extracted from the
    Grasshopper binary file.

    Args:
        logic_id: The filename (without extension) of the Grasshopper file.
                  Use list_library() first to see available IDs.
                  Examples: catenary, bending, 01_simplebeam
    Returns:
        JSON string with detected physics components and context, or error.
    """
    query_id = logic_id.lower()
    file_map = indexer.index.get(query_id)

    if not file_map:
        return json.dumps({"error": f"Logic '{logic_id}' not found. Use list_library() to see available IDs."})

    # Prioritize GHX > GH > JSON-only
    target_file = file_map.get('ghx') or file_map.get('gh')
    target_json = file_map.get('json')

    # If only a JSON sidecar exists, return it directly
    if target_json and not target_file:
        try:
            with open(target_json, 'r') as f:
                data = json.load(f)
            return json.dumps({"logic_id": logic_id, "source": target_json, "metadata": data})
        except Exception as e:
            return json.dumps({"error": f"Failed to read JSON sidecar: {e}"})

    # Parse via the binary string extractor
    try:
        parser = GHParser(target_file)
        context = parser.parse()
        return context.model_dump_json()
    except Exception as e:
        return json.dumps({"error": f"Failed to parse '{target_file}': {str(e)}"})


@mcp.tool()
def list_ikea_furniture(
    category: str = "",
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Lists furniture in the controlled IKEA Singapore model library.

    Args:
        category: Optional exact category filter such as "chair", "sofa", or "storage".
    Returns:
        Compact paginated asset cards. Use get_ikea_furniture only for a
        selected asset that needs full metadata.
    """
    page = retrieval_store.search_assets(
        library_id="ikea",
        category=category,
        limit=limit,
        offset=offset,
    )
    return json.dumps({
        "catalogue_region": furniture_indexer.catalogue_region,
        "catalogue_checked": furniture_indexer.catalogue_checked,
        **page,
    })


@mcp.tool()
def search_ikea_furniture(
    query: str = "",
    category: str = "",
    max_width_mm: float = 0,
    max_depth_mm: float = 0,
    max_height_mm: float = 0,
    exact_dimensions_only: bool = False,
    limit: int = 10,
    offset: int = 0,
) -> str:
    """
    Searches IKEA furniture by product language and room-fit dimensions.

    Use this before placing furniture. Prefer exact-dimension matches for final layouts;
    series-only matches are useful for concept design but are labelled as such.
    """
    page = retrieval_store.search_assets(
        query=query,
        library_id="ikea",
        category=category,
        max_width_mm=max_width_mm,
        max_depth_mm=max_depth_mm,
        max_height_mm=max_height_mm,
        exact_dimensions_only=exact_dimensions_only,
        limit=limit,
        offset=offset,
    )
    return json.dumps(page)


@mcp.tool()
def get_ikea_furniture(asset_id: str) -> str:
    """Returns one IKEA furniture asset's dimensions, provenance, and availability."""
    asset = retrieval_store.get_asset(asset_id, library_id="ikea")
    if not asset:
        return json.dumps({"status": "error", "message": f"Unknown furniture asset_id: {asset_id}"})
    return json.dumps({"status": "success", "asset": asset})


@mcp.tool()
def list_drawing_assets(
    category: str = "",
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Lists representation-only entourage and graphic proxy assets.

    Drawing assets are intentionally isolated from IKEA product search and do
    not participate in room collision checks unless explicitly registered.
    """
    page = retrieval_store.search_assets(
        library_id="drawing_assets",
        category=category,
        limit=limit,
        offset=offset,
    )
    return json.dumps({
        "library_id": "drawing_assets",
        "purpose": "architectural representation and entourage",
        **page,
    })


@mcp.tool()
def search_drawing_assets(
    query: str = "",
    category: str = "",
    max_width_mm: float = 0,
    max_depth_mm: float = 0,
    max_height_mm: float = 0,
    limit: int = 10,
    offset: int = 0,
) -> str:
    """Searches only the controlled architectural drawing-asset library."""
    return json.dumps(retrieval_store.search_assets(
        query=query,
        library_id="drawing_assets",
        category=category,
        max_width_mm=max_width_mm,
        max_depth_mm=max_depth_mm,
        max_height_mm=max_height_mm,
        limit=limit,
        offset=offset,
    ))


@mcp.tool()
def get_drawing_asset(asset_id: str) -> str:
    """Returns one drawing asset's provenance, scale guidance, and availability."""
    asset = retrieval_store.get_asset(asset_id, library_id="drawing_assets")
    if not asset:
        return json.dumps({
            "status": "error",
            "message": f"Unknown drawing asset_id: {asset_id}",
        })
    return json.dumps({"status": "success", "asset": asset})


@mcp.tool()
def list_drawing_recipes() -> str:
    """Lists compact audited layer, lineweight, projection, and export recipes."""
    recipes = []
    for recipe_id, recipe in sorted(drawing_recipe_indexer.recipes.items()):
        recipes.append({
            "recipe_id": recipe_id,
            "name": recipe.get("name"),
            "description": recipe.get("description"),
            "projection": recipe.get("projection", {}).get("type"),
            "recommended_scales": recipe.get("recommended_scales", []),
        })
    return json.dumps({"total": len(recipes), "recipes": recipes})


@mcp.tool()
def get_drawing_recipe(recipe_id: str) -> str:
    """Returns one complete audited drawing recipe."""
    recipe = drawing_recipe_indexer.get(recipe_id)
    if not recipe:
        return json.dumps({
            "status": "error",
            "message": f"Unknown drawing recipe_id: {recipe_id}",
        })
    return json.dumps({
        "status": "success",
        "recipe": drawing_recipe_indexer.public_record(recipe),
    })


@mcp.tool()
def get_retrieval_status() -> str:
    """Returns compact diagnostics for the local structured retrieval system."""
    return json.dumps({
        "status": "ready",
        "database": STATE_DB_PATH,
        "asset_index": retrieval_store.asset_stats(),
        "ikea_index": retrieval_store.asset_stats("ikea"),
        "drawing_asset_index": retrieval_store.asset_stats("drawing_assets"),
        "drawing_recipes": len(drawing_recipe_indexer.recipes),
        "retrieval": ["sqlite", "fts5", "rtree"],
        "embedding_adapter": "not_configured",
    })


@mcp.tool()
def create_design_scene(name: str, units: str = "mm") -> str:
    """
    Creates a persistent scene handle for a house or interior generation.
    Scene metadata remains local and is retrieved by ID instead of being
    repeated in the model context.
    """
    try:
        return json.dumps({
            "status": "success",
            "scene": retrieval_store.create_scene(name=name, units=units),
        })
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


@mcp.tool()
def get_design_scene(scene_id: str) -> str:
    """Returns a token-efficient scene summary by stable handle."""
    scene = retrieval_store.get_scene(scene_id)
    if not scene:
        return json.dumps({"status": "error", "message": f"Unknown scene_id: {scene_id}"})
    return json.dumps({"status": "success", "scene": scene})


@mcp.tool()
def upsert_design_room(
    scene_id: str,
    name: str,
    bounds_mm: list[float],
    room_id: str = "",
) -> str:
    """
    Creates or updates a room in the local scene ledger.
    bounds_mm is [min_x, min_y, min_z, max_x, max_y, max_z]. When room_id is
    omitted, an existing room with the same name in the scene is updated
    instead of creating a duplicate.
    """
    try:
        result = retrieval_store.upsert_room(
            scene_id=scene_id,
            name=name,
            bounds_mm=bounds_mm,
            room_id=room_id,
        )
        return json.dumps({"status": "success", **result})
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


@mcp.tool()
def register_scene_instance(
    scene_id: str,
    asset_id: str,
    x_mm: float,
    y_mm: float,
    z_mm: float | None = None,
    rotation_degrees: float = 0,
    scale: float = 1,
    room_id: str = "",
    instance_id: str = "",
    locked: bool = False,
    rhino_guid: str = "",
) -> str:
    """
    Registers or moves an asset instance in millimetres without retransmitting
    its full metadata. Returns a stable instance handle and scene revision.
    When z_mm is omitted the instance stands on its room's floor (the room's
    min_z), so rooms at storey elevation validate correctly.
    """
    try:
        result = retrieval_store.upsert_instance(
            scene_id=scene_id,
            asset_id=asset_id,
            x_mm=x_mm,
            y_mm=y_mm,
            z_mm=z_mm,
            rotation_degrees=rotation_degrees,
            scale=scale,
            room_id=room_id,
            instance_id=instance_id,
            locked=locked,
            rhino_guid=rhino_guid,
        )
        return json.dumps({"status": "success", **result})
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


@mcp.tool()
def remove_scene_instance(scene_id: str, instance_id: str) -> str:
    """
    Removes an instance from the scene ledger (recorded as a revision delta).
    The Rhino geometry, if any, is not touched.
    """
    try:
        result = retrieval_store.remove_instance(scene_id, instance_id)
        return json.dumps({"status": "success", **result})
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


@mcp.tool()
def remove_design_room(scene_id: str, room_id: str) -> str:
    """
    Removes a room from the scene ledger. Instances that referenced it stay
    in the scene, orphaned (re-home them with register_scene_instance).
    """
    try:
        result = retrieval_store.remove_room(scene_id, room_id)
        return json.dumps({"status": "success", **result})
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


@mcp.tool()
def validate_scene_layout(scene_id: str, detail_limit: int = 50) -> str:
    """
    Runs local R-tree broad-phase collision and room-containment checks.
    Only compact violations are returned; geometry remains in Rhino.
    """
    try:
        return json.dumps({
            "status": "success",
            **retrieval_store.validate_scene(scene_id, limit=detail_limit),
        })
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


@mcp.tool()
def create_generation_plan(
    goal: str,
    scope: str = "house",
    scene_id: str = "",
) -> str:
    """
    Creates a dependency-ordered local plan. scope may be house, interior,
    structure, or drawing. The plan stores handles and step state rather than verbose
    repeated context.
    """
    try:
        return json.dumps({
            "status": "success",
            "plan": retrieval_store.create_generation_plan(
                goal=goal,
                scope=scope,
                scene_id=scene_id,
            ),
        })
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


@mcp.tool()
def get_generation_plan(plan_id: str) -> str:
    """Returns a compact dependency graph and current step states."""
    plan = retrieval_store.get_generation_plan(plan_id)
    if not plan:
        return json.dumps({"status": "error", "message": f"Unknown plan_id: {plan_id}"})
    return json.dumps({"status": "success", "plan": plan})


@mcp.tool()
def update_generation_step(
    plan_id: str,
    step_id: str,
    status: str,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
) -> str:
    """
    Advances a generation step after its dependencies complete. Input and
    output references should be stable scene, room, asset, instance, or Rhino
    GUID handles.
    """
    try:
        return json.dumps({
            "status": "success",
            "plan": retrieval_store.update_plan_step(
                plan_id=plan_id,
                step_id=step_id,
                status=status,
                input_refs=input_refs,
                output_refs=output_refs,
            ),
        })
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


@mcp.tool()
def place_ikea_furniture(
    asset_id: str,
    x: float = 0,
    y: float = 0,
    z: float = 0,
    rotation_degrees: float = 0,
    scale: float = 1,
) -> str:
    """
    Imports an indexed IKEA SketchUp model into Rhino 8 as a reusable block and places an instance.

    The asset is imported only when its block definition does not already exist. Subsequent calls
    create lightweight instances. Position uses the active Rhino document units; rotation is around
    world Z. The tool never accepts an arbitrary file path.
    """
    asset = furniture_indexer.get(asset_id)
    if not asset:
        return json.dumps({"status": "error", "message": f"Unknown furniture asset_id: {asset_id}"})
    if not asset.get("file_available"):
        return json.dumps({"status": "error", "message": f"Furniture file is missing for {asset_id}."})
    if asset.get("geometry_status") == "defective":
        return json.dumps({
            "status": "error",
            "message": f"{asset_id} has known-defective source geometry and is "
                       f"excluded from placement: {asset.get('geometry_note', 'see manifest')}",
        })

    numeric_values = [x, y, z, rotation_degrees, scale]
    if not all(isinstance(value, (int, float)) and abs(value) != float("inf") and value == value for value in numeric_values):
        return json.dumps({"status": "error", "message": "Placement values must be finite numbers."})
    if scale <= 0 or scale > 100:
        return json.dumps({"status": "error", "message": "scale must be greater than 0 and no more than 100."})

    payload = json.dumps({
        "type": "place_furniture",
        "asset_id": asset_id,
        "file_path": asset["_resolved_file"],
        "name": f"{asset.get('series', '')} {asset.get('product', '')}".strip(),
        "position": [x, y, z],
        "rotation_degrees": rotation_degrees,
        "scale": scale,
        "metadata": {
            "series": asset.get("series"),
            "product": asset.get("product"),
            "variant": asset.get("variant"),
            "category": asset.get("category"),
            "dimensions_mm": asset.get("dimensions_mm"),
            "ikea_product_id": asset.get("ikea_product_id"),
            "ikea_url": asset.get("ikea_url"),
            "warehouse_url": asset.get("warehouse_url"),
            "warehouse_status": asset.get("warehouse_status"),
            "match_status": asset.get("match_status"),
        },
    }).encode("utf-8")

    try:
        response = _send_and_receive(payload, timeout=90.0)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Rhino furniture import timed out."})
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Rhino bridge is unavailable. Start RhinoAlmondBridge first."})
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Furniture placement failed: {exc}"})

    # Post-import QA: compare the real placed bounds against the catalogue
    # dimensions, and apply any manifest-declared geometry correction.
    try:
        result = json.loads(response)
    except (TypeError, ValueError):
        return response
    if not isinstance(result, dict) or result.get("status") != "success":
        return response
    check = _dimension_check(asset, result.get("bounds"), scale)
    if check:
        result["dimension_check"] = check
    correction = asset.get("import_correction") or {}
    rotate_x = float(correction.get("rotate_x_degrees", 0) or 0)
    if rotate_x and result.get("object_guid"):
        result["import_correction_applied"] = _apply_import_correction(
            result["object_guid"], rotate_x, z
        )
    return json.dumps(result)


def _dimension_check(asset: dict, bounds: dict | None, scale: float) -> dict | None:
    """Flags gross mismatches between placed AABB and catalogue dimensions.

    Sorted-extent comparison so plan rotations don't false-positive. Only
    returns a payload on failure; a clean placement stays silent.
    """
    dims = asset.get("dimensions_mm") or {}
    expected = [dims.get("width"), dims.get("depth"), dims.get("height")]
    if not bounds or not all(isinstance(v, (int, float)) and v > 0 for v in expected):
        return None
    try:
        placed = sorted(
            abs(float(bounds["max"][i]) - float(bounds["min"][i])) for i in range(3)
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    expected_sorted = sorted(float(v) * scale for v in expected)
    tolerance = 0.15
    mismatched = [
        axis for axis, (p, e) in enumerate(zip(placed, expected_sorted))
        if e > 0 and abs(p - e) / e > tolerance
    ]
    if not mismatched:
        return None
    return {
        "status": "mismatch",
        "expected_sorted_mm": [round(v, 1) for v in expected_sorted],
        "placed_sorted_mm": [round(v, 1) for v in placed],
        "tolerance": tolerance,
        "note": "Placed geometry deviates from catalogue dimensions beyond "
                "tolerance; inspect the source model (see manifest match note).",
    }


def _apply_import_correction(object_guid: str, rotate_x_degrees: float, target_z: float) -> bool:
    """Re-orients a placed instance whose source geometry is mis-oriented
    (manifest import_correction), then re-seats it on the placement plane."""
    script = f"""
using System;
using System.Collections.Generic;
using Rhino;
using Rhino.Geometry;

public class Script
{{
    public static List<Guid> Run(RhinoDoc doc)
    {{
        var id = new Guid("{object_guid}");
        var obj = doc.Objects.FindId(id);
        if (obj == null) return new List<Guid>();
        var bb = obj.Geometry.GetBoundingBox(true);
        var rot = Transform.Rotation(RhinoMath.ToRadians({rotate_x_degrees}), Vector3d.XAxis, bb.Center);
        doc.Objects.Transform(id, rot, true);
        var obj2 = doc.Objects.FindId(id);
        if (obj2 != null)
        {{
            var bb2 = obj2.Geometry.GetBoundingBox(true);
            doc.Objects.Transform(id, Transform.Translation(0, 0, {target_z} - bb2.Min.Z), true);
        }}
        doc.Views.Redraw();
        return new List<Guid>();
    }}
}}
"""
    payload = json.dumps({"type": "execute", "script": script}).encode("utf-8")
    try:
        response = json.loads(_send_and_receive(payload, timeout=30.0))
        return response.get("status") == "success"
    except Exception:
        return False


def _material_script(material: dict, guid_list: list[str],
                     apply_render_material: bool, attach_metadata: bool) -> str:
    """C# for the bridge: create/reuse a PBR doc material, assign it to the
    objects, and write almond:* user strings (Datasmith metadata in Unreal)."""
    r, g, b = (int(v) for v in material["base_color"])
    metallic = float(material["metallic"])
    roughness = float(material["roughness"])
    opacity = float(material["opacity"])
    mat_name = "ALMOND::" + material["material_id"]
    guid_array = ", ".join(f'"{value}"' for value in guid_list)
    user_strings = {
        "almond:material_id": material["material_id"],
        "almond:material_name": material["name"],
        "almond:material_category": material["category"],
        "almond:ue_material_slot": material["ue_material_slot"],
        "almond:base_color": f"{r},{g},{b}",
        "almond:metallic": f"{metallic:g}",
        "almond:roughness": f"{roughness:g}",
        "almond:opacity": f"{opacity:g}",
    }
    set_strings = "\n                ".join(
        f'obj.Attributes.SetUserString("{key}", "{value.replace(chr(34), "")}");'
        for key, value in user_strings.items()
    ) if attach_metadata else "// metadata disabled"
    assign_material = """
                var att = obj.Attributes;
                att.MaterialIndex = matIndex;
                att.MaterialSource = Rhino.DocObjects.ObjectMaterialSource.MaterialFromObject;
""" if apply_render_material else "\n                // render material disabled\n"
    return f"""
using System;
using System.Collections.Generic;
using Rhino;

public class Script
{{
    public static List<Guid> Run(RhinoDoc doc)
    {{
        int matIndex = -1;
        string matName = "{mat_name}";
        for (int i = 0; i < doc.Materials.Count; i++)
        {{
            var existing = doc.Materials[i];
            if (existing != null && !existing.IsDeleted && existing.Name == matName)
            {{ matIndex = i; break; }}
        }}
        if (matIndex < 0)
        {{
            var mat = new Rhino.DocObjects.Material();
            mat.Name = matName;
            mat.DiffuseColor = System.Drawing.Color.FromArgb({r}, {g}, {b});
            mat.Transparency = {1.0 - opacity:g};
            mat.ToPhysicallyBased();
            var pb = mat.PhysicallyBased;
            if (pb != null)
            {{
                pb.BaseColor = new Rhino.Display.Color4f({r}f / 255f, {g}f / 255f, {b}f / 255f, 1f);
                pb.Metallic = {metallic:g};
                pb.Roughness = {roughness:g};
                pb.Opacity = {opacity:g};
            }}
            matIndex = doc.Materials.Add(mat);
        }}

        var done = new List<Guid>();
        foreach (string s in new[] {{ {guid_array} }})
        {{
            var obj = doc.Objects.FindId(new Guid(s));
            if (obj == null) continue;{assign_material}                {set_strings}
            obj.CommitChanges();
            done.Add(obj.Id);
        }}
        doc.Views.Redraw();
        RhinoApp.WriteLine("Almond material '" + matName + "' applied to " + done.Count + " object(s).");
        return done;
    }}
}}
"""


@mcp.tool()
def list_materials(category: str = "", query: str = "") -> str:
    """
    Lists the curated PBR material library used by assign_material.

    Each entry carries metallic/roughness PBR channels, an Unreal material
    slot name (ue_material_slot) for deterministic remapping after import,
    and tags. Categories: metal, plastic, glass, wood, mineral, polymer.
    """
    materials = material_library.list(category=category, query=query)
    return json.dumps({
        "total": len(materials),
        "materials": materials,
        "library_dir": str(material_library.directory),
    })


@mcp.tool()
def assign_material(
    guids: list[str],
    material_id: str,
    apply_render_material: bool = True,
    attach_metadata: bool = True,
) -> str:
    """
    Assigns a curated PBR material to Rhino objects and stamps them with
    machine-readable material metadata for downstream pipelines (Unreal).

    Two effects, independently switchable:
    - apply_render_material: creates/reuses a physically-based Rhino
      material (ALMOND::<material_id>) and assigns it per object, so GLB
      export (publish_to_chestnut) and Datasmith carry real PBR channels.
    - attach_metadata: writes almond:* user-text keys (material_id, name,
      category, ue_material_slot, base_color, metallic, roughness, opacity)
      on each object - Datasmith imports these as asset metadata in Unreal,
      so materials can be remapped by ue_material_slot deterministically.

    Works on breps, meshes, and block instances (an instance's material
    applies to definition geometry set to 'by parent'; the metadata is
    always attached to the instance itself). Call list_materials first to
    discover material_ids.
    """
    material = material_library.get(material_id)
    if not material:
        known = ", ".join(sorted(material_library.materials)) or "none loaded"
        return json.dumps({
            "status": "error",
            "message": f"Unknown material_id: {material_id}. Known: {known}",
        })
    guid_list = []
    for value in guids:
        try:
            guid_list.append(str(uuid.UUID(str(value))))
        except ValueError:
            return json.dumps({
                "status": "error",
                "message": f"Invalid Rhino object GUID: {value}",
            })
    if not guid_list:
        return json.dumps({"status": "error", "message": "guids must not be empty."})

    script = _material_script(material, guid_list, apply_render_material, attach_metadata)
    payload = json.dumps({"type": "execute", "script": script}).encode("utf-8")
    try:
        response = json.loads(_send_and_receive(payload, timeout=60.0))
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Rhino bridge is unavailable. Start RhinoAlmondBridge first."})
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Material assignment failed: {exc}"})
    if response.get("status") != "success":
        return json.dumps(response)
    applied = response.get("guids") or []
    return json.dumps({
        "status": "success",
        "material_id": material_id,
        "rhino_material_name": "ALMOND::" + material_id,
        "ue_material_slot": material["ue_material_slot"],
        "applied_count": len(applied),
        "requested_count": len(guid_list),
        "applied_guids": applied,
        "metadata_attached": attach_metadata,
        "render_material_applied": apply_render_material,
    })


@mcp.tool()
def place_drawing_asset(
    asset_id: str,
    x: float = 0,
    y: float = 0,
    z: float = 0,
    rotation_degrees: float = 0,
    scale: float = 1,
) -> str:
    """
    Places an indexed representation asset as a reusable Rhino block.

    Drawing assets are placed on ALMOND-DRAW::ASSETS and remain distinct from
    IKEA product blocks. The tool accepts only files resolved from the
    controlled DrawingAssetfiles manifest.
    """
    asset = drawing_asset_indexer.get(asset_id)
    if not asset:
        return json.dumps({
            "status": "error",
            "message": f"Unknown drawing asset_id: {asset_id}",
        })
    if not asset.get("file_available"):
        return json.dumps({
            "status": "error",
            "message": f"Drawing asset file is missing for {asset_id}.",
        })
    numeric_values = [x, y, z, rotation_degrees, scale]
    if not all(
        isinstance(value, (int, float))
        and abs(value) != float("inf")
        and value == value
        for value in numeric_values
    ):
        return json.dumps({
            "status": "error",
            "message": "Placement values must be finite numbers.",
        })
    if scale <= 0 or scale > 100:
        return json.dumps({
            "status": "error",
            "message": "scale must be greater than 0 and no more than 100.",
        })

    payload = json.dumps({
        "type": "place_drawing_asset",
        "asset_id": asset_id,
        "file_path": asset["_resolved_file"],
        "name": f"{asset.get('product', '')} {asset.get('variant', '')}".strip(),
        "position": [x, y, z],
        "rotation_degrees": rotation_degrees,
        "scale": scale,
        "metadata": {
            "library_id": "drawing_assets",
            "product": asset.get("product"),
            "variant": asset.get("variant"),
            "category": asset.get("category"),
            "dimensions_mm": asset.get("dimensions_mm"),
            "drawing_roles": asset.get("drawing_roles", []),
            "lod": asset.get("lod"),
            "warehouse_url": asset.get("warehouse_url"),
            "match_status": asset.get("match_status"),
        },
    }).encode("utf-8")

    try:
        return _send_and_receive(payload, timeout=90.0)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Rhino drawing-asset import timed out."})
    except ConnectionRefusedError:
        return json.dumps({
            "status": "error",
            "message": "Rhino bridge is unavailable. Start RhinoAlmondBridge first.",
        })
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Drawing asset placement failed: {exc}",
        })


@mcp.tool()
def apply_drawing_style(recipe_id: str = "technical_axon_v1") -> str:
    """
    Creates or updates the Rhino layer hierarchy, plot weights, colours, and
    linetypes defined by an audited drawing recipe.
    """
    recipe = drawing_recipe_indexer.get(recipe_id)
    if not recipe:
        return json.dumps({
            "status": "error",
            "message": f"Unknown drawing recipe_id: {recipe_id}",
        })
    payload = json.dumps({
        "type": "apply_drawing_style",
        "recipe_id": recipe_id,
        "layers": recipe.get("layers", []),
    }).encode("utf-8")
    try:
        return _send_and_receive(payload, timeout=60.0)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Applying drawing style timed out."})
    except ConnectionRefusedError:
        return json.dumps({
            "status": "error",
            "message": "Rhino bridge is unavailable. Start RhinoAlmondBridge first.",
        })
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Drawing style application failed: {exc}",
        })


@mcp.tool()
def import_drawing_hatch_patterns(asset_id: str) -> str:
    """
    Imports the AutoCAD-style .pat hatch definitions of an indexed drawing
    asset into the active Rhino document's hatch pattern table.

    The tool accepts only .pat files resolved from the controlled
    DrawingAssetfiles manifest, mirroring the placement tools' security
    boundary.
    """
    asset = drawing_asset_indexer.get(asset_id)
    if not asset:
        return json.dumps({
            "status": "error",
            "message": f"Unknown drawing asset_id: {asset_id}",
        })
    if not asset.get("file_available"):
        return json.dumps({
            "status": "error",
            "message": f"Drawing asset file is missing for {asset_id}.",
        })
    resolved = asset["_resolved_file"]
    if not resolved.lower().endswith(".pat"):
        return json.dumps({
            "status": "error",
            "message": f"Asset {asset_id} is not a .pat hatch definition file.",
        })
    payload = json.dumps({
        "type": "import_hatch_patterns",
        "file_path": resolved,
    }).encode("utf-8")
    try:
        return _send_and_receive(payload, timeout=60.0)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Hatch pattern import timed out."})
    except ConnectionRefusedError:
        return json.dumps({
            "status": "error",
            "message": "Rhino bridge is unavailable. Start RhinoAlmondBridge first.",
        })
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "message": f"Hatch pattern import failed: {exc}",
        })


@mcp.tool()
def list_diagram_assets(category: str = "", limit: int = 20, offset: int = 0) -> str:
    """Lists available vector and CAD diagram assets (people, trees, symbols)."""
    page = retrieval_store.search_assets(
        library_id="diagram_assets",
        category=category,
        limit=limit,
        offset=offset,
    )
    return json.dumps({
        "library_id": "diagram_assets",
        "purpose": "2D vector diagramming and line-art",
        **page,
    })


@mcp.tool()
def search_diagram_assets(
    query: str = "",
    category: str = "",
    max_width_mm: float = 0,
    max_depth_mm: float = 0,
    max_height_mm: float = 0,
    limit: int = 10,
    offset: int = 0,
) -> str:
    """Searches the diagram asset library."""
    return json.dumps(retrieval_store.search_assets(
        query=query,
        library_id="diagram_assets",
        category=category,
        max_width_mm=max_width_mm,
        max_depth_mm=max_depth_mm,
        max_height_mm=max_height_mm,
        limit=limit,
        offset=offset,
    ))


@mcp.tool()
def get_diagram_asset(asset_id: str) -> str:
    """Returns one diagram asset's metadata."""
    asset = retrieval_store.get_asset(asset_id, library_id="diagram_assets")
    if not asset:
        return json.dumps({"status": "error", "message": f"Unknown diagram asset_id: {asset_id}"})
    return json.dumps({"status": "success", "asset": asset})


@mcp.tool()
def place_diagram_asset(
    asset_id: str,
    x: float = 0,
    y: float = 0,
    z: float = 0,
    rotation_degrees: float = 0,
    scale: float = 1,
) -> str:
    """Places an indexed diagram asset (SVG, DWG, DXF)."""
    asset = diagram_asset_indexer.get(asset_id)
    if not asset:
        return json.dumps({"status": "error", "message": f"Unknown diagram asset_id: {asset_id}"})
    if not asset.get("file_available"):
        return json.dumps({"status": "error", "message": f"Diagram asset file is missing for {asset_id}."})
        
    payload = json.dumps({
        "type": "place_drawing_asset",
        "asset_id": asset_id,
        "file_path": asset["_resolved_file"],
        "name": f"{asset.get('product', '')} {asset.get('variant', '')}".strip(),
        "position": [x, y, z],
        "rotation_degrees": rotation_degrees,
        "scale": scale,
        "metadata": {
            "library_id": "diagram_assets",
            "product": asset.get("product"),
            "variant": asset.get("variant"),
            "category": asset.get("category"),
            "dimensions_mm": asset.get("dimensions_mm"),
            "drawing_roles": asset.get("drawing_roles", []),
            "lod": asset.get("lod"),
        },
    }).encode("utf-8")

    try:
        return _send_and_receive(payload, timeout=90.0)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Rhino diagram import timed out."})
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Diagram asset placement failed: {exc}"})


@mcp.tool()
def execute_rhino_script(script: str) -> str:
    """
    Sends a C# RhinoCommon script to the Rhino 3D Bridge for compilation and execution.
    The script is compiled by Roslyn inside Rhino and executed natively as JIT-compiled C#.

    The script MUST define a class with a static Run method that returns created GUIDs:

        public class Script
        {
            public static List<Guid> Run(RhinoDoc doc)
            {
                var guids = new List<Guid>();
                // Use doc.Objects.AddSphere(), doc.Objects.AddBrep(), etc.
                // Append each GUID: guids.Add(guid);
                return guids;
            }
        }

    Available namespaces (auto-imported if not present):
        System, System.Collections.Generic, System.Linq,
        Rhino, Rhino.Geometry, Rhino.DocObjects

    Args:
        script: C# source code containing a class with public static List<Guid> Run(RhinoDoc doc).
    Returns:
        JSON with status (success/compile_error/runtime_error), created GUIDs, or error trace.
    """
    payload = json.dumps({"type": "execute", "script": script}).encode('utf-8')

    try:
        return _send_and_receive(payload)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Rhino bridge timed out (>60s)."})
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Connection refused. Is the RhinoAlmondBridge plugin loaded in Rhino?"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Bridge error: {e}"})


@mcp.tool()
def validate_structure(
    guids: list[str],
    structure_type: str = "beam",
    load_kn: float = 10.0,
    material: str = "Steel"
) -> str:
    """
    Validates AI-generated geometry against Karamba3D structural analysis.
    Call this AFTER execute_rhino_script to verify the generated structure is buildable.

    The bridge tries three analysis pathways in strict order of confidence and
    always tells you which one actually ran:
        analysis_method "api"        — direct Karamba 3.1 API solve, confidence "high"
        analysis_method "template"   — audited capsule GHX template,  confidence "medium"
        analysis_method "rule_based" — heuristic span/slenderness rules, confidence "low"
    The verdict string names the method (e.g. "[RULE-BASED ESTIMATE, LOW CONFIDENCE] ...").
    Treat rule_based/low results as estimates, NOT finite element analysis, and say so
    when reporting to the user.

    If the structure FAILS, modify the design (add supports, increase member size,
    change material) and call execute_rhino_script + validate_structure again.
    When worst_member_guids is present, edit only those offending members instead
    of regenerating everything. Iterate up to 3 times before reporting the best attempt.

    Args:
        guids: List of Rhino object GUID strings from execute_rhino_script output.
        structure_type: Analysis template to use. Options:
            "beam"       — simple beam bending/deflection
            "truss"      — axial force/buckling analysis
            "shell"      — shell stress/displacement
            "frame"      — moment/shear frame analysis
            "canopy"     — cantilevered canopy
            "gridshell"  — large deformation gridshell
            "membrane"   — form-finding membrane
            "highrise"   — high-rise structural systems
        load_kn: Applied load in kN (default 10.0).
        material: Material type: "Steel", "S355", "Concrete", "Wood", "Aluminium" (default "Steel").
    Returns:
        JSON passed through untouched from the bridge. Top-level fields: status
        ("pass"|"fail"|"error"), passed (bool), verdict (text), suggestions,
        confidence ("high"|"medium"|"low"), warnings, and worst_member_guids
        (up to 5 Rhino GUIDs of the most over-utilized members — edit those
        first). The results object carries the numbers: max_deflection_mm,
        deflection_limit_mm, utilization_ratio, max_stress_mpa, yield_stress_mpa,
        span_m, analysis_method ("api"|"template"|"rule_based"), reactions_kn
        (total vertical reaction, api path only), and per_element_utilization —
        a list of {source_guids, utilization} entries (utilization 1.0 = at
        capacity) keyed back to the Rhino objects that produced each element.
    """
    request = {
        "type": "validate",
        "guids": guids,
        "structure_type": structure_type,
        "load_kn": load_kn,
        "material": material,
    }
    payload = json.dumps(request).encode('utf-8')

    try:
        response = _send_and_receive(payload, timeout=60.0)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Structural validation timed out (>60s)."})
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Connection refused. Is the RhinoAlmondBridge plugin loaded in Rhino?"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Bridge error: {e}"})

    # Persist the run in the state DB so export_structural_report can render
    # an auditable history. Recording must never break validation itself.
    try:
        result = json.loads(response)
        if isinstance(result, dict) and result.get("status") in ("pass", "fail"):
            retrieval_store.record_validation_run(request, result, guids)
    except Exception:
        pass
    return response


def _render_validation_report(runs: list[dict]) -> str:
    """Markdown report of persisted validate_structure runs, newest first."""
    from datetime import datetime, timezone

    lines = [
        "# Structural validation report",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
        f"by almond-mcp. {len(runs)} run(s), newest first.",
        "",
        "## How a run works",
        "",
        "`validate_structure(guids, structure_type, load_kn, material)` sends the",
        "referenced Rhino geometry to the bridge, which extracts member axes and",
        "tries three analysis pathways in strict order of confidence:",
        "",
        "1. **api** — direct Karamba 3.1 solve (real FEA), confidence *high*;",
        "2. **template** — audited capsule GHX definition, confidence *medium*;",
        "3. **rule_based** — span/slenderness heuristics (UDL `w = load/span`,",
        "   `5wL^4/384EI`), confidence *low*. An estimate, not FEA.",
        "",
        "Pass criteria: max deflection within **L/250** of the detected span, and",
        "material utilization below yield (default S235 steel, fy = 235 MPa).",
        "The applied load defaults to **10 kN** unless load_kn is given.",
        "",
        "## Runs",
        "",
        "| # | when (UTC) | type | method | confidence | span m | defl mm | limit mm | util | reactions kN | members | result |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        lines.append(
            f"| {run['id']} | {run['ran_at'][:16].replace('T', ' ')} "
            f"| {run['structure_type']} | {run['analysis_method']} "
            f"| {run['confidence']} | {run['span_m']:.1f} "
            f"| {run['max_deflection_mm']:.2f} | {run['deflection_limit_mm']:.1f} "
            f"| {run['utilization_ratio']:.2f} | {run['reactions_kn']:.2f} "
            f"| {run['member_count']} | {'PASS' if run['passed'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("## Run details")
    for run in runs:
        lines += [
            "",
            f"### Run {run['id']} — {run['structure_type']}, "
            f"{run['analysis_method']} ({'PASS' if run['passed'] else 'FAIL'})",
            "",
            f"- input: {run['member_count']} object(s), load {run['load_kn']:.1f} kN, "
            f"material {run['material']}",
            f"- verdict: {run['verdict']}",
        ]
        if run["warnings"]:
            lines.append("- warnings:")
            lines += [f"  - {w}" for w in run["warnings"]]
    lines += [
        "",
        "## Reading the numbers",
        "",
        "- Only **api** runs are finite element analysis; reactions_kn is",
        "  populated on the api path only and should equal the applied load",
        "  plus self-weight (equilibrium).",
        "- Known gaps in karambaCommon 3.1.60519 (issue #6): api-mode",
        "  max_deflection and per-element utilization may read 0.0 due to",
        "  signature drift — trust reactions and stability diagnostics;",
        "  cross-check deflection against the rule_based estimate.",
        "- rule_based results are labeled LOW CONFIDENCE for a reason: treat",
        "  them as sanity checks, not engineering.",
        "",
    ]
    return "\n".join(lines)


@mcp.tool()
def export_structural_report(path: str = "", limit: int = 50) -> str:
    """
    Renders the persisted validate_structure history to a Markdown report.

    Every successful validate_structure call is recorded in the local state
    database (inputs, analysis method, confidence, numbers, warnings). This
    tool writes them to a .md file, newest first, with an explanation of the
    analysis pathways and pass criteria.

    Args:
        path: Output file path. Default:
            <user data dir>/reports/structural-validation-<timestamp>.md
        limit: Maximum number of runs to include (default 50, max 500).
    Returns:
        JSON with the report path and run count.
    """
    from datetime import datetime, timezone

    try:
        runs = retrieval_store.list_validation_runs(limit=limit)
        if not runs:
            return json.dumps({
                "status": "error",
                "message": "No validation runs recorded yet - call validate_structure first.",
            })
        target = Path(path) if path else (
            paths.user_data_dir() / "reports" /
            f"structural-validation-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_validation_report(runs), encoding="utf-8")
        return json.dumps({
            "status": "success",
            "path": str(target),
            "runs": len(runs),
            "latest_method": runs[0]["analysis_method"],
        })
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


def _restore_and_place_script(contract: dict, materials: dict[str, dict],
                              x_mm: float, y_mm: float, z_mm: float,
                              rotation_degrees: float, layer: str) -> str:
    """C# run after a GLB import: restore metadata, correct the colour drift,
    collapse duplicate materials, then place per the contract anchor."""
    lib_rows = []
    for material_id, material in materials.items():
        r, g, b = (int(v) for v in material["base_color"])
        lib_rows.append(
            '{{ "%s", new object[] {{ "%s", "%s", "%s", "%s", %d, %d, %d, %s, %s, %s }} }}'
            % (exchange.material_name(material_id), material_id, material["name"],
               material["category"], material["ue_material_slot"], r, g, b,
               repr(float(material["metallic"])), repr(float(material["roughness"])),
               repr(float(material["opacity"])))
        )
    anchor = contract["spatial"].get("anchor", "bottom_center")
    return f"""
using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.Geometry;
using Rhino.DocObjects;
using Rhino.Display;

public class Script
{{
    // material name -> {{ id, name, category, ue_slot, r, g, b, metallic, roughness, opacity }}
    static readonly Dictionary<string, object[]> Lib = new Dictionary<string, object[]>
    {{
        {",\n        ".join(lib_rows) if lib_rows else ""}
    }};

    public static List<Guid> Run(RhinoDoc doc)
    {{
        var imported = new List<RhinoObject>();
        foreach (string s in new[] {{ {", ".join('"%s"' % g for g in contract["_imported_guids"])} }})
        {{
            var o = doc.Objects.FindId(new Guid(s));
            if (o != null) imported.Add(o);
        }}
        if (imported.Count == 0) return new List<Guid>();

        // 1. collapse duplicate materials: glTF import creates one per mesh
        var canonical = new Dictionary<string, int>();
        int deduped = 0;
        for (int i = 0; i < doc.Materials.Count; i++)
        {{
            var m = doc.Materials[i];
            if (m == null || m.IsDeleted || !Lib.ContainsKey(m.Name)) continue;
            if (!canonical.ContainsKey(m.Name)) canonical[m.Name] = i;
        }}
        // 2. restore canonical PBR values (glTF round trip shifts base colour)
        foreach (var kv in canonical)
        {{
            var spec = Lib[kv.Key];
            var mat = doc.Materials[kv.Value];
            mat.Name = kv.Key;
            mat.DiffuseColor = System.Drawing.Color.FromArgb((int)spec[4], (int)spec[5], (int)spec[6]);
            mat.Transparency = 1.0 - Convert.ToDouble(spec[9]);
            mat.ToPhysicallyBased();
            var pb = mat.PhysicallyBased;
            if (pb != null)
            {{
                pb.BaseColor = new Color4f((int)spec[4] / 255f, (int)spec[5] / 255f, (int)spec[6] / 255f, 1f);
                pb.Metallic = Convert.ToDouble(spec[7]);
                pb.Roughness = Convert.ToDouble(spec[8]);
                pb.Opacity = Convert.ToDouble(spec[9]);
            }}
            mat.CommitChanges();
        }}

        int layerIndex = doc.Layers.FindByFullPath("{layer}", -1);
        if (layerIndex < 0)
        {{
            var l = new Layer {{ Name = "{layer}" }};
            layerIndex = doc.Layers.Add(l);
        }}

        // 3. re-attach the metadata glTF dropped, keyed off the surviving name
        int stamped = 0;
        foreach (var obj in imported)
        {{
            var mat = doc.Materials[obj.Attributes.MaterialIndex];
            string matName = mat != null ? mat.Name : "";
            if (matName.Length > 0 && Lib.ContainsKey(matName))
            {{
                if (canonical.ContainsKey(matName) && obj.Attributes.MaterialIndex != canonical[matName])
                {{
                    obj.Attributes.MaterialIndex = canonical[matName];
                    deduped++;
                }}
                obj.Attributes.MaterialSource = ObjectMaterialSource.MaterialFromObject;
                var spec = Lib[matName];
                obj.Attributes.SetUserString("almond:material_id", (string)spec[0]);
                obj.Attributes.SetUserString("almond:material_name", (string)spec[1]);
                obj.Attributes.SetUserString("almond:material_category", (string)spec[2]);
                obj.Attributes.SetUserString("almond:ue_material_slot", (string)spec[3]);
                obj.Attributes.SetUserString("almond:base_color", spec[4] + "," + spec[5] + "," + spec[6]);
                obj.Attributes.SetUserString("almond:metallic", Convert.ToString(spec[7]));
                obj.Attributes.SetUserString("almond:roughness", Convert.ToString(spec[8]));
                obj.Attributes.SetUserString("almond:opacity", Convert.ToString(spec[9]));
                obj.Attributes.ObjectColor = System.Drawing.Color.FromArgb((int)spec[4], (int)spec[5], (int)spec[6]);
                obj.Attributes.ColorSource = ObjectColorSource.ColorFromObject;
                stamped++;
            }}
            obj.Attributes.SetUserString("almond:asset_id", "{contract['asset_id']}");
            obj.Attributes.SetUserString("almond:source_app", "{contract.get('source_app', 'unknown')}");
            obj.Attributes.LayerIndex = layerIndex;
            obj.CommitChanges();
        }}

        // 4. place per the contract anchor, in this document's units
        double toDoc = RhinoMath.UnitScale(UnitSystem.Millimeters, doc.ModelUnitSystem);
        var bb = BoundingBox.Empty;
        foreach (var o in imported) bb.Union(o.Geometry.GetBoundingBox(true));
        var anchorPt = new Point3d((bb.Min.X + bb.Max.X) / 2, (bb.Min.Y + bb.Max.Y) / 2,
            "{anchor}" == "center" ? (bb.Min.Z + bb.Max.Z) / 2 : bb.Min.Z);
        var target = new Point3d({x_mm} * toDoc, {y_mm} * toDoc, {z_mm} * toDoc);
        var xform = Transform.Translation(target - anchorPt);
        if (Math.Abs({rotation_degrees}) > 1e-9)
            xform = xform * Transform.Rotation(RhinoMath.ToRadians({rotation_degrees}), Vector3d.ZAxis, anchorPt);
        foreach (var o in imported) doc.Objects.Transform(o.Id, xform, true);

        // 5. measure what actually landed, for the contract dimension check
        var after = BoundingBox.Empty;
        foreach (var o in imported)
        {{
            var refreshed = doc.Objects.FindId(o.Id);
            if (refreshed != null) after.Union(refreshed.Geometry.GetBoundingBox(true));
        }}
        double toMM = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Millimeters);
        RhinoApp.WriteLine(string.Format(
            "ALMOND_IMPORT stamped={{0}} deduped={{1}} w={{2:F1}} d={{3:F1}} h={{4:F1}}",
            stamped, deduped,
            (after.Max.X - after.Min.X) * toMM,
            (after.Max.Y - after.Min.Y) * toMM,
            (after.Max.Z - after.Min.Z) * toMM));
        System.IO.File.WriteAllText(
            System.IO.Path.Combine(System.IO.Path.GetTempPath(), "almond_import_report.json"),
            "{{\\"stamped\\":" + stamped + ",\\"deduped\\":" + deduped
            + ",\\"width\\":" + ((after.Max.X - after.Min.X) * toMM).ToString("F1")
            + ",\\"depth\\":" + ((after.Max.Y - after.Min.Y) * toMM).ToString("F1")
            + ",\\"height\\":" + ((after.Max.Z - after.Min.Z) * toMM).ToString("F1") + "}}");
        doc.Views.Redraw();
        return imported.Select(o => o.Id).ToList();
    }}
}}
"""


@mcp.tool()
def export_asset_contract(
    guids: list[str],
    asset_id: str,
    name: str = "",
    output_dir: str = "",
) -> str:
    """
    Exports Rhino objects as a portable Almond asset: a GLB plus an asset
    contract (.almond.json) carrying what the file cannot.

    The contract records real dimensions in mm, the anchor and support plane,
    clearances, and the Almond material_id of every object - so another
    application (Blender, Unreal, another Rhino) can restore full meaning
    even though glTF drops per-object metadata. Pair with
    import_asset_contract on the receiving side.

    Args:
        guids: Rhino object GUIDs to export (from execute_rhino_script).
        asset_id: Stable id, e.g. "canopy-pavilion-01" (letters, digits, . _ -).
        name: Human-readable name; defaults to asset_id.
        output_dir: Destination folder. Default: <user data dir>/exchange.
    Returns:
        JSON with the glb path, contract path, and recorded dimensions.
    """
    if not guids:
        return json.dumps({"status": "error", "message": "At least one GUID is required."})
    try:
        target_dir = Path(output_dir) if output_dir else paths.user_data_dir() / "exchange"
        glb_path, contract_path = exchange.contract_paths(target_dir, asset_id)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    payload = json.dumps({
        "type": "export_glb",
        "guids": guids,
        "output_path": str(glb_path),
    }).encode("utf-8")
    try:
        result = json.loads(_send_and_receive(payload, timeout=90.0))
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Rhino bridge is unavailable."})
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"GLB export failed: {exc}"})
    if result.get("status") != "success":
        return json.dumps(result)

    bounds = result.get("bounds") or {}
    if not bounds:
        return json.dumps({"status": "error", "message": "Export returned no bounds."})
    # export_glb reports bounds in document units
    unit_scale = {"Millimeters": 1.0, "Centimeters": 10.0, "Meters": 1000.0,
                  "Inches": 25.4, "Feet": 304.8}.get(result.get("units", "Millimeters"), 1.0)
    bounds_mm = {
        "min": [float(v) * unit_scale for v in bounds["min"]],
        "max": [float(v) * unit_scale for v in bounds["max"]],
    }
    material_groups = _material_groups(guids)
    try:
        contract = exchange.build_contract(
            asset_id=asset_id,
            name=name or asset_id,
            glb_filename=glb_path.name,
            bounds_mm=bounds_mm,
            materials=material_groups,
            source_app="rhino",
            object_count=len(result.get("object_guids", guids)),
        )
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)})
    contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return json.dumps({
        "status": "success",
        "asset_id": asset_id,
        "glb_path": str(glb_path),
        "contract_path": str(contract_path),
        "dimensions_mm": contract["dimensions_mm"],
        "materials": material_groups,
        "next_step": "Open this contract elsewhere with import_asset_contract, or "
                     "run get_blender_helper_script('import') to load it in Blender.",
    })


def _material_groups(guids: list[str]) -> list[dict]:
    """Ask Rhino which Almond material each object carries."""
    script = """
using System;
using System.Collections.Generic;
using System.IO;
using Rhino;

public class Script
{
    public static List<Guid> Run(RhinoDoc doc)
    {
        var rows = new List<string>();
        foreach (string s in new[] { %s })
        {
            var obj = doc.Objects.FindId(new Guid(s));
            if (obj == null) continue;
            string mid = obj.Attributes.GetUserString("almond:material_id");
            if (string.IsNullOrEmpty(mid))
            {
                var mat = doc.Materials[obj.Attributes.MaterialIndex];
                if (mat != null && mat.Name != null && mat.Name.StartsWith("ALMOND::"))
                    mid = mat.Name.Substring(8);
            }
            if (!string.IsNullOrEmpty(mid)) rows.Add(mid + "|" + s);
        }
        File.WriteAllLines(Path.Combine(Path.GetTempPath(), "almond_matgroups.txt"), rows);
        return new List<Guid>();
    }
}
""" % ", ".join('"%s"' % g for g in guids)
    try:
        _send_and_receive(json.dumps({"type": "execute", "script": script}).encode("utf-8"),
                          timeout=45.0)
        report = Path(tempfile.gettempdir()) / "almond_matgroups.txt"
        groups: dict[str, list[str]] = {}
        if report.is_file():
            for line in report.read_text(encoding="utf-8").splitlines():
                if "|" in line:
                    material_id, guid = line.split("|", 1)
                    groups.setdefault(material_id, []).append(guid)
        return [{"material_id": k, "objects": v} for k, v in sorted(groups.items())]
    except Exception:
        return []


@mcp.tool()
def import_asset_contract(
    contract_path: str,
    x_mm: float = 0,
    y_mm: float = 0,
    z_mm: float = 0,
    rotation_degrees: float = 0,
    layer: str = "ALMOND-EXCHANGE",
) -> str:
    """
    Imports an Almond asset contract (from Blender, Unreal, or another Rhino)
    into the open Rhino document, restoring everything the file format drops.

    Runs the full receive sequence: import the GLB, collapse the duplicate
    materials glTF creates, restore canonical PBR values from the Almond
    material library (glTF round trips shift base colours), re-attach the
    almond:* metadata keyed off the surviving material name, place the asset
    at the requested point using the contract's anchor, and verify the
    measured size against the contract's recorded dimensions.

    Args:
        contract_path: Path to a .almond.json contract file.
        x_mm, y_mm, z_mm: Placement point in millimetres (contract anchor).
        rotation_degrees: Rotation about world Z.
        layer: Destination layer, created if absent.
    Returns:
        JSON with counts restored/deduplicated and a dimension_check comparing
        what landed against the contract.
    """
    try:
        contract = exchange.load_contract(contract_path)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    import_script = """
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Rhino;

public class Script
{
    public static List<Guid> Run(RhinoDoc doc)
    {
        var before = new HashSet<Guid>(doc.Objects.Select(o => o.Id));
        RhinoApp.RunScript("_-Import \\"%s\\" _Enter", false);
        var added = doc.Objects.Where(o => !before.Contains(o.Id)).Select(o => o.Id).ToList();
        File.WriteAllLines(Path.Combine(Path.GetTempPath(), "almond_imported.txt"),
            added.Select(g => g.ToString()));
        return added;
    }
}
""" % contract["_resolved_file"].replace("\\", "\\\\")
    try:
        result = json.loads(_send_and_receive(
            json.dumps({"type": "execute", "script": import_script}).encode("utf-8"),
            timeout=120.0))
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Rhino bridge is unavailable."})
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Import failed: {exc}"})
    if result.get("status") != "success":
        return json.dumps(result)
    imported = result.get("guids") or []
    if not imported:
        return json.dumps({"status": "error",
                           "message": "Rhino imported no objects from the GLB."})

    contract["_imported_guids"] = imported
    needed = {row["material_id"] for row in contract.get("materials", [])}
    library = {mid: material_library.get(mid) for mid in needed}
    known = {mid: spec for mid, spec in library.items() if spec}
    unknown = sorted(mid for mid, spec in library.items() if not spec)

    script = _restore_and_place_script(contract, known, x_mm, y_mm, z_mm,
                                       rotation_degrees, layer)
    try:
        restore = json.loads(_send_and_receive(
            json.dumps({"type": "execute", "script": script}).encode("utf-8"),
            timeout=120.0))
    except Exception as exc:
        return json.dumps({"status": "error",
                           "message": f"Imported, but restore/place failed: {exc}",
                           "imported_guids": imported})
    if restore.get("status") != "success":
        return json.dumps({"status": "error", "message": restore.get("message", "restore failed"),
                           "imported_guids": imported})

    report_path = Path(tempfile.gettempdir()) / "almond_import_report.json"
    report = {}
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except ValueError:
            report = {}
    check = exchange.dimension_report(contract, report) if report else {"status": "unknown"}
    return json.dumps({
        "status": "success",
        "asset_id": contract["asset_id"],
        "source_app": contract.get("source_app", "unknown"),
        "imported_count": len(imported),
        "metadata_restored": report.get("stamped", 0),
        "materials_deduplicated": report.get("deduped", 0),
        "unknown_material_ids": unknown,
        "dimension_check": check,
        "layer": layer,
        "imported_guids": imported,
    })


@mcp.tool()
def get_blender_helper_script(action: str, asset_id: str = "", name: str = "",
                              output_dir: str = "", material_id: str = "",
                              object_names: list[str] | None = None) -> str:
    """
    Returns Python to run inside Blender (via blender-mcp's execute_code) so
    Blender participates in the Almond workflow without a dedicated bridge.

    Actions:
        "export"    - export the current Blender selection as an Almond asset
                      contract + GLB (measured from evaluated mesh data,
                      because Blender inflates curve bounding boxes).
        "materials" - create Almond library materials in Blender (sRGB values
                      converted to linear) and assign them to named objects,
                      tagging both with almond:* properties.

    Args:
        action: "export" or "materials".
        asset_id, name, output_dir: for "export" (output_dir defaults to the
            Almond exchange folder).
        material_id, object_names: for "materials".
    Returns:
        JSON with a "script" field to pass to Blender's execute_code.
    """
    action = action.strip().lower()
    if action == "export":
        if not asset_id:
            return json.dumps({"status": "error", "message": "asset_id is required for export."})
        target = output_dir or str(paths.user_data_dir() / "exchange")
        return json.dumps({
            "status": "success",
            "action": "export",
            "script": exchange.blender_export_script(asset_id, name or asset_id, target),
            "note": "Run in Blender, then call import_asset_contract with the printed path.",
        })
    if action == "materials":
        material = material_library.get(material_id)
        if not material:
            return json.dumps({"status": "error",
                               "message": f"Unknown material_id: {material_id}. Call list_materials."})
        if not object_names:
            return json.dumps({"status": "error", "message": "object_names is required."})
        script = exchange.blender_material_script(
            [material], [{"material_id": material_id, "objects": object_names}])
        return json.dumps({"status": "success", "action": "materials", "script": script})
    return json.dumps({"status": "error", "message": 'action must be "export" or "materials".'})


@mcp.tool()
def list_capsules(capability: str = "", audited_only: bool = False) -> str:
    """
    Lists Grasshopper capsules: GH definitions with a typed, audited input/output
    contract that can be executed via run_gh_definition.

    Call this FIRST to discover what capsules exist before calling run_gh_definition.
    Each entry is a compact card with capsule_id, capability, structure_type,
    audited flag, and the reserved ALMOND_IN_* / ALMOND_OUT_* port names. Only
    capsules with audited=true can actually run; audited=false capsules are
    retrieval context only (read them via get_logic_by_id instead).

    Args:
        capability: Optional filter: "analyze", "generate", "form_find", or "aggregate".
        audited_only: When true, list only capsules that run_gh_definition will accept.
    Returns:
        JSON with total and a list of compact capsule cards.
    """
    page = retrieval_store.search_capsules(
        capability=capability,
        audited_only=audited_only,
        limit=50,
    )
    return json.dumps({
        "capsule_library_dir": CAPSULE_LIBRARY_DIR,
        **page,
    })


@mcp.tool()
def run_gh_definition(
    capsule_id: str,
    inputs: dict,
    seed: int | None = None,
    timeout_s: float = 60.0,
) -> str:
    """
    Runs an audited Grasshopper capsule (GH definition + typed contract) through
    the Rhino bridge and returns its declared outputs.

    Workflow: call list_capsules() first to pick a capsule_id and see its input/
    output port names. Create any geometry with execute_rhino_script, then pass
    the returned GUIDs here. Inputs are validated client-side against the capsule
    manifest before anything is sent to Rhino, so errors from this tool name the
    exact port at fault.

    Input value forms (keyed by the exact ALMOND_IN_* port name):
      - Geometry ports (point/curve/mesh/brep and their [] list forms):
        {"guids": ["<rhino-object-guid>", ...]} referencing objects already in
        the Rhino document.
      - number / integer / string / bool ports: the raw JSON value.
      - number[] / integer[] / string[] ports: a flat JSON list.
    Units are declared per port in the manifest — supply values in those units;
    nothing is guessed or auto-converted client-side. Optional inputs may be
    omitted; the capsule's declared defaults then apply inside the definition.

    Only audited capsules run. audited=false means the GHX has no verified
    ALMOND_IN_*/ALMOND_OUT_* harness params yet; this tool refuses it
    (see capsules/AUTHORING.md for how to harness one).

    The response's "outputs" object is keyed by ALMOND_OUT_* names; interpret
    each value using the manifest's semantics field (e.g. max_nodal_displacement,
    per_element_utilization) and declared units. The response also carries
    analysis_method (api|template|rule_based), confidence (high|medium|low),
    warnings, and baked_guids — report method and confidence honestly;
    rule_based/low means an estimate, not FEA.

    Args:
        capsule_id: Stable capsule identifier from list_capsules (e.g. "karamba_beam_v1").
        inputs: Object mapping ALMOND_IN_* port names to values (forms above).
        seed: Optional integer seed for stochastic definitions; omit for deterministic ones.
        timeout_s: Solver budget in seconds (default 60, max 600).
    Returns:
        JSON with status, capsule_id, outputs, baked_guids, analysis_method,
        confidence, warnings, and error — or a validation error naming the
        offending input and the valid port names.
    """
    manifest = retrieval_store.get_capsule(capsule_id)
    if not manifest:
        listing = retrieval_store.search_capsules(limit=50)
        return json.dumps({
            "status": "error",
            "message": f"Unknown capsule_id: {capsule_id}. Use list_capsules() to discover capsules.",
            "available_capsules": [
                capsule["capsule_id"] for capsule in listing["capsules"]
            ],
        })

    if not manifest.get("audited"):
        return json.dumps({
            "status": "error",
            "message": (
                f"Capsule '{capsule_id}' is not audited: its definition has no verified "
                "ALMOND_IN_*/ALMOND_OUT_* harness params, so run_gh_definition refuses to "
                "execute it. It remains available as retrieval context (get_logic_by_id). "
                "See capsules/AUTHORING.md for how to harness and audit the definition."
            ),
        })

    if not isinstance(inputs, dict):
        return json.dumps({
            "status": "error",
            "message": "inputs must be an object keyed by ALMOND_IN_* port names.",
        })

    ports = {
        port["name"]: port
        for port in manifest.get("inputs", [])
        if isinstance(port, dict) and isinstance(port.get("name"), str)
    }
    valid_names = sorted(ports)

    unknown = sorted(set(inputs) - set(ports))
    if unknown:
        return json.dumps({
            "status": "error",
            "message": f"Unknown input name(s) for '{capsule_id}': {', '.join(unknown)}.",
            "valid_inputs": valid_names,
        })

    missing = sorted(
        name for name, port in ports.items()
        if port.get("required", True) and name not in inputs
    )
    if missing:
        return json.dumps({
            "status": "error",
            "message": f"Missing required input(s) for '{capsule_id}': {', '.join(missing)}.",
            "valid_inputs": valid_names,
        })

    problems = []
    for name in sorted(inputs):
        problem = _capsule_input_error(ports[name], inputs[name])
        if problem:
            problems.append(problem)
    if problems:
        return json.dumps({
            "status": "error",
            "message": "Input validation failed: " + " ".join(problems),
            "valid_inputs": valid_names,
        })

    if not (isinstance(timeout_s, (int, float)) and not isinstance(timeout_s, bool)
            and timeout_s == timeout_s and 0 < timeout_s <= 600):
        return json.dumps({
            "status": "error",
            "message": "timeout_s must be a number between 0 (exclusive) and 600 seconds.",
        })

    manifest_path = manifest.get("_manifest_path") or os.path.join(
        CAPSULE_LIBRARY_DIR, f"{capsule_id}.capsule.json"
    )

    payload = json.dumps({
        "type": "run_definition",
        "capsule_id": capsule_id,
        "manifest_path": manifest_path,
        "inputs": inputs,
        "seed": seed,
        "timeout_s": timeout_s,
    }).encode("utf-8")

    try:
        # Socket budget exceeds the solver budget so the bridge can report its
        # own timeout as structured JSON instead of a dead connection.
        return _send_and_receive(payload, timeout=float(timeout_s) + 15.0)
    except socket.timeout:
        return json.dumps({
            "status": "error",
            "message": f"Capsule '{capsule_id}' timed out (>{timeout_s}s solver budget).",
        })
    except ConnectionRefusedError:
        return json.dumps({
            "status": "error",
            "message": "Connection refused. Is the RhinoAlmondBridge plugin loaded in Rhino?",
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Bridge error: {e}"})


@mcp.tool()
def publish_objects_to_chestnut(
    guids: list[str],
    asset_name: str,
    asset_id: str = "",
    body_type: str = "static",
    collider: str = "box",
    preserve_scale: bool = True,
    mass: float = 0.0,
) -> str:
    """
    Exports specific Rhino objects as one GLB and publishes them to Chestnut.

    Use this after execute_rhino_script (and optionally validate_structure), passing
    the returned object GUIDs. Reusing asset_id updates the existing Chestnut asset
    without changing placements that already reference it.

    Args:
        guids: Rhino object GUIDs to export. Unrelated document objects are excluded.
        asset_name: Human-readable name shown in Chestnut.
        asset_id: Stable optional ID for linked updates. Generated deterministically
                  from the Rhino document and GUIDs when omitted.
        body_type: "static" for architecture, "dynamic" for loose props, or
                   "kinematic" for script-driven objects.
        collider: Collider intent: "box", "convex", "compound", or "trimesh".
                  Chestnut currently falls back to a box where needed.
        preserve_scale: Keep Rhino's real-world dimensions instead of normalizing
                        the model to a one-metre display prop.
        mass: Physics mass in kilograms. Static bodies always use zero.
    Returns:
        JSON containing the stable Chestnut asset ID, URL, metadata, and whether
        the operation created or updated the asset.
    """
    if not guids:
        return json.dumps({"status": "error", "message": "At least one Rhino object GUID is required."})
    if not asset_name.strip():
        return json.dumps({"status": "error", "message": "asset_name is required."})

    body_type = body_type.lower()
    collider = collider.lower()
    if body_type not in {"static", "dynamic", "kinematic"}:
        return json.dumps({"status": "error", "message": "body_type must be static, dynamic, or kinematic."})
    if collider not in {"box", "convex", "compound", "trimesh"}:
        return json.dumps({"status": "error", "message": "collider must be box, convex, compound, or trimesh."})
    if mass < 0:
        return json.dumps({"status": "error", "message": "mass cannot be negative."})

    output_path = os.path.join(tempfile.gettempdir(), f"almond_{uuid.uuid4().hex}.glb")
    payload = json.dumps({
        "type": "export_glb",
        "guids": guids,
        "output_path": output_path,
    }).encode("utf-8")

    try:
        export_result = json.loads(_send_and_receive(payload, timeout=90.0))
        if export_result.get("status") != "success":
            return json.dumps(export_result)

        source_key = "|".join([
            export_result.get("document_path", ""),
            *sorted(export_result.get("object_guids", guids)),
        ])
        source_hash = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:12]
        stable_id = asset_id.strip() or f"{_slug(asset_name)}-{source_hash}"
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", stable_id):
            return json.dumps({
                "status": "error",
                "message": "asset_id must contain only letters, numbers, dot, underscore, or hyphen (max 80).",
            })

        metadata = {
            "assetId": stable_id,
            "name": asset_name.strip(),
            "preserveScale": preserve_scale,
            "bodyType": body_type,
            "collider": collider,
            "mass": 0.0 if body_type == "static" else (mass or 1.0),
            "units": export_result.get("units", "Unknown"),
            "axisConvention": "glTF Y-up",
            "source": {
                "application": "Rhino",
                "documentPath": export_result.get("document_path", ""),
                "documentSerial": export_result.get("document_serial"),
                "objectGuids": export_result.get("object_guids", guids),
                "sourceId": f"rhino:{source_hash}",
            },
            "bounds": export_result.get("bounds"),
        }
        chestnut_result = _post_multipart(
            f"{CHESTNUT_URL}/api/props/upsert",
            {"metadata": json.dumps(metadata)},
            output_path,
        )
        if not chestnut_result.get("success"):
            return json.dumps({"status": "error", "message": chestnut_result.get("error", "Chestnut rejected asset.")})
        return json.dumps({
            "status": "success",
            "chestnut_url": CHESTNUT_URL,
            **chestnut_result,
        })
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Rhino bridge is unavailable. Start RhinoAlmondBridge first."})
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Rhino GLB export timed out."})
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "chestnut_url": CHESTNUT_URL,
            "message": str(exc),
        })
    finally:
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except OSError:
            pass


@mcp.tool()
def publish_to_chestnut(
    guids: list[str],
    asset_name: str,
    behavior: str = "auto",
    asset_id: str = "",
) -> str:
    """
    Publishes Rhino objects to Chestnut using safe semantic defaults.

    This is the preferred publishing tool for normal use. It hides collider,
    scale, mass, and rigid-body details. Call it when the user says things such
    as "publish that to Chestnut".

    Args:
        guids: Rhino object GUIDs returned by execute_rhino_script.
        asset_name: Human-readable asset name.
        behavior: Optional semantic preset:
            "auto"         — infer architecture versus movable object from name
            "architecture" — fixed building, terrain, structure, or enclosure
            "object"       — movable physical prop affected by gravity
            "animated"     — script-driven door, lift, platform, or mechanism
        asset_id: Optional stable link ID. Omit for a deterministic Rhino link.
    """
    behavior = behavior.lower().strip()
    if behavior not in {"auto", "architecture", "object", "animated"}:
        return json.dumps({
            "status": "error",
            "message": "behavior must be auto, architecture, object, or animated.",
        })

    if behavior == "auto":
        architecture_words = {
            "architecture", "building", "pavilion", "house", "wall", "floor",
            "roof", "terrain", "landscape", "bridge", "structure", "room",
            "facade", "tower", "canopy", "shell", "frame",
        }
        words = set(re.findall(r"[a-z]+", asset_name.lower()))
        behavior = "architecture" if words & architecture_words else "object"

    presets = {
        "architecture": {"body_type": "static", "collider": "box", "mass": 0.0},
        "object": {"body_type": "dynamic", "collider": "box", "mass": 1.0},
        "animated": {"body_type": "kinematic", "collider": "box", "mass": 0.0},
    }
    preset = presets[behavior]
    return publish_objects_to_chestnut(
        guids=guids,
        asset_name=asset_name,
        asset_id=asset_id,
        body_type=preset["body_type"],
        collider=preset["collider"],
        preserve_scale=True,
        mass=preset["mass"],
    )


if __name__ == "__main__":
    mcp.run()

