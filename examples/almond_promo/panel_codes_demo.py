"""The same frame under different design code profiles, run through the Almond panel (native engine).

Needs Rhino with the mezzanine frame (mk_frame.py); a profile folder with extra profiles can be passed
to Rhino through ALMOND_DESIGN_CODE_DIR when redeploying.
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bridge import run_cs                                      # noqa: E402
import panel_demo                                              # noqa: E402
from panel_native_demo import LAYER, form, click, wait_idle, scroll, shot, results, js   # noqa: E402


def options(select_id):
    return json.loads(unquote(js(f'return encodeURIComponent(JSON.stringify([...document.getElementById("{select_id}")'
                                 '.options].map(o=>[o.value,o.textContent,o.disabled])))').strip()))


def text(element_id):
    return unquote(js(f'return encodeURIComponent(document.getElementById("{element_id}").textContent)').strip())


def main():
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    panel_demo.run_cs('RhinoApp.RunScript("_AlmondStructure", false); log.Append("ok");', quiet=True)
    time.sleep(4)                                                         # first visit: engine check + profiles
    run_cs(LAYER.replace("VIS", "true"), quiet=True)
    ids = ",".join('new Guid("%s")' % g for g in panel_demo.GUIDS)
    run_cs('doc.Objects.UnselectAll(); foreach (var g in new[]{%s}) doc.Objects.Select(g, true); doc.Views.Redraw(); '
           'log.Append("sel");' % ids, quiet=True)
    js('document.getElementById("analysis-engine").value="native";'
       'document.getElementById("analysis-engine").dispatchEvent(new Event("change"));return "ok";')
    click("capture")
    print("capture:", wait_idle())
    run_cs(LAYER.replace("VIS", "false"), quiet=True)
    print("codes:", options("analysis-code"))
    form(analysis_load=0, floor_imposed=2.0, floor_dead=1.0, support_restraint="pinned",
         analysis_connections="rigid", analysis_overlay="deflection", analysis_span=6.2, analysis_limit="",
         section_override=True, section_diameter=219.1, section_wall=8.0)
    rows = []
    for code in ("eurocode", "demo-na", "off"):
        form(analysis_code=code)
        note = text("code-note")
        uls = options("analysis-uls")
        if code == "demo-na":
            scroll("#analysis-settings h2")
            shot("c_setup_demo")
        click("analyze")
        msg = wait_idle()
        r = results()
        r.update(code=code, note=note, uls=uls[0][1], uls_locked=uls[0][2] or None, message=msg)
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        scroll("#analysis-results h2")
        shot(f"c_{code}")
    (Path(r"C:\Users\liang\Documents\almond_promo\ui") / "panel_codes.json").write_text(
        json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
