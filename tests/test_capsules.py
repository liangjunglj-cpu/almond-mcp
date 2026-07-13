"""Capsule MCP surface tests.

No Rhino required: the bridge socket helper (server._send_and_receive) is
monkeypatched, the state database is a per-test temporary sqlite file, and the
capsule library is a per-test temporary directory (plus one read-only pass over
the real capsules/ directory).
"""
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_ROOT / "almond_mcp" / "server.py"
REAL_CAPSULE_DIR = PROJECT_ROOT / "capsules"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


AUDITED_MANIFEST = {
    "capsule_id": "test_beam_v1",
    "version": 1,
    "capability": "analyze",
    "structure_type": "beam",
    "plugin_dependencies": [{"name": "Karamba3D", "min_version": "3.1"}],
    "definition_file": "TestBeam.ghx",
    "title": "Test beam capsule",
    "description_for_llm": "Test-only audited capsule.",
    "inputs": [
        {"name": "ALMOND_IN_LINES", "type": "curve[]", "units": "m", "required": True},
        {"name": "ALMOND_IN_LOAD_KN", "type": "number", "units": "kN",
         "required": False, "default": 10.0},
        {"name": "ALMOND_IN_COUNT", "type": "integer", "required": False},
        {"name": "ALMOND_IN_NAMES", "type": "string[]", "required": False},
    ],
    "outputs": [
        {"name": "ALMOND_OUT_DISP_MM", "type": "number", "units": "mm",
         "semantics": "max_nodal_displacement"},
        {"name": "ALMOND_OUT_UTIL", "type": "number[]",
         "semantics": "per_element_utilization"},
    ],
    "binding": "reserved_nicknames",
    "confidence": "template",
    "audited": True,
}

UNAUDITED_MANIFEST = {
    "capsule_id": "test_unaudited_v1",
    "version": 1,
    "capability": "generate",
    "definition_file": "TestUnaudited.ghx",
    "title": "Test unaudited capsule",
    "inputs": [
        {"name": "ALMOND_IN_SEED_PTS", "type": "point[]", "required": True},
    ],
    "outputs": [
        {"name": "ALMOND_OUT_COUNT", "type": "integer", "semantics": "part_count"},
    ],
    "binding": "reserved_nicknames",
    "confidence": "template",
    "audited": False,
}


def _load_server(monkeypatch, tmp_path, capsule_dir):
    monkeypatch.setenv("RHINO_MCP_STATE_DB", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("RHINO_MCP_CAPSULE_DIR", str(capsule_dir))
    spec = importlib.util.spec_from_file_location(
        f"almond_server_capsules_{uuid.uuid4().hex}", SERVER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call(tool, **kwargs):
    """Invoke an MCP tool's underlying function regardless of fastmcp version."""
    fn = getattr(tool, "fn", tool)
    return fn(**kwargs)


class BridgeMock:
    """Captures payloads sent to the bridge and returns a canned response."""

    def __init__(self, response: str):
        self.response = response
        self.payloads: list[tuple[dict, float]] = []

    def __call__(self, payload_bytes: bytes, timeout: float = 60.0) -> str:
        self.payloads.append((json.loads(payload_bytes.decode("utf-8")), timeout))
        return self.response


def _forbid_bridge(server, monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("The bridge must not be contacted for invalid requests.")
    monkeypatch.setattr(server, "_send_and_receive", _fail)


@pytest.fixture()
def capsule_dir(tmp_path):
    directory = tmp_path / "capsules"
    directory.mkdir()
    (directory / "test_beam_v1.capsule.json").write_text(
        json.dumps(AUDITED_MANIFEST), encoding="utf-8"
    )
    (directory / "test_unaudited_v1.capsule.json").write_text(
        json.dumps(UNAUDITED_MANIFEST), encoding="utf-8"
    )
    # Manifest missing required keys: must be skipped, not crash startup.
    (directory / "broken.capsule.json").write_text(
        json.dumps({"capsule_id": "broken_v1"}), encoding="utf-8"
    )
    # Unparseable JSON: must also be skipped.
    (directory / "notjson.capsule.json").write_text("{nope", encoding="utf-8")
    return directory


@pytest.fixture()
def server(monkeypatch, tmp_path, capsule_dir):
    return _load_server(monkeypatch, tmp_path, capsule_dir)


# ── Sync + listing ───────────────────────────────────────────────────────────

def test_sync_skips_invalid_manifests_and_lists_capsules(server):
    report = server.capsule_sync_report
    assert report["synced"] == 2
    skipped_files = {entry["file"] for entry in report["skipped"]}
    assert skipped_files == {"broken.capsule.json", "notjson.capsule.json"}

    payload = json.loads(_call(server.list_capsules))
    assert payload["total"] == 2
    cards = {card["capsule_id"]: card for card in payload["capsules"]}
    assert set(cards) == {"test_beam_v1", "test_unaudited_v1"}

    beam = cards["test_beam_v1"]
    assert beam["audited"] is True
    assert beam["capability"] == "analyze"
    assert beam["structure_type"] == "beam"
    assert beam["definition_file"] == "TestBeam.ghx"
    assert beam["inputs"] == [
        "ALMOND_IN_LINES", "ALMOND_IN_LOAD_KN", "ALMOND_IN_COUNT", "ALMOND_IN_NAMES",
    ]
    assert beam["outputs"] == ["ALMOND_OUT_DISP_MM", "ALMOND_OUT_UTIL"]
    # Compact cards must not leak local filesystem paths.
    assert "_manifest_path" not in beam
    assert cards["test_unaudited_v1"]["audited"] is False


def test_list_capsules_filters(server):
    audited = json.loads(_call(server.list_capsules, audited_only=True))
    assert [card["capsule_id"] for card in audited["capsules"]] == ["test_beam_v1"]

    generate = json.loads(_call(server.list_capsules, capability="generate"))
    assert [card["capsule_id"] for card in generate["capsules"]] == ["test_unaudited_v1"]

    none = json.loads(_call(server.list_capsules, capability="generate", audited_only=True))
    assert none["total"] == 0


def test_real_capsule_library_syncs_cleanly(monkeypatch, tmp_path):
    server = _load_server(monkeypatch, tmp_path, REAL_CAPSULE_DIR)
    assert server.capsule_sync_report["skipped"] == []
    payload = json.loads(_call(server.list_capsules))
    assert payload["total"] == 8
    assert all(card["capability"] == "analyze" for card in payload["capsules"])


# ── run_gh_definition rejections (bridge must never be reached) ─────────────

def test_run_rejects_unknown_capsule(server, monkeypatch):
    _forbid_bridge(server, monkeypatch)
    result = json.loads(_call(
        server.run_gh_definition, capsule_id="no_such_capsule", inputs={},
    ))
    assert result["status"] == "error"
    assert "Unknown capsule_id" in result["message"]
    assert "test_beam_v1" in result["available_capsules"]


def test_run_refuses_unaudited_capsule(server, monkeypatch):
    _forbid_bridge(server, monkeypatch)
    result = json.loads(_call(
        server.run_gh_definition,
        capsule_id="test_unaudited_v1",
        inputs={"ALMOND_IN_SEED_PTS": {"guids": ["a-guid"]}},
    ))
    assert result["status"] == "error"
    assert "not audited" in result["message"]
    assert "capsules/AUTHORING.md" in result["message"]


def test_run_rejects_missing_required_input(server, monkeypatch):
    _forbid_bridge(server, monkeypatch)
    result = json.loads(_call(
        server.run_gh_definition,
        capsule_id="test_beam_v1",
        inputs={"ALMOND_IN_LOAD_KN": 12.5},
    ))
    assert result["status"] == "error"
    assert "Missing required input" in result["message"]
    assert "ALMOND_IN_LINES" in result["message"]
    assert result["valid_inputs"] == sorted(
        port["name"] for port in AUDITED_MANIFEST["inputs"]
    )


@pytest.mark.parametrize("bad_inputs, fragment", [
    # Geometry port given a raw list instead of the {"guids": [...]} form.
    ({"ALMOND_IN_LINES": ["a-guid"]}, '{"guids"'),
    # Geometry port given an empty guid list.
    ({"ALMOND_IN_LINES": {"guids": []}}, '{"guids"'),
    # number port given a string.
    ({"ALMOND_IN_LINES": {"guids": ["a-guid"]}, "ALMOND_IN_LOAD_KN": "heavy"},
     "ALMOND_IN_LOAD_KN must be a finite number"),
    # number port given a bool (bool is not a number here).
    ({"ALMOND_IN_LINES": {"guids": ["a-guid"]}, "ALMOND_IN_LOAD_KN": True},
     "ALMOND_IN_LOAD_KN must be a finite number"),
    # integer port given a float.
    ({"ALMOND_IN_LINES": {"guids": ["a-guid"]}, "ALMOND_IN_COUNT": 2.5},
     "ALMOND_IN_COUNT must be an integer"),
    # string[] port given a scalar.
    ({"ALMOND_IN_LINES": {"guids": ["a-guid"]}, "ALMOND_IN_NAMES": "solo"},
     "ALMOND_IN_NAMES must be a flat list of strings"),
])
def test_run_rejects_wrong_typed_inputs(server, monkeypatch, bad_inputs, fragment):
    _forbid_bridge(server, monkeypatch)
    result = json.loads(_call(
        server.run_gh_definition, capsule_id="test_beam_v1", inputs=bad_inputs,
    ))
    assert result["status"] == "error"
    assert fragment in result["message"]
    assert result["valid_inputs"] == sorted(
        port["name"] for port in AUDITED_MANIFEST["inputs"]
    )


def test_run_rejects_unknown_input_name(server, monkeypatch):
    _forbid_bridge(server, monkeypatch)
    result = json.loads(_call(
        server.run_gh_definition,
        capsule_id="test_beam_v1",
        inputs={"ALMOND_IN_LINES": {"guids": ["a-guid"]}, "ALMOND_IN_NOPE": 1},
    ))
    assert result["status"] == "error"
    assert "ALMOND_IN_NOPE" in result["message"]
    assert result["valid_inputs"] == sorted(
        port["name"] for port in AUDITED_MANIFEST["inputs"]
    )


# ── run_gh_definition happy path: exact contract payload, verbatim response ─

def test_run_happy_path_sends_contract_payload_verbatim_response(
    server, monkeypatch, capsule_dir,
):
    bridge_response = json.dumps({
        "status": "ok",
        "capsule_id": "test_beam_v1",
        "outputs": {"ALMOND_OUT_DISP_MM": 14.2, "ALMOND_OUT_UTIL": [0.31, 0.87]},
        "baked_guids": [],
        "analysis_method": "template",
        "confidence": "medium",
        "warnings": ["self weight only"],
        "error": None,
    })
    mock = BridgeMock(bridge_response)
    monkeypatch.setattr(server, "_send_and_receive", mock)

    inputs = {
        "ALMOND_IN_LINES": {"guids": ["11111111-2222-3333-4444-555555555555"]},
        "ALMOND_IN_LOAD_KN": 12.5,
    }
    result = _call(
        server.run_gh_definition,
        capsule_id="test_beam_v1",
        inputs=inputs,
        seed=42,
        timeout_s=60.0,
    )

    # Bridge response passes through completely untouched.
    assert result == bridge_response

    assert len(mock.payloads) == 1
    sent, socket_timeout = mock.payloads[0]
    expected_manifest_path = str(
        (Path(server.CAPSULE_LIBRARY_DIR) / "test_beam_v1.capsule.json").resolve()
    )
    assert sent == {
        "type": "run_definition",
        "capsule_id": "test_beam_v1",
        "manifest_path": expected_manifest_path,
        "inputs": inputs,
        "seed": 42,
        "timeout_s": 60.0,
    }
    # Socket budget must exceed the solver budget.
    assert socket_timeout > 60.0


def test_run_omitted_seed_is_sent_as_null(server, monkeypatch):
    mock = BridgeMock(json.dumps({"status": "ok", "outputs": {}}))
    monkeypatch.setattr(server, "_send_and_receive", mock)
    _call(
        server.run_gh_definition,
        capsule_id="test_beam_v1",
        inputs={"ALMOND_IN_LINES": {"guids": ["a-guid"]}},
    )
    sent, _ = mock.payloads[0]
    assert "seed" in sent
    assert sent["seed"] is None
    assert sent["timeout_s"] == 60.0


def test_run_returns_error_json_when_bridge_down(server, monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise ConnectionRefusedError()
    monkeypatch.setattr(server, "_send_and_receive", _refuse)
    result = json.loads(_call(
        server.run_gh_definition,
        capsule_id="test_beam_v1",
        inputs={"ALMOND_IN_LINES": {"guids": ["a-guid"]}},
    ))
    assert result["status"] == "error"
    assert "RhinoAlmondBridge" in result["message"]


# ── validate_structure passthrough ───────────────────────────────────────────

def test_validate_structure_passes_through_new_fields(server, monkeypatch):
    bridge_response = json.dumps({
        "status": "success",
        "passed": False,
        "verdict": "[KARAMBA API, HIGH CONFIDENCE] 1 member over capacity.",
        "results": {"deflection_mm": 22.4, "utilization_max": 1.31},
        "analysis_method": "api",
        "confidence": "high",
        "per_element_utilization": [0.42, 1.31],
        "worst_member_guids": ["66666666-7777-8888-9999-000000000000"],
    })
    mock = BridgeMock(bridge_response)
    monkeypatch.setattr(server, "_send_and_receive", mock)

    result = _call(
        server.validate_structure,
        guids=["guid-1", "guid-2"],
        structure_type="frame",
        load_kn=25.0,
        material="S355",
    )
    # Untouched passthrough, new fields included.
    assert result == bridge_response
    parsed = json.loads(result)
    assert parsed["analysis_method"] == "api"
    assert parsed["confidence"] == "high"
    assert parsed["per_element_utilization"] == [0.42, 1.31]
    assert parsed["worst_member_guids"] == ["66666666-7777-8888-9999-000000000000"]

    # It still speaks the legacy "validate" request type.
    sent, _ = mock.payloads[0]
    assert sent == {
        "type": "validate",
        "guids": ["guid-1", "guid-2"],
        "structure_type": "frame",
        "load_kn": 25.0,
        "material": "S355",
    }
