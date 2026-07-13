# Almond MCP for Rhino

<p align="center"><img src="assets/almond-icon.svg" width="120" alt="Almond"></p>

Almond exposes Rhino 8 and a semantic design layer as MCP tools: curated
furniture/drawing/diagram libraries with spatial contracts, audited Karamba
capsules, structured retrieval (SQLite FTS5 + R-tree scene ledger), script
execution over a TCP bridge, and publishing into Chestnut.

## What Almond is

Most Rhino MCP servers give the model a single power: *run a script*. That
demos well, but generation is blind — the model has no memory of what is
already in the scene, no real-world dimensions, no constraints, and no way
to check its own work. The result is geometry that looks plausible and
measures wrong.

Almond is a **semantic layer around Rhino**, built so a language model can
design with spatial awareness and produce high-detail, high-fidelity output:

- **A persistent scene ledger** (SQLite) — scenes, rooms, placed instances,
  delta-based revisions. The model *queries* the current state instead of
  guessing it.
- **Curated asset libraries with spatial contracts** — every furniture and
  drawing asset carries its real catalogue dimensions plus an authored
  contract: anchor point, floor footprint, functional clearances (e.g.
  900 mm in front of a bookcase), collision shape, placement priority.
  Placement respects ergonomics, not just bounding boxes.
- **Structured retrieval** — FTS5 natural-language search and R-tree spatial
  indexes, isolated per library, returning compact asset cards sized for a
  model's context window.
- **Layout validation** — an R-tree broad-phase overlap and room-containment
  check the model can run *before* committing a layout.
- **Audited Karamba capsules** — typed input/output contracts
  (`ALMOND_IN_*`/`ALMOND_OUT_*`) over structural Grasshopper definitions, so
  generated structures get real displacement/utilization feedback.
- **Drawing recipes** — layer hierarchies, plot weights, and linetype
  standards applied as one command, so output reads as an architectural
  drawing rather than raw curves.
- **Script execution and GLB publishing** — the raw `execute_rhino_script`
  power is still there, plus one-call publishing of selected geometry into
  Chestnut with physics metadata.

The design goal: the model composes from **verified parts and validated
layouts** instead of hallucinating geometry.

Two pieces work together:

- **`almond-mcp`** (this Python package, on PyPI) — the MCP server Claude
  talks to. Holds the semantic layer; needs no Rhino SDK.
- **`almondbridge`** (a Rhino 8 plugin, on the Rhino Package Manager) —
  listens on `127.0.0.1:5000` (local only) inside Rhino and executes what
  the server sends. Starts automatically with Rhino.

## Setup, step by step

Fresh machine to working in about five minutes. You need Rhino 8 on Windows
and a Claude that supports MCP (Claude Desktop or Claude Code).

1. **Install the bridge.** In Rhino 8 run `_PackageManager`, search
   `almondbridge`, install, restart Rhino. You should see
   `RhinoAlmondBridge: TCP listener started on port 5000` in the command
   history — no command needed. (`AlmondMCPStatus` checks it any time.)
2. **Install [uv](https://docs.astral.sh/uv/)** (Python not required —
   uv manages everything):

   ```powershell
   winget install astral-sh.uv
   ```

3. **Register the server with Claude.**
   - *Claude Desktop:* edit `%APPDATA%\Claude\claude_desktop_config.json`:

     ```json
     {
       "mcpServers": {
         "Almond": {
           "command": "uvx",
           "args": ["almond-mcp"]
         }
       }
     }
     ```

   - *Claude Code:* `claude mcp add Almond -- uvx almond-mcp`
4. **Restart Claude.** The Almond tools (`execute_rhino_script`,
   `search_ikea_furniture`, `create_design_scene`, …) appear in the tool
   list. First run creates `%LOCALAPPDATA%\Almond` with the library
   manifests and the scene database.
5. **Check the plumbing** (Rhino open):

   ```powershell
   uvx almond-mcp doctor
   ```

6. **Populate the asset libraries** (optional — everything except model
   *placement* works without it). The manifests ship with the package, but
   the model files are 3D Warehouse content that cannot legally be
   redistributed (see `THIRD-PARTY-NOTICES.md`), so each user downloads
   them from the original source pages:

   ```powershell
   uvx almond-mcp fetch-assets --open   # opens each missing model's source page
   uvx almond-mcp fetch-assets          # re-run to verify sha256 checksums
   ```

   Save each download into the library's `models/` folder under the exact
   file name shown; the command verifies every checksum.
7. **Optional extras:** Karamba3D 3.1 enables `validate_structure` (found at
   runtime — never bundled); point `RHINO_MCP_LIBRARY_DIR` at your own
   Grasshopper definition library to expose it via `list_library`.

## CLI

```text
almond-mcp               start the MCP server (also: almond-mcp serve)
almond-mcp fetch-assets  report missing/invalid model files and their sources
almond-mcp doctor        check directories, manifests, state DB, bridge port
almond-mcp paths         print every resolved directory
```

Directory resolution order: `RHINO_MCP_*` environment variable → repository
checkout (development) → `%LOCALAPPDATA%\Almond` (installed). Overridable
locations:

| Environment variable | Default folder |
| --- | --- |
| `RHINO_MCP_LIBRARY_DIR` | `Grasshopperfiles` (your GH/Karamba definitions) |
| `RHINO_MCP_FURNITURE_DIR` | `IkeaFurniturefiles` |
| `RHINO_MCP_DRAWING_ASSET_DIR` | `DrawingAssetfiles` |
| `RHINO_MCP_DIAGRAM_ASSET_DIR` | `DiagramAssetfiles` |
| `RHINO_MCP_DRAWING_RECIPE_DIR` | `DrawingRecipes` |
| `RHINO_MCP_CAPSULE_DIR` | `capsules` |
| `RHINO_MCP_STATE_DB` | `%LOCALAPPDATA%\Almond\almond_state.sqlite3` |

## Rhino to Chestnut

After `execute_rhino_script` returns the GUIDs it created, publish only those
objects with:

```text
publish_to_chestnut(
  guids=[...],
  asset_name="Timber Pavilion"
)
```

This preferred tool applies semantic defaults automatically. Its optional
`behavior` presets are `architecture`, `object`, and `animated`. Use the
lower-level tool only when explicit physics control is needed:

```text
publish_objects_to_chestnut(
  guids=[...],
  asset_name="Timber Pavilion",
  asset_id="timber-pavilion-01",
  body_type="static",
  collider="box",
  preserve_scale=true,
  mass=0
)
```

The tool:

1. asks Rhino 8 to export the supplied GUIDs as GLB;
2. explicitly maps Rhino Z-up to glTF Y-up;
3. uploads the GLB and its source/physics metadata to Chestnut;
4. creates or updates the stable `asset_id`; and
5. removes the temporary GLB after publishing.

Reusing an `asset_id` updates the geometry while Chestnut placements continue
to reference the same asset URL.

Chestnut defaults to the deployed service at
`https://chestnut-mnvo.onrender.com`. Override it before starting the MCP
server when local development is required:

```powershell
$env:CHESTNUT_URL = "http://127.0.0.1:3000"
almond-mcp
```

## IKEA furniture library

Almond exposes a controlled IKEA Singapore furniture library:

```text
list_ikea_furniture(category="chair")
search_ikea_furniture(
  query="compact living room sofa",
  max_width_mm=2000,
  exact_dimensions_only=true
)
place_ikea_furniture(
  asset_id="ikea-sg-klippan-s49010615",
  x=0,
  y=0,
  z=0,
  rotation_degrees=90
)
```

SketchUp files are resolved from the furniture library's `manifest.json`.
Claude cannot provide arbitrary import paths. Rhino imports each asset once
as a block definition and creates lightweight instances for subsequent
placements. Almond is not affiliated with Inter IKEA Systems B.V.; product
names identify the real products whose catalogue dimensions the manifest
records.

## Architectural drawing asset library

Representation-only entourage and graphic proxies live in the independent
drawing asset library. They never appear in IKEA searches:

```text
search_drawing_assets(query="landscape tree")
get_drawing_asset(asset_id="context-tree-chinese-elm-a708cff4")
place_drawing_asset(
  asset_id="context-tree-chinese-elm-a708cff4",
  x=12000,
  y=8000
)
```

Audited drawing recipes are stored separately in `DrawingRecipes`. The first
recipe creates a technical-axon layer hierarchy with plot weights and custom
hidden/overhead linetypes:

```text
list_drawing_recipes()
get_drawing_recipe(recipe_id="technical_axon_v1")
apply_drawing_style(recipe_id="technical_axon_v1")
create_generation_plan(
  goal="Produce a technical axonometric",
  scope="drawing"
)
```

## Karamba capsules

Audited capsule manifests (`capsules/*.capsule.json`) declare typed
input/output contracts for structural Grasshopper definitions using reserved
`ALMOND_IN_*` / `ALMOND_OUT_*` nicknames — beams, trusses, frames, shells,
gridshells, membranes, canopies, and high-rises. See `capsules/AUTHORING.md`
to bind your own definitions. Karamba3D itself is user-installed; the bridge
finds it at runtime via reflection.

## Structured retrieval and scene state

Almond builds a local SQLite database from the asset manifests at startup.
The database provides:

- library-isolated dimensional and category filters;
- FTS5 natural-language retrieval;
- R-tree asset and scene-instance spatial indexes;
- stable scene, room, asset, and instance handles;
- delta-based scene revisions; and
- dependency-ordered generation plans.

Search and list tools return compact asset cards. Full provenance,
footprints, clearances, and source metadata are returned only by
`get_ikea_furniture`. Geometry and Grasshopper files remain local.

Useful tools:

```text
get_retrieval_status()
create_design_scene(name="Apartment test")
upsert_design_room(
  scene_id="scene_...",
  name="Living room",
  bounds_mm=[0, 0, 0, 6000, 4500, 2800]
)
register_scene_instance(
  scene_id="scene_...",
  room_id="room_...",
  asset_id="ikea-sg-klippan-s49010615",
  x_mm=3000,
  y_mm=3900
)
validate_scene_layout(scene_id="scene_...")
create_generation_plan(
  goal="Generate and furnish a compact house",
  scope="house",
  scene_id="scene_..."
)
```

The current spatial validator is an R-tree world-AABB broad phase plus room
containment. Oriented-footprint, functional-clearance, and automatic
resolution passes can build on the same persistent scene ledger.

## Development

```powershell
git clone <repo> almond-mcp
cd almond-mcp
uv run pytest          # 23 tests, no Rhino required
uv run almond-mcp doctor
```

On OneDrive-synced folders set `UV_LINK_MODE=copy` (OneDrive rejects uv's
hardlinks). Licensing: `LICENSE` (MIT), `THIRD-PARTY-NOTICES.md`, and
`docs/licensing-audit.md` for what may and may not be distributed.
