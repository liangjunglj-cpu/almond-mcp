# Food4Rhino listing - Almond 0.6 release candidate

Prepared for publication; this document does not mean the release is live.
Update the existing Almond MCP listing, preserving the permanent plugin GUID.
Use the Rhino Account that owns the existing app / Yak package.

## Listing fields

| Field | Prepared value |
| --- | --- |
| App name | Almond MCP |
| Release | almondbridge 0.6.0-rc.11 / almond-mcp 0.6.0rc11 (prerelease) |
| Platform | Rhino 8 for Windows only |
| GUID | c337dbb8-394a-4593-9c2b-a3d7cfc91893 |
| Code licence | MIT |
| Included generated assets | CC BY 4.0; attribute Almond generated asset library |
| Website | https://github.com/liangjunglj-cpu/almond-mcp |
| Support | https://github.com/liangjunglj-cpu/almond-mcp/issues |
| Support email | liangjung.lj@gmail.com |
| Icon | assets/almond-icon-512.png |
| Categories | Architecture; AI / automation; select the closest offered categories |

## Short description

Almond for Rhino 8: browse 47 generated 3D models and linked SVG/DXF drawings in an offline Object Archive, with embedded metadata and source records. Includes an optional MCP bridge for AI-assisted modelling. Windows; free and open source.

## Description

Almond combines an architectural Object Archive with a semantic MCP bridge for
Rhino 8. Install almondbridge, restart Rhino, and run **AlmondLibrary** to open
its compact library in a dockable side panel that follows Rhino appearance settings. Use AlmondLibraryBrowser
for full-size browsing. Browsing the included collection needs no
Python installation, Meshy account or AI subscription.

The package includes 47 generated GLB models with embedded Almond passports,
spatial contracts, measured mesh dimensions, neutral previews and source records.
Ten models have linked drawing packages: 60 plan/front/right view-scale pairs
in SVG and DXF, plus 20 A3 SVG sheets at 1:50 and 1:100. Search the collection,
rotate a model, inspect its drawings and download the representation you need.
DXFs use full-size millimetres; SVG sheets retain their declared paper scale.
The docked panel also offers Place and thumbnail dragging into the viewport,
with shared blocks and a Light detail option for heavier generated models.

Source histories include recorded generation prompts, provider task IDs,
checksums, attribution and known evidence gaps. Generated geometry is a design
aid; its dimensions are not manufacturer specifications. Derived drawings are
silhouettes and do not infer construction layers, hidden edges or performance.

Seven optional community drawing elements remain searchable as catalogue records
and source links. Their third-party model files are not redistributed. Six
architectural detail reference directories are research leads, not attributed
inputs to the existing generated models.

For AI-assisted modelling, the separate almond-mcp Python package connects an
MCP-compatible client to the Rhino bridge. It adds asset retrieval, spatial
contracts, layout validation, material metadata, drawing generation and optional
Karamba-based structural workflows. Python/uv and an MCP client are required for
these AI features, but are not required to browse the included archive.

Code is MIT. Included generated models and derived drawings are CC BY 4.0,
attributed to Almond generated asset library. Other components retain their
included licence notices. Not affiliated with Meshy, McNeel, Trimble, IKEA or
Karamba3D. Karamba and downloaded community model files are not bundled.

## Downloads

Primary file: `almondbridge-0.6.0-rc.11-rh8_0-win.yak`.
Optional upload wrapper: `almondbridge-0.6.0-rc.11-food4rhino.zip` containing the
same Yak and quickstart guide. Both are in `dist/release-0.6.0rc11/` after preparation.
Use the current form's supported upload type; do not rename an extension.
If the existing listing is linked to Yak, update the matching package rather
than creating a duplicate app. The permanent GUID remains unchanged.

Download title: **Almond 0.6 release candidate - Rhino 8 Windows + Object Archive**.
Description: Install through Rhino Package Manager (Include pre-releases) or use
the provided Yak package. Restart Rhino, then run Almond. The 47 generated
models are included. See GETTING-STARTED.md for optional MCP setup.

## Release notes

- Adds AlmondLibrary and the bundled offline Neo Swiss Object Archive.
- Includes 47 generated models, metadata, source evidence and previews.
- Links 10 drawing packages with SVG, DXF and A3 sheets.
- Adds a shared MCP repository search and per-object resources.
- Adds compact Karamba help buttons with setup guidance and support diagrams.
- Adds audited packaging, checksum verification, isolated builds and CI artifacts.
- Windows / Rhino 8.0 SDK compatibility; in-Rhino runtime smoke is a release gate.

Suggested screenshots: archive overview; model with metadata; plan/DXF view.
Use screenshots from the candidate being released, not unrelated project imagery.

## Publication references

Checked 19 September 2026: [Food4Rhino FAQ](https://www.food4rhino.com/en/faq),
[McNeel package publishing](https://developer.rhino3d.com/guides/yak/pushing-a-package-to-the-server/),
and [Rhino plugin installation](https://www.rhino3d.com/en/docs/guides/scripts-plugins/how-to-use/).
Food4Rhino account access and any listing review remain separate from local builds.

### rc.6 placement and rc.7 workspace

Compact model tiles, thumbnail-to-viewport placement, a keyboard-accessible
Place action, shared blocks, optional lighter meshes and embedded derivation
records. Viewport dragging was confirmed by the user on rc.6. Keep this listing a draft until the remaining native checklist in
release-0.6.md passes. Public publishing has not been performed.

The rc.7 menu separates Models and Karamba Validation. The analysis workspace
shows assumptions, support/load diagrams, view toggles, mapped utilization,
deflection limits and exportable analysis records. Karamba installation and
licensing are separate. This is first-order screening, not full code verification.
The active IKEA catalogue and supplier links/tools have been retired. Native
acceptance of the new Karamba workspace is pending.
