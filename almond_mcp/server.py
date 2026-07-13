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
from almond_mcp import paths

# ── Constants ────────────────────────────────────────────────────────────────

DELIMITER = b'\n<<EOF>>\n'
LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_LIBRARY_DIR")
FURNITURE_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_FURNITURE_DIR")
DRAWING_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_DRAWING_ASSET_DIR")
DIAGRAM_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_DIAGRAM_ASSET_DIR")
DRAWING_RECIPE_DIR = paths.resolve_dir("RHINO_MCP_DRAWING_RECIPE_DIR")
CAPSULE_LIBRARY_DIR = paths.resolve_dir("RHINO_MCP_CAPSULE_DIR")
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
    bounds_mm is [min_x, min_y, min_z, max_x, max_y, max_z].
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
    z_mm: float = 0,
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
        return _send_and_receive(payload, timeout=90.0)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Rhino furniture import timed out."})
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Rhino bridge is unavailable. Start RhinoAlmondBridge first."})
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"Furniture placement failed: {exc}"})


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
    payload = json.dumps({
        "type": "validate",
        "guids": guids,
        "structure_type": structure_type,
        "load_kn": load_kn,
        "material": material,
    }).encode('utf-8')

    try:
        return _send_and_receive(payload, timeout=60.0)
    except socket.timeout:
        return json.dumps({"status": "error", "message": "Structural validation timed out (>60s)."})
    except ConnectionRefusedError:
        return json.dumps({"status": "error", "message": "Connection refused. Is the RhinoAlmondBridge plugin loaded in Rhino?"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Bridge error: {e}"})


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

