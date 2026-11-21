# Open-source structural analysis / FEA engines: survey for Almond

Survey date: 2026-10-11. Repo stars, last-push dates and licences were checked with `gh api` on the survey date. PyPI data came from `pypi.org/pypi/<pkg>/json`. Anything not checked against a primary source is marked **[unverified]**.

Licence routes used throughout:
- **(a)** Almond may list it as an *optional* Python dependency (extra / dependency group). The user installs it; Almond does not redistribute it.
- **(b)** Almond may vendor, copy or port code, keeping the original notice.
- **(c)** Learn from it or use it as a test oracle only. No import from shipped code and no copying. Applies to GPL, AGPL and non-commercial licences.

Almond baseline (from the brief, plus a read-only look at `almond_mcp/frame_solver.py`, 860 lines, and `pyproject.toml`):
- Runtime dependencies are numpy>=2, shapely>=2.1, ezdxf, contourpy and others. **There is no scipy**: the solver is dense numpy.
- OpenSeesPy is already confined to the `bench` dependency group, which is the correct handling (see section 5).

---

## 1. Executive summary: top refinement recommendations

| # | Recommendation | Source engine / paper | Licence route | Effort | How it plugs into Almond |
|---|---|---|---|---|---|
| 1 | **Add Timoshenko shear deformation to the beam element, plus the EC3 6.2.6 shear check and the 6.2.8 bending-shear (M-V) interaction.** | Karamba3D beams *are* Timoshenko (Rubin's formulation; Karamba manual and a developer post). That probably explains part of Almond's 1.3% deflection gap to Karamba **[hypothesis, untested]**. Shear-area and check formulas: Blueprints `formula_6_17`…`6_22`, `6_18_sub_av`, `6_29`/`6_30` (MIT). | Formulas are public; Blueprints is MIT, route (b) with attribution | **S** | `local_stiffness()` gets the factor φ = 12EI/(G·A_s·L²) (Przemieniecki), driven by `Section.Asy/Asz` (rolled-section A_v per EN 1993-1-1 6.2.6(3); default None means Euler-Bernoulli, which keeps the existing OpenSees 1e-14 tests valid). `geometric_stiffness()` gets the matching shear-flexible terms. `ec3.member_check()` gets V_pl,Rd, ρ = (2V/V_pl − 1)² and the 6.2.6(6) web-shear-buckling flag. Re-run the Karamba comparison with shear areas on. |
| 2 | **Add a flat triangular shell element to the native solver: DKT bending (Batoz 1980) plus a membrane with drilling DOF (Felippa ANDES/OPT, 2003).** | Karamba3D shells are flat triangles resembling Argyris' TRIC element, with *no transverse shear* (Karamba manual and bibliography). DKT is the closest open Kirchhoff analogue. MIT reference code: **MYSTRAN `Source/EMG/EMG4/TPLT1.f90`** (DKT, explicit Batoz formulation), `TREL1.f90` (triangle membrane), `TPLT2.f90` (MIN3 thick plate). ANDES reference: Kratos `shell_thin_element_3D3N.hpp` (BSD-4-Clause). Quad: Pynite `Quad3D.py` (DKMQ + plane stress, MIT). | MYSTRAN and Pynite: (b) (port with MIT notice). Kratos: read only / (a) as oracle. | **L** | New `almond_mcp/shell_solver.py` (or element module) reusing the 6-DOF/node assembly of `frame_solver._assemble`. Needs **scipy.sparse** (BSD-3; add as a dependency). Phase 1 is linear static, then K_g for alpha_cr, then a lumped or consistent mass for modal. Benchmark against Karamba shell results through the existing reflection adapter, plus the shell suite in section 4. Lets Almond drop the Karamba fallback for linear shells. |
| 3 | **Add a permissive shell and solid oracle in the `bench` group: MYSTRAN through the `mystran` PyPI wheel, with Kratos as a second oracle.** | MYSTRAN (MIT, NASTRAN-style input) supports static, modal and linear buckling, with DKT/DKQ/MIN3/MIN4 plates. `pip install mystran` ships a `win_amd64` wheel with the executable. Kratos `KratosStructuralMechanicsApplication` 10.4.4 ships cp310–cp313 `win_amd64` wheels (BSD-4-Clause) with ANDES, DSG, MITC4 and corotational shells. | MYSTRAN: (a)/(b). Kratos: (a) | **S–M** | `benchmarks/` harness: write a minimal BDF (GRID/CTRIA3/CQUAD4/PSHELL/MAT1/SPC/FORCE/PLOAD2) and parse the F06 output. **Do not use pyNastran**: PyPI 1.4.1 pins `numpy<2`, which conflicts with Almond's `numpy>=2`. Same pattern as the OpenSeesPy benchmarks today. |
| 4 | **Add modal / natural-vibration analysis (frames now, shells later).** | Pynite `FEModel3D.analyze_modal` (MIT) solves `[K]{φ} = ω²[M]{φ}` with a consistent mass matrix, plus lumped mass taken from a load combination as m = F/g. It calls `scipy.sparse.linalg.eigsh(K11, k, M=M11, sigma=0.0, which='LM')`. | (b) pattern; the maths is textbook | **S–M** | Add `mass_matrix(e, L)` (consistent Przemieniecki 12×12, or lumped). Reuse `_assemble` partitioning and `critical_load_factor`'s eigen path. Expose f₁…f_n and modal mass participation. Benchmarks: SOFiSTiK BE25 and BE39, plus OpenSeesPy `eigen`. Karamba equivalents are "Natural Vibrations" and "Eigen Modes". |
| 5 | **Add lateral-torsional buckling (EC3 6.3.2) and bow imperfections (5.3.2 Table 5.1).** | No permissive open code computes M_cr robustly. Options: (i) closed-form 3-factor C1/C2/C3 (Access Steel NCCI SN003, free); (ii) a 7-DOF thin-walled beam element with warping and geometric stiffness, reusing Almond's alpha_cr eigen machinery (Trahair; Yang & McGuire). pyCUFSM (finite strip) is a cross-check only: GitHub says LGPL-3.0, PyPI says AFL-3.0 (inconsistent). Karamba's cross-section optimiser does apply flexural and lateral-torsional buckling plus EC3 Annex B procedure 2, with C_m capped at 0.9 (Karamba manual A.2.6). | Formulas public; pyCUFSM (c) | **M** | `ec3.member_check` gets χ_LT (6.56 general / 6.57 rolled with f-modification). M_cr comes from SN003 for standard cases and from the warping-element eigen solve otherwise. I_w comes from recommendation 6. Bow imperfections e₀/L (Table 5.1) become equivalent UDLs feeding the existing P-Delta path. Benchmarks: SOFiSTiK DCE-EN15, DCE-EN24 and DCE-EN20. |
| 6 | **Add a cross-section property calculator for arbitrary sections** (A, I, shear centre, J, I_w, shear areas, plastic moduli). | **sectionproperties** (MIT) uses the Pilkey warping-function FE approach and can import Rhino `.3dm`. **Caveat:** its mesher `cytriangle` wraps Shewchuk's Triangle, which "may not be sold or included in commercial products without a license". The same applies to `structuralcodes` (depends on `triangle`), `concreteproperties` and `blue-prints`. | sectionproperties: (a) optional extra only, with the Triangle caveat documented. Own implementation: (b)/learn. | **M** | Either `almond-mcp[sections]` (optional) or an own mini-implementation: triangulate with **`shapely.constrained_delaunay_triangles`** (GEOS, shapely ≥2.1, already a dependency; refinement must be added), then run 6-node warping FE following Pilkey, *Analysis and Design of Elastic Beams* (2002). Validate against sectionproperties in the bench group and against Blueprints/structuralcodes profile tables. |
| 7 | **Add section-size optimisation and BESO for beams (and later shells), matching Karamba's "Optimize Cross Section", "BESO for Beams" and "BESO for Shells".** | Karamba method (manual A.2.6, §3.6.9): walk a section family until utilisation ≤ 1, then re-analyse until stable. BESO uses soft-kill, a strain-energy-density weight per force component, a BESOFac re-add ratio and MinDist. Literature: Xie & Steven (ESO); Huang & Xie (2007) for convergent BESO. Code to learn from: `calculix/beso` (LGPL-3.0, (c)/(a)), `TopOpt.jl` (MIT), `zfergus/topopt` (MIT, 2D SIMP). | Algorithms public; MIT codes (b) | **S** (section optimisation), **M** (BESO beams), **L** (BESO shells, after #2) | New `almond_mcp/optimize.py` driving `solve_combinations` and `ec3.apply`. BESO beams: per-element energy density from `ElementResult`, soft-kill by scaling E by 1e-6, with history averaging. |
| 8 | **Add form-finding and cable/membrane analysis: force density first, then dynamic relaxation.** | `compas_fd` `fd_numpy` (MIT; about 50 lines on scipy `spsolve`) and `compas_dr` (MIT). `jax_fdm` (MIT; differentiable, inverse form-finding; heavy JAX dependency). Karamba's "Large Deformation Analysis" is plain incremental geometry updating (its manual notes drift and no forces in the output). | (b) re-implement (Schek 1974) or (a) `compas_fd` | **S** (FDM), **M** (DR plus cable/membrane elements) | `almond_mcp/formfinding.py`: FDM on line networks with q per edge from Rhino curves, then DR with pretension / cable-only (tension-only) members. This complements the existing tension/compression behaviour. |

Second-tier items (worth doing, lower leverage):
- **EN 1991-1-4 wind (M).** No maintained open Python library exists (see section 3.6). Implement §4.2–4.5: v_b, c_r(z), c_o, I_v, q_p(z). Add §7.2 c_pe tables for walls and flat or duopitch roofs, using the National Annex machinery Almond already has. ASCE 7 q_z is a one-liner. Cross-check against `dancergraham/eurocode` (MIT, tiny) and the SkyCiv worked example.
- **Structural exchange (M).** IfcOpenShell has a full `ifcopenshell.api.structural` module (`add_structural_analysis_model`, `add_structural_load_case`, `add_structural_boundary_condition`, …). It is LGPL-3.0 (route (a)) and exports IFC4 structural analysis views. Blueprints' `saf` package (MIT) shows how to emit SAF (Structural Analysis Format, xlsx) for SCIA/RFEM-class tools **[SAF tool support unverified]**.
- **Calculation reports (S–M).** `handcalcs` (Apache-2.0) and `efficalc` (MIT) render LaTeX calculations. Blueprints' per-formula classes with `.latex()` (MIT) are a good model for EC3 check reports.
- **AISC 360 Commentary C2 second-order benchmarks (S).** Pynite's `Testing/test_AISC_PDelta_benchmarks.py` (MIT) encodes them. Port them as Almond P-Delta regression tests.
- **EN 1993-1-9 fatigue (S).** `fatpack` (ISC) does rainflow counting and EC3 detail curves. Route (a).

---

## 2. Comparison table

Stars and last-push dates are from `gh api` (2026-10-11). Element and analysis entries are from README, source or docs as noted. Karamba3D is listed first as the target, not as an open option.

| Engine | URL | Licence (SPDX, from repo) | Route | Lang | Stars / last push | Elements | Analyses | Code checks | Notes vs Karamba3D |
|---|---|---|---|---|---|---|---|---|---|
| **Karamba3D 3.1** (target) | manual.karamba3d.com | Proprietary | n/a | C# | n/a | Timoshenko beams, trusses, flat TRIC-like triangle shells without transverse shear, membranes, springs | 1st order, Th.II, Nonlinear WIP, Large Deformation (incremental), buckling, eigen, natural vibrations | EC3 utilisation incl. flexural and LTB, Annex B proc. 2 | Algorithms: Optimize Cross Section, BESO beams/shells, Optimize Reinforcement, Tension/Compression Eliminator |
| **Pynite** (PyNiteFEA 3.2.0) | github.com/JWock82/Pynite | **MIT** | a, b | Py | 756 / 2026-10-11 | EB 3D members (tension/compression-only), springs, `Plate3D` (rectangular Kirchhoff), `Quad3D` (DKMQ + plane stress, weak drilling spring), meshers (rectangle, annulus, cylinder, frustum), shear wall, mat foundation | Linear, P-Delta, modal (consistent mass, `eigsh`), pushover, T/C iteration | None (steel section helper only) | Closest MIT analogue. `Tri3D.py` is not wired into `FEModel3D` (stub; its docstring still says "rectangular"). Plate tests use loose tolerances (15% vs Timoshenko Table 45), so not an oracle for plates. Derivation notebooks: `Derivations/DMKQ Quad Element.ipynb`, `MITC4 Quad Element.ipynb` |
| anaStruct 1.7.0 | github.com/anastruct/anaStruct | **LGPL-3.0** (LICENSE.txt) but pyproject declares **GPL-3.0-or-later** (conflicting) | c (treat as GPL) | Py | 468 / 2026-10-09 | 2D frame/truss | Linear, geometric nonlinear, plastic hinges, influence lines **[from memory]** | None | 2D only; nothing to adopt |
| OpenSees / OpenSeesPy 3.8.0.0 | github.com/OpenSees/OpenSees | UC Regents custom (NOASSERTION): noncommercial for educational/research/non-profit; others "internal purposes only" | c (bench only; already Almond policy) | C++ | 831 / 2026-10-09; Py 280 / 2026-08-18 | Everything: elastic/force/disp beams, ShellMITC4/9, ShellDKGQ/DKGT, ShellNLDKGQ/T, ASDShellQ4/T3 (corotational), solids | All: static, P-Delta/corotational, buckling, modal, dynamic, material nonlinear | None | Already Almond's 1e-14 oracle |
| xara 0.0.45 | github.com/peer-open-source/xara | Top-level **BSD-2-Clause**, but `about/COPYRIGHT` carries the UC OpenSees noncommercial licence for the bundled OpenSees code | c (treat as OpenSees) | C++/Py | 66 / 2026-09-28 | As OpenSees | As OpenSees | None | Don't be misled by the BSD badge |
| Alpaca4d | github.com/Alpaca4d/alpaca4d | Apache-2.0 tag, but README: "everything is subject to the OpenSees license terms" | c | C# (GH) | 38 / 2026-10-07 | Beam, shell, brick (OpenSees) | Static, modal, ground motion | None | GH competitor to Karamba built on OpenSees |
| compas_fea2 0.2.1 | github.com/compas-dev/compas_fea2 | **MIT**; backends `fea2/compas_fea2_{opensees,abaqus,sofistik,castem}` are MIT text (GitHub shows "other") | a, b | Py | 14 / 2025-11-20 (last release 2024-05) | Abstract: Beam, Truss, Strut/Tie, Spring, Link, Mass, Shell, Membrane, Tet/Penta/Hexa | Steps: static, Modal, Buckling, ComplexEigen, SteadyStateDynamic, quasistatic, dynamic | None | Solver-agnostic data model; delegates to commercial or OpenSees solvers. Low activity. Useful as a schema reference only |
| compas_fd 0.5.4 | github.com/BlockResearchGroup/compas_fd | **MIT** (LICENSE text; GitHub NOASSERTION) | a, b | Py | 7 / 2024-11-10 | Line networks | Force density (constrained: line/curve/plane/surface/frame) | n/a | Form-finding Karamba lacks natively (Kangaroo territory) |
| compas_dr | github.com/BlockResearchGroup/compas_dr | **MIT** (text) | a, b | Py | 3 / 2024-10-16 | Line networks | Dynamic relaxation with constraints | n/a | Same |
| compas_tna | github.com/BlockResearchGroup/compas_tna | **MIT** | a, b | Py | 16 / 2026-09-02 | Funicular networks | Thrust Network Analysis | n/a | Masonry vaults |
| compas_ags | github.com/BlockResearchGroup/compas_ags | **MIT** | a, b | Py | 18 / 2024-11-27 | 2D | Algebraic graphic statics | n/a | Teaching / early design |
| COMPAS core | github.com/compas-dev/compas | **MIT** | a | Py | 387 / 2026-10-04 | Geometry, datastructures | n/a | n/a | Heavy dependency for little gain |
| jax_fdm 0.14.1 | github.com/arpastrana/jax_fdm | **MIT** | a, b | Py/JAX | 119 / 2026-09-11 | Networks | Differentiable FDM, inverse form-finding | n/a | Best-in-class inverse FDM, but JAX is heavy |
| JaxSSO | github.com/GaoyuanWu/JaxSSO | **MIT** | b (ref) | Py/JAX | 42 / 2025-12-22 | Beam-column, **MITC4 shell** | Linear, differentiable shape/size/topology optimisation | n/a | MIT MITC4 reference code |
| BHoM (+ Robot_, Karamba3D_Toolkit) | github.com/BHoM | **LGPL-3.0** | a (C# adapters) | C# | 249 / 2026-10-08 | Object model; adapters to Robot, ETABS, Lusas, Karamba | None of its own | None | Interop only |
| Frame3DD | github.com/hpgavin/frame3dd | **GPL-3.0** (LICENSE.txt) | c | C | 7 / 2026-01-29 (pyFrame3DD 34 / 2024-05) | 3D frame/truss with shear deformation, geometric stiffness | Static, modal, condensation | None | Useful GPL oracle for Timoshenko and modal frames (subprocess only) |
| CalculiX ccx | dhondt.de | **GPL-2.0** (Debian copyright; MSYS2 says or-later) | c (subprocess) | Fortran/C | n/a | Solids; S3/S4/S8 shells are **expanded to solids** (C3D6/C3D8I/C3D20) | Static, buckling, modal, nonlinear, contact | None | Weak shell oracle because of expansion. `pyccx` (BSD-2) drives it |
| Code_Aster | gitlab.com/codeaster/src | **GPL-3.0-only** (GitLab API) | c | Fortran/C/Py | 32 (GitLab) / 2026-10-09 | DKT/DKQ/DST/Q4G plates, COQUE_3D (Naghdi, QUAD9/TRIA7), beams, solids | Everything | Some (EN fatigue) **[unverified]** | Validation manual (GFDL) is a free benchmark source (SSLS/SSLV/SDLS) |
| Kratos Multiphysics 10.4.4 (StructuralMechanicsApplication) | github.com/KratosMultiphysics/Kratos | **BSD-4-Clause** (core and SMA `license.txt`; advertising clause) | a (wheels); b possible but awkward | C++/Py | 1373 / 2026-10-10 | Shells: thin T3 (ANDES), thin Q4 (ANDES membrane), thick T3 (DSG), CS-DSG3, thick Q4, MITC4, all with corotational option; beams; cables; membranes; solids | Linear, nonlinear geometric/material, buckling, modal, dynamic, formfinding (membranes) | None | **Best permissive heavyweight oracle**; pip wheels for win_amd64 cp310–313 |
| FEniCSx (dolfinx) | github.com/FEniCS/dolfinx | **LGPL-3.0** | a | C++/Py | 1220 / 2026-10-10 | General variational (any) | Any (you write the weak form) | None | Overkill; poor Windows pip story **[unverified]** |
| scikit-fem 12.0.2 | github.com/kinnala/scikit-fem | **BSD-3-Clause** | a, b | Py | 663 / 2026-10-10 | Includes **Morley** and **Argyris** (C¹) Kirchhoff plate triangles, HHJ, P1–P4, Hermite | Linear, eigen (you assemble) | None | Pure-Python, pip-light **plate-bending oracle**: Argyris converges very fast |
| SfePy 2026.3 | github.com/sfepy/sfepy | **BSD-3-Clause** | a, b | Py | 841 / 2026-09-29 | Solids; `shell10x` Reissner-Mindlin shell | Linear/nonlinear, eigen | None | Secondary |
| FElupe 11.1.3 | github.com/adtzlr/felupe | **GPL-3.0** | c | Py | 188 / 2026-10-09 | Hyperelastic solids | Nonlinear | None | Not relevant |
| sectionproperties 3.10.2 | github.com/robbievanleeuwen/section-properties | **MIT** (dependency `cytriangle` LGPL-3 wrapping Shewchuk Triangle, non-commercial) | a (optional, caveat); b for algorithms | Py | 560 / 2026-04-16 | 6-node triangle cross-section FE | Geometric, warping (J, I_w, monosymmetry), shear centre (elastic and Trefftz), shear areas, plastic, stress, composite | n/a | Karamba has a fixed cross-section library; this goes beyond it |
| concreteproperties 0.8.0 | github.com/robbievanleeuwen/concrete-properties | **MIT** (depends on sectionproperties and cytriangle) | a (caveat) | Py | 246 / 2026-09-17 | RC / composite / prestressed sections | Moment-curvature, M-N and biaxial interaction, cracked properties, stresses | AS3600, NZS3101 (not EC2) | Route to RC section checks |
| structuralcodes 0.7.2 (fib) | github.com/fib-international/structuralcodes | **Apache-2.0** (depends on `triangle`, LGPL wrapper of Shewchuk Triangle) | a (caveat), b | Py | 300 / 2026-09-23 | Fibre and Marin section integrators, shell section integrator, EU/UK/US profile tables | Section M-N-κ, smeared cracking constitutive models | **EC2 2004** (materials, shear, crack control, creep/shrinkage), **EC2 2023**, **MC2010** (shear, punching, torsion), MC2020 stub | Best open EC2/fib library; no EC3/EC5 |
| Blueprints (`blue-prints` 0.7.2) | github.com/Blueprints-org/blueprints | **MIT** (depends on sectionproperties, so Triangle; also googletrans and python-docx) | b (vendor single formulas); a heavy | Py | 127 / 2026-10-03 | Profiles | n/a | EN 1993-1-1 §6 formula classes 6.1–6.45, 6.54–6.55; steel checks: tension, compression, bending, **shear (6.2.6)**; EN 1992; EN 1993-1-8/-1-9/-5; EN 1995 SLS 7.3/7.4 only; Dutch NA; SAF export | Per-formula classes with LaTeX output; ideal for vendoring EC3 shear |
| eurocodepy 2027.0.8 | github.com/pcachim/eurocodepy | **LGPL-3.0** (LICENSE text) | a | Py | 56 / 2026-10-05 | n/a | n/a | EC0/EC2/EC3/EC8 utilities and material DBs incl. timber classes; no EC5 member checks | Minor |
| pycba 1.0.2 | github.com/ccaprani/pycba | **AGPL-3.0** since 2026-06-27 (was Apache-2.0) | c | Py | 128 / 2026-10-05 | Continuous beams | Linear, influence lines, vehicle loading | n/a | Avoid; pre-1.0 Apache releases exist but aren't worth it |
| Phaenotyp | github.com/bewegende-Architektur/Phaenotyp | **GPL-3.0** | c | Py (Blender) | 24 / 2026-10-09 | Via Pynite (members, quads) | Via Pynite; GA and gradient descent | Simple Euler buckling | Blender analogue of Almond's ambitions; GPL |
| FramAT 0.5 | github.com/airinnova/framat | **Apache-2.0** | a, b | Py | 27 / 2025-12-18 | 3D Euler-Bernoulli only | Linear | None | Nothing new |
| MYSTRAN 19.0.0 (PyPI `mystran` 18.0.0.1) | github.com/MystranSolver/MYSTRANSolver | **MIT** | a, b | Fortran 95 | 119 / 2026-10-09 | CBAR/CBEAM/CROD, CTRIA3 (DKT or MIN3 bending + membrane), CQUAD4 (DKQ, MIN4, MIN4T), CSHEAR, solids, CLPT laminates | Linear static, modal, linear buckling | None | **Permissive NASTRAN-class oracle with a pip wheel**; readable MIT DKT/MIN3/DKQ/MIN4 code |
| FrontISTR | github.com/FrontISTR/FrontISTR (dev on GitLab) | **MIT** | a (exe), b | Fortran/C | 117 / 2026-10-11 | MITC3, MITC4, MITC9 shells (`static_LIB_shell.f90`), beams, trusses, solids | Static, nonlinear geometric/material, contact, eigen, frequency response, dynamic | None | MIT nonlinear MITC reference; needs MPI and METIS to build |
| BriefFiniteElement.NET | gitlab.com/fem-net/bfe-net (GitHub archived mirror) | **LGPL-3.0** (GitHub) / "other" (GitLab) | a (NuGet, C# bridge) | C# | 180 / 2026-07-20 | Bar, triangle/quad shell, tetra **[element formulations unverified]** | Linear static | None | Only relevant if solving inside the Rhino bridge |
| awatif 3.4 | github.com/madil4/awatif | **MIT** | b | TS / C++-WASM | 183 / 2026-10-10 | 3D frame (6 DOF), releases | Linear static; imperfections; ULS combinations | Report generation | Shells and second-order are sold as a paid "Solver API" (not open) |
| xc | github.com/xcfem/xc | **GPL-3.0** | c | C++/Py | 382 / 2026-10-04 | OpenSees-derived | Nonlinear | EC2/EC3/EC5 checks **[unverified]** | Learn only |
| torch-fem 0.13.1 | github.com/meyer-nils/torch-fem | **MIT** | a, b | Py/PyTorch | 128 / 2026-10-10 | Trusses, planar, shells, solids | Nonlinear, differentiable | n/a | Heavy dependency |
| jax-fem | github.com/deepmodeling/jax-fem | **GPL-3.0** | c | Py/JAX | 772 / 2026-10-09 | Solids | Differentiable | n/a | GPL |
| calculix/beso | github.com/calculix/beso | **LGPL-3.0** | c / a | Py | 472 / 2025-04-03 | Uses CalculiX | BESO topology optimisation | n/a | Algorithm reference for Karamba-style BESO |
| ToPy | github.com/williamhunter/topy | **MIT** (LICENSE.md; partly based on Sigmund's 99-line code) | b | Py | 577 / 2022-08-31 (stale) | 2D/3D continuum | SIMP | n/a | Stale |
| zfergus/topopt 0.0.1a1 | github.com/zfergus/topopt | **MIT** | b | Py | 128 / 2022-07-18 | 2D continuum | SIMP (top88-style) | n/a | Small and readable |
| TopOpt.jl | github.com/JuliaTopOpt/TopOpt.jl | **MIT** (Expat; GitHub NOASSERTION) | b | Julia | 226 / 2026-08-18 | Truss and continuum | SIMP, BESO, stress-constrained | n/a | Best open truss topology reference |
| ShapeOp | jeske/ShapeOp mirror; shapeop.org | **MPL-2.0** (file header) | a / b (file-level copyleft) | C++ | mirror 10 / 2019 | Projective constraints | Shape-op (Kangaroo-like) | n/a | Kangaroo 2 itself is closed (bundled with Rhino) |
| libigl | github.com/libigl/libigl | **MPL-2.0** core; some modules **GPL-3.0** (`LICENSE.GPL`, `LICENSE.MPL2`) | a/b (core only) | C++ | 5104 / 2026-09-21 | Geometry processing | n/a | n/a | Not a structural solver |
| IfcOpenShell 0.9.0 | github.com/IfcOpenShell/IfcOpenShell | **LGPL-3.0** | a | C++/Py | 2848 / 2026-10-10 | `api.structural`: analysis model, members, connections, loads, load cases/groups, boundary conditions | n/a | n/a | IFC structural analysis view export |
| pyCUFSM 0.2.0 | github.com/brookshsmith/pyCUFSM | GitHub **LGPL-3.0**; PyPI **AFL-3.0** (inconsistent) | c (until clarified) | Py | 71 / 2026-10-09 | Finite strip | Elastic buckling of thin-walled sections (local, distortional, global/LTB) | n/a | Cross-check for M_cr and cold-formed |
| fatpack | github.com/Gunnstein/fatpack | **ISC** | a, b | Py | 157 / 2026-03-28 | n/a | Rainflow counting, S-N curves | EN 1993-1-9 detail curves | Small, useful |
| handcalcs 1.11.0 / efficalc 1.2.7 | github.com/connorferster/handcalcs; github.com/youandvern/efficalc | **Apache-2.0** / **MIT** | a | Py | 5803 / 2026-10-03; 51 / 2025-08-26 | n/a | n/a | Calc rendering | Report layer |
| dancergraham/eurocode | github.com/dancergraham/eurocode | **MIT** | b (cross-check) | Py | 15 / 2023-04-30 | n/a | n/a | EN 1991-1-4 basics, French NA (single `ec1.py`) | Too small to depend on |
| buddyd16/Structural-Engineering | github.com/buddyd16/Structural-Engineering | **BSD-3-Clause** | b | Py 2.7 | 295 / 2024-12-09 | 2D frame, beams | Linear | NDS wood, ACI, AISC snippets | Stale (Python 2.7) |
| Kiwi!3D | kiwi3d.com; TUM | Not open source (no licence found); latest beta 0.6.0, 2023-01 (food4rhino) | n/a | C# | n/a | Isogeometric shell, membrane, beam, cable | Linear and geometrically nonlinear | n/a | IGA reference only; not available |

Other notable items, not tabled in detail: `pyNastran` (BSD-3, but PyPI 1.4.1 pins numpy<2), `pyccx` (BSD-2 CalculiX driver), `ospgrillage` (MIT, OpenSeesPy bridge grillages, so it inherits OpenSees terms), `CALFEM` (MIT, teaching), `nusa` (MIT), `SolidsPy` (MIT), `suanPan` (GPL-3), `stabileo` (AGPL-3), `ONSAS` (GPL-3, MATLAB), `pystra` (GPL), `dx-eurocode` (AGPL, GitLab), `mento` (MIT; scope unverified), `Pirouz-Nourian/VectoRelax` (MIT, vectorised DR notebook).

---

## 3. Deep dives

### 3.1 Pynite: the closest MIT analogue (route b)

Files (`gh api repos/JWock82/Pynite/git/trees/main`, package `Pynite/`):
- `Quad3D.py` (46.8 kB). An isoparametric quad formed by superposing **DKMQ** bending (Katili; reference 1: "A Comparative Formulation of DKMQ, DSQ and MITC4…") on an isoparametric plane-stress membrane.
  - Drilling DOF gets a weak spring of about 1/1000 of the smallest rotational diagonal ("Bathe's recommendation", comment near line 564).
  - Supports orthotropy modifiers `kx_mod/ky_mod`.
  - Key methods: `B_b`, `B_s_gamma` (eq. 39 of Katili), `A_Delta_inv_DKMQ`, `ke_b`, `ke_m`, `T`, `FER`.
  - **Worth porting**: the DKMQ assembly (it degenerates correctly to thin plates), the transformation `T()`, and the surface-pressure FER.
- `Plate3D.py`. Rectangular-only Kirchhoff plate. The closed-form 12×12 bending matrix comes from `Derivations/Rectangular Plate Element.ipynb`. Not general enough for Rhino meshes.
- `Tri3D.py`. **Not wired into `FEModel3D`** (no `add_tri`). Its `ke_b` is the rectangular plate matrix. Do not use.
- `Analysis.py`:
  - `_PDelta` (iterative P-Delta).
  - `_pushover_step` / `_load_step_ratio` (plastic-hinge yield surface with `tau(p, my, mz, …)`).
  - `_check_TC_convergence` (tension/compression-only iteration).
  - `_check_stability` (zero-stiffness DOF detection). Compare with Almond's `_spurious_rotation_dofs` and `_mechanism`.
- `FEModel3D.analyze_modal` (around line 2472). Consistent mass plus "mass from load combination via m = F/g". Shift-invert `eigsh(..., sigma=0.0)`. This is the pattern for recommendation 4.
- `Testing/test_AISC_PDelta_benchmarks.py`. AISC 360 second-order benchmark cases. Port them to Almond's P-Delta tests.
- `Testing/test_plates&quads.py`. Tolerances are 1% (simple plate) and **15%** (Timoshenko Table 45 hydrostatic). Pynite plates are therefore not a precise oracle.

Gaps relative to Almond: no linear-buckling eigen solve (alpha_cr), no EC checks, no load-combination factorisation reuse. Almond's frame solver is already ahead on stability (alpha_cr, sway imperfections). Pynite's value for Almond is mainly its **plate/quad code, modal pattern and test cases**.

### 3.2 MYSTRAN and Kratos as shell references and oracles

**MYSTRAN** (MIT; every source file carries an MIT header):
- `Source/EMG/EMG4/TPLT1.f90`: DKT thin plate. Header: based on Batoz, "An Explicit Formulation for an Efficient Triangular Plate-Bending Element" (IJNME 1982).
- `TPLT2.f90`: **MIN3** (Tessler & Hughes, "A Three-Node Mindlin Plate Element With Improved Transverse Shear").
- `QPLT1.f90`: **DKQ** (Batoz & Ben Tahar). `QPLT2.f90`: **MIN4** (Tessler & Hughes 1983). `QPLT3.f90`: **MIN4T** (four MIN3 sub-triangles, condensed).
- `TREL1.f90` / `QDEL1.f90`: element drivers for mass, thermal, stress recovery and stiffness. `QMEM1.f90`: isoparametric membrane quad with reduced shear integration and warping correction. `EMG6/BBMIN4`, `BSMIN4`, `BMQMEM`: B-matrices.

Recommended Almond shell, matching Karamba's TRIC-like Kirchhoff triangle:
1. Bending: **DKT**, ported from `TPLT1.f90` (MIT). Batoz's explicit form is about 150 lines of numpy.
2. Membrane: **CST plus drilling via ANDES/OPT** (Felippa, "A study of optimal membrane triangles with drilling freedoms", CMAME 192, 2003). Kratos' `shell_thin_element_3D3N.hpp` is the C++ reference (BSD-4, so read it rather than copy). Simpler fallback: CST plus a weak drilling spring, as Pynite does.
3. Later: MIN3 (from `TPLT2.f90`) as a thick-shell option, since Karamba neglects transverse shear in shells.

Oracle usage:
- `pip install mystran` provides a `win_amd64` wheel and `mystran.get_mystran_binary()` (third-party package `spookylukey/mystran-package`, MIT).
- Write the BDF directly; avoid pyNastran's `numpy<2` pin.
- Run SOL 101 (static), SOL 103 (modal) and SOL 105 (buckling), and parse the F06.

**Kratos** (BSD-4-Clause):
- `applications/StructuralMechanicsApplication/custom_elements/shell_elements/` contains:
  - `shell_thin_element_3D3N` (ANDES, corotational).
  - `shell_thin_element_3D4N` (ANDES membrane).
  - `shell_thick_element_3D3N` (DSG, Bletzinger).
  - `cs_dsg3_thick_shell_element_3D3N` (CS-DSG3 plus ANDES membrane).
  - `shell_thick_element_3D4N` and `mitc_thick_shell_element_3D4N` (corotational).
- PyPI wheels: `KratosMultiphysics`, `KratosStructuralMechanicsApplication`, `KratosLinearSolversApplication` 10.4.4, cp310–cp313 `win_amd64`.
- Use it as a geometric-nonlinear / large-deformation shell and cable oracle (a Karamba "Large Deformation" equivalent).
- The BSD-4 advertising clause ("This product includes Kratos Multi-Physics technology") makes vendoring unattractive. Keep it as an optional bench dependency.

**FrontISTR** (MIT): `fistr1/src/lib/static_LIB_shell.f90` implements MITC (Dvorkin & Bathe; Bucalem & Bathe) for MITC3, MITC4 and MITC9, with tying-point tables. This is an MIT reference if Almond ever needs a Reissner-Mindlin quad shell. Building it needs MPI and METIS, so it is not a convenient oracle on Windows.

**CalculiX** is a poor shell oracle: S3/S4/S8 elements are expanded internally into C3D6/C3D8I/C3D20 solids (ccx manual).

### 3.3 compas_fea2 backends

- Core (MIT) defines the abstract model:
  - Elements (`model/elements.py`): `BeamElement`, `TrussElement`, `StrutElement`, `TieElement`, `SpringElement`, `LinkElement`, `MassElement`, `ShellElement`, `MembraneElement`, `Tetrahedron`/`Pentahedron`/`Hexahedron`.
  - Steps (`problem/steps/`): `static`, `perturbations` (`ModalAnalysis`, `BucklingAnalysis`, `ComplexEigenValue`, `LinearStaticPerturbation`, `SteadyStateDynamic`, `SubstructureGeneration`), `quasistatic`, `dynamic`.
- Backends live in the `fea2` org: `compas_fea2_opensees`, `_abaqus`, `_sofistik`, `_castem` (all MIT text), plus stale `_ansys`. There is no CalculiX or Kratos backend.
- Activity is low: 14 stars, last release v0.2.1 (2024-05), last push 2025-11.
- **Verdict:** don't depend on it. Its step taxonomy (static / modal / buckling / dynamic as separate "steps" over one model) is a good schema reference for Almond's MCP `validate_structure` API if it grows analysis types.

### 3.4 sectionproperties and concreteproperties

**sectionproperties** (MIT, v3.10.2):
- Features (docs user guide): global, centroidal and principal properties; plastic moduli and shape factors; **warping** (torsion constant J, warping constant I_w, monosymmetry constants); **shear centre** (elastic and Trefftz); **shear areas**; stress analysis and Mohr's circles; composite materials; Rhino `.3dm` and `.dxf` import.
- Uses quadratic (6-node) triangles; the formulation follows Pilkey.
- **Licence trap:** the dependency `cytriangle` (LGPL-3.0) wraps Shewchuk's Triangle. Triangle's page says it "may not be sold or included in commercial products without a license". MIT Almond can still offer `almond-mcp[sections]` as an *optional extra* (the user installs it), but must not vendor Triangle and must document the restriction. The same trap applies to `concreteproperties`, `structuralcodes` (via `triangle`, drufat, LGPL-3.0 with a Triangle-C submodule) and `blue-prints`.
- **Permissive alternative:** `shapely.constrained_delaunay_triangles` (shapely ≥2.1, GEOS ≥3.10, already an Almond dependency) gives a constrained triangulation without quality refinement. Add midpoint or Ruppert-style refinement yourself, then 6-node warping FE, giving a Triangle-free calculator.

**concreteproperties** (MIT, v0.8.0):
- Moment-curvature, M-N and biaxial interaction, cracked properties, service and ultimate stresses for RC, composite and prestressed sections.
- Design-code modules are **AS3600** and **NZS3101** only. Eurocode appears only as stress-strain profiles.
- For EC2 use **structuralcodes** (Apache-2.0): `codes/ec2_2004` (materials, shear, crack control, creep and shrinkage, restraint cracking), `codes/ec2_2023`, `codes/mc2010` (shear, punching, torsion, interfaces), plus `sections/` (fibre and Marin integrators, shell section integrator, moment-curvature).
- This is the most credible route from "indicative" to applied EN 1992 member checks. Optional extra (Triangle caveat), or vendor individual Apache-2.0 formula modules (keep the NOTICE/licence).

### 3.5 Eurocode check libraries (EC2 / EC3 / EC5)

- **EC3:**
  - Blueprints (MIT) `codes/eurocode/en_1993_1_1_2005/chapter_6_ultimate_limit_state/formula_6_*.py` covers 6.1–6.45 and 6.54–6.55. That includes **shear 6.17–6.22** (`formula_6_18_sub_av.py` has A_v for rolled I/H/channel/…) and **M-V interaction 6.29/6.30**. `checks/eurocode/steel/strength_shear.py` implements the class 1/2 plastic shear check (I and RHS only; upright profiles only).
  - Gaps: no χ_LT (6.56–6.58) and no M_cr.
  - Vendor single formula modules (MIT, with notice) instead of depending on the package, which drags in sectionproperties/Triangle, googletrans and python-docx.
- **EC2:** structuralcodes (above). Blueprints also covers many EN 1992-1-1 chapters.
- **EC5:** **no open library does EN 1995 member checks.** Blueprints has only SLS 7.3/7.4 and a prEN 1995 stub. eurocodepy (LGPL-3.0) has timber material classes only. The Haskoning EC5 package is private. Almond will have to implement EN 1995-1-1 §6.1–6.3 (k_mod, k_h, k_crit, k_c, k_sys) itself. Material tables can be taken from EN 338/EN 14080 values.
- **Verification data:** SOFiSTiK's free verification manual (DCE-EN13/14/15/20/24/29/30 for steel; DCE-EN1–12, 31–39 for concrete).

### 3.6 Wind (EN 1991-1-4 / ASCE 7)

- No maintained open Python library was found. `dancergraham/eurocode` (MIT) is a single `ec1.py` plus a French NA module (last push 2023). Commercial tools are VelVenti (CADS) and FIN EC; `bridgesolutions.Wind` is a .NET package covering chapter 8 only.
- **Recommendation:** implement it yourself:
  - v_b = c_dir·c_season·v_b,0.
  - c_r(z) = k_r·ln(z/z₀), with k_r = 0.19(z₀/0.05)^0.07.
  - I_v.
  - q_p(z) = [1 + 7I_v]·½ρ·v_m².
  - c_pe,1/c_pe,10 tables 7.1 (walls), 7.2 (flat roofs) and 7.4a/b (duopitch).
  - All NA parameters go in Almond's existing National Annex files.
- ASCE 7-22: q_z = 0.00256·K_z·K_zt·K_d·K_e·V² (psf).
- Verify against the SkyCiv EN 1991-1-4 worked example and the IDEcad parameter checklist.

---

## 4. Validation and benchmark sources (free reference values)

| Benchmark | What it tests | Reference value | Free source |
|---|---|---|---|
| **Scordelis-Lo roof** (R=25, L=50, t=0.25, E=4.32e8 [classic value, unverified here], ν=0, gravity 90 per unit area) | Membrane plus bending, curved shell | u_z at mid free edge = **0.3086** (deep-shell theory); many FE codes converge to **0.3024** | Altair SimSolid verification VS09 (help.altair.com, "SS-V: 1080 Scordelis-Lo Roof"); MacNeal & Harder (1985) *FEAD* 1:3–20 (scanned PDF at x2go-cdm.ing.unimo.it) |
| **Pinched cylinder with rigid diaphragms** (R=300, L=600, t=3, E=3e6, ν=0.3, P=1) | Inextensional bending / membrane locking | radial u under load = **1.8248e-5** (Belytschko; an 8192² Fourier-term study gives 1.827158e-5; Lindberg 1969: 0.1825e-4) | SOFiSTiK BE41 (docs.sofistik.com, free PDF); Abaqus Benchmarks 2.3.2 (mirrors at abaqus-docs.mit.edu); SOLIDWORKS "Test of a Pinched Cylinder with Diaphragm" |
| **Pinched hemisphere, 18° hole** (R=10, t=0.04, E=6.825e7, ν=0.3, F=2 linear) | Rigid-body rotation, membrane locking | Linear: radial u ≈ **0.094** (MacNeal-Harder / Belytschko obstacle course) **[value not re-verified from primary source]**. Nonlinear NAFEMS 3DNLG-9 (F=200 total): u = −5.952 / v = 3.427 (±2%) | COMSOL "pinched hemispherical shell" model doc (nonlinear values); Altair SimSolid VNL08; ANSYS VM-R029-T9 listings |
| **MITC3+/MITC4+ benchmark set** (Jeon, Lee, Bathe 2015) | Full shell obstacle course incl. hyperboloid, Cook's membrane, twisted beam | Tables of converged s-norm/reference values | web.mit.edu/kjb/www/Principal_Publications/ (free PDF) |
| **MacNeal-Harder set** (straight/curved/twisted cantilever, plates, patch tests) | Element distortion sensitivity | Values in the paper | Paper (scanned); Altair OptiStruct OS-V 0710/0720/0760 pages reproduce them |
| **Kirchhoff plate tables** | Plate bending (simply supported/clamped, UDL/point) | e.g. SS square UDL: w_max = 0.00406·qa⁴/D | Timoshenko & Woinowsky-Krieger (book); cross-check with **scikit-fem Argyris** (BSD-3) converged solutions computed locally |
| Rectangular plate natural frequencies | Shell mass and modal | Closed form / tables | SOFiSTiK BE39 |
| Beam eigenvalues, various BCs; flexural-torsional buckling | Modal, buckling | Closed form | SOFiSTiK BE25, BE13/14/15, BE37 (2nd-order varying section) |
| **AISC 360 Commentary C2 benchmarks** | P-Delta / P-δ rigour | Tabulated amplifications | Pynite `Testing/test_AISC_PDelta_benchmarks.py` (MIT) encodes them |
| EN 1993 design checks: bending+shear, classification, flexural buckling, M+V+N, **LTB**, restrained column, class 4 | EC3 implementation | Worked numbers | SOFiSTiK DCE-EN13, 14, 15, 20, **24**, 29, 30 |
| EN 1992 checks (bending, shear, torsion, punching, cracks, deflection) | EC2 | Worked numbers | SOFiSTiK DCE-EN1–12, 17–39 |
| M_cr for doubly symmetric I-beams (C1/C2/C3) | LTB elastic critical moment | Formula and tables | Access Steel NCCI SN003 (free) **[URL not fetched]** |
| NAFEMS LE1–LE11, FV series | Linear elastic / free vibration | NAFEMS (paid) | Values reproduced in the **Code_Aster validation manual** (SSLV/SSLS/SDLS docs, GNU FDL, e.g. ericca.uqtr.ca mirrors) and in Altair/ANSYS verification pages |
| Karamba3D self-comparison | Parity | Karamba outputs | Almond's own reflection adapter (already used: 1.3% deflection) |

Suggested Almond benchmark ladder for a new shell element:
1. Patch tests (membrane, bending).
2. Kirchhoff plates vs scikit-fem Argyris.
3. Scordelis-Lo, pinched cylinder and pinched hemisphere convergence plots.
4. MYSTRAN DKT on identical meshes (should match to round-off if the formulations are equal).
5. Karamba on identical meshes (expect small differences, since TRIC ≠ DKT).

---

## 5. Licence compatibility notes for an MIT project on PyPI

1. **Permissive (MIT, BSD-2/3, Apache-2.0, ISC):** Pynite, MYSTRAN, FrontISTR, sectionproperties, concreteproperties, Blueprints, compas_*, jax_fdm, JaxSSO, scikit-fem, SfePy, TopOpt.jl, zfergus/topopt, ToPy, fatpack, efficalc, structuralcodes (Apache), FramAT (Apache), handcalcs (Apache).
   - You can depend on them or vendor them. When vendoring, keep the copyright and licence text in the file header or a `THIRD_PARTY_NOTICES`.
   - Apache-2.0: carry any `NOTICE` file and mark modified files.
   - Porting Fortran to numpy (MYSTRAN) is a derived work: keep the MIT notice.
2. **BSD-4-Clause (Kratos):** permissive but carries an advertising clause. Fine as an optional or bench dependency. Avoid vendoring, or every advertising mention of the feature would need the acknowledgement.
3. **MPL-2.0 (ShapeOp, libigl core):** file-level copyleft. Linking or depending is fine. Modified MPL files must stay MPL. libigl's GPL-3 modules must be avoided.
4. **LGPL-3.0 (IfcOpenShell, BHoM, eurocodepy, calculix/beso, cytriangle, drufat/triangle, BFE.NET):**
   - An optional Python import from MIT code is generally accepted: users can swap the library, and Almond doesn't redistribute it.
   - Never copy LGPL code into Almond.
   - anaStruct is inconsistent (LICENSE LGPL-3.0 vs pyproject GPL-3.0-or-later): treat it as GPL.
5. **GPL-2/3 (Frame3DD, CalculiX, Code_Aster, FElupe, Phaenotyp, xc, suanPan, jax-fem, ONSAS):** route (c) only.
   - Running a separately installed GPL *executable* via subprocess for benchmarking is generally treated as mere aggregation and is acceptable in `benchmarks/`.
   - Do **not** import GPL Python modules from shipped Almond code, and do not bundle them in the wheel.
6. **AGPL-3.0 (pycba ≥ the 2026-06-27 relicence, stabileo, GIBBON, dx-eurocode):** avoid entirely. That includes network or MCP use, which AGPL explicitly targets.
7. **Non-commercial / custom:**
   - OpenSees, OpenSeesPy and xara: xara's BSD-2 top-level licence does not cover the bundled UC OpenSees code (`about/COPYRIGHT`). Alpaca4d is "subject to the OpenSees license".
   - Shewchuk's **Triangle**: "may not be sold or included in commercial products without a license". It enters *transitively* through sectionproperties, concreteproperties, structuralcodes and Blueprints.
   - Keep all of these out of runtime dependencies. At most offer them as clearly documented optional extras or bench-only groups (Almond already does this for OpenSeesPy).
8. **Proprietary:** Karamba3D, Kangaroo 2 and Kiwi!3D. Use the adapter / reflection only, at runtime on the user's licensed install. Never redistribute their DLLs or examples. This is consistent with `docs/licensing-audit.md` per AGENTS.md.
9. **Paper-derived algorithms** (DKT, ANDES/OPT, MIN3, DKMQ, MITC, BESO, FDM, DR, Pilkey warping FE, NCCI SN003 formulas, EN code clauses) are not copyrightable as methods. Implementing them from the papers is clean regardless of who else implemented them.
   - Do not transcribe large tables from EN standards verbatim into the repo. Standards are copyrighted, and short parameter values are generally used in practice **[not legal advice]**.
10. **Dependency hygiene check:**
    - Adding **scipy** (BSD-3) for sparse solves and `eigsh` is safe and recommended.
    - **pyNastran 1.4.1** pins `numpy<2` and `scipy<2`, so don't add it.
    - `blue-prints` pulls `googletrans` and `python-docx`. Vendor formulas instead.

---

## Source links (primary)

- Pynite: https://github.com/JWock82/Pynite (files `Pynite/Quad3D.py`, `Plate3D.py`, `Tri3D.py`, `Analysis.py`, `FEModel3D.py`, `Testing/`)
- MYSTRAN: https://github.com/MystranSolver/MYSTRANSolver (`Source/EMG/EMG4/TPLT1.f90`, `TPLT2.f90`, `QPLT1-3.f90`, `TREL1.f90`, `QMEM1.f90`); PyPI `mystran`: https://pypi.org/project/mystran/
- FrontISTR: https://github.com/FrontISTR/FrontISTR (`fistr1/src/lib/static_LIB_shell.f90`)
- Kratos: https://github.com/KratosMultiphysics/Kratos (`kratos/license.txt`, `applications/StructuralMechanicsApplication/license.txt`, `custom_elements/shell_elements/`)
- OpenSees licence: https://github.com/OpenSees/OpenSees/blob/master/COPYRIGHT; xara: https://github.com/peer-open-source/xara (`LICENSE.txt`, `about/COPYRIGHT`)
- Code_Aster: https://gitlab.com/codeaster/src (GPL-3.0-only per GitLab API)
- CalculiX licence: https://metadata.ftp-master.debian.org/changelogs/main/c/calculix-ccx/stable_copyright; shell expansion: ccx manual mirrors (web.mit.edu/calculix_v2.7/...)
- Karamba3D: https://manual.karamba3d.com/llms.txt (component index); shells and TRIC: https://manual.karamba3d.com/appendix/bibliography; cross-section optimisation: https://manual.karamba3d.com/appendix/a.4-background-information/a.4.6-approach-used-for-cross-section-optimization.md; BESO beams: https://manual.karamba3d.com/3-in-depth-component-reference/3.5-algorithms/3.5.9-beso-for-beams.md; Large deformation: https://manual.karamba3d.com/3-in-depth-component-reference/3.5-algorithms/3.5.4-analyze-large-deformation; Timoshenko beams: https://manual.karamba3d.com/troubleshooting/4.3.-miscellaneous-problems/4.1.0-faq and grasshopper3d.com forum
- sectionproperties: https://sectionproperties.readthedocs.io/en/stable/user_guide.html; concreteproperties: https://concrete-properties.readthedocs.io/en/stable/user_guide.html
- Triangle licence: https://www.cs.cmu.edu/~quake/triangle.html; cytriangle: https://github.com/m-clare/cytriangle
- structuralcodes: https://github.com/fib-international/structuralcodes; Blueprints: https://github.com/Blueprints-org/blueprints
- compas_fea2: https://github.com/compas-dev/compas_fea2 and https://github.com/fea2; compas_fd / compas_dr / compas_tna / compas_ags: https://github.com/BlockResearchGroup
- scikit-fem plates: https://github.com/kinnala/scikit-fem (`skfem/element/element_tri/element_tri_argyris.py`, `element_tri_morley.py`, `docs/examples/ex02.py`)
- IfcOpenShell structural API: https://github.com/IfcOpenShell/IfcOpenShell/tree/v0.9.0/src/ifcopenshell-python/ifcopenshell/api/structural
- Shapely constrained Delaunay: https://shapely.readthedocs.io/en/2.1.1/reference/shapely.constrained_delaunay_triangles.html
- SOFiSTiK verification index: https://docs.sofistik.com/2026/en/verification/index.html; BE41 PDF: https://docs.sofistik.com/2026/en/verification/_static/verification/pdf/be41.pdf
- Altair Scordelis-Lo: https://help.altair.com/ss/en_us/topics/simsolid/verification%20manual/static_analysis_test_problem_vs09_r.htm
- COMSOL pinched hemisphere: https://doc.comsol.com/6.4/doc/com.comsol.help.models.sme.pinched_hemispherical_shell/pinched_hemispherical_shell.html
- MITC3+/MITC4+ benchmarks: https://web.mit.edu/kjb/www/Principal_Publications/Performance_of_the_MITC3+_and_MITC4+_shell_elements_in_widely_used_benchmark_problems.pdf
- Kiwi!3D: https://www.cee.ed.tum.de/en/st/software/research/kiwi3d/ ; https://www2.food4rhino.com/en/node/2430
- Wind: https://skyciv.com/docs/tech-notes/loading/en-1991-1-4-wind-load-calculation-example/ ; https://github.com/dancergraham/eurocode
