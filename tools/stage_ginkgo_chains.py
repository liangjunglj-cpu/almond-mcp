"""Stage Ginkgo-generated meshes as a captured Almond batch, from the tool calls that generated them.

    python tools/stage_ginkgo_chains.py GeneratedAssetfiles/batches/<batch>.json \
        --ginkgo C:/Users/liang/OneDrive/Documents/Builiding0/Ginkgo --chain chain-<batch>.json

Generalises tools/stage_ginkgo_batch.py (refset_1024) to the other generation routes Ginkgo has used:

  image stage  meshy_text_to_image, meshy_image_to_image (owner photographs as input) or Higgsfield
               generate_image / generate_image_batch (optionally with owner photographs as media references)
  mesh stage   meshy_image_to_3d (linked by input_task_id, or by uploading the image file) or Higgsfield
               generate_3d with Tripo (linked by passing the image job ID as a media reference, or by uploading a
               locally edited copy of the generated image: link 'uploaded_derivative', which retains both images
               as <asset_id>.image-output.png and <asset_id>.png and records the edit)

A chain record with "route": "meshy_text_to_3d" has no image stage: Meshy text-to-3D preview (the prompt) and
refine (linked by preview_task_id). No input image exists or is retained; the tool writes <asset_id>.preview.json
and <asset_id>.mesh.json and copies the refine download, which may be a GLB or an OBJ (Meshy's OBJ download; its
texture maps are not copied, the library assigns Almond materials). The batch asset then carries preview_task_id
instead of image_job_id.

The chain file holds, per Ginkgo prop name, the requests the Ginkgo session actually submitted, the IDs its
results returned and where the downloaded files were saved (Ginkgo-relative). This tool checks every ID
against the batch, checks the link between the image and mesh stages, and refuses an uploaded image that was
modified after its upload. It then copies the untouched provider files into GeneratedAssetfiles/raw/<batch>/:

  <asset_id>.png         the image the mesh stage received (hashed)
  <asset_id>.glb         the dense provider download (hashed)
  <asset_id>.image.json  the exact image request, ID, status evidence and output hash
  <asset_id>.mesh.json   the exact mesh request, ID, input-image and output hashes

A batch with "route": "procedural_script" has no provider at all: a Blender script in the owner's project built the
pieces and exported one FBX each (Project Y2K kits). It needs no --chain (pass the project root as --ginkgo). The
tool checks the script, the kit record and every FBX against the hashes in the batch, refuses an FBX older than a
later edit of its script (unless the batch records that edit and that it leaves the piece alone), retains the
script as text (local absolute paths redacted, see redact_local_paths) and the kit record under raw/<batch>/evidence/,
and writes <asset_id>.fbx, <asset_id>.mesh.json and raw/<batch>/procedural.json.

Other recorded fields pass through unchanged, e.g. an image record's concept_reference (a session-generated concept
image given to the image request by job ID: named and hashed, not copied). A refine request that names no ai_model
keeps that gap in the mesh record's provider_model.
Owner photographs used as image-to-image inputs are hashed and named, never copied. Account-scoped result
URLs and local absolute paths are not copied. Nothing is generated or re-downloaded.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

REPO = Path(__file__).resolve().parents[1]
DROP = ('file', 'reference_inputs', 'session', 'link', 'downloaded_at', 'download')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace('Z', '+00:00'))


def modified(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def check_link(aid: str, image: dict, mesh: dict, image_file: Path):
    request = mesh['request']
    if mesh['link'] == 'input_task_id':
        ok = request.get('input_task_id') == image['task_id']
    elif mesh['link'] == 'media_job_id':
        ok = [m.get('value') for m in request.get('medias', [])] == [image['task_id']]
    elif mesh['link'] == 'upload':
        ok = 'input_task_id' not in request and request.get('image') == 'local upload of ' + image_file.name
        if modified(image_file) > when(mesh['submitted_at']):
            raise SystemExit(f'{aid}: reference image changed after it was uploaded for the mesh stage')
    elif mesh['link'] == 'uploaded_derivative':
        # The session edited the generated image (e.g. cropped out a stray duplicate) and uploaded that file as
        # media for the mesh stage. The derivative is retained and hashed; the edit is described in the record.
        upload = mesh['uploaded_input']
        ok = ([m.get('value') for m in request.get('medias', [])] == [upload['media_id']]
              and bool(upload.get('operation')))
        if modified(image_file.parent / Path(upload['file']).name) > when(upload['uploaded_at']):
            raise SystemExit(f'{aid}: uploaded derivative changed after it was uploaded for the mesh stage')
    else:
        ok = False
    if not ok:
        raise SystemExit(f'{aid}: mesh request does not reference the recorded image ({mesh["link"]})')


def stage_text_to_3d(args, batch, raw, extracted, asset, record):
    """Meshy text-to-3D: preview task (prompt) -> refine task (preview_task_id); no image stage."""
    aid, prop = asset['asset_id'], asset['ginkgo_name']
    preview, mesh = record.get('preview'), record.get('mesh')
    if not preview or not mesh or 'image' in record or preview['status'] != 'SUCCEEDED' or mesh['status'] != 'SUCCEEDED':
        raise SystemExit(f'{aid}: incomplete text-to-3D record for {prop}')
    if (preview['task_id'], mesh['task_id']) != (asset['preview_task_id'], asset['mesh_task_id']) or 'image_job_id' in asset:
        raise SystemExit(f'{aid}: task IDs disagree between session records and batch')
    if preview['tool'] != 'meshy_text_to_3d' or mesh['tool'] != 'meshy_text_to_3d_refine':
        raise SystemExit(f'{aid}: not a Meshy text-to-3D preview and refine')
    if preview['request']['prompt'] != asset['prompt']:
        raise SystemExit(f'{aid}: batch prompt differs from the submitted preview request')
    if mesh['link'] != 'preview_task_id' or mesh['request'].get('preview_task_id') != preview['task_id']:
        raise SystemExit(f'{aid}: refine request does not name the recorded preview task')
    source = args.ginkgo / mesh['file']
    suffix = source.suffix.lower()
    if suffix not in ('.glb', '.obj'):
        raise SystemExit(f'{aid}: unsupported refine download {source.name}')
    if modified(source) > when(mesh['downloaded_at']):
        raise SystemExit(f'{aid}: {source.name} changed after the session downloaded it')
    reported = (mesh.get('download') or {}).get('reported_file_size_bytes')
    if reported is not None and reported != source.stat().st_size:
        raise SystemExit(f'{aid}: {source.name} size differs from the size meshy_download_model reported')
    output = f'{aid}{suffix}'
    shutil.copyfile(source, raw / output)
    mesh_sha = sha256(raw / output)
    evidence_source = {'pass_records': batch['origin']['pass_records'],
                       'session_records': f"Tool calls of Ginkgo Claude Code session {preview['session']}"
                       ' (submissions, results and downloads)',
                       'extracted_at': extracted}
    preview_record = {'asset_id': aid, **{k: v for k, v in preview.items() if k not in DROP},
                      'seed': None, 'evidence_source': evidence_source}
    mesh_record = {'asset_id': aid, **{k: v for k, v in mesh.items() if k not in DROP},
                   'input_link': 'preview_task_id', 'output_file': output, 'output_format': suffix[1:],
                   'output_sha256': mesh_sha, 'output_file_modified_at': modified(source).isoformat(timespec='seconds'),
                   'seed': None, 'evidence_source': evidence_source}
    if mesh.get('download'):
        mesh_record['download'] = mesh['download']
    for name, value in (('preview', preview_record), ('mesh', mesh_record)):
        (raw / f'{aid}.{name}.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print(aid, prop, preview['task_id'], mesh['task_id'], suffix, mesh_sha[:12])


# A local absolute path under a user profile: backslashes (also JSON-escaped, doubled) or forward slashes.
LOCAL_PATH = re.compile(r'[A-Za-z]:[\\/]+Users[\\/][^"\'\n]*')


def redact_local_paths(text: str, replacement: str, anchor: str | None = None) -> str:
    """Replace each local absolute path with *replacement*; with an *anchor* folder name (e.g. the project folder),
    the part of the path after that folder is kept, so project-relative locations stay readable."""
    def sub(match):
        path = match.group(0)
        parts = re.split(r'([\\/]+)', path)
        if anchor and anchor in parts:
            return replacement + ''.join(parts[parts.index(anchor) + 1:])
        return replacement
    return LOCAL_PATH.sub(sub, text)


SECRET = re.compile(r'(api[_-]?key|secret|password|bearer\s|token\s*=|sk-[A-Za-z0-9]{16})', re.IGNORECASE)


def stage_procedural(args, batch, raw, extracted):
    """Route 'procedural_script': geometry a Blender script in the owner's project built and exported as FBX.

    No provider, no image, no task IDs. The evidence is the generator script (hash-checked, retained as text with any
    local absolute path redacted), the kit record the script wrote beside its FBX files (hash-checked, retained) and
    each FBX (hash-checked, copied to raw/). An FBX older than its script's last edit is refused unless the batch
    records that post-export edit and shows it does not touch that piece."""
    evidence = raw / 'evidence'
    evidence.mkdir(exist_ok=True)
    staged = {'scripts': {}, 'kit_records': {}}
    for group in ('scripts', 'kit_records'):
        for path, entry in batch['generator'][group].items():
            source = args.ginkgo / path
            if sha256(source) != entry['sha256']:
                raise SystemExit(f'{path}: changed since the batch recorded it')
            text = source.read_text(encoding='utf-8')
            lines = [n for n, line in enumerate(text.splitlines(), 1) if LOCAL_PATH.search(line)]
            if lines and not entry.get('redact_local_paths'):
                raise SystemExit(f'{path}: local absolute paths on lines {lines}; record a redaction')
            if lines:
                text = redact_local_paths(text, entry['redact_local_paths'], entry.get('redaction_anchor'))
            if SECRET.search(text):
                raise SystemExit(f'{path}: possible credential; review before retaining it')
            (evidence / entry['retained_as']).write_bytes(text.encode('utf-8'))
            retained = sha256(evidence / entry['retained_as'])
            if retained != entry['retained_sha256']:
                raise SystemExit(f'{path}: retained copy hash {retained} differs from the batch record')
            staged[group][path] = {**entry, 'modified_at': modified(source).isoformat(timespec='seconds'),
                                   'redacted_lines': lines}
    (raw / 'procedural.json').write_text(json.dumps(staged, indent=2) + '\n', encoding='utf-8')
    for asset in batch['assets']:
        aid = asset['asset_id']
        script = batch['generator']['scripts'][asset['generator_script']]
        fbx = args.ginkgo / asset['source_file']
        if fbx.suffix.lower() != '.fbx' or sha256(fbx) != asset['source_sha256']:
            raise SystemExit(f'{aid}: {fbx.name} missing or changed since the batch recorded it')
        if modified(args.ginkgo / asset['generator_script']) > modified(fbx):
            edit = script.get('post_export_edit') or {}
            if asset['source_name'] in edit.get('affected_variants', [asset['source_name']]):
                raise SystemExit(f'{aid}: the script was edited after {fbx.name} was exported')
        shutil.copyfile(fbx, raw / f'{aid}.fbx')
        record = {'asset_id': aid, 'tool': 'blender_procedural_script', 'source_name': asset['source_name'],
                  'source_file': asset['source_file'], 'generator_script': asset['generator_script'],
                  'generator_script_sha256': script['sha256'], 'kit_record': asset['kit_record'],
                  'kit_entry': asset['kit_entry'], 'output_file': f'{aid}.fbx', 'output_format': 'fbx',
                  'output_sha256': sha256(raw / f'{aid}.fbx'),
                  'output_file_modified_at': modified(fbx).isoformat(timespec='seconds'),
                  'evidence_source': {'project_files': [asset['generator_script'], asset['kit_record'],
                                                        asset['source_file']],
                                      'authoring': script['authoring'], 'extracted_at': extracted}}
        (raw / f'{aid}.mesh.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        print(aid, asset['source_name'], record['output_sha256'][:12])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--ginkgo', type=Path, required=True,
                        help='Project root the batch paths resolve against (Ginkgo, or Project Y2K)')
    parser.add_argument('--chain', type=Path, help='Records extracted from the Ginkgo session tool calls '
                        '(not used by route procedural_script, whose evidence is project files)')
    args = parser.parse_args()
    batch = json.loads(args.batch.read_text(encoding='utf-8'))
    raw = REPO / 'GeneratedAssetfiles/raw' / batch['batch_id']
    raw.mkdir(parents=True, exist_ok=True)
    extracted = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if batch.get('route') == 'procedural_script':
        stage_procedural(args, batch, raw, extracted)
        return
    if args.chain is None:
        parser.error('--chain is required for provider-generated batches')
    chain = json.loads(args.chain.read_text(encoding='utf-8'))
    for asset in batch['assets']:
        aid, prop = asset['asset_id'], asset['ginkgo_name']
        record = chain.get(prop) or {}
        if record.get('route', batch.get('route')) == 'meshy_text_to_3d':
            if batch.get('route') != 'meshy_text_to_3d' or record.get('route') != 'meshy_text_to_3d':
                raise SystemExit(f'{aid}: chain and batch disagree on the generation route')
            stage_text_to_3d(args, batch, raw, extracted, asset, record)
            continue
        image, mesh = record.get('image'), record.get('mesh')
        if not image or not mesh or image['status'] not in ('SUCCEEDED', 'COMPLETED') \
                or mesh['status'] not in ('SUCCEEDED', 'COMPLETED'):
            raise SystemExit(f'{aid}: incomplete generation record for {prop}')
        if (image['task_id'], mesh['task_id']) != (asset['image_job_id'], asset['mesh_task_id']):
            raise SystemExit(f'{aid}: task IDs disagree between session records and batch')
        if image['request']['prompt'] != asset['prompt']:
            raise SystemExit(f'{aid}: batch prompt differs from the submitted image request')
        png, glb = args.ginkgo / image['file'], args.ginkgo / mesh['file']
        check_link(aid, image, mesh, png)
        for path, stage in ((png, image), (glb, mesh)):
            saved = stage.get('downloaded_at') or stage.get('completed_observed_at')
            if stage['provider'] == 'meshy' and saved and modified(path) > when(saved):
                raise SystemExit(f'{aid}: {path.name} changed after the session downloaded it')
        derivative = mesh['link'] == 'uploaded_derivative'
        image_output = f'{aid}.image-output.png' if derivative else f'{aid}.png'
        shutil.copyfile(png, raw / image_output)
        if derivative:
            shutil.copyfile(args.ginkgo / mesh['uploaded_input']['file'], raw / f'{aid}.png')
        shutil.copyfile(glb, raw / f'{aid}.glb')
        image_sha, mesh_sha = sha256(raw / image_output), sha256(raw / f'{aid}.glb')
        input_sha = sha256(raw / f'{aid}.png')
        sessions = sorted({image['session'], mesh['session']})
        evidence_source = {'pass_records': batch['origin']['pass_records'],
                           'session_records': 'Tool calls of Ginkgo Claude Code session(s) ' + ', '.join(sessions)
                           + ' (submissions, results and downloads)',
                           'extracted_at': extracted}
        references = [{'name': Path(r['file']).name, 'role': r['role'], 'sha256': sha256(args.ginkgo / r['file']),
                       'retained': False, 'note': 'Owner photograph uploaded to the image stage; not distributed'}
                      for r in image.get('reference_inputs', [])]
        image_record = {'asset_id': aid, **{k: v for k, v in image.items() if k not in DROP},
                        'reference_inputs': references,
                        'output_file': image_output, 'output_sha256': image_sha,
                        'output_file_modified_at': modified(png).isoformat(timespec='seconds'),
                        'seed': None, 'evidence_source': evidence_source}
        if image.get('download'):
            image_record['status_basis'] = 'Provider reported completed; ' + image['download']
        mesh_record = {'asset_id': aid, **{k: v for k, v in mesh.items() if k not in DROP + ('uploaded_input',)},
                       'input_link': mesh['link'], 'input_image_sha256': input_sha,
                       'output_file': f'{aid}.glb', 'output_sha256': mesh_sha,
                       'seed': None, 'evidence_source': evidence_source}
        if derivative:
            upload = mesh['uploaded_input']
            mesh_record['uploaded_input'] = {'file': f'{aid}.png', 'sha256': input_sha, 'derived_from_sha256': image_sha,
                                             'media_id': upload['media_id'], 'uploaded_at': upload['uploaded_at'],
                                             'operation': upload['operation']}
        for suffix, value in (('image', image_record), ('mesh', mesh_record)):
            (raw / f'{aid}.{suffix}.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        print(aid, prop, image['task_id'], mesh['task_id'], image_sha[:12], mesh_sha[:12])


if __name__ == '__main__':
    main()
