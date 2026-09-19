"""The unified catalogue must join representations and serve only indexed files."""
import http.client
import json
from pathlib import Path
import threading

from almond_mcp.asset_repository import AssetRepository, create_server

REPO = Path(__file__).resolve().parents[1]


def repository():
    return AssetRepository({"generated": REPO / "GeneratedAssetfiles",
                            "drawing": REPO / "DrawingAssetfiles",
                            "drafting": REPO / "Draftingfiles"})


def test_catalogue_joins_models_drawings_and_evidence():
    repo = repository()
    assert repo.catalogue()["counts"] == {"assets":57, "models":50, "elements":7, "drawing_packages":10, "views":60}
    record = repo.records["gen-office-chair-1"]
    assert record["available"] and record["provenance"]["recorded_generation"]["mesh_task_id"]
    assert record["drawing"]["source"]["asset_id"] == record["id"]
    assert len(record["drawing"]["views"]) == 6
    assert len(record["drawing"]["sheets"]) == 2
    for view in record["drawing"]["views"]:
        assert repo.files[view["svg"]][1].is_file()
        assert repo.files[view["dxf"]][1].is_file()
    assert repo.search("office chair", drawing_ready=True)["total"] == 1
    assert repo.search(kind="element")["total"] == 7
    assert repo.search("no such object")["total"] == 0
    assert len(repo.search(limit=2)["assets"]) == 2
    assert all(source["generation_use"] == "candidate_only" for source in repo.sources)


def test_missing_and_escaping_files_are_never_exposed(tmp_path):
    generated = tmp_path / "generated"
    generated.mkdir()
    secret = tmp_path / "secret.glb"
    secret.write_bytes(b"private")
    (generated / "manifest.json").write_text(json.dumps({"assets":[
        {"asset_id":"missing", "file":"models/missing.glb"},
        {"asset_id":"escape", "file":"../secret.glb"},
        {"asset_id":"absolute", "file":str(secret)},
    ]}))
    repo = AssetRepository({"generated":generated, "drawing":tmp_path/"drawing", "drafting":tmp_path/"drafting"})
    assert len(repo.records) == 3
    assert all(not a["available"] and a["model"] is None for a in repo.records.values())
    assert not repo.files


def test_http_downloads_and_file_boundary():
    repo = repository()
    server = create_server(0, repo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    def request(route, method="GET", headers=None):
        connection.request(method, route, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    try:
        status, headers, content = request("/")
        assert status == 200 and b"Almond" in content and b"karamba-page" in content
        assert "charset=utf-8" in headers["Content-Type"]
        status, headers, content = request("/api/catalogue?download=1")
        assert status == 200 and json.loads(content)["counts"]["assets"] == 57
        assert "attachment" in headers["Content-Disposition"]
        record = repo.records["gen-office-chair-1"]
        for route in [record["model"], record["record_url"], record["drawing"]["views"][0]["dxf"], "/vendor/model-viewer.min.js"]:
            status, headers, content = request(route+"?download=1")
            assert status == 200 and content
            assert "attachment" in headers["Content-Disposition"]
        for route in ["/../pyproject.toml", "/files/generated/../../pyproject.toml", "/files/generated/%2e%2e/manifest.json", "/files/generated/manifest.json", "/api/assets/unknown.json"]:
            assert request(route)[0] == 404
        assert request("/api/catalogue", headers={"Host":"attacker.example"})[0] == 403
        assert request("/api/catalogue", method="POST")[0] == 501
        status, headers, body = request(record["model"], method="HEAD")
        assert status == 200 and not body and int(headers["Content-Length"]) > 0
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join()


def test_mcp_repository_resource_uses_the_same_catalogue():
    from test_generated_assets import load_server_module
    server = load_server_module()
    result = server.search_asset_repository("office chair", drawing_ready=True)
    assert result["total"] == 1
    record = json.loads(server.repository_asset_resource(result["assets"][0]["id"]))
    assert record["provenance"]["asset_id"] == record["id"]
    assert len(record["local_files"]) == 18
    assert all(Path(path).is_file() for path in record["local_files"].values())
