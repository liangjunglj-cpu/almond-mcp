# Atelier 07: environmental study

This is the neo-Swiss duplex from the structural tests, run through Almond's environmental engine
from the live Rhino model, on measured Zurich weather.

| File | |
| --- | --- |
| `A07-board-01-site-climate.png` | Site in context, sun path, monthly climate (A3, 300 dpi) |
| `A07-board-02-daylight.png` | Annual daylight per floor: DA300, direct sun (ASE), daylight factor |
| `A07-board-03-energy-comfort.png` | Envelope solar exposure, heating by month, upper-floor temperatures with and without blinds |
| `A07-board-04-rooms-constructions.png` | Rooms and constructions: plans tinted by overheating, section details, per-room results |
| `A07-daylight-simulation.mp4` | 23 s: illuminance through clear-sky 21 June and 21 December days, with the LM-83 blinds, ending on the annual result |
| `results.json` | The run IDs and metrics behind the boards (runs are stored under `%LOCALAPPDATA%\Almond\environment\runs`) |

## Results

| | Ground floor | Upper floor |
| --- | --- | --- |
| sDA300/50 % | 81 % | 66 % |
| ASE1000,250 h | 72 % | 35 % |
| Average daylight factor | 8.0 % | 3.3 % |
| Heating | 32 kWh/m² | 19 kWh/m² |
| Hours above 26 °C, no blinds | 819 (fails TM52) | 859 (fails TM52) |
| Hours above 26 °C, summer blinds | 54 (passes) | 114 (passes) |

Envelope solar exposure averages 747 kWh/m² a year over the 2,107 sensors that see sky, up to
1,285 kWh/m² on the roof, with one bounce off the ground and neighbours (55 % of it direct).
Faces that see no sky from either side, such as slab undersides and bases resting on the ground,
carry no sensors.

The fully glazed south facade gives generous daylight and a lot of direct sun. Without shading the
house overheats in a Zurich summer. External blinds in summer mode fix that and leave the winter sun,
and so the heating, unchanged.

## Rooms and constructions (2026-11-03)

The same house, now with **rooms defined by hand** and **layered constructions** assigned to its elements.
This was done in the Almond panel's Environment workspace, live in Rhino. The workspace has five steps:
Site → Rooms → Constructions → Study → Results.

- **Rooms:** eight boundary curves on the plan. Living (double height), hall and dining, entry and kitchen
  on the ground floor; study, bedroom, bathroom and landing on the mezzanine. A 4 × 4 m garden pavilion
  (roof on four posts) was added to test the open-space path.
- **Constructions:**
  - external walls: insulated concrete sandwich, exposed inside (U 0.17)
  - ground slab: RC on XPS with screed and oak (U 0.22)
  - mezzanine: RC with screed and oak
  - roof: warm flat roof with an exposed soffit (U 0.12)
  - façade: triple low-e in slim steel frames (U_w 1.10, g 0.44)
  - partitions: stud walls
  - fallback for anything untagged: the `eu_new_build` set
- **Study settings:** Zurich-Affoltern TMYx, no mechanical cooling, 80 % heat recovery on the fresh air,
  windows opened (3 ach) above 24 °C. Blinds are compared with none.

| Room | Heating kWh/m² | h > 26 °C | with summer blinds | sDA | ASE |
| --- | --- | --- | --- | --- | --- |
| Living (double height) | 45 | 3620 | 2344 | 100 % | 100 % |
| Hall and dining | 39 | 4 | 0 | 97 % | 91 % |
| Kitchen | 14 | 1081 | 397 | 70 % | 66 % |
| Study | 15 | 21 | 16 | 82 % | 0 % |
| Bedroom | 3 | 590 | 336 | 100 % | 85 % |
| Bathroom | 99 | 0 | 0 | 0 % | 0 % |
| Landing | 29 | 0 | 0 | 76 % | 0 % |
| Garden pavilion | open: SET* 16.5 °C mean (daytime), MRT above air | | | | |

What the room-by-room study shows that the floor-by-floor study hid:

- **The living room overheats.** It has about 70 m² of south- and west-facing glass on 40 m² of floor,
  and summer blinds do not fix it.
- **Other rooms are fine.** The study, hall and landing stay comfortable.
- **The bedroom and kitchen need the blinds.**

The workspace's enclosure check found that the living room opens onto the mezzanine (21 m²) and the hall
onto the stair void. It treats those openings as adiabatic: the warm air that would rise into the upper
level stays in the living room, which **overstates its overheating**. Defining the open-plan volume as
one room is the more faithful model. The bathroom and the 2.4 m² entry show high heating per m² because
small rooms at 22 °C lose heat to cooler neighbours. The rooms' exchange balances within 1 %
(42 of 4,295 kWh).

Envelope check against Approved Document L (England, OGL): walls 0.18, roof 0.15 and windows 1.10 pass
the limits; the ground floor (0.22 against 0.18) does not.

**Tropical variant (synthetic weather):** the same rooms and constructions on a *synthetic* tropical year at 1.35° N
(a test fixture, not Singapore data) with cooling to the room set-points. The Singapore pack gives RETV
11.28 W/m², under the 25 W/m² limit. The south and west façades reach about 22 W/m² each, with
solar correction factors derived from the weather file. The double-height living room needs about 530 kWh/m² of
cooling a year. This is indicative only, not a BCA Green Mark assessment. A run on a real Singapore EPW needs the
file downloaded first.

Board 04 (`A07-board-04-rooms-constructions.png`) shows:
- the step strip;
- the room plans tinted by hours above 26 °C;
- the section details of the four main constructions;
- the per-room table.

The diagram system is the panel's own. `rooms_results.json` records the rooms, constructions,
settings, run IDs and per-room results. `scripts/board_rooms.py` with `scripts/rooms.json` redraws the
board from the saved runs.

## Inputs

- **Weather:** Zurich-Affoltern, MeteoSwiss station 066640, typical year TMYx 2011–2025, from
  [climate.onebuilding.org](https://climate.onebuilding.org/WMO_Region_6_Europe/CHE_Switzerland/index.html)
  (`CHE_ZH_Zurich.Affoltern.066640_TMYx.2011-2025.epw`; not redistributed here). Almond read it with no
  missing records. TMYx radiation is derived from reanalysis and satellite data, and its direct-normal
  total (1,517 kWh/m²) is generous for Zurich.
- **Geometry:** 1,012 objects from the 3DM. Movable furniture and decorative detail are left out, as
  IES LM-83 does; sensors inside fixed joinery are dropped.
- **Reflectance:** taken from each object's render material (concrete 0.35, oak 0.30, plaster 0.75 …).
- **Glazing:** triple glazing, τ 0.70, g 0.50, U 0.7.
- **Thermal:** two zones (lower and upper floor), heavy concrete mass, wall U 0.17 and roof U 0.15.
  Mechanical ventilation with heat recovery is modelled as an effective 0.1 air change per hour.
  Residential schedule, heating to 20 °C, no cooling, natural ventilation above 24 °C. The blinds
  (g × 0.15) close above 200 W/m² on days with a mean outdoor temperature above 12 °C.
- **Video days:** a clear sky (IES clear-sky illuminance, CIE standard clear sky), not the file's
  weather, so that the sun's movement reads.

## Engine fixes from this study

This house exposed six ways real models trip the engine. Each is now fixed in `almond_mcp/environment`
and has a test:
- thin railings meshed to a million triangles;
- glass modelled as 12 mm solids, so light crossed two faces;
- a facade on a dense street was judged to face inwards;
- windows spanning two storeys were given whole to one zone;
- floorboard seams opened sensor-free strips;
- sensors were placed inside kitchen and wardrobe joinery.

`scripts/` holds the export, analysis, capture, board and video scripts as they were run. They expect
Rhino open with the working copy of the model, the almondbridge plugin loaded, and the EPW beside them.
