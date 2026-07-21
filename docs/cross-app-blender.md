# Cross-application workflow: Blender ↔ Rhino (and onward to Unreal)

Findings from a live proof run on 2026-07-16 (Blender 5.1.2 headless,
Rhino 8 + almondbridge 0.2.3, almond-mcp 0.4.0). The goal: test whether
Almond's semantic layer can move assets *between* applications rather than
only driving one.

## The architecture this validates

Almond already separates concerns in the way a software-agnostic system
needs:

```
         Claude  +  almond-mcp server        <- semantic layer: ledger,
              |                                 material library, spatial
              |                                 contracts, validation
      +-------+--------+---------------+
      |                |               |
  Rhino bridge    Blender bridge   (Unreal, ...)     <- thin executors
  (TCP 5000)      (TCP 5001, TBD)
```

Only the *executors* are application-specific. Nothing in the scene ledger,
the material library, or the placement contracts knows what Rhino is. A
second application therefore needs a bridge, not a second Almond.

Two transport options for a Blender bridge, both proven feasible here:

1. **Headless invocation** (used in this test): the server runs
   `blender --background --python <generated script>`. No addon to install,
   works today, but no live session state.
2. **Persistent addon** (the eventual match to RhinoAlmondBridge): a small
   Blender addon opening a socket on 127.0.0.1:5001 speaking the same JSON
   protocol, so both apps stay open and Claude drives them simultaneously.

## What the live proof did

1. Blender built a parametric slatted bench (1800 x 450 x 450 mm), assigned
   materials named `ALMOND::wood-oak` / `ALMOND::steel-painted-sage` with
   PBR channels matching the Almond library, tagged objects with `almond:*`
   custom properties, and exported GLB + a sidecar JSON *spatial contract*
   (dimensions, anchor, clearances, collision shape - the same shape the
   curated libraries use).
2. Rhino imported the GLB through the existing bridge.
3. Almond re-attached semantics and placed the bench per its contract
   (bottom_center anchor on the floor, centred under a canopy archetype).

## Empirical findings (the useful part)

| What transfers | Result |
| --- | --- |
| Geometry + dimensions | **Exact.** 1800 x 450 x 450 mm measured in Rhino, matching the Blender contract to 0.1 mm |
| Material *identity* | **Survives** via the `ALMOND::<material_id>` naming convention - the reliable carrier |
| PBR channels (metallic/roughness) | **Survives** (0.85/0.45 and 0.0/0.65 arrived intact) |
| Base colour | **Drifts.** Oak 200,170,130 arrived as 228,212,188; sage 150,170,120 as 200,212,181 - a linear→sRGB double conversion in the import |
| `almond:*` metadata (glTF `extras`) | **Dropped entirely** by Rhino's glTF importer |
| Material instancing | **Proliferates** - the importer created a separate material per mesh instead of sharing one per definition |

The two failures are exactly why the semantic layer belongs in Almond and
not in the file. Because Almond knows the `material_id`, it can:

- **restore** the `almond:*` metadata after import (reconstructed from the
  surviving material name - 7/7 objects in the test);
- **correct** the colour drift by re-applying canonical library values;
- **place** the asset correctly because the spatial contract travelled
  beside the file rather than inside it.

File formats lose meaning; the ledger keeps it. That is the whole thesis of
[Ginkgo](../../Builiding0/Ginkgo/README.md) demonstrated in miniature.

## Design implications for a real integration

- **Interchange currency:** GLB for geometry + PBR, plus a sidecar JSON
  contract for everything the file cannot carry. Never rely on `extras`.
- **Material naming is the join key.** `ALMOND::<material_id>` in every
  app, `ue_material_slot` for Unreal. Keep the manifest the single
  authority for actual values.
- **Deduplicate on import.** One material per `material_id`, then reassign;
  otherwise every round trip multiplies material assets (this is also what
  degrades Unreal shader compilation and batching).
- **Sync display colour from the material** so Shaded/Wireframe views read
  correctly, not just Rendered.
- **Units and anchors are contract fields, not conventions.** Blender works
  in metres, Rhino documents vary; the contract carries mm explicitly and
  the placement resolves against the target document's unit system.
- **Direction is symmetric.** Rhino→Blender is the same pipeline with the
  exporters swapped: Almond exports selected objects as GLB with the
  contract, Blender imports and re-attaches custom properties from the
  material names.

## Status

This was a proof, not a shipped feature. What exists today: the material
library, `assign_material`, and the metadata convention (v0.4.0). What a
`blender_exchange` feature would add: an `export_asset_contract` tool on
the Rhino side, an `import_asset_contract` tool that runs the restore +
place + dedupe sequence, and a Blender-side addon or headless invoker.
