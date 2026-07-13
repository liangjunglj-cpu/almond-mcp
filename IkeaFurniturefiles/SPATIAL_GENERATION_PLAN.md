# Spatial Metadata and Generation Plan

## Shared asset contract

Every asset, whether downloaded or generated, must contain:

- `geometry_source.type`: `downloaded_asset` or `primitive_generated`
- millimetre-based asset-local coordinates with Z up
- a stable `bottom_center` anchor
- a conservative local AABB
- a 2D floor footprint
- front, back, left, and right functional clearances
- collision shape and placement priority
- bounds source and measurement status

Catalogue dimensions are nominal. Rhino measures the actual geometry after
first import or generation and changes `geometry_bounds_status` from
`pending_rhino_measurement` to `measured`.

## Placement and collision workflow

1. Inspect room boundaries, walls, openings, and door swings.
2. Transform asset footprints and oriented boxes into world coordinates.
3. Use AABBs for broad-phase rejection.
4. Use oriented boxes or footprint polygons for narrow-phase validation.
5. Include functional clearance envelopes in a separate test.
6. Keep user-locked objects fixed.
7. Move the lowest-priority object through nearby translations, wall zones,
   and rotations.
8. Score valid candidates by circulation, wall alignment, functional grouping,
   and distance from openings.
9. Return `no_valid_layout` when no collision-free candidate exists.

## Primitive generation

Primitive-generated assets use the same contract as downloaded blocks.

1. Search the downloaded library first.
2. Generate a primitive only when the user permits fallback generation.
3. Record generator name, version, deterministic parameters, materials, and
   source hash.
4. Create the object around the standard anchor.
5. Measure its real Rhino geometry and derive its footprint.
6. Register it as a reusable block asset.
7. Apply category clearances.
8. Validate physical collisions and functional clearances before placement.
9. Label it clearly as generated rather than IKEA-authored.

## Proposed AlmondMCP tools

- `inspect_room`
- `measure_asset_bounds`
- `validate_furniture_layout`
- `resolve_furniture_collisions`
- `lock_furniture_position`
- `generate_primitive_asset`
- `place_asset`
