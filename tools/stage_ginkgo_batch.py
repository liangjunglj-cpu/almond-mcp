"""Stage Ginkgo-generated props as a captured Almond batch, from the records that ran them.

    python tools/stage_ginkgo_batch.py GeneratedAssetfiles/batches/ginkgo-refset-1024.json \
        --ginkgo C:/Users/liang/OneDrive/Documents/Builiding0/Ginkgo --chain chain.json

Ginkgo generated each prop as a Higgsfield reference image (generate_image_batch) followed
by a Meshy image-to-3D task that uploaded that image file. This tool takes the requests
recorded by the session that submitted those jobs, cross-checks every ID against the pass's jobs.json,
and copies the untouched provider files into GeneratedAssetfiles/raw/<batch_id>/:

  <asset_id>.png         the reference image Meshy received (hashed)
  <asset_id>.glb         the dense Meshy download (hashed)
  <asset_id>.image.json  the exact image request, job ID and output hash
  <asset_id>.mesh.json   the exact Meshy request, task ID, input-image and output hashes

Account-scoped result URLs, account identifiers and local absolute paths are not copied.
Nothing is generated or re-downloaded; a missing or contradictory record stops the run.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import ntpath
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def read_chain(path: Path) -> dict:
    """Generation records per Ginkgo prop name, as extracted from the Ginkgo session's tool calls.

    Expected per prop: image {submitted_at, request, context, job_id, status, model,
    completed_observed_at, result_filename} and mesh {submitted_at, request, task_id}.
    """
    chain = json.loads(path.read_text(encoding='utf-8'))
    props = {}
    for prop, record in chain.items():
        image, mesh = record.get('image', {}), record.get('mesh', {})
        request = {k: v for k, v in mesh.get('request', {}).items() if k not in ('file_path', 'response_format')}
        if 'file_path' in mesh.get('request', {}):
            request['image'] = 'local upload of ' + ntpath.basename(mesh['request']['file_path'])
        props[prop] = {
            'image': {'submitted_at': image.get('submitted_at'), 'request': image.get('request'),
                      'context': image.get('context'), 'task_id': image.get('job_id'),
                      'status': 'COMPLETED' if image.get('status') == 'completed' else image.get('status'),
                      'provider_model': image.get('model'), 'completed_observed_at': image.get('completed_observed_at'),
                      'provider_output_name': image.get('result_filename')} if image else None,
            'mesh': {'submitted_at': mesh['submitted_at'], 'request': request, 'task_id': mesh['task_id']} if mesh else None,
        }
    return props


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--ginkgo', type=Path, required=True)
    parser.add_argument('--chain', type=Path, required=True, help='Records extracted from the Ginkgo session tool calls')
    args = parser.parse_args()
    batch = json.loads(args.batch.read_text(encoding='utf-8'))
    meshy_dir = args.ginkgo / 'runs/refset_1024/meshy'
    jobs = json.loads((meshy_dir / 'jobs.json').read_text(encoding='utf-8'))
    chain = read_chain(args.chain)
    raw = REPO / 'GeneratedAssetfiles/raw' / batch['batch_id']
    raw.mkdir(parents=True, exist_ok=True)
    evidence_source = {'pass_records': 'Ginkgo runs/refset_1024/meshy/jobs.json',
                       'session_records': 'Tool calls of Ginkgo Claude Code session c849f85f-3384-47ae-bf45-2e1a471d157c (image and mesh submissions)',
                       'extracted_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    for asset in batch['assets']:
        aid, prop = asset['asset_id'], asset['ginkgo_name']
        record = chain.get(prop, {})
        image, mesh = record.get('image'), record.get('mesh')
        if not image or image.get('status') != 'COMPLETED' or not mesh:
            raise SystemExit(f'{aid}: incomplete generation record for {prop}')
        if (image['task_id'], mesh['task_id']) != (jobs['ref_' + prop], jobs['meshy_' + prop]) \
                or (image['task_id'], mesh['task_id']) != (asset['image_job_id'], asset['mesh_task_id']):
            raise SystemExit(f'{aid}: task IDs disagree between session records, jobs.json and batch')
        if image['request']['prompt'] != asset['prompt']:
            raise SystemExit(f'{aid}: batch prompt differs from the submitted image request')
        png, glb = meshy_dir / f'ref_{prop}.png', meshy_dir / f'{prop}_src.glb'
        modified = datetime.fromtimestamp(png.stat().st_mtime, timezone.utc)
        if modified > datetime.fromisoformat(mesh['submitted_at'].replace('Z', '+00:00')):
            raise SystemExit(f'{aid}: reference image changed after it was uploaded to Meshy')
        shutil.copyfile(png, raw / f'{aid}.png')
        shutil.copyfile(glb, raw / f'{aid}.glb')
        image_sha, mesh_sha = sha256(raw / f'{aid}.png'), sha256(raw / f'{aid}.glb')
        image_record = {'asset_id': aid, 'provider': 'higgsfield', 'tool': 'generate_image_batch',
                        'submitted_at': image['submitted_at'], 'request': image['request'],
                        'batch_context': image['context'], 'status': image['status'],
                        'task_id': image['task_id'], 'provider_model': image['provider_model'],
                        'completed_observed_at': image['completed_observed_at'],
                        'provider_output_name': image['provider_output_name'],
                        'output_file': f'{aid}.png', 'output_sha256': image_sha,
                        'output_file_modified_at': modified.isoformat(timespec='seconds'),
                        'seed': None, 'consumed_credits': 'about 0.25 (Ginkgo MESH_SOURCES.md)',
                        'evidence_source': evidence_source}
        mesh_record = {'asset_id': aid, 'provider': 'meshy', 'tool': 'meshy_image_to_3d',
                       'submitted_at': mesh['submitted_at'], 'request': mesh['request'],
                       'input_image_sha256': image_sha, 'status': 'SUCCEEDED',
                       'status_basis': 'Downloaded in the Ginkgo session with meshy_download_model; GLB present',
                       'task_id': mesh['task_id'], 'output_file': f'{aid}.glb', 'output_sha256': mesh_sha,
                       'seed': None, 'consumed_credits': 30, 'evidence_source': evidence_source}
        for suffix, value in (('image', image_record), ('mesh', mesh_record)):
            (raw / f'{aid}.{suffix}.json').write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        print(aid, prop, image['task_id'], mesh['task_id'], image_sha[:12], mesh_sha[:12])


if __name__ == '__main__':
    main()
