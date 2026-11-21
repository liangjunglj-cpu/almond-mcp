# Scene metadata audit pilot

This development feature applies the stale-quantity review pattern studied in
[HdM BIMlight](https://github.com/herzogdemeuron/BIMlight). The implementation is
original Almond code; no HdM implementation code has been copied.

Use the matching development server and bridge. The public 0.7.0rc2 bridge does
not expose the new endpoints; older bridges return an explicit error. This pilot
does not change installed packages, the package version or client configuration.

1. Call `capture_scene_metadata_snapshot(name, guids)` with 1-500 explicit object
   GUIDs. Keep the returned `snapshot_id`. This writes a new immutable record in
   the local Almond state database and does not alter Rhino.
2. Edit the model normally, then call `audit_scene_metadata(snapshot_id)`.
   The result reports changed/missing objects and reasons, with full counts even
   when details are truncated. Auditing never updates the baseline or repairs
   metadata. New objects outside the selected IDs are outside the audit scope.
3. Call `show_scene_metadata_issues(snapshot_id)` to display temporary boxes and
   reason labels. Deleted objects are marked at their old position. Clear them
   with `show_scene_metadata_issues(clear=True)`. Appearance, selection and geometry
   are preserved. Capture a new named baseline only when deliberately accepting
   the revised state.

## What it compares

- Existence (including hidden and locked objects), geometry type and world bounds.
- All `almond:*` and `Almond.*` object user text, including section, asset,
  construction and material records. Added, removed and changed keys are explicit.
- Curve length and Brep surface area / closed-solid volume. Unsupported quantities
  are not invented. Block quantities are not aggregated in this pilot.
- Block instance transforms separately from the definition geometry checksum.
  Nested definitions are traversed, with a depth/size guard. Every selected block
  instance is audited independently. Definition-member attributes and document
  material definitions are outside this pilot; it compares top-level object user text.
- Native Rhino `GeometryBase.DataCRC` as a change detector. It is not a
  cryptographic geometry identity, an engineering check or proof metadata is true.
  Ordinary movements/extents already explain corresponding coordinate CRC changes.

Measurements are normalised to mm, mm2 and mm3. Default length tolerance is
0.1 mm plus a relative tolerance of 1e-6; area/volume absolute tolerances are
1 mm2 / 1 mm3. Relative position tolerance follows object size, not distance from
the world origin. Unit conversions therefore do not imply movement by themselves.
Because native CRCs depend on geometry units, cross-unit audits skip CRC and block
linear-transform comparisons and report limited coverage rather than claiming a
fully clean audit. Bounds, quantities and metadata remain compared physically.

An inventory must account for every requested ID exactly once. Invalid, partial,
unsupported-unit or different-document replies cannot produce a clean/deleted
verdict. A saved file is identified by its full path; an unsaved document uses
Rhino process/document runtime identity. Save As, saving a previously blank file,
or reopening an unsaved document requires a deliberate new baseline. The tool
does not stamp document IDs or write hidden user text to circumvent this boundary.

## Validation

Run the scene audit and tool tests, retrieval-store regressions and bridge-client
tests in an isolated state directory; build the bridge against the pinned Rhino
8.0 GA SDK. The live development smoke should exercise unchanged, moved, scaled,
deleted, section-edited and block-definition-edited objects, physical unit
conversion, overlay clear and unchanged persistent attributes. Keep the production
bridge installed while testing the compiled inventory helper separately, and
distinguish helper validation from deployment of the new protocol endpoints.
