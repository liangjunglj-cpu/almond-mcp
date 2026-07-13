# Rhino Manual Test Checklist

Manual verification steps for the almondmcp structural pipeline refactor. Nothing here can be tested in the sandbox; every step needs a real Windows machine with Rhino 8. Work through the steps in order, because later steps depend on earlier ones. For each step, the expected console or JSON output is listed, including the exact warning strings that mark a downgrade.

Prerequisites: Visual Studio 2022 with the .NET desktop development workload, Rhino 8 for Windows, Karamba3D 3.1 (build 3.1.60519) installed for Rhino 8, and internet access for the first NuGet restore. See `RhinoAlmondBridge/BUILD.md` for full details.

## 1. Build the plugin in Visual Studio

1. Open `RhinoAlmondBridge/RhinoAlmondBridge.csproj` in Visual Studio 2022.
2. Select the Release configuration and build (Ctrl+Shift+B).
3. Expect: build succeeds with zero errors. Output lands in `RhinoAlmondBridge\bin\Release\net48\RhinoAlmondBridge.dll`.
4. Confirm the project has no reference to any Karamba assembly. All Karamba access is late bound by reflection in `KarambaAdapter.cs`. If the build asks for a Karamba reference, something regressed; do not add one.
5. Failure modes: NuGet restore errors mean no internet or a wrong feed. Compiler errors in `KarambaAdapter.cs`, `ModelConditioner.cs`, `GhDefinitionRunner.cs`, `StructuralValidator.cs`, or `BridgeServer.cs` mean the C# from this refactor needs fixing; note the first error and file.

## 2. Load the plugin and confirm startup lines

1. Start Rhino 8 and load the DLL (drag it into the viewport or use `PlugInManager`).
2. Expect these exact lines in the Rhino command line:
   ```
   RhinoAlmondBridge: Loading MCP Bridge plugin...
   RhinoAlmondBridge: TCP listener started on port 5000.
   RhinoAlmondBridge: Ready to receive C# scripts from MCP server.
   ```
3. If you instead see `RhinoAlmondBridge: Failed to bind port 5000`, another process owns the port. Close it or change the port in `RhinoAlmondBridgePlugin.cs` and rebuild.
4. Run `AlmondMCPStatus` to confirm the bridge is listening, then start the MCP server (or run `AlmondMCPStart`).
5. On the Python side, the server startup log (stderr) should include `Synced 8 capsule manifests from ...capsules.` and no `Skipping capsule manifest` lines.

## 3. validate_structure on a drawn line (Karamba API path)

1. In Rhino, draw a single straight line, roughly 6 m long in model units (or create it via the `execute_rhino_script` tool so you get the GUID back).
2. Call the MCP tool `validate_structure` with that GUID, `structure_type` "beam", the default 10 kN load, and material "Steel".
3. Expect the Rhino command line to print `RhinoAlmondBridge: Running structural validation...` followed by a `Validation pass:` or `Validation fail:` line.
4. Expect the JSON verdict to start with `[KARAMBA 3.1 API, HIGH CONFIDENCE]`. That prefix is the proof that the direct karambaCommon 3.1 call worked.
5. Check the response body: top level `confidence` is "high", `warnings` is empty or minor, `worst_member_guids` echoes your line's GUID when utilization is nonzero, and `results` carries `analysis_method` "api", plausible `max_deflection_mm` (a few millimetres for a 6 m steel beam under 10 kN), `utilization_ratio` under 1.0, and a nonzero `reactions_kn` roughly equal to self weight plus 10 kN.
6. Also confirm `results.per_element_utilization` is a list of objects of the form `{"source_guids": [...], "utilization": 0.xx}` pointing back at your line.
7. If the verdict instead starts with `[AUDITED TEMPLATE, MEDIUM CONFIDENCE]` or `[RULE-BASED ESTIMATE, LOW CONFIDENCE]`, the API path failed. Read the `warnings` array; the string to look for is `Karamba API path unavailable: api_unavailable: ...`, which lists every folder that was probed for `karambaCommon.dll`. Fix the Karamba install path or set `ALMOND_KARAMBA_DIR` (see BUILD.md) and retry before continuing.

## 4. Fallback behavior when Karamba is missing

This step verifies the loud downgrade chain. Do it on a machine without Karamba, or temporarily force the miss by setting `ALMOND_KARAMBA_DIR` to an empty folder before starting Rhino.

1. Repeat the `validate_structure` call from step 3.
2. Expect NO crash and NO silent success. The call must still return structured JSON.
3. Because every shipped capsule is still `audited: false`, the template path must also refuse, so the expected verdict prefix is `[RULE-BASED ESTIMATE, LOW CONFIDENCE]` and `confidence` is "low".
4. Expect ALL of these warning strings in the `warnings` array:
   - `Karamba API path unavailable: api_unavailable: ...` (with the probed folders)
   - `No audited 'analyze' capsule found for structure_type 'beam'.`
   - `Karamba API and audited template capsules were both unavailable; this is a rule-of-thumb estimate, not FEA.`
5. If any of those warnings is missing while the result is rule based, the loud failure contract is broken; file it as a bug.
6. Restore the real Karamba path afterwards and confirm step 3 gives `[KARAMBA 3.1 API, HIGH CONFIDENCE]` again.

## 5. run_definition refusal on an unaudited capsule

1. Call the MCP tool `list_capsules()`. Expect 8 capsules, all `capability` "analyze", all `audited: false` out of the box.
2. Call `run_gh_definition` with `capsule_id` "karamba_beam_v1" and inputs `{"ALMOND_IN_LINES": {"guids": ["<your line guid>"]}}`.
3. Expect an error JSON refusing to run, with a message containing `is not audited` and a pointer to `capsules/AUTHORING.md`. This refusal happens client side in Python; the Rhino command line must NOT print `Running capsule definition...`, because the bridge is never contacted for a refused capsule.
4. Also probe the validation layer while you are here, expecting errors that name the offending port and never reach Rhino:
   - unknown capsule id: message contains `Unknown capsule_id` plus an `available_capsules` list
   - missing required input: message contains `Missing required input(s)` and `ALMOND_IN_LINES`
   - wrong type (for example `"ALMOND_IN_LOAD_KN": "heavy"`): message contains `must be a finite number`
   - geometry given as a bare list instead of `{"guids": [...]}`: message shows the required `{"guids"` form

## 6. Harness the beam template and run it end to end

1. Follow `capsules/AUTHORING.md` step by step for the beam capsule: open `Grasshopperfiles/Karambafileswithmodel/01_SimpleBeam.ghx`, add the harness params (`ALMOND_IN_LINES`, `ALMOND_IN_LOAD_KN`, `ALMOND_OUT_DISP_MM`, `ALMOND_OUT_UTIL`, `ALMOND_OUT_MASS_KG`) with exact NickNames, wire them in, remove the internal sliders and geometry they replace, group as `ALMOND HARNESS`, test a solve inside Grasshopper, and Save As `Grasshopperfiles/Karambafiles/harnessed/01_SimpleBeam.ghx`.
2. Edit `capsules/karamba_beam_v1.capsule.json` and set `"audited": true`. Restart the MCP server so the capsule registry resyncs, and confirm `list_capsules(audited_only=true)` now returns the beam capsule.
3. Call `run_gh_definition` with `capsule_id` "karamba_beam_v1", your line GUID in `ALMOND_IN_LINES`, and `ALMOND_IN_LOAD_KN` 12.5.
4. Expect the Rhino command line to print `RhinoAlmondBridge: Running capsule definition...`.
5. Expect response JSON with `status` "ok", `analysis_method` "template", `confidence` "medium", `outputs` keyed by the three ALMOND_OUT names with plausible numbers in the declared units (mm, ratio list, kg), `baked_guids` empty (the beam capsule declares no geometry outputs), and `error` null.
6. Warning strings that indicate a broken harness rather than success:
   - `The definition has no params with these required NickNames: ...` means a NickName is misspelled; the run must hard error, not solve.
   - `The definition has no params with these output NickNames: ...` means an output param is missing; also a hard error.
   - `Output 'ALMOND_OUT_...' produced no data.` means the wire into that output param is dead.
   - `[GH error] ...` entries surface component failures inside the definition.
   - `Seed supplied but the definition has no ALMOND_IN_SEED param; seed ignored.` is expected if you pass a seed; it is informational only.
7. Rerun `validate_structure` from step 3 with `ALMOND_KARAMBA_DIR` pointed at an empty folder again. With the beam capsule now audited, the fallback should upgrade one level: expect verdict prefix `[AUDITED TEMPLATE, MEDIUM CONFIDENCE]` and the warning `Template path cannot attribute utilization to individual members; source_guids lists the full input set.`

## 7. Timeout behavior

1. Call `run_gh_definition` on the audited beam capsule with `timeout_s` set to a tiny value such as 1 (or 5) and a decent number of input lines so the solve takes measurable time.
2. Expect one of two structured outcomes, never a hung tool call and never a dead socket:
   - the bridge reports it first: `status` "error" with `error` containing `exceeded the Ns timeout and was aborted`, or the generic bridge line `Execution timed out (Ns).`
   - the Python side reports it first: `status` "error" with message `Capsule 'karamba_beam_v1' timed out (>Ns solver budget).`
3. The Python socket budget is the solver budget plus 15 seconds and the bridge UI wait is the solver budget plus 10 seconds, so in the normal case the bridge answers with structured JSON before the socket gives up. If you see raw `Bridge error:` connection resets instead, the framing broke; report it.
4. Afterwards, confirm Rhino is still responsive and a normal `run_gh_definition` with the default 60 second budget still succeeds. An aborted Grasshopper solve must not poison the next run.
5. Also confirm `validate_structure` still enforces its own 60 second socket budget by returning `Structural validation timed out (>60s).` if you ever push it past a minute.

## 8. Wrap up

1. Rerun the automated suite on the workstation for completeness: `uv run pytest` inside `mcp-rhino-plugin` (23 tests, all green, no Rhino required).
2. Record which verdict prefixes you observed in steps 3, 4, and 6.7, since those three lines are the whole confidence story: api high, template medium, rule based low.
3. Leave `audited` true only for capsules whose harness you personally verified per the checklist at the end of `capsules/AUTHORING.md`. A false flag is honest; a wrong true flag produces fake engineering numbers.
