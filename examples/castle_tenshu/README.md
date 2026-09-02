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
