from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from almond_mcp import server
from almond_mcp.retrieval_store import AlmondStore
from test_scene_audit import inventory


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    store=AlmondStore(tmp_path/'audit.db');monkeypatch.setattr(server,'retrieval_store',store)
    current=inventory()
    def send(payload,**kw):
        message=json.loads(payload)
        if message['type']=='scene_inventory':return json.dumps(current)
        return json.dumps({'status':'cleared' if message.get('clear') else 'shown'})
    transport=Mock(side_effect=send);monkeypatch.setattr(server,'_send_and_receive',transport)
    return store,current,transport


def test_capture_audit_and_overlay_do_not_repair_baseline(runtime):
    store,current,transport=runtime
    captured=server.capture_scene_metadata_snapshot('Before',current['requested_ids'])
    sid=captured['snapshot']['snapshot_id'];old=store.get_metadata_snapshot(sid)
    current['objects'][0]['metadata']['almond:section']='chs 193.7x8'
    report=server.audit_scene_metadata(sid)
    assert report['reason_counts']=={'metadata_changed':1}
    assert store.get_metadata_snapshot(sid)==old
    assert [json.loads(c.args[0])['type'] for c in transport.call_args_list]==['scene_inventory','scene_inventory']
    assert server.show_scene_metadata_issues(sid)['status']=='shown'
    payload=json.loads(transport.call_args.args[0]);assert payload['issues'][0]['rhino_guid']==current['requested_ids'][0]
    assert server.show_scene_metadata_issues(clear=True)['status']=='cleared'
    assert store.get_metadata_snapshot(sid)==old


def test_old_bridge_and_partial_replies_do_not_create_snapshot(runtime):
    store,current,transport=runtime
    transport.side_effect=None;transport.return_value=json.dumps({'status':'error','message':'Unknown request type'})
    result=server.capture_scene_metadata_snapshot('Before',current['requested_ids'])
    assert result['status']=='error' and 'development almondbridge' in result['message']
    transport.return_value=json.dumps({**current,'complete':False})
    assert server.capture_scene_metadata_snapshot('Before',current['requested_ids'])['status']=='error'


def test_different_document_cannot_show_overlay(runtime):
    store,current,transport=runtime
    sid=server.capture_scene_metadata_snapshot('Before',current['requested_ids'])['snapshot']['snapshot_id']
    current['document_key']='file:wrong.3dm'
    assert server.show_scene_metadata_issues(sid)['status']=='error'
    assert json.loads(transport.call_args.args[0])['type']=='scene_inventory'


def test_unknown_snapshot_does_not_contact_rhino(runtime):
    store,current,transport=runtime
    assert server.audit_scene_metadata('unknown')['status']=='error'
    transport.assert_not_called()
