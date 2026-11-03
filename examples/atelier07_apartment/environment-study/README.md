# Atelier 07: environmental study

This is the neo-Swiss duplex from the structural tests, run through Almond's environmental engine
from the live Rhino model, on measured Zurich weather.

| File | |
| --- | --- |
| `A07-board-01-site-climate.png` | Site in context, sun path, monthly climate (A3, 300 dpi) |
| `A07-board-02-daylight.png` | Annual daylight per floor: DA300, direct sun (ASE), daylight factor |
| `A07-board-03-energy-comfort.png` | Envelope solar exposure, heating by month, upper-floor temperatures with and without blinds |
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
