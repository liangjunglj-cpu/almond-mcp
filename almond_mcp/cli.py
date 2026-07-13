"""almond-mcp command line.

Subcommands:
  serve         start the MCP server (default when no subcommand is given)
  fetch-assets  report which library model files are missing, with the
                original download URL and expected sha256 for each
  doctor        check directories, manifests, state DB, and the Rhino bridge
  paths         print every resolved directory and the state DB location
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import webbrowser
from pathlib import Path

from almond_mcp import __version__, paths

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 5000

# Libraries whose manifests reference downloadable model files.
_MODEL_LIBRARIES = (
    ("RHINO_MCP_FURNITURE_DIR", "IKEA furniture"),
    ("RHINO_MCP_DRAWING_ASSET_DIR", "drawing assets"),
    ("RHINO_MCP_DIAGRAM_ASSET_DIR", "diagram assets"),
)


def _load_manifest(library_dir: Path) -> dict | None:
    manifest_path = library_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _asset_status(library_dir: Path, asset: dict) -> tuple[str, str]:
    """Return (status, detail) for one manifest asset."""
    rel = asset.get("file")
    if not rel:
        return "no-file", "manifest entry has no file field"
    target = library_dir / rel
    if not target.is_file():
        return "missing", str(target)
    expected = (asset.get("sha256") or "").upper()
    # Some entries carry non-hash markers like "placeholder"; only a real
    # 64-hex digest is verifiable.
    if len(expected) == 64 and _sha256(target) != expected:
        return "hash-mismatch", str(target)
    return "ok", str(target)


def cmd_fetch_assets(args: argparse.Namespace) -> int:
    """List every model file the manifests expect, and where to get it.

    3D Warehouse requires a Trimble sign-in, so downloads stay manual: the
    command prints (and with --open, opens) the source page for each missing
    file. Re-run afterwards to verify the sha256 of what you saved.
    """
    missing_urls: list[str] = []
    problems = 0
    for env_var, label in _MODEL_LIBRARIES:
        library_dir = Path(paths.resolve_dir(env_var))
        manifest = _load_manifest(library_dir)
        if manifest is None:
            print(f"[{label}] no manifest at {library_dir}")
            problems += 1
            continue
        print(f"\n[{label}] {library_dir}")
        for asset in manifest.get("assets", []):
            status, detail = _asset_status(library_dir, asset)
            if status == "ok":
                if args.verbose:
                    print(f"  ok            {asset['asset_id']}")
                continue
            problems += 1
            url = asset.get("warehouse_url") or ""
            print(f"  {status:13} {asset['asset_id']}")
            print(f"                expected file: {asset.get('file')}")
            if asset.get("sha256"):
                print(f"                expected sha256: {asset['sha256']}")
            if url:
                print(f"                download from: {url}")
                if status == "missing":
                    missing_urls.append(url)
            else:
                print("                no recorded source URL - supply your own file")
    if problems == 0:
        print("\nAll manifest assets are present with matching hashes.")
        return 0
    print(f"\n{problems} asset(s) need attention.")
    print("Save each download into the library's models/ folder using the")
    print("expected file name, then re-run `almond-mcp fetch-assets` to verify.")
    if args.open and missing_urls:
        for url in missing_urls:
            webbrowser.open(url)
        print(f"Opened {len(missing_urls)} source page(s) in your browser.")
    return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        mark = "ok  " if passed else "FAIL"
        print(f"  {mark}  {label}" + (f" - {detail}" if detail else ""))

    print(f"almond-mcp {__version__} doctor\n")
    print("Directories:")
    for env_var in paths.LIBRARY_DIRS:
        resolved = Path(paths.resolve_dir(env_var))
        check(f"{paths.LIBRARY_DIRS[env_var]}", resolved.is_dir(), str(resolved))

    print("Manifests:")
    for env_var, label in _MODEL_LIBRARIES:
        library_dir = Path(paths.resolve_dir(env_var))
        try:
            manifest = _load_manifest(library_dir)
        except json.JSONDecodeError as exc:
            check(label, False, f"manifest.json invalid: {exc}")
            continue
        if manifest is None:
            check(label, False, "manifest.json missing")
            continue
        assets = manifest.get("assets", [])
        present = sum(
            1 for asset in assets if _asset_status(library_dir, asset)[0] == "ok"
        )
        check(label, True, f"{present}/{len(assets)} model files present")

    print("State database:")
    db_path = Path(paths.resolve_state_db())
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        probe = db_path.parent / ".almond_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        check("state DB location writable", True, str(db_path))
    except OSError as exc:
        check("state DB location writable", False, str(exc))

    print("Rhino bridge:")
    try:
        with socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=2):
            check(f"bridge listening on {BRIDGE_HOST}:{BRIDGE_PORT}", True)
    except OSError:
        check(
            f"bridge listening on {BRIDGE_HOST}:{BRIDGE_PORT}",
            False,
            "start Rhino 8 with the RhinoAlmondBridge plugin loaded",
        )

    print("\nAll checks passed." if ok else "\nSome checks failed (see above).")
    return 0 if ok else 1


def cmd_paths(args: argparse.Namespace) -> int:
    for env_var, name in paths.LIBRARY_DIRS.items():
        print(f"{name:20} {paths.resolve_dir(env_var)}   ({env_var})")
    print(f"{'state DB':20} {paths.resolve_state_db()}   ({paths.STATE_DB_ENV})")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    # Resolving before import scaffolds the user data dir on first run, so
    # the module-level indexers in server.py find their directories.
    for env_var in paths.LIBRARY_DIRS:
        paths.resolve_dir(env_var)
    from almond_mcp import server

    server.mcp.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="almond-mcp",
        description="Almond MCP server for Rhino 8 (semantic scene layer, "
        "curated asset libraries, Karamba capsules).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="start the MCP server (default)")
    fetch = sub.add_parser(
        "fetch-assets", help="report missing/invalid model files and their sources"
    )
    fetch.add_argument(
        "--open", action="store_true", help="open missing assets' source pages"
    )
    fetch.add_argument(
        "--verbose", action="store_true", help="also list assets that are ok"
    )
    sub.add_parser("doctor", help="check directories, manifests, DB, and bridge")
    sub.add_parser("paths", help="print resolved directories")

    args = parser.parse_args(argv)
    handlers = {
        None: cmd_serve,
        "serve": cmd_serve,
        "fetch-assets": cmd_fetch_assets,
        "doctor": cmd_doctor,
        "paths": cmd_paths,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
