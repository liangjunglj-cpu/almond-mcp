# Almond drawing pilot

Ten models have plan/front/right silhouettes at 1:50 and 1:100. Open `index.html`
for the gallery. Each package contains scaled SVG, full-size millimetre DXF,
available A3 sheets, and `drawing.json` with generation evidence and output hashes.

The geometry is derived from the Almond generated asset library (CC BY 4.0).
Attribute **Almond generated asset library**, https://github.com/liangjunglj-cpu/almond-mcp.
No third-party reference drawing files are bundled. `sources.json` contains
research candidates; it does not claim they were used to generate these models.

Silhouettes are appropriate for layout and entourage. They do not show inferred
construction layers, hidden edges or sections. Front orientation requires review.
Print individual A3 SVGs at actual size and check the 50 mm calibration line.

MCP tools: `get_asset_drawing`, `generate_asset_drawing_views`,
`audit_asset_drawing`, `get_generation_sources`, `search_detail_sources`.
Custom GLBs require explicit mm/m units; no original model file is overwritten.
Source references supplied to generation describe the drawing's references and
do not retroactively become original Meshy inputs. User-provided history and
rights remain unverified unless separately reviewed.
