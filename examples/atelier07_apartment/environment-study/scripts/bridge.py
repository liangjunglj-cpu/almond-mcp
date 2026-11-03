import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from almond_mcp import bridge_client
def run(script, timeout=600):
    r = json.loads(bridge_client.send(json.dumps({"type": "execute", "script": script}).encode(), timeout=timeout))
    if r.get("status") != "success":
        raise RuntimeError(str(r)[:2000])
    return r
