# Rooms, constructions and the Environment panel: live test (2026-11-03)

This is a rerun of the whole environment feature on `master` after PR #43 (`39619a7`). It has two parts:

- the automated test suite, run in full;
- the Atelier 07 house run in a live Rhino 8 through the Environment panel, with each step captured.

The run found three panel display problems, all fixed and covered by tests, and one documentation gap,
now documented.

## Test suite

| Run | Result |
| --- | --- |
| `pytest` on master, as run normally | 459 passed, 101 skipped |
| The 101 skipped tests, with the .NET archive host built (`tests/archive_host`) and `ALMOND_ARCHIVE_TEST_HOST` set | 105 passed |
| Full suite after the fixes below, archive host set, so nothing skipped | **562 passed, 0 skipped** (560 + 2 new regression tests) |

The only reason anything was skipped is the archive host. With it built, every test in the repository
runs: the panel workspace, the archive distribution, and the native mesh decoder on all 50 models.

## Live run in Rhino

**Setup:**

- Rhino 8 with the almondbridge built from this branch: archive rebuilt with the fixes below, bridge
  token check on.
- A scratch copy of the Atelier 07 model, never the repo's `.3dm`. It has 9 rooms: 8 enclosed and the
  open garden pavilion. It has 7 assigned constructions.
- Weather: Zurich-Affoltern and Singapore-Changi TMYx (2011–2025). These files are not in the repo.

**How it was driven:** each step was driven through the panel's own web view: setting the controls,
clicking the buttons and reading the panel back. The one step that was not is the weather-file dialog;
the site step was given the EPW path directly. Captures are full-page renders of the panel, in Rhino's
dark theme, plus Rhino viewport captures composited onto paper.

`live-panel-run.log` records every step: control values, headline, results table, code check and notes.

| Image | Step |
| --- | --- |
| `01-rhino-model.png` | The Atelier 07 house and the open garden pavilion in the Rhino viewport |
| `02-panel-home.png` | Panel home: Models, Structural Validation, and the Environment card |
| `03-panel-site-zurich.png` | **Site**: Zurich weather loaded. Sun path, latitude, mean air 10.6 °C, 1295 kWh/m² |
| `04-panel-rooms.png` | **Rooms**: room plan per level, table, and a warning on each room that is not fully closed (pavilion 66 % open, internal openings, model gaps) |
| `05-panel-constructions-wall.png` | **Constructions**: the insulated concrete sandwich wall, with section, U 0.17, κ 84 kJ/m²K |
| `06-panel-constructions-window.png` | Triple low-e window in a slim steel frame: U_w 1.10, g 0.44, τv 0.63 |
| `07-panel-study-thermal.png` | **Study**: thermal, 3 ach window ventilation, 80 % heat recovery, summer blinds, UK Part L check |
| `08-panel-results-thermal-zurich.png` | **Results**: hours above 26 °C per room, per-room table, notes, code check |
| `09-rhino-thermal-zurich.png` | The same result drawn in Rhino (envelope and fit-out hidden for the capture) |
| `10-panel-study-daylight.png` | Study: annual daylight, medium quality, 0.5 m grid |
| `11-panel-results-daylight-zurich.png` | sDA / ASE per room |
| `12-rhino-daylight-zurich.png` | DA300 on each room's work plane, both levels and the pavilion |
| `13-panel-site-singapore.png` | Site: Singapore weather. Latitude 1.37°, mean air 28 °C |
| `14-panel-results-thermal-singapore.png` | Cooled tropical run with the BCA RETV check |
| `15-rhino-thermal-singapore.png` | The Singapore result in Rhino |
| `site-diagram-north-0-and-200.png` | The fixed site diagram with north up and north at 200° |
| `before/` | The two problems before their fixes (see below) |

### Results reproduce the committed study

With the model's own layer state, every number matches `examples/atelier07_apartment/environment-study/rooms_results.json`
exactly.

| Study | Room or index | This run | Committed |
| --- | --- | --- | --- |
| Thermal, Zurich, blinds | Living room, h > 26 °C | 2333 | 2333 |
| | Kitchen / Bedroom / Study | 395 / 328 / 28 | 395 / 328 / 28 |
| | Heating: Living / Bathroom / Entry, kWh/m² | 45.8 / 99.6 / 61.9 | 45.8 / 99.6 / 61.9 |
| | Garden pavilion, SET* mean | 16.5 °C | 16.5 °C |
| UK Approved Document L | window / wall / roof / ground floor | pass / pass / pass / fail (0.216 vs 0.18) | same |
| Annual daylight, Zurich | sDA: Study / Landing / Hall and dining | 75.8 / 73.2 / 96.6 % | 75.8 / 73.2 / 96.6 % |
| | ASE: Bedroom / Kitchen | 84.8 / 65.7 % | 84.8 / 65.7 % |
| Thermal, Singapore, cooled | Living room cooling | 450.3 kWh/m² | 450.3 kWh/m² |
| BCA RETV | overall / S / W | 10.94 / 22.88 / 19.34 W/m² | 10.94 / 22.88 / 19.34 W/m² |

Run times with numba: thermal 55 s, annual daylight 370 s, Singapore 59 s.

### Test-drive fixes, rechecked live

`test-drive-recheck.log` reruns the Rhino-side checks from the independent test drive (`73d5c06`) on
throwaway geometry, which is deleted afterwards. All of them behave as intended:

- **Tags are all-or-nothing:** a request with one missing object tags nothing.
- **Duplicate room names are refused.**
- **Heights and set-points are checked:** a height of 3000 (model units) and set-points of 26/20 °C
  are both refused.
- **Bad geometry is reported:** an object tagged as a room on an open curve is listed as having no
  usable geometry.
- **A closed room lets its own window's light in:** daylight factor 2.97 %.
- **Strict option parsing:** the Singapore check on a Zurich weather file, with `residential="false"`,
  reads as ETTV (non-residential) and warns that the weather file is not for Singapore.

The first attempt of this script, run straight after the panel session, failed differently. Its
test boxes were reported missing after the refused tag request. The second run passed in full. A third
repeated the panel-then-recheck sequence, and its first checks passed before its output was cut short. A minimal repeat of the suspected cause did not
reproduce it either: a script that throws after an earlier script added geometry. That suspected cause
is `ScriptExecutor` calling `doc.Undo()` when a script fails. This is recorded as an **open item**, not
a confirmed bug.

## What the live run found

1. **Diagrams were nearly unreadable in Rhino's dark theme** (`before/dark-panel-diagram.png`).
   - Cause: the panel takes Rhino's palette, so `--paper` becomes dark grey. The engine's diagrams are
     drawn in fixed ink colours, so section titles, layer labels, OUT/IN and the U/g/κ figures were
     dark grey on dark grey.
   - Fixed: every environment diagram now sits on a fixed paper sheet (`--sheet`, the archive paper
     `#efeee8`) in light and dark panels alike, like a drawing on paper (`environment.css`).
2. **The page title read "Climate, Rooms& Comfort".** The panel hides the heading's `<br>`, and the
   space was missing. Fixed in `index.html`.
3. **The site name ran into the north mark** (`before/site-name-under-north.png`). The location title
   sat top-left, so a long name such as "Zurich.Affoltern, ZH, CHE" ran under the "N". With north
   rotated to the south, the caption collided instead. Fixed: the name and caption move to whichever
   half is away from the north mark (`diagrams.site_diagram`), as shown in
   `site-diagram-north-0-and-200.png`.
4. **Undocumented: a study simulates visible objects only.**
   - What happened: an early rerun had decorative layers hidden ("Objects and graphics", "Lighting")
     to tidy the captures. Thermal results moved by a few hours and daylight sDA by up to 9 points.
   - Why: the export skips hidden objects and hidden layers, by design. Hiding furniture or planting
     removes them from the simulation.
   - Now documented in `docs/environmental-analysis.md`. The captures above hide layers only while
     the picture is taken, never during a run.

Problems 1–3 have regression tests in `tests/test_rooms_constructions.py`.

## Still open

- **The first test-drive recheck's missing geometry,** described above. It did not reproduce.
  - Worth guarding: `ScriptExecutor` could call `doc.Undo()` only when the failed script actually
    changed the document.
- **Singapore result plan:** for cooled rooms it shows hours above 26 °C operative. In Singapore that is
  close to 8760 h in every cooled room, so the plan is uniformly dark. Cooling kWh/m² would be the more
  useful map for cooled runs. The README of the Atelier study reports hours above 28 °C for this
  reason.
- **The EPW file dialog** ("Choose weather file") was not exercised. The path was passed to the site step.
