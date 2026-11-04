# Environmental analysis (climate, daylight, radiation, thermal comfort)

Almond can analyse a design against a real weather year: climate, sun and shadow, daylight, solar
radiation, thermal comfort and energy, per room with layered constructions.
Everything runs inside the Almond MCP server (numpy, optionally numba), so no Radiance or EnergyPlus
install is needed. Rhino is only used to export geometry and to draw the coloured results back.

What is simulated is what is visible. With no objects passed, a study exports every visible object in
the document, so hiding a layer (furniture, planting, context) removes those objects from the run as
shading and reflecting surfaces. Hidden objects, objects on hidden layers, and Almond's own
`Almond::…` result layers are left out.

## Clean-room statement

This is **not** a decompilation or copy of ClimateStudio (Solemma), whose binaries and documentation
are licensed. Nothing from it was disassembled, decompiled or read. What is shared is the set of
**public methods and standards** that tools like it are built on, implemented here from the published
papers and standards listed below. The metric definitions (sDA, ASE, UDI, DGP …) are the industry's,
not any vendor's. Results will differ from ClimateStudio's: different ray tracer, sampling and
defaults. Compare trends and options, and do not expect identical numbers.

ClimateStudio is a trademark of Solemma; Ladybug Tools, Radiance, EnergyPlus, DIVA, LEED and Green Mark
belong to their respective owners. They are named only to describe compatibility or comparison;
Almond is not affiliated with or endorsed by any of them, and uses no code from them.

## Tools

| Tool | What it does | Needs Rhino |
| --- | --- | --- |
| `climate_summary` | EPW data quality, monthly stats, degree days, design temps, wind rose, outdoor comfort, bioclimatic strategy hours, psychrometric bins | no |
| `sun_path` | sunrise/noon/sunset, hourly sun positions, sun-path diagram data | no |
| `analyze_daylight` | `annual` (sDA, ASE, DA, cDA, UDI, EN 17037, DGPs views), `daylight_factor`, `point_in_time` | grid on Rhino floors, or `shoebox` |
| `analyze_solar_radiation` | kWh/m² and direct-sun hours on any surfaces, any period | Rhino surfaces, or `shoebox` facade |
| `analyze_thermal` | ISO 13790 hourly zones: heating/cooling kWh/m², peaks, operative temperature, adaptive comfort, TM52, PMV | closed Rhino volumes, or `shoebox` |
| `thermal_comfort` | PMV/PPD, operative temperature, psychrometrics, adaptive limits for one condition | no |
| `show_environment_result` | draw a saved run as a coloured mesh + legend on `Almond::Environment::…` | yes |
| `list_environment_runs`, `get_environment_run` | saved runs (JSON + arrays + PNG plans) | no |
| `list_environment_materials` | material library, layer-name rules, construction presets | no |

Weather files: any EnergyPlus `.epw` file (for example from climate.onebuilding.org).

### Typical session

1. `climate_summary(epw_path=…)` and `sun_path(epw_path=…, month=12, day=21)` to read the site.
2. Put floors, walls, ceilings and glazing on named layers (`Glazing`, `Walls`, `Floor` …), cut the
   openings in the walls, then call `analyze_daylight(epw_path=…, grid_guids=[floor GUIDs])`.
3. **Read `scene.classification`** in the result. Every object is listed with the material it got
   and why (layer-name match, user text, transparency, or orientation fallback). Fix layers, or pass
   `materials={"Building::Feature wall": {"reflectance": 0.3}}`, then run again.
4. `show_environment_result(run_id, metric="ase_hours")` to see another metric in Rhino.
5. `analyze_thermal(epw_path=…, zone_guids=[…], free_running=True, natural_ventilation_ach=4)` for
   passive comfort, or with set-points for loads.

To study without Rhino (quick option testing, teaching), give any analysis tool a `shoebox`, e.g.
`{"width": 6, "depth": 8, "height": 3, "orientation": 270, "wwr": 0.4, "overhang": 0.8}`.

## Methods

**Weather (epw.py).** Follows the EnergyPlus Auxiliary Programs EPW data dictionary. Missing-value
sentinels and out-of-range values become gaps. Gaps of up to 6 h are interpolated and longer ones
take the mean of the same hour in the same month. RH and dew point are derived from each other.
Night-time irradiance is zeroed, and GHI/DNI/DHI closure is checked. Missing illuminance comes from
the Perez et al. (1990) luminous efficacy model. 29 February is dropped and sub-hourly files are
averaged to hourly. Every repair is counted in `data_quality`.

**Sun (solar.py).** NOAA solar position (Meeus 1991), about ±0.01°, with refraction. EPW hours are
hour-ending, so positions are taken at mid-interval.

**Skies (sky.py).** Tregenza 145 patches and Reinhart subdivisions (577, 2305) plus a ground patch.
The Perez, Seals & Michalsky (1993) all-weather luminance distribution is normalised so that each
hour reproduces the file's diffuse horizontal value exactly. Also available: the CIE 1955 overcast
sky, a uniform sky, and the 15 CIE general standard skies (ISO 15469).

**Daylight (daylight.py).** This is the daylight coefficient method (as in Radiance `rcontrib` /
five-phase):

* direct sky coefficients: every patch is sampled with stratified shadow rays through clear glazing
  (Fresnel angular transmittance of a single-pane equivalent, n = 1.52);
* interreflections: an irradiance-cache radiosity solve. Sensors' eye rays find the surface cells
  they see, those cells' rays find the next ones (one level per bounce), every cell gets
  deterministic direct sky coefficients, and E = Dc + F·ρ·E is iterated. Sensors gather from
  their first hit only, which keeps per-sensor noise low and the sun patch's interreflected light
  smooth. At medium quality its mean is 2–5 % above a 4,096-path unbiased reference (the cost
  of the cache's cell discretisation), with 3–5 % median per-sensor noise between runs;
* the sun is traced exactly each hour, for both direct illuminance and ASE;
* dynamic shading follows IES LM-83-12. Each aperture group (one per facade orientation) closes a
  diffusing shade in any hour where more than 2 % of sensors get over 1000 lux of direct sun. The
  closed state has its own coefficients.

Metrics: sDA300/50 % and ASE1000,250h (LM-83, 08:00–18:00 every day by default), DA, cDA, UDI
(Nabil & Mardaljevic 2005 bins), EN 17037 daylight provision levels (illuminance method), daylight
factor (CIE overcast) split into its direct and interreflected parts with the EN 17037 DF targets for
the site, and simplified DGP (Wienold 2009) for view points. DGPs is reported only for hours
without direct sun at the eye, where it is valid. The hours with the sun in view are counted
separately (`sun_in_view_pct`), and DGPs is capped at 1.

**Radiation (radiation.py).** Cumulative Perez solar sky by daylight coefficients plus the sun
traced every hour. One diffuse bounce is on by default, so light reflected by modelled ground and
neighbours counts, and `ground_reflectance` applies to modelled ground as well as the ground beyond
the model. With `bounces=0` only direct sky and sun count. Direct-sun hours use the WMO
bright-sunshine threshold (DNI ≥ 120 W/m²). The climate summary calls the same count
`bright_sun_hours`: in typical-year files with modelled radiation it can far exceed measured
sunshine.

**Thermal (thermal.py).** ISO 13790:2008 simple hourly method (5R1C, Annex C), with Crank–Nicolson
steps, the standard's 10 W/m² test for exact heating/cooling need, Table 12 thermal-mass classes,
and the sky-radiation and opaque solar terms. Solar gains are ray traced on the real windows and
walls with the context (no transposition model). Fresh air is set per floor area by schedule
(indicative EN 16798-1 Category II: office 1.4, school 4.0, homes 0.42 l/s·m²), so a double-height
room is not ventilated twice as hard; infiltration defaults to 0.3 air changes per hour. Natural
ventilation opens when it is warm inside and cooler outside. Ground floors see the EPW ground
temperatures. Zones that are not rooms (a wall, a slab, under 2 m² of floor) are rejected.

**Comfort (comfort.py).** PMV/PPD per ISO 7730:2005 Annex D. Adaptive comfort per ASHRAE 55-2020
§5.4 (including the elevated air speed allowance) and EN 16798-1:2019 Annex B (running mean α 0.8).
Overheating per CIBSE TM52 (three criteria). Psychrometrics use the ASHRAE Fundamentals
(Hyland–Wexler) equations.

## Rooms, constructions and code packs

### Rooms (user-defined zones)

Mark the rooms yourself, in the panel (Environment → Rooms) or with `define_room`. A room is:

- a **closed volume** (one polysurface, extrusion or closed mesh);
- the **surfaces that bound it** (a roof and two walls, a canopy on posts). The room is then the prism
  over the convex hull of their plan, from their lowest to their highest point;
- a **closed planar curve** with a height, which is extruded.

The tags are Rhino user text: `almond:room`, `almond:room_use`, `almond:room_set`, `almond:room_heat_c`,
`almond:room_cool_c` and `almond:room_height`. Room uses (living, bedroom, kitchen, bath, circulation,
office, classroom, outdoor) set gains, schedule, set-points and fresh air. They are Almond's documented
assumptions (`rooms.ROOM_USES`) and can be overridden per room.

**Rooms do not have to be enclosed.** Each room's boundary is sampled on a ~0.5 m mesh. Every sample
probes for a building element within 0.35 m, inside or outside, so walls drawn as solids around a
room are found. Faces shared with another room count as internal. Faces left open are then sorted:

- **Openings to outside.** The space beyond the face is not enclosed by the building.
- **Internal openings.** The space beyond is enclosed: rays from it hit the building in nine of ten
  directions. Typical cases are double-height voids, stair openings and gallery edges.

The open share of the sides and top picks the method. Each result says which method was used.

| State | Open to outside | Method |
| --- | --- | --- |
| enclosed | < 5 % | ISO 13790 5R1C with the room's constructions. Smaller gaps are reported, not modelled. |
| semi-open | 5-30 % | 5R1C plus the air through the openings: single-sided per de Gids and Phaff (1982), cross ventilation by orifice flow. Free-running, no heating or cooling. |
| open | ≥ 30 % | Semi-outdoor comfort. Air is at outdoor temperature. Mean radiant temperature comes from sky, roof underside and ground, plus sun on the body (SolarCal, cylindrical body). Comfort is SET\*. No loads are reported. |

Room names are unique (objects are grouped into a room by name, so `define_room` refuses a name already in use),
heights are metres (up to 100 m) and set-points 5-40 °C with heating below cooling. A room that cannot be built
(no height, too small, an open curve) is left out with a note, and the other rooms are still analysed.
The ground is the lowest room floor: a room raised above it with no room below has an exposed floor.
A face behind a window takes the construction of the wall it sits in. In daylight studies a self-enclosed
room volume keeps its own windows clear, and a room on the ground with no floor element gets one.
Heat recovery bypasses in mild weather: it runs below the heating set-point + 2 K, or above the cooling
set-point when cooling.

Internal openings are treated as adiabatic, with no air exchange between the rooms. Define open-plan
spaces as one room. When nothing is modelled around a closed room volume, its own faces are the
envelope, which is the classic zone workflow.

Rooms exchange heat through shared walls and floors (H = U·A), across a slab or partition up to 0.35 m
thick. The coupling uses the previous pass's air temperatures, over three passes; the net exchange
balances to zero: each pair of rooms has one conductance. Where only one room has a
construction for the shared face it is used; with none, 1.5 W/m²K (a light partition) stands in. Thermal mass comes from the constructions:
C_m = Σ κ·A and A_m = C_m² / Σ κ²·A (ISO 13790 12.3.1.2). A ceiling sees the soffit side of the floor
above.

### Constructions

`list_constructions`, `get_construction` and the panel's Constructions step show the library: about 40
assemblies (external walls, roofs, ground, exposed and intermediate floors, partitions, doors and
windows) plus construction sets for Europe and Singapore. A custom build-up can be evaluated inline.
Elements get one with `assign_construction` (user text `almond:construction`). A room takes the
construction of each element that bounds it; its set fills the rest. Untagged faces fall back to the
study's preset.

Calculations, each implemented from the procedure of the named standard; no tables are copied:

- U-value by the EN ISO 6946 procedure. Surface resistances depend on heat-flow direction;
  unventilated air layers use convection plus radiation. Ventilated claddings are left out.
- Areal heat capacity κ by the EN ISO 13786 periodic method (24 h, surface resistances included).
  Exposed concrete is about 80 kJ/m²K; a plasterboard partition about 13.
- Glazing: U_g by the EN 673 procedure (gas Nusselt number, emissivities). Solar and visible
  transmittance by multiple reflection between the panes. g = τ_e plus the inward share of the absorbed
  heat. U_w by the EN ISO 10077-1 area-weighted method.
- Finishes set the daylight reflectances. The top of a roof shows its outside layer, the underside of a
  floor its soffit, and everything else the inside finish. Window assemblies set τ_v, g and U.

Data provenance: material λ/ρ/c and glass optics come from the EnergyPlus datasets (ASHRAE Handbook of
Fundamentals values; BSD-style licence). Reflectance defaults come from honeybee-standards (MIT).
Finishes, frames and the build-ups themselves are labelled Almond assumptions. Every value carries a
source id (`data/sources.json`). Thermal bridging by studs, ties and fixings is not included: treat
timber-frame and fixed-insulation U-values as lower bounds.

### Code packs (`list_code_packs`, `check_envelope`, `analyze_rooms(envelope_pack=...)`)

| Pack | Relation | What it checks |
| --- | --- | --- |
| `sg_bca` | method | ETTV (non-residential) or RETV (residential) per facade and overall, and RTTV with skylights. The formulas come from the BCA Code on Envelope Thermal Performance. Solar correction factors are derived from the site EPW, per true orientation (the model's north rotation is applied to the facades). SC = g / 0.87 over the whole window; external shading devices are not credited (conservative). A weather file outside Singapore is flagged. Your own licensed CF tables can be loaded with `user_tables_path`. **Indicative; not a BCA Green Mark assessment.** |
| `uk_adl_2021` | bundled (OGL v3) | Area-weighted U per element against the Approved Document L limiting values, plus the notional dwelling fabric. |
| `de_banz_2020` | bundled (public domain) | German flat-rate U-values of unrefurbished elements, by construction age band. |
| `eu_hotmaps` | bundled (CC BY 4.0) | EU building-stock U-values by country, sector and period (TABULA-based). |

The packs are design checks. None performs a jurisdiction's whole-building compliance calculation (SAP,
SBEM, GEG, Green Mark scoring). Australian NCC and NZ H1 data are openly licensed (CC BY 4.0) and are
planned packs; they are not keyed yet.

### Panel workspace

The Almond panel's Environment workspace has five steps: Site → Rooms → Constructions → Study → Results.
Each step opens with an orientation diagram: the step strip, the sun path, the room plan with enclosure
state, the section detail of a construction, and the study section. The results show a tinted room plan
and metric tiles, and the per-room colours are drawn in the viewport. Diagrams come from
`environment/diagrams.py`, which renders the same drawing to SVG for the panel and to PNG for boards in
the archive's palette. The panel runs studies out of process (`almond-mcp environment`, JSON on stdin and
stdout). Its export and draw scripts are the MCP tools' own, so the two always agree.

## Validation (tests/test_environment.py)

| Check | Reference | Result |
| --- | --- | --- |
| Unobstructed sensor, uniform and CIE skies | E = E_h exactly | ±1 % |
| Sensor under a square skylight in an opaque plane | analytic view factor (parallel rectangle) | ±3 % |
| Downward sensor over an infinite ρ = 0.5 plane | E = ρ E_h | ±1.5 % |
| Sun through horizontal glass | cos θ · τ(θ) | 1e-4 |
| Shoebox interreflected DF | BRE split-flux formula | same range (0.7 % vs ≈ 0.7 %) |
| Interreflection cache solve | unbiased path tracer, 2,048–4,096 paths/sensor | +2 to +5 % mean, medium quality |
| Open horizontal sensor, annual | Σ GHI of the file | ±3 % |
| Sky matrix | reproduces the file's DHI each hour | 1e-9 |
| PMV, 8 cases | ISO 7730 algorithm (pythermalcomfort) | ±0.01 |
| Adaptive EN 16798 / ASHRAE 55 | standard formulas | exact |
| 5R1C steady state | conductance network by hand | 1e-4 |
| BVH ray casting | brute force | identical hits |

## Limits (read before trusting a number)

* Materials drive results as much as geometry does, so the result always lists the classification.
  Defaults follow LM-83 (ceiling 70 %, walls 50 %, floor 20 %, ground 20 %).
* Glazing transmits specularly and does not reflect. Shades are ideal diffusers. There are no
  BSDFs, no complex fenestration and no specular materials.
* Windows drawn over uncut walls let no light in. This is detected and reported.
* DGPs is not valid with the sun in view. Those hours are counted separately, so treat them as
  glare. Use DGPs to compare options, not to certify glare.
* Grid surfaces can be single surfaces or solids. A work-plane grid uses only horizontal faces, and
  keeps the upper of two stacked faces. Radiation grids drop faces that see no sky from either side
  (the underside or inner face of a solid). A floor or roof solid's underside is classified as
  ceiling.
* Name rules read layer, object and render-material names. Window frame parts (mullion, transom,
  sill, frame …) are frames, not glass, and "roof slab" is a roof.
* "Glass" in a name or render material does not make every object a window. Curtains, drapes,
  blinds and sheers are textiles: they are opaque `shading` (ρ 0.5), and only a curtain *wall* is
  glazing. Glass inside the room is not glazing either. Glassware (tumbler, carafe) and shower
  screens are ignored, since they are small and clear. Mirrors, oven doors, laptops and TVs are
  opaque `furniture`. Any other object can be set with an `almond:env_material` user text, a
  `materials` override or a construction.
* The thermal model is a single-zone RC network: interzone heat flow is adiabatic, there is no
  moisture balance, and the schedules are presets. It is good for comparing options and for
  overheating risk. For compliance, use EnergyPlus.
* Speed: install the `fast` extra (`uvx --from "almond-mcp[fast]" almond-mcp`) for compiled ray
  casting, about 100× faster. Without it the numpy path gives the same results, only slower.
  An annual study on a real model can take longer than an MCP client waits. Pass `background=True`
  to `analyze_daylight`, `analyze_solar_radiation` or `analyze_thermal`: you get a `job_id` at once,
  and `get_environment_run(job_id)` reports progress, then returns the result.

## References

Perez R. et al. (1990) Solar Energy 44(5) 271–289 · Perez R., Seals R., Michalsky J. (1993) Solar
Energy 50(3) 235–245 · Tregenza P. (1987) Lighting Res. Technol. 19(1) · Reinhart C. (2011)
Daysim / Radiance MF subdivision · IES LM-83-12 · EN 17037:2018 · ISO 15469:2004 · ISO 7730:2005 ·
ASHRAE 55-2020 · EN 16798-1:2019 · ISO 13790:2008 · CIBSE TM52 (2013) · Nabil & Mardaljevic (2005)
Lighting Res. Technol. 37(1) · Wienold J. (2009) Building Simulation 2009 · Meeus J. (1991)
Astronomical Algorithms · Givoni B. (1992) Energy and Buildings 18(1).
