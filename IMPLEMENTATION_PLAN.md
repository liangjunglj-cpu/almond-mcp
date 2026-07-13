# Almond MCP Structural Pipeline Refactor — Implementation Plan

Scope this session: Phases 1 to 3. Wasp is spec'd but not built.
Baseline commit: `4195374`. All work is diffable against it.

## Goals

1. Replace fuzzy NickName template scraping with a direct Karamba 3.1 (build 3.1.60519) API path.
2. Turn library GHX files into **capsules**: file + JSON sidecar manifest with a typed input/output contract.
3. Add one generic bridge operation `run_definition` so any audited GHX (Karamba, Kangaroo, later Wasp) runs through the same door.
4. Loud failure everywhere. No silent fallback masquerading as FEA.

## Agent assignments

| Agent | Owns | Deliverables |
|---|---|---|
| 1 Schema | `capsules/`, `ghx_parser.py`, `retrieval_store.py` | `capsules/capsule.schema.json`, 8 Karamba manifests, `capsules/AUTHORING.md`, manifest loading in parser/store |
| 2 C# | `RhinoAlmondBridge/` | `KarambaAdapter.cs`, `ModelConditioner.cs`, rewritten `StructuralValidator.cs`, `GhDefinitionRunner.cs`, `BridgeServer.cs` routing |
| 3 Python | `server.py` | `run_gh_definition` + `list_capsules` MCP tools, `validate_structure` as wrapper, per-element diagnostics, `tests/test_capsules.py` |
| 4 Verify | everything | test run, contract cross-check, `docs/RHINO_TEST_CHECKLIST.md` |

Order: 1 → (2 ∥ 3) → 4.

## Shared contract: capsule manifest (sidecar `<name>.capsule.json`)

```json
{
  "capsule_id": "karamba_beam_v1",
  "version": 1,
  "capability": "analyze",            // analyze | generate | form_find | aggregate
  "plugin_dependencies": [{"name": "Karamba3D", "min_version": "3.1"}],
  "definition_file": "Karamba_Analysis_Example_1D_20220524.ghx",
  "title": "Simple beam bending and deflection",
  "description_for_llm": "When to use, assumptions, limits.",
  "inputs": [
    {"name": "ALMOND_IN_LINES", "type": "curve[]", "units": "m", "required": true,
     "description": "Beam axis curves, node-merged"},
    {"name": "ALMOND_IN_LOAD_KN", "type": "number", "units": "kN", "required": false, "default": 10.0}
  ],
  "outputs": [
    {"name": "ALMOND_OUT_DISP_MM", "type": "number", "units": "mm",
     "semantics": "max_nodal_displacement"},
    {"name": "ALMOND_OUT_UTIL", "type": "number[]", "semantics": "per_element_utilization"}
  ],
  "binding": "reserved_nicknames",     // params in GHX carry these exact NickNames
  "confidence": "template",            // api > template > rule_based
  "audited": true
}
```

Rules:
- Binding is exact NickName match on reserved `ALMOND_IN_*` / `ALMOND_OUT_*` names. Any required input unbound → hard error, no solve.
- Units are declared, never guessed. C# converts explicitly at the boundary.
- Existing example GHX files WITHOUT harness params get manifests with `"audited": false` and are retrieval context only; `run_definition` refuses them.

## Shared contract: bridge payload (TCP 127.0.0.1:5000, JSON, existing framing)

New request type:

```json
{"type": "run_definition",
 "capsule_id": "karamba_beam_v1",
 "manifest_path": "<abs path to sidecar>",
 "inputs": {"ALMOND_IN_LINES": {"guids": ["..."]}, "ALMOND_IN_LOAD_KN": 12.5},
 "seed": 42, "timeout_s": 60}
```

Input value forms: `{"guids": [...]}` (resolve from RhinoDoc), raw number, string, bool, `[numbers]`.

Response:

```json
{"status": "ok|error", "capsule_id": "...",
 "outputs": {"ALMOND_OUT_DISP_MM": 14.2, "ALMOND_OUT_UTIL": [0.31, 0.87]},
 "baked_guids": [], "analysis_method": "api|template|rule_based",
 "confidence": "high|medium|low", "warnings": [], "error": null}
```

`validate` (existing type) is kept for compatibility but internally routes to the Karamba API path first, template capsule second, rule based last — and the returned `verdict` string must name the method, e.g. `"[RULE-BASED ESTIMATE, LOW CONFIDENCE] ..."`.

## Phase detail

### Phase 1 — Capsule contracts (Agent 1)
- JSON Schema for manifests, validated at load.
- Manifests for: beam, truss, shell, frame, canopy, gridshell, membrane, highrise (the 8 in `TemplateMap`), marked `audited: false` until the user adds harness params in GH (AUTHORING.md explains exactly how: create GH params, set NickNames, group them, save-as into `Karambafiles/harnessed/`).
- `ghx_parser.py`: load sidecar when present, merge into `GHPhysicsContext.metadata`.
- `retrieval_store.py`: capsule table or asset kind so `list_library`/search surface capsule_id, capability, audited flag.

### Phase 2 — Karamba API direct (Agent 2)
- `KarambaAdapter.cs`: ALL karambaCommon 3.1 calls behind this one file. Late-bind via reflection OR compile-time reference to Karamba DLLs from the Rhino 8 plugin dir with `<Private>false</Private>`; agent picks reflection if DLL path handling is fragile, and documents the choice.
- Pipeline: resolve GUIDs → `ModelConditioner` (merge nodes at doc tolerance, split members at intersections, classify curve→beam / mesh|brep→shell, infer section from drawn geometry where possible) → build model (LineToBeam / MeshToShell, supports from declared anchors else lowest-Z nodes, self-weight + imposed load) → ThI analysis → per element utilization, max displacement, reactions.
- Result includes worst-member GUIDs so the LLM can edit only offenders.
- `GhDefinitionRunner.cs`: contract-bound GHX execution for audited capsules (exact NickName binding, hard error on unbound required input, typed output extraction with declared units).
- `StructuralValidator.cs` becomes an orchestrator: api → template → rule_based, each clearly labeled.
- Must compile against net48, RhinoCommon 8, Grasshopper 8. No compile possible in sandbox: code must be reviewed-for-syntax and the build done by the user in VS. Keep changes additive where possible.

### Phase 3 — Generic MCP surface (Agent 3)
- `run_gh_definition(capsule_id, inputs, seed=None)` tool: looks up manifest via store, validates inputs against manifest client-side (fail fast before hitting Rhino), sends `run_definition`, returns structured result.
- `list_capsules(capability=None)` tool.
- `validate_structure` re-implemented as a wrapper that keeps its current signature (backwards compatible) and adds `per_element` + `worst_guids` passthrough.
- Unit tests with a mocked bridge socket; runnable via `uv run pytest` in sandbox.

### Phase 4 (spec only, next session) — Wasp
- Capsules with `capability: aggregate`; tools `define_wasp_part(guids, connection_planes)`, `run` with rules grammar + seed; parts stored in AlmondStore like furniture assets; output GUIDs feed straight into `validate_structure`.

## Out of scope this session
Wasp implementation, Kangaroo capsules, Rhino.Compute scaling, upstream structural-intent schema in generation plans.
