"""MCP tools and resources for the parametric (Grasshopper) teaching library."""
import asyncio
import json
import shutil
from pathlib import Path

import pytest

from almond_mcp import paths
from almond_mcp.parametric_library import ParametricLibrary, open_in_grasshopper_script
from tests.test_capsules import BridgeMock, _call, _load_server

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "ParametricLibrary"
pytestmark = pytest.mark.skipif(not LIBRARY.is_dir(), reason="ParametricLibrary not in this checkout")


@pytest.fixture
def server(monkeypatch, tmp_path):
    cap = tmp_path / "capsules"
    cap.mkdir()
    monkeypatch.setenv("RHINO_MCP_PARAMETRIC_DIR", str(LIBRARY))
    return _load_server(monkeypatch, tmp_path, cap)


def test_paths_resolve_parametric_library_like_other_libraries(monkeypatch):
    monkeypatch.delenv("RHINO_MCP_PARAMETRIC_DIR", raising=False)
    assert Path(paths.resolve_dir("RHINO_MCP_PARAMETRIC_DIR")) == LIBRARY
    assert "ParametricLibrary" in paths.VERSIONED_LIBRARIES


def test_list_filters_and_searches(server):
    everything = _call(server.list_parametric_definitions)
    assert everything["status"] == "success" and everything["total"] == 10
    facades = _call(server.list_parametric_definitions, category="facade")
    assert facades["total"] == 5 and all(c["category"] == "facade" for c in facades["definitions"])
    hits = _call(server.list_parametric_definitions, query="attractor")
    assert hits["definitions"][0]["id"] in {"facade-attractor-perforation", "landscape-paving-patterns"}
    assert {"facade-attractor-perforation", "landscape-paving-patterns"} <= {c["id"] for c in hits["definitions"]}
    assert _call(server.list_parametric_definitions, query="zzzz-nothing")["total"] == 0
    beginner = _call(server.list_parametric_definitions, level="beginner")
    assert all(c["level"] == "beginner" for c in beginner["definitions"])


def test_get_definition_returns_lesson_path_and_rights(server):
    d = _call(server.get_parametric_definition, definition_id="structure-shell-roof-ribs")
    assert d["status"] == "success"
    assert Path(d["definition_path"]).is_file() and Path(d["rights"]["licence_file"]).is_file()
    assert d["rights"]["licence"] == "BlueOak-1.0.0" and d["source"]["commit"].startswith("0e57586b")
    assert d["steps"][0]["title"].startswith("1") and all(s["explain"] for s in d["steps"])
    assert d["how_to_use"] and d["concepts"]
    voronoi = _call(server.get_parametric_definition, definition_id="facade-voronoi-screen")
    assert voronoi["value_overrides"] and voronoi["scripts"]
    assert _call(server.get_parametric_definition, definition_id="nope")["status"] == "error"


def test_tampered_definition_is_refused(tmp_path):
    copy = tmp_path / "ParametricLibrary"
    shutil.copytree(LIBRARY, copy, ignore=shutil.ignore_patterns("upstream"))
    target = copy / "definitions" / "massing-twisting-polygon-tower.ghx"
    target.write_bytes(target.read_bytes().replace(b"Twisting polygon tower", b"Twisting polygon tower!", 1))
    lib = ParametricLibrary(copy)
    with pytest.raises(ValueError, match="differs from the source register"):
        lib.verify("massing-twisting-polygon-tower")
    assert lib.verify("structure-shell-roof-ribs").is_file()


def test_open_sends_grasshopper_open_for_verified_file(server, monkeypatch):
    mock = BridgeMock(json.dumps({"status": "success", "guids": []}))
    monkeypatch.setattr(server, "_send_and_receive", mock)
    result = _call(server.open_parametric_definition, definition_id="facade-diagrid-on-surface")
    assert result["status"] == "success"
    (payload, _), = mock.payloads
    assert payload["type"] == "execute"
    expected = str(LIBRARY / "definitions" / "facade-diagrid-on-surface.ghx").replace("\\", "\\\\")
    assert expected in payload["script"]
    assert "_-Grasshopper _Document _Open" in payload["script"]
    assert _call(server.open_parametric_definition, definition_id="../../etc")["status"] == "error"
    assert len(mock.payloads) == 1


def test_open_reports_bridge_failure(server, monkeypatch):
    def refuse(payload, timeout=60.0):
        raise ConnectionRefusedError

    monkeypatch.setattr(server, "_send_and_receive", refuse)
    result = _call(server.open_parametric_definition, definition_id="facade-diagrid-on-surface")
    assert result["status"] == "error" and "definition_path" in result


def test_open_script_escapes_paths():
    script = open_in_grasshopper_script(Path('C:/Users/a "b"/lib/x.ghx'))
    assert '\\"b\\"' in script and "File.Exists" in script


def test_mcp_resources(server):
    from fastmcp import Client

    async def check():
        async with Client(server.mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
            assert tools["list_parametric_definitions"].annotations.readOnlyHint
            assert not tools["open_parametric_definition"].annotations.destructiveHint
            catalogue = await client.read_resource("almond://parametric/catalogue")
            assert json.loads(catalogue[0].text)["total"] == 10
            preview = await client.read_resource("almond://parametric/facade-louvre-rotation/preview")
            assert preview[0].mimeType == "image/png"
            lesson = await client.read_resource("almond://parametric/facade-louvre-rotation/lesson")
            assert json.loads(lesson[0].text)["title"] == "Louvres rotated by length"
    asyncio.run(check())


# -- harnessed capsules in the capsule registry --------------------------------

CAPSULE = "parametric_shell_roof_ribs_v1"
PORTS = {"ALMOND_IN_BASE_SRF", "ALMOND_IN_RIBS_U", "ALMOND_IN_RIBS_V", "ALMOND_IN_RIB_DEPTH", "ALMOND_IN_BRACE_RADIUS"}


def test_library_capsule_is_registered_but_refused_until_audited(server, monkeypatch):
    assert server.capsule_sync_report["skipped"] == []
    listing = json.loads(_call(server.list_capsules, capability="generate"))
    assert CAPSULE in {c["capsule_id"] for c in listing["capsules"]}
    audited = json.loads(_call(server.list_capsules, audited_only=True))
    assert CAPSULE not in {c["capsule_id"] for c in audited["capsules"]}

    detail = _call(server.get_parametric_definition, definition_id="structure-shell-roof-ribs")
    cap = detail["capsule"]
    assert cap["capsule_id"] == CAPSULE and cap["capability"] == "generate"
    assert cap["audited"] is False and cap["runnable"] is False and cap["integrity"].startswith("verified")
    assert {p["name"] for p in cap["inputs"]} == PORTS
    assert all(p["type"].startswith(("curve", "brep")) for p in cap["outputs"])
    assert Path(cap["definition_path"]).is_file() and Path(cap["manifest_path"]).is_file()
    assert "harness.audited" in cap["how_to_run"] and cap["audit_note"]
    assert _call(server.get_parametric_definition, definition_id="facade-louvre-rotation")["capsule"] is None
    cards = {c["id"]: c for c in _call(server.list_parametric_definitions, category="structure")["definitions"]}
    assert cards["structure-shell-roof-ribs"]["capsule_id"] == CAPSULE
    assert cards["structure-shell-roof-ribs"]["capsule_audited"] is False

    def _no_bridge(*_a, **_k):
        raise AssertionError("the bridge must not be contacted for an unaudited capsule")
    monkeypatch.setattr(server, "_send_and_receive", _no_bridge)
    result = json.loads(_call(server.run_gh_definition, capsule_id=CAPSULE, inputs={"ALMOND_IN_RIBS_U": 10}))
    assert result["status"] == "error" and "not audited" in result["message"] and "Audit note" in result["message"]


def test_tampered_harnessed_capsule_is_skipped(monkeypatch, tmp_path):
    copy = tmp_path / "ParametricLibrary"
    shutil.copytree(LIBRARY, copy, ignore=shutil.ignore_patterns("upstream"))
    target = copy / "capsules" / "structure-shell-roof-ribs.harnessed.ghx"
    import re
    text = target.read_text(encoding="utf-8")
    # change the rib depth default stored on the ALMOND_IN_RIB_DEPTH harness param
    pattern = re.compile(r'(>ALMOND_IN_RIB_DEPTH</item>.*?<item name="number"[^>]*>)([^<]+)(</item>)', re.DOTALL)
    tampered, count = pattern.subn(lambda m: m.group(1) + str(float(m.group(2)) * 10) + m.group(3), text, count=1)
    assert count == 1
    target.write_text(tampered, encoding="utf-8")
    monkeypatch.setenv("RHINO_MCP_PARAMETRIC_DIR", str(copy))
    cap = tmp_path / "capsules"
    cap.mkdir()
    server = _load_server(monkeypatch, tmp_path, cap)
    errors = [e for s in server.capsule_sync_report["skipped"] for e in s["errors"]]
    assert any("differs from the source register" in e for e in errors)
    assert CAPSULE not in {c["capsule_id"] for c in json.loads(_call(server.list_capsules))["capsules"]}
    detail = _call(server.get_parametric_definition, definition_id="structure-shell-roof-ribs")
    assert detail["capsule"]["integrity"].startswith("FAILED") and detail["capsule"]["runnable"] is False
    # the teaching definition itself is untouched and still served
    assert detail["status"] == "success" and Path(detail["definition_path"]).is_file()
