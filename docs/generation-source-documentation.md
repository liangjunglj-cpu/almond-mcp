# Source documentation for generated models and drawings

Adopted 19 September 2026 for the continuing Almond library work.

## Existing assets

Twenty assets record a Higgsfield image job followed by a Meshy mesh task. Their image IDs use `image_job_id`, not `image_task_id`. The register preserves both provider-specific identifiers; the remaining image-stage provider is inferred from the recorded catalogue tool and labelled accordingly.

`GeneratedAssetfiles/source-register.json` inventories the recorded evidence for each generated asset: Meshy task IDs, model labels, recorded prompt, generation date, transformations, output checksums and declared licence. The original `provenance.json`, catalogue, manifest and embedded passports remain the underlying evidence.

The register explicitly identifies incomplete historical evidence. A stored brief and shared recipe are not proof of the exact API request that ran. An image task ID is not a retained input image. An empty reference list means the external references were not recorded; it does not prove there were none. The audit compares local records and does not authenticate Meshy account rights.

Refresh and check it in the scratch development environment:

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'almond-060rc1-venv'
$env:UV_LINK_MODE = 'copy'
uv run python tools/document_generation_sources.py
uv run python tools/document_generation_sources.py --check
```

The register is included in future wheel/source builds. Previously built distributions must be rebuilt to include it. Do not edit the generated register directly: correct the underlying evidence, then regenerate it.

## Record before the next generation

For every selected article, drawing, photo, model or dataset, record:

- Stable source ID, title, author/designer, publisher, canonical URL and access date.
- For DETAIL: project/article title, architect, issue/date, page numbers and drawing/figure locator, wherever available. Use `unknown` for unavailable fields.
- Exact item revision or repository commit; local filename and SHA-256 if a permitted copy is retained. A repository homepage alone is insufficient attribution for a particular file.
- Access basis and terms/licence URL; separate decisions for consultation, generation-input upload, adaptation and redistribution. Reading access does not automatically permit uploading publisher images to Meshy or bundling them in Almond.
- How it was used: background reading, dimensional reference, assembly reference, direct generation input or adapted geometry. Name the relevant features, dimensions or materials and the affected output asset IDs.
- Verification status and unresolved assumptions. Preserve source measurements separately from dimensions measured on generated geometry.

For each generation run, retain the submitted prompt and settings, provider/model version, task IDs, timestamp, seed when exposed, input source IDs/file hashes and output hashes. Redact secrets, account identifiers, cookies and signed URL tokens. Keep permitted private source files outside the distributable asset pack. Record normalization, rotation, scaling, retopology and subsequent edits as derivation steps with parent/output hashes.

For custom Meshy imports, request the original generation record when available. Preserve supplied facts as user-supplied evidence; mark absent history unknown rather than inventing it. Record the import checksum and transformations even when earlier history is unavailable.

## Source selection is not generation attribution

The user accepted the recommended libraries as research candidates. The [research review](detail-library-research-2026-09.md) is the source directory. dataholz, Lignumdata, ARCAT, CADdetails, WikiHouse and LibreCAD are not retrospectively assigned to existing Meshy assets. DETAIL access is still unverified.

Before using an item, create its individual source record. Carry those IDs into the model's provenance, its sidecar and any drawing representation. A source added after generation must say `post_generation_reference`, including the attachment date; it must never be presented as an original input.

Recommended per-output fields:

```json
{
  "source_id": "project-source-001",
  "relationship": "assembly_reference",
  "used_for": ["wall layer sequence"],
  "locator": {"page": null, "figure": null},
  "evidence_status": "pending_source_review",
  "source_revision": null,
  "input_sha256": null,
  "generation_run_id": null,
  "rights": {
    "terms_url": null,
    "generation_input_upload": "unreviewed",
    "redistribution": "unreviewed"
  }
}
```

This is a documentation template, not a new validated passport schema. Complete the source record with the bibliographic fields above before use. A detail inspired by a source must not be labelled a certified copy or inherit the source assembly's performance ratings automatically.

## Release and drawing checks

Every distributed asset should resolve to its evidence record and output hash. Include public attribution and permitted metadata with the pack; retain restricted documents privately. A drawing sheet should identify its source/model revision, units, scale, and whether dimensions are generated, measured, declared or source-verified. Unknown rights or missing critical evidence must remain visible in review, not be converted into an assumed open licence.

The current automated check detects missing legacy generation fields, inconsistent task history, prompt disagreements and stale source-register content. New source relationships and item-level rights still require review and future schema validation. Run the source check whenever the generated catalogue changes and before building a release.

## Captured organic batch

The rc.12 organic batch retains exact image and mesh request bodies, linked task
IDs, timestamps and SHA-256 hashes in `captured_generation`. Generated reference
images are shipped with the public evidence; expiring provider URLs and account
credentials are excluded. The source checker verifies the prompt, task chain,
image bytes, source-mesh hash chain and packaged triangle count. Legacy assets
keep their historical gaps instead of inheriting this batch's stronger evidence.

`run_meshy_batch.py` records an intent before each paid POST and never retries an
uncertain submission automatically. Review generated images before submitting
the mesh stage. `prepare_organic_meshes.py` preserves dense originals and derives
library geometry with recorded checks; `import_organic_batch.py` links that
evidence to the catalogue and embedded passports.

## Ginkgo batch (external image stage)

`batches/ginkgo-refset-1024.json` imports sixteen props generated in the
owner's Ginkgo project (pass `runs/refset_1024`, 24 October 2026). Each chain
is a Higgsfield `gpt_image_2_5` reference image followed by a Meshy 7.1
image-to-3D task. Meshy received the image as a file upload, so there is no
`input_task_id` linking the two. The captured mesh record carries
`input_image_sha256` instead, and the source checker accepts that link only
when it equals the retained image's checksum.

`tools/stage_ginkgo_batch.py` builds the raw records from the requests that
the Ginkgo session actually submitted (prompts, settings, job and task IDs,
timestamps). It cross-checks every ID against Ginkgo's `jobs.json`, and it
refuses a reference image modified after its Meshy upload. It copies the
untouched provider files without regenerating anything. Account-scoped result
URLs and local paths are dropped. The provider file name is kept because it
carries the job timestamp.

The import keeps known gaps visible:

- Seeds were not returned.
- Meshy's own status record was not re-queried: the task IDs no longer resolve
  through the currently connected Meshy key. Success rests on the downloaded
  GLB.
- Image credits are Ginkgo's estimate.
- Heights are the sizes authored in the Ginkgo scene scripts, not surveys.


## Ginkgo batches with other generation routes (2026-11-18)

Three more batches import Ginkgo meshes with `tools/stage_ginkgo_chains.py`. It generalises
`stage_ginkgo_batch.py` to every route Ginkgo has used. The chain file holds, per prop, the
requests the Ginkgo session submitted, the IDs its results returned and where the downloads were
saved. The tool checks the IDs against the batch and the link between the two stages, then copies
the untouched files:

| Batch | Image stage | Mesh stage | Link between stages |
| --- | --- | --- | --- |
| `ginkgo-meshbank-2026-11` | Meshy text-to-image `nano-banana` | Meshy 7.1 | `input_task_id` |
| `ginkgo-freiburg-2026-11` | Meshy image-to-image from the owner's photograph crops | Meshy 7.1 | `input_task_id` (ornaments), uploaded file checksum (fountain) |
| `ginkgo-refset-1118` | Higgsfield `gpt_image_2_5` with a concept image as reference | Meshy 7.1, or Tripo H3.1 via Higgsfield `generate_3d` | uploaded file checksum (Meshy), image job ID as the only media reference (Tripo) |

The source checker accepts the Tripo link only when the request names the recorded image job as
its sole media reference and the retained image's checksum matches. Owner photographs given to
image-to-image appear in `reference_inputs` by name, role and SHA-256. They are not retained or
distributed. Every mesh record carries `input_link`, saying how the mesh stage received its image.

Known gaps, in addition to the refset_1024 ones:

- Where Meshy's status response was not recorded in the session, credits are the price-table
  figure and are labelled as such. The same applies to every image task.
- Tripo and Higgsfield images were downloaded with `curl` from the job's result URL. The
  evidence is the job result and the download command, not a provider checksum.
- Fountain and ornament sizes were measured from photographs in Ginkgo's reconstruction, not
  surveyed. Wall mount heights are the heights at which those scenes placed them.

## Project Y2K batches and the Meshy text-to-3D route (2026-11-20)

Three batches import props from the owner's Project Y2K game, all generated in Ginkgo sessions:
`y2k-props-v038` and `y2k-twofronts-2026-09` (Meshy text-to-3D) and `y2k-trees-refset-0923b`
(Higgsfield image, uploaded to Meshy-7, the existing `upload` link).

Text-to-3D has no image stage. Meshy takes the prompt in a **preview** task and textures it in a
**refine** task that names the preview by `preview_task_id`. A batch declares `"route":
"meshy_text_to_3d"`, and each asset carries `preview_task_id` instead of `image_job_id`. For that
route:

- `stage_ginkgo_chains.py` writes `<asset_id>.preview.json` and `<asset_id>.mesh.json` (the refine,
  `input_link: preview_task_id`), checks the refine names the recorded preview, refuses a download
  modified after the session saved it or whose size differs from what `meshy_download_model`
  reported, and copies the refine download. No image is retained, because none existed.
- `import_organic_batch.py` records `generation_route`, `preview_task_id` and `preview_model` in the
  manifest and provenance in place of `image_task_id` / `image_model`, and sets
  `captured_generation.input_image_file` to null.
- The source checker applies the text-to-3D requirements only when the recorded
  `generation_route` says so: it then requires the preview task and model, the prompt in the preview
  request, the refine-to-preview link and no input image, and rejects a record that names both a
  route and an image stage. Image-stage assets keep every earlier requirement.

The round 1/2 props were downloaded from Meshy as OBJ (Y-up, arbitrary units) with separate texture
maps. The OBJ is the hashed provider output (`output_format: obj`). `prepare_organic_meshes.py`
imports its geometry directly (Blender OBJ importer, Y-up to Z-up, -Z forward: the same axis change
as the glTF importer), drops the texture maps, decimates to the batch target and exports the library
GLB, so the derivation record links the OBJ hash to the prepared GLB hash in one step
(`source_format: obj`).

Known gaps, in addition to the earlier ones:

- Two v038 previews (box stack, ivy) were never queried in the session. Their success is inferred
  from the refine tasks that name them, and their credits are the price-table figure; both are
  labelled in `status_basis` / `consumed_credits`.
- The session that made the round 1/2 props records the Meshy balance but not the plan, so whether
  the account was on a paid plan on 2026-09-06 is unknown (see `docs/licensing-audit.md`).
- Sizes are the game's own placement or conditioning heights, not surveys.

## Ginkgo props reused in Project Y2K (four batches, 2026-11-20)

Thirteen Ginkgo props that Project Y2K content v061 conditioned for its Mirai Ward hub
(`twofronts/meshy/ginkgo_props_v061`), one batch per Ginkgo pass and route:

- `ginkgo-refset-1003` and `ginkgo-refset-0924`: Higgsfield `gpt_image_2_5` images from text
  prompts, curl-downloaded in the session and uploaded to Meshy-7 image-to-3D (`upload` link).
- `ginkgo-refset-1007`: a two-step image stage. Concept images were made from text prompts; each
  single-object reference image then took one concept image as its only media reference. The image
  record names that concept in `concept_reference` (job ID, file name, SHA-256, its own prompt;
  `retained: false`). The meshes are Tripo H3.1 through Higgsfield `generate_3d` (`media_job_id`
  link) or Meshy-7.1 image-to-3D (`upload` link).
- `ginkgo-lausanne-market`: Meshy-6 text-to-3D (the existing route). Its refine request named no
  `ai_model`; the chain records that in `provider_model` ("unspecified ... provider default"), and
  `import_organic_batch.py` now takes `mesh_model` from that field when the request has none,
  instead of failing or guessing a model.

Each batch's `origin.used_in_project_y2k` states where Y2K used the prop (v061 conditioned most of
them from Ginkgo's `*_near.glb` LODs of these downloads; the provider downloads are the hashed
sources here). Design proximity: the refset_1003 and refset_1007 prompts were written from owner
reference sets of third-party photographs that were pasted into the sessions and never uploaded to
a generator. Each generated image was compared with those photographs on 2026-11-20 and the
comparison is recorded in `reference_review`; three refset_1003 props (pack unit, cube rover,
lander) were excluded as close to specific third-party designs.

Known gaps:

- Three refset_1003 Meshy tasks were never status-queried in the session; their success rests on
  `meshy_download_model` returning the GLB, and their credits are not recorded.
- `runs/refset_1003/meshy/jobs.json` names the failed first rover task; the file on disk is the
  re-run's download. The rover is excluded anyway (design proximity).
- Vehicle sizes are Project Y2K's conditioning lengths; the other sizes are real-world choices made
  for this import (each batch's `dimension_basis`).

## Project Y2K procedural kit pieces and the procedural route (2026-11-20)

Four batches (`y2k-street-kit-v004`, `y2k-district-kit-v016`, `y2k-megastructure-kit-v020`,
`y2k-world-kit-v040`) import thirty pieces that Blender scripts in the owner's Project Y2K game
repository built and exported as FBX. No generation provider, prompt, image or task exists for them,
so they use a new route, keyed like text-to-3D: the batch declares `"route": "procedural_script"`
and the manifest and provenance record `generation_route: procedural_script`. For that route:

- The batch's `generator.scripts` holds, per script, the project-relative path, the SHA-256 and
  size of the project file, the retained copy's name and SHA-256, any redaction, helper
  dependencies (with their current hashes) and an `authoring` record: the Claude Code session(s)
  that wrote and edited the script and ran the export, from the session transcripts, or
  `"tool": "not found"` with the reason. `generator.kit_records` does the same for the kit record
  each script wrote beside its FBX files. Each asset names its `source_file` (FBX) and
  `source_sha256`, its `generator_script`, its `kit_record` entry (local paths dropped) and any
  recorded `edits`.
- `stage_ginkgo_chains.py` needs no chain file for this route. It checks every script, kit record
  and FBX against the batch hashes, refuses an FBX older than a later edit of its script unless the
  batch records that edit (`post_export_edit`, with the variants it touched) and the piece is not
  among them, refuses a likely credential, and retains the scripts and kit records as text under
  `raw/<batch>/evidence/`. Absolute local paths are redacted: the path up to the project folder is
  replaced (`redact_local_paths`, `redaction_anchor`), so the retained copy's hash differs from the
  project file's, and both are recorded.
- `prepare_organic_meshes.py` imports the FBX with Blender's FBX importer (file axes and
  `FBX_SCALE_UNITS` honoured, so pieces arrive at their authored metre size; custom normals not
  imported), removes engine collision hulls (`UCX_*`), applies the recorded edits and records each
  with the triangles it removed in `source_edits`. Edits are removals of cleanly separable parts
  only: `remove_thin_loose_parts` (loose parts no thicker than a stated size along an axis, used
  for tessellated lettering) and `remove_faces_by_material` (used for a decal quad). The target is
  the source triangle count, so nothing is decimated or subdivided; hard edges above 30 degrees are
  kept for the low-poly geometry.
- `import_organic_batch.py` copies the retained scripts and kit records to `batches/<batch>/`,
  writes `generation_route`, `generator_script`, `generator_script_sha256`, `source_file` and
  `source_sha256` in place of the provider keys (the prompt is null; there are no image or mesh
  task or model keys), sets the generator to `procedural_script` and the contract's `source_app`
  to `blender`.
- The source checker applies these requirements only when the recorded route says so: it requires
  the script and source hashes, checks that the retained script and kit record still hash to the
  recorded values, that the FBX hash links the mesh record, the derivation and the manifest, and
  rejects a procedural record that also names a prompt, an image stage or a provider task. A record
  without the route keeps every provider requirement (and a captured record with no image stage and
  no route is an error). `tools/verify_release.py` checks the retained files in the release
  evidence.

Known gaps:

- `build_street_kit.py` (street kit v004, 2026-09-11) predates every retained Project Y2K and
  Ginkgo transcript; who wrote it is recorded as not found.
- `kit_v040.py` and `kinetic_v046.py` import the owner's Ginkgo world-pack library (`gwlib.py`),
  which changed after these exports; its current hash is recorded, the version the export used is
  not retained. The export command for `MW_Shrine.fbx` was not pinned to a tool call (the session
  edits and the file times bracket it).
- `kinetic_v046.py` was edited a minute after the railcar export (two replacements inside the
  blimp builder, recorded in `post_export_edit`); the retained script is the edited file.
- The megastructure kit was designed with six owner-supplied third-party reference images in
  view; they are named and hashed (`external_reference_files`), not retained.
- The weld and degenerate cleanup drops a few triangles from four street and district pieces
  (24 to 64); the counts are the difference between `source_triangles`, the recorded removals and
  `quality.triangles`.
- Sizes are the authored kit sizes; wall mount heights are assumptions.
