"""Distribution and real .NET host integration (never loads/replaces Rhino)."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from build_archive_bundle import build_bundle


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    path=tmp_path_factory.mktemp("rhino-archive")/"archive"
    build_bundle(path)
    return path


def test_distributed_archive_excludes_community_files_and_keeps_evidence(bundle):
    catalogue=json.loads((bundle/"api/catalogue.json").read_text())
    assert catalogue["counts"]["assets"]==57
    assert len(list(bundle.rglob("*.glb")))==50
    assert not list(bundle.rglob("*.skp"))
    assert all(not a["available"] for a in catalogue["assets"] if a["kind"]=="element")
    for a in catalogue["assets"]:
        if a["kind"]=="model":
            assert a["provenance"]["asset_id"]==a["id"]
    manifest=json.loads((bundle/"bundle.json").read_text())
    for route,entry in manifest["routes"].items():
        assert hashlib.sha256((bundle/entry["path"]).read_bytes()).hexdigest()==entry["sha256"]
    with pytest.raises(ValueError,match="new or empty"):
        build_bundle(bundle)


@pytest.mark.skipif(not os.environ.get("ALMOND_ARCHIVE_TEST_HOST"),reason="Build the .NET archive host and set ALMOND_ARCHIVE_TEST_HOST")
def test_real_dotnet_host_http_and_integrity(bundle):
    process=subprocess.Popen([os.environ["ALMOND_ARCHIVE_TEST_HOST"],str(bundle)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        url=process.stdout.readline().strip()
        assert url.startswith("http://127.0.0.1:"),process.stderr.read() if process.poll() is not None else url
        origin=urlsplit(url)
        def request(route,method="GET",host=None):
            connection=http.client.HTTPConnection(origin.hostname,origin.port,timeout=10)
            connection.request(method,route,headers={"Host":host or origin.netloc})
            response=connection.getresponse()
            result=response.status,dict(response.getheaders()),response.read()
            connection.close()
            return result
        status,headers,body=request("/api/catalogue")
        assert status==200 and json.loads(body)["counts"]["models"]==50
        assert "wasm-unsafe-eval" in headers["Content-Security-Policy"]
        for route in ["/", "/app.js", "/preview-display.js", "/preview-style.mjs", "/karamba.js", "/analysis-view.mjs", "/vendor/model-viewer.min.js", "/files/generated/models/gen-office-chair-1.glb", "/files/drafting/pilot/gen-office-chair-1/plan-1-50.dxf"]:
            assert request(route)[0]==200
        assert request("/analysis-view.mjs")[1]["Content-Type"].startswith("text/javascript")
        status,headers,body=request("/files/generated/models/gen-office-chair-1.glb?download=1")
        assert status==200 and body[:4]==b"glTF" and "attachment" in headers["Content-Disposition"]
        assert request("/../LICENSE")[0]==404
        assert request("/api/catalogue",host="outside.example")[0]==403
        assert request("/api/catalogue",method="POST")[0]==405
        assert request("/api/catalogue",method="HEAD")[2]==b""
        icon=bundle/"ui/favicon.svg"
        original=icon.read_bytes()
        try:
            icon.write_bytes(b"tampered")
            assert request("/favicon.svg")[0]==409
        finally: icon.write_bytes(original)
    finally:
        process.communicate("\n",timeout=10)
        assert process.returncode==0
