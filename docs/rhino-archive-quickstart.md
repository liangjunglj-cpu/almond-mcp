# Almond workspace for Rhino 8

Install **almondbridge 0.7.0-rc.1** from Rhino's Package Manager (search
`almondbridge` with **Include pre-releases** ticked), or install the supplied
**almondbridge-0.7.0-rc.1-rh8_0-win.yak**. Save your work, restart Rhino, and
run **Almond**. Windows / Rhino 8.0+. This is a pre-release; the stable version
remains 0.6.0.

Browsing and placing the included library models need neither Python nor an
MCP client. The structural engine and the optional AI workflow use the matching
`almond-mcp 0.7.0rc1` Python package through uv (see below).

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

Karamba results come from your own Karamba installation; Almond's automated
and browser checks do not establish solver correctness.

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

## Structural Validation

Choose **Structure** from the Almond menu, or run **AlmondStructure** (the older
**AlmondKaramba** still works). The step-by-step guide is the
[Structure workspace tutorial](https://github.com/liangjunglj-cpu/almond-mcp/blob/master/docs/structural-tutorial.md).

**Almond native** is built in. Rhino runs `uvx almond-mcp@0.7.0rc1 solve`, so uv
must be installed (`winget install astral-sh.uv`); the first run downloads the
engine, later runs take a few seconds. It analyses frames drawn as centre lines:

- loads: total load, floor area loads (imposed and build-up), placed Almond models, self-weight;
- EN 1990 load combinations from the selected design code (Eurocode recommended
  values by default; National Annex profiles can be added);
- rigid or simple (pinned beam end) connections, and per-curve `almond:release`;
- per-curve sections with `almond:section` user text (`rect 300x640`, `box 200x300x8`,
  `chs 114.3x4`, mm unless a unit follows); otherwise inferred, or CHS 114.3 × 4;
- stability: alpha-cr, sway imperfections and P-Delta second-order analysis below 10;
- EN 1993-1-1 steel member checks: section class, buckling curves by fabrication,
  flexural buckling with Annex B interaction;
- the deflected shape or first buckling mode in the viewport, and every member,
  support and combination in the **Almond Results** panel (`AlmondResults`), with CSV export.

Concrete, timber and aluminium results are indicative: forces, deflection and
stability are computed, but EN 1992/1995/1999 are not applied, so there is no
capacity pass/fail. Prismatic solids are read as their centre lines; other solids
are skipped with a warning. One study takes at most 200 selected objects.
**Karamba3D** needs its own installation and licence and also handles shells.
Developers can point the panel at a checkout with `ALMOND_SOLVER_COMMAND`
(for example `"<repo>\.venv\Scripts\python.exe" -m almond_mcp`).

Changing settings marks results stale; recapture after changing Rhino geometry.
Results are snapshots, not live monitoring. This is design-stage screening of the
stated idealisation, not a substitute for an engineer's design and sign-off.

## Optional AI/MCP workflow

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). Configure
your MCP client with command `uvx` and these arguments:

```json
["--from", "almond-mcp==0.7.0rc1", "almond-mcp"]
```

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
