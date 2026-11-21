# Openly licensed Grasshopper definitions for an Almond teaching catalogue

Research date 2026-10-11. Companion data: `reference/gh-library-candidates-2026-10.json` (129 repos, every .gh/.ghx path for accepted/conditional repos, pinned raw URLs, plugin dependencies) and `reference/gh-library-candidates-2026-10.meta.json` (field semantics).

## Method

- Searched with `gh search code --extension ghx|gh` across 64 architecture keywords. Code search only indexes XML `.ghx`; binary `.gh` files show up through repo-level discovery. Also ran `gh search repos` by topic (grasshopper, grasshopper3d, rhino3d, parametric-design, computational-design) and by keyword, and checked known sources directly (McNeel, ParametricCamp, COMPAS/ETH GKR/BRG, TUM AFAB, Ladybug, Wasp, BHoM, Kangaroo, Mode Lab primer, plugin repos).
- Checked licences per repo with `gh api repos/O/R/license`, read the actual text wherever GitHub reported NOASSERTION, and grepped READMEs for licence statements. Nothing was cloned.
- Fetched each candidate file into memory with `gh api` and parsed it:
  - `.ghx`: XML read of the `GHALibraries` chunk for plugin assemblies, plus component names and scribble/panel text.
  - `.gh`: raw-deflate decompression of the GH_IO archive, then the same chunks.
  - Script components: plain and base64-encoded source scanned for Python `import`s to catch COMPAS-style dependencies, which are user objects and not GHA plugins.
- Pinned every raw URL to the branch commit SHA. Spot-checks return HTTP 200/206. None of the fetched files was a git-lfs pointer.

## Counts

| | repos | selected files | vanilla (no plugin, no 3rd-party Python) |
|---|---|---|---|
| accept | 29 (27 with selections) | **95** | **58** |
| conditional | 10 (9 with selections) | 18 | 5 |
| exclude | 90 | - | - |

"Vanilla" means it runs on stock Rhino 8. GhPython and Rhino 8 script components count as vanilla. Kangaroo2 ships with Rhino 7/8 and is flagged as "bundled".

Of the 58 vanilla accepted files, 24 come from one repo (runxel). Openly licensed, vanilla, *architectural* Grasshopper files are scarce on GitHub. Most architectural sets carry no licence at all (see the exclusions below).

## Licence notes for an MIT project

- MIT, BSD, Apache-2.0, BlueOak-1.0.0, BSL-1.0, CC0 and CC BY 4.0 are all fine.
  - Keep the original copyright/licence notice next to each file, e.g. `LICENSES/<repo>.txt` plus a per-file header scribble.
  - BlueOak and BSL also require the licence text with source copies.
  - CC BY requires attribution plus a "modified" statement.
- MIT itself does not force the redistributed assets to be MIT. The cleanest approach is a `third_party/` catalogue tree with a manifest listing source, licence and SHA, the same pattern as `GeneratedAssetfiles/source-register.json` and `docs/licensing-audit.md`.
- **Embedded plugin code risk.** User-object plugins (COMPAS "Draw", compas_timber "CT:", Ladybug legacy, CEM) store their Python source inside the `.gh`/`.ghx`. COMPAS-family code is MIT, so that's fine. Ladybug Tools code is AGPL-3.0, so strip those components first (relevant to `climate_active_envelopes`).

## Top picks (ranked, 14 definitions)

### Facade / screens / paneling
1. **runxel `gh/voronoi_on_surface.ghx`** (BlueOak, vanilla, 61 objects). Voronoi cells populated on a brep and offset into a perforated screen. Includes good scribbled notes on a known Offset-on-Surface bug.
   https://raw.githubusercontent.com/runxel/grasshopper-examples/0e57586bdc00a4c3663983e67f36a0ce1f6c7ee6/gh/voronoi_on_surface.ghx
2. **runxel `gh/diagrid_on_surface.ghx`** (BlueOak, vanilla). Diagrid on a freeform surface with Divide Domain² and Isotrim. The canonical facade-structure lesson.
3. **runxel attractor series `attractor_1..4_*.ghx`** (BlueOak, vanilla). Point, linear, deflection and multi-point attractors on rectangular, hexagonal and triangular grids. Teach these as one perforated-panel progression.
4. **runxel `gh/spiral_panels.ghx`** + **`gh/rotate_by_length.ghx`** (vanilla). A field of rotated extruded fins plus rotation-by-remap logic. This is the louvre/fin lesson. A dedicated louvre file exists only in the unlicensed jhorikawa set.

### Structure
5. **runxel `gh/shell_roof.ghx`** (vanilla). Ruled shell roof with an iso-curve rib grid, piped members and diagonal bracing.
6. **arpastrana/compas_cem `examples/ghpython/dome.ghx`** and **`spiral_staircase.ghx`** (MIT; needs the `compas` + `compas_cem` Python packages). Equilibrium form-finding with a real structural rationale.
7. **arup-group/GSA-Grasshopper `ExampleFiles/GsaGH_Example3_Truss.gh`** and **`GsaGH_Example2_Reciprocal.gh`** (MIT). The truss and reciprocal-roof geometry is vanilla. Analysis needs GsaGH plus a licensed Oasys GSA. Good for pairing with Almond's native frame solver: keep the geometry and swap in the analysis.
8. **gramaziokohler/coding_architecture_fs25 `a02_tessellation.ghx` → `a03_lift_solution.ghx` → `a04_design_solution.ghx`** (MIT; compas, compas_timber and repo-local .py modules). An ETH reciprocal-frame timber pavilion pipeline, from 2D units to freeform to joints.

### Form / massing
9. **oderby/VVD `examples/versionTower.ghx`** / **`versionTower-Flower.ghx`** and **marcsyp/gh-serve-ionic `tower-simple.ghx`** / **`Tower-lines.ghx`** (MIT, vanilla). Twisting polygon floor plates lofted or extruded into towers. Tower-lines adds a floor-area readout.
10. **runxel `gh/tween_two_closed_curves_native.ghx`** and **`star_curve_loft.ghx`** (vanilla). Floor-plate interpolation between two plans, and a twisted star-section tower.
11. **danilnagy/gh-subd-plan `subdivision.gh`** (MIT; needs Human, which is free but closed-source). A room programme (rooms.json) recursively subdivided into a floor plan, ready for Galapagos. This is the only openly licensed plan generator found.
12. **baharmon/computational-design-library `15-terrain/terrain-mesh.gh`** and nonoesp **`GADHelper_TerrainFromRLs.gh`** (MIT, vanilla). Site terrain from points or contours, with contours.

### Detail
13. **gramaziokohler/compas_introduction `305/307/308_class_brickwall_methods.ghx`** (MIT, plain GhPython) and **compas_introduction_2025 `brick_wall_solution.ghx`** (needs compas). A parametric brick bond along curves and surfaces, written OOP-style.
14. **nonoesp/GettingArchitectureDoneKit `Util_StairsFromPlanSteps.gh`**, **`GADArchitectureRoofInclined.gh`** and **`Util_metalDoor.gh`** (MIT, vanilla clusters), plus **mcneel/compute.rhino3d `dresser3.gh`** (MIT, vanilla, H/W/D dresser with drawer cuts), plus **bringfire/Rook `spiral_staircase.ghx`** (MIT, GhPython).

Runners-up:
- trtku/sand-report `formwork_spiral_v1.ghx`, `slab_formwork_1to1.ghx` and the vault proposal (MIT, vanilla; sand-formwork research).
- climate_active_bricks `ex4_assembly_solar_optimization.ghx` (MIT; a brick wall rotated per brick for solar exposure, needs compas).
- runxel `mesh_shadow.ghx` (a shading study).
- arendvw/clipper "Simple urban plan" (BSL-1.0; needs the Clipper plugin).

## Conditional (usable with caveats)

| repo | licence | why conditional | notable files |
|---|---|---|---|
| ParametricCamp/TutorialFiles | CC BY-SA 4.0 | Share-alike: modified copies must stay CC BY-SA. Ship them as a separately licensed sub-folder, never relicensed to MIT. Mostly vanilla and the most architectural set found. | Berlin Holocaust Memorial p1-3, Calatrava L'Umbracle p1-2 |
| code-id/WORKFLOW-Webinar… | CC BY-SA 4.0 (README) | share-alike | recursive OOP surface subdivision |
| ar0551/Wasp | LGPL-3.0 | LGPL example files can't be relicensed MIT, and Wasp is required | 130 discrete-aggregation examples |
| gramaziokohler/coding_architecture_fs26 | MIT by README only | The README says "see LICENSE" but the repo has no LICENSE file, so there is no copyright line to reproduce | mesh-relax reciprocal frame, attractors |
| shapediver/GrasshopperExampleModels | MIT | showcases need 6-8 plugins | Barcelona neighbourhood, Speckle pavilion |
| simpleSketche/simple-sketches | MIT | needs Human + Bengesht | programme floor-plan sketches |
| augmentedfabricationlab/climate_active_envelopes | MIT | contains AGPL Ladybug components | brick envelope + solar radiation |
| augmentedfabricationlab/cdf_2023 | MIT | needs CEM / Karamba3D | Chovghi CEM structure |
| MAS-dfab/MAS-2526 | MIT | needs the `mola` library or repo modules | subdivision massing, stick structure |
| gramaziokohler/workshop_iaac_2024 | MIT | compas_urt + Kangaroo2 | ceramic tile design |

## Excluded but notable

- **jhorikawa/GrasshopperHowtos** (no licence, 289★). The richest architectural set: 126 definitions including Twisted Louver, Snake Tower, Recursive Stair, Metaball Building, Leaf Dome, Fractal Shell and Column Shelf. All rights reserved, so ask Junichiro Horikawa. GrasshopperTips and GrasshopperProgrammingTutorials are in the same position.
- **Dan-Piker/Kangaroo-examples** (no licence, 250★). Bending gridshell, gridshell drape, tensile cone, British Museum roof, planar quads, soap film. This is the gridshell/tensile gap in the accepted set. Ask Daniel Piker.
- **renatogcruz/workshop_parametric_architecture**, **ekaggrat/_gh** (jali screens) and **papiluxo/santiago.world** (Nervi dome, IIT truss). Architectural, but no licence.
- **Digital-Structures/gh-design-space-exploration** (MIT Digital Structures), **ITEC-GPA/Rhino2FEM** (188 FEM definitions), **dantaeyoung/GrasshopperArsenal** (GSAPP), **BRG-teaching/seoul_2025**, **SUTD-UDOpt**, **mcneel/developer.rhino3d.com** samples. All have no licence.
- **modelab/grasshopper-primer** example files: CC BY-NC-SA 3.0. The NC term blocks redistribution.
- **ladybug-tools** sample files: AGPL-3.0. **philipbelesky/groundhog** landscape precedent models (Busan Cinema, Max IV, Sony Forest): GPL-3.0. brian-ho/intro-to-urban-data, dewbee, MetaMAP and augmented-carpentry: GPL-3.0. BHoM, SAM and Caribou: LGPL-3.0.
- Permissive but off-topic: the COMPAS robotics courses (compas-teaching, CRCL-EPFL, GKR workshops), compas_fab, Robots, Machina, compas_slicer, gh-sharp (a component dictionary), and Rhino.Inside.Revit examples (they need Revit).

## Gaps and suggestions

- **Gridshells, tensile structures, louvres and stairs**: the best files are unlicensed (Kangaroo-examples, jhorikawa). Ask the authors for an MIT/CC BY grant, or author these lessons in Almond yourself, using the accepted files only as pattern references.
- **Plugin-light first tier**: start with the runxel, nonoesp, VVD, marcsyp, baharmon and McNeel files. They are vanilla and need only annotation.
- **Second tier**: add compas_cem, the GKR and AFAB files, and danilnagy. These need `pip install compas compas_cem compas_timber` in Rhino 8 CPython, or Human, and the catalogue should document that.
- Selected files carry Rhino 6/7-era GhPython (IronPython). Re-save in Rhino 8 and check the script components before packaging.

## Downloaded corpus: how these definitions are built

All 95 accepted files were downloaded at their pinned commits, converted to XML
where they were binary (36 files, `tools/parametric_library/gh_convert.ps1`,
Rhino 8 GH_IO, archive-level only) and inspected with
`tools/parametric_library/ghx_inspect.py`. Nothing was opened in Grasshopper
or solved. The corpus itself stays outside the repository; only the ten files
used by `ParametricLibrary/` are tracked, under `ParametricLibrary/upstream/`.

| Measure | Value |
| --- | --- |
| Objects per definition | median 31, max 449 (compas_cem bridge) |
| Longest wire chain (dependency depth) | median 10, max 31 |
| Files with any group / any scribble | 69 / 52 of 95 |
| Files with no group and no scribble at all | 21 |
| Objects outside every group | median 71 % per file |
| Number sliders without a meaningful name (empty, "Slider", "x"...) | 478 of 793 (60 %) |
| Files with script components | 40 (32 legacy GhPython/IronPython, 10 Rhino 8 Python 3) |
| Files with clusters | 13 |
| Plugins referenced | GhPython 25, GSA 5, Human 3, SpatialSlur 2, Weaverbird 2, Kangaroo2 2, NGon 2, Tunny 2, one each: Clipper, VoxelTools, Bifocals, Pufferfish, HDTReference, LunchBox, Karamba3D |
| Third-party Python in scripts | compas (220 imports), compas_cem 176, compas_rhino 169, compas_timber 61 |
| Plugin-free and dependency-free | 55 |

Most common components: Number Slider (781), Panel (442), Number (414),
Scribble (308), Data (192), Curve (155), Relay (141), Custom Preview (139),
Point (125), Colour Swatch (118), Boolean Toggle (113), Move (95).

The architectural definitions nearly all share one pipeline:

1. **Inputs**: sliders, toggles and one referenced or internalised base geometry
   (surface, curve or footprint).
2. **Parameter space**: the base is subdivided, either in UV space
   (Divide Domain², Isotrim, Divide Surface) or along a curve (Divide Curve,
   Series).
3. **Field**: a per-element driver value, such as distance to an attractor,
   a Series, Remap Numbers over Bounds, or Random.
4. **Module**: one element is built (a fin, a hole, a paver, a floor plate) and
   copied onto every anchor with Move, Orient or Rotate.
5. **Output**: Loft, Extrude or Pipe, then Custom Preview with colour
   gradients, then bake.

What stops these files from teaching well:

- **Unnamed sliders.** 60 % carry no name.
- **Stray layout.** Logic is spread across the canvas with long backward
  wires.
- **Notes in the wrong place.** Notes, when present, explain implementation
  quirks rather than the design idea.
- **Unmarked results.** No marker shows which component is the result to bake.

`ParametricLibrary/` addresses exactly these points.
