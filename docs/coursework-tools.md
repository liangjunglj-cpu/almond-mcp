# Coursework workflow: what a comfort course asks for, and what Almond does now

This note compares a university course on comfort in architecture with Almond. Students take a shoebox
through seven design cases, then a multizone building study with daylight, view, loads and adaptive
comfort. The comparison is functional: it lists what the exercises ask students to produce and checks
whether Almond can produce it. It did not use another tool's interface, documentation, defaults or code.
Method notes are in [environmental-analysis.md](environmental-analysis.md#coursework-style-studies).

## Gaps found and what was built

| The exercise asks for | Before | Now |
| --- | --- | --- |
| Warmest and coldest week of the weather file | monthly statistics only | `climate_summary` → `extreme_weeks`: computed from the hourly data, with the hottest / coldest day in each. The file's own typical / extreme periods are listed with their real length: a file's "week" can span 15 days across the year end, which a student had noticed. |
| Monthly diurnal averages (dry-bulb, wet-bulb, GHI, DHI, DNI) | not available | `climate_summary(diurnal_chart=True)`: chart and CSV |
| Sun path with shadows at 09:00, 12:00 and 15:00 on 20 March | sun-path data | `shadow_study`: ray-traced shadow plans with sun dial, north and scale. The time convention is stated: local standard time, with each shot's solar time. |
| Heating 21 °C occupied / 18 °C setback | heating off when unoccupied | `heating_setback`, `cooling_setback` |
| 0.11 people/m² at 1.2 met; 5 l/s per person + 1 l/s·m² | gains in W/m², fresh air per m² | `people_per_m2`, `ventilation_l_s_person` |
| Heating and ventilation November–April, natural ventilation May–October | all year | `heating_months`, `cooling_months`, `ventilation_months`, `natural_ventilation_months` |
| Shade closing above 150 W/m² on the window | fixed 300 W/m² | `shading_on_above_w_m2` |
| Custom weekday / weekend (binary) schedules | four presets | `custom_schedule` |
| Hourly operative temperature of ID0–ID6 against outdoor air, warmest and coldest week | per-case runs, no export | `compare_thermal_cases`: table, charts, and one CSV with every case's operative temperature |
| Hourly energy balance of ID0 on the hottest and coldest day | not available | an hourly balance per zone that closes to zero every hour, as charts and CSVs in kWh/m². Columns are named, so nothing is found by position. |
| Heating set-point from PMV for activity and clothing | PMV for one condition | `comfort_setpoints`: lowest / highest temperature on the category's PMV limits |
| Adaptive comfort May–October: too hot / too cold hours against occupancy | % of the whole year | `adaptive_en16798_hours`, category I–III hour counts over `comfort_months` |
| Whole-building heating and lighting kWh/m²·yr | per room | `building` totals in `analyze_rooms` and multi-zone `analyze_thermal` |
| Mean DF, DA 2 m from the window, sDA, EN 17037 levels, as a table and bar charts | per run | `analyze_daylight(probe_distance_from_window_m=2)` and `compare_daylight_cases`, which also models a static blind |
| EN 17037 view out (ID0 vs ID6, view plane 1.22 m) | not available | `en17037_view_out`: sight angle, outside distance, layers, level map |
| EN 17037 access to sunlight on a day between 1 Feb and 21 Mar | direct-sun hours on surfaces | `en17037_sunlight`: per window, on a day or over the range, with the best day and a chart |

Almond already avoids some of the problems the course notes record:
- Model units are read from the document, so a centimetre model needs no rescaling.
- Rooms do not have to be zero-thickness closed volumes, and windows within 0.3 m of a room face count.
- Every input that was assumed is listed with the result.

## In the Rhino panel

The Environment workspace takes the same order as the course: Site → Rooms → Constructions → Study →
Results → Compare. The layout, names and visuals are Almond's own; only the sequence of tasks follows
the exercises.

| The exercise step | Where it is in the panel |
| --- | --- |
| Climate analysis: extreme weeks, diurnal averages | Site → Climate (chart and CSV) |
| Sun path and shadows on 20 March | Site → Sun & shadow plans |
| Occupants, fresh air, set-points, setbacks, seasons | Study → Thermal → People & fresh air, Set-points & seasons |
| Heating set-point from PMV | Study → Thermal → Set-points from comfort (PMV) |
| Operative temperature in the warmest / coldest week, energy balance on the hottest / coldest day | Results → charts (pick the room for the balance) |
| Hourly data for the spreadsheet | Study → Write hourly CSV per room; Results → Open run folder |
| Design cases side by side (ID0–ID6) | Results → Keep as case, then Compare |
| EN 17037 view out and sunlight | Study → View out / Sunlight on windows |
| Lighting with 300 lx stepped dimming | Study → Thermal → Lighting control (dim continuously, in steps, or switch off) |

### Daylight-linked lighting, checked

The course's lighting runs "300 lx stepped dimming". Almond now models it: `lighting_control` traces the
daylight at control points over each floor and dims, steps or switches the lights to top up to the target.

**South-facing office shoebox, Zurich:**
- Lighting falls from 21.2 to 6.7–10.3 kWh/m² at 20 % glazing (on/off to continuous) and to 3.1–3.8 kWh/m²
  at 70 %.
- Heating rises a little and cooling falls, because the lights give off less heat.

**The Atelier's rooms, residential schedule, stepped:**
- Building lighting falls from 6.9 to 5.2 kWh/m². Most lit hours are evenings, so the saving is
  modest; the windowless bathroom saves almost nothing.

## Not done yet

- **Air walls and doors between zones.** Internal openings are treated as adiabatic.
- **Glazing classification by name.** The name rule meant for "curtain wall" also catches interior
  textiles and glass objects (curtains, tumblers, an oven door), which are then treated as clear glazing
  in daylight studies. `en17037_sunlight` avoids it by using the windows that carry a window
  construction. Fixing the rule would change existing models' daylight results, so it is left for its
  own change.

## Example output

Exercise-1-style cases on a 17.4 m² shoebox in Helsinki (TMYx), and the Atelier 07 house:

| Image | |
| --- | --- |
| `images/coursework-tools/01-monthly-diurnal-averages.png` | monthly diurnal averages |
| `images/coursework-tools/02-shadow-plans-atelier.png` | shadow plans, 20 March 09:00 / 12:00 / 15:00 |
| `images/coursework-tools/03-operative-warmest-week.png`, `04-…coldest-week.png` | ID0–ID6 operative temperature against outdoor air |
| `images/coursework-tools/05-energy-balance-hottest-day.png`, `06-…coldest-day.png` | ID0 hourly energy balance |
| `images/coursework-tools/07-bars-mean-df.png`, `08-bars-sda.png` | daylight cases |
| `images/coursework-tools/09-sunlight-per-day-atelier.png` | EN 17037 sunlight per window, 1 Feb – 21 Mar |
| `images/coursework-tools/10-view-out-level-id0.png` | EN 17037 view-out level in ID0 (medium everywhere, high on 73 % of the floor; behind the ID6 neighbour it falls to minimum everywhere) |
