# Infinity castle: Almond Infinity - a fractal castle built for an "infinite scale" film

Third-generation kit (2026-09-03). Where city kit v2 was a district, this
is ONE building engineered to look endless, then filmed in Blender with
slow pans while the castle itself moves.

## The fractal

- **Castles on castles** - each of the four corner towers carries a sky
  platform with a complete miniature copy of the castle (`module()`
  recurses; detail level from absolute size: full >= 10 m half-span,
  simple >= 4 m, mini below). 21 modules over two corner-recursion levels.
- **Endless spiral ziggurat keep** - `keep_chain()` stacks 6-tier groups
  (tier side x0.80, alternating 0/45deg), each group rotated +22.5deg and
  reseeded from the last tier's width x0.76, so the silhouette converges
  toward a vanishing point (~80.6 m apex from a 30 m half-span base).
- **Moving assemblies** - three counter-rotating halo rings (36/30/24
  segments), six orbiting islet-castles on inverted rock cones, and a
  12-fin crown at the apex. Each is exported as its own GLB set so
  Blender can parent it to an animated empty.
- **Glow** - every "glow" batch (tier bands, gate arch, ring underglow,
  islet crystals, needle tips, crown blades) is polycarbonate-opal in
  Rhino and a cyan emissive (strength 14) in Cycles.

~1,190 objects; materials + structural roles embedded via
`assign_material` on 38 batches (`MAT` table in the driver).

## Running

Rhino 8 open, fresh mm document, bridge on 5000:

```bash
uv run --no-sync python examples/infinity_castle/castle_driver.py ALL     # SUN + C1..C4 + MAT
uv run --no-sync python examples/infinity_castle/castle_driver.py EXPORT  # inf-<asm>__<matkey>.glb
uv run --no-sync python examples/infinity_castle/castle_driver.py SAVE3DM # ~/Documents/almond_infinity/
```

State in `%TEMP%/almond_infinity` (`ALMOND_INF_SCRATCH` overrides).
`ALMOND_DRY=1` dry-runs; `ALMOND_CAPTURE=1` snaps per-batch viewport
frames. Sun = the v2 session's panel values (N 209.2 / az 168.3 /
alt 22.4 / intensity 2.22), written to `<scratch>/sun_state.json` and
re-used verbatim by Blender.

## The film

```bash
blender -b -P examples/infinity_castle/blender_infinity_anim.py
```

1,560 frames / 65 s / 24 fps, 1280x720 Cycles (48 samples, OptiX,
persistent data, AgX):

1. **Fractal reveal** (0-20 s) - close on a grandchild mini-castle, one
   unbroken pull-back reveals castle on castle on castle.
2. **Slow orbit** (20-46 s) - quarter orbit while rings counter-rotate
   (+55/-40/+70 deg over the film), islets orbit (+25deg) and bob
   (phase-staggered sines), crown spins (-90deg).
3. **The ascent** (46-65 s) - rise along the spiral ziggurat to the
   rotating crown, ending wide.

`ALMOND_ANIM_PROBE="1,480,1104"` renders chosen frames as stills to check
choreography cheaply; `ALMOND_ANIM_START`/`END` chunk the full render;
`ALMOND_BLEND_PATH` saves the .blend. Assemble with ffmpeg:

```bash
ffmpeg -framerate 24 -i <scratch>/blender_anim/f%04d.png -c:v libx264 -pix_fmt yuv420p -crf 18 almond_infinity_film.mp4
```

## Gotchas

- Assembly animation NEEDS the per-assembly GLB split (glTF flattens by
  material otherwise); islets are re-clustered per islet in Blender by
  centroid bearing (they sit at 15 + k*60 deg).
- Parent meshes to empties with `matrix_parent_inverse` AFTER the mm->m
  matrix_world scaling; the importer hierarchy is flattened first with
  `parent_clear(KEEP_TRANSFORM)`.
- Rich textured materials are imported from
  `examples/city_kit_v2/blender_modern_mats.py` (shared sys.path import);
  "glow" is the one local recipe.
- All v2 bridge gotchas apply (LinearDimension purge, ViewCapture,
  60 s socket cap).
