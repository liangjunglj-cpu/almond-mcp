# Almond Celestia - floating sky-citadel (Genshin-style x cyber-tech)

Third castle generation (2026-09-06). Greater physical volume (~450 m
scene, ~137 m spire), completely different style: bright anime day,
saturated pastel palette, floating islands over a sea of stylized
clouds, cyan + gold energy accents.

## Massing

- **Great island** - r=95 m top disc (meadow grass) on a stepped inverted
  rock cone with rim cliffs, 20 glowing under-crystals, 8 waterfalls
  pouring off the rim with mist discs.
- **Citadel** - marble podium + 8 shrinking drum tiers (ivory), each with
  a cyan glow band, brass trim ring, double glazed-teal pagoda roof
  discs, window slits, radial brass fins; brass needle + gold apex orb
  (apex z=129 m). Recursive `citadel(s, depth)`.
- **6 radial towers** (R=45 m) with parapeted sky platforms carrying
  0.30-scale mini-citadels; sagging arc bridges back to the core; 6 rim
  pylons with gold beacons.
- **Village** - ~190 teal-roofed ivory houses in six sectors between
  marble ring paths + radial avenues with brass curbs; 40 mint niwaki
  trees; gold lantern orbs.
- **10 satellite islands** (R 128-196 m, varied heights/sizes) with their
  own mini-citadels, trees, crystals, waterfalls, houses - prefixed
  `o_*`, exported as the `islands` assembly.
- **Motion assemblies** - 3 horizontal brass energy rings, a 44-segment
  vertical gold halo behind the spire (spins about its own axis), a
  24-crystal swarm, 12 sigil discs, apex crown.

~3,200 objects; library gains brass-polished, ceramic-teal,
grass-meadow (26 materials).

## Running

```bash
uv run --no-sync python examples/castle_celestia/celestia_driver.py ALL
uv run --no-sync python examples/castle_celestia/celestia_driver.py EXPORT
uv run --no-sync python examples/castle_celestia/celestia_driver.py SAVE3DM
```

State in `%TEMP%/almond_celestia`. Sky scene - NO ground; MAT looks up
materials via `matfor()` (strips the `o_` prefix), so satellite batches
share the main table.

## The film (EEVEE!)

```bash
blender -b -P examples/castle_celestia/blender_celestia_anim.py
```

1,560 frames / 65 s / **1920x1080 EEVEE** (~3 s/frame vs Cycles ~5 s at
720p), Standard view transform for the saturated anime look:

1. **The rise** (0-20 s) - from beneath the cloud sea past the glowing
   under-crystals and waterfalls, up over the island rim.
2. **Grand orbit** (20-46 s) - rings spin (+50/-38/+65), crystal swarm
   drifts, sigils rotate, islands orbit (+10) and bob.
3. **The ascent** (46-65 s) - climb the drum-spire to the crown with the
   gold halo turning behind it.

Genshin-grade notes: gradient-sky BACKDROP SPHERE (emission ramp on
object-Z; world stays a flat soft-blue ambient for lighting), 48 flat
white cloud discs below + 6 above, facing-gradient teal roof material
(LayerWeight -> teal mix), compositor bloom, glow strengths ~2.2-2.6
(higher blows to white under Standard), waterfalls at 0.4 emission read
as water instead of light pillars.

## Gotchas

- Rhino Rendered-mode ViewCapture shows black wireframe when the Rhino
  window is minimized (realtime pipeline never draws) - paint object
  display colors from their materials and capture in Shaded instead.
- EEVEE 5.x: engine id "BLENDER_EEVEE"; screen-space raytracing ~triples
  frame time and is invisible in this flat style - leave it off.
- All prior Blender 5.x gotchas apply (keyframe interpolation pref,
  compositor node group, Mix node sockets, parent after mm->m scaling).
