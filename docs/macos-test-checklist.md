# almondbridge on Rhino 8 for Mac: test checklist

The macOS package (`almondbridge-<version>-rh8_0-mac.yak`, the `net7.0` build) compiles and packages on
Windows, but **nobody has run it on a Mac yet**. Work through this list on a real Mac before the package
is pushed to Yak. Yak versions are immutable, so a broken push cannot be replaced, only superseded.

Write down the result of each step (pass, fail, or the exact message) in the table at the end, and
attach screenshots of anything that looks wrong.

## What you need

- A Mac with **Rhino 8 for Mac** (any service release; note the exact one from *Rhino → About Rhinoceros*)
  and whether it is Apple silicon or Intel.
- [Homebrew](https://brew.sh), then `brew install uv`.
- The macOS Yak from the pull request's CI run: open the PR's *Checks* tab, select *Build and verify release
  candidate*, download the `almond-release-candidate` artifact and unzip it. Inside
  `release-<version>/` is `almondbridge-<version>-rh8_0-mac.yak`, next to `yak-verification-mac.json`.
- Optional: Claude Desktop for macOS, to test the MCP path end to end.

Before you start, turn off **AirPlay Receiver** (*System Settings → General → AirDrop & Handoff*). Since
macOS 12 it listens on port 5000, the bridge's fixed port. Step 2 also checks what happens when it is
left on.

## 1. Install and load

1. Quit Rhino. Install the package with Rhino's Yak CLI:

   ```sh
   "/Applications/Rhino 8.app/Contents/Resources/bin/yak" install ~/Downloads/almondbridge-<version>-rh8_0-mac.yak
   ```

   If that path does not exist, start Rhino and drag the `.yak` file onto the Rhino window instead.
2. Start Rhino. The command history should show:

   ```
   RhinoAlmondBridge: Loading MCP Bridge plugin...
   RhinoAlmondBridge: TCP listener started on port 5000.
   ```

3. Check *Rhino → Settings → Plug-ins*: **RhinoAlmondBridge** is listed and loaded, with no load error.

If the plug-in fails to load, copy the full error text. Also note whether
`~/Library/Application Support/McNeel/Rhinoceros/packages/8.0/almondbridge/` contains `RhinoAlmondBridge.rhp`,
`Microsoft.CodeAnalysis.dll`, `Microsoft.CodeAnalysis.CSharp.dll` and `Newtonsoft.Json.dll`.

## 2. Bridge status and session token

1. Run `AlmondMCPStatus`. Expected: the bridge reports it is listening on 127.0.0.1:5000.
2. In Terminal:

   ```sh
   ls -l ~/Library/Application\ Support/Almond/bridge.token
   ls ~/.local/share/Almond 2>/dev/null && echo "WRONG FOLDER USED"
   ```

   Expected: the token file exists with mode `-rw-------` (owner only), and the second command prints nothing.
3. Optional: turn AirPlay Receiver back on and restart Rhino. Record whether the bridge still binds
   (`TCP listener started` vs `Failed to bind port 5000`) and what step 3's `doctor` says. Then turn it off again.

## 3. doctor

With Rhino open:

```sh
uvx almond-mcp doctor
```

Expected: every check passes, including **bridge listening on 127.0.0.1:5000** and **bridge accepts this
client's session token**. "model files present 0/N" is normal on a fresh install. Paste the full output.

## 4. Panels (web views)

The panels are Eto WebViews, which on macOS are WKWebView rather than Edge WebView2.

1. Run `Almond`. The **Almond** panel opens with the Models thumbnails rendered: not blank, no "script error".
   Search for `chair`, open a model's details, and check that the 3D preview turns.
2. Run `AlmondLibraryBrowser`. The full browser view opens in your default web browser.
3. Run `AlmondResults`. The **Almond Results** panel opens (it can be empty before an analysis).
4. Run `AlmondEnvironment` (Simulation, BETA). The panel renders. After any study run (step 7), its
   *Open folder* button should open the run folder in **Finder**.
5. Check the panel tab icons. The Almond and Almond Results tabs show the almond icon, not a blank square.

## 5. Placement

Set the document units to millimetres, then:

1. Click a model thumbnail's place action. Rhino prompts *Pick model insertion point*, a red preview box
   follows the cursor, and a click places the model as a block.
2. **Drag** a thumbnail from the panel into a viewport and release it. On macOS a drag is expected to
   become a pick: after you release, Rhino prompts for the insertion point and a click places the model.
   (Windows hands the held pointer to the viewport directly; macOS has no equivalent hand-over.) Record
   what happens, especially if the release itself places the model, or if nothing happens.
3. Place the same model again with the light (reduced) detail option, then run `_Undo` once. Only the last
   placement should be removed.

## 6. Structure solve (native engine)

1. Draw a simple portal frame as centre lines (two 3 m columns and a 6 m beam), select it and run
   `AlmondStructure`. Keep **Engine: native**, then run the analysis.
2. The first run downloads the solver through `uvx` (this needs network access) and can take a minute.
   Expected: utilisation results, and the deflected shape drawn in the viewport. `AlmondResults` lists the
   members.
3. Start Rhino from the **Dock** (not from Terminal) for this step, so it gets macOS's minimal `PATH`. The
   solver should still find `uvx` in `/opt/homebrew/bin` (Apple silicon) or `/usr/local/bin` (Intel).
4. Switch **Engine: Karamba** and run again. Expected: no crash. The analysis falls back to an audited
   template or a rule-based estimate, and the warnings include
   `the Karamba3D api path is Windows only in this Almond release`.

## 7. MCP end to end (optional, Claude Desktop)

1. Add the server to `~/Library/Application Support/Claude/claude_desktop_config.json`:

   ```json
   { "mcpServers": { "Almond": { "command": "uvx", "args": ["almond-mcp"] } } }
   ```

   If Claude reports `spawn uvx ENOENT`, replace `"uvx"` with the full path from `which uvx`.
2. Quit Claude Desktop completely (⌘Q) and reopen it. The Almond tools are listed.
3. Ask Claude to run `execute_rhino_script` with a script that adds a sphere. This compiles C# with Roslyn
   on Rhino's .NET runtime. Expected: a sphere appears, and one `_Undo` removes it.
4. Ask for `place_structural_reference`, then `validate_structure` on the placed members. This is the same
   native solve as step 6, driven over the bridge.
5. Optional: run one `analyze_daylight` study on a shoebox room, then `show_environment_result`.

## 8. Shutdown

Quit Rhino. `~/Library/Application Support/Almond/bridge.token` should be gone.

## Results

| Step | Result | Notes |
| --- | --- | --- |
| Rhino version, chip | | |
| 1 Install and load | | |
| 2 Status and token (mode 0600, right folder) | | |
| 2.3 AirPlay Receiver on | | |
| 3 doctor | | |
| 4.1 Almond panel | | |
| 4.2 Library browser | | |
| 4.3 Results panel | | |
| 4.4 Environment panel and Finder | | |
| 4.5 Tab icons | | |
| 5.1 Click placement | | |
| 5.2 Drag placement | | |
| 5.3 Light detail and undo | | |
| 6.1 to 6.3 Native solve, started from the Dock | | |
| 6.4 Karamba fallback | | |
| 7 MCP end to end | | |
| 8 Token removed on quit | | |

If everything passes, the macOS Yak from the same CI run can be pushed alongside the Windows one. Push it
only after this table is filled in.
