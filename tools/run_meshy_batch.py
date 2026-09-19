"""Submit an explicitly selected Meshy batch stage and retain generation evidence.

MESHY_API_KEY must be supplied by the caller. Raw responses (including expiring
download URLs) stay in the gitignored raw directory; public evidence is sanitized.
POST requests are never retried automatically after an uncertain response.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import ssl
from urllib.parse import urlparse

import httpx

REPO = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["images", "meshes", "poll"])
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    root = REPO / "GeneratedAssetfiles/raw" / batch["batch_id"]
    root.mkdir(parents=True, exist_ok=True)
    key = os.environ["MESHY_API_KEY"]
    with httpx.Client(verify=ssl.create_default_context(), timeout=120) as client:
        for asset in batch["assets"]:
            aid = asset["asset_id"]
            if args.stage == "poll":
                for stage, endpoint in [("image", "text-to-image"), ("mesh", "image-to-3d")]:
                    ledger = root / (aid + "." + stage + ".json")
                    if not ledger.exists():
                        continue
                    record = json.loads(ledger.read_text())
                    if not record.get("task_id"):
                        print(aid, stage, "submission uncertain; inspect provider before resubmitting", flush=True)
                        continue
                    response = client.get("https://api.meshy.ai/openapi/v1/" + endpoint + "/" + record["task_id"], headers={"Authorization": "Bearer " + key})
                    response.raise_for_status()
                    task = response.json()
                    write(root / (aid + "." + stage + ".response.json"), task)
                    record.update(status=task["status"], consumed_credits=task.get("consumed_credits"),
                                  provider_created_at=task.get("created_at"), provider_started_at=task.get("started_at"))
                    write(ledger, record)
                    print(aid, stage, task["status"], task.get("progress"), flush=True)
                    if task["status"] != "SUCCEEDED":
                        continue
                    url = task["image_urls"][0] if stage == "image" else task["model_urls"]["glb"]
                    # Provider returns the output URL; never forward API credentials to it.
                    if urlparse(url).scheme != "https":
                        raise ValueError("Refusing non-HTTPS output URL")
                    target = root / (aid + (".png" if stage == "image" else ".glb"))
                    if not target.exists():
                        download = client.get(url, follow_redirects=True)
                        download.raise_for_status()
                        target.write_bytes(download.content)
                    record.update(status=task["status"], output_file=target.name,
                                  output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                                  finished_at=task.get("finished_at"), seed=task.get("seed"))
                    write(ledger, record)
                continue
            stage = "image" if args.stage == "images" else "mesh"
            endpoint = "text-to-image" if stage == "image" else "image-to-3d"
            ledger = root / (aid + "." + stage + ".json")
            if ledger.exists():
                print(aid, stage, "already recorded; skipped", flush=True)
                continue
            payload = dict(batch["image_settings"] if stage == "image" else batch["mesh_settings"])
            if stage == "image":
                payload["prompt"] = asset["prompt"]
            else:
                image_record = json.loads((root / (aid + ".image.json")).read_text())
                if image_record.get("status") != "SUCCEEDED":
                    raise ValueError("Image has not completed: " + aid)
                payload["input_task_id"] = image_record["task_id"]
            record = {"asset_id": aid, "endpoint": "/openapi/v1/" + endpoint,
                      "submitted_at": datetime.now(timezone.utc).isoformat(),
                      "request": payload, "status": "submission_started"}
            write(ledger, record)
            response = client.post("https://api.meshy.ai" + record["endpoint"], json=payload, headers={"Authorization": "Bearer " + key})
            if response.status_code >= 400:
                record.update(status="submission_rejected", http_status=response.status_code)
                write(ledger, record)
                raise RuntimeError(f"Meshy rejected {aid} ({response.status_code}): {response.text[:300]}")
            record.update(task_id=response.json()["result"], status="submitted")
            write(ledger, record)
            print(aid, stage, record["task_id"], flush=True)


if __name__ == "__main__":
    main()
