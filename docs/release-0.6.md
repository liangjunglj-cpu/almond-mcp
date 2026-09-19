# Almond 0.6 release infrastructure

Candidate pair: **almondbridge 0.6.0-rc.7** and **almond-mcp 0.6.0rc7**.
Both are unpublished candidates. The Yak targets **Rhino 8.0 / Windows**;
RhinoCommon remains pinned to 8.0.23304.9001. Plugin identity stays
`c337dbb8-394a-4593-9c2b-a3d7cfc91893`. No Rhino update is required.

## What users receive

The Yak contains the compiled bridge, runtime dependencies, a complete read-only
Object Archive, 47 generated GLBs, contracts, 47 previews, source evidence,
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
It creates `dist/release-0.6.0rc7/` with:

- Python wheel and sdist.
- `almondbridge-0.6.0-rc.7-rh8_0-win.yak`.
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
   `uvx --from almond-mcp==0.6.0rc7 almond-mcp --version` on a clean machine.
3. Authenticate the maintainer's Yak account, then push the exact tested artifact:

   ```powershell
   & 'C:/Program Files/Rhino 8/System/Yak.exe' login
   & 'C:/Program Files/Rhino 8/System/Yak.exe' push ./dist/release-0.6.0rc7/almondbridge-0.6.0-rc.7-rh8_0-win.yak
   & 'C:/Program Files/Rhino 8/System/Yak.exe' search --all --prerelease almondbridge
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

Validation: compare every triangle of all 47 models against the independent
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
