# Almond 0.7 — structural analysis

Pre-release pair: **almondbridge 0.7.0-rc.2** (Yak, Rhino 8 / Windows) and **almond-mcp 0.7.0rc2** (PyPI).
rc.1 went to PyPI only (`almond-mcp 0.7.0rc1`); its Yak was never pushed, because the first run from PyPI
failed behind a TLS-inspecting proxy (fixed in #26) and the shell feedback was unclear (#25).
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
| Pre-release | The panel pins its PyPI twin for prereleases (`0.7.0-rc.1` → `almond-mcp@0.7.0rc1`); before, any version with a hyphen ran the latest stable, 0.6.0, which has no `solve` command | #20 |
| Capture feedback | Capture errors (200-object limit, library blocks, units) show beside the button, not only at the foot of the form | #21 |
| Workspace layout | Structure workspace in five tabs (Model, Loads, Supports, Code, Results) with icons; a status line with colours and "How to fix" hints; an Engine/Structure/Loads/Supports checklist that enables Run | #22 |
| Shells | Shells are flagged at capture when the native engine is selected (it solves line models only), with a specific fix: Karamba3D, or centre lines | #25 |
| First run | The panel starts uv with `UV_NATIVE_TLS=1` (Windows certificate store), so the engine downloads behind TLS-inspecting proxies and antivirus; a user's own setting is kept; a certificate error gets a specific hint | #26 |

## Merge order

All merged in order on 3 October 2026: #18 → #19 → #20 → #21 → #22 (master `d00db0a`), then #25 and #26
(master `6964ebe`). Build the published artifacts from master, not from a branch.

## Build

```powershell
./tools/prepare_release.ps1
```

This produces `dist/release-0.7.0rc2/` with the wheel, sdist, `almondbridge-0.7.0-rc.2-rh8_0-win.yak`,
the Food4Rhino ZIP, the test and audit reports and `SHA256SUMS.txt`. Nothing is uploaded.

## Required Rhino smoke test (structure workspace)

In addition to the archive checks in [release-0.6.md](release-0.6.md#required-final-rhino-smoke-test),
on the exact Yak, in a clean Rhino 8 profile **without** `ALMOND_SOLVER_COMMAND` set:

1. `AlmondStructure` opens; **Check engines** reports *Native engine ready*. This requires
   `almond-mcp 0.7.0rc2` on PyPI, so publish it first (see below). Without it, the panel must report
   the failure clearly, not crash.
2. Draw a two-bay steel frame with support points. Capture it, run with Eurocode, floor 2.0 + 1.0 kN/m²
   and pinned bases. Expect a deflected overlay, a verdict, αcr and the Results panel filling.
3. Switch to simple connections and rerun; switch the overlay to the first buckling mode.
4. Give one curve `almond:section` = `rect 300x600` and Concrete: the verdict is *Indicative only*
   and the Results panel lists RECT 300×600 for that member.
5. Select more than 200 objects: the panel refuses with the 200-object message.
6. Select a solid box column: it is read as a centre line with a warning; a block-shaped solid is skipped.
7. Results panel: sort, filter (*Over 100%*, *Columns*), row click selects the member, **Save CSV**.
8. MCP: with `uvx --from almond-mcp==0.7.0rc2 almond-mcp` configured, `validate_structure` with
   `detail=True` and `visualize_structure` on the same frame give the panel's numbers.
9. Update path: install over 0.6.0 and confirm the Models workspace still browses and places.

Record pass/fail, the Yak SHA-256, Windows version and Rhino service release here.

## Publication sequence (operator)

1. **PyPI first:** `uv publish dist/release-0.7.0rc2/*` with the maintainer token. Verify
   `uvx --from almond-mcp==0.7.0rc2 almond-mcp --version` on a clean machine. The bridge's panel
   depends on this package, so the Yak must not go out before it.
2. **Yak:** `Yak.exe push dist/release-0.7.0rc2/almondbridge-0.7.0-rc.2-rh8_0-win.yak`, then
   `Yak.exe search --all --prerelease almondbridge`. Users need **Include pre-releases**.
3. Tag `v0.7.0rc2` and create a GitHub pre-release with the checksums.
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

## Build record — rc.2, 3 October 2026

Built with `./tools/prepare_release.ps1` from master `4564c1c` (after #27), in a clean `git worktree` of that
commit, with `UV_NATIVE_TLS=1` and `powershell.exe -File` as for rc.1.

- Tests: 400 passed, 0 failed (including the .NET archive-host and solver process-boundary tests).
- Clean wheel install: 56 MCP tools; archive HTTP and repository resource checks passed.
- Yak audit: 392 routes, 57 assets (50 models, 7 elements), 10 drawing packages, 51.1 MB; bridge `0.7.0-rc.2`,
  archive `0.7.0rc2`.

| File | SHA-256 |
|---|---|
| `almondbridge-0.7.0-rc.2-rh8_0-win.yak` | `914b890e850b43c0fe5bc97cb76bee239912cddd32f6bfd6fc343b70f5dbf8f7` |
| `almond_mcp-0.7.0rc2-py3-none-any.whl` | `c602ba520d97d02987d7bb61062ba7e62180c7df59e933c7301833e2226fa3f1` |
| `almond_mcp-0.7.0rc2.tar.gz` | `864854ac16a95203d035d52e227b573b5a27e35dab189ae981de3741d16c3168` |
| `almondbridge-0.7.0-rc.2-food4rhino.zip` | `15e4844f847a56f23e43171501ba1b11bbe9580102d74b5f22ee229d76c156b4` |

### rc.2 smoke test

Windows 11 Home 10.0.26200, Rhino 8, the exact Yak above installed over rc.1 (the Package Manager removed the
inactive rc.1 at start). The rc.2 code differs from the rc.1 smoke-tested build only by #25 and #26, so these
checks target them; checks 2-9 above carry over.

| Check | Result |
|---|---|
| Certificate fix (#26), before PyPI: user-level `UV_NATIVE_TLS` removed; the panel's solver set to `uvx --refresh --from <rc2 wheel> almond-mcp`, which re-resolves the dependencies from PyPI on every start | Pass: *Native engine ready · v0.7.0rc2*. Control: the same `uvx --refresh` from a shell without the variable fails with *invalid peer certificate: UnknownIssuer* |
| Shells (#25): capture a two-bay frame plus one planar surface with the native engine | Pass: amber *Selection captured, but it includes 1 shell.*, the Karamba3D/centre-line hint, the summary ends *shells need Karamba3D*, the Structure chip asks for input and Run stays disabled |
| Full run: recapture the frame alone, Steel CHS 219.1×8, fixed bases, rigid joints | Pass: *Within configured checks*, 0.33 mm, 3.3 %, αcr 307.55, overlay drawn, solver almond-mcp 0.7.0rc2 |

### rc.2 publication

`almond-mcp 0.7.0rc2` was uploaded to PyPI on 3 October 2026; the PyPI SHA-256 of the wheel and sdist match the
table above. First run from PyPI on the exact Yak: `ALMOND_SOLVER_COMMAND`, `UV_NATIVE_TLS` and `UV_SYSTEM_CERTS`
unset, and `UV_CACHE_DIR` pointed at an empty folder so nothing came from the cache. **Pass:** the panel showed
*Starting the native engine… The first run downloads it.*, then *Native engine ready · v0.7.0rc2* after about
17 s (289 MB downloaded), behind the same TLS-inspecting network that broke rc.1.

Published on 4 October 2026: the Yak (`914b890e…`) to yak.rhino3d.com as `almondbridge 0.7.0-rc.2 (prerelease)`,
listed by `Yak.exe search --all --prerelease almondbridge`; tag `v0.7.0rc2` on `4564c1c`; GitHub pre-release
[v0.7.0rc2](https://github.com/liangjunglj-cpu/almond-mcp/releases/tag/v0.7.0rc2) with the Yak, wheel, sdist and
`SHA256SUMS.txt`. Food4Rhino stays on 0.6.0.

Follow-up: uv now reports `UV_NATIVE_TLS` as deprecated in favour of `UV_SYSTEM_CERTS`. It still works; a later
release should set both.

## Build record — rc.1, 3 October 2026 (PyPI only)

Built with `./tools/prepare_release.ps1` from master `d00db0a` (after #22), in a clean `git worktree` of that
commit: the main checkout held unrelated uncommitted asset work that must not reach a release. This build
supersedes the earlier rc.1 builds from the release branch and from `d73f0de`; their hashes are not to be published.

- Tests: 398 passed (including the .NET archive-host and solver process-boundary tests).
- Clean wheel install: 56 MCP tools; archive HTTP and repository resource checks passed.
- Yak audit: 392 routes, 57 assets (50 models, 7 elements), 10 drawing packages, 51.1 MB; bridge `0.7.0-rc.1`,
  archive `0.7.0rc1`.

| File | SHA-256 |
|---|---|
| `almondbridge-0.7.0-rc.1-rh8_0-win.yak` | `8c701864f2ee18911447fd00d7b944bcf6a5aa9bad42f053b1ed84b169ff8c81` |
| `almond_mcp-0.7.0rc1-py3-none-any.whl` | `9189cd46b5f4685b2f49f20c0f34e14365173603f5f4ff0e3262948e01e06a85` |
| `almond_mcp-0.7.0rc1.tar.gz` | `e4c304ecab3ffb471ed05dd5b89cc0e508e2f0119242de086917eec0998d9151` |
| `almondbridge-0.7.0-rc.1-food4rhino.zip` | `ee44ae8dc34bec0cf8462558fa7b3ab9ab2b573823375552849de210a89b07e1` |

`dist/release-0.7.0rc1/SHA256SUMS.txt` lists these and the reports.

On this machine uv needs `UV_NATIVE_TLS=1` (a TLS-inspecting proxy), and the script must run under
PowerShell 7, or `powershell.exe -File` without stream redirection: Windows PowerShell 5.1 turns uv's stderr
notes into terminating errors when the streams are redirected inside PowerShell. The bundled
`food4rhino-listing.md` still describes 0.6.0; it is updated only for a stable release.

### Rhino smoke test so far

Windows 11 Home 10.0.26200, Rhino 8. The panel's solver pointed at a local install of the rc wheel
(`ALMOND_SOLVER_COMMAND`), since `almond-mcp 0.7.0rc1` is not yet on PyPI.

| # | Check | Result |
|---|---|---|
| 1 | Check engines; and without the override, the unpublished PyPI rc | Pass: *Native engine ready · v0.7.0rc1*; without it the panel reports the engine as starting and does not crash |
| 2 | Two-bay steel frame, Eurocode, floor 2.0 + 1.0, pinned, rigid | Pass: 5.34 mm, 38.3 %, αcr 31.18, overlay drawn, Results panel 13 rows |
| 3 | Simple joints, then the buckling overlay | Pass (simple joints on fixed bases; on pinned bases the frame is correctly a mechanism) |
| 4 | `almond:section` rect + Concrete | Pass: *Indicative only*, RECT 300x600 in the Results panel |
| 5 | More than 200 objects | Pass: refused with the 200-object message (shown beside the button since #21) |
| 6 | Solid box column / block | Pass via the export path: centre line with a rect section and a warning; block skipped |
| 7 | Results panel sort, filter, row click, CSV | Pass. On `d00db0a`: **Save CSV** opened *Save member results*; the saved file has a UTF-8 BOM and 21 lines (header + 20 members) |
| 8 | MCP `validate_structure` / `visualize_structure` from the rc wheel | Pass: identical to the panel (5.339 mm, αcr 31.18) |
| 9 | Models workspace after the update | Pass on `d00db0a` (checked by hand): catalogue browses, a model places in the viewport |

Checks 1-6 and 8 ran on the `d73f0de` build; checks 7 (Save dialog) and 9 on `d00db0a`. On `d00db0a` the
tabbed workspace was also walked through on the A07 mezzanine (capture, loads, supports, code, run, rerun;
status states and the run checklist). Still to do on this exact Yak: the first run from PyPI, with
`ALMOND_SOLVER_COMMAND` removed, after `almond-mcp 0.7.0rc1` is uploaded.

Testing note: automation that starts an Almond command from a script and then calls the panel's web view
synchronously can deadlock Rhino (the command never returns and selection stops working). Interactive use
does not do this; drive automated checks with real clicks and keep commands and panel scripting apart.

### rc.1 publication

`almond-mcp 0.7.0rc1` was uploaded to PyPI on 3 October 2026 (hashes as above). The first run from PyPI, with
`ALMOND_SOLVER_COMMAND` removed, failed on this machine: *invalid peer certificate: UnknownIssuer*, because uv
trusts only its bundled roots and the network inspects TLS. With `UV_NATIVE_TLS=1` set for the user it passed
(*Native engine ready · v0.7.0rc1*). The rc.1 Yak was not pushed; rc.2 sets the variable itself (#26).

## Publication record

*Pending.* Nothing has been published for 0.7.
