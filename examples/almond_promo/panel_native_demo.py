"""Drive the Almond panel's Structural Validation workspace with the native engine and screenshot each step.

Form values and buttons are set through the panel's own controls (panel_demo.js), so every action goes
through the real panel -> bridge -> `almond-mcp solve` -> overlay path. Run with Rhino open, the
mezzanine frame built (mk_frame.py) and selected (panel_demo.py prep).
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bridge import run_cs                      # noqa: E402
import panel_demo                              # noqa: E402
from panel_demo import js                      # noqa: E402

LAYER = r'''var l = doc.Layers.FindName("A07 / 16 Structure"); if (l != null) { l.IsVisible = VIS; l.CommitChanges(); } doc.Views.Redraw(); log.Append("ok");'''


def form(**values):
    """Set inputs by id (checkboxes take booleans) and fire the form's input event."""
    code = []
    for key, v in values.items():
        k = key.replace("_", "-")
        if isinstance(v, bool):
            code.append(f'document.getElementById("{k}").checked={str(v).lower()};')
        else:
            code.append(f'document.getElementById("{k}").value={json.dumps(str(v))};')
        code.append(f'document.getElementById("{k}").dispatchEvent(new Event("input",{{bubbles:true}}));'
                    f'document.getElementById("{k}").dispatchEvent(new Event("change",{{bubbles:true}}));')
    js("".join(code) + 'return "set";')


def click(action):
    js(f'document.querySelector(\'[data-analysis="{action}"]\').click();return "clicked";')


def wait_idle(timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        time.sleep(1.0)
        if js('return String(!document.getElementById("analysis-run").disabled)').strip() == "true":
            return unquote(js('return encodeURIComponent(document.getElementById("analysis-message").textContent)').strip())
    raise TimeoutError("panel still busy")


def scroll(selector):
    js(f'document.querySelector({json.dumps(selector)}).scrollIntoView({{block:"start"}});return "ok";')
    time.sleep(0.6)


def shot(name):
    panel_demo.step(name, wait=0.8)
    panel_demo.topmost(False)


def results():
    return json.loads(unquote(js('return encodeURIComponent(JSON.stringify({outcome:document.getElementById("analysis-outcome").textContent,'
                         'method:document.getElementById("analysis-method").textContent,'
                         'd:document.getElementById("deflection-value").textContent,'
                         'u:document.getElementById("utilization-value").textContent,'
                         's:document.getElementById("stability-value").textContent,'
                         'facts:[...document.querySelectorAll("#native-facts li")].map(n=>n.textContent)}))').strip()))


def main():
    run_cs((HERE / "rhino_setup_view.cs").read_text(encoding="utf-8").replace("LENS", "42"), quiet=True)
    js('document.getElementById("analysis-engine").value="native";'
       'document.getElementById("analysis-engine").dispatchEvent(new Event("change"));return "ok";')
    run_cs(LAYER.replace("VIS", "true"), quiet=True)            # hidden objects cannot be selected
    ids = ",".join('new Guid("%s")' % g for g in panel_demo.GUIDS)
    run_cs('doc.Objects.UnselectAll(); foreach (var g in new[]{%s}) doc.Objects.Select(g, true); doc.Views.Redraw(); '
           'log.Append(doc.Objects.GetSelectedObjects(false, false).Count());' % ids, quiet=True)
    click("capture")
    print("capture:", wait_idle())
    run_cs(LAYER.replace("VIS", "false"), quiet=True)          # the overlay replaces the drawn axes
    form(analysis_load=0, floor_imposed=2.0, floor_dead=1.0, support_restraint="pinned",
         analysis_connections="rigid", analysis_overlay="deflection", analysis_span=6.2,
         section_override=True, section_diameter=219.1, section_wall=8.0)
    scroll("#analysis-settings h2")
    shot("n1_setup")
    rows = []
    for name, extra in (("n2_rigid", {}), ("n3_simple", {"analysis_connections": "simple"}),
                        ("n4_simple_244", {"section_diameter": 244.5, "section_wall": 10.0}),
                        ("n5_buckling", {"analysis_overlay": "buckling"})):
        if extra:
            form(**extra)
        click("analyze")
        msg = wait_idle()
        r = results()
        r.update(name=name, message=msg)
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        scroll("#analysis-results h2")
        shot(name)
    (Path(r"C:\Users\liang\Documents\almond_promo\ui") / "panel_native.json").write_text(
        json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
