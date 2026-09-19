# Almond Object Archive for Rhino 8

For this prepared release candidate, install the supplied
**almondbridge-0.6.0-rc.6-rh8_0-win.yak**, save your work, restart Rhino,
and run **AlmondLibrary**. This candidate has not yet been published to the
public Package Manager. The package targets Windows / Rhino 8.0+.

The Neo Swiss archive opens in a dockable **Almond Library** panel inside Rhino.
Drag the panel tab beside Layers or Properties, or float it on another monitor.
Rhino remembers its docking position. Use **Open in browser** in the panel or
the **`AlmondLibraryBrowser`** command for the full-size browser view.
The panel has compact search, model cards and full-width object details.
Source links and download links open in your browser. The archive runs locally while Rhino stays
open; no Python, Meshy login, AI subscription or Internet connection is needed
to browse the included files after installation. Rhino's licence is separate.

Search and rotate 47 generated models, inspect the 10 linked drawing packages,
and download GLB, SVG, DXF and A3 SVG sheets. Choose 1:50 or 1:100 drawing views;
DXF geometry uses full-size millimetres. Viewports fit drawings to the screen,
so screen size is not print scale. Import downloaded DXFs into Rhino using
millimetres. GLB downloads retain the original Almond numeric-mm convention
and Y-up coordinates; use the panel's Place action or Almond's MCP placement
workflow for unit and anchor handling.

## Place a model

Drag a thumbnail into a Rhino viewport and release at the insertion point.
An orange bounding outline previews the model's size. Press Esc to cancel;
releasing outside a viewport cancels after a short timeout. You can also click
**Place** and then pick a point, which supports keyboard access and object snaps.
Finish other Rhino commands before placement. The model stays aligned to world
axes with its bottom centre at the chosen point; use Rhino Rotate afterwards.

**Light** targets 20,000 triangles for heavier models, preserving the full mesh
for smaller objects. **Original** keeps the source triangle geometry.
Reduction can alter fine features and silhouette; it is a display approximation.
The original GLB and its derived drawings remain unchanged. A first heavy
placement can take a moment to prepare after you pick the point.

Repeated placements reuse a block definition and material. Objects carry source
records, original checksums, full passports and a derivation record containing
actual triangle counts, geometry fingerprint, units and reduction method.
Undo removes a placement. Use Explode only when you need independent geometry.

Placement is available for the 47 included generated GLBs, inside the Rhino
panel. Browser downloads and the seven community catalogue entries do not have
native placement. Imported models use the current Rhino layer.

The native pointer handoff, reduction, block reuse and undo still require
an interactive Rhino smoke check for this release candidate; the decoder and
browser layout have automated/standalone verification.

Each record includes dimensions, an asset ID, source evidence, generation task
IDs, declared licence and known evidence gaps. Dimensions describe generated
geometry; drawings are silhouettes, not certified construction details.

The models and derived drawings are released as **CC BY 4.0**. Attribute
**Almond generated asset library**, link <https://creativecommons.org/licenses/by/4.0/>,
and note modifications. The package includes source records and licence
notices. The seven additional community drawing elements are catalogue records
only; obtain their files from the linked sources under their own terms.

Saved selections are browser-local. The Rhino archive uses a fresh loopback
port when it starts, so saved selections are not guaranteed across Rhino restarts.
The separately installed Python archive uses a stable configurable port.

## Optional AI/MCP workflow

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). Configure
your MCP client with command `uvx` and these arguments:

```json
["--from", "almond-mcp==0.6.0rc6", "almond-mcp"]
```

This pinned command becomes available after the matching Python release is
published. Use the provided local wheel for prerelease testing beforehand.
The MCP client launches its own stdio server. It connects to the Rhino bridge
on 127.0.0.1:5000; browsing the archive itself does not require this connection.
Do not use the older developer-oriented `AlmondMCPStart` command to configure
an AI client. See the repository README for client-specific setup.

## Troubleshooting

- Archive folder missing: reinstall the full Yak package; copying only the RHP
  is insufficient. Keep its dependencies and `archive` directory together.
- Model download reports the file changed: reinstall that release. The host
  verifies each served file against its bundled checksum.
- Optional drawing element says unavailable: its community model is not bundled.
- Browser cannot connect after quitting Rhino: reopen Rhino and run `AlmondLibrary`.
- Models remain available on disk inside the installed package's
  `archive/files/generated/models` directory; source records are in `archive/evidence`.

Support: <https://github.com/liangjunglj-cpu/almond-mcp/issues>.
