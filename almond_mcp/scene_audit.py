"""Read-only comparison of explicit Rhino object inventories.

Inspired by BIMlight's stale-quantity review pattern; no external code copied.
All physical measurements in this contract are millimetres (or mm squared/cubed).
Native geometry CRCs are compared only within the same document unit system.
"""
from __future__ import annotations

import math
import uuid
from collections import Counter

SCHEMA = 1
MAX_OBJECTS = 500


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Audit measurements must be finite numbers')
    return float(value)


def _guid(value):
    try:
        parsed = uuid.UUID(str(value))
        if not parsed.int:
            raise ValueError('Empty GUID')
        return str(parsed)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError('Every audited object needs a valid Rhino GUID') from exc


def object_ids(values):
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_OBJECTS:
        raise ValueError(f'Provide 1 to {MAX_OBJECTS} explicit Rhino object GUIDs')
    ids = [_guid(value) for value in values]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate Rhino GUIDs are not allowed')
    return ids


def validate_inventory(data):
    if not isinstance(data, dict) or data.get('status') != 'ok' or type(data.get('schema')) is not int or data.get('schema') != SCHEMA:
        raise ValueError('Expected a scene_inventory schema 1 reply; update the matching almondbridge')
    if data.get('complete') is not True:
        raise ValueError('Incomplete inventory cannot establish deleted or unchanged objects')
    if not isinstance(data.get('document_key'), str) or not data['document_key']:
        raise ValueError('Inventory has no document identity')
    if not isinstance(data.get('units'), str) or not data['units']:
        raise ValueError('Inventory has no document unit system')
    requested = object_ids(data.get('requested_ids'))
    objects = data.get('objects')
    missing = data.get('missing_ids')
    if not isinstance(objects, list) or not isinstance(missing, list):
        raise ValueError('Inventory must explicitly report objects and missing_ids')
    found = []
    for obj in objects:
        if not isinstance(obj, dict):
            raise ValueError('Invalid inventory object')
        found.append(_guid(obj.get('id')))
        b = obj.get('bounds_mm')
        if not isinstance(b, list) or len(b) != 6:
            raise ValueError('Each object needs six world bounding-box coordinates in mm')
        b = [_number(v) for v in b]
        if any(b[i] > b[i+3] for i in range(3)):
            raise ValueError('Invalid object bounding box')
        if not isinstance(obj.get('kind'), str) or not obj['kind']:
            raise ValueError('Object kind is required')
        metadata = obj.get('metadata')
        if not isinstance(metadata, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k,v in metadata.items()):
            raise ValueError('Metadata must be a string dictionary')
        quantities = obj.get('quantities')
        if not isinstance(quantities, dict) or set(quantities) - {'length_mm','area_mm2','volume_mm3'}:
            raise ValueError('Unsupported quantity or missing quantity dictionary')
        for value in quantities.values():
            if value is not None and _number(value) < 0:
                raise ValueError('Quantities cannot be negative')
        transform = obj.get('transform')
        if transform is not None:
            if not isinstance(transform, list) or len(transform) != 12:
                raise ValueError('Instance transform must have 12 row-major entries; translations in mm')
            for v in transform: _number(v)
        crc = obj.get('geometry_crc')
        if crc is not None and not isinstance(crc, str):
            raise ValueError('Geometry CRC must be a string or null')
    absent = [_guid(g) for g in missing]
    reported = found + absent
    if len(reported) != len(set(reported)) or set(reported) != set(requested):
        raise ValueError('Inventory does not account for every requested object exactly once')
    return data


def compare(baseline, current, absolute_mm=0.1, relative=1e-6, detail_limit=100):
    """Compare without updating either inventory. Changed units never imply movement alone."""
    baseline = validate_inventory(baseline)
    current = validate_inventory(current)
    absolute_mm, relative = _number(absolute_mm), _number(relative)
    if absolute_mm < 0 or relative < 0:
        raise ValueError('Tolerances cannot be negative')
    if isinstance(detail_limit, bool) or not isinstance(detail_limit, int) or not 1 <= detail_limit <= MAX_OBJECTS:
        raise ValueError(f'detail_limit must be between 1 and {MAX_OBJECTS}')
    if baseline['document_key'] != current['document_key']:
        raise ValueError('Different Rhino document: deliberately capture a new baseline for this document')
    if set(map(_guid,baseline['requested_ids'])) != set(map(_guid,current['requested_ids'])):
        raise ValueError('Audit must inventory exactly the baseline object IDs')
    if baseline['missing_ids']:
        raise ValueError('A baseline cannot contain missing objects')
    before = {_guid(o['id']):o for o in baseline['objects']}
    after = {_guid(o['id']):o for o in current['objects']}
    units_changed = baseline['units'] != current['units']
    warnings = []
    if units_changed:
        warnings.append('Document units changed. Physical bounds and quantities remain comparable in mm; native CRC and instance linear-transform comparisons are skipped.')
    issues = []
    def close(a,b,absolute):
        return abs(a-b) <= absolute + relative*max(abs(a),abs(b))
    for guid, old in before.items():
        new = after.get(guid)
        reasons = []
        def add(code, message, **values):
            reasons.append({'code':code,'message':message,**values})
        if new is None:
            add('missing_object','Object was deleted or is no longer present in this document')
        else:
            a,b = old['bounds_mm'],new['bounds_mm']
            sizes_a = [a[i+3]-a[i] for i in range(3)]
            sizes_b = [b[i+3]-b[i] for i in range(3)]
            # Relative position tolerance follows object size, never distance from world origin.
            position_tolerance = absolute_mm + relative*max(*sizes_a,*sizes_b)
            delta = [(b[i]+b[i+3]-a[i]-a[i+3])/2 for i in range(3)]
            moved = any(abs(v)>position_tolerance for v in delta)
            resized = any(not close(x,y,absolute_mm) for x,y in zip(sizes_a,sizes_b))
            if moved: add('moved','World bounding-box centre changed',delta_mm=delta)
            if resized: add('size_changed','World extents changed (scale, rotation or shape)',before_mm=sizes_a,after_mm=sizes_b)
            if old['kind'] != new['kind']: add('geometry_type_changed','Geometry type changed',before=old['kind'],after=new['kind'])
            ta,tb = old.get('transform'),new.get('transform')
            if (ta is None)!=(tb is None): add('instance_type_changed','Object changed between a block instance and ordinary geometry')
            elif ta is not None and not units_changed:
                changed = any(abs(ta[i]-tb[i]) > position_tolerance if i in (3,7,11)
                              else not close(ta[i],tb[i],1e-8) for i in range(12))
                if changed: add('transform_changed','Block instance transform changed')
            if not units_changed:
                if not old.get('geometry_crc') or not new.get('geometry_crc'):
                    warnings.append(f'{guid}: geometry CRC unavailable; geometric coverage is limited to bounds and quantities')
                elif old['geometry_crc'] != new['geometry_crc']:
                    # Ordinary CRCs include coordinates; movement/extents already explain those changes.
                    if old['kind']=='InstanceReference' or not (moved or resized):
                        add('geometry_changed','Geometry checksum changed',before=old['geometry_crc'],after=new['geometry_crc'])
            for key in sorted(set(old['metadata']) | set(new['metadata'])):
                av,bv = old['metadata'].get(key),new['metadata'].get(key)
                if av != bv:
                    code = 'metadata_removed' if bv is None else 'metadata_added' if av is None else 'metadata_changed'
                    add(code,f'Object user text changed: {key}',key=key,before=av,after=bv)
            for key in sorted(set(old['quantities']) | set(new['quantities'])):
                av,bv = old['quantities'].get(key),new['quantities'].get(key)
                if av is None or bv is None:
                    if av != bv: add('quantity_unavailable',f'Quantity availability changed: {key}',quantity=key,before=av,after=bv)
                elif not close(av,bv,absolute_mm if key=='length_mm' else 1.0):
                    add('quantity_changed',f'Recomputed geometric quantity changed: {key}',quantity=key,before=av,after=bv)
        if reasons:
            issues.append({'rhino_guid':guid,'name':old.get('name',''),'bounds_mm':(new or old)['bounds_mm'],'reasons':reasons})
    counts = Counter(r['code'] for item in issues for r in item['reasons'])
    return {'status':'success','audit_status':'changed' if issues else 'incomplete' if warnings else 'clean',
            'checked_objects':len(before),'changed_objects':len(issues),'unchanged_objects':len(before)-len(issues),
            'units_changed':units_changed,'issues':issues[:detail_limit],'omitted_issues':max(0,len(issues)-detail_limit),
            'reason_counts':dict(sorted(counts.items())),'warnings':warnings,
            'tolerances':{'absolute_mm':absolute_mm,'relative':relative,'area_absolute_mm2':1.0,'volume_absolute_mm3':1.0},
            'scope':'Explicit snapshot objects only; detects change from recorded state, not design correctness or metadata truth. CRC is a change detector, not a cryptographic identity.'}
