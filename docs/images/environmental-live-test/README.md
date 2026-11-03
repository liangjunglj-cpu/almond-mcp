# Environmental analysis: live Rhino test (2026-11-01)

The first end-to-end run of the environmental tools (`docs/environmental-analysis.md`) against a live
Rhino 8. The tools ran through the Almond MCP server, from the checkout.

**Model:** an 8 × 6 × 3 m south-facing office, with its window cut into the facade wall. It has a
1 m overhang, a 10 m-high neighbour 14 m to the south, a ground plane, and a closed box for the
thermal zone, all on `AlmondEnvTest::…` layers in a millimetre document.

**Weather:** a synthetic EPW at 40°N, written by `tests/env_weather.py`. No real EPW was on the
machine, so these numbers prove the pipeline and are not real climate data.

| File | What it shows |
| --- | --- |
| `rhino-annual-da-plan.png` | Annual DA300 drawn in Rhino as a vertex-coloured mesh with legend (top view) |
| `rhino-solar-radiation-3d.png` | Annual irradiation on the roofs and the neighbour, drawn in Rhino (upright legend) |
| `annual-da.png`, `annual-ase_hours.png`, `annual-udi_useful.png`, `annual-mean_lux.png` | The annual run's PNG plans: sDA 63.5 %, ASE 20.8 %, shades closed 34 % of occupied hours |
| `daylight-factor-plan.png` | Daylight factor, CIE overcast: average 1.9 % after the facade-classification fix |
| `radiation-kwh-m2-elevation.png` | Irradiation map from the radiation run |
| `thermal-office-result.json` | Thermal zone run: heating 41.8 / cooling 11.7 kWh/m², TM52 pass (insulated, office schedule) |
| `open-plan-da-before-grid-fix.png` | Earlier offline test: an XY-aligned grid on a rotated room put sensors mm from the wall (dark line) and the old interreflection estimator was noisy |
| `open-plan-da-after-noise-fix.png` | The same room after the fixes: grid aligned to the room and the radiosity cache solve |

## Documentation photos (`photos/`)

These are Rhino viewport captures (Shaded, 1800 × 1125) of the test model and the results Almond
drew back into the document, composited onto a light background for print.

| Photo | Shows |
| --- | --- |
| `photos/01-model-overview.png` | The test model from the south-east: the room with its cut window and overhang, and the 10 m neighbour to the south |
| `photos/02-annual-daylight-autonomy.png` | Annual DA300 on the work plane (ceiling hidden), with legend |
| `photos/03-annual-sunlight-exposure-ase.png` | Hours of direct sun above 1000 lux (ASE): the strip under the overhang edge |
| `photos/04-daylight-factor.png` | Daylight factor under the CIE overcast sky |
| `photos/05-solar-radiation.png` | Annual irradiation on the roofs and on the neighbour's west and south faces, with the upright 3D legend |
| `photos/06-daylight-autonomy-plan.png` | DA300 in plan, window at the bottom |

What the live run found and fixed:

- surfaces named "facade …" were classified as dark exterior finish (they face the room too);
- radiation sensors were placed under the neighbour's base, which rests on the ground (they are
  now dropped, with a warning);
- a false "sensors outside the model" warning;
- the legend collapsed in perspective views.

Still open:

- the installed almondbridge is older than this branch, so it has no `ping` request type;
- the live server runs without numba, on the slower numpy path.
