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
aggregating them for redistribution, so **no model file is included in any
distribution artifact** (PyPI wheel, sdist, Yak package, or git repository).

What Almond distributes instead is its own factual metadata: manifests
recording each model's title, publisher, source URL, catalogue dimensions,
sha256 checksum, and Almond's original spatial contract (anchor, footprint,
clearances, collision shape). Each user downloads the model files from the
recorded source pages themselves; `almond-mcp fetch-assets` lists what is
missing and verifies checksums after download.

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
