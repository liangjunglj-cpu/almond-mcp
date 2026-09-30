"""Atelier-07 mezzanine (bedroom wing) steel grillage as Rhino lines + support points; GUIDs -> frame_ids.json."""
import json
from bridge import run_cs
Z = 3085
XW, XM, XE = 6600, 9700, 12800
YS = [0, 2500, 5000, 7500, 10000]
segs = []   # (group, x1,y1,z1,x2,y2,z2) in build order
for i in range(4): segs.append(('edge', XW, YS[i], Z, XW, YS[i + 1], Z))                 # void-edge beam
for y in YS:
    segs.append(('joist' if 0 < y < 10000 else 'edge', XW, y, Z, XM, y, Z))
    segs.append(('joist' if 0 < y < 10000 else 'edge', XM, y, Z, XE, y, Z))
for i in range(4): segs.append(('stringer', XM, YS[i], Z, XM, YS[i + 1], Z))            # mid stringer
cols = [('column', XW, 0, 0, XW, 0, Z), ('column', XW, 5000, 0, XW, 5000, Z)]
wall = [(XE, y, Z) for y in YS] + [(XW, 10000, Z), (XM, 10000, Z)]
bases = [(XW, 0, 0), (XW, 5000, 0)]
L = lambda s: 'ids.Add(doc.Objects.AddLine(new Line(new Point3d(%d,%d,%d),new Point3d(%d,%d,%d)),a));' % s[1:]
P = lambda p: 'ids.Add(doc.Objects.AddPoint(new Point3d(%d,%d,%d),a));' % p
body = '''var ex = doc.Layers.FindName("A07 / 16 Structure"); int li = ex != null ? ex.Index : doc.Layers.Add("A07 / 16 Structure", Color.FromArgb(233, 68, 43)); foreach (var o in doc.Objects.FindByLayer(doc.Layers[li])) doc.Objects.Delete(o, true);
var a = new ObjectAttributes{LayerIndex=li}; var ids = new List<Guid>();
''' + '\n'.join(L(s) for s in segs + cols) + '\n' + '\n'.join(P(p) for p in wall + bases) + '''
doc.Views.Redraw(); log.Append(string.Join(",", ids));'''
ids = run_cs(body, quiet=True).strip().split(',')
n = len(segs)
out = {'beams': ids[:n], 'columns': ids[n:n + 2], 'wall': ids[n + 2:n + 2 + len(wall)], 'bases': ids[n + 2 + len(wall):],
       'groups': [s[0] for s in segs]}
json.dump(out, open(r'C:/Users/liang/Documents/almond_promo/frame_ids.json', 'w'), indent=1)
print({k: len(v) for k, v in out.items()})
