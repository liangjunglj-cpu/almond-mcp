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

## Capsules vs. example files

A capsule manifest declares an input/output contract (reserved
`ALMOND_IN_*`/`ALMOND_OUT_*` nicknames, types, units, semantics) for a
Grasshopper definition. The manifests were written for this project; they do
not embed any third-party definition. The `definition_file` they name is
supplied by the user (or authored per `capsules/AUTHORING.md`), so shipping
the manifests is analogous to wasp-mcp shipping factual pattern knowledge
derived from examples without shipping the examples.

## Rebuild triggers

Re-run this audit if any of these change:

- a model file is added to any `models/` directory (record provenance in the
  manifest at the same time);
- `Grasshopperfiles` content is referenced by a distributed artifact;
- the bridge gains a NuGet dependency (extend the Yak notices);
- Almond starts shipping generated geometry derived from 3D Warehouse meshes
  (bounding boxes computed from a mesh are fine; simplified copies of the
  mesh are not).
