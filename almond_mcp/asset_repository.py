"""One read-only catalogue for generated models, drawing elements and projections.

The catalogue joins existing libraries by stable asset ID. Files stay in their
canonical libraries; HTTP serves only individual manifest-listed files.
"""
from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

from almond_mcp import __version__, paths

UI_ROOT = Path(__file__).with_name("library_ui")


def read_json(path: Path, default=None):
    if not path.is_file():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8-sig"))


class AssetRepository:
    def __init__(self, roots: dict[str, Path] | None = None):
        self.roots = roots or {
            "generated": Path(paths.resolve_dir("RHINO_MCP_GENERATED_ASSET_DIR")),
            "drawing": Path(paths.resolve_dir("RHINO_MCP_DRAWING_ASSET_DIR")),
            "drafting": Path(paths.resolve_dir("RHINO_MCP_DRAFTING_DIR")),
        }
        self.roots = {k: Path(v).resolve() for k, v in self.roots.items()}
        self.files: dict[str, tuple[Path, Path]] = {}
        self.records: dict[str, dict] = {}
        self.refresh()

    def file(self, library: str, relative: str | None) -> str | None:
        if not relative:
            return None
        root = self.roots[library]
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return None
        url = "/files/" + library + "/" + quote(candidate.relative_to(root).as_posix(), safe="/")
        self.files[url] = (root, candidate)
        return url

    def refresh(self):
        self.files = {}
        self.records = {}
        source_register = read_json(self.roots["generated"] / "source-register.json")
        sources = {a["asset_id"]: a for a in source_register.get("assets", [])}
        drawings = {a["asset_id"]: a for a in read_json(self.roots["drafting"] / "manifest.json").get("assets", [])}
        for library in ("generated", "drawing"):
            manifest = read_json(self.roots[library] / "manifest.json")
            for asset in manifest.get("assets", []):
                aid = asset["asset_id"]
                model = self.file(library, asset.get("file"))
                fmt = Path(asset.get("file", "")).suffix.lstrip(".").lower()
                record = {
                    "id": aid, "name": asset.get("product", aid),
                    "kind": "model" if library == "generated" else "element",
                    "library": library, "category": asset.get("category", "other"),
                    "variant": asset.get("variant", ""), "format": fmt,
                    "tags": asset.get("tags", []), "roles": asset.get("drawing_roles", []),
                    "dimensions_mm": asset.get("dimensions_mm", {}),
                    "dimension_basis": asset.get("spatial", {}).get("bounds_source", "unverified"),
                    "available": bool(model), "model": model,
                    "preview": self.file(library, f"previews/{aid}.png") if library == "generated" else model if fmt == "svg" else None,
                    "contract": self.file(library, asset.get("contract_file")),
                    "license": asset.get("license", "Source terms apply; not cleared for redistribution"),
                    "source_url": (asset.get("warehouse_url") or "https://www.meshy.ai/") if library == "generated" else asset.get("warehouse_url", ""),
                    "publisher": asset.get("warehouse_publisher") or ("Almond generated asset library" if library == "generated" else "Not recorded"),
                    "provenance": sources.get(aid), "metadata": asset,
                    "drawing": None, "uri": f"almond://repository/{aid}",
                    "record_url": "/api/assets/" + quote(aid, safe="") + ".json",
                }
                if aid in drawings:
                    package = drawings[aid]["package"]
                    drawing_url = self.file("drafting", package + "/drawing.json")
                    if drawing_url:
                        drawing = read_json(self.files[drawing_url][1])
                        views = []
                        for rep in drawing.get("representations", []):
                            view = {k: rep[k] for k in ("view", "scale", "method", "approximation_note") if k in rep}
                            for fmt_name in ("svg", "dxf"):
                                view[fmt_name] = self.file("drafting", package + "/" + rep[fmt_name])
                            views.append(view)
                        record["drawing"] = {
                            "record": drawing_url, "views": views,
                            "sheets": [{"scale": s, "svg": self.file("drafting", f"{package}/sheet-A3-1-{s}.svg")} for s in drawing.get("scales", [])],
                            "source": drawing.get("source", {}),
                        }
                self.records[aid] = record
        self.sources = read_json(self.roots["drafting"] / "sources.json").get("sources", [])

    def catalogue(self) -> dict:
        assets = list(self.records.values())
        return {"schema_version": 1, "version": __version__,
                "title": "Almond Object Archive", "indexed_at": datetime.now(timezone.utc).isoformat(),
                "counts": {"assets": len(assets), "models": sum(a["kind"] == "model" for a in assets),
                           "elements": sum(a["kind"] == "element" for a in assets),
                           "drawing_packages": sum(bool(a["drawing"]) for a in assets),
                           "views": sum(len(a["drawing"]["views"]) for a in assets if a["drawing"])},
                "assets": assets, "sources": self.sources}

    def search(self, query="", kind="all", drawing_ready=False, limit=20):
        if kind not in {"all", "model", "element"}:
            raise ValueError("kind must be all, model or element")
        terms = query.casefold().split()
        results = []
        for asset in self.records.values():
            text = " ".join([asset["name"], asset["id"], asset["category"], asset["variant"], asset["metadata"].get("render_material_id", ""), *asset["tags"], *asset["roles"]]).casefold()
            if kind != "all" and asset["kind"] != kind or drawing_ready and not asset["drawing"]:
                continue
            if all(term in text for term in terms):
                results.append({k: asset[k] for k in ("id", "name", "kind", "category", "format", "available", "dimensions_mm", "license", "uri") } | {"drawing_ready": bool(asset["drawing"])})
        return {"total": len(results), "assets": results[:max(1, min(limit, 100))]}


def create_server(port=8767, repository: AssetRepository | None = None):
    repo = repository or AssetRepository()
    static = {"/" + p.relative_to(UI_ROOT).as_posix(): p for p in UI_ROOT.rglob("*") if p.is_file()}
    static["/"] = UI_ROOT / "index.html"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(False)

        def do_HEAD(self):
            self.respond(True)

        def respond(self, head):
            # Loopback binding plus Host validation prevents DNS rebinding reads.
            if self.headers.get("Host", "") not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                self.send_error(403)
                return
            route = urlsplit(self.path).path
            content = None
            mime = "application/json"
            filename = None
            if route == "/api/catalogue":
                content = json.dumps(repo.catalogue(), ensure_ascii=False).encode()
                filename = "almond-object-archive.json"
            elif route.startswith("/api/assets/"):
                record = next((a for a in repo.records.values() if a["record_url"] == route), None)
                if record:
                    content = json.dumps(record, ensure_ascii=False, indent=2).encode()
                    filename = record["id"] + ".json"
            else:
                path = static.get(route)
                root = UI_ROOT.resolve()
                if route in repo.files:
                    root, path = repo.files[route]
                if path and path.resolve().is_relative_to(root) and path.is_file():
                    content = path.read_bytes()
                    mime = {".js": "text/javascript", ".mjs": "text/javascript", ".glb": "model/gltf-binary", ".svg": "image/svg+xml", ".dxf": "application/dxf"}.get(path.suffix, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    filename = path.name
            if content is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            if filename and urlsplit(self.path).query == "download=1":
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
            self.end_headers()
            if not head:
                self.wfile.write(content)

        def log_message(self, fmt, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve_library(port=8767, open_browser=False):
    import webbrowser

    with create_server(port) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Almond Object Archive: {url}\nPress Ctrl+C to stop.", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
