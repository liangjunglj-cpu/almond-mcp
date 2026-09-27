# Almond 0.6.0rc1 — semantic asset library

This release candidate develops the existing 47 Meshy assets into a portable,
queryable design library. Geometry is preserved; this is a metadata, reasoning
and distribution update, not a new generation batch. It is built locally and
is not yet a public PyPI or Yak release.

## The product distinction

Almond can support the full **select → inspect → fit → place → validate**
workflow. A client can explain why it chose an asset, see its source and
limitations, budget its geometry, and check its required footprint before
touching Rhino. The library and read-only tools work without Rhino or a Meshy
account; modelling/placement still requires the existing Almond Rhino bridge.

The distinction is the combination of portable asset meaning and an explicit
design workflow. This is not a claim that no other MCP server has such tools.

## What travels with each asset

| Metadata | Basis |
| --- | --- |
| Stable identity, category and search tags | Existing authored catalogue |
| Actual dimensions, polygon count | Existing normalised geometry measurements |
| Nominal target and plan deviation | Prompt target compared with measurement |
| Anchor, footprint, support plane, clearances | Existing spatial contract; authored allowances |
| Material ids and mesh groups | Existing Almond material contract |
| Prompt, Meshy job ids, model and generation date | Recorded provenance |
| Suggested rooms | Explicitly labelled category/label heuristics |
| Quality warnings and topology review status | No invented certification or topology audit |
| Licence and attribution | Existing project declarations; models CC BY 4.0, metadata MIT |

The full passport is in `asset.extras.almond.passport`, the `.almond.json`
sidecar, and the catalogue manifest. Node extras reference the stable identity.
`passport.schema.json` describes the versioned envelope; Pydantic validates
required fields and positive, finite dimensions. Nested source/provenance
records remain extensible dictionaries. Model and sidecar checksums are in the
manifest; the model checksum also binds the sidecar to its GLB.

The sidecar is retained because Rhino drops some glTF extras. The existing
restore script now stamps `almond:passport` onto imported Rhino objects. That
script's generation is tested; an actual Rhino import round trip is still a
release acceptance check.

Legacy GLBs use numeric millimetres with Y up. This release does not rescale
them. A generic glTF consumer, which expects metres, must apply 0.001; the
passport records the conversion. Contract axes are X width, Y depth, Z up.

## MCP interface

- `recommend_generated_assets`: exact token ranking over labels/tags, with
  explicit category, suggested-room, triangle-budget and envelope filters.
  Returns reasons, warnings, valid 0°/90° orientations and resource URIs.
- `get_generated_asset_passport`: full provenance and spatial metadata.
- `evaluate_generated_asset_fit`: arbitrary-angle rectangular envelope check,
  including authored clearances by default; reports required size and margins.
- `almond://generated/catalogue`: compact JSON catalogue resource.
- `almond://generated/{asset_id}/passport`: JSON passport resource.
- `almond://generated/{asset_id}/preview`: the existing Blender PNG preview.

The three new tools return structured JSON and advertise read-only behaviour.
Existing list/search/get/place APIs remain available. No extra service or
embedding database is needed.

Example brief: “Find a bench for a 2400 × 1600 mm area, under 10,000 triangles.”

```python
recommend_generated_assets(query="bench", width_mm=2400, depth_mm=1600,
                           max_triangles=10000)
get_generated_asset_passport(asset_id="gen-park-bench-1")
evaluate_generated_asset_fit(asset_id="gen-park-bench-1",
                             width_mm=2400, depth_mm=1600)
```

Inspect the preview, then use `place_generated_asset`, `register_scene_instance`
and `validate_scene_layout`. Envelope fit means the rectangle can contain the
asset somewhere; it does not check obstacles, a particular scene position,
mounting height, egress or accessibility compliance. Suggested room filters
are intentionally simple and are not semantic-vector search.

## Packaging and upgrades

The `almond-mcp` **0.6.0rc1 wheel includes all 47 GLBs, 47 sidecars, previews,
the manifest, schema and provenance**. A fresh install needs no asset download
or GitHub publication. It scaffolds the generated library under
`Almond/GeneratedAssetfiles/releases/0.6.0rc1` in the user's data directory.
Old versions and user overrides are preserved. Re-resolution restores missing
bundled files; `audit-assets` reports modified/corrupt files without overwriting
them. Explicit `RHINO_MCP_GENERATED_ASSET_DIR` still takes precedence.

The Rhino `almondbridge` binary is unchanged: the feature uses the existing
script/import API. Do not publish a new Yak binary solely to match this Python
version. Do not register a second MCP server alongside an existing Almond entry.

Build in a scratch environment on OneDrive, as required by `AGENTS.md`:

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'almond-060rc1-venv'
$env:UV_LINK_MODE = 'copy'
uv run pytest -q
uv run almond-mcp audit-assets
uv build
uv run python tools/verify_release.py dist/almond_mcp-0.6.0rc1-py3-none-any.whl
```

A local trial can use the built wheel via `uvx --from <absolute-wheel-path>
almond-mcp audit-assets`, then the same command with `serve` in an isolated MCP
client. This does not require changing the user's existing MCP configuration.

Before public release: test one actual Rhino import in a fresh document,
verify units and `almond:passport`, register the instance and validate the
layout, then publish the reviewed source and package through the project's
normal release process. GitHub currently lacks earlier local commits, so
publishing the release also needs review of that existing backlog.

## Verification record (19 September 2026)

- All 47 model hashes, sidecar hashes, embedded/sidecar/manifest passports,
  identities, dimensions and PNG previews passed the offline asset audit.
- Compared each updated GLB with the previous Git HEAD: binary chunks, mesh
  definitions, materials, scene graph and transforms are unchanged.
- MCP client integration exercised discovery, structured recommendations,
  passport resources, preview MIME types and unknown-id handling.
- Built both source distribution and wheel; verified the wheel's asset pack
  and exclusions. Installed the wheel into a separate environment and invoked
  it outside the source checkout with a fresh, temporary user-data directory.
- The installed server exposed 52 tools over stdio; the bench-fit example and
  PNG resource read succeeded. Source tests use FastMCP 3.0.2/MCP 1.26.0;
  the clean installation smoke test also passed with FastMCP 4.0.5/MCP 2.2.0.
- Actual Rhino import and object metadata restoration remain untested live.

## Next library improvements

Generation evidence and future reference attribution follow
[source documentation](generation-source-documentation.md). The per-asset
`GeneratedAssetfiles/source-register.json` records known history and explicit
gaps; regenerate it after library edits and run its `--check` before release.

1. Curate per-asset seating/use heights, front direction and explicit contact
   points; measure them from the geometry and record the evidence.
2. Add validated lower-detail meshes for heavy trees and furniture, with
   separate checksums and measured visual error.
3. Author room kits with relationship rules (chair/table clearance, lamp
   mounting), using the existing scene ledger for collision checks.
4. Add verified IFC classifications and manufacturer data only where an
   actual source supports them; generated approximations remain labelled.
5. Add new Meshy models against a written brief, then ingest through the same
   normalise → passport → preview → audit pipeline.

Implementation references: [glTF asset schema](https://github.com/KhronosGroup/glTF/blob/main/specification/2.0/schema/asset.schema.json)
and [MCP tools and structured results](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
