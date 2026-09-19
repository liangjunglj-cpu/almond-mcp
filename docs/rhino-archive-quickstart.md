# Almond workspace for Rhino 8

For this prepared release candidate, install the supplied
**almondbridge-0.6.0-rc.13-rh8_0-win.yak**, save your work, restart Rhino,
and run **Almond**. This candidate has not yet been published to the
public Package Manager. The package targets Windows / Rhino 8.0+.

The archive opens in a dockable **Almond** panel inside Rhino. Its background,
text, controls and font follow Rhino appearance settings, including theme changes.
Drag the panel tab beside Layers or Properties, or float it on another monitor.
Rhino remembers its docking position. Use the **Open in browser** arrow in the compact header or
the **`AlmondLibraryBrowser`** command for the full-size browser view.
The panel has compact search, coloured model cards and full-width object details.
Thumbnails use the models' assigned material colours, not photographic textures.
Source links and download links open in your browser. The archive runs locally while Rhino stays
open; no Python, Meshy login, AI subscription or Internet connection is needed
to browse the included files after installation. Rhino's licence is separate.

Search and rotate 50 generated models, inspect the 10 linked drawing packages,
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

Placement is available for the 50 included generated GLBs, inside the Rhino
panel. Browser downloads and the seven community catalogue entries do not have
native placement. Imported models use the current Rhino layer.

Viewport dragging was confirmed in Rhino by the user on rc.6. The new Karamba
workspace requires native acceptance on this candidate; automated and browser
checks do not establish solver correctness.

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

## Karamba Validation

Choose **Karamba** from the Almond menu, or run **AlmondKaramba** directly.
The models area remains available through **AlmondLibrary**.

1. Select structural curves, shell surfaces/meshes and optional Rhino point
   objects for supports. Click **Use Rhino selection**. Placed visual model
   blocks are not structural analysis models.
2. Set material, total downward load, self-weight and fixed/pinned restraints.
   Selected points define support locations; without points the lowest nodes
   are used. Choose **Require selected points** to disallow that inference.
3. Review sections. The default beam is CHS 114.3 × 4 mm and shell thickness
   is 100 mm. Inferred sections need review. A CHS override uses millimetres
   independently of document units. Truss assemblies retain beam elements;
   axial-only releases are not applied.
4. Use Axonometric, Front or Top and the Members, Supports and Loads toggles.
   Before solving, the diagram is a provisional preview. With no selection it
   is a labelled illustrative frame, with no analysis results.
5. Click **Run Karamba analysis**. The workspace requires the existing direct
   Karamba API and never replaces an unavailable solve with a rule estimate.
   Installation and licence availability are checked in the running Rhino.
6. Read maximum deflection against the indicative L/250 limit and utilization
   against 100%. Missing metrics display as unavailable and cannot pass.
   Toggle utilization colouring, select the highest-utilization source members,
   or save a JSON report containing input IDs, settings, geometry snapshot,
   warnings, result method and timestamp.

Changing analysis settings marks results stale. Recapture after changing Rhino
geometry or document units; the native bridge rejects stale selections. Results
are snapshots, not live monitoring. Overlay/view toggles do not rerun analysis.
Only actual support/load positions and reported utilization are shown after a
solve; no displacement field is returned, so no deformed shape is drawn.

This is first-order analysis of the stated idealisation, not full project-specific
code verification. Review solver warnings and inferred assumptions. The existing
MCP validation tool remains available, with explicitly labelled fallback methods.

## Optional AI/MCP workflow

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). Configure
your MCP client with command `uvx` and these arguments:

```json
["--from", "almond-mcp==0.6.0rc13", "almond-mcp"]
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

In Karamba, press the small **?** beside a heading for guidance. Press it again
or use Escape to close it. The diagrams explain supports and display symbols;
opening help does not change analysis inputs.

Search **organic** for the three detailed natural/textile additions. Choose
**Original** before dragging if you want the complete library mesh. Object
details show actual triangle counts, topology checks and the generated reference
image. Preview colours are Almond materials; source-image textures are not baked
into these geometry editions.

### Preview display mode

The Preview selector defaults to Follow Rhino viewport inside Rhino. Ghosted,
Arctic, Shaded and Rendered are approximated in the thumbnails and enlarged 3D
preview. Choose Material colours to keep colour previews. Custom/unsupported modes
fall back to material colours. Scene lighting and edge settings are not reproduced;
placed objects use Rhino’s actual display mode.
