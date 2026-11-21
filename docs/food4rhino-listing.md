# Food4Rhino listing - Almond 0.8.0

Prepared for the 0.8.0 stable release (almondbridge 0.8.0 on Yak, almond-mcp 0.8.0 on PyPI). Update the
existing [Food4Rhino listing](https://www.food4rhino.com/en/app/almond-mcp), preserving the permanent plugin
GUID, with the Rhino Account that owns the existing app / Yak package. Put 0.8.0 first in downloads and keep
0.6.0 as the previous stable download. Publish the GitHub release, PyPI and Yak first
([release-0.8.md](release-0.8.md)).

## Listing fields

| Field | Prepared value |
| --- | --- |
| App name | Almond MCP |
| Release | almondbridge 0.8.0 / almond-mcp 0.8.0 |
| Platform | Rhino 8 for Windows only |
| GUID | c337dbb8-394a-4593-9c2b-a3d7cfc91893 |
| Code licence | MIT |
| Included generated assets | CC BY 4.0; attribute Almond generated asset library |
| Website | https://github.com/liangjunglj-cpu/almond-mcp |
| Support | https://github.com/liangjunglj-cpu/almond-mcp/issues |
| Support email | liangjung.lj@gmail.com |
| Icon | assets/almond-icon-512.png |
| Categories | Architecture; Structure / analysis; Environment / simulation; AI / automation (closest offered) |

## Short description

Almond for Rhino 8: an offline library of 144 generated 3D models with linked drawings, a built-in structural
analysis engine with Eurocode steel checks, and (beta) climate, daylight and thermal studies. Optional MCP
bridge for AI-assisted modelling. Windows; free and open source.

## Description

Almond is a working library for architecture inside Rhino 8. Install almondbridge, restart Rhino and run
**Almond**: one docked panel with three workspaces, Models, Structure and Environment, that follows Rhino's
appearance. Browsing models and running the structural engine need no AI subscription.

**Models.** 144 generated 3D models: furniture, people, plants and trees, street furniture, building services,
vehicles and boats, ornament, and a Blender-scripted street and services kit. Every model carries an embedded
passport, real-world dimensions, an Almond material, a preview and its source record (how it was generated or
built, with checksums and known evidence gaps). Search, rotate, Place or drag into the viewport; ten models
have linked plan and elevation drawings (SVG, DXF, A3 sheets). Generated geometry is a design aid; dimensions
are not manufacturer specifications.

**Structure.** Draw a frame as centre lines with support points and press Run. Almond's own 3D frame solver
(checked against OpenSees on twelve typologies) gives the deflected shape, buckling factor α_cr, P-Δ where it
matters, EN 1990 load combinations, floor and placed-model loads, support types per point (fixed, pinned,
rollers, springs, lateral restraints), and EN 1993-1-1 steel member checks: classes, buckling curves,
interaction, shear, bow imperfections and lateral-torsional buckling. Each member is judged against its own
span, sway as storey drift. The Almond Results panel lists every member, combination and load with CSV export.
Concrete, timber and aluminium are indicative; gravity loads only. Karamba3D can be used as an alternative
engine (beta; Karamba is installed and licensed separately).

**Environment (beta).** Load an EPW weather file, define rooms and constructions, and study climate, sun path,
shadows, daylight (daylight factor, sDA/ASE/UDI, EN 17037), solar radiation, ISO 13790 thermal energy and
comfort, with code packs for envelope checks. Results are design-stage comparisons, not compliance
simulations.

**For AI-assisted modelling**, the almond-mcp Python package connects an MCP client (Claude, Codex) to the Rhino
bridge: model retrieval and placement, layout checks, drawings, structural and environmental studies, twelve
benchmarked structural reference typologies and ten annotated Grasshopper teaching definitions. Model files
download on first use. Python/uv and an MCP client are needed only for these AI features.

Code is MIT. Included generated models and derived drawings are CC BY 4.0, attributed to Almond generated asset
library. Other components keep their included licence notices. Not affiliated with Meshy, Tripo, McNeel,
Trimble, IKEA or Karamba3D. Karamba and downloaded community model files are not bundled.

## Downloads

Primary file: `almondbridge-0.8.0-rh8_0-win.yak`. Optional upload wrapper:
`almondbridge-0.8.0-food4rhino.zip` (the same Yak and the quickstart guide). Both are in
`dist/release-0.8.0/` after preparation. Use the current form's supported upload type; do not rename an
extension. If the listing is linked to Yak, update the matching package rather than creating a duplicate app.

Download title: **Almond 0.8.0 - Rhino 8 Windows: Models, Structure, Environment (beta)**.
Description: Install through Rhino Package Manager (search almondbridge) or use the provided Yak. Restart
Rhino, then run Almond. All 144 models are included. See rhino-archive-quickstart.md for optional MCP setup with
almond-mcp 0.8.0 from PyPI.

## Release notes

- Stable release; replaces 0.6.0. No "Include pre-releases" needed.
- Structure workspace out of beta: Almond's own frame solver, EN 1990 combinations, stability (α_cr, P-Δ) and
  EN 1993-1-1 steel checks now including shear, bow imperfections, lateral-torsional buckling and Table B.3 Cm.
- Support types per support point from the Supports tab; per-member deflection spans and storey drift.
- Environment workspace (beta): climate, daylight, radiation, thermal and comfort studies for rooms, with
  constructions and code packs, and a tutorial model.
- Model library grows from 50 to 144 models, labelled by how each was made (Meshy, Tripo, Scripted).
- MCP: structural reference typologies, Grasshopper teaching definitions, scene-metadata audit (pilot); model
  files download on first use.

## Gallery images

Upload in this order (1200 × 800; full 1920 × 1080 versions beside them). The renders are made in Blender
from the release's own model files and Almond materials; the panel captures come from the release candidate
in Rhino 8 (dark theme, the tester's setting). Files are in `dist/release-0.8.0/food4rhino-images/` after preparation (not tracked in git).

| # | File | Caption |
|---|---|---|
| 1 | `harbour-street-1200x800.png` | A waterfront street furnished from the library: fishing boats, street furniture, people and trees |
| 2 | `library-lineup-1200x800.png` | 40 of the 144 library models at true relative scale |
| 3 | `panel-models.png` | The Models workspace in Rhino: search, previews, Place and drag |
| 4 | `structure-overlay.png` | The native structural engine: deflected shape and member utilisation in the viewport |
| 5 | `structure-results.png` | Almond Results: every member, combination and check, with CSV export |
| 6 | `environment-daylight.png` | Environment (beta): a room daylight study on the tutorial model |
| 7 | `environment-results.png` | Environment (beta): the results tab with the daylight plan |
| 8 | `y2k-district-1200x800.png` | A plaza assembled from the scripted street and services kit |
| 9 | `interior-living-1200x800.png` | An interior from the furniture models |
| 10 | `model-detail-1200x800.png` | One model up close, with its mesh |

## Earlier listing: 0.6.0

almondbridge 0.6.0 and almond-mcp 0.6.0 were published to Yak and PyPI on 27 September 2026 and the listing
was updated the same day. Its text and the rc.6/rc.7 notes are in git history
(`git show origin/master:docs/food4rhino-listing.md`).

## Publication references

Checked 19 September 2026: [Food4Rhino FAQ](https://www.food4rhino.com/en/faq),
[McNeel package publishing](https://developer.rhino3d.com/guides/yak/pushing-a-package-to-the-server/),
and [Rhino plugin installation](https://www.rhino3d.com/en/docs/guides/scripts-plugins/how-to-use/).
Food4Rhino account access and any listing review remain separate from local builds.
