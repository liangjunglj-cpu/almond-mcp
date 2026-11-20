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
