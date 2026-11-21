"""Simulation features in beta: every environment tool says (BETA), the panel says so too, and since 0.8.0
the native structural engine is stable while its Karamba route keeps (BETA); the panel's hierarchy keeps
every control its scripts use, and the tutorial model places what each analysis needs
(checked by running the real engines on exactly what it places)."""
from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path

import pytest

from almond_mcp import native_structure as ns, tutorial
from almond_mcp.environment import panel, studies, thermal
from tests.env_weather import synthetic_weather
from tests.test_capsules import BridgeMock, _call, _load_server

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "almond_mcp" / "library_ui"
BRIDGE = ROOT / "RhinoAlmondBridge"
STRUCTURE_TOOLS = {"validate_structure", "visualize_structure", "export_structural_report", "list_design_codes"}


@pytest.fixture(autouse=True)
def _runs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv(studies.RUNS_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


@pytest.fixture()
def server(monkeypatch, tmp_path):
    caps = tmp_path / "capsules"
    caps.mkdir()
    return _load_server(monkeypatch, tmp_path, caps)


def _descriptions(server) -> dict[str, str]:
    return {t.name: t.description or "" for t in asyncio.run(server.mcp.list_tools())}


def test_every_environment_tool_is_labelled_beta_and_the_native_structure_tools_are_not(server):
    tools = _descriptions(server)
    environment = _env_tool_names(server)
    assert "place_simulation_tutorial" in environment and len(environment) >= 19
    for name in environment:
        assert tools[name].lstrip().startswith("(BETA)"), name
    # 0.8.0: the native structural engine is stable; only its Karamba route stays in beta
    for name in STRUCTURE_TOOLS:
        assert not tools[name].lstrip().startswith("(BETA)"), name
    for name in ("validate_structure", "visualize_structure"):
        assert "(BETA)" in tools[name] and "karamba" in tools[name].lower(), name
    # the library and drawing tools are not labelled
    for name in ("list_library", "place_generated_asset", "get_asset_drawing"):
        assert "(BETA)" not in tools[name]
    assert "(BETA)" in server.mcp.instructions and "native structural engine" in server.mcp.instructions


def _env_tool_names(_server=None) -> set[str]:
    src = (ROOT / "almond_mcp" / "environment_tools.py").read_text(encoding="utf-8")
    return set(re.findall(r"@mcp\.tool\([^)]*\)\s*\n\s*def (\w+)\(", src))


def test_panel_and_plugin_say_beta():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert re.search(re.escape("Climate, Rooms <br>&amp; Comfort") +
                     r'<span class="red">\.</span> <span class="beta-tag"[^>]*>\(BETA\)</span></h1>', html)
    assert re.search(re.escape("Structural <br>Validation") + r'<span class="red">\.</span></h1>', html)
    assert html.count('class="beta-tag"') == 2                     # the environment heading and home card
    assert "Karamba3D · separate licence (BETA)" in html           # the Karamba route stays in beta
    assert "(BETA)" not in (UI / "results.html").read_text(encoding="utf-8")
    assert '"Almond Results"' in (BRIDGE / "RhinoAlmondBridgePlugin.cs").read_text(encoding="utf-8")
    assert "(BETA)" in (BRIDGE / "EnvironmentWorkspace.cs").read_text(encoding="utf-8")
    commands = (BRIDGE / "LibraryCommands.cs").read_text(encoding="utf-8")
    assert "Structural Validation (BETA)" not in commands and "Karamba engine is (BETA)" in commands
    view = (BRIDGE / "StructureView.cs").read_text(encoding="utf-8")
    assert 'Data.Engine != "native"' in view and '"(BETA)  " + title' in view   # only the Karamba legend


def _ids(html: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html))


@pytest.mark.parametrize("script", ["environment.js", "karamba.js"])
def test_hierarchy_keeps_every_control_the_scripts_use(script):
    """Advanced options moved into collapsed sections: every element the scripts address must still exist."""
    html = (UI / "index.html").read_text(encoding="utf-8")
    src = (UI / script).read_text(encoding="utf-8")
    used = set(re.findall(r"\bel\('([a-z0-9-]+)'\)", src))
    missing = {i for i in used if i not in _ids(html)}
    assert not missing, missing


def _collapsed_ids(html: str) -> tuple[set[str], int]:
    """Ids inside a collapsed ("advanced") section, nested sections included, and the number of sections."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.ids, self.sections = [], set(), 0

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "details":
                advanced = "advanced" in (a.get("class") or "").split()
                assert not (advanced and "open" in a), "an advanced section must start collapsed"
                self.stack.append(advanced)
                self.sections += advanced
            if a.get("id") and any(self.stack):
                self.ids.add(a["id"])

        def handle_endtag(self, tag):
            if tag == "details":
                self.stack.pop()

    p = P()
    p.feed(html)
    return p.ids, p.sections


def test_advanced_options_are_collapsed_and_primary_ones_are_not():
    html = (UI / "index.html").read_text(encoding="utf-8")
    hidden, sections = _collapsed_ids(html)
    assert sections >= 14
    for advanced in ("env-preset", "env-nv", "env-hr", "env-blinds", "env-pack", "env-quality", "env-spacing", "env-room-set",
                     "env-room-heat", "analysis-uls", "analysis-stability", "analysis-fabrication", "analysis-connections",
                     "floor-imposed", "section-override",
                     # the coursework (#45) and lighting (#47) controls: all behind a collapsed section
                     "env-shade-on", "env-csv", "env-people", "env-vent-person", "env-heat", "env-heat-back", "env-m-heat-0",
                     "env-pmv-met", "env-light-mode", "env-light-lux", "env-view-h", "env-sl-alt", "env-sun-times"):
        assert advanced in hidden, advanced
    for primary in ("env-room-name", "env-room-use", "env-study", "env-cooling", "analysis-type", "analysis-material",
                    "analysis-load", "self-weight", "support-restraint", "analysis-code", "analysis-run", "env-run",
                    "env-case-name", "env-compare-room"):
        assert f'id="{primary}"' in html and primary not in hidden, primary


def test_panel_takes_rhino_colours_not_the_brand_palette():
    css = (UI / "panel.css").read_text(encoding="utf-8")
    assert "#e94329" not in css.lower()
    assert ".rhino-panel .env-strip{display:none}" in css           # the beige stepper gives way to Rhino-style tabs
    theme = (UI / "panel-theme.js").read_text(encoding="utf-8")
    assert "red:palette.accent" in theme
    host = (BRIDGE / "LibraryPanel.cs").read_text(encoding="utf-8")
    assert "accent = colour(PaintColor.PressedEnd)" in host and "InactiveTabBackground" in host
    env_css = (UI / "environment.css").read_text(encoding="utf-8")
    assert ".rhino-panel .env-page{--sheet:#ffffff}" in env_css


# --- tutorial model ---------------------------------------------------------------------------------

def test_tutorial_script_places_every_part_on_its_own_layers():
    cs = tutorial.script("all")
    assert "public static List<Guid> Run(RhinoDoc doc)" in cs and "__" not in cs.replace("__ROOT__", "")
    assert 'Clear("Almond Tutorial::Environment")' in cs and 'Clear("Almond Tutorial::Structure")' in cs
    assert '"room", "Tutorial Studio"' in cs and '"construction", "win_triple_lowe_ar_timber"' in cs
    assert '"room_height", "3"' in cs and "AddTextDot" in cs and "if (true)" in cs     # beside the model by default
    for part in tutorial.spec("all").values():
        notes = next(x["text"] for x in part["texts"] if x.get("top"))
        assert json.dumps(notes) in cs and "TextVerticalAlignment.Top" in cs
        for dot in part["dots"]:
            assert json.dumps(dot["label"]) in cs and "\n" not in dot["label"] and dot["text"] in notes
    env_only = tutorial.script("environment", (0, 0, 0))
    assert "Structure" not in env_only.split("public static List<Guid> Run")[1].split("doc.Views.Redraw")[0].replace("Almond simulation", "")
    assert "if (false)" in env_only
    with pytest.raises(ValueError):
        tutorial.spec("acoustics")


def test_tutorial_rooms_are_what_the_engine_expects():
    data = tutorial.export_like("environment")
    rooms, encs, _scene, notes = studies.prepare_rooms(data)
    states = {r.name: (r.use, e.state) for r, e in zip(rooms, encs)}
    assert states == {tutorial.ENV_ROOM: ("living", "enclosed"), tutorial.ENV_LOGGIA: ("outdoor", "open")}
    assert any("semi-outdoor" in n for n in notes)
    df = studies.run_rooms_daylight(data, None, "daylight_factor", "draft", "tutorial", 0.5)
    by_room = {r["room"]: r["average_df_pct"] for r in df["rooms"]}
    assert 1.0 < by_room[tutorial.ENV_ROOM] < 10.0               # the window lets light in


def test_tutorial_thermal_uses_its_window_construction():
    data = tutorial.export_like("environment")
    res = studies.run_rooms_thermal(data, synthetic_weather(), thermal.Settings(), "tutorial", {"epw_path": "synthetic"})
    studio = next(r for r in res["rooms"] if r["room"] == tutorial.ENV_ROOM)
    assert studio["method"] == "5R1C" and studio["thermal"]["areas_m2"]["window"] == pytest.approx(5.4)
    windows = [c for c in studio["thermal"]["constructions"] if c["surface"] == "window"]
    assert windows and windows[0]["construction"] == "win_triple_lowe_ar_timber"
    loggia = next(r for r in res["rooms"] if r["room"] == tutorial.ENV_LOGGIA)
    assert loggia["method"] == "semi_outdoor"


def test_tutorial_frame_passes_with_its_sections_and_fails_without():
    """The panel defaults (10 kN total) plus the 2.0 + 1.0 kN/m2 floor load the dots suggest: the frame's
    almond:section sizes pass, the default CHS 114.3 x 4 fails (as a live Rhino run showed: 72 mm, 303 %)."""
    loads = {"imposed": 2.0, "dead": 1.0}
    out = ns.validate(tutorial.structure_model(), "frame", 10.0, "Steel", True, True, floor_loads=loads)
    assert out["status"] == "pass", out.get("verdict")
    bare = tutorial.structure_model()
    for m in bare["members"]:
        m.pop("section")
    weak = ns.validate(bare, "frame", 10.0, "Steel", True, True, floor_loads=loads)
    assert weak["status"] == "fail" and weak["results"]["max_deflection_mm"] > 50
    assert '"section", "box 100x200x6"' in tutorial.script("structure")


def test_panel_engine_builds_the_tutorial_script():
    out = io.StringIO()
    panel.main(io.StringIO(json.dumps({"action": "tutorial_script", "part": "structure"})), out)
    reply = json.loads(out.getvalue())
    assert reply["status"] == "ok" and "Almond Tutorial::Structure" in reply["script"]
    assert set(reply["requirements"]) >= {"thermal", "daylight_factor", "structure"}
    host = (BRIDGE / "LibraryPanel.cs").read_text(encoding="utf-8")
    assert re.search(r"environment/\([^)]*\|tutorial\)", host)      # the panel's allow-list passes the action
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'data-tutorial="environment"' in html and 'data-tutorial="structure"' in html


def test_place_simulation_tutorial_tool(server, monkeypatch):
    bridge = BridgeMock(json.dumps({"status": "success", "guids": ["a", "b", "c"]}))
    monkeypatch.setattr(server, "_send_and_receive", bridge)
    out = _call(server.place_simulation_tutorial, part="environment", origin=[100, 0, 0])
    assert out["status"] == "success" and out["objects"] == 3 and out["rooms"] == [tutorial.ENV_ROOM, tutorial.ENV_LOGGIA]
    sent = bridge.payloads[0][0]
    assert sent["type"] == "execute" and "new Vector3d(100.0 * S" in sent["script"]
    assert _call(server.place_simulation_tutorial, part="all", origin=[1, 2])["status"] == "error"
    assert _call(server.place_simulation_tutorial, part="acoustics")["status"] == "error"


# --- structural tools that had no test of their own ---------------------------------------------------

def test_list_design_codes_and_structural_report(server, tmp_path, monkeypatch):
    from tests.test_validate_engines import PORTAL
    codes = json.loads(_call(server.list_design_codes))
    assert any(p.get("id") == "eurocode" or p.get("name") == "eurocode" for p in codes.get("profiles", codes.get("codes", [])))
    empty = json.loads(_call(server.export_structural_report, path=str(tmp_path / "none.md")))
    assert empty["status"] == "error" and "validate_structure" in empty["message"]
    monkeypatch.setattr(server, "_send_and_receive", lambda payload, timeout=60.0: json.dumps(PORTAL))
    json.loads(server.validate_structure(guids=["c1", "c2", "b"], structure_type="frame", load_kn=10))
    report = json.loads(_call(server.export_structural_report, path=str(tmp_path / "report.md")))
    assert report.get("status") in ("success", "ok") and Path(report["path"]).is_file()
    assert "NATIVE" in Path(report["path"]).read_text(encoding="utf-8").upper()
