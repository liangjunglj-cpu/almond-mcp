# Native frame solver

`validate_structure` analyses line models (beams, columns, trusses, frames) with
Almond's own 3D frame solver by default. Users no longer need Karamba3D for these;
Karamba remains available for shells and as a cross-check.

| | Native (`engine="auto"` / `"native"`) | Karamba (`engine="karamba"`) |
| --- | --- | --- |
| Install | nothing beyond almond-mcp + almondbridge | Karamba3D 3.1 licence (trial: 20 members) |
| Elements | straight beams (axial, torsion, biaxial bending), truss bars | beams, shells |
| Solve time, 20-member frame | ~13 ms (+ ~160 ms model export) | ~1.5 s |
| `analysis_method` | `"native"` | `"api"` / `"template"` / `"rule_based"` |

`engine="auto"` routes to Karamba when the structure type is shell, gridshell or
membrane, when the selection contains shells, or when the installed bridge cannot
export a structural model (older than this change); the result then carries a
warning saying why.

## Method

- Direct stiffness method, Euler-Bernoulli beams, 6 DOF per node, rigid joints
  (`almond_mcp/frame_solver.py`, numpy only, written from the textbook method).
- Uniform member loads (self weight is one) are exact within each member: Hermite
  interpolation of the end displacements plus the fixed-fixed particular solution, so
  one element per member gives the exact deflected shape and moment diagram.
- Linear elastic, first order, static. Singular systems are reported as a
  **mechanism** with the nodes involved, never solved silently.
- Rotations at nodes that only truss bars meet are restrained automatically and
  reported (they carry no load).

## Modelling conventions (same as the Karamba path)

The bridge's `structure_model` message exports the conditioned geometry used by the
Karamba path: welded nodes, members split at intersections, inferred sections, curved
axes polygonized identically. `almond_mcp/native_structure.py` then applies:

- **Supports:** declared Rhino points (snapped to the nearest node within 50 mm), else
  every lowest-Z node. `fixed_supports=False` pins them (translations only).
- **Loads:** `load_kn` shared equally by the free nodes, acting downward; self weight
  γ·A along every member unless `self_weight=False`.
- **Deflection limit:** span/250. Span = longest member for beam/frame, else overall
  extent; `span_m` overrides it when members are split at every node (a 6.2 m joist
  drawn as two 3.1 m segments).
- **Member check (EN 1993-1-1, simplified):** cross-section interaction 6.2.1(7)
  `|N|/N_Rd + |M_y|/M_y,Rd + |M_z|/M_z,Rd` (CHS: resultant moment) with **elastic**
  moduli by default (conservative, the same basis as the Karamba check); flexural
  buckling 6.3.1 with L_cr = member length and the section's buckling curve, combined
  linearly with bending. γ_M0 = γ_M1 = 1.0.

**Not covered:** shells, second-order/P-Δ, lateral-torsional buckling (hollow sections
are immune; I-sections are not checked for it), shear/torsion interaction, dynamics,
connections, national annexes. Results are a preliminary design check, not an
engineer's sign-off.

## Benchmarks

Asserted in `tests/test_frame_solver.py` (20 closed-form cases including equilibrium,
superposition, orientation invariance, mechanisms, section properties and EN 1993
buckling) and `tests/test_native_structure.py` (Karamba cross-check). Regenerate the
tables with `uv run python tools/run_structural_benchmarks.py`.

### Closed form (CHS 114.3×4, S235)

| Case | Closed form | Exact (mm) | Native (mm) | Error |
| --- | --- | ---: | ---: | ---: |
| Cantilever, tip load 10 kN, 3 m | PL³/3EI | 203.0514 | 203.0514 | 0.0e+00 |
| Cantilever, UDL 5 kN/m, 4 m (1 element) | wL⁴/8EI | 360.9803 | 360.9803 | 1.1e-16 |
| Simply supported, UDL 8 kN/m, 6 m | 5wL⁴/384EI | 304.5771 | 304.5771 | 6.7e-16 |
| Simply supported, midspan 12 kN, 5 m | PL³/48EI | 70.5040 | 70.5040 | 7.8e-16 |
| Fixed-fixed, UDL 6 kN/m, 5 m | wL⁴/384EI | 22.0325 | 22.0325 | 1.1e-16 |
| Two-bar truss, apex 20 kN | PL/2EA·sin²α | 0.2386 | 0.2386 | 2.2e-16 |

### Karamba3D cross-check

Reference runs: Karamba3D 3.1 (karambaCommon 3.1.60921) in Rhino 8, 2026-09-30, on the
same geometry and conventions (`tests/data/karamba_reference.json`).

| Model | Section | Load (kN) | Karamba δ (mm) | Native δ (mm) | Δ | Karamba u | Native u | Δ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| portal_cantilever | CHS 114.3×4 | 10 | 110.45 | 110.15 | -0.3% | 1.209 | 1.209 | +0.0% |
| mezzanine | CHS 114.3×4 | 150 | 183.01 | 182.32 | -0.4% | 3.588 | 3.501 | -2.4% |
| mezzanine | CHS 139.7×5 | 150 | 82.05 | 81.59 | -0.6% | 1.910 | 1.911 | +0.1% |
| mezzanine | CHS 168.3×6.3 | 150 | 38.56 | 38.25 | -0.8% | 1.072 | 1.076 | +0.4% |
| mezzanine | CHS 193.7×8 | 150 | 20.92 | 20.71 | -1.0% | 0.664 | 0.668 | +0.5% |
| mezzanine | CHS 219.1×8 | 150 | 14.52 | 14.33 | -1.3% | 0.519 | 0.522 | +0.5% |
| mezzanine | CHS 114.3×4 | 0.001 | 6.20 | 6.19 | -0.2% | 0.106 | 0.107 | +0.7% |
| mezzanine | CHS 114.3×4 | 50 | 65.11 | 64.87 | -0.4% | 1.235 | 1.238 | +0.3% |
| mezzanine | CHS 114.3×4 | 100 | 124.06 | 123.59 | -0.4% | 2.375 | 2.370 | -0.2% |

The deflection gap grows slightly with stockier sections: Karamba uses Timoshenko
beams (shear deformation), the native solver Euler-Bernoulli. Bending-governed members
match Karamba's utilization within 1 %; compression members can differ by up to ~11 %
(EN 1993 6.3 linear interaction here, Karamba's own interaction factors there).

Live check (2026-10-01): the mezzanine exported from Rhino through `structure_model`
gave native 182.31 mm / u 3.50 vs Karamba `validate` 182.53 mm / u 3.59 (CHS 114.3×4),
and 20.70 mm / 0.668 vs 20.85 mm / 0.664 (CHS 193.7×8), same verdicts.
