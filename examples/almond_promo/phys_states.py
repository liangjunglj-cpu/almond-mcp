"""Karamba structure-view states for the PHYSICS section -> phys_states.json (consumed by rhino_phys_capture.cs)."""
import json
WORK = r'C:/Users/liang/Documents/almond_promo'
F = json.load(open(WORK + '/frame_ids.json'))
b = F['beams']; c = F['columns']; supports = F['wall'] + F['bases']
edge, south, joists, north, stringer = b[0:4], b[4:6], b[6:12], b[12:14], b[14:18]
BUILD = c + edge + south + north + joists + stringer          # erection order
STAGES = [('COLUMNS + VOID-EDGE BEAM', c + edge), ('EDGE BEAMS', c + edge + south + north),
          ('JOISTS', c + edge + south + north + joists), ('STRINGER  ·  COMPLETE', BUILD)]
SIZES = [(114.3, 4.0), (139.7, 5.0), (168.3, 6.3), (193.7, 8.0), (219.1, 8.0)]
FINAL = SIZES[3]   # lightest section that passes
T = 'ALMOND  //  KARAMBA LIVE ANALYSIS'


def req(members, load, size=SIZES[0], title=T, **kw):
    r = dict(type='structure_view', guids=members + supports, load_kn=load, fixed_rotations=False, span_m=6.2,
             color_by='utilization', scale=5, show_legend=False, beam_diameter_mm=size[0], beam_wall_mm=size[1], title=title)
    r.update(kw)
    return r


states = [dict(name='off_00', clear=True)]
states.append(dict(name='solve_full', req=req(BUILD, 150), capture=False))
for k in range(1, 21):   # physics off: members appear in erection order
    states.append(dict(name='off_%02d' % k, req=dict(req(BUILD, 150), reanalyze=False, physics=False, reveal=k / 20)))
for i, (nm, mem) in enumerate(STAGES):   # physics on: every erection stage solved live (CHS 114.3x4 as generated)
    load = round(150 * len(mem) / 20)
    states.append(dict(name='on_stage%d' % (i + 1), req=req(mem, load, title=T + '  ·  STAGE %d/4  %s' % (i + 1, nm))))
for L in (0, 25, 50, 75, 100, 125, 150):   # service load ramp on the complete frame
    states.append(dict(name='on_load%03d' % L, req=req(BUILD, max(L, 0.001), title=T + '  ·  SERVICE LOAD')))
for i, s in enumerate(SIZES):   # Almond iterates the section until the check passes
    states.append(dict(name='fix_%d' % i, req=req(BUILD, 150, s, title=T + '  ·  ITERATION %d/5  CHS %.1fx%.1f' % (i + 1, s[0], s[1]))))
for i, (nm, mem) in enumerate(STAGES):   # final design re-checked at every erection stage
    load = round(150 * len(mem) / 20)
    states.append(dict(name='ok_stage%d' % (i + 1), req=req(mem, load, FINAL, title=T + '  ·  STAGE %d/4  %s' % (i + 1, nm))))
states.append(dict(name='ok_final', req=req(BUILD, 150, FINAL, title=T + '  ·  CHS 193.7x8  ·  VERIFIED')))
json.dump(states, open(WORK + '/phys_states.json', 'w'), indent=1)
print(len(states), 'states,', sum(1 for s in states if s.get('capture', True)), 'captures')

# one request file per state (no JSON parsing needed inside Rhino): NN_name[__nocap].json
import os, glob
d = WORK + '/phys_req'
os.makedirs(d, exist_ok=True)
for f in glob.glob(d + '/*.json'): os.remove(f)
for i, s in enumerate(states):
    r = {'type': 'structure_view', 'clear': True} if s.get('clear') else s['req']
    json.dump(r, open('%s/%02d_%s%s.json' % (d, i, s['name'], '' if s.get('capture', True) else '__nocap'), 'w'))
