# City kit: the Almond district workflow

A reusable, city-scale test workflow: four blocks, ten buildings across
five construction systems, all detailed by one shared kit so the
architectural language stays consistent while every typology keeps its
own structural logic. Built and verified live 2026-08-30 (3,700+ objects,
fresh mm document).

## The pipeline (per building)

```
get_construction_guidance   -> spans, depths, spacings for the system
kit functions               -> punched_windows / curtain_band / balcony /
                               stair_core / entrance / parapet / street_lamp / tree
assign_material (+roles)    -> construction intent stamped on the objects
validate_structure/capsule  -> one span group per system (<= trial cap)
check_egress                -> exits, separation, widths per building
get_typology_narrative      -> lineage paragraphs for the district dossier
```

## Running it

Rhino 8 open with an (ideally empty) millimetre document, bridge on 5000:

```bash
uv run --no-sync python examples/city_kit/district_driver.py A   # north blocks
uv run --no-sync python examples/city_kit/district_driver.py B   # south blocks + urban
uv run --no-sync python examples/city_kit/district_driver.py C   # materials, checks, dossier, captures
```

State (GUID map `district_guids.json`, `district_dossier.md`, PNG
captures) lands in `%TEMP%/almond_district` or `$ALMOND_DISTRICT_SCRATCH`.

## What the 2026-08-30 run proved

- **Consistency at scale**: one 3 m facade module, one core detail, one
  entrance/balcony/parapet vocabulary across concrete flat-plate housing,
  steel towers on a podium, masonry terraces, glulam mid-rise, a trussed
  market hall and a timber library.
- **Validation per system** (Karamba api, high confidence): I-joists 6 m
  member-basis, glulam 6 m, 24 m hall truss extent-basis - each fitting
  its construction-library system.
- **Flat plate** via the shell capsule: 55 mm under -3.9 kN/m² on the
  template section.
- **Egress caught a real failure**: the market hall's 515 assembly
  occupants exceed the 500-person tier -> 3 exits required, 2 provided.
  A third (west) exit was added and the recheck passed 4/4.
- **Narration layer**: each block captioned from `get_typology_narrative`
  (courtyard-house-city, steel-frame-tower, dense-roof-access-settlement,
  timber-bracket-hall, civic-hall-on-piazza) into `district_dossier.md` -
  narration never drove geometry.

## Known constraints

- Karamba **trial license**: <= 20 beam elements per solve (counts can
  double internally - keep validation sets to ~6-10 lines), shell meshes
  <= ~5x5 faces, Large Deformation (gridshell capsule) unusable headless.
  A licensed Karamba lifts all of this.
- Bridge script calls cap at 60 s unless the request carries `timeout_s`.
- First Grasshopper boot in a Rhino session takes minutes; warm after.

## Picking up in a new conversation

1. Rhino open, bridge alive (`AlmondMCPStatus`), repo at
   `C:\Users\liang\OneDrive\Documents\almond-mcp`.
2. Session memory (`construction-knowledge-layer` memory file) carries the
   state; this README carries the workflow.
3. Extend by adding kit functions (roof gardens, arcades, bay windows...)
   or new blocks - keep the phase pattern and the per-system validation.
