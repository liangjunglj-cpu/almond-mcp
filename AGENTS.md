# Setup contract for AI assistants

You are setting up **Almond MCP** — this specific project, not a generic
"Rhino MCP". Follow these steps exactly. Everything can be done headlessly.

## Do NOT

- **Do not substitute another implementation.** `rhino-mcp`,
  `Rhino-MCP-Platform`, `rhino-mcp-router`, and similar are *different,
  unrelated products*. The only two artifacts of this project are:
  - Rhino plugin: **`almondbridge`** (Rhino 8 Package Manager / Yak)
  - MCP server: **`almond-mcp`** (PyPI, run with `uvx almond-mcp`)
- **Do not upgrade or downgrade Rhino.** almondbridge ≥ 0.2.4 installs on
  every Rhino 8 service release (yak tag `rh8_0`). There is no minimum
  service release. If the Package Manager shows no result, the machine is
  not on Rhino 8, or its package index needs a refresh — never "fix" this
  by updating Rhino.
- Do not clone or build this repo for a normal install; use the published
  packages.
- Do not modify or remove other entries in the user's MCP config.

## Install steps (Windows, Rhino 8)

1. **Verify Rhino 8 exists** (do not install/upgrade it yourself):
   `Test-Path "C:\Program Files\Rhino 8\System\Rhino.exe"`
2. **Install the bridge headlessly** (no GUI needed):
   ```powershell
   & "C:\Program Files\Rhino 8\System\Yak.exe" install almondbridge
   ```
   (Equivalent GUI path: `_PackageManager` in Rhino → search `almondbridge`.)
3. **Install uv if missing** (`Get-Command uv` to check):
   ```powershell
   winget install astral-sh.uv
   ```
4. **Register the MCP server** with the user's client — command `uvx`,
   args `["almond-mcp"]`, stdio transport:
   - Claude Desktop: add under `mcpServers` in
     `%APPDATA%\Claude\claude_desktop_config.json`:
     `"Almond": { "command": "uvx", "args": ["almond-mcp"] }`
   - Claude Code: `claude mcp add Almond -- uvx almond-mcp`
   - Codex CLI: `codex mcp add Almond -- uvx almond-mcp` (or the
     equivalent `[mcp_servers.Almond]` entry with `command = "uvx"`,
     `args = ["almond-mcp"]` in `~/.codex/config.toml`)
5. **Start (or restart) Rhino 8.** The bridge auto-starts and listens on
   `127.0.0.1:5000` (local only). In Rhino, `AlmondMCPStatus` confirms it.
6. **Verify end to end:**
   ```powershell
   uvx almond-mcp doctor
   ```
   All checks should pass while Rhino is open. The
   "model files present 0/N" state is normal on a fresh install.
7. **Hand the asset step back to the human.** Downloading the optional
   furniture/drawing models requires *their* Trimble sign-in:
   `uvx almond-mcp fetch-assets --open` opens each source page; re-running
   `fetch-assets` verifies checksums. Do not attempt to automate the
   downloads or source the files from anywhere else.

## Install steps (macOS, Rhino 8 for Mac) — experimental

The macOS package (`almondbridge-<version>-rh8_0-mac.yak`) is built but not
yet tested on a Mac or published. If the Package Manager on a Mac shows no
`almondbridge`, the macOS package is not published yet: say so to the user.
Do not substitute another product, and do not upgrade Rhino.

1. **Verify Rhino 8 for Mac exists** (do not install/upgrade it yourself):
   `test -d "/Applications/Rhino 8.app" && echo ok`
2. **Install the bridge:** `_PackageManager` in Rhino → search `almondbridge`
   (headless: `"/Applications/Rhino 8.app/Contents/Resources/bin/yak" install almondbridge`).
3. **Install uv if missing** (`command -v uv` to check): `brew install uv`
4. **Register the MCP server** — command `uvx`, args `["almond-mcp"]`:
   - Claude Desktop: add under `mcpServers` in
     `~/Library/Application Support/Claude/claude_desktop_config.json`:
     `"Almond": { "command": "uvx", "args": ["almond-mcp"] }`. If Claude
     reports `spawn uvx ENOENT`, use the absolute path from `which uvx`.
   - Claude Code / Codex CLI: same commands as on Windows.
5. **Start (or restart) Rhino 8.** `AlmondMCPStatus` confirms the bridge. The
   session token is `~/Library/Application Support/Almond/bridge.token`.
6. **Verify:** `uvx almond-mcp doctor`. If the bridge is not listening on
   5000, ask the user to turn off AirPlay Receiver (System Settings → General
   → AirDrop & Handoff), which uses port 5000 on macOS 12+.
7. Same asset hand-over as step 7 above. Karamba3D is Windows only; on macOS
   `validate_structure` solves line models with the native solver and falls
   back to the template or rule-based estimate for shells.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Package Manager / `yak install` finds nothing | Not Rhino 8, or stale index — retry; never upgrade Rhino to fix this |
| `doctor`: bridge not listening on 5000 | Rhino isn't running, or the plugin didn't load — restart Rhino, run `AlmondMCPStatus` |
| Bridge replies `unauthorized` / `doctor`: token not accepted | The bridge only accepts requests carrying this Rhino session's token (written to `%LOCALAPPDATA%\Almond\bridge.token` at Rhino start). Update `almond-mcp` to the version matching almondbridge and restart the MCP client; after a Rhino restart nothing else is needed. Never disable or bypass the check |
| "file is outside its configured library" on placement | bridge older than 0.2.4 — `yak install almondbridge` again and restart Rhino |
| Ctrl+Z says nothing to undo after a script error (Delete still works) | bridge older than 0.7.1 leaked an Undo record after rolling back a failed script - update almondbridge; restart Rhino to clear the stuck state |
| `validate_structure` says rule_based / low confidence | Karamba3D 3.1 not installed — optional; install only if the user wants FEA |
| Claude/Codex doesn't show the tools | MCP client wasn't fully restarted (Claude Desktop: quit from the system tray, not just the window) |

## For agents working in this repo (development)

- For generated models and derived drawings, follow
  `docs/generation-source-documentation.md`: record item-level sources and
  actual generation inputs, preserve unknowns, and distinguish later
  references from original inputs. Refresh `GeneratedAssetfiles/source-register.json`
  after catalogue edits and run `tools/document_generation_sources.py --check`
  before packaging.

- Python ≥3.12, `uv run pytest` (set `UV_LINK_MODE=copy` on OneDrive paths;
  never sync the checkout's `.venv` while a live MCP server runs from it —
  use `UV_PROJECT_ENVIRONMENT` pointing to a scratch dir instead).
- Bridge: .NET SDK, `dotnet build -c Release` in `RhinoAlmondBridge/`;
  keep RhinoCommon pinned to the 8.0 GA SDK (the yak version tag equals
  the SDK compiled against). Yak versions are immutable — never push an
  unverified build.
- Licensing: `docs/licensing-audit.md` — downloaded 3D Warehouse models and
  Karamba/Kangaroo examples must never enter any distribution artifact.
