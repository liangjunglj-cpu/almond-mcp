"""Import reviewed batch derivatives (organic Meshy batches, or external image + Meshy batches such as
Ginkgo props) with exact, sanitized request evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

from build_generated_assets import normalise, load_material_colours, REPO
from almond_mcp.asset_passport import enrich_asset


def write(path, value):
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def main():
    batch_file=Path(sys.argv[1]);batch=json.loads(batch_file.read_text())
    library=REPO/'GeneratedAssetfiles';raw=library/'raw'/batch['batch_id']
    evidence_dir=library/'batches'/batch['batch_id'];evidence_dir.mkdir(exist_ok=True)
    manifest=json.loads((library/'manifest.json').read_text())
    catalogue=json.loads((library/'catalogue.json').read_text())
    provenance=json.loads((library/'provenance.json').read_text())
    quality={r['asset_id']:r for r in json.loads((raw/'prepared/quality.json').read_text())}
    selected = [a for a in batch['assets'] if a['asset_id'] in batch['release_assets']]
    if {a['asset_id'] for a in selected} & {a['asset_id'] for a in manifest['assets']}:
        raise ValueError('Batch already imported; refusing replacement')
    for asset in selected:
        aid=asset['asset_id'];image=json.loads((raw/(aid+'.image.json')).read_text());mesh=json.loads((raw/(aid+'.mesh.json')).read_text())
        q=quality[aid];prepared=raw/'prepared'/(aid+'.glb')
        assert hashlib.sha256(prepared.read_bytes()).hexdigest()==q['prepared_sha256']
        assert hashlib.sha256((raw/(aid+'.glb')).read_bytes()).hexdigest()==mesh['output_sha256']==q['source_sha256']
        assert hashlib.sha256((raw/(aid+'.png')).read_bytes()).hexdigest()==image['output_sha256']
        if q['quality']['nonmanifold_edges_excluding_boundary']:
            raise ValueError('Review nonmanifold geometry before import: '+aid)
        shutil.copyfile(raw/(aid+'.png'),evidence_dir/(aid+'.png'))
        evidence={'batch_id':batch['batch_id'],'image':image,'mesh':mesh,'derivation':q,
                  'input_image_file':'batches/'+batch['batch_id']+'/'+aid+'.png',
                  'external_reference_status':batch['external_reference_status'],'external_reference_ids':[],
                  'dimension_basis':batch.get('dimension_basis','Authored nominal height for architectural studies; width and depth measured after uniform normalization. Not a physical survey.'),
                  'reference_review':asset.get('reference_review','Reference image visually reviewed for neutral architectural use.'),
                  'rights':batch.get('rights','Generated for the Almond library using the owner-configured Meshy account; public pack distribution authorized by owner. CC BY 4.0. API balance verified; subscription contract not independently audited.')}
        if 'origin' in batch:
            evidence['origin']={'project':batch['origin']['project'],'pass':batch['origin']['pass'],
                                'source_name':asset.get('ginkgo_name'),'records':batch['origin']['records']}
        write(evidence_dir/(aid+'.json'),evidence)
        variant=asset['variant']+'; '+batch['variant_suffix'] if 'variant_suffix' in batch else 'Organic form; detailed geometry edition'
        tags=(asset['tags']+['detailed','meshy',batch['batch_id']]) if 'tags' in asset else ['organic','detailed','meshy',batch['batch_id'],asset['product'].lower()]
        brief={'asset_id':aid,'category':asset['category'],'product':asset['product'],
               'variant':variant,
               'dimensions_mm':{'width':asset['width_hint_mm'],'depth':asset['depth_hint_mm'],'height':asset['height_mm']},
               'render_material_id':asset['material'],'prompt':asset['prompt'],
               'tags':tags,
               'drawing_roles':['interior_perspective','exterior_perspective','axonometric'],
               'geometry_mode':'3d_entourage','support_plane':asset.get('support_plane','floor'),
               'placement_priority':asset.get('placement_priority','accessory'),'lod':'high',
               'recipe_override':batch.get('recipe_override','captured_organic_batch')}
        if 'mount_height_mm' in asset:
            brief['mount_height_mm']=asset['mount_height_mm']
        if batch.get('image_provider','meshy')=='meshy':
            history={'image_provider':'meshy','image_task_id':image['task_id'],'image_model':image['request']['ai_model']}
        else:
            # External image stage (e.g. Higgsfield), uploaded to Meshy as a file: the link is the image hash.
            if mesh.get('input_image_sha256')!=image['output_sha256']:
                raise ValueError('Mesh input image differs from the retained reference image: '+aid)
            history={'image_provider':batch['image_provider'],'image_job_id':image['task_id'],'image_model':image['request']['model']}
        history.update({'mesh_provider':'meshy','mesh_task_id':mesh['task_id'],'mesh_model':mesh['request']['ai_model'],
                        'generated_at':mesh['submitted_at'][:10],'captured_generation':evidence})
        record=normalise(brief,prepared,library/'models',load_material_colours(),{aid:history})
        record['geometry_source']['parameters']['captured_generation']=evidence
        record['license_note']=evidence['rights']
        contract_path=library/record['contract_file'];contract=json.loads(contract_path.read_text())
        enrich_asset(record,contract,library/record['file'],contract_path)
        manifest['assets'].append(record);catalogue['assets'].append(brief);provenance['assets'][aid]=history
        print(aid,record['triangle_count'],record['dimensions_mm'])
    for filename,data in [('manifest.json',manifest),('catalogue.json',catalogue),('provenance.json',provenance)]:
        write(library/filename,data)


if __name__=='__main__':main()
