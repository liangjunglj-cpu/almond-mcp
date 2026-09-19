# City kit v2: Almond Modern - modernist district around a transit concourse

Second-generation city-scale workflow (2026-08-30). Where v1
(`examples/city_kit`) tested five construction systems with one detail
kit, v2 explores **modernist social architecture**:

- **Volume play, not just boxes** - a 9F slab on pilotis with a two-storey
  sky-garden void, cantilevered "drawer" volumes and a setback crown; a 5-level
  ziggurat of stepped terraces; a glass **cylinder tower** (drum floors, radial
  fins, open-air 2-storey sky deck) on a podium; two **interlocking bars**
  (5F x 8F) sliding through each other; a rotated plaza kiosk and tilted
  oriented-box elements (awnings, PV panels, escalators, saw-tooth markings).
- **Transit-integrated concourse** - a below-grade metro station (island
  platform, tracks, berthed 3-car train, stairs + escalators through deck
  openings), an at-grade glazed concourse hall on pilotis with skylight
  monitors over the platform voids, and a bus interchange (canopy island,
  shelters, two buses) - all one continuous public spine.
- **Building systems** - egg-crate brise-soleil (block A south), vertical
  aluminium fins (hall + tower + bar west faces), deep slab overhangs
  (ziggurat), PV arrays (tilted, south-facing), wind cowls, plant rooms with
  louvers, skylights - climate devices as facade language.
- **Social ground floor** - corner shops (double-height glazed, fascia +
  awning) on every block, rooftop terraces/gardens everywhere, a sky bridge
  from the bars into the concourse, plaza with benches and trees.

~2,950 objects, one shared kit (`glass_wall`, `ribbon`, `corner_shop`,
`pv_array`, `roof_garden`, `stair_core`, ...), oriented boxes via a new
`add_obl_boxes` bridge template (yaw + pitch).

## Sun and view

`SUN` phase drives the doc sun from the user's Rhino Sun panel: **North
209.2°, azimuth 168.3°, altitude 22.4°, intensity 2.22, manual control**,
plus a gradient sky on the Rendered display mode and an SE perspective
camera. The computed model-space sun vector is written to
`<scratch>/sun_state.json` and re-used verbatim by the Blender script, so
both applications cast identical shadows.

## Running

Rhino 8 open, mm document, bridge on 5000:

```bash
uv run --no-sync python examples/city_kit_v2/modernist_driver.py ALL     # SUN + M1..M8
uv run --no-sync python examples/city_kit_v2/modernist_driver.py EXPORT  # per-material GLBs
uv run --no-sync python examples/city_kit_v2/modernist_driver.py PAN 1   # aerial tracking frames
uv run --no-sync python examples/city_kit_v2/modernist_driver.py PAN 2   # street-level tracking frames
```

State lands in `%TEMP%/almond_modern` (`ALMOND_MODERN_SCRATCH` to
override). `ALMOND_DRY=1` dry-runs the Python geometry;
`ALMOND_CAPTURE=1` snaps a rendered-view timelapse frame after every
batch into `<scratch>/genframes` (the procedural-generation film).

## Recording the generation

The 2026-08-30 run was recorded two ways simultaneously:

1. **Screen recording** - ffmpeg `gdigrab` desktop capture at 10 fps into
   a kill-safe MPEG-TS while the driver ran against the foregrounded
   Rhino window in Rendered mode (sun + shadows live).
2. **Clean viewport timelapse** - `ALMOND_CAPTURE=1` per-batch
   `ViewCapture` frames (1280x720), immune to window occlusion.

Then two `PAN` passes (240 frames each, `ViewCapture` 1600x900, constant
camera-target offset = true parallel tracking): an aerial track along the
south front and an eye-level track along the north street. Frames are
assembled with ffmpeg; see `renders/` for the final cut.

## Blender replication

```bash
blender -b -P examples/city_kit_v2/blender_modern.py
```

Imports the per-material GLBs, builds Cycles materials per material_id
(plaster white, two concretes, glass with transmission, anodized fins,
dark PV cells, emissive lamp heads, foliage split), aims a Sun lamp along
the **exact** `sun_state.json` vector (energy scaled from the panel's
2.22), Nishita sky for ambience, SE aerial + SE street cameras, AgX. Saves
`~/Documents/almond_modern.blend`.

## Gotchas learned in this session

- `execute_rhino_script` C# only; `SetCameraLocations(target, camera)` -
  target FIRST.
- The bridge stamps a `LinearDimension` per create/assign batch;
  `purge_dims()` (inside `save()`) sweeps them - TextEntity labels survive.
- `view.CaptureToBitmap(...)` ignores the display-mode background (black
  sky); `Rhino.Display.ViewCapture` honors it - use it for all captures.
- The Rendered display mode's background is the display-mode
  `FillMode` (`DisplayPipelineAttributes.FrameBufferFillMode.Gradient2Color`
  + `UpdateDisplayMode`), not `doc.RenderSettings`.
- Bridge socket cap is 60 s; for long frame loops send the raw payload
  with `timeout_s` via `m._send_and_receive` and chunk the frames.
