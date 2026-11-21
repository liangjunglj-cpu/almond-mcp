"""Run with a clean wheel-installed Python from outside the source checkout.

This deliberately uses an isolated data directory under the test environment;
it does not change an active MCP installation or contact Rhino.

The wheel carries no generated model files; they download on first use. Set
ALMOND_MODEL_BASE_URL to a local folder (file://) or server holding the release's
model files (tools/prepare_release.ps1 points it at dist/release-<v>/models), so
the check never depends on the network.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

for key in list(os.environ):
    if key.startswith("RHINO_MCP_") or key == "PYTHONPATH":
        os.environ.pop(key)
os.environ["LOCALAPPDATA"] = str(Path(sys.prefix) / "fresh-data")
MODEL_BASE = os.environ.get("ALMOND_MODEL_BASE_URL", "")
assert MODEL_BASE, "Set ALMOND_MODEL_BASE_URL to the staged release model files (file:// or http://)"

import almond_mcp
from almond_mcp import model_store
from almond_mcp.asset_repository import AssetRepository, create_server
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

assert Path(almond_mcp.__file__).is_relative_to(Path(sys.prefix)), "Must use an installed wheel"
assert not (Path(almond_mcp.__file__).parent / "data" / "GeneratedAssetfiles" / "models").exists(), \
    "The wheel must not carry generated model files"
repository = AssetRepository()
catalogue = repository.catalogue()
assert catalogue["counts"]["assets"] == 151
assert sum(a["available"] for a in catalogue["assets"]) == 144
models_dir = repository.roots["generated"] / "models"
assert not list(models_dir.glob("*.glb")), "A fresh install starts with no model files"
assert not any(a["local"] for a in catalogue["assets"] if a["kind"] == "model")
server = create_server(0, repository)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for route in ["/", "/app.js", "/karamba.js", "/karamba-help.js", "/panel-theme.js", "/panel.css", "/analysis-view.mjs", "/vendor/model-viewer.min.js", "/vendor/THIRD-PARTY-LICENSES.txt",
                  "/api/catalogue", repository.records["gen-office-chair-1"]["model"]]:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{route}") as response:
            assert response.status == 200 and response.read()
    # the first model request downloaded the GLB + contract, verified
    assert (models_dir / "gen-office-chair-1.glb").is_file() and (models_dir / "gen-office-chair-1.almond.json").is_file()
    # offline: an undownloaded model answers 503 with a message the viewer can show, and leaves nothing behind
    with tempfile.TemporaryDirectory() as empty:
        os.environ["ALMOND_MODEL_BASE_URL"] = Path(empty).as_uri()
        other = next(a for a in repository.records.values() if a["kind"] == "model" and not (models_dir / Path(a["model"]).name).exists())
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{other['model']}")
            raise AssertionError("expected 503 for an unreachable model")
        except urllib.error.HTTPError as exc:
            assert exc.code == 503 and "fetch-assets --generated" in json.loads(exc.read())["message"]
        assert not list(models_dir.glob(".*.part"))
        os.environ["ALMOND_MODEL_BASE_URL"] = MODEL_BASE
finally:
    server.shutdown()
    server.server_close()
    thread.join()


async def main():
    transport = StdioTransport(command=sys.executable, args=["-m", "almond_mcp.cli", "serve"],
                               env=dict(os.environ), cwd=str(Path(sys.prefix)))
    async with Client(transport, timeout=60) as client:
        tools = await client.list_tools()
        assert "validate_structure" in {t.name for t in tools}
        assert not any("ikea" in t.name.lower() for t in tools)
        result = await client.call_tool("search_asset_repository", {"query":"office chair", "drawing_ready":True})
        payload = result.structured_content
        assert payload["total"] == 1, payload
        record = json.loads((await client.read_resource(payload["assets"][0]["uri"]))[0].text)
        assert len(record["local_files"]) == 18
        assert record["provenance"]["recorded_generation"]["mesh_task_id"]
        assert all(Path(p).is_file() for p in record["local_files"].values())
        organic = (await client.call_tool("search_asset_repository", {"query":"organic-2026-09"})).structured_content
        assert organic["total"] == 3
        for asset in organic["assets"]:
            detail = json.loads((await client.read_resource(asset["uri"]))[0].text)
            # generation evidence (batches/) ships in the sdist, not the wheel
            assert detail.get("generation_image") is None
            assert detail["metadata"]["triangle_count"] >= 70000
            assert all(Path(p).is_file() for p in detail["local_files"].values())
        return {"version":almond_mcp.__version__, "mcp_tools":len(tools),
                "object_archive":catalogue["counts"], "fresh_install_available":144,
                "optional_elements_uninstalled":7, "installed_http":"passed",
                "installed_mcp_search_resource":"passed", "installed_path":almond_mcp.__file__}


def prefetch_and_audit() -> dict:
    """`fetch-assets --generated` downloads every model; the audit then needs them all."""
    cli = [sys.executable, "-m", "almond_mcp.cli"]
    fetched = subprocess.run(cli + ["fetch-assets", "--generated"], capture_output=True, text=True,
                             cwd=str(Path(sys.prefix)))
    assert fetched.returncode == 0, fetched.stdout[-2000:] + fetched.stderr[-2000:]
    audit = subprocess.run(cli + ["audit-assets", "--require-models"], capture_output=True, text=True,
                           cwd=str(Path(sys.prefix)))
    assert audit.returncode == 0, audit.stdout[-2000:]
    report = json.loads(audit.stdout)
    return {"prefetched_models": report["checked"], "installed_audit": report["status"],
            "model_source": "ALMOND_MODEL_BASE_URL (staged release files)"}


if __name__ == "__main__":
    result = asyncio.run(main())
    result.update(prefetch_and_audit())
    print(json.dumps(result, indent=2))
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
