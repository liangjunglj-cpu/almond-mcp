# Food4Rhino listing — ready-to-paste fields

## Updating an existing listing (current release: 0.5.0, both halves aligned)

Steps: sign in at food4rhino.com with your Rhino account → click your
username (top right) → **My apps** (or **Content**) → **Almond MCP** →
**Edit**. Change the fields below, then **Save** at the bottom.

**1. Short Description** — replace with:

```
Connect Rhino 8 to Claude AI via MCP: semantic scene ledger, curated asset and PBR material libraries, layout validation, Karamba3D-backed structural checks with exportable reports, and portable asset contracts for Blender/Unreal. Free & open source (MIT).
```

**2. Body** — replace the two feature paragraphs with the *Description*
section below (it now leads with materials and cross-app exchange).

**3. Version / release notes** — set to:

```
almondbridge 0.5.0 / almond-mcp 0.5.0

- Installs on EVERY Rhino 8 service release (8.0+). Earlier builds were
  tagged rh8_32 and were invisible in the Package Manager to users below
  8.32 - if you could not find the package before, you can now.
- Curated PBR material library: assign_material writes a physically-based
  Rhino material plus machine-readable metadata, so GLB and Datasmith
  carry real materials into Unreal instead of guessed display colours.
- Cross-application asset exchange: export_asset_contract /
  import_asset_contract move assets between Rhino, Blender and Unreal with
  dimensions, anchors and material identity preserved; Almond restores the
  metadata and colours that glTF drops, and collapses duplicate materials.
- Structural validation runs are recorded and exportable as Markdown
  reports; Karamba3D 3.1 binds correctly when installed via the Package
  Manager.
```

**4. Downloads** — edit the existing file entry (or add a new one and
delete the old):

| Sub-field | Value |
| --- | --- |
| File Title | `almondbridge 0.5.0 — Rhino 8 bridge plugin (Windows)` |
| Description | `Rhino-side bridge for the Almond MCP server. Easiest install: Rhino 8 _PackageManager, search "almondbridge" (works on any Rhino 8 release). This download is the same package for offline install. The AI-side server installs with: uvx almond-mcp (PyPI).` |
| File | `dist\yak\almondbridge-0.5.0-rh8_0-any.yak` |

Everything else — Title, GUID, License, URLs, icon, Platform — stays as
it is. Re-saving may put the app back into moderation for a short time;
that is normal and the existing page stays live meanwhile.

---

## Exact "Create App" form fields (matched to the live form, 2026-07-14)

| Form field | Value |
| --- | --- |
| **Title** | `Almond MCP` |
| **Short Description** (max 255 chars) | `Connect Rhino 8 to Claude AI via MCP: semantic scene ledger, curated asset libraries with real dimensions, layout validation, Karamba3D-backed structural checks with exportable reports, drawing recipes, and C# scripting. Free & open source (MIT).` |
| **Body** | use the long **Description** section below |
| **Category** (max 3, CTRL-click) | `Machine Learning (ML)`, `Architecture`, `Development` (pick nearest names offered) |
| **GUID** | `c337dbb8-394a-4593-9c2b-a3d7cfc91893` (the plugin's permanent ID — lets Rhino link the installed plugin to this listing) |
| **License** | `MIT` (or Other License → https://github.com/liangjunglj-cpu/almond-mcp/blob/master/LICENSE) |
| **Support Email** | `liangjung.lj@gmail.com` |
| **Support Forum URL** | `https://github.com/liangjunglj-cpu/almond-mcp/issues` |
| **Web URL** | `https://github.com/liangjunglj-cpu/almond-mcp` |
| **Project Icon** | `assets\almond-icon-512.png` (square PNG, well under size limits) |
| **Platform** | check **Rhino \| Windows \| Version 8** only (the form itself warns not to also mark Grasshopper unless GH-only) |
| **Trial/Commercial App** | leave **unchecked** (fully free) |

**Downloads section** (Add new file):

| Sub-field | Value |
| --- | --- |
| File Title | `almondbridge 0.2.3 — Rhino 8 bridge plugin (Windows)` |
| Description | `Rhino-side bridge for the Almond MCP server. Easiest install: Rhino 8 _PackageManager, search "almondbridge". This download is the same package for offline install (drag onto Rhino). The AI-side server installs with: uvx almond-mcp (PyPI).` |
| Downloads Type | the Windows/file option offered |
| File | `dist\yak\almondbridge-0.2.3-rh8_32-any.yak` — if `.yak` is not an accepted extension, zip it first (`almondbridge-0.2.3.zip`) and say so in the description |

Add 2–4 screenshots from `assets\screenshots\` after the app is created
(F4R lets you attach images/media on the app page).

---

Submit at https://www.food4rhino.com → sign in with your Rhino account
(same one used for `yak login`) → My apps → **Add App**. Paste the fields
below. Keep the app name and icon stable across updates.

---

## App name

```
Almond MCP
```

## Tagline / one-liner (where a short summary field is offered)

```
Let Claude design in Rhino 8 — with real dimensions, layout validation, and Karamba structural checks.
```

## Category / platform

- Platform: **Rhino** (Windows), works alongside **Grasshopper**
- Category: AI / Automation / Development (pick the closest F4R offers;
  "Utilities" as fallback)

## Tags / keywords

```
AI, MCP, Claude, automation, LLM, Karamba, structural analysis, furniture, scene layout, scripting
```

## Description (long)

```
Almond connects Rhino 8 to Claude (or any MCP client) through a semantic
design layer, so a language model can build with spatial awareness instead
of guessing:

- PBR materials with meaning: a curated material library assigns real
  physically-based Rhino materials and writes machine-readable metadata
  onto each object, so GLB export and Datasmith carry true materials into
  Unreal and remap to your master materials by slot name.
- Cross-application asset exchange: assets move between Rhino, Blender and
  Unreal with dimensions, anchors, clearances and material identity intact.
  Almond restores the metadata and colours that glTF silently drops, and
  collapses the duplicate materials importers create.

- A persistent scene ledger (SQLite): scenes, rooms, placed instances,
  revision history. The model queries the current state instead of
  hallucinating it.
- Curated asset libraries with spatial contracts: real catalogue
  dimensions, anchor points, footprints, functional clearances, and
  collision shapes. Placements respect ergonomics, and every placement is
  dimension-checked against the catalogue.
- Layout validation: R-tree collision and room-containment checks the
  model runs before committing a layout.
- Structural validation with real FEA: generated geometry is checked
  through Karamba3D 3.1 when installed (bound at runtime - never bundled),
  with honest fallbacks and confidence labels. Every run is recorded and
  exportable as a Markdown validation report (deflection vs L/250,
  utilization, reactions).
- Drawing recipes: layer standards, plot weights, and linetypes applied
  as one command.
- Full C# scripting: compile-and-run RhinoCommon scripts, headless
  Grasshopper execution, GLB export.

The plugin in this listing is the Rhino-side bridge (almondbridge on the
Package Manager). It listens on 127.0.0.1:5000 (local only) and starts
with Rhino. The AI-facing server installs separately in one line:
uvx almond-mcp (PyPI).

No 3D models are bundled. The furniture/drawing libraries ship as metadata
manifests; each user downloads model files from their original 3D
Warehouse pages with "almond-mcp fetch-assets", which verifies checksums.
Not affiliated with Inter IKEA Systems, Trimble, or Karamba3D GmbH.

Open source (MIT): https://github.com/liangjunglj-cpu/almond-mcp
```

## Features (bullet list field, if separate)

```
- Claude drives Rhino 8 through MCP: modeling, furnishing, drawing, analysis
- Persistent scene ledger with rooms, instances, and revision history
- Curated furniture/drawing libraries with real dimensions and clearances
- Automatic placement QA: bounds checked against catalogue dimensions
- Layout validation: collision + room containment before committing
- Karamba3D 3.1 structural checks (real FEA when installed) with exportable Markdown reports
- Drawing recipes: layer standards, plot weights, linetypes in one command
- C# RhinoCommon script execution and headless Grasshopper runs
- Local-only TCP bridge (127.0.0.1); indexed files only, never arbitrary paths
```

## System requirements

```
Rhino 8 for Windows. The MCP server requires uv (astral.sh/uv) and an MCP
client such as Claude Desktop or Claude Code. Optional: Karamba3D 3.1 for
FEA-backed validate_structure; a free Trimble account to download the
optional furniture/drawing model files.
```

## Installation instructions

```
1. In Rhino 8: _PackageManager -> search "almondbridge" -> Install ->
   restart Rhino. The bridge starts automatically (AlmondMCPStatus checks).
2. Install uv: winget install astral-sh.uv
3. Add to your Claude Desktop config (%APPDATA%\Claude\
   claude_desktop_config.json) under mcpServers:
   "Almond": { "command": "uvx", "args": ["almond-mcp"] }
   (Claude Code: claude mcp add Almond -- uvx almond-mcp)
4. Restart Claude. Optional: uvx almond-mcp fetch-assets --open for the
   asset libraries, uvx almond-mcp doctor for a health check.
Full guide: https://github.com/liangjunglj-cpu/almond-mcp
```

## License

```
Free, open source (MIT). Third-party notices included in the package.
```

## Links

- Website / support: `https://github.com/liangjunglj-cpu/almond-mcp`
- Issues: `https://github.com/liangjunglj-cpu/almond-mcp/issues`
- PyPI (server): `https://pypi.org/project/almond-mcp/`

## Version + release notes (current)

```
almondbridge 0.2.3 / almond-mcp 0.3.0

- Bridge auto-starts with Rhino; resolves libraries from the user data dir
- Karamba3D 3.1 binds via reflection (Package Manager installs supported)
- Structural validation runs are recorded and exportable as Markdown reports
- Placement QA: catalogue dimension checks and manifest-driven geometry corrections
- Scene ledger: storey-aware placement defaults, room upsert by name, delete APIs
```

## Media

- Icon: `assets/almond-icon-512.png` (F4R usually wants ~200-512px square)
- Screenshots (in `assets/screenshots/`, from the ARCC tower stress test):
  - `arcc_final_persp.png` — cable-stayed tower built end-to-end by Claude via Almond
  - `arcc_front.png` — elevation matching the reference drawing
  - `arcc_final_interior.png` — office interior: castellated beams + placed IKEA-catalogue furniture
  - `arcc_final_facade.png` — corrugated polycarbonate facade detail (1:25 spec)
- Optional: a short screen capture of Claude placing furniture / running
  validate_structure makes a strong hero video.

## Submission notes

- F4R review can take a few days; the download section can simply state
  "Install via Rhino 8 Package Manager (search: almondbridge)" rather than
  uploading a file — that keeps Yak the single source of truth. If F4R
  requires an uploaded file, attach the same .yak you pushed
  (dist/yak/almondbridge-0.2.3-rh8_32-any.yak).
- Keep the almond icon identical to the Yak package icon so the two
  listings read as one product.
