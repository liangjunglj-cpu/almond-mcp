"""Run with a clean wheel-installed Python from outside the source checkout.

This deliberately uses an isolated data directory under the test environment;
it does not change an active MCP installation or contact Rhino.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import urllib.request

for key in list(os.environ):
    if key.startswith("RHINO_MCP_") or key == "PYTHONPATH":
        os.environ.pop(key)
os.environ["LOCALAPPDATA"] = str(Path(sys.prefix) / "fresh-data")

import almond_mcp
from almond_mcp.asset_repository import AssetRepository, create_server
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

assert Path(almond_mcp.__file__).is_relative_to(Path(sys.prefix)), "Must use an installed wheel"
repository = AssetRepository()
catalogue = repository.catalogue()
assert catalogue["counts"]["assets"] == 57
assert sum(a["available"] for a in catalogue["assets"]) == 50
server = create_server(0, repository)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for route in ["/", "/app.js", "/karamba.js", "/karamba-help.js", "/panel-theme.js", "/panel.css", "/analysis-view.mjs", "/vendor/model-viewer.min.js", "/vendor/THIRD-PARTY-LICENSES.txt",
                  "/api/catalogue", repository.records["gen-office-chair-1"]["model"]]:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{route}") as response:
            assert response.status == 200 and response.read()
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
            assert detail["generation_image"] in detail["local_files"]
            assert detail["metadata"]["triangle_count"] >= 70000
            assert all(Path(p).is_file() for p in detail["local_files"].values())
        return {"version":almond_mcp.__version__, "mcp_tools":len(tools),
                "object_archive":catalogue["counts"], "fresh_install_available":50,
                "optional_elements_uninstalled":7, "installed_http":"passed",
                "installed_mcp_search_resource":"passed", "installed_path":almond_mcp.__file__}


if __name__ == "__main__":
    result = asyncio.run(main())
    print(json.dumps(result, indent=2))
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
