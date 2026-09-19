"""Import preconverted Meshy assets with honest, incomplete historical evidence.

python tools/import_project_meshes.py PROJECT CONFIG CONVERTED_DIR
"""
import hashlib
import json
from pathlib import Path
import sys
from build_generated_assets import normalise, load_material_colours, read_glb, world_bounds, REPO
from almond_mcp.asset_passport import enrich_asset

def write(path, data):
    path.write_text(json.dumps(data,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')

def main():
    project, config_file, converted = map(Path,sys.argv[1:])
    config=json.loads(config_file.read_text(encoding='utf-8'))
    conversions={a['asset_id']:a for a in json.loads((converted/'conversion-record.json').read_text())}
    library=REPO/'GeneratedAssetfiles'
    manifest=json.loads((library/'manifest.json').read_text())
    catalogue=json.loads((library/'catalogue.json').read_text())
    provenance=json.loads((library/'provenance.json').read_text())
    source_documents=[{'path':p,'sha256':hashlib.sha256((project/p).read_bytes()).hexdigest()} for p in config['evidence']]
    ids={a['asset_id'] for a in config['assets']}
    if any(a['asset_id'] in ids for a in manifest['assets']): raise ValueError('Import IDs already exist; do not silently replace library models')
    for spec in config['assets']:
        aid=spec['asset_id']; raw=converted/(aid+'.glb'); conversion=conversions[aid]
        if hashlib.sha256(raw.read_bytes()).hexdigest()!=conversion['converted_sha256']: raise ValueError('Stale converted model')
        if hashlib.sha256((project/spec['source']).read_bytes()).hexdigest()!=conversion['source_sha256']: raise ValueError('Source model changed')
        g,b=read_glb(raw);lo,hi,tris=world_bounds(g,b);scale=spec['height_mm']/(hi[1]-lo[1])
        brief={'asset_id':aid,'category':spec['category'],'product':spec['product'],'variant':spec['variant'],
               'dimensions_mm':{'width':round((hi[0]-lo[0])*scale,1),'depth':round((hi[2]-lo[2])*scale,1),'height':spec['height_mm']},
               'render_material_id':spec['material'],'prompt':None,'tags':['ProjectY2K','Meshy','imported','concept',spec['product'].lower()],
               'drawing_roles':['exterior_perspective','axonometric','concept_layout'],'geometry_mode':'3d_entourage',
               'support_plane':'floor','placement_priority':'accessory','lod':'compact','intended_role':spec['role']}
        history={'evidence_type':'existing_project_import','image_task_id':None,'image_model':None,
                 'mesh_task_id':spec['task'],'mesh_model':'meshy-6 text-to-3d preview/refine; source remesh history partial',
                 'generated_at':config['generation_date']}
        record=normalise(brief,raw,library/'models',load_material_colours(),{aid:history})
        imported={'project':config['project'],'source_documents':source_documents,'conversion':conversion,
                  'task_id_status':spec['task_id_status'],'source_remesh_task_recorded':spec['remesh_task'],
                  'import_date':'2026-09-19','prompt_status':'unknown; original submitted prompt not retained in reviewed project records',
                  'image_stage':'not_applicable; text-to-3d generation',
                  'dimension_basis':'Height is an authored project placement value from twofronts/world/assets.json, not a verified physical measurement. Width/depth preserve source proportions.',
                  'rights':config['rights'],'intended_role':spec['role']}
        history['import_record']=imported
        record['geometry_source']['parameters'].update(evidence_type='existing_project_import',import_record=imported)
        record['series']='ALMOND-Y2K'
        record['warehouse_publisher']='ProjectY2K / Almond generated asset library'
        record['license_note']='Project owner authorized public CC BY 4.0 distribution on 2026-09-19; generating account entitlement not independently verified.'
        contract_path=library/record['contract_file'];contract=json.loads(contract_path.read_text())
        enrich_asset(record,contract,library/record['file'],contract_path)
        manifest['assets'].append(record);catalogue['assets'].append(brief);provenance['assets'][aid]=history
        print(aid,record['triangle_count'],record['dimensions_mm'])
    manifest['license_note']='CC BY 4.0, attributed to Almond generated asset library. Original models carry historical paid-plan declarations; ProjectY2K additions carry project-owner redistribution authorization. See item-level source evidence; provider entitlement is not independently verified.'
    for name,data in [('manifest.json',manifest),('catalogue.json',catalogue),('provenance.json',provenance)]:write(library/name,data)

if __name__=='__main__':main()
