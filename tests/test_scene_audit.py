from copy import deepcopy
import json
import uuid
import pytest

from almond_mcp import scene_audit
from almond_mcp.retrieval_store import AlmondStore

G1=str(uuid.UUID(int=1)); G2=str(uuid.UUID(int=2))

def inventory():
    return {'status':'ok','schema':1,'complete':True,'document_key':'file:demo.3dm','units':'Millimeters',
            'requested_ids':[G1],'missing_ids':[], 'objects':[{'id':G1,'kind':'Curve','name':'beam',
            'bounds_mm':[0,0,0,4000,0,0], 'metadata':{'almond:section':'chs 114.3x4'},
            'quantities':{'length_mm':4000},'transform':None,'geometry_crc':'1234'}]}


def test_unchanged_is_clean_and_does_not_modify_inputs():
    a,b=inventory(),inventory(); old_a,old_b=deepcopy(a),deepcopy(b)
    report=scene_audit.compare(a,b)
    assert report['audit_status']=='clean' and report['checked_objects']==1
    assert a==old_a and b==old_b


@pytest.mark.parametrize('change,expected',[
    ('move','moved'),('scale','size_changed'),('delete','missing_object'),
    ('section','metadata_changed'),('remove_section','metadata_removed'),
    ('shape','geometry_changed'),('quantity','quantity_changed')])
def test_changes_report_specific_reasons(change,expected):
    a,b=inventory(),inventory();obj=b['objects'][0]
    if change=='move':obj['bounds_mm']=[100,0,0,4100,0,0];obj['geometry_crc']='abcd'
    if change=='scale':obj['bounds_mm'][3]=8000;obj['quantities']['length_mm']=8000
    if change=='delete':b['objects']=[];b['missing_ids']=[G1]
    if change=='section':obj['metadata']['almond:section']='chs 193.7x8'
    if change=='remove_section':obj['metadata']={}
    if change=='shape':obj['geometry_crc']='abcd'
    if change=='quantity':obj['quantities']['length_mm']=4500
    report=scene_audit.compare(a,b)
    assert report['changed_objects']==1 and expected in report['reason_counts']


def test_physical_unit_conversion_does_not_claim_geometry_changed():
    a,b=inventory(),inventory();b['units']='Meters';b['objects'][0]['geometry_crc']='changed-native-units'
    report=scene_audit.compare(a,b)
    assert report['changed_objects']==0 and report['units_changed']
    assert report['audit_status']=='incomplete' and 'skipped' in report['warnings'][0]


def test_scaled_block_and_changed_definition_audited_per_instance():
    a=inventory();obj=a['objects'][0];obj['kind']='InstanceReference'
    obj['transform']=[1,0,0,0,0,1,0,0,0,0,1,0]
    second=deepcopy(obj);second['id']=G2;a['objects'].append(second);a['requested_ids'].append(G2)
    b=deepcopy(a);b['objects'][0]['transform'][0]=2;b['objects'][0]['bounds_mm'][3]=8000
    for o in b['objects']:o['geometry_crc']='changed-definition'
    report=scene_audit.compare(a,b)
    assert report['changed_objects']==2 and report['reason_counts']['geometry_changed']==2
    assert report['reason_counts']['transform_changed']==1


def test_mirrored_block_transform_detected_even_with_same_bounds():
    a=inventory();a['objects'][0]['kind']='InstanceReference';a['objects'][0]['transform']=[1,0,0,0,0,1,0,0,0,0,1,0]
    b=deepcopy(a);b['objects'][0]['transform'][0]=-1
    assert scene_audit.compare(a,b)['reason_counts']=={'transform_changed':1}


def test_far_from_origin_does_not_hide_real_movement():
    a,b=inventory(),inventory()
    for source in [a,b]:source['objects'][0]['bounds_mm']=[1e9,0,0,1e9+4000,0,0]
    b['objects'][0]['bounds_mm'][0]+=10;b['objects'][0]['bounds_mm'][3]+=10
    assert 'moved' in scene_audit.compare(a,b)['reason_counts']


def test_far_from_origin_block_translation_uses_object_size_tolerance():
    a=inventory();obj=a['objects'][0];obj['kind']='InstanceReference'
    obj['bounds_mm']=[1e9,0,0,1e9+4000,0,0]
    obj['transform']=[1,0,0,1e9,0,1,0,0,0,0,1,0]
    b=deepcopy(a);b['objects'][0]['transform'][3]+=10
    b['objects'][0]['bounds_mm'][0]+=10;b['objects'][0]['bounds_mm'][3]+=10
    assert 'transform_changed' in scene_audit.compare(a,b)['reason_counts']


def test_guid_case_is_normalised_and_empty_guid_refused():
    a,b=inventory(),inventory()
    mixed='abcdef12-abcd-abcd-abcd-abcdef123456'
    a['requested_ids']=[mixed.upper()];a['objects'][0]['id']=mixed.upper()
    b['requested_ids']=[mixed];b['objects'][0]['id']=mixed
    assert scene_audit.compare(a,b)['audit_status']=='clean'
    with pytest.raises(ValueError):scene_audit.object_ids([str(uuid.UUID(int=0))])


def test_tolerances_and_full_counts_with_truncated_details():
    a,b=inventory(),inventory();b['objects'][0]['bounds_mm'][0]+=0.01;b['objects'][0]['bounds_mm'][3]+=0.01
    assert scene_audit.compare(a,b)['audit_status']=='clean'
    for source in [a,b]:
        second=deepcopy(source['objects'][0]);second['id']=G2;source['objects'].append(second);source['requested_ids'].append(G2)
    for obj in b['objects']:obj['metadata']={}
    report=scene_audit.compare(a,b,detail_limit=1)
    assert report['changed_objects']==2 and len(report['issues'])==1 and report['omitted_issues']==1


@pytest.mark.parametrize('case',['incomplete','unaccounted','duplicate','wrong_document','nonfinite','missing_baseline'])
def test_bad_inventory_cannot_report_deleted_or_clean(case):
    a,b=inventory(),inventory()
    if case=='incomplete':b['complete']=False
    if case=='unaccounted':b['objects']=[]
    if case=='duplicate':b['objects'].append(deepcopy(b['objects'][0]))
    if case=='wrong_document':b['document_key']='file:other.3dm'
    if case=='nonfinite':b['objects'][0]['bounds_mm'][0]=float('nan')
    if case=='missing_baseline':a['objects']=[];a['missing_ids']=[G1]
    with pytest.raises(ValueError):scene_audit.compare(a,b)


@pytest.mark.parametrize('value',[-1,float('inf'),float('nan'),True])
def test_invalid_tolerance_refused(value):
    with pytest.raises(ValueError):scene_audit.compare(inventory(),inventory(),absolute_mm=value)


def test_snapshots_are_immutable_and_survive_store_reload(tmp_path):
    path=tmp_path/'state.db';store=AlmondStore(path);data=inventory()
    first=store.capture_metadata_snapshot('Before',data)
    data['objects'][0]['metadata']['almond:section']='chs 193.7x8'
    second=store.capture_metadata_snapshot('After',data)
    assert first['snapshot_id']!=second['snapshot_id']
    read=store.get_metadata_snapshot(first['snapshot_id']);read['inventory']['objects'][0]['metadata']={}
    before=AlmondStore(path).get_metadata_snapshot(first['snapshot_id'])
    assert before['inventory']['objects'][0]['metadata']['almond:section']=='chs 114.3x4'
    assert store.get_metadata_snapshot('missing') is None


def test_capture_refuses_missing_object(tmp_path):
    data=inventory();data['objects']=[];data['missing_ids']=[G1]
    with pytest.raises(ValueError):AlmondStore(tmp_path/'state.db').capture_metadata_snapshot('No',data)
