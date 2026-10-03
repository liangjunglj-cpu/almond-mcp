# Almond 0.7 — structural analysis

Pre-release pair: **almondbridge 0.7.0-rc.1** (Yak, Rhino 8 / Windows) and **almond-mcp 0.7.0rc1** (PyPI).
Stable remains 0.6.0 until an rc passes the Rhino smoke test below. RhinoCommon stays pinned to
8.0.23304.9001; plugin identity `c337dbb8-394a-4593-9c2b-a3d7cfc91893` is unchanged. The build and
publication mechanics are those of [release-0.6.md](release-0.6.md) (`tools/prepare_release.ps1`, the
`release-candidate.yml` workflow, immutable Yak versions).

Users start with the [Structure workspace tutorial](structural-tutorial.md).

## What changed since 0.6.0

| Area | Change | PR |
|---|---|---|
| Karamba view | Live Karamba structure view in the viewport | #9 |
| Native solver | Almond's own 3D frame solver (direct stiffness, exact member loads); the default engine for line models | #10 |
| Loads | Floor area loads (bays from the plan graph) and loads from placed Almond models | #11 |
| Combinations | EN 1990 SLS/ULS combinations (6.10 or 6.10a/b), one factorisation | #12 |
| Connections | Member end releases, simple (pinned beam end) connections, `almond:release` per curve | #13 |
| Stability | αcr by eigenvalue, EN 1993 sway imperfections, P-Δ below αcr 10 | #14 |
| Panel | The Almond panel runs the native engine (`almond-mcp solve`); design code profiles with National Annex files | #15 |
| Results | Almond Results panel: every member, support, combination and load, CSV export; panel icons | #16, #17 |
| Validation | Hand-calculation tests and a mutation check of the structural suite | #17 |
| Member checks | EN 1993-1-1 per member: Table 5.2 classes, Table 6.2 curves by fabrication, Annex B interaction; buckling length per member, not per sub-element | #18 |
| Solids | Prismatic solids read as centre lines with rectangular sections; brep edges never become beams | #18 |
| Verdict | Concrete, timber and aluminium are indicative: no capacity pass/fail | #18 |
| Sections | `almond:section` user text per curve (`rect`, `box`, `chs`, with units) | #19 |
| Pre-release | The panel pins its PyPI twin for prereleases (`0.7.0-rc.1` → `almond-mcp@0.7.0rc1`); before, any version with a hyphen ran the latest stable, 0.6.0, which has no `solve` command | this release |

## Merge order

Each PR is stacked on the previous one; merge in order, each after its CI passes:

1. #18 `feat/ec3-member-checks` → master
2. #19 `feat/curve-sections` (retargets to master once #18 merges)
3. `release/0.7.0-rc.1` (version bump, docs, the pin fix)

Build the artifacts from the merged master revision, not from a branch.

## Build

```powershell
./tools/prepare_release.ps1
```

This produces `dist/release-0.7.0rc1/` with the wheel, sdist, `almondbridge-0.7.0-rc.1-rh8_0-win.yak`,
the Food4Rhino ZIP, the test and audit reports and `SHA256SUMS.txt`. Nothing is uploaded.

## Required Rhino smoke test (structure workspace)

In addition to the archive checks in [release-0.6.md](release-0.6.md#required-final-rhino-smoke-test),
on the exact Yak, in a clean Rhino 8 profile **without** `ALMOND_SOLVER_COMMAND` set:

1. `AlmondStructure` opens; **Check engines** reports *Native engine ready*. This requires
   `almond-mcp 0.7.0rc1` on PyPI, so publish it first (see below). Without it, the panel must report
   the failure clearly, not crash.
2. Draw a two-bay steel frame with support points. Capture it, run with Eurocode, floor 2.0 + 1.0 kN/m²
   and pinned bases. Expect a deflected overlay, a verdict, αcr and the Results panel filling.
3. Switch to simple connections and rerun; switch the overlay to the first buckling mode.
4. Give one curve `almond:section` = `rect 300x600` and Concrete: the verdict is *Indicative only*
   and the Results panel lists RECT 300×600 for that member.
5. Select more than 200 objects: the panel refuses with the 200-object message.
6. Select a solid box column: it is read as a centre line with a warning; a block-shaped solid is skipped.
7. Results panel: sort, filter (*Over 100%*, *Columns*), row click selects the member, **Save CSV**.
8. MCP: with `uvx --from almond-mcp==0.7.0rc1 almond-mcp` configured, `validate_structure` with
   `detail=True` and `visualize_structure` on the same frame give the panel's numbers.
9. Update path: install over 0.6.0 and confirm the Models workspace still browses and places.

Record pass/fail, the Yak SHA-256, Windows version and Rhino service release here.

## Publication sequence (operator)

1. **PyPI first:** `uv publish dist/release-0.7.0rc1/*` with the maintainer token. Verify
   `uvx --from almond-mcp==0.7.0rc1 almond-mcp --version` on a clean machine. The bridge's panel
   depends on this package, so the Yak must not go out before it.
2. **Yak:** `Yak.exe push dist/release-0.7.0rc1/almondbridge-0.7.0-rc.1-rh8_0-win.yak`, then
   `Yak.exe search --all --prerelease almondbridge`. Users need **Include pre-releases**.
3. Tag `v0.7.0rc1` and create a GitHub pre-release with the checksums.
4. Food4Rhino stays on 0.6.0 until a stable 0.7.0.

## Known limits (documented to users)

- Steel member checks only; concrete (EN 1992), timber (EN 1995) and aluminium (EN 1999) are indicative.
- Gravity loads only; no wind. No member bow imperfections (EN 1993 5.3.2(6)), no shear check 6.2.6;
  Class 4 sections fail as not covered.
- The sway imperfection's m counts all column lines (no ≥50 %-of-average-load filter per plane).
- Floor bays longer than 2:1 span one way: the long edges carry the floor load and the short edge beams get
  none from it, so check short beams separately.
- Only the Eurocode recommended values ship; National Annex profiles are user-supplied and flagged
  when unverified.
- One panel study takes at most 200 selected objects.

## Build record — rc.1 preparation, 3 October 2026

Built locally with `./tools/prepare_release.ps1` from the `release/0.7.0-rc.1` branch (before merging; rebuild
from master for publication). On this machine uv needs `UV_NATIVE_TLS=1` (a TLS-inspecting proxy), and the
script must run under PowerShell 7, or `powershell.exe -File` without stream redirection, because Windows
PowerShell 5.1 turns uv's stderr notes into terminating errors when the streams are redirected inside PowerShell.

- Tests: 398 passed (including the .NET archive-host and solver process-boundary tests).
- Clean wheel install: 56 MCP tools, archive HTTP and repository resource checks passed.
- Yak audit: 392 routes checked, 50 models, 51.1 MB.
- `almondbridge-0.7.0-rc.1-rh8_0-win.yak` SHA-256 `819377182f495931ef9d1f143b9b60fad8c552fcee8c25b39c8f87ab56f26d2b`
- `almond_mcp-0.7.0rc1-py3-none-any.whl` SHA-256 `b24dc4d6e02a99debde2ec98acb4d239c61f1decef92ebf08546625f51561492`
- Rhino in-process smoke test: **pending**.

The bundled `food4rhino-listing.md` still describes 0.6.0; it is updated only for a stable release.

## Publication record

*Pending.* Nothing has been published for 0.7.
