"""Stage Ginkgo-generated meshes as a captured Almond batch, from the tool calls that generated them.

    python tools/stage_ginkgo_chains.py GeneratedAssetfiles/batches/<batch>.json \
        --ginkgo C:/Users/liang/OneDrive/Documents/Builiding0/Ginkgo --chain chain-<batch>.json

Generalises tools/stage_ginkgo_batch.py (refset_1024) to the other generation routes Ginkgo has used:

  image stage  meshy_text_to_image, meshy_image_to_image (owner photographs as input) or Higgsfield
               generate_image_batch
  mesh stage   meshy_image_to_3d (linked by input_task_id, or by uploading the image file) or Higgsfield
               generate_3d with Tripo (linked by passing the image job ID as a media reference)

The chain file holds, per Ginkgo prop name, the requests the Ginkgo session actually submitted, the IDs its
results returned and where the downloaded files were saved (Ginkgo-relative). This tool checks every ID
against the batch, checks the link between the image and mesh stages, and refuses an uploaded image that was
modified after its upload. It then copies the untouched provider files into GeneratedAssetfiles/raw/<batch>/:

  <asset_id>.png         the image the mesh stage received (hashed)
  <asset_id>.glb         the dense provider download (hashed)
  <asset_id>.image.json  the exact image request, ID, status evidence and output hash
  <asset_id>.mesh.json   the exact mesh request, ID, input-image and output hashes

Owner photographs used as image-to-image inputs are hashed and named, never copied. Account-scoped result
URLs and local absolute paths are not copied. Nothing is generated or re-downloaded.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
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
    else:
        ok = False
    if not ok:
        raise SystemExit(f'{aid}: mesh request does not reference the recorded image ({mesh["link"]})')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--ginkgo', type=Path, required=True)
    parser.add_argument('--chain', type=Path, required=True, help='Records extracted from the Ginkgo session tool calls')
    args = parser.parse_args()
    batch = json.loads(args.batch.read_text(encoding='utf-8'))
    chain = json.loads(args.chain.read_text(encoding='utf-8'))
    raw = REPO / 'GeneratedAssetfiles/raw' / batch['batch_id']
    raw.mkdir(parents=True, exist_ok=True)
    extracted = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for asset in batch['assets']:
        aid, prop = asset['asset_id'], asset['ginkgo_name']
        record = chain.get(prop) or {}
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
        shutil.copyfile(png, raw / f'{aid}.png')
        shutil.copyfile(glb, raw / f'{aid}.glb')
        image_sha, mesh_sha = sha256(raw / f'{aid}.png'), sha256(raw / f'{aid}.glb')
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
                        'output_file': f'{aid}.png', 'output_sha256': image_sha,
                        'output_file_modified_at': modified(png).isoformat(timespec='seconds'),
                        'seed': None, 'evidence_source': evidence_source}
        if image.get('download'):
            image_record['status_basis'] = 'Provider reported completed; ' + image['download']
        mesh_record = {'asset_id': aid, **{k: v for k, v in mesh.items() if k not in DROP},
                       'input_link': mesh['link'], 'input_image_sha256': image_sha,
                       'output_file': f'{aid}.glb', 'output_sha256': mesh_sha,
                       'seed': None, 'evidence_source': evidence_source}
        for suffix, value in (('image', image_record), ('mesh', mesh_record)):
            (raw / f'{aid}.{suffix}.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        print(aid, prop, image['task_id'], mesh['task_id'], image_sha[:12], mesh_sha[:12])


if __name__ == '__main__':
    main()
