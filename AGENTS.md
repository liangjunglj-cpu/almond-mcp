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

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Package Manager / `yak install` finds nothing | Not Rhino 8, or stale index — retry; never upgrade Rhino to fix this |
| `doctor`: bridge not listening on 5000 | Rhino isn't running, or the plugin didn't load — restart Rhino, run `AlmondMCPStatus` |
| "file is outside its configured library" on placement | bridge older than 0.2.4 — `yak install almondbridge` again and restart Rhino |
| `validate_structure` says rule_based / low confidence | Karamba3D 3.1 not installed — optional; install only if the user wants FEA |
| Claude/Codex doesn't show the tools | MCP client wasn't fully restarted (Claude Desktop: quit from the system tray, not just the window) |

## For agents working in this repo (development)

- Python ≥3.12, `uv run pytest` (set `UV_LINK_MODE=copy` on OneDrive paths;
  never sync the checkout's `.venv` while a live MCP server runs from it —
  use `UV_PROJECT_ENVIRONMENT` pointing to a scratch dir instead).
- Bridge: .NET SDK, `dotnet build -c Release` in `RhinoAlmondBridge/`;
  keep RhinoCommon pinned to the 8.0 GA SDK (the yak version tag equals
  the SDK compiled against). Yak versions are immutable — never push an
  unverified build.
- Licensing: `docs/licensing-audit.md` — downloaded 3D Warehouse models and
  Karamba/Kangaroo examples must never enter any distribution artifact.
