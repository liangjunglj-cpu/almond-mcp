# Solver benchmarks: native frame solver vs OpenSees

Eleven building typologies (`tests/structural_typologies.py`) solved by Almond's native frame solver
and, independently, by [OpenSees](https://opensees.berkeley.edu/) through OpenSeesPy:

| Typology | What it exercises |
| --- | --- |
| moment frame | 3D rigid frame, beam UDLs, wind; sway buckling |
| braced tower | pinned beams (end releases), truss braces, tall model |
| Pratt truss | pin-jointed bars, statically determinate |
| portal | pinned-base gable frame; sway buckling |
| warehouse | portals + pinned purlins + end-bay bracing |
| space grid | 1,152 bars, double-layer grid |
| arch | parabolic arch, funicular load, in-plane buckling, near-buckling P-Delta |
| L-bracket | bending + torsion |
| canopy | cantilevers with back-spans, edge beam, eccentric load |
| diagrid | inclined members only (local axes), wind |
| Vierendeel | rigid-jointed girder without diagonals |

Checks (`test_opensees_crosscheck.py`): linear displacements, rotations, reactions and member
forces (to ~1e-9 relative; 1e-3 where OpenSees needs penalty links for member end releases);
elastic critical load factor alpha_cr within 1 %; second-order (P-Delta) displacements and moments
within 1 %. A strict `xfail` records the known open-section limitation (no warping term in the
torsional geometric stiffness; the Rhino bridge exports hollow and solid sections only).

The closed-form checks of the same typologies (method of joints, virtual work, force method,
funicular thrust, invariance) need no reference solver and run in CI: `tests/test_structural_typologies.py`.

## Running

OpenSeesPy is an optional `bench` dependency group, not a runtime dependency. On a OneDrive
checkout, or while a live MCP server runs from the checkout's `.venv`, point uv at a scratch
environment:

```powershell
$env:UV_LINK_MODE = "copy"; $env:UV_PROJECT_ENVIRONMENT = "$env:TEMP\almond-bench"
uv run --group bench pytest benchmarks            # the cross-checks (about a minute)
uv run --group bench python -m benchmarks.run_benchmarks --scaling   # report tables + validate() timing
```

Without OpenSeesPy (CI) the cross-check module is skipped.

## Notes on the reference

- OpenSees' `PDelta` transformation has no in-member P-delta term, so its buckling loads converge
  from above more slowly than Almond's consistent geometric stiffness; the tests mesh it finer.
- Buckling is extracted from OpenSees' own tangent matrices (`printA`) at a small load factor. A
  corotational truss tangent also changes with the bars' rotation, which pollutes that difference,
  so bar-only models are rebuilt with PDelta beams of negligible bending stiffness
  (`opensees_ref.bars_as_beams`).

## Licence

OpenSeesPy is free for research, education and internal use; commercial redistribution of software
that imports it needs a licence. It is therefore never imported by `almond_mcp`, and `benchmarks/` is
outside the wheel and the sdist (see `docs/licensing-audit.md`).
