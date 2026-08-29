# Construction-system guidance: real assemblies, not arbitrary members

Why Almond v0.6 adds a construction knowledge layer, where its numbers come
from, and how it threads through `get_construction_guidance`,
`validate_structure`, and `assign_material`.

## The problem it solves

Karamba validation (see [structural-validation.md](structural-validation.md))
tells you whether a set of members *solves* — deflection, utilization,
reactions. It cannot tell you whether the members correspond to anything a
builder would recognize: a 15 m sawn-lumber joist can pass FEA if you make it
deep enough, but it is not a thing that exists. The construction library closes
that gap with curated knowledge of how structural systems are actually formed:
which material, which element roles, what spans and spacings are real, and
what member depth a given span implies.

## Source and honesty

Parameters are distilled and paraphrased from **Francis D.K. Ching,
*Building Construction Illustrated*, 4th ed. (Wiley, 2014)** — each system
entry carries `bci_ref` section numbers. They are the book's preliminary-sizing
rules of thumb (e.g. steel beam depth ≈ span/20, wood joist depth ≈ span/16,
open-web joist span ≤ 24 × depth), intended for design plausibility, **not** a
substitute for engineering analysis or the governing code. The manifest states
this in its `source` field and every `construction_check` repeats it.

## The library

`Constructionfiles/manifest.json` — 23 systems across four categories:

| Category | Systems |
| --- | --- |
| floor | wood joist, wood I-joist/trussed joist, plank-and-beam, steel wide-flange, open-web steel joist, light-gauge steel joist, one-way slab, one-way joist (pan) slab, flat plate/flat slab, waffle slab, precast hollow-core, precast tees |
| wall | wood platform framing, cast-in-place bearing wall, concrete column grid, reinforced CMU, steel column frame |
| roof | steel rigid frame, steel trusses, space frame, wood rafters, wood trusses |
| foundation | concrete shallow foundation (spread footings / walls / slab on grade) |

Each system entry:

- `structural_material` — `validate_structure`'s material vocabulary
  (`Steel`, `Concrete`, `Wood`; `S355` is normalized to Steel).
- `structure_types` — which `validate_structure` templates the system maps to.
- `render_material_ids` — Materialfiles PBR ids, so the declared construction
  material is *visible in Rhino* and survives GLB/Datasmith export.
- `span_range_m` — real span range (for `category: wall`, `span_axis` is
  `"vertical"` and the range is unsupported height).
- `depth_rules` — `depth ≈ span / span_ratio` rules per element.
- `typical_spacing_m`, `elements` (role + guidance), `construction_notes`,
  `bci_ref`, `tags`.

The manifest also ships `reference` tables: occupancy live loads (kPa) and
material densities (kg/m³) from BCI appendix A.06–A.07, for choosing
`load_kn` inputs honestly.

Every parameter is itemized with its exact BCI section title and page in
the generated **[construction spec register](construction-spec-register.md)**
(`tools/build_spec_register.py` regenerates it from the manifest).

## The workflow

```
get_construction_guidance(material="Wood", structure_type="beam", span_m=4.5)
        │  pick a system; size members from depth/spacing rules
        ▼
execute_rhino_script          — generate members at real sections/spacings
        ▼
assign_material(guids, "wood-oak",
                structural_role="joist",
                construction_system="wood-joist-floor")
        │  stamps almond:structural_role / almond:construction_system /
        │  almond:structural_material user text on the objects
        ▼
validate_structure(guids, "beam", load_kn, "Wood")
        │  Karamba pathway as before, PLUS construction_check appended:
        │  which curated systems cover this structure_type/material,
        │  fits_span per system, suggested depths, and a warning when the
        │  span is outside every curated system's range
```

`construction_check.warnings` are also merged into the response's top-level
`warnings`, so an implausible-as-drawn structure is flagged even when the
solver passes it.

## Egress checking

`check_egress` turns the manifest's egress rules into one verdict pass:
occupant load from plate area and occupancy, required exit count (tiers +
the multi-story minimum of two), exit separation against the plate
diagonal, total and per-exit egress widths, and optional measured travel
distances and dead-end lengths. Each check names its requirement, the
provided value, and its basis, so a failing layout says what to fix (add
an exit, move a core, widen a stair). IBC-typical numeric factors are
labeled as such and the response repeats the verify-governing-code note.

## Rhino-side metadata

`assign_material` with the new optional parameters writes, alongside the
existing PBR keys:

| User text key | Example |
| --- | --- |
| `almond:structural_role` | `joist`, `girder`, `stud`, `truss_chord` |
| `almond:construction_system` | `wood-joist-floor` |
| `almond:structural_material` | `Wood` (from the system entry) |

If the chosen `material_id` is not among the system's typical
`render_material_ids`, the assignment still applies but the response carries a
warning — stating materials clearly beats silently accepting a mismatch.

## Verified behavior (2026-08-29)

- 23 systems index at server start (`Indexed 23 construction systems.`).
- `get_construction_guidance(material="Wood", structure_type="beam", span_m=4.5)`
  → 4 systems, all `fits_span: true`, wood joist suggested depth 281 mm
  (= 4500/16).
- `assess_span("beam", "Wood", 15.0)` → warning: outside the typical range of
  every curated Wood beam system (correct: that span wants glulam,
  trusses, or steel).
- `assess_span("truss", "Steel", 20.0)` → open-web joists, steel trusses and
  space frames all fit; no warnings.
- Full test suite: 48 passed (`tests/test_construction.py` covers manifest
  validity, material-id cross-links to Materialfiles, filtering, span
  assessment, and metadata script generation).

## Companion narration layer (prong 2, built 2026-08-30)

`Historyfiles/manifest.json` + `get_typology_narrative`: 18 typology
narratives distilled from Ching/Jarzombek/Prakash, *A Global History of
Architecture* — precedents, eras and urban roles, cross-linked to
construction-system ids and page-referenced (`gha_ref`, matching
[reference/gha_toc.txt](reference/gha_toc.txt)). NARRATION ONLY by
contract: entries caption and contextualize designs (the perimeter block's
Hof lineage, the ger behind every membrane roof); they never drive
geometry — that is the construction library's job. Page-indexed TOCs of
both volumes remain in [reference/](reference/) for deep reading.
