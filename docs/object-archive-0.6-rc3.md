# Almond Object Archive — 0.6.0rc3

One local entry point for the generated model and drawing libraries. The Neo
Swiss interface uses an editorial grid, warm paper background, restrained red
accents, large typography, and neutral geometry-study thumbnails.

## Open it

From an installed rc3 package, run `almond-mcp library --open`. It serves at
<http://127.0.0.1:8767/>. Use `--port 8768` if the default port is occupied.
Keep the command running while using the archive; Ctrl+C stops it. No Rhino
session or Internet connection is needed for the local library and 3D viewer.

From this checkout, use the development interpreter with
`python -m almond_mcp.cli library --open`. Do not sync a live MCP environment.

## Collection

- 47 generated Meshy GLBs with embedded passports and sidecar spatial contracts.
- 7 indexed drawing elements: 4 community SKP models and 3 SVG elements.
- 10 linked projection packages: 60 view/scale combinations, each in SVG and
  DXF, plus 20 A3 SVG sheets.
- 6 reference directories, explicitly separate from model-generation evidence.

The catalogue joins existing manifests by stable asset ID. It does not copy or
move model files. Generated models live in `GeneratedAssetfiles`, drawing
elements in `DrawingAssetfiles`, and projections in `Draftingfiles`. The normal
Almond environment overrides continue to select each canonical library.
Restart the archive after changing manifests or adding files. Missing local
files remain discoverable with an explicit unavailable state and source link.

Search covers names, IDs, variants, categories, tags and drawing roles. Filters
select generated models, drawing elements, linked drawing packages or saved
objects. Saved selections stay in browser localStorage; there is no account or
cloud synchronization. Search has a `/` keyboard shortcut; dialogs support Escape.

Open an object to rotate/zoom its GLB, select a plan/front/right view or A3 sheet,
choose 1:50 or 1:100, and download the available representation. SVG and sheet
scale describes print size; fitted screen previews are not physically to scale.
DXF coordinates are full-size millimetres. The browser scales legacy numeric-mm
GLBs by 0.001 for display only; downloaded geometry is unchanged.

Thumbnails are neutral Blender geometry studies, not material specifications.
Rebuild with `blender -b --python tools/render_generated_previews.py --
GeneratedAssetfiles/models GeneratedAssetfiles/previews --archive`.

## Shared MCP and HTTP catalogue

- MCP tool: `search_asset_repository(query, kind, drawing_ready, limit)`.
- MCP resource: `almond://repository/{asset_id}` includes source evidence,
  representations and resolved local paths, even without the browser server.
- HTTP: `/api/catalogue` and `/api/assets/{asset_id}.json`.
- Every object can download its JSON record; About can export the full index.

The HTTP index uses relative URLs and omits absolute local file locations.
It is a catalogue export, not a portable model-file bundle. The existing source
register preserves known gaps: exact submitted API requests and original image
bytes are not reconstructed. Later reference research is not attributed as a
generation input.

## Packaging and boundaries

The UI, model-viewer 4.3.1, its Apache 2.0 licence, and registry integrity record
ship inside the Python package. The viewer is vendored from the official npm
package; no CDN is required for the bundled uncompressed GLBs. Decoder downloads
for future compressed formats are not enabled. The server binds only to
127.0.0.1, validates Host, and serves a fixed allowlist of UI and manifest-listed
files. It does not provide uploads, filesystem browsing or remote access.

The wheel and source distribution exclude all downloaded community model files.
A fresh installation shows their catalogue records and source links; the user's
existing local files are accessible only where already installed. Publishing
this local archive publicly would require a separately scoped deployment and
item-level rights review.

Derived drawings are silhouettes, not construction details. They do not infer
hidden edges, assembly layers, or verified manufacturer dimensions. The existing
MCP drawing audit checks outputs against source geometry before production use.

The Rhino bridge binary and active MCP registration are unchanged by this build.
