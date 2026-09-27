# Almond 0.6 release infrastructure

Stable pair: **almondbridge 0.6.0** and **almond-mcp 0.6.0**, published to Yak and
PyPI on 27 September 2026; see [Stable 0.6.0 preparation](#stable-060-preparation)
and [its publication record](#stable-060-publication-record). The Yak targets **Rhino 8.0 / Windows**;
RhinoCommon remains pinned to 8.0.23304.9001. Plugin identity stays
`c337dbb8-394a-4593-9c2b-a3d7cfc91893`. No Rhino update is required.

## What users receive

The Yak contains the compiled bridge, runtime dependencies, a complete read-only
Object Archive, 50 generated GLBs, contracts, 50 previews, source evidence,
10 drawing packages, attribution and licences. `AlmondLibrary` opens a dockable
Eto panel using Rhino 8's embedded web view and a loopback server hosted inside
the plugin; it requires neither Python nor an AI client. `AlmondLibraryBrowser`
opens the browser view. No Eto, Rhino UI or WebView2 runtime DLL is redistributed.
The archive closes with Rhino. No external CDN is used for included models.

The Python wheel independently includes the same generated asset collection and
MCP tools. Users who want AI workflows install/configure that package separately.
There is no automatic PyPI installation from the Rhino command. The Yak indexes
seven optional community drawing elements as unavailable records/source links;
their binaries never ship. No Karamba/Kangaroo examples or proprietary SDK DLLs
are redistributed.

The .NET host serves only manifest-listed routes, binds an ephemeral loopback
port, rejects foreign Host headers and write methods, and checks each response
file against the bundled SHA-256. It never exposes filesystem browsing or an
execution/upload endpoint. Saved browser selections are scoped to that port.
The panel adds a native Place action and thumbnail drag gesture; both enter a
fixed Rhino command rather than using an HTTP write endpoint.

## Reproduce the release

On Windows with .NET SDK and uv, from the repository:

```powershell
./tools/prepare_release.ps1
```

The default Yak executable comes with Rhino 8. For a build machine without Rhino:

```powershell
./tools/prepare_release.ps1 -YakExecutable C:/build-tools/yak.exe
```

The script uses unique TEMP environments and fresh bridge output; it never
syncs a live MCP environment, installs into Rhino, or falls back to an old RHP.
It runs the Python suite and real .NET HTTP-host integration tests, checks source
records, builds/audits wheel and sdist, performs an isolated wheel installation
and MCP smoke, builds a Windows Yak, and audits its allowlist and model hashes.
It creates `dist/release-<version>/` (for stable: `dist/release-0.6.0/`) with:

- Python wheel and sdist.
- `almondbridge-0.6.0-rh8_0-win.yak`.
- Food4Rhino ZIP wrapper, listing text and quickstart guide.
- JUnit test results, clean-install and Yak reports, and `SHA256SUMS.txt`.

The GitHub Actions `release-candidate.yml` runs this same pipeline on Windows
for pull requests or manual dispatch. It downloads a pinned standalone Yak from
McNeel, verifies its pinned SHA-256, and uploads build artifacts. The vendor's
0.15.1 standalone executable is unsigned; its hash was recorded from the official
HTTPS download and verified locally. The workflow requests
read-only repository access; no publication credentials are involved. This
workflow must be committed/pushed before it runs on GitHub.

## Required final Rhino smoke test

Compilation and standalone host tests cannot prove command registration or
runtime behaviour in Rhino. Before uploading an immutable version, test the
exact Yak in a disposable Windows/Rhino 8 profile or test machine:

1. Record the package SHA-256, Windows version and Rhino service release.
2. Install the local candidate using the Package Manager/local package flow;
   restart Rhino and confirm the same plugin GUID and candidate version.
3. Run `AlmondLibrary`; verify the dockable panel opens without Python on PATH.
   Dock, float, close and reopen it. Verify 3D rotation, the compact layout,
   `AlmondLibraryBrowser`, external source links and download links.
4. Open a GLB and a plan/front view, download GLB/DXF/record JSON, and inspect
   source metadata. Confirm optional community models remain unavailable.
5. Import a downloaded DXF into a millimetre document and compare a known mesh
   bound. Keep generated bounds distinct from verified product dimensions.
6. Repeat `AlmondLibrary` to confirm it reuses its host. Quit Rhino and confirm
   the archive port closes. Reopen Rhino and check the command again.
7. With the matching MCP wheel configured in an isolated client, verify repository
   search and one existing Rhino placement workflow in a disposable document.
8. Exercise both update-from-0.5.x and fresh-install paths; leave existing user
   downloads/custom assets untouched.

Record pass/fail and the tested package hash in the release record. Do not
claim this in-process smoke passed based only on the automated build report.

## Publication sequence (operator run, not performed by preparation)

1. Review and commit the intended source changes; run the workflow from that
   exact revision. Retain artifacts and the successful Rhino smoke record.
2. Publish the Python wheel/sdist to PyPI using the project's maintainer account
   (prefer PyPI Trusted Publishing for later CI automation). Verify the pinned
   `uvx --from almond-mcp==0.6.0 almond-mcp --version` on a clean machine.
3. Authenticate the maintainer's Yak account, then push the exact tested artifact:

   ```powershell
   & 'C:/Program Files/Rhino 8/System/Yak.exe' login
   & 'C:/Program Files/Rhino 8/System/Yak.exe' push ./dist/release-0.6.0/almondbridge-0.6.0-rh8_0-win.yak
   & 'C:/Program Files/Rhino 8/System/Yak.exe' search almondbridge
   ```

   A test-server push is optional before production; it is still an external
   publication and is not part of `prepare_release.ps1`. Never place Yak tokens
   in source or build artifacts. Future CI can use the documented `YAK_TOKEN`
   secret in a protected publication environment; do not run `login --ci` in
   logs because it prints a credential.
4. Update the existing Food4Rhino listing using `food4rhino-listing.md`. Preserve
   its GUID and app identity, attach the tested package or approved ZIP format,
   and use candidate screenshots. Verify the download/Package Manager link.
5. Create release notes and retain checksums. Versions already on Yak cannot be
   overwritten; fixes require a new version. A rollback uses the prior supported
   version and, when warranted, yanks the faulty package from discovery.

For stable 0.6.0, update Python `pyproject.toml`, `__init__.py`, asset-pack manifests
and lockfile, plus the bridge csproj/Yak manifest and release documentation.
Rebuild and retest; do not rename prerelease binaries as a stable release.

## Reference documentation

- [McNeel Yak creation](https://developer.rhino3d.com/guides/yak/creating-a-rhino-plugin-package/)
- [Manifest versions](https://developer.rhino3d.com/guides/yak/the-package-manifest/)
- [Yak CLI, standalone downloads and CI authentication](https://developer.rhino3d.com/guides/yak/yak-cli-reference/)
- [Immutable publishing and test server](https://developer.rhino3d.com/guides/yak/pushing-a-package-to-the-server/)
- [Food4Rhino developer FAQ](https://www.food4rhino.com/en/faq)

Official documentation checked 19 September 2026. No package account, live
listing, active Rhino plugin registration, or MCP configuration is changed by
the local preparation process.

## rc.6 compact placement workspace

The panel removes the landing-page hero and uses two thumbnail columns down to
280 CSS pixels. The browser retains the full archive layout. Thumbnails remain
static lazy-loaded images; the 3D viewer is created only for an open object.

Native panel gestures invoke a fixed Rhino command through a per-panel random
capability in intercepted same-origin navigation. The HTTP server remains
read-only and has no placement or execution endpoint. Only installed catalogue
GLBs can be selected; catalogue, materials and model bytes are hash-verified.
No file path or Rhino script can be supplied by the web UI.

A bounded C# GLB decoder reads the existing payload directly, preserving indices
and supplied normals, handling the archive's positive uniform transforms and
converting numeric millimetres/Y-up to Rhino's units/Z-up. No extra mesh copies
are distributed. Light placement calls Rhino Mesh.Reduce for meshes above
20,000 faces; actual results and source history are recorded on the Rhino block.
Definitions are keyed by source/record/material/detail/units and reused only
while their geometry fingerprint still matches. Edited blocks remain intact.

Validation: compare every triangle of all 50 models against the independent
Python drafting decoder, verify supplied normal lengths, and reject malformed
identity/buffer/accessor/animation/cycle cases. Build against Rhino 8.0 GA.
Before publication, manually check: held-mouse drag/release, outside release,
Esc, Place with object snaps, Light versus Original on a heavy tree, repeated
block reuse, material appearance, units (mm/m/in), current layer, Undo/Redo,
save/reopen metadata, and placement after editing a previous block. These
viewport dragging was confirmed by the user on rc.6; the remaining native checks
still need explicit acceptance. A browser test is not evidence of viewport placement.

## rc.7 Almond menu and Karamba workspace

The stable panel GUID is retained and its title becomes Almond. Commands:
Almond (home), AlmondLibrary (Models), AlmondKaramba (Karamba Validation).
The Neo Swiss home has two workspaces and links to sources/about. Existing model
placement remains intact. The active IKEA index, four supplier MCP tools,
legacy placement bridge action and shipped source catalogue are retired;
local historical records and downloads are preserved.

Karamba actions use the existing per-panel session capability and a fixed native
command. The HTTP host still has no analysis/write/execution endpoint. Settings
are bounded and allowlisted. Selection is limited to 200 structural objects,
10,000 faces per shell mesh and 200 faces per brep. Geometry and document-unit
fingerprints prevent stale selection use. The direct API supports explicit
self-weight and support restraint choices and a CHS section override. The panel
requires that API; missing solver metrics yield incomplete, never pass. Existing
MCP fallback pathways remain labelled, and nondefault options require the API.

The SVG diagram uses conditioned geometry, actual solver support/load locations,
and reported mapped utilization. The initial example is explicitly illustrative.
View/overlay toggles do not invalidate results; setup changes do. JSON exports
contain selected GUIDs, geometry snapshot, settings, warnings, result method and
timestamp. No simulated displacement field or unmeasured result is displayed.

Acceptance after restart: open all three commands, switch pages and return to
Models; confirm placement; check engine detection, selection/cancel, a supported
beam/frame and a mechanism, selected support points, self-weight on/off,
fixed/pinned restraint, section override, missing-metric handling, mapped colours,
worst-member selection, JSON export/cancel, edited geometry rejection and a
second document. Native solver and WebView callback acceptance remains pending.

## rc.8 material-colour thumbnails

Regenerates all 47 model thumbnails from the unchanged GLBs using their embedded
material base colours, transparent backgrounds and paint.sl studio lighting.
The gallery stays lightweight: static PNGs, with the interactive viewer loaded
only for an opened object. Preview derivation records link every PNG to its GLB
and renderer settings; the library audit rejects stale previews. The Yak includes
the record under archive/evidence/preview-render-record.json.

No phototexturing is introduced. Neutral materials remain neutral. Geometry,
material definitions, source passports, placement and Karamba code are unchanged.

## Rhino appearance integration (rc.9)

The embedded workspace reads Rhino panel, text, button and edit-box colours and
its default UI font. Appearance changes update CSS in place without reloading
the catalogue, selection or analysis settings. A compact header replaces the
separate browser/reload toolbar. Controls use consistent spacing and borders;
preview tiles retain neutral backgrounds and original material colours. Karamba
member/support/load diagrams adapt to the host palette. The full browser archive
retains its Neo Swiss layout. No Rhino appearance settings are modified.

Uses Rhino 8.0 GA APIs: AppearanceSettings.GetPaintColor, DefaultFontFaceName and
RhinoApp.AppSettingsChanged. The subscription is removed on panel disposal.
Validate native theme switching after restart, including retained search/input
state and closing/reopening the panel. Browser checks cannot prove native theme
event delivery.

## Karamba explainers (rc.11)

Six small question-mark buttons explain the workflow, engine, selection, setup,
diagram and results. They expand inline, support keyboard activation and Escape,
and do not change solver inputs. Fixed/pinned and diagram-symbol sketches are
illustrative.

The rc.11 collection retained 47 general-purpose models. The five futuristic
ProjectY2K imports considered in the unpublished rc.10 candidate are excluded
from rc.11 at the owner's request. No original ProjectY2K files were modified.
See [selection review](projecty2k-selection.md) for the scope and source inventory.

## Organic library additions (rc.12)

Adds three newly generated neutral organic models: weathered boulder, driftwood
and folded throw. These are new Meshy jobs,
not imports from Y2K. Library derivatives target 80k–120k triangles; dense
provider originals remain locally retained. Source requests, generation images,
hashes and mesh checks accompany the models. Object details expose mesh counts
and link to the actual generated input image. Use Original placement for the
full library detail; Light still makes an optional smaller copy.

The broad-frond plant and ornamental grass trials are excluded from this
candidate: the former did not pass cleanup/visual review, and the latter had no
completed model at selection cutoff. No new Y2K or simple primitive assets are added.

## Viewport-aware item previews (rc.13)

The Rhino panel defaults to **Preview → Follow Rhino viewport**. The active
viewport (including a layout detail) is read every half second on the UI thread.
Ghosted gives translucent surfaces, Arctic gives white surfaces and soft shadows,
Shaded gives neutral surfaces, and Rendered uses the original material colours.
Switching the active viewport updates the thumbnails and an open 3D viewer.
The selector can also hold a fixed preview style or use Material colours.

These are approximate web previews, not Rhino viewport captures. Document lighting,
backgrounds, edge settings, custom display modes and ray tracing are not reproduced.
Unsupported modes explicitly fall back to material colours. Placed objects use
Rhino's actual display pipeline; no document geometry, materials, or display settings
are changed by preview selection. Drawing views are unaffected.

Only visible styled thumbnails load live models (up to eight); scrolling away or
opening the enlarged viewer releases their elements. Loading or failed thumbnails
use simplified image styling. Rendered/material thumbnails reuse the existing
coloured PNGs. Material overrides are restored when returning to coloured previews.

Validation: pinned Rhino 8 GA SDK build, material round-trip tests, packaged module
routes, and browser checks of thumbnails, enlarged models and narrow sidebar layout.
Native viewport switching must still be checked after saving work and restarting
Rhino into rc.13. No public release is performed by preparation or local installation.

## Publication record — 19 September 2026

- **Rhino Package Manager: published** `almondbridge 0.6.0-rc.13`, Windows / Rhino 8.0+.
- Source commit: `f83fe392901ed49af38238466bb16809bcd4158e`.
- Artifact: `almondbridge-0.6.0-rc.13-rh8_0-win.yak`.
- SHA-256: `fa40abae6a630fb7fe6afba123ea51f829ca231e1ec57028488f265804a0fe42`.
- Production Yak push succeeded and public `search --all --prerelease almondbridge`
  returned the new version. Users must enable **Include pre-releases**.
- 185 tests, clean wheel/MCP installation, 388 package routes, 421 installed files
  and [CI](https://github.com/liangjunglj-cpu/almond-mcp/actions/runs/35457176696) passed.
- User accepted the preview update and explicitly requested deployment. The full
  native smoke checklist has not been independently recorded; this remains a prerelease.
- Food4Rhino: [existing Almond MCP listing](https://www.food4rhino.com/en/app/almond-mcp)
  updated and saved successfully. rc.13 is the first download, with the uploaded ZIP
  containing the exact published Yak and updated quickstart. Existing app GUID,
  icon, screenshots and historical downloads were preserved. Public description
  explains the library, display-mode approximation and optional PyPI limitation.
- PyPI `almond-mcp 0.6.0rc13`: upload blocked by missing publishing credentials.
  The included Rhino library needs no Python. Optional MCP users must use the
  supplied local wheel until the matching PyPI prerelease is available.

The published Yak is immutable. Documentation/status updates do not replace it.

## Stable 0.6.0 preparation

Prepared 27 September 2026 and published the same day. Source is the rc.13 revision
(`d5610cb`) with version changes (`10acd31`) and two Python fixes found by the
MCP smoke test below. Python package, lockfile, both asset-pack manifests,
bridge csproj and Yak manifest move to `0.6.0`; the Yak description drops the
Include pre-releases note and pins `almond-mcp==0.6.0`; the bundled quickstart
and Food4Rhino text describe the stable package. No C#, models or UI changed,
so the rc.13 panel behaviour (including viewport dragging) is unchanged.

### MCP smoke findings (step 7), 27 September 2026

Run against live Rhino 8 with almondbridge 0.6.0 installed, from a stdio MCP
client, first with the locked dependencies and then with fresh resolution
(`mcp` SDK 2.2.0). `almond-mcp doctor` passed on the first build, but the
server itself did not start, and placement had two defects dating from v0.5.0:

- **Server crash on upgrade.** Retiring the IKEA catalogue syncs it empty; the
  prune deleted asset rows still referenced by recorded scene instances, so any
  state database with IKEA placements failed with `FOREIGN KEY constraint failed`
  at import time. Referenced rows are now kept under library `retired`, out of
  search; unreferenced rows are still deleted. Replayed on a copy of a real
  database: 13 instances kept, 9 assets retired, 7 removed, no FK violations.
- **`place_generated_asset` could not compile.** Material rows were %-formatted
  with doubled braces and then spliced into an f-string, so Roslyn received
  `{{ ... }}`. Any asset with a known material failed after import.
- **Models landed 1000× too large.** Library GLBs are numeric millimetres
  (passport `coordinate_convention.glb_numeric_units: "mm"`), but Rhino's glTF
  import reads metres. Placement now applies 0.001 for such contracts; exchange
  GLBs exported by Rhino stay unscaled. The dimension check compares sorted
  extents, so per-axis size was checked in Rhino separately.

After the fixes, dining chair and bent-plywood lounge chair placed at exact
catalogue width × depth × height (0.0 relative error), upright, bottom-centre
at the origin, on the requested layer with asset ID and passport. Repository
search returned generated models. Regression tests cover all three.

### Artifacts

`tools/prepare_release.ps1` passed on the fixed source: 188 tests, source check,
wheel/sdist audit, clean isolated install (54 MCP tools) with HTTP and MCP search
smoke, bridge build (0 warnings) and Yak audit of 388 routes / 50 models / 10
drawing packages. Artifacts are in `dist/release-0.6.0/`:

- `almondbridge-0.6.0-rh8_0-win.yak` —
  SHA-256 `d1f2a623a0c682ecb447691b367ab7e9aff7203a961017752500b4fd12fd1306`.
  This is the first build, the one under the native smoke test. The Yak carries
  no Python; the rebuild differed only in the recompiled `RhinoAlmondBridge.rhp`
  (unchanged C# source), so the tested package was retained with its ZIP.
- `almond_mcp-0.6.0-py3-none-any.whl` —
  SHA-256 `2abac20c4aaeeefd2ce8c805db997acd5197acbbb7d3a0a081839a959aa2330c`.
- `almond_mcp-0.6.0.tar.gz` —
  SHA-256 `def1d191942992b3af699c05666eea047efa87977c0b808d3a5ead8f1afd8f3f`.
- `almondbridge-0.6.0-food4rhino.zip` and `SHA256SUMS.txt` for the rest.

### Rhino smoke record, 27 September 2026

[Required Rhino smoke test](#required-final-rhino-smoke-test) run on Windows 11
Home 10.0.26200 with Rhino 8.34.26223.11001, almondbridge 0.6.0 installed from
the Yak with SHA-256 `d1f2a623a0c682ecb447691b367ab7e9aff7203a961017752500b4fd12fd1306`
(hash and installed version checked). **Result: pass.**

- Step 7 (MCP): passed after the fixes above, checked by the agent from a
  stdio client against the live bridge.
- Remaining steps (panel, drag/Place/Esc/Light/block reuse/units/Undo/save,
  viewport-following previews, drawings/DXF/downloads, Karamba solve and
  export, lifecycle, 0.5.0 upgrade path): reported passed by the user, who ran
  them in Rhino against the pass criteria. Individual step results were not
  itemised.

### Stable 0.6.0 publication record

Machine-readable record: [publication-0.6.0.json](publication-0.6.0.json).

- **PyPI: published** `almond-mcp 0.6.0` by the maintainer with a project-scoped
  token, before the Yak. PyPI digests match `SHA256SUMS.txt`; a clean
  `uvx --from almond-mcp==0.6.0` reports 0.6.0 and `doctor` passes against Rhino.
- **Rhino Package Manager: published** `almondbridge 0.6.0`, the smoke-tested Yak
  `d1f2a623a0c682ecb447691b367ab7e9aff7203a961017752500b4fd12fd1306`. Plain
  `Yak.exe search almondbridge` (no `--prerelease`) returns 0.6.0, so users no
  longer need **Include pre-releases**.
- [CI](https://github.com/liangjunglj-cpu/almond-mcp/actions/runs/36333172315) passed
  on the fixed source `1fa18ca`.
- **Food4Rhino: pending.** Upload `almondbridge-0.6.0-food4rhino.zip` above rc.13
  on the existing listing using `food4rhino-listing.md`.
