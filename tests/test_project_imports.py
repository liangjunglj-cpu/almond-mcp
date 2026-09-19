"""Imported geometry must be compact, traceable and truthful about unknown history."""
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from document_generation_sources import build_register


def test_y2k_imports_keep_source_history_and_compact_geometry():
    manifest=json.loads((ROOT/'GeneratedAssetfiles/manifest.json').read_text())
    imports=[a for a in manifest['assets'] if a['asset_id'].startswith('gen-y2k-')]
    assert len(imports)==5
    for asset in imports:
        generation=asset['geometry_source']['parameters']
        evidence=generation['import_record']
        assert generation['prompt'] is None and generation['image_task_id'] is None
        assert evidence['image_stage'].startswith('not_applicable')
        assert asset['triangle_count']<=20000
        assert evidence['conversion']['source_triangles']>=asset['triangle_count']
        assert asset['license']==evidence['rights']['model_license']=='CC-BY-4.0'
        assert evidence['rights']['authorization_date']=='2026-09-19'
        assert not Path(evidence['conversion']['source_file']).is_absolute()
        assert evidence['dimension_basis'].startswith('Height is an authored project placement')
        assert asset['passport']['provenance']==asset['geometry_source']


def test_import_audit_rejects_missing_source_checksums(tmp_path):
    library=ROOT/'GeneratedAssetfiles'
    for name in ['manifest.json','catalogue.json','provenance.json']:
        data=json.loads((library/name).read_text())
        if name=='manifest.json':
            for asset in data['assets']:
                if asset['asset_id'].startswith('gen-y2k-'):
                    asset['geometry_source']['parameters']['import_record']['conversion']['source_sha256']='invalid'
        (tmp_path/name).write_text(json.dumps(data),encoding='utf-8')
    result=build_register(tmp_path)
    assert result['status']=='inconsistent'
    assert sum('invalid import evidence checksum' in e for e in result['errors'])==5
