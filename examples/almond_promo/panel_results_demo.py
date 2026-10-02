"""Run a native analysis from the Structure workspace, open the Almond Results panel and screenshot it.

Needs Rhino with the mezzanine frame (mk_frame.py).
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bridge import run_cs                                                   # noqa: E402
import panel_demo                                                           # noqa: E402
from panel_native_demo import LAYER, form, click, wait_idle, scroll, shot, results, js   # noqa: E402

RESULTS_JS = r'''var p = Rhino.UI.Panels.GetPanel<RhinoAlmondBridge.AlmondResultsPanel>(doc);
var f = typeof(RhinoAlmondBridge.AlmondResultsPanel).GetField("_view", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
var v = p == null ? null : (Eto.Forms.WebView)f.GetValue(p); log.Append(v == null ? "no panel" : v.ExecuteScript(CODE));'''


def results_js(code):
    return run_cs(RESULTS_JS.replace("CODE", json.dumps(code)), quiet=True)


def main(connections="simple"):
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    run_cs('RhinoApp.RunScript("_AlmondStructure", false); log.Append("ok");', quiet=True)
    time.sleep(4)
    run_cs(LAYER.replace("VIS", "true"), quiet=True)
    ids = ",".join('new Guid("%s")' % g for g in panel_demo.GUIDS)
    run_cs('doc.Objects.UnselectAll(); foreach (var g in new[]{%s}) doc.Objects.Select(g, true); doc.Views.Redraw(); '
           'log.Append("sel");' % ids, quiet=True)
    js('document.getElementById("analysis-engine").value="native";'
       'document.getElementById("analysis-engine").dispatchEvent(new Event("change"));return "ok";')
    click("capture")
    print("capture:", wait_idle())
    run_cs(LAYER.replace("VIS", "false"), quiet=True)
    form(analysis_code="eurocode", analysis_load=0, floor_imposed=2.0, floor_dead=1.0, support_restraint="pinned",
         analysis_connections=connections, analysis_overlay="deflection", analysis_span=6.2, analysis_limit="",
         section_override=True, section_diameter=219.1, section_wall=8.0)
    click("analyze")
    print("analyze:", wait_idle())
    print(json.dumps(results(), ensure_ascii=False))
    scroll("#analysis-results h2")
    click("results")
    time.sleep(4)
    print("results page:", unquote(results_js(
        'return encodeURIComponent(document.getElementById("sum-count").textContent + " members; " + '
        'document.querySelectorAll("#members tbody tr").length + " rows")').strip()))
    shot("r_members")
    for tab in ("supports", "combinations", "loads"):
        results_js(f'document.getElementById("tab-{tab}").click(); return "ok";')
        time.sleep(0.8)
        shot(f"r_{tab}")
    results_js('document.getElementById("tab-members").click(); document.querySelector("[data-filter=fail]").click(); return "ok";')
    time.sleep(0.8)
    shot("r_fail_filter")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or []))
