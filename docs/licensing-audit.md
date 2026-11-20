# Licensing audit — what almond-mcp may and may not distribute

Audited 2026-07-14, when the standalone repository was created for
publication. Every content class in the project is listed with its origin,
license position, and distribution decision. `THIRD-PARTY-NOTICES.md` is the
user-facing summary; this file is the reasoning.

## Decision table

| Content | Origin | License position | Distributed? |
| --- | --- | --- | --- |
| Python server, CLI, retrieval store, ghx parser | self-authored | MIT (this repo) | yes — PyPI wheel/sdist |
| RhinoAlmondBridge C# source | self-authored | MIT (this repo) | yes — repo + compiled Yak package |
| Library manifests (IKEA, drawing, diagram) | self-authored metadata | MIT; facts about products/models are not copies of them | yes — bundled in wheel as `almond_mcp/data/` |
| Spatial contracts, generation plans, `SPATIAL_GENERATION_PLAN.md` | self-authored | MIT | yes |
| Karamba capsule manifests (`karamba_*.capsule.json`), capsule schema, AUTHORING.md | self-authored contracts | MIT | yes |
| Drawing recipes (`technical_axon.json`) | self-authored | MIT | yes |
| IKEA/context `.skp` model files | 3D Warehouse community uploads | 3DW ToU forbids stand-alone redistribution and aggregation for redistribution | **no** — gitignored, excluded from wheel/sdist |
| Drawing/diagram model files (`.svg`, `.skp`, `.png`) | manifests mark them `downloaded_asset`; three have no recorded source URL | provenance partly unknown → treat as non-redistributable | **no** — same exclusions |
| `Grasshopperfiles` (Karamba examples, Kangaroo examples, tent/tensile models) | karamba3d.com, Daniel Piker's Kangaroo examples, misc. | no redistribution grant (Karamba examples proprietary; Kangaroo examples repo has no license ⇒ all rights reserved) | **no** — kept out of the standalone repo entirely; local path via `RHINO_MCP_LIBRARY_DIR` |
| Karamba3D assemblies | Karamba3D GmbH, commercial | user-installed; bridge binds via reflection only | **no** |
| RhinoCommon / Grasshopper SDK | McNeel | MIT (RhinoCommon) / developer terms; referenced not shipped | **no** |
| Newtonsoft.Json, Roslyn, System.* DLLs | NuGet | MIT | yes — inside Yak package only, with notices |
| IKEA product names in manifests | public catalogue facts | nominative fair use; disclaimer in notices | yes (names only) |
| OpenSeesPy (benchmark reference solver, `benchmarks/`) | Univ. of California / Oregon State, PyPI `openseespy` | free for research, education and internal use; commercial redistribution of anything that imports it needs a licence (Dr. Minjie Zhu) | **no** — optional `bench` dependency group only; never imported by `almond_mcp`; `benchmarks/` is outside the wheel and sdist |
| Generated asset library (`GeneratedAssetfiles/models/*.glb` + `.almond.json` contracts) | generated with Meshy from self-authored prompts (`GeneratedAssetfiles/catalogue.json`), some with Higgsfield reference images, normalised by `tools/build_generated_assets.py` | Meshy Terms: output generated on a paid plan belongs to the account; Higgsfield claims no ownership of outputs; released here under CC BY 4.0 (manifest/contracts MIT) | yes — git repository, sdist, Rhino plugin archive and GitHub release assets; the wheel carries the manifest, catalogue and previews only, and installs download each model file from the GitHub release on first use (or `almond-mcp fetch-assets --generated`) |

## 3D Warehouse analysis

The [3D Warehouse Terms of Use](https://help.sketchup.com/en/3d-warehouse/3d-warehouse-terms-use-faq)
and General Model License permit using downloaded models, including
commercially, inside a *Combined Work* that adds substantial content — but
prohibit transferring models as stand-alone items and prohibit aggregating
content for redistribution. An asset library whose value is the models
themselves is precisely an aggregation, so bundling the `.skp` files in a
package would violate the ToU regardless of the package being free.

What ships instead is Almond's own metadata layer. Facts recorded about a
model (its title, publisher, URL, checksum, the real product's catalogue
dimensions) are not the model, and the spatial contract (anchor, footprint,
clearance, collision shape) is original work keyed to the real-world product,
not derived from the mesh. Users complete the library on their own machines
by downloading each model from its recorded source page —
`almond-mcp fetch-assets` automates the checking, never the downloading,
because 3D Warehouse requires each user's own Trimble sign-in.

Three drawing/diagram assets (`diagram-person-standing-1`,
`diagram-tree-deciduous-1`, `diagram-texture-brick-1`) are marked
`downloaded_asset` with **no recorded source URL**. Until their provenance is
recorded or they are replaced with self-drawn equivalents, they are treated
as non-redistributable and `fetch-assets` reports them as
"no recorded source URL". TODO: replace with original SVGs, then move them
into the distributable set.

## Generated (Meshy) asset library

`GeneratedAssetfiles/` is the one library whose model files *are*
distributed. Almost every asset was produced from a self-authored prompt: a
reference image (Meshy's own image models, or Higgsfield for batch 2 and the
Ginkgo batches) followed by Meshy image-to-3D on a paid plan. The exceptions
are listed under the Ginkgo batches below: six photo-derived Freiburg pieces and
three Tripo meshes. Meshy's terms grant
paid accounts ownership of generated output, and Higgsfield claims no
ownership of its outputs, so the files are ours to license. They are released under CC BY 4.0 (attribution: "Almond generated
asset library"), and the manifest, contracts and build tooling are MIT like
the rest of the repository. Provenance is recorded per asset in the manifest
(`geometry_source.parameters`: prompt, image task id, mesh task id, model,
date) and in `GeneratedAssetfiles/provenance.json`.

Starting with 0.6.0rc1, the wheel includes the generated GLBs, MIT contracts,
catalogue/provenance, passport schema and preview renders for offline use.
The release verifier checks an explicit allowlist: no 3D Warehouse models,
raw Meshy downloads, compiled bridge binaries or example projects. Earlier
versions used repository download URLs. 3D Warehouse content stays manual.

From the release after 0.7.0rc2 the wheel no longer includes the generated
GLBs and contracts (the library outgrew PyPI's 100 MB file limit); it keeps the
manifest, catalogue, provenance, source register and previews. The model files
are attached to the GitHub release of the same version, and an install
downloads each one from there on first use, checked against the manifest's
SHA-256 (`almond_mcp/model_store.py`). They are the same CC BY 4.0 files, so
attribution travels with the manifest and contracts as before. The release
verifier refuses a wheel that contains any GLB or contract. The sdist, the Rhino
plugin archive and the repository still carry the model files.

The generation evidence in `GeneratedAssetfiles/batches/` (per-asset request
records and the input images the providers received) is not in the wheel,
which keeps it under PyPI's 100 MB file limit. It ships in the sdist (attached to
the GitHub release; too large for PyPI, which gets the wheel only), in the
Rhino plugin archive (`evidence/batches/`) and in the repository. The manifest's
`input_image_file` paths are relative to `GeneratedAssetfiles/` in those copies.
The release verifier refuses a wheel that contains `batches/` and checks every
captured input image's SHA-256 against the sdist.

Raw Meshy downloads (`GeneratedAssetfiles/raw/`) are gitignored; the tracked
normalised files are derived from them deterministically.

### Ginkgo props (batch `ginkgo-refset-1024`, added 2026-11-05)

Sixteen props generated for the owner's Ginkgo world pass `refset_1024`
(building services, household and interior objects) were re-derived as library
geometry. Each came from an original descriptive prompt rendered by Higgsfield
`gpt_image_2_5` on the owner's account, then uploaded to Meshy 7.1 image-to-3D
on the owner's paid account. No photographs, third-party images or marketplace
models were submitted; the owner's scene photographs for that pass were never
uploaded. The owner approved the CC BY 4.0 release on 2026-11-05, knowing the
same props also appear inside the owner's paid GRANDWHIS world packs.

Deliberately excluded: the Tripo H3.1 condenser (generated via Higgsfield; that
rights route has not been reviewed), the four assembled W063–W066 scenes (paid
products, and scenes rather than placeable objects), and discarded or
earlier-pass meshes. The library editions carry Almond materials only; the
provider's PBR textures are not distributed. The retained reference images
ship in `batches/ginkgo-refset-1024/` as generation evidence.

### Ginkgo mesh bank, Freiburg and refset_1118 (three batches, added 2026-11-18)

Eighteen further Ginkgo meshes, approved by the owner for the CC BY 4.0 library
on 2026-11-18, came by three rights routes:

- `ginkgo-meshbank-2026-11` (7 cafe and street props): original text prompts,
  Meshy `nano-banana` text-to-image, then Meshy 7.1 image-to-3D, all on the
  owner's paid Meshy account. No external images.
- `ginkgo-freiburg-2026-11` (2 facade ornaments, 3 fountain statues, 1 Gothic
  canopy): Meshy image-to-image received crops of the **owner's own
  photographs** of a Freiburg facade (1890s) and of the Fischbrunnen fountain
  (15th century). The clean generated image then went to Meshy 7.1. The designs
  reproduced are long out of copyright. The photographs are hashed in the
  evidence but never distributed. The current monument's restoration history
  (later copies of the figures) was not audited.
- `ginkgo-refset-1118` (taxi, refuse truck, vending machine, palm, shrub clump):
  Higgsfield `gpt_image_2_5` reference images, each conditioned on one of the
  owner's own approved concept images. Then either Meshy 7.1 (palm, shrub) or
  **Tripo H3.1 through the owner's Higgsfield account** (taxi, truck, vending
  machine). The refset_1024 batch left Tripo output out because that route was
  unreviewed. For these three, the owner confirmed the rights in the Ginkgo pass
  and approved their CC BY 4.0 release. Tripo's terms were not independently
  audited.

As before, only the re-derived untextured geometry with Almond materials ships,
plus the reference images as evidence. No provider textures, photographs or
assembled GRANDWHIS scenes. The Freiburg scene copies of people, bicycles and
the lamp were left out: they are scene-baked copies of older mesh-bank meshes,
and the originals are in the mesh-bank batch.

### Project Y2K props (three batches, added 2026-11-20)

On 2026-11-20 the owner approved adding models used in the owner's Project Y2K
game, "except for the operatives and bosses", to the CC BY 4.0 library. Twelve
were imported, all generated from the owner's own sessions on the same Meshy
account as the rest of the library (account ID in the result URLs):

- `y2k-props-v038` (bin-bag heap, cardboard stack, ivy clump, rubble pile):
  Meshy-6 **text-to-3D** (preview + refine), 2026-09-23, in a Ginkgo session for
  pass refset_0923, and reused unchanged in Y2K. Text prompts only.
- `y2k-trees-refset-0923b` (red maple, green broadleaf): Higgsfield
  `gpt_image_2_5` images from text prompts (no media references), uploaded to
  Meshy-7 image-to-3D, 2026-09-24.
- `y2k-twofronts-2026-09` (planter pod, capsule vending machine, egg kiosk,
  holo sign pod, hover scooter, hover car): Meshy-6 text-to-3D, 2026-09-06, the
  Meshy account's first recorded use. **Whether that account was on a paid plan
  on 2026-09-06 is not recorded** (Y2K's MESHY_NOTES gives only the 3,320-credit
  balance and an empty task list), so paid status is not asserted for this
  batch. The owner should confirm the plan; Meshy's ownership grant to paid
  accounts is the basis this audit relies on elsewhere.

No images were given to the text-to-3D tasks, and none to the tree image jobs;
the Ginkgo passes' owner reference sets were never submitted. The vehicles are
speculative designs (no wheels, no maker's styling or marks). Excluded by rule:
operatives and their drones, bosses, the needle pistol, the pod building
(building-scale), Ginkgo's `tree_green_wild` (never used in Y2K) and every
decimated, remeshed or conditioned derivative (`_lp`, `model_merged.obj`,
`SM_*` FBX, the 20k GLB conversions). Only untextured re-derived geometry with
Almond materials ships; Meshy's texture maps are not distributed (the
cardboard-stack texture has small printed patches, which therefore never ship).

### Ginkgo props reused in Project Y2K (four batches, added 2026-11-20)

On 2026-11-20 the owner chose a second Y2K group, Ginkgo props that Project Y2K
content v061 placed in its hub, under the same CC BY 4.0 approval. Thirteen were
imported:

- `ginkgo-refset-1003` (inflatable-cushion lounge chair, strapped water bladder,
  pressure canister) and `ginkgo-refset-0924` (plaster statue): Higgsfield
  `gpt_image_2_5` images from text prompts, Meshy-7 image-to-3D.
- `ginkgo-refset-1007` (rooftop water tanks, six-wheeled rover, capsule tram,
  drone, drone launcher vehicle, shuttle, planter box, flower clump): reference
  images conditioned on the pass's own text-only concept art, then **Tripo H3.1
  through Higgsfield** (six) or Meshy-7.1 (two). The Tripo terms and the
  Higgsfield entitlements are not independently audited; the owner approved these
  Tripo models by name.
- `ginkgo-lausanne-market` (dress form): Meshy-6 text-to-3D.

The Ginkgo passes' own approvals (refset_1003 2026-10-03, refset_1007 2026-10-07)
covered the GRANDWHIS packs only; the library release rests on the 2026-11-20
approval. **Design proximity.** The refset_1003 and refset_1007 prompts were
written from owner reference sets of third-party photographs and artworks (never
uploaded to a generator, never distributed). Each generated image was compared
with them: the cushion lounge chair shares a material kit with a designer stool
but not its form, and the rover and capsule tram share subject and colourway
with two concept artworks but not their forms; these were imported with the
comparison recorded and **the owner should confirm them**. Excluded: the
refset_1003 pack unit and cube rover (close copies of a collectible backpack and
a rover concept) and the lander (replica of a handmade artwork); the refset_1007
AC unit (the condenser family the owner left out) and habitat module (building
scale, stair); the Lausanne bike (duplicate), pigeon (creature) and walking and
sitting figures; the inflatable bear (character art); every LOD and Y2K `SM_GK61`
derivative. The shuttle and launcher were checked for armament (none). Only
untextured re-derived geometry ships.

### Project Y2K procedural kit pieces (four batches, added 2026-11-20)

On 2026-11-20 the owner chose a third Y2K group, the procedural kit pieces, under
the same CC BY 4.0 approval. Thirty were imported: street furniture (street kit
v004), market and yard props (district kit v016), facade and rooftop services
(megastructure kit v020), and Mirai Ward street details, a lantern shrine and
two commuter railcars (world v040). They are the owner's own project geometry:
Blender scripts in the Project Y2K repository build every piece from primitives
(no imported, provider or third-party geometry), and the scripts were written
in the owner's Claude Code sessions where a session is recorded (the street kit
script's authoring session was not found). No generator account or credits are
involved. The scripts and kit records ship as evidence text with local paths
redacted; kit colours and textures do not ship (Almond materials only).

**Lettering and marks.** Three street pieces carried tessellated lettering from
Blender's built-in font ("01", "RELAY" / "ACCESS", "NEON GATEWAY"); it was
removed as a recorded edit, so no glyph geometry ships. The lead railcar's
destination-board decal quad (a lettered texture) was removed too. **References.**
The megastructure kit was "modelled in Blender from the owner's 2026-09-19
reference images": six third-party renders and photographs of dense city towers
the owner pasted into the session (hashed, never distributed). The five pieces
imported from it (satellite dish, AC unit stack, pipe riser, scaffold bay,
antenna cluster) are generic assemblies of boxes and tubes; **the owner should
confirm** this group. The shrine is a generic torii-and-lantern street shrine,
not a model of a specific shrine; the railcars are generic, with no operator
livery or marks. Excluded: the drain grate, square pillar, catwalk and stair,
overhead cable, blank neon sign, blimp, cargo airship, ad balloon and sign drone
(their billboard textures may show operatives), the sky gondola and cable, the
ten Chinese neon signs (glyphs from Windows system fonts, whose licences do not
clearly allow redistributing outlines), game pickups (the ammo cell is
weapon-adjacent), jump pad, parkour and FX meshes, and every building-scale,
wall, ground or road module.

## Capsules vs. example files

A capsule manifest declares an input/output contract (reserved
`ALMOND_IN_*`/`ALMOND_OUT_*` nicknames, types, units, semantics) for a
Grasshopper definition. The manifests were written for this project; they do
not embed any third-party definition. The `definition_file` they name is
supplied by the user (or authored per `capsules/AUTHORING.md`), so shipping
the manifests is analogous to wasp-mcp shipping factual pattern knowledge
derived from examples without shipping the examples.

## Commercial distribution: environment engine, constructions, code packs, panel (2026-11-03)

Goal: the Python package and the Rhino plugin can be sold without third-party IP problems.

| Content | Origin | Licence position | Distributed? |
| --- | --- | --- | --- |
| Environment engine (`almond_mcp/environment/*.py`), panel workspace (`library_ui/environment.*`, `EnvironmentWorkspace.cs`) | self-authored; methods implemented from cited papers and standards (no code from Ladybug/Honeybee, Radiance, EnergyPlus, ClimateStudio) | MIT | yes |
| Material λ/ρ/c, glass optics | EnergyPlus v26.2.0 `datasets/` (ASHRAE HOF, WINDOW glass library) | EnergyPlus licence, BSD-style: redistribution permitted with the notice; the name EnergyPlus may not be used for the product | yes, with `LICENSES/EnergyPlus.txt` and the notice |
| Generic reflectances | honeybee-standards v2.0.7 | MIT | yes, with notice |
| DE age-band U-values | BAnz AT 04.12.2020 B1 | official work, Section 5 UrhG (no copyright) | yes, cited |
| EU stock U-values | Hotmaps building-stock (TABULA-based) | CC BY 4.0 | yes, attributed |
| England AD L limits / notional fabric | Approved Document L 2021 (2023 amendments) | OGL v3.0 (licence statement in the document) | yes, attributed |
| Singapore ETTV/RETV/RTTV | BCA Code on Envelope Thermal Performance | BCA terms: no reproduction without written permission; formulas are a method | method only - CF and SC computed by Almond; users may load their own licensed tables at run time (never bundled) |
| Assembly build-ups, finishes, frames, room-use profiles | self-authored assumptions | MIT | yes, labelled `almond-own` |
| Aalborg 2021 materials table | Johra, DCE Technical Report 289 | CC BY-SA 4.0 (ShareAlike would bind merged data) | **no** - not bundled; a user-side import (never merged) is a possible follow-up |
| honeybee-energy-standards, IGDB, bauteilkatalog.ch, SS / EN / ISO / Eurocode tables | various | AGPL / CC BY-ND / proprietary / paid standards | **no** |

Enforcement: `tests/test_rooms_constructions.py::test_library_provenance_and_licences` fails when a bundled
value lacks a source or a source's licence is not on the allow-list; `tools/license_scan.py` checks the
Python dependency closure, the plugin's NuGet packages, vendored UI files and the data sources, and
`tools/verify_release.py` refuses a wheel when it reports anything denied or unknown. Scan result at
this commit: 0 denied or unknown; to review: certifi (MPL-2.0, used unmodified as a dependency - fine)
and the BCA method citation (no data shipped).

Trademarks: product names (ClimateStudio, Ladybug Tools, Radiance, EnergyPlus, LEED, Green Mark) appear
only nominatively in documentation and result notes, with a non-affiliation statement; no logos, no
third-party names in product or command names, no certification wording (Singapore results say
"indicative; not a BCA Green Mark assessment", daylight references say "not a LEED assessment").

Open permission requests worth sending before launch (none is needed for the current scope):
- BCA - permission to bundle the ETTV/RETV tables (CF, SC, material k-values) for a table-based figure.
- Enterprise Singapore - SS 553 design conditions as defaults (currently user inputs).
- DESNZ / BRE - SAP 10.2 tables, if a UK SAP-style module is wanted.
- IWU - TABULA data directly (currently via CC BY Hotmaps).
- ABCB / MBIE - none needed (CC BY 4.0); Australian NCC and NZ H1 packs are planned, not yet keyed.

This audit is an engineering record, not legal advice: have counsel review it before commercial launch.

## Rebuild triggers

Re-run this audit if any of these change:

- a model file is added to any `models/` directory (record provenance in the
  manifest at the same time);
- `Grasshopperfiles` content is referenced by a distributed artifact;
- the bridge gains a NuGet dependency (extend the Yak notices);
- `almond_mcp` (or anything shipped) starts importing `openseespy`, or `benchmarks/` is added to
  the sdist/wheel;
- a generated asset is regenerated or re-prompted (update `provenance.json` and
  rebuild the manifest so task ids and checksums stay truthful);
- Almond starts shipping generated geometry derived from 3D Warehouse meshes
  (bounding boxes computed from a mesh are fine; simplified copies of the
  mesh are not).
