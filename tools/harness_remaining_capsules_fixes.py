import xml.etree.ElementTree as ET

# CANOPY: Analyse.Model <- Assemble.Model (bypass OptiCroSec, which hits a trial limit)
t = ET.parse('01_SimpleCanopy_harnessed.xml')
root = t.getroot()
assemble_model_out = None
for obj in root.iter('chunk'):
    if obj.get('name') != 'Object':
        continue
    tname = next((it.text for it in obj.find('items').iter('item') if it.get('name') == 'Name'), '?').strip()
    if tname != 'Assemble Model (Karamba3D)':
        continue
    cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
    for pc in cont.iter('chunk'):
        if pc.get('name') == 'param_output':
            pits = pc.find('items')
            nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
            if nm == 'Model':
                assemble_model_out = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
assert assemble_model_out
n = 0
for obj in root.iter('chunk'):
    if obj.get('name') != 'Object':
        continue
    tname = next((it.text for it in obj.find('items').iter('item') if it.get('name') == 'Name'), '?').strip()
    if tname != 'Analyse (Karamba3D)':
        continue
    cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
    for pc in cont.iter('chunk'):
        if pc.get('name') not in ('param_input', 'p'):
            continue
        pits = pc.find('items')
        if pits is None:
            continue
        nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), None)
        if nm != 'Model':
            continue
        for it in pits.iter('item'):
            if it.get('name') == 'Source':
                it.text = assemble_model_out
                n += 1
print('canopy: analyse rewired to assemble directly:', n)
assert n >= 1
t.write('01_SimpleCanopy_harnessed.xml', encoding='utf-8', xml_declaration=True)

# HIGHRISE: branch-0 Load collector <- a functioning Gravity Loads output
t = ET.parse('01_HighRiseSystems_harnessed.xml')
root = t.getroot()
loads_info = []
for obj in root.iter('chunk'):
    if obj.get('name') != 'Object':
        continue
    tname = next((it.text for it in obj.find('items').iter('item') if it.get('name') == 'Name'), '?').strip()
    cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
    if cont is None:
        continue
    inst = next((it.text for it in cont.find('items').iter('item') if it.get('name') == 'InstanceGuid'), None)
    if tname == 'Loads (Karamba3D)':
        au = None
        for c in cont.find('chunks').findall('chunk'):
            if c.get('name') == 'ActiveUnit':
                au = next((it.text for it in c.find('items').iter('item')), None)
        out = None
        for pc in cont.iter('chunk'):
            if pc.get('name') in ('param_output', 'p'):
                pits = pc.find('items')
                if pits is None:
                    continue
                nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), '')
                if nm in ('Load', 'L'):
                    out = next((it.text for it in pits.iter('item') if it.get('name') == 'InstanceGuid'), None)
        loads_info.append((inst, au, out))
for li in loads_info:
    print('loads comp:', li[0][:8], 'unit:', li[1], 'out:', str(li[2])[:8])
grav = next((li for li in loads_info if li[1] == 'Gravity' and li[2]), None)
if grav is None:
    grav = next((li for li in loads_info if li[2]), None)
print('chosen loads:', grav[0][:8], grav[1])
n = 0
for obj in root.iter('chunk'):
    if obj.get('name') != 'Object':
        continue
    cont = next((c for c in obj.find('chunks').findall('chunk') if c.get('name') == 'Container'), None)
    if cont is None:
        continue
    inst = next((it.text for it in cont.find('items').iter('item') if it.get('name') == 'InstanceGuid'), None)
    if not (inst or '').startswith('3f062725'):
        continue
    for pc in cont.iter('chunk'):
        if pc.get('name') not in ('param_input', 'p'):
            continue
        pits = pc.find('items')
        if pits is None:
            continue
        nm = next((it.text for it in pits.iter('item') if it.get('name') == 'Name'), None)
        if nm != 'Load':
            continue
        srcs = [it for it in pits.findall('item') if it.get('name') == 'Source']
        for i, it in enumerate(srcs):
            if i == 0:
                it.text = grav[2]
                it.set('index', '0')
                n += 1
            else:
                pits.remove(it)
        sc = next((it for it in pits.iter('item') if it.get('name') == 'SourceCount'), None)
        if sc is not None:
            sc.text = '1'
        pits.set('count', str(len(pits.findall('item'))))
print('highrise: branch-0 load rewired:', n)
assert n >= 1
t.write('01_HighRiseSystems_harnessed.xml', encoding='utf-8', xml_declaration=True)
