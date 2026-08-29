"""Surgery for the last four capsules: canopy, membrane, gridshell, highrise."""
import xml.etree.ElementTree as ET
import uuid

PARAM_CURVE = "d5967b9f-e8ee-436b-a8ad-29fdcecf32d5"
PARAM_NUMBER = "3e8ca6be-fda8-4aaf-b5c0-3c54c8bb7312"
PARAM_POINT = "fbac3e32-f100-4292-8692-77240a42fd1a"
PARAM_MESH = "1e936df3-0eea-4246-8549-514cb8862b7a"


def make_param(idx, type_guid, type_name, inst, nick, desc, source, x, y):
    obj = ET.Element('chunk', {'name': 'Object', 'index': str(idx)})
    items = ET.SubElement(obj, 'items', {'count': '2'})

    def item(parent, name, text, tn='gh_string', tc='10', extra=None):
        a = {'name': name, 'type_name': tn, 'type_code': tc}
        if extra:
            a.update(extra)
        e = ET.SubElement(parent, 'item', a)
        e.text = text
        return e

    item(items, 'GUID', type_guid, 'gh_guid', '9')
    item(items, 'Name', type_name)
    chunks = ET.SubElement(obj, 'chunks', {'count': '1'})
    cont = ET.SubElement(chunks, 'chunk', {'name': 'Container'})
    ci = ET.SubElement(cont, 'items', {'count': str(7 + (1 if source else 0))})
    item(ci, 'Description', desc)
    item(ci, 'InstanceGuid', inst, 'gh_guid', '9')
    item(ci, 'Mapping', '1', 'gh_int32', '3')
    item(ci, 'Name', type_name)
    item(ci, 'NickName', nick)
    item(ci, 'Optional', 'true', 'gh_bool', '1')
    if source:
        item(ci, 'Source', source, 'gh_guid', '9', {'index': '0'})
    item(ci, 'SourceCount', '1' if source else '0', 'gh_int32', '3')
    cch = ET.SubElement(cont, 'chunks', {'count': '1'})
    att = ET.SubElement(cch, 'chunk', {'name': 'Attributes'})
    ai = ET.SubElement(att, 'items', {'count': '2'})
    b = ET.SubElement(ai, 'item', {'name': 'Bounds', 'type_name': 'gh_drawing_rectanglef', 'type_code': '35'})
    for tag, val in (('X', str(x)), ('Y', str(y)), ('W', '160'), ('H', '24')):
        ET.SubElement(b, tag).text = val
    p = ET.SubElement(ai, 'item', {'name': 'Pivot', 'type_name': 'gh_drawing_pointf', 'type_code': '31'})
    for tag, val in (('X', str(x + 80)), ('Y', str(y + 12))):
        ET.SubElement(p, tag).text = val
    return obj


def load(fname):
    t = ET.parse(fname)
    return t, t.getroot()


def containers_of(root):
    out = {}
    for obj in root.iter('chunk'):
        if obj.get('name') != 'Object':
            continue
        tname = next((it.text for it in obj.find('items').iter('item') if it.get('name') == 'Name'), '?').strip()
        cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
        if cont is None:
            continue
        inst = next((it.text for it in cont.find('items').iter('item') if it.get('name') == 'InstanceGuid'), None)
        nick = next((it.text for it in cont.find('items').iter('item') if it.get('name') == 'NickName'), None)
        out[inst] = (tname, nick, cont)
    return out


def add_params(root, specs):
    defobjs = next(c for c in root.iter('chunk') if c.get('name') == 'DefinitionObjects')
    oc = next(it for it in defobjs.find('items').iter('item') if it.get('name') == 'ObjectCount')
    count = int(oc.text)
    holder = defobjs.find('chunks')
    for i, (tg, tn, inst, nick, src) in enumerate(specs):
        holder.append(make_param(count + i, tg, tn, inst, nick, f'Almond harness: {nick}.', src, 60, 40 + i * 70))
    holder.set('count', str(count + len(specs)))
    oc.text = str(count + len(specs))


def rewire_named_input(cont, in_name, new_src, replace_all_sources=True):
    n = 0
    for pc in cont.iter('chunk'):
        if pc.get('name') not in ('param_input', 'p'):
            continue
        pits = pc.find('items')
        if pits is None:
            continue
        nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), None)
        if nm != in_name:
            continue
        srcs = [it for it in pits.findall('item') if it.get('name') == 'Source']
        if not srcs:
            continue
        for i, it in enumerate(srcs):
            if i == 0:
                it.text = new_src
                it.set('index', '0')
            else:
                pits.remove(it)
        sc = next((it for it in pits.iter('item') if it.get('name') == 'SourceCount'), None)
        if sc is not None:
            sc.text = '1'
        pits.set('count', str(len(pits.findall('item'))))
        n += 1
    return n


def replace_source_guid(root, old_src_prefix, new_src):
    n = 0
    for it in root.iter('item'):
        if it.get('name') == 'Source' and it.text and it.text.startswith(old_src_prefix):
            it.text = new_src
            n += 1
    return n


def null_input(cont, in_name):
    """Remove all sources from a named input (disables a branch)."""
    n = 0
    for pc in cont.iter('chunk'):
        if pc.get('name') not in ('param_input', 'p'):
            continue
        pits = pc.find('items')
        if pits is None:
            continue
        nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), None)
        if nm != in_name:
            continue
        removed = False
        for it in list(pits.findall('item')):
            if it.get('name') == 'Source':
                pits.remove(it)
                removed = True
        if removed:
            sc = next((it for it in pits.iter('item') if it.get('name') == 'SourceCount'), None)
            if sc is not None:
                sc.text = '0'
            pits.set('count', str(len(pits.findall('item'))))
            n += 1
    return n


# ═══ CANOPY ═══
t, root = load('01_SimpleCanopy.xml')
C = containers_of(root)
G_LINES, G_LOAD, G_SUP = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
G_DISP, G_MASS = str(uuid.uuid4()), str(uuid.uuid4())
add_params(root, [
    (PARAM_CURVE, 'Curve', G_LINES, 'ALMOND_IN_LINES', None),
    (PARAM_NUMBER, 'Number', G_LOAD, 'ALMOND_IN_LOAD_KN', None),
    (PARAM_POINT, 'Point', G_SUP, 'ALMOND_IN_SUPPORTS', None),
    (PARAM_NUMBER, 'Number', G_DISP, 'ALMOND_OUT_DISP_MM', 'c0e4ceae-3dff-46b5-a5b5-44b8a71c04e2'[:0] or None),
    (PARAM_NUMBER, 'Number', G_MASS, 'ALMOND_OUT_MASS_KG', None),
])
# fix output sources after creation (need full inst guids from mapping)
CANOPY_DISP = None
CANOPY_MASS = None
for inst, (tname, nick, cont) in C.items():
    if tname == 'Analyse (Karamba3D)':
        for pc in cont.iter('chunk'):
            if pc.get('name') != 'param_output':
                continue
            pits = pc.find('items')
            nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
            if 'Maximum Displacement' in nm:
                CANOPY_DISP = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
    if tname == 'Assemble Model (Karamba3D)':
        for pc in cont.iter('chunk'):
            if pc.get('name') != 'param_output':
                continue
            pits = pc.find('items')
            nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
            if 'Mass' in nm:
                CANOPY_MASS = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
# wire the two output params we just added
for obj in root.iter('chunk'):
    if obj.get('name') != 'Object':
        continue
    cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
    if cont is None:
        continue
    ci = cont.find('items')
    nick = next((it.text for it in ci.iter('item') if it.get('name') == 'NickName'), None)
    if nick in ('ALMOND_OUT_DISP_MM', 'ALMOND_OUT_MASS_KG'):
        src = CANOPY_DISP if nick == 'ALMOND_OUT_DISP_MM' else CANOPY_MASS
        e = ET.SubElement(ci, 'item', {'name': 'Source', 'index': '0', 'type_name': 'gh_guid', 'type_code': '9'})
        e.text = src
        sc = next((it for it in ci.iter('item') if it.get('name') == 'SourceCount'), None)
        sc.text = '1'
        ci.set('count', str(len(ci.findall('item'))))
# rewires
le = next(v for v in C.values() if v[0] == 'Create Linear Element (Karamba3D)')
n1 = rewire_named_input(le[2], 'Line', G_LINES)
supp = next(v for v in C.values() if v[0] == 'Support (Karamba3D)')
n2 = rewire_named_input(supp[2], 'Pos|Ind', G_SUP)
# load: slider feeding any Unit Z Factor -> G_LOAD
n3 = 0
sliders = {k for k, v in C.items() if v[0] == 'Number Slider'}
for inst, (tname, nick, cont) in C.items():
    if tname != 'Unit Z':
        continue
    for pc in cont.iter('chunk'):
        if pc.get('name') != 'param_input':
            continue
        pits = pc.find('items')
        nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), None)
        if nm != 'Factor':
            continue
        for it in pits.iter('item'):
            if it.get('name') == 'Source' and it.text in sliders:
                it.text = G_LOAD
                n3 += 1
# repoint one mesh-load Loads to Point unit at all beam nodes
loads_mesh = next((v for k, v in C.items() if k.startswith('b013a6e1')), None)
n4 = n5 = 0
if loads_mesh:
    _, _, lcont = loads_mesh
    for c in lcont.find('chunks').findall('chunk'):
        if c.get('name') == 'ActiveUnit':
            for it in c.find('items').iter('item'):
                it.text = 'Point'
                n4 += 1
    le_points = None
    for pc in le[2].iter('chunk'):
        if pc.get('name') == 'param_output':
            pits = pc.find('items')
            nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
            if nm == 'Points':
                le_points = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
    # the Mesh-unit Vector source (a Unit Z output) reused for the Point unit
    uz_out = None
    for pc in lcont.iter('chunk'):
        if pc.get('name') != 'p':
            continue
        pits = pc.find('items')
        nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), None)
        if nm == 'Vector':
            s = next((it.text for it in pits.iter('item') if it.get('name') == 'Source'), None)
            if s:
                uz_out = s
    for pc in lcont.iter('chunk'):
        if pc.get('name') != 'p':
            continue
        pits = pc.find('items')
        nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), None)
        if nm == 'Force Vector' and uz_out:
            has = any(it.get('name') == 'Source' for it in pits.iter('item'))
            if not has:
                e = ET.SubElement(pits, 'item', {'name': 'Source', 'index': '0', 'type_name': 'gh_guid', 'type_code': '9'})
                e.text = uz_out
                sc = next((it for it in pits.iter('item') if it.get('name') == 'SourceCount'), None)
                if sc is not None:
                    sc.text = '1'
                pits.set('count', str(len(pits.findall('item'))))
                n5 += 1
        if nm == 'Pos|Ind' and le_points:
            has = any(it.get('name') == 'Source' for it in pits.iter('item'))
            if not has:
                e = ET.SubElement(pits, 'item', {'name': 'Source', 'index': '0', 'type_name': 'gh_guid', 'type_code': '9'})
                e.text = le_points
                sc = next((it for it in pits.iter('item') if it.get('name') == 'SourceCount'), None)
                if sc is not None:
                    sc.text = '1'
                pits.set('count', str(len(pits.findall('item'))))
                n5 += 1
print(f"CANOPY: line={n1} supp={n2} loadfactor={n3} activeunit={n4} pointload_wires={n5} disp={CANOPY_DISP is not None} mass={CANOPY_MASS is not None}")
assert n1 == 1 and n2 == 1 and n3 >= 1 and CANOPY_DISP and CANOPY_MASS
t.write('01_SimpleCanopy_harnessed.xml', encoding='utf-8', xml_declaration=True)

# ═══ MEMBRANE ═══
t, root = load('04_MembraneFormFinding.xml')
C = containers_of(root)
G_MESH, G_PRE, G_SUP = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
add_params(root, [
    (PARAM_MESH, 'Mesh', G_MESH, 'ALMOND_IN_MESH', None),
    (PARAM_NUMBER, 'Number', G_PRE, 'ALMOND_IN_PRESTRAIN', None),
    (PARAM_POINT, 'Point', G_SUP, 'ALMOND_IN_SUPPORTS', None),
    (PARAM_NUMBER, 'Number', str(uuid.uuid4()), 'ALMOND_OUT_DISP_MM', '17f4804b-4fe1-4b93-0000-000000000000'[:0] or None),
    (PARAM_NUMBER, 'Number', str(uuid.uuid4()), 'ALMOND_OUT_MASS_KG', None),
])
MEM_DISP = MEM_MASS = None
for inst, (tname, nick, cont) in C.items():
    if tname == 'AnalyseThII (Karamba3D)':
        for pc in cont.iter('chunk'):
            if pc.get('name') == 'param_output':
                pits = pc.find('items')
                nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
                if 'Maximum Displacement' in nm:
                    MEM_DISP = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
    if tname == 'Assemble Model (Karamba3D)':
        for pc in cont.iter('chunk'):
            if pc.get('name') == 'param_output':
                pits = pc.find('items')
                nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
                if 'Mass' in nm:
                    MEM_MASS = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
for obj in root.iter('chunk'):
    if obj.get('name') != 'Object':
        continue
    cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
    if cont is None:
        continue
    ci = cont.find('items')
    nick = next((it.text for it in ci.iter('item') if it.get('name') == 'NickName'), None)
    if nick in ('ALMOND_OUT_DISP_MM', 'ALMOND_OUT_MASS_KG'):
        src = MEM_DISP if nick == 'ALMOND_OUT_DISP_MM' else MEM_MASS
        e = ET.SubElement(ci, 'item', {'name': 'Source', 'index': '0', 'type_name': 'gh_guid', 'type_code': '9'})
        e.text = src
        sc = next((it for it in ci.iter('item') if it.get('name') == 'SourceCount'), None)
        sc.text = '1'
        ci.set('count', str(len(ci.findall('item'))))
se = next(v for v in C.values() if v[0] == 'Create Surface Element (Karamba3D)')
n1 = rewire_named_input(se[2], 'Mesh', G_MESH)
supp = next(v for v in C.values() if v[0] == 'Support (Karamba3D)')
n2 = rewire_named_input(supp[2], 'Pos|Ind', G_SUP)
lo = next((v for k, v in C.items() if k.startswith('438131fa')), None)
n3 = rewire_named_input(lo[2], 'Eps0', G_PRE) if lo else 0
vx = next((v for v in C.values() if v[1] == 'VertexLoads'), None)
n4 = rewire_named_input(vx[2], 'Mesh', G_MESH) if vx else 0
print(f"MEMBRANE: mesh={n1} supp={n2} prestrain={n3} vertexload_mesh={n4} disp={MEM_DISP is not None} mass={MEM_MASS is not None}")
assert n1 == 1 and n2 == 1 and n3 == 1 and MEM_DISP and MEM_MASS
t.write('04_MembraneFormFinding_harnessed.xml', encoding='utf-8', xml_declaration=True)

# ═══ GRIDSHELL ═══
t, root = load('04_LargeDeformationTriangularGridshell.xml')
C = containers_of(root)
G_LINES, G_MAXD, G_SUP = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
add_params(root, [
    (PARAM_CURVE, 'Curve', G_LINES, 'ALMOND_IN_LINES', None),
    (PARAM_NUMBER, 'Number', G_MAXD, 'ALMOND_IN_MAXDISP_M', None),
    (PARAM_POINT, 'Point', G_SUP, 'ALMOND_IN_SUPPORTS', None),
    (PARAM_NUMBER, 'Number', str(uuid.uuid4()), 'ALMOND_OUT_DISP_MM', None),
    (PARAM_NUMBER, 'Number', str(uuid.uuid4()), 'ALMOND_OUT_MASS_KG', None),
])
GS_DISP = '06f35033-1277'  # LaDeform Maximum Displacement [cm] (prefix)
lad = next(v for v in C.values() if v[0] == 'Large Deformation Analysis (Karamba3D)')
GS_DISP_FULL = None
for pc in lad[2].iter('chunk'):
    if pc.get('name') == 'param_output':
        pits = pc.find('items')
        nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
        if 'Maximum Displacement' in nm:
            GS_DISP_FULL = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
# mass: the Assemble whose Elem source belongs to the DEFORMED LineElem (4ba0c93f...)
GS_MASS_FULL = None
le2_elem = None
for k, v in C.items():
    if v[0] == 'Create Linear Element (Karamba3D)' and k.startswith('4ba0c93f'):
        for pc in v[2].iter('chunk'):
            if pc.get('name') == 'param_output':
                pits = pc.find('items')
                nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
                if nm == 'Element':
                    le2_elem = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
for k, v in C.items():
    if v[0] != 'Assemble Model (Karamba3D)':
        continue
    elem_srcs = []
    for pc in v[2].iter('chunk'):
        if pc.get('name') in ('param_input', 'p'):
            pits = pc.find('items')
            nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), None)
            if nm == 'Elem':
                elem_srcs = [it.text for it in pits.iter('item') if it.get('name') == 'Source']
    if le2_elem in elem_srcs:
        for pc in v[2].iter('chunk'):
            if pc.get('name') == 'param_output':
                pits = pc.find('items')
                nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
                if 'Mass' in nm:
                    GS_MASS_FULL = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
for obj in root.iter('chunk'):
    if obj.get('name') != 'Object':
        continue
    cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
    if cont is None:
        continue
    ci = cont.find('items')
    nick = next((it.text for it in ci.iter('item') if it.get('name') == 'NickName'), None)
    if nick in ('ALMOND_OUT_DISP_MM', 'ALMOND_OUT_MASS_KG'):
        src = GS_DISP_FULL if nick == 'ALMOND_OUT_DISP_MM' else GS_MASS_FULL
        e = ET.SubElement(ci, 'item', {'name': 'Source', 'index': '0', 'type_name': 'gh_guid', 'type_code': '9'})
        e.text = src
        sc = next((it for it in ci.iter('item') if it.get('name') == 'SourceCount'), None)
        sc.text = '1'
        ci.set('count', str(len(ci.findall('item'))))
le1 = next(v for k, v in C.items() if v[0] == 'Create Linear Element (Karamba3D)' and k.startswith('7f586f9f'))
n1 = rewire_named_input(le1[2], 'Line', G_LINES)
n2 = 0
for k, v in C.items():
    if v[0] == 'Support (Karamba3D)' and (k.startswith('4f1f82ea') or k.startswith('4758b4f9')):
        n2 += rewire_named_input(v[2], 'Pos|Ind', G_SUP)
n3 = rewire_named_input(lad[2], 'Maximum Displacement [m]', G_MAXD)
print(f"GRIDSHELL: line={n1} supp={n2} maxdisp={n3} disp={GS_DISP_FULL is not None} mass={GS_MASS_FULL is not None}")
assert n1 == 1 and n2 == 2 and n3 == 1 and GS_DISP_FULL and GS_MASS_FULL
t.write('04_LargeDeformationTriangularGridshell_harnessed.xml', encoding='utf-8', xml_declaration=True)

# ═══ HIGHRISE ═══
t, root = load('01_HighRiseSystems.xml')
C = containers_of(root)
G_LINES, G_SUP = str(uuid.uuid4()), str(uuid.uuid4())
add_params(root, [
    (PARAM_CURVE, 'Curve', G_LINES, 'ALMOND_IN_LINES', None),
    (PARAM_POINT, 'Point', G_SUP, 'ALMOND_IN_SUPPORTS', None),
    (PARAM_NUMBER, 'Number', str(uuid.uuid4()), 'ALMOND_OUT_DISP_MM', None),
    (PARAM_NUMBER, 'Number', str(uuid.uuid4()), 'ALMOND_OUT_MASS_KG', None),
])
HR_DISP = '726db907-6b3a-47aa-bb91-6a21b3ef3641'
HR_MASS = '26d1e879-9d11-4c42-81c6-5dab3fb88e64'
for obj in root.iter('chunk'):
    if obj.get('name') != 'Object':
        continue
    cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
    if cont is None:
        continue
    ci = cont.find('items')
    nick = next((it.text for it in ci.iter('item') if it.get('name') == 'NickName'), None)
    if nick in ('ALMOND_OUT_DISP_MM', 'ALMOND_OUT_MASS_KG'):
        src = HR_DISP if nick == 'ALMOND_OUT_DISP_MM' else HR_MASS
        e = ET.SubElement(ci, 'item', {'name': 'Source', 'index': '0', 'type_name': 'gh_guid', 'type_code': '9'})
        e.text = src
        sc = next((it for it in ci.iter('item') if it.get('name') == 'SourceCount'), None)
        sc.text = '1'
        ci.set('count', str(len(ci.findall('item'))))
le0 = next(v for k, v in C.items() if v[0] == 'Create Linear Element (Karamba3D)' and k.startswith('115bdd1a'))
n1 = rewire_named_input(le0[2], 'Line', G_LINES)
n2 = 0
for k, v in C.items():
    if v[0] == 'Support (Karamba3D)':
        n2 += rewire_named_input(v[2], 'Pos|Ind', G_SUP)
n3 = 0
for k, v in C.items():
    if v[0] == 'Analyse (Karamba3D)' and not k.startswith('bd22955f'):
        n3 += null_input(v[2], 'Model')
print(f"HIGHRISE: line={n1} supp={n2} disabled_branches={n3}")
assert n1 == 1 and n2 >= 5 and n3 == 3
t.write('01_HighRiseSystems_harnessed.xml', encoding='utf-8', xml_declaration=True)
print("all four saved")
