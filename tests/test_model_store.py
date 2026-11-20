"""Generated model files download on first use (the PyPI wheel ships none).

No network: downloads come from a loopback http.server or a file:// folder."""
import functools
import hashlib
import http.client
import http.server
import importlib.util
import json
import os
import tempfile
import threading
import tomllib
from pathlib import Path

import pytest

from almond_mcp import __version__, model_store, paths
from almond_mcp.asset_passport import audit_library
from almond_mcp.asset_repository import AssetRepository, create_server

REPO = Path(__file__).resolve().parents[1]
GLB = b"glTF" + b"\x02\x00\x00\x00" + b"fake model bytes " * 64
CONTRACT = b'{"asset_id": "gen-test-1", "file": "gen-test-1.glb"}\n'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def asset(glb=GLB, contract=CONTRACT, **extra) -> dict:
    return {"asset_id": "gen-test-1", "file": "models/gen-test-1.glb", "sha256": sha(glb),
            "contract_file": "models/gen-test-1.almond.json", "contract_sha256": sha(contract), **extra}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    # Never reach a real proxy or the release host; loopback only.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.delenv(model_store.BASE_URL_ENV, raising=False)
    model_store._verified.clear()


@pytest.fixture
def release(tmp_path):
    """A folder laid out like the GitHub release: flat file names."""
    folder = tmp_path / "release"
    folder.mkdir()
    (folder / "gen-test-1.glb").write_bytes(GLB)
    (folder / "gen-test-1.almond.json").write_bytes(CONTRACT)
    return folder


@pytest.fixture
def served(release):
    """The release folder behind a loopback HTTP server; yields (base URL, request log)."""
    log = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.append(self.path)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(release)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", log
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def leftovers(root: Path) -> list[Path]:
    return [p for p in (root / "models").glob("*.part")] if (root / "models").is_dir() else []


def test_release_url_follows_the_package_version_and_env_override(monkeypatch):
    assert model_store.release_base_url() == \
        f"https://github.com/liangjunglj-cpu/almond-mcp/releases/download/v{__version__}"
    recorded = "https://raw.githubusercontent.com/liangjunglj-cpu/almond-mcp/master/GeneratedAssetfiles/models/a.glb"
    assert model_store.candidate_urls("a.glb", recorded, version="9.9.9") == [
        "https://github.com/liangjunglj-cpu/almond-mcp/releases/download/v9.9.9/a.glb", recorded]
    # a recorded URL that is not https is never used
    assert model_store.candidate_urls("a.glb", "http://example.invalid/a.glb", version="1") == [
        "https://github.com/liangjunglj-cpu/almond-mcp/releases/download/v1/a.glb"]
    monkeypatch.setenv(model_store.BASE_URL_ENV, "file:///C:/mirror/models/")
    assert model_store.candidate_urls("a.glb", recorded) == ["file:///C:/mirror/models/a.glb"]


def test_downloads_model_and_contract_from_http_and_verifies(tmp_path, served, monkeypatch):
    base, log = served
    monkeypatch.setenv(model_store.BASE_URL_ENV, base)
    root = tmp_path / "library"
    assert not model_store.is_local(asset(), root) and model_store.is_obtainable(asset())
    files = model_store.ensure_generated_files(asset(), root)
    assert files["model"].read_bytes() == GLB and files["contract"].read_bytes() == CONTRACT
    assert files["model"] == (root / "models" / "gen-test-1.glb").resolve()
    assert sorted(log) == ["/gen-test-1.almond.json", "/gen-test-1.glb"]
    assert model_store.is_local(asset(), root) and not leftovers(root)
    # present and verified: no second request
    model_store.ensure_generated_files(asset(), root)
    assert len(log) == 2


def test_file_url_base_works_for_offline_mirrors(tmp_path, release, monkeypatch):
    monkeypatch.setenv(model_store.BASE_URL_ENV, release.as_uri())
    files = model_store.ensure_generated_files(asset(), tmp_path / "library")
    assert files["model"].read_bytes() == GLB


def test_hash_mismatch_is_rejected_and_nothing_is_left_behind(tmp_path, release, monkeypatch):
    (release / "gen-test-1.glb").write_bytes(GLB + b"tampered")
    monkeypatch.setenv(model_store.BASE_URL_ENV, release.as_uri())
    root = tmp_path / "library"
    with pytest.raises(model_store.ModelUnavailable, match="sha256 mismatch"):
        model_store.ensure_generated_files(asset(), root)
    assert not (root / "models" / "gen-test-1.glb").exists()
    assert not leftovers(root)


def test_mismatched_local_file_is_replaced_only_by_a_verified_download(tmp_path, release, monkeypatch):
    root = tmp_path / "library"
    (root / "models").mkdir(parents=True)
    stale = root / "models" / "gen-test-1.glb"
    stale.write_bytes(b"older model")
    (root / "models" / "gen-test-1.almond.json").write_bytes(CONTRACT)
    monkeypatch.setenv(model_store.BASE_URL_ENV, (tmp_path / "empty").as_uri())
    with pytest.raises(model_store.ModelUnavailable):
        model_store.ensure_generated_files(asset(), root)
    assert stale.read_bytes() == b"older model"  # a failed download never destroys the old file
    monkeypatch.setenv(model_store.BASE_URL_ENV, release.as_uri())
    assert model_store.ensure_generated_files(asset(), root)["model"].read_bytes() == GLB


def test_interrupted_download_leaves_no_partial_file(tmp_path, monkeypatch):
    class Broken:
        def __init__(self):
            self.calls = 0

        def read(self, n):
            self.calls += 1
            if self.calls > 1:
                raise ConnectionResetError("connection dropped")
            return GLB[:10]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(model_store.urllib.request, "urlopen", lambda request, timeout: Broken())
    monkeypatch.setenv(model_store.BASE_URL_ENV, "https://mirror.invalid/models")
    root = tmp_path / "library"
    with pytest.raises(model_store.ModelUnavailable, match="connection dropped"):
        model_store.ensure_generated_files(asset(), root)
    assert not (root / "models" / "gen-test-1.glb").exists() and not leftovers(root)


def test_offline_error_names_the_fix(tmp_path, monkeypatch):
    # a closed loopback port: connection refused, like a machine with no network
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv(model_store.BASE_URL_ENV, f"http://127.0.0.1:{port}")
    with pytest.raises(model_store.ModelUnavailable) as caught:
        model_store.ensure_generated_files(asset(), tmp_path / "library", timeout=5)
    message = str(caught.value)
    assert "gen-test-1.glb" in message and "almond-mcp fetch-assets --generated" in message
    assert model_store.BASE_URL_ENV in message
    assert isinstance(caught.value, OSError)  # existing `except OSError` paths report it


def test_unsafe_or_unverifiable_entries_never_download(tmp_path, release, monkeypatch):
    monkeypatch.setenv(model_store.BASE_URL_ENV, release.as_uri())
    with pytest.raises(model_store.ModelUnavailable, match="outside"):
        model_store.ensure_generated_files(asset(file="../escape.glb"), tmp_path / "library")
    assert not model_store.is_obtainable(asset(sha256="placeholder"))
    with pytest.raises(model_store.ModelUnavailable, match="no verifiable"):
        model_store.ensure_generated_files(asset(sha256="placeholder"), tmp_path / "library")


def test_checkout_files_are_never_downloaded_or_overwritten(tmp_path, release, monkeypatch):
    root = tmp_path / "GeneratedAssetfiles"
    root.mkdir()
    monkeypatch.setattr(paths, "_repo_dir", lambda name: root)
    monkeypatch.setenv(model_store.BASE_URL_ENV, release.as_uri())
    with pytest.raises(model_store.ModelUnavailable, match="repository checkout"):
        model_store.ensure_generated_files(asset(), root)
    assert not (root / "models").exists()


def test_the_real_checkout_needs_no_download(monkeypatch):
    monkeypatch.setenv(model_store.BASE_URL_ENV, "http://127.0.0.1:9")  # would fail if used
    library = REPO / "GeneratedAssetfiles"
    record = json.loads((library / "manifest.json").read_text(encoding="utf-8"))["assets"][0]
    files = model_store.ensure_generated_files(record, library)
    assert files["model"].is_file() and files["contract"].is_file()


def test_prefetch_all_and_cli_fetch_generated(tmp_path, release, monkeypatch, capsys):
    from almond_mcp import cli
    root = tmp_path / "library"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"library_id": "generated_assets", "assets": [asset()]}))
    monkeypatch.setenv("RHINO_MCP_GENERATED_ASSET_DIR", str(root))
    monkeypatch.setenv(model_store.BASE_URL_ENV, (tmp_path / "nowhere").as_uri())
    assert cli.main(["fetch-assets", "--generated"]) == 1
    assert "fetch-assets --generated" in capsys.readouterr().out
    monkeypatch.setenv(model_store.BASE_URL_ENV, release.as_uri())
    assert cli.main(["fetch-assets", "--generated"]) == 0
    assert "downloaded    gen-test-1" in capsys.readouterr().out
    assert (root / "models" / "gen-test-1.almond.json").read_bytes() == CONTRACT
    summary = model_store.ensure_all([asset()], root)
    assert summary["present"] == 1 and summary["failed"] == 0


def test_audit_lists_models_not_downloaded_without_failing(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"assets": [asset()]}))
    relaxed = audit_library(root, require_models=False)
    assert relaxed["status"] == "success" and relaxed["not_downloaded"] == ["gen-test-1"]
    assert relaxed["checked"] == 0
    assert audit_library(root)["status"] == "error"


def test_archive_ui_downloads_on_first_request_and_reports_offline(tmp_path, release, monkeypatch):
    generated = tmp_path / "generated"
    (generated / "previews").mkdir(parents=True)
    (generated / "manifest.json").write_text(json.dumps({"assets": [asset(product="Test model")]}))
    repo = AssetRepository({"generated": generated, "drawing": tmp_path / "drawing", "drafting": tmp_path / "drafting"})
    record = repo.records["gen-test-1"]
    assert record["available"] and not record["local"]
    assert record["model"] == "/files/generated/models/gen-test-1.glb"
    server = create_server(0, repo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def get(route):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            connection.request("GET", route, headers={"Host": f"127.0.0.1:{server.server_port}"})
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result
        monkeypatch.setenv(model_store.BASE_URL_ENV, (tmp_path / "nowhere").as_uri())
        status, body = get(record["model"])
        assert status == 503 and "fetch-assets --generated" in json.loads(body)["message"]
        monkeypatch.setenv(model_store.BASE_URL_ENV, release.as_uri())
        assert get(record["model"]) == (200, GLB)
        assert get(record["contract"]) == (200, CONTRACT)
        assert repo.ensure(record["model"]).is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def load_server():
    os.environ["RHINO_MCP_GENERATED_ASSET_DIR"] = str(REPO / "GeneratedAssetfiles")
    os.environ["RHINO_MCP_STATE_DB"] = tempfile.mktemp(suffix=".sqlite3")
    spec = importlib.util.spec_from_file_location("almond_server_model_store_test", REPO / "almond_mcp" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_placement_and_drawings_go_through_the_download_helper(monkeypatch):
    server = load_server()
    real = model_store.ensure_generated_files
    calls = []

    def offline(asset, root=None, **kwargs):
        calls.append(asset["asset_id"])
        raise model_store.ModelUnavailable("offline: run `almond-mcp fetch-assets --generated`")

    monkeypatch.setattr(server.model_store, "ensure_generated_files", offline)
    placed = json.loads(server.place_generated_asset("gen-park-bench-1"))
    assert placed["status"] == "error" and "fetch-assets --generated" in placed["message"]
    drawn = server.generate_asset_drawing_views(asset_id="gen-park-bench-1")
    assert drawn["status"] == "error" and "offline" in drawn["message"]
    assert calls == ["gen-park-bench-1", "gen-park-bench-1"]

    # online: the helper's contract path is what placement loads and hands to Rhino
    received = {}
    monkeypatch.setattr(server.model_store, "ensure_generated_files",
                        lambda asset, root=None, **kw: real(asset, root))
    monkeypatch.setattr(server, "_receive_contract",
                        lambda contract, *args: received.update(contract) or {"status": "success"})
    placed = json.loads(server.place_generated_asset("gen-park-bench-1"))
    assert placed["status"] == "success" and received["asset_id"] == "gen-park-bench-1"
    assert Path(received["_resolved_file"]).is_file()


def test_indexer_marks_downloadable_models_available_but_not_local(tmp_path):
    server = load_server()
    library = tmp_path / "GeneratedAssetfiles"
    library.mkdir()
    (library / "manifest.json").write_text(json.dumps({"library_id": "generated_assets", "assets": [asset()]}))
    indexer = server.AssetLibraryIndexer(str(library), library_id="generated_assets", label="generated")
    record = indexer.get("gen-test-1")
    assert record["file_available"] and not record["file_local"]
    (library / "manifest.json").write_text(json.dumps({"library_id": "generated_assets",
                                                       "assets": [asset(sha256="placeholder")]}))
    indexer = server.AssetLibraryIndexer(str(library), library_id="generated_assets", label="generated")
    assert not indexer.get("gen-test-1")["file_available"]


def test_wheel_ships_catalogue_and_previews_but_no_model_files():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    shipped = set(wheel)
    assert not any(key.startswith("GeneratedAssetfiles/models") for key in shipped)
    assert not any(key.startswith("GeneratedAssetfiles/batches") for key in shipped)
    for kept in ("manifest.json", "catalogue.json", "previews", "provenance.json", "source-register.json",
                 "structural-loads.json", "passport.schema.json", "README.md"):
        assert f"GeneratedAssetfiles/{kept}" in shipped, kept
    # the sdist (GitHub release only) still carries the models for the release upload
    assert "/GeneratedAssetfiles/models" in project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
