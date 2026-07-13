# Capsule Authoring Guide

This guide explains how to turn a Karamba example GHX into an audited capsule that Almond can run through `run_definition`. Right now every manifest in this folder says `"audited": false` because the example files ship with their own internal sliders and geometry. Your job is to add a small harness of Grasshopper params with reserved NickNames so Almond has fixed sockets to plug into.

You need Rhino 8, Grasshopper, and Karamba3D 3.1 or newer installed.

## The contract in one paragraph

Each capsule is a GHX file plus a sidecar manifest named `<capsule_id>.capsule.json`. The manifest lists inputs named `ALMOND_IN_*` and outputs named `ALMOND_OUT_*`. Almond binds to params in the GHX by exact NickName match on those reserved names. If a required input has no matching param, the run fails loudly and nothing is solved. Units are whatever the manifest declares, so your harness must feed the definition values in those units. Only when the harness exists and you have verified a real run do you flip `audited` to `true`.

## Steps for any template

1. Open the template from `Grasshopperfiles/Karambafileswithmodel/` in Grasshopper. Check the manifest in this folder that points at it (look at the `definition_file` field) so you know which params to create.
2. For each entry in the manifest `inputs`, place a standalone Grasshopper param component of the matching type on the canvas:
   - `curve[]` gets a Curve param, `mesh` gets a Mesh param, `number` gets a Number param, and so on.
3. Set each param's NickName to the reserved name exactly, for example `ALMOND_IN_LINES`. Double click the param label or use the component menu. Spelling and capitalization must match the manifest character for character.
4. Wire each input param into the definition where the template currently uses its own slider or internal geometry, and then delete or disconnect the internal source so the harness param is the only feed. For optional inputs, set the manifest default as the param's persistent value so the file still solves on open.
5. Mind units. The manifest declares them. If the manifest says metres and the template was built in another unit, insert a multiplication so the definition receives what it expects.
6. For each entry in the manifest `outputs`, place a param of the matching type, set its NickName to the reserved name, and wire the corresponding result into it. Flatten list outputs so Almond reads a flat list.
7. Draw a group around all harness params and title it `ALMOND HARNESS` so future you can find it.
8. Test inside Grasshopper: feed sample geometry into the inputs, confirm the solver runs, and confirm every output param carries a sensible value in the declared units.
9. Save As into `Grasshopperfiles/Karambafiles/harnessed/` keeping the same filename. Do not overwrite the original example.
10. Edit the manifest in this folder: confirm `definition_file` matches the harnessed filename, then change `"audited": false` to `"audited": true`. Almond will refuse to run the capsule until this flag is true, and the flag is your signature that steps 1 through 9 really happened.

## Worked example: the beam capsule

Manifest: `karamba_beam_v1.capsule.json`, template: `01_SimpleBeam.ghx`.

The manifest declares two inputs and three outputs:

| NickName | Type | Units | Role |
|---|---|---|---|
| `ALMOND_IN_LINES` | Curve (list) | m | beam axis curves |
| `ALMOND_IN_LOAD_KN` | Number | kN | point load, default 10.0 |
| `ALMOND_OUT_DISP_MM` | Number | mm | max nodal displacement |
| `ALMOND_OUT_UTIL` | Number (list) | ratio | utilization per element |
| `ALMOND_OUT_MASS_KG` | Number | kg | total mass |

Do this:

1. Open `01_SimpleBeam.ghx`. Find where the beam line enters `Line to Beam` (or the equivalent assemble chain) and where the load magnitude slider feeds the `Point Load` component.
2. Drop a Curve param, set its NickName to `ALMOND_IN_LINES`, set its access to list, and wire it into `Line to Beam` in place of the internal line. Delete the internal line source.
3. Drop a Number param, set its NickName to `ALMOND_IN_LOAD_KN`, give it a persistent value of 10.0, and wire it to the load magnitude input. Karamba point loads take a force vector in kN, so a value of 10 with a unit Z vector means 10 kN downward. Remove the old slider.
4. After the `Analyze` component, use `Disassemble Model` or the analysis outputs to get maximum displacement. Karamba reports displacement in the document unit, so convert to millimetres with a multiplication if needed, then wire into a Number param nicknamed `ALMOND_OUT_DISP_MM`.
5. Wire the `Utilization` component's per element output, flattened, into a Number param nicknamed `ALMOND_OUT_UTIL`.
6. Wire the model mass output into a Number param nicknamed `ALMOND_OUT_MASS_KG` (convert to kilograms if the template reports tonnes).
7. Group the five params as `ALMOND HARNESS`. Test with a 6 m line: expect a few millimetres of deflection and utilizations well under 1.0 for the default section.
8. Save As `Grasshopperfiles/Karambafiles/harnessed/01_SimpleBeam.ghx`.
9. In `karamba_beam_v1.capsule.json` set `"audited": true`.

## Checklist before flipping audited

- Every required manifest input has a param with the exact reserved NickName.
- Every manifest output param carries a value after a test solve.
- Units at each socket match the manifest declarations.
- Internal sliders and geometry that the harness replaces are removed, not just bypassed.
- The harnessed file lives in `Grasshopperfiles/Karambafiles/harnessed/` and the original example is untouched.
- You ran it once yourself and the numbers were plausible.

If any of these fail, leave `audited` as `false`. A false flag is honest; a wrong true flag produces fake engineering numbers.
