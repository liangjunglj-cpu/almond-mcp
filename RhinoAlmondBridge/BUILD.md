# Building RhinoAlmondBridge

## Prerequisites

1. Visual Studio 2022 (any edition) with the ".NET desktop development" workload.
2. Rhino 8 for Windows installed.
3. Karamba3D 3.1 (build 3.1.60519) installed for Rhino 8. Optional at build time, required at runtime for the "api" analysis path.
4. Internet access on the first build so NuGet can restore RhinoCommon, Grasshopper, Microsoft.CodeAnalysis.CSharp, and Newtonsoft.Json.

## Build steps

1. Open `RhinoAlmondBridge.csproj` in Visual Studio (File, Open, Project/Solution). Visual Studio generates a solution around it.
2. Select the `Release` configuration.
3. Build (Ctrl+Shift+B). Output lands in `RhinoAlmondBridge\bin\Release\net48\RhinoAlmondBridge.dll`.
4. Rename or copy `RhinoAlmondBridge.dll` to `RhinoAlmondBridge.rhp` if your install flow loads `.rhp` files, or drag the DLL onto Rhino once; Rhino registers plugin assemblies either way through `PlugInManager`.

The project intentionally has NO reference to any Karamba assembly. Do not add one. All Karamba access is late bound through reflection inside `KarambaAdapter.cs`, so the plugin compiles and runs on machines without Karamba and simply reports the api path as unavailable there.

## Where the Karamba 3.1 DLLs live

The Karamba installer for Rhino 8 places its assemblies in the Rhino plugin folder:

```
C:\Program Files\Rhino 8\Plug-ins\Karamba\
    karambaCommon.dll     (the API the adapter binds to)
    Karamba.dll           (loaded when present)
    Karamba.gha           (Grasshopper components, not used by the adapter)
```

If Karamba was installed through the Rhino package manager instead, the files live under:

```
%APPDATA%\McNeel\Rhinoceros\packages\8.0\Karamba3D\<version>\
```

## How the adapter resolves Karamba at runtime

`KarambaAdapter` probes in this order and stops at the first hit:

1. `KarambaAdapter.OverridePluginPath` when set from code.
2. The `ALMOND_KARAMBA_DIR` environment variable when set.
3. `C:\Program Files\Rhino 8\Plug-ins\Karamba` and `...\Karamba3D`.
4. The yak package folders under `%APPDATA%\McNeel\Rhinoceros\packages\8.0`.
5. Before all of that, if the Karamba Grasshopper plugin already loaded `karambaCommon` into the process, that loaded assembly is reused directly.

A hit means a folder containing `karambaCommon.dll`. The adapter calls `Assembly.LoadFrom` on it, hooks `AssemblyResolve` so Karamba's own dependencies resolve from the same folder, and then drives everything through `KarambaCommon.Toolkit` via reflection. If no folder is found, every analysis request degrades to the template capsule path, then to the rule based estimate, and the failure reason (`api_unavailable: ...`) appears in the response warnings. Nothing throws.

If your Karamba sits somewhere unusual, set the environment variable before starting Rhino:

```
setx ALMOND_KARAMBA_DIR "D:\Tools\Karamba"
```

## What to check in the Rhino command line on first load

1. Start Rhino 8 and load the plugin (drag the DLL into the viewport or use `PlugInManager`).
2. Expect these lines:
   ```
   RhinoAlmondBridge: Loading MCP Bridge plugin...
   RhinoAlmondBridge: TCP listener started on port 5000.
   RhinoAlmondBridge: Ready to receive C# scripts from MCP server.
   ```
3. If port 5000 is taken you will instead see `Failed to bind port 5000`. Close the other process or change the port in `RhinoAlmondBridgePlugin.cs`.
4. Run `AlmondMCPStatus` to confirm the bridge is listening.
5. To confirm the Karamba api path, send a `validate` request (or use the MCP `validate_structure` tool) against a simple line and check the verdict prefix:
   `[KARAMBA 3.1 API, HIGH CONFIDENCE]` means the direct API worked.
   `[AUDITED TEMPLATE, MEDIUM CONFIDENCE]` means the API was unavailable but an audited capsule ran.
   `[RULE-BASED ESTIMATE, LOW CONFIDENCE]` means both were unavailable; check the `warnings` array in the response for the `api_unavailable` reason, which lists every folder that was probed.

## Directory expectations at runtime

The bridge locates support folders by walking up from the plugin DLL, with environment variable overrides:

| Purpose | Env override | Default search |
|---|---|---|
| GHX library | `RHINO_MCP_LIBRARY_DIR` | nearest `Grasshopperfiles` ancestor folder |
| Capsule manifests | `RHINO_MCP_CAPSULE_DIR` | nearest `capsules` ancestor folder |
| Karamba DLLs | `ALMOND_KARAMBA_DIR` | standard Rhino 8 Karamba locations above |

Keep `capsules\*.capsule.json` next to the repository root (the folder Agent 1 populated) so `run_definition` can resolve `capsule_id` values without an explicit `manifest_path`.
