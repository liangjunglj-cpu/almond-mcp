"""Harness Karamba's 01_InputCurvesAsTruss.ghx for the karamba_truss_v1 capsule.

Same GH_IO surgery recipe as tools/harness_frame_capsule.py (see there for
the mechanics: the Karamba examples are BINARY archives misnamed .ghx;
GH_IO.dll converts them without opening Grasshopper). The truss capsule
uses 01_InputCurvesAsTruss.ghx - the example built to take external
curves - rather than the slider-parametric 01_ParametricTruss.ghx the
manifest originally pointed at; its Line-Line Intersection stage shatters
input lines at crossings, so continuous chords node-merge automatically.

Harness contract (mirrors capsules/karamba_truss_v1.capsule.json):
  ALMOND_IN_LINES     rename of the template's existing floating Curve
                      param "Crv" (BindParam clears its referenced data)
  ALMOND_IN_LOAD_KN   Param_Number -> Unit-Z factor that drives the
                      per-node vertical point loads (replaces the
                      "live load" slider; the panel-driven gravity/self-
                      weight branch is untouched)
  ALMOND_IN_SUPPORTS  Param_Point  -> all three Support components'
                      "Pos|Ind" inputs
  ALMOND_OUT_DISP_MM  Param_Number <- Analyse "Maximum Displacement [cm]"
  ALMOND_OUT_MASS_KG  Param_Number <- Assemble Model "Mass [kg]"
  plus: the point-load Pos|Ind (inside the Loads component's EvalUnits)
  is repointed from the example's referenced Rhino points to the
  Line-Line Intersection node output, so EVERY model node receives the
  load regardless of input geometry.

Key instance guids inside 01_InputCurvesAsTruss.ghx:
  Crv param            42c85f85-1f62-456a-a62e-a8c4cef82252
  live-load slider     c439d8fa-33d6-4317-bf3d-e7219de0c331
  LLInter node points  9377820c-2a0d-4ee5-a0ef-dce6d58dd244
  Analyse disp [cm]    0a6e6a16-ab70-484f-b5f7-768e520f3bbf
  Assemble mass [kg]   c2540a19-d98f-49b2-af5c-ef3daa1e106c

Verified live 2026-08-29 (bridge 0.5.3, which unit-scales guid geometry
to port units): a 6 m x 0.9 m Warren truss (7 members, mm document) with
25 kN per node and 2 base support points returned disp 0.4996 cm
(5.0 mm ~ L/1200) and mass 310 kg via run_gh_definition; the 3
rigid-body-mode warning is Karamba's correct planar-truss-in-3D
diagnosis, matching the api pathway's behavior on the same geometry.

The surgery was executed inline during the 2026-08-29 session; to re-run
it, follow tools/harness_frame_capsule.py with the constants above (the
helper functions are identical). Deployment target:
Grasshopperfiles/Karambafiles/harnessed/01_InputCurvesAsTruss.ghx.
"""

raise SystemExit(
    "This file documents the truss harness; run the surgery by adapting "
    "tools/harness_frame_capsule.py with the constants in the docstring.")
