# Almond 0.6.0rc2: traceable drawing pilot

DETAIL account access is deferred at the user's request. This update works offline with existing generated models and user-supplied static GLBs. No new paid generation or external drawing download is required.

## Available workflow

1. `get_generation_sources(asset_id)` returns recorded generation evidence, including Higgsfield image jobs where applicable and explicit unknowns.
2. `get_asset_drawing(asset_id)` retrieves a precomputed pilot package. Ten models cover seating, a table, sofa, bed, sanitary fixture, street lighting, vegetation and a person.
3. `generate_asset_drawing_views` creates plan, front and right silhouettes for any supported library model or a custom GLB. It writes a new directory under the user's Almond `drawing-runs` folder; it never overwrites previous drawing packages.
4. `audit_asset_drawing` verifies output checksums and compares the current model's transformed triangle geometry with the recorded geometry hash. Metadata-only model changes do not make drawings stale. For custom models, supply the current source path to check staleness.
5. `search_detail_sources` searches six curated source directories by topic. It returns links and access/rights notes, not actual downloaded construction details. Item-level citations can be attached through `source_references` when generating a drawing package.

Example custom mesh call:

```json
{
  "source_glb": "C:/Projects/MyProject/custom-bench.glb",
  "input_units": "m",
  "up_axis": "y",
  "scales": [50, 100]
}
```

Call `generate_asset_drawing_views` with those arguments. Standard glTF exports normally use metres; the legacy Almond library uses numeric millimetres and is handled automatically. No dimensions or units are guessed for custom files. Supported custom input is a static uncompressed GLB with embedded float positions and triangle indices, up to 100 MB and 250,000 triangles. Skinning, animation, morph targets, external buffers, required extensions and sparse/normalized accessors are rejected explicitly.

## Output and representation

Each package contains three views at each requested scale, as SVG and full-size millimetre DXF, plus A3 landscape SVG sheets where the geometry fits. An oversized view does not silently shrink to fit: a sheet warning explains the missing sheet. The default scales are 1:50 and 1:100. Each sheet includes measured extents and a 50 mm paper calibration line; print at actual size.

The method unions projected mesh triangles and simplifies their boundaries while preserving topology. A 0.01 mm precision grid avoids tiny numerical slivers. For meshes above 30,000 triangles, a bounded raster mask is converted to vector contours instead; the longest projected extent spans 2,044 pixels. These dense-mesh contours use simplification without topology preservation, so small openings and fine features can disappear. Every view records its method, topology policy and raster resolution where applicable. The simplification tolerance is 0.05 mm at paper scale, capped at 5 mm in model space. Total raster-plus-simplification boundary error is not independently measured.

Views use a right-handed coordinate frame. For Y-up input, the explicit transform is `(X,-Z,Y)` into Z-up; front looks along +Y, right looks along -X. This is a coordinate convention, not recognition of an object's actual front. Input translations and model origin are retained. Bounds come from projected geometry; normalization for furniture placement is a separate existing workflow.

These are silhouettes for entourage/layout drafting. They do not infer internal visible edges, hidden lines, cut planes, hatches, wall layers, fasteners or engineering ratings. Section drawing, construction assembly composition and live Rhino sheet placement remain future increments. The existing Rhino bridge binary is unchanged.

## Source documentation

Every SVG embeds the source asset ID, source file and geometry hashes, coordinate interpretation, generation evidence, drawing method and limitations. `drawing.json` links the geometry to every derived file and records output hashes. DXF files use millimetres and a dedicated profile layer; retain their adjacent manifest when exchanging them because full citations reside in SVG/JSON.

Source references require a title, publisher, canonical URL, item/page/figure locator, access date, terms URL, relationship and explanation of use. They are attached to this drawing and do not retroactively become original generation inputs. Missing custom mesh history stays `not_supplied`. See [source documentation](generation-source-documentation.md).

The bundled source directory contains dataholz, Lignumdata, ARCAT, CADdetails, WikiHouse and LibreCAD. These remain research candidates with item-specific review requirements. No external source is credited as the origin of the pilot geometry, and no third-party drawing binaries are bundled.

## Build and verification

Use the scratch development environment so the live MCP environment is untouched:

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'almond-060rc2-venv'
$env:UV_LINK_MODE = 'copy'
uv sync
uv run python tools/document_generation_sources.py --check
uv run python tools/build_drawing_pilot.py
uv run pytest -q
uv build
uv run python tools/verify_release.py dist/almond_mcp-0.6.0rc2-py3-none-any.whl
```

The pilot builder reuses audited existing packages; it refuses to overwrite stale packages. A revised pilot must use a new output directory. Runtime generation already creates a new revision directory on every call.

Validation includes analytical boxes for unit conversion/node transforms, a shape with a genuine hole, DXF reading/auditing, physical SVG dimensions, metadata-only changes versus changed geometry, invalid inputs and the MCP custom-GLB workflow. Release verification audits all generated models, source records and bundled pilot drawing packages.

Runtime algorithm references: [Shapely union](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.union_all.html), [topology-preserving simplification](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.simplify.html), [glTF specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html).
