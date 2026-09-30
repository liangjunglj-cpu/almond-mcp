"""Live screen recording of furnishing Atelier-07 from the Almond Library panel.

Each asset is found with the panel search, placed with the panel's Place button and a real
viewport pick (red preview box), then swapped for the final Atelier-07 instance of that same
library asset (its authored rotation + finish)."""
import json, subprocess, time
from pathlib import Path
from bridge import run_cs
from shot import rhino_front_top, topmost
import ui

WORK = Path(r"C:\Users\liang\Documents\almond_promo")
T = {a['id']: a for a in json.load(open(WORK / 'lib_targets.json'))}
by_asset = {}
for a in T.values():
    by_asset.setdefault(a['asset'], []).append(a)

SEARCH = (2260, 470)
PLACE_L, PLACE_R = (2142, 1215), (2375, 1215)
PARK = (1500, 1450)


def cs_swap(asset, show_ids, next_z, stagger_ms=0):
    ids = ','.join('new Guid("%s")' % i for i in show_ids)
    return run_cs(f'''
foreach(var d in doc.InstanceDefinitions.Where(d=>d!=null&&!d.IsDeleted&&d.Name.StartsWith("Almond::{asset}::")).ToList())
 foreach(var r in d.GetReferences(0))doc.Objects.Delete(r.Id,true);
var show=new Guid[]{{{ids}}};
foreach(var g in show){{doc.Objects.Show(g,true);if({stagger_ms}>0){{doc.Views.ActiveView.Redraw();RhinoApp.Wait();System.Threading.Thread.Sleep({stagger_ms});}}}}
doc.Objects.UnselectAll();
var vp=doc.Views.ActiveView.ActiveViewport;vp.SetConstructionPlane(new Plane(new Point3d(0,0,{next_z}),Vector3d.ZAxis));
doc.Views.Redraw();log.Append("ok");''', quiet=True)


def cs_cplane(z):
    run_cs(f'var vp=doc.Views.ActiveView.ActiveViewport;vp.SetConstructionPlane(new Plane(new Point3d(0,0,{z}),Vector3d.ZAxis));log.Append("ok");', quiet=True)


def search(q):
    ui.click(*SEARCH, dur=0.55)
    time.sleep(0.15)
    ui.hotkey(ui.VK_CONTROL, ui.VK_A); ui.hotkey(ui.VK_BACK)
    ui.type_text(q, cps=12)
    time.sleep(0.9)


def place(button, target, glide=1.3):
    ui.click(*button, dur=0.5)
    time.sleep(0.35)
    # enter the viewport, then glide the red preview box to the drop point
    tx, ty = target
    ui.move_to(tx - 260, ty - 180, 0.5)
    ui.move_to(tx + 40, ty + 25, glide * 0.7)
    ui.move_to(tx, ty, glide * 0.3)
    time.sleep(0.35)
    ui.click()
    time.sleep(1.2)


# (query, button, asset, instance id to show, extra instances, cplane z for the drop)
SEQ = [
    ("sofa", PLACE_L, 'gen-sofa-3-seat-1', 'c0ce6a95-fe48-4b15-828a-760c12c2a1f0', [], 37),
    ("throw", PLACE_L, 'gen-folded-throw-1', 'c2b7d48d-7fd4-4ecc-a305-bc31ab4c277c', [], 620),
    ("armchair", PLACE_L, 'gen-armchair-bent-birch-webbed-1', '9f4b7de4-3016-4e95-ad92-15522ac236cd', [], 37),
    ("leather", PLACE_L, 'gen-lounge-chair-leather-plywood-1', 'f2824952-6885-4866-847f-03145aed8dc5', [], 37),
    (None, PLACE_R, 'gen-ottoman-leather-plywood-1', 'aae46db9-3f41-424f-acbf-7600d91ca615', [], 37),
    ("dining chair", PLACE_L, 'gen-dining-chair-1', 'd5cc2b4e-48d2-49e1-80ae-c8378b6c1d16',
     ['ec1a8a10-c0f7-46c6-a892-30a6fc6622b7', '3c822d33-c000-40e3-8496-51c6f62cdff8',
      '22fd3b19-4cbe-41a2-bd7f-42f90d753d4e', 'f17ff02c-f323-4e2d-bb46-f76d5f83a0f4',
      '752e62df-9a7c-4f06-a938-cfde242ec8d4'], 24),
]
BURST = ['gen-pendant-lamp-sphere-1', 'gen-bed-double-1', 'gen-folded-throw-1', 'gen-task-chair-mesh-ergonomic-1',
         'gen-task-lamp-balanced-arm-1', 'gen-bathtub-1', 'gen-toilet-1', 'gen-tea-trolley-bent-birch-1', 'gen-bicycle-1']

if __name__ == '__main__':
    out = WORK / 'lib_rec.mp4'
    cs_cplane(SEQ[0][5])
    h = rhino_front_top(park=PARK)
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'ddagrab=framerate=30:draw_mouse=1,hwdownload,format=bgra', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '14', '-pix_fmt', 'yuv420p', str(out)],
                          stdin=subprocess.PIPE)
    marks = {}
    t0 = time.time()
    try:
        time.sleep(1.5)
        for i, (q, btn, asset, iid, extra, z) in enumerate(SEQ):
            marks[asset + '_start'] = time.time() - t0
            if q:
                search(q)
            place(btn, (T[iid]['sx'], T[iid]['sy']))
            marks[asset + '_drop'] = time.time() - t0
            nz = SEQ[i + 1][5] if i + 1 < len(SEQ) else 0
            cs_swap(asset, [iid], nz)
            if extra:
                time.sleep(0.5)
                cs_swap(asset, extra, nz, stagger_ms=180)
            ui.move_to(*PARK, 0.4)
            time.sleep(0.6)
        # the rest of the library pieces in this apartment
        search("")
        marks['burst'] = time.time() - t0
        rest = [a['id'] for k in BURST for a in by_asset[k]
                if not (k == 'gen-folded-throw-1' and a['id'] == 'c2b7d48d-7fd4-4ecc-a305-bc31ab4c277c')]
        cs_swap('none', rest, 0, stagger_ms=260)
        ui.move_to(*PARK, 0.4)
        time.sleep(2.5)
    finally:
        ff.stdin.write(b'q'); ff.stdin.flush(); ff.wait(30)
        topmost(h, False)
        (WORK / 'lib_marks.json').write_text(json.dumps(marks, indent=1))
    print(marks)
