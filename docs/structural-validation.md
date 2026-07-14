# Structural validation: process, inputs, and verified behavior

How Almond's `validate_structure` works, what goes in, what comes out, and
the dimension matrix it has been verified against (live sessions,
2026-07-14, bridge 0.2.3, Karamba 3.1.60519).

## Process

```
validate_structure(guids, structure_type, load_kn, material)
        │  MCP server → TCP bridge (port 5000)
        ▼
RhinoAlmondBridge.StructuralValidator
  1. resolve the Rhino objects, extract member axis segments (unit-scaled to meters)
  2. detect span (max extent; defaults to 5.0 m when undeterminable)
  3. choose an analysis pathway, in strict order of confidence:
       api        → Karamba 3.1 solve via KarambaAdapter (real FEA)   confidence: high
       template   → audited capsule .ghx (karamba_*_v1)               confidence: medium
       rule_based → heuristic UDL formulas                            confidence: low
  4. pass/fail checks (same criteria for every pathway)
  5. record the run in the state DB → export_structural_report renders Markdown
```

The response always names the pathway that actually ran
(`results.analysis_method`) and prefixes the verdict, e.g.
`[KARAMBA 3.1 API, HIGH CONFIDENCE]` vs `[RULE-BASED ESTIMATE, LOW CONFIDENCE]`.
A rule-based answer is an estimate, not FEA — the label is the contract.

## Inputs

| Parameter | Default | Meaning |
| --- | --- | --- |
| `guids` | required | Rhino object GUIDs (curves/pipes; axes are extracted) |
| `structure_type` | `"beam"` | analysis template: beam, truss, shell, frame, canopy, gridshell, membrane, highrise |
| `load_kn` | `10.0` | applied load in kN (also drives the rule-based UDL `w = load/span`) |
| `material` | `"Steel"` | Steel (S235), S355, Concrete, Wood, Aluminium |

Supports: when no anchors are declared, the bridge pins the lowest-Z node(s)
automatically and says so in `warnings`.

## Pass criteria

- **Deflection:** `max_deflection_mm ≤ span_mm / 250` (e.g. 24 mm for a 6 m
  span, 48 mm for 12 m).
- **Strength:** utilization < 1.0 against yield (S235: fy = 235 MPa).
- Rule-based pathway: mid-span UDL deflection `5wL⁴/384EI`, moment `wL²/8`,
  with load sharing across members.

## Verified dimension matrix (2026-07-14, live)

| Test geometry | Span | Members | Pathway | Result | Key output |
| --- | --- | --- | --- | --- | --- |
| Planar Warren truss, 900 deep, Ø-tube axes | 6 m | 8 | **api** | PASS | reactions 10.0022 kN; solver flagged 4 rigid-body modes (planar truss in 3D — correct diagnosis) |
| Same truss, double span | 12 m | 12 | **api** | PASS | reactions 10.0042 kN — the +Δ over the applied 10 kN doubled with doubled steel (self-weight equilibrium) |
| Spatially braced box truss (two planar trusses + cross members + plan bracing) | 6 m | 34 | **rule_based** (fallback) | PASS (low conf.) | native solver threw in AnalyzeThI; adapter downgraded honestly and labeled it |
| Planar truss, pre-Karamba sessions | 6 m | 8 | rule_based | PASS (low conf.) | 0.40 mm vs 24 mm limit — heuristic, no reactions |
| ARCC tower roof truss (in-model geometry) | 6 m | 8 | api | PASS | first live FEA pass of the stress test |

Evidence the api pathway is real FEA and not the estimator relabeled:
reactions only exist on the api path and obey equilibrium (applied load +
self-weight, with the self-weight delta scaling with member length); the
solver returns Karamba's own topology-specific diagnostics (rigid-body
modes); a defective model makes the native engine throw rather than answer;
and the two pathways give different numbers for identical geometry.

## Known gaps (issue #6)

In karambaCommon 3.1.60519, two result extractions have signature drift:

- `max_deflection_mm` can read **0.0 on the api path** (displacement
  out-param not extracted) — cross-check against the rule_based estimate;
- `per_element_utilization` is unavailable (Utilization.solve drift), so
  utilization-based checks fall back to 0.

**Practical rule:** trust api-mode *reactions and stability diagnostics*;
treat api-mode *deflection/utilization* verdicts as incomplete until #6 is
closed. Confidence labels in the response reflect this honestly.

## Getting a report

Every recorded run can be exported as Markdown:

```text
validate_structure(guids=[...], structure_type="truss", load_kn=25)
export_structural_report()            # → %LOCALAPPDATA%\Almond\reports\structural-validation-<ts>.md
export_structural_report(path="C:\\project\\checks.md", limit=10)
```

The report contains the pathway explanation, a run table (span, deflection
vs limit, utilization, reactions, member count, PASS/FAIL), per-run verdicts
and warnings, and the interpretation notes above.
