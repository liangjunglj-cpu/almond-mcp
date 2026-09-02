# Almond Tenshu - techno Japanese castle, aggregated outwards

Remodel of the infinity castle (2026-09-03) after the user's reference
images: Japanese castle massing in a dense techno-megastructure style.

## Massing (Japanese) x style (techno)

- **Battered ishigaki** stone bases everywhere (stepped 0.55H batter) -
  under the tenshu, every wall run, every yagura and gatehouse flank.
- **6-tier tenshu** whose stepped roofs flare OUTWARD: 3 shrinking slabs +
  pitched eave skirts per storey, vermilion soffit strips under every
  eave, white neon lines along every eave edge, ridge finials.
- **Aggregated outwards**: honmaru (+/-48 x 42 m) -> ninomaru (72 x 64) ->
  sannomaru (98 x 88) wall rings with corner yagura shrinking outward
  (0.5 / 0.38 / 0.30 scale mini-tenshu - the fractal read), a south
  gatehouse chain (3 gates + east gate), annex terrace wings E/W, and an
  approach bridge with neon edges.
- **Reference palette**: `steel-painted-charcoal` bodies (new library
  material), `aluminium-anodized` + `plaster-white` panel inlays,
  `steel-painted-vermilion` accents/soffits/doors (new), stone
  `concrete-boardformed`, greeble ribs + pipes `steel-galvanized`,
  white neon (`glow` batches) + orange neon (`gloworange`: lanterns,
  ring fins, apex). Panel patterns are deterministic (`det()` hash).
- **Motion**: two angular tech rings (30/24 segments) counter-rotating,
  a 24-lantern orange swarm orbiting + bobbing, a radar-like apex array
  spinning on the keep.

~1,800 objects; materials + roles embedded on 36 batches.

## Running

```bash
uv run --no-sync python examples/castle_tenshu/tenshu_driver.py CLEAR    # wipe doc first
uv run --no-sync python examples/castle_tenshu/tenshu_driver.py ALL      # SUN + T1..T4 + MAT
uv run --no-sync python examples/castle_tenshu/tenshu_driver.py EXPORT   # tns-<asm>__<matkey>.glb
uv run --no-sync python examples/castle_tenshu/tenshu_driver.py SAVE3DM  # ~/Documents/almond_infinity/almond_tenshu.3dm
```

State in `%TEMP%/almond_tenshu`. Same env switches as the infinity kit
(`ALMOND_DRY`, `ALMOND_CAPTURE`, `ALMOND_TNS_SCRATCH`).

## The film

```bash
blender -b -P examples/castle_tenshu/blender_tenshu_anim.py
```

1,560 frames / 65 s / 24 fps, 1280x720 Cycles AgX (exposure -0.85 for
the charcoal + white mix):

1. **Aggregation reveal** (0-20 s) - close on the sannomaru SE corner
   yagura, pull-back reveals turret -> bailey -> bailey -> tenshu.
2. **Slow orbit** (20-46 s) - R~220 m while rings counter-rotate
   (+45/-60), lanterns orbit (+30) and bob, apex spins (-140).
3. **The approach** (46-65 s) - up the south gate axis over the bridge
   and three gatehouses, rising to the apex array against the sky.

Probes: `ALMOND_ANIM_PROBE="1,480,1104,1560"`. All infinity-kit Blender
gotchas apply (5.x keyframe interpolation preference, parent after mm->m
scaling, 24 km ground plane).

## v2: Wasp-style aggregation + night cyberpunk grade (same session)

- **AGG phase** - seeded discrete aggregation (Wasp-like, `random.Random(7)`)
  on a 3.6 m voxel grid: rooms / corridors / shafts / bridges / 2x2x2
  tesseract frame-cells with glowing cores, grown from seeds on the tier
  setbacks, wall caps, yagura and gate tops. A pyramidal height envelope
  (`env_top`, tallest at the keep) plus a tenshu keep-out cone preserves
  the castle silhouette. 250 modules, ~1,365 objects.
- **DET phase** - layered facade plates + corner neon on the tenshu,
  antenna clusters, wall equipment + conduits, 8 big billboard screens,
  14 floating holo panels (their own `holo` assembly - they drift and
  bob in Blender). Scene total ~3,460 objects, 50 material batches.
- **Glow classes** - matkeys glow (white), gloworange, glowcyan
  (interface screens: brick-texture UI grid + flicker), glowwarm
  (window strips).
- **Night grade** - near-black sky, dim blue moon (0.3 W/m2) along the
  Rhino sun vector, wet-asphalt glossy ground (rough 0.14) reflecting
  the neon, AgX exposure -0.3, and Blender 5.x compositor bloom
  (scene.compositing_node_group + Glare BLOOM node; params are INPUT
  SOCKETS in 5.x, and scene.node_tree no longer exists).

## v4: construction-quality detail + landscaping (same session)

- **SITE phase** - granite paths with expansion-joint covers, karesansui
  raked-gravel panels (wave-texture rake lines in Cycles), a stone-edged
  pond with rocks, niwaki pines + clipped hedges, 14 stone lanterns
  (warm-glow light boxes), three tea pavilions (granite floor, oak posts
  on galvanized base plates, the kit's flared roof so the eave neon and
  vermilion soffits stay consistent).
- **JOINTS phase** - grand entry stair embedded in the tenshu ishigaki
  south batter up to a vermilion portal + canopy; wall-walk stairs in
  four courtyards; base plates + anchor nubs under the plaza pylons;
  vertical panel-joint reveals on the two lowest tenshu storeys; coping
  seams + inner handrails on every bailey wall; splice flanges on the
  service pipes.
- **Materials** - library gains stone-granite-paving, gravel-raked,
  water-still, foliage-pine; MAT now also stamps BCI construction
  systems (bearing walls, flat plates, column grid) via assign_material.
  ~5,100 objects, 71 batches.
