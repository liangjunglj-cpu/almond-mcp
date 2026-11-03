# Third-party notices

almond-mcp builds upon or references the following third-party work. This
file must accompany any distribution of the software, including standalone
distribution of the compiled `RhinoAlmondBridge.rhp` (e.g. via Yak /
Food4Rhino). The full analysis behind each decision is in
`docs/licensing-audit.md`.

## 3D Warehouse models — NOT distributed

The furniture, context, drawing, and diagram model files that Almond's
manifests describe were downloaded from Trimble's
[3D Warehouse](https://3dwarehouse.sketchup.com). The 3D Warehouse Terms of
Use prohibit redistributing downloaded models as stand-alone items or
aggregating them for redistribution, so **no downloaded 3D Warehouse model file is included in any
distribution artifact** (PyPI wheel, sdist, Yak package, or git repository).

What Almond distributes instead is its own factual metadata: manifests
recording each model's title, publisher, source URL, catalogue dimensions,
sha256 checksum, and Almond's original spatial contract (anchor, footprint,
clearances, collision shape). Each user downloads the model files from the
recorded source pages themselves; `almond-mcp fetch-assets` lists what is
missing and verifies checksums after download.

## Generated asset library — distributed (CC BY 4.0)

The models in `GeneratedAssetfiles/models/` (people, trees, vehicles, site
furniture, columns, balustrades, sanitary fixtures, generic
furniture) were generated with [Meshy](https://www.meshy.ai) from prompts
written for this project and normalised by `tools/build_generated_assets.py`.
Output generated on a paid Meshy plan belongs to the generating account, and
these files are released under the
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)
license. Attribute as "Almond generated asset library
(github.com/liangjunglj-cpu/almond-mcp)". The accompanying manifest,
`.almond.json` contracts and tooling are MIT-licensed with the rest of the
project. No 3D Warehouse content was used to produce them.

## IKEA trademarks

IKEA product and series names (BILLY, KALLAX, KLIPPAN, …) appear in the
furniture manifest solely to factually identify the real products whose
published catalogue dimensions the manifest records. almond-mcp is an
independent project. It is not affiliated with, endorsed by, or sponsored by
Inter IKEA Systems B.V., and no IKEA model files, imagery, or catalogue
content are distributed.

## Karamba3D — NOT distributed

[Karamba3D](https://karamba3d.com) is commercial structural-analysis software
by Karamba3D GmbH. Nothing from Karamba3D is distributed: no assemblies, no
example definitions. The bridge's `KarambaAdapter` binds to a user-installed
Karamba3D 3.1 at runtime via reflection, and the `karamba_*.capsule.json`
manifests are original, self-authored input/output contracts for definitions
the user supplies. The Karamba3D and Kangaroo example `.ghx` files used
during development remain a local research library and are excluded from
every distribution artifact.

## Kangaroo examples — NOT distributed

Kangaroo example definitions by Daniel Piker were used locally as a physics
reference library. They carry no redistribution license and are excluded
from every distribution artifact.

## Rhino / Grasshopper SDK

RhinoCommon and the Grasshopper SDK are used under McNeel's developer terms;
RhinoCommon is MIT-licensed. McNeel assemblies are referenced, never
redistributed.

## Bridge runtime dependencies (distributed with the Yak package)

The compiled `RhinoAlmondBridge` plugin ships with these MIT-licensed
assemblies, restored from NuGet at build time:

- **Newtonsoft.Json** — Copyright (c) 2007 James Newton-King, MIT License.
- **Microsoft.CodeAnalysis (Roslyn)** and supporting **System.\*** packages —
  Copyright (c) .NET Foundation and Contributors, MIT License.

The MIT license text for these packages:

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
```

## Python dependencies — installed, not vendored

`fastmcp`, `mcp`, `pydantic`, and `lxml` are declared dependencies installed
by the user's package manager from PyPI; they are not vendored into any
almond-mcp artifact.
# Drafting runtime dependencies (0.6.0rc2)

The optional use of architectural reference directories does not bundle their
drawings. The drawing pilot is derived from Almond's generated CC BY 4.0 model
pack and retains source attribution in every SVG and package manifest.

Drafting uses NumPy (BSD-3-Clause), Shapely (BSD-3-Clause; its binary distributions
also carry GEOS licensing notices) and ezdxf (MIT). These are installed as
dependencies with their own notices; they are not relicensed as Almond code.

Dense mesh drafting also uses Pillow (MIT-CMU) and ContourPy (BSD-3-Clause),
installed with their own licence notices, to convert bounded projection masks
into explicit vector contours.

## Environmental analysis

The environmental engine (`almond_mcp/environment`) is original code implementing published methods
and standards (Perez sky and luminous-efficacy models, NOAA solar position, ISO 7730, ISO 13790,
ASHRAE 55, EN 16798-1, IES LM-83, EN 17037, CIBSE TM52). No ClimateStudio, Radiance, DAYSIM or
EnergyPlus code or binaries are included or required. The optional `fast` extra installs numba
(BSD-2-Clause) and llvmlite (BSD-2-Clause) from PyPI; they are not vendored. The false-colour ramps
are sampled stops of matplotlib's viridis / magma colour maps, whose data is CC0.

### Construction and code-pack data (`almond_mcp/environment/data/`)

Every bundled value records its source in `data/sources.json`; licence texts are in `data/LICENSES/`.

- **Material thermal properties and glass optics**: from the EnergyPlus `datasets/` folder
  (`ASHRAE_2005_HOF_Materials.idf`, `WindowGlassMaterials.idf`, EnergyPlus v26.2.0). EnergyPlus,
  Copyright (c) 1996-present, The Board of Trustees of the University of Illinois, The Regents of the
  University of California through Lawrence Berkeley National Laboratory, Oak Ridge National Laboratory
  (UT-Battelle), Alliance for Energy Innovation, LLC, and other contributors. All rights reserved.
  Redistributed under the EnergyPlus licence (BSD-style; `data/LICENSES/EnergyPlus.txt`). Almond is not
  EnergyPlus and is not endorsed by its developers.
- **Generic reflectances** (floor 0.20, wall 0.50, ceiling 0.80): honeybee-standards v2.0.7, MIT
  License, Copyright (c) 2020 Ladybug Tools (`data/LICENSES/honeybee-standards.txt`).
- **German flat-rate U-values by construction age**: Bekanntmachung der Regeln zur Datenaufnahme und
  Datenverwendung im Wohngebaeudebestand, BAnz AT 04.12.2020 B1 - an official work, free of copyright
  under Section 5 UrhG.
- **EU building-stock U-values**: Hotmaps building-stock dataset (gitlab.com/hotmaps/building-stock,
  CC BY 4.0), residential part based on the IEE TABULA project (www.episcope.eu); reduced to element
  averages by Almond.
- **England limiting and notional U-values**: Approved Document L, 2021 edition incorporating 2023
  amendments. Contains public sector information licensed under the Open Government Licence v3.0.
- **Singapore ETTV / RETV / RTTV**: the formulas of the BCA Code on Envelope Thermal Performance for
  Buildings are implemented (a method, cited); none of the Code's tables are reproduced - solar
  correction factors are derived from the user's weather file and shading from the model. Results are
  indicative and are not a BCA Green Mark assessment.
- **Assembly build-ups, finishes' reflectance and absorptance, window frames and room-use profiles** are
  Almond's own assumptions (MIT), labelled `almond-own`.

Not bundled (licence does not allow it in a commercial product): EN ISO 10456 / 6946 and Eurocode tables,
Singapore Standards (SS 530/531/553/554), BCA code tables, the Aalborg 2021 materials table (CC BY-SA;
not bundled), honeybee-energy-standards (AGPL-3.0), bauteilkatalog.ch, IGDB
records (CC BY-ND).

## Browser model viewer

The local Object Archive vendors `@google/model-viewer` 4.3.1 from the official
npm registry (https://www.npmjs.com/package/@google/model-viewer), under Apache
License 2.0. Its original licence and package integrity record are included in
`almond_mcp/library_ui/vendor/`. The distribution bundle retains embedded
third-party notices. Full component licence texts and their retrieval records
are also included in `THIRD-PARTY-LICENSES.txt` and `version.json` there.
