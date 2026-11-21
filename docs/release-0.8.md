# Almond 0.8 — stable release

Stable pair: **almondbridge 0.8.0** (Yak, Rhino 8 / Windows) and **almond-mcp 0.8.0** (PyPI wheel; the sdist
goes to the GitHub release only). It follows the 0.7.0rc2 pre-release and is the first stable release since
0.6.0, so Rhino users need no **Include pre-releases**. RhinoCommon stays pinned to 8.0.23304.9001; the plugin
identity `c337dbb8-394a-4593-9c2b-a3d7cfc91893` is unchanged. Build mechanics are those of
[release-0.6.md](release-0.6.md) and [release-0.7.md](release-0.7.md) (`tools/prepare_release.ps1`, the
`release-candidate.yml` workflow, immutable Yak versions), with the packaging changes below.

## What is stable and what stays (BETA)

| Area | Status in 0.8.0 | Evidence |
|---|---|---|
| Native structural engine (`validate_structure`, `visualize_structure`, Structure workspace, Almond Results) | **stable** | OpenSees cross-check: 27 pass + 1 strict xfail (open-section warping); linear error ≤ 1.2e-6 on 12 typologies; α_cr within −0.27 … 0.00 %; mutation check 63/63 |
| EN 1993-1-1 member checks (classes, curves, Annex B, shear 6.2.6/6.2.8, bow imperfections, LTB 6.3.2, Table B.3 Cm) | stable for steel; concrete, timber and aluminium stay indicative | `test_ec3.py`, `test_hand_calculations.py`, mutation check |
| Karamba3D route | **(BETA)** | No CI; issue #6 (per-member utilization on Karamba 3.1.60519) open |
| Environment: climate, daylight, radiation, thermal, comfort, rooms, code packs | **(BETA)** | No real-EPW test in CI, no ASHRAE 140 / BESTEST thermal benchmark, no reference-engine daylight comparison yet |
| Generated model library (144 models) | stable | Source register 0 errors; release verifier checks every model, image and script |

The shell-roof α_cr difference against OpenSees recorded in the GH stress test (−17 %) is an under-meshed
OpenSees reference: refining a gridshell 16× brings OpenSees to −1.3 % of Almond, and a fixed-fixed CHS member
gives the exact Euler load in Almond at ×4. Almond's value is the correct, conservative one.

## What changed since 0.7.0rc2

**Structure**
- Shear (EN 1993-1-1 6.2.6/6.2.8), local bow imperfections, sway m rule, one-way bay end strips (#40);
  lateral-torsional buckling of I-sections with numerical M_cr (#42); results panel columns for shear, LTB,
  sway φ and bow imperfections (#41).
- Curved members as chords with a model-size budget, and every member judged against its own span (#37),
  combined with member-relative deflection, storey drift and one verdict shared by `validate_structure` and the
  overlay (deflection-verdicts).
- Table B.3 equivalent moment factor Cm read from each member's moment diagram, without the 2 % cliff.
- Support types per support point, read from `almond:support` by the bridge and set from the Supports tab or
  Claude (#32, #33); lateral restraints `lateral-x` / `lateral-y`.
- Non-finite and non-physical solver inputs are rejected at the boundary; indicative runs are recorded and
  reported honestly; the bridge no longer stamps dimensions over script output (#48).
- Structural reference library: twelve benchmarked typologies as MCP tools (list, get, analyze, place).

**Environment (BETA)**
- Rooms, layered constructions, code packs incl. Singapore (from 0.7 master), coursework-style studies
  (climate charts, shadows, thermal cases, EN 17037; #45), daylight-linked lighting (#47), curtains and interior
  glass are not windows (#46), environment review fixes, a tutorial model, and the Rhino-style panel with
  advanced options collapsed.
- Cooled rooms report hours above 28 °C: "hours above 26 °C" counted a cooled room's own set-point.

**Library and tools**
- Generated library 84 → 144 models: Ginkgo props, Daxi harbour boats and Project Y2K props and kit pieces,
  each with recorded generation evidence (new routes: edited uploads, Meshy text-to-3D, concept references,
  procedural scripts). The library page labels models Meshy / Tripo / Scripted.
- Parametric teaching library: ten annotated Grasshopper definitions (MIT / BlueOak) as MCP tools.
- Scene-metadata snapshot and audit (pilot).
- The panel engine sets `UV_SYSTEM_CERTS` and the deprecated `UV_NATIVE_TLS` for uv.

## Packaging changes

- **Model files are GitHub release assets.** The PyPI wheel (about 40 MB) carries the catalogue, provenance and
  previews but no GLB or contract; each model downloads on first use from
  `https://github.com/liangjunglj-cpu/almond-mcp/releases/download/v0.8.0/<file>` and is refused unless its
  sha256 matches the manifest. `almond-mcp fetch-assets --generated` prefetches them. The Rhino plugin bundles
  all 144 models and needs no download.
- **PyPI gets the wheel only.** The sdist (well over 100 MB: models plus generation evidence) goes to the GitHub
  release.

## Build

```powershell
./tools/prepare_release.ps1
```

Produces `dist/release-0.8.0/` with the wheel, sdist, `models/` (every GLB + contract for the GitHub release),
`almondbridge-0.8.0-rh8_0-win.yak`, the Food4Rhino ZIP, the test and audit reports and `SHA256SUMS.txt`.
Nothing is uploaded.

## Required Rhino smoke test

On the exact Yak, in Rhino 8 without `ALMOND_SOLVER_COMMAND`:

1. `Almond` opens the panel; **Models** lists 144 models; search, rotate, Place and drag work; a Tripo, a
   Meshy and a Scripted model each place at catalogue size.
2. **Structure**: Check engines → native engine ready (needs almond-mcp 0.8.0 on PyPI, or a local wheel via
   `ALMOND_SOLVER_COMMAND` before publication). Run the tutorial frame: verdict, overlay, Results panel, no
   (BETA) on the native engine; the Karamba option still says (BETA).
3. Support types: set a pinned and a roller point in the Supports tab; the overlay draws per-type symbols.
4. **Environment** (BETA label visible): place the tutorial model, run a daylight factor and a thermal study;
   a cooled room's plan reads "Hours above 28 °C".
5. MCP: `uvx almond-mcp@0.8.0 doctor` passes; `place_generated_asset` downloads a model on a fresh user-data
   directory from the GitHub release.

Record pass/fail, the Yak SHA-256, Windows version and Rhino service release here.

## Publication sequence (operator)

1. **GitHub release first:** create release `v0.8.0` on the tagged build commit and upload
   `dist/release-0.8.0/models/*`, the sdist, the Yak and `SHA256SUMS.txt`. Installs download models from here,
   so it must exist before PyPI. Never delete or replace a model file on a published release.
2. **PyPI:** upload the wheel only: `uv publish dist/release-0.8.0/almond_mcp-0.8.0-py3-none-any.whl`.
   Verify `uvx --from almond-mcp==0.8.0 almond-mcp --version` and `fetch-assets --generated` on a clean machine.
3. **Yak:** `Yak.exe push dist/release-0.8.0/almondbridge-0.8.0-rh8_0-win.yak`, then confirm with
   `curl https://yak.rhino3d.com/versions/almondbridge` (an earlier push silently failed).
4. **Food4Rhino:** update the existing listing with [food4rhino-listing.md](food4rhino-listing.md).

## Known limits (documented to users)

- Steel member checks only; concrete, timber and aluminium are indicative. Gravity loads only; no wind.
- Environment results are design-stage comparisons, not compliance simulations, until the thermal benchmark,
  a real-EPW check and a daylight reference comparison exist.
- The Karamba route depends on Karamba 3.1 internals (issue #6).
- One material colour per generated model; some models face +X rather than −Y (documented per asset).
