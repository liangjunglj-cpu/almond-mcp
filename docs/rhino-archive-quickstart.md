# Almond Object Archive for Rhino 8

Install **almondbridge** from Rhino's `_PackageManager`, restart Rhino, and run
**`AlmondLibrary`**. For this release candidate, enable **Include pre-releases**
and select **0.6.0-rc.4**. The package is prepared for Windows / Rhino 8.0+.

The Neo Swiss archive opens in your browser. It runs locally while Rhino stays
open; no Python, Meshy login, AI subscription or Internet connection is needed
to browse the included files after installation. Rhino's licence is separate.

Search and rotate 47 generated models, inspect the 10 linked drawing packages,
and download GLB, SVG, DXF and A3 SVG sheets. Choose 1:50 or 1:100 drawing views;
DXF geometry uses full-size millimetres. Viewports fit drawings to the screen,
so screen size is not print scale. Import downloaded DXFs into Rhino using
millimetres. GLB downloads retain the original Almond numeric-mm convention
and Y-up coordinates; use Almond's MCP placement workflow for spatial-contract
handling. The archive does not automatically place objects into the Rhino scene.

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
["--from", "almond-mcp==0.6.0rc4", "almond-mcp"]
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
