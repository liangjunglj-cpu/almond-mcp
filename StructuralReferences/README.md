# Almond structural reference library

Twelve benchmarked building typologies as parametric line models, usable from the Almond
MCP tools and in Rhino. They are the models Almond's native frame solver is verified
against: closed forms in `tests/test_structural_typologies.py` (method of joints, virtual
work, the force method, funicular statics) and OpenSees cross-checks in `benchmarks/`.
A reference run therefore shows what a *correct* `validate_structure` result looks like
for a typology, with the benchmark's own loads, before a user's geometry is checked
against the same engine.

| id | title | family | planar | closed form |
| --- | --- | --- | --- | --- |
| `moment-frame` | Rigid moment frame | frame | | |
| `braced-tower` | Braced tower | tower | | |
| `pratt-truss` | Pratt truss | truss | yes | method of joints, virtual work |
| `portal` | Pinned-base gable portal | frame | yes | force method |
| `warehouse` | Portal-frame warehouse | hall | | |
| `space-grid` | Double-layer space grid | roof | | |
| `arch` | Parabolic arch | arch | yes | funicular statics |
| `l-bracket` | L-shaped cantilever | cantilever | | bending + torsion |
| `canopy` | Cantilever canopy | cantilever | | |
| `diagrid` | Cylindrical diagrid tower | tower | | |
| `vierendeel` | Vierendeel girder | truss | yes | |
| `mixed-supports` | Frame on six support types | frame | | |

## Files

| Path | What |
| --- | --- |
| `catalogue.json` | Titles, what each reference exercises, parameters with ranges and defaults, sections, the default study, supports, verification, related capsules and parametric definitions, teaching notes |
| `almond_mcp/structural_references.py` | The builders (moved from the test suite; `tests/structural_typologies.py` re-exports them), the frame-to-model conversion, closed-form checks, analysis and the Rhino placement script |

Everything here is Almond's own and MIT licensed; nothing is downloaded.

## How a reference becomes an Almond model

1. The builder makes a `frame_solver.Frame` in SI (m, kN): S355 steel, hollow sections,
   supports, G/Q member and nodal loads, wind.
2. `to_model` writes the **same conditioned-model JSON the Rhino bridge exports**: one
   member per element with its SectionSpec, `release` words for bars (`bar`) and pin-ended
   beams (`hinged`), typed `supports` in the `almond:support` grammar (or plain
   `anchor_points` when every support is fixed or pinned), and `loads`: the benchmark's G and
   Q loads as nodal forces and member line loads. Wind is dropped (Almond checks gravity
   combinations with a sway imperfection) and said so.
3. Planar textbook models (Pratt, portal, arch, Vierendeel) become 3D: supports restrain y,
   every other node gets a `lateral-y` restraint (the deck or bracing a planar truss relies
   on) and bars become `hinged` (pin-jointed in the plane, continuous in plan). In-plane
   statics are unchanged, which the closed-form checks confirm.
4. `native_structure.validate` analyses the model exactly as `validate_structure` does for
   Rhino geometry (EN 1990 combinations, EN 1993-1-1 member checks, stability).

## In Almond (MCP tools)

```text
list_structural_references(query="truss")
get_structural_reference("pratt-truss", parameters={"span": 24})
analyze_structural_reference("pratt-truss", parameters={"span": 24}, detail=True)   # no Rhino needed
place_structural_reference("pratt-truss", parameters={"span": 24}, x_mm=0, y_mm=0)   # draws it in Rhino
validate_structure(guids=<member_guids + support_guids>, **rhino.validate_structure)
```

`analyze_structural_reference` returns `validate_structure`'s result plus a `reference`
block: parameters, counts, loads applied, support types, conversion notes and `checks`
(the run against the benchmark frame and, where one exists, the textbook value).
`place_structural_reference` draws members with `almond:section`, `almond:release` and
support points with `almond:support` user text, and names the nearest `validate_structure`
call: the bridge exports geometry, sections, releases and support points but not loads, so
the reference's variable loads become one `load_kn`. Resources:
`almond://structural/catalogue` and `almond://structural/{id}/model`.

Some references fail honestly at their defaults: the canopy (deflection) and diagrid
(ring-beam utilization) are sizing exercises, and the warehouse's slender X-bracing
diagonals govern once Almond checks each bar as a compression member. The catalogue's
teaching notes say what to change.

## Adding a reference

Write the builder in `almond_mcp/structural_references.py` (return `{"frame": Frame,
"combos": {...}}`, hollow or solid sections only), add it to `ALL`, and describe it in
`catalogue.json` (`builder` = the function name; every parameter with type, range and
default; the default study; supports; verification). `tests/test_structural_references.py`
checks that every catalogue entry builds, converts, analyses and keeps its closed form.
