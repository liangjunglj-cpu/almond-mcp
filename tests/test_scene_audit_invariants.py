"""Scene metadata audit invariants: origin-independent tolerance, truncation accounting,
identity under reordering, schema strictness and concurrent snapshot capture."""
import copy
import uuid
import pytest
from almond_mcp import scene_audit as sa

def inventory(count=1, origin=0):
    ids=[str(uuid.UUID(int=i+1)) for i in range(count)]
    return {'status':'ok','schema':1,'complete':True,'document_key':'test-document','units':'Millimeters',
            'requested_ids':ids,'missing_ids':[], 'objects':[{'id':g,'kind':'Curve','name':'beam',
              'bounds_mm':[origin,0,0,origin+4000,0,0], 'metadata':{'almond:section':'chs 114.3x4'},
              'quantities':{'length_mm':4000},'transform':None,'geometry_crc':'1234'} for g in ids]}

@pytest.mark.parametrize('origin',[0,1e6,1e9,-1e9])
def test_audit_tolerance_is_invariant_to_geographic_origin(origin):
    a=inventory(origin=origin); b=copy.deepcopy(a)
    for k in [0,3]:b['objects'][0]['bounds_mm'][k]+=.2
    assert sa.compare(a,b)['reason_counts']=={'moved':1}

def test_audit_all_500_objects_and_truncated_details_are_accounted_for():
    a=inventory(500); b=copy.deepcopy(a)
    for o in b['objects']:o['metadata']['almond:section']='changed'
    out=sa.compare(a,b,detail_limit=7)
    assert out['changed_objects']==500 and out['omitted_issues']==493
    assert len(out['issues'])==7 and out['reason_counts']=={'metadata_changed':500}
    assert sa.compare(b,a,detail_limit=7)['changed_objects']==500

def test_audit_reordering_and_guid_case_do_not_change_identity():
    a=inventory(20); b=copy.deepcopy(a)
    b['objects'].reverse();b['requested_ids'].reverse()
    for o in b['objects']:o['id']=o['id'].upper()
    b['requested_ids']=[g.upper() for g in b['requested_ids']]
    before=copy.deepcopy((a,b))
    assert sa.compare(a,b)['audit_status']=='clean'
    assert (a,b)==before

@pytest.mark.parametrize('value',[True,1.0,'1',None])
def test_audit_schema_requires_an_integer_version(value):
    a=inventory();a['schema']=value
    with pytest.raises(ValueError):sa.validate_inventory(a)

def test_concurrent_snapshots_are_unique_immutable_and_recoverable(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from almond_mcp.retrieval_store import AlmondStore
    store=AlmondStore(tmp_path/'state.db')
    def capture(i):
        data=inventory();data['objects'][0]['metadata']['almond:section']=str(i)
        record=store.capture_metadata_snapshot(f'snapshot {i}',data)
        return i,record['snapshot_id']
    with ThreadPoolExecutor(max_workers=8) as pool:records=list(pool.map(capture,range(64)))
    assert len({sid for _,sid in records})==64
    reopened=AlmondStore(tmp_path/'state.db')
    for i,sid in records:
        assert reopened.get_metadata_snapshot(sid)['inventory']['objects'][0]['metadata']['almond:section']==str(i)
