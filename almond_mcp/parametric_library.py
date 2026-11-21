"""Read-only access to the annotated parametric (Grasshopper) teaching library.

The library lives in ``ParametricLibrary/`` (development checkout) or is
scaffolded from the wheel into the user data directory. Every definition is an
adapted third-party file whose logic is unchanged; integrity is checked
against the source register before a definition is handed out or opened.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class ParametricLibrary:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._catalogue = None
        self._register = None

    # ── loading ──────────────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        return (self.root / "catalogue.json").is_file()

    def _load(self) -> None:
        if self._catalogue is None:
            self._catalogue = json.loads((self.root / "catalogue.json").read_text(encoding="utf-8"))
            self._register = {item["id"]: item for item in json.loads(
                (self.root / "source-register.json").read_text(encoding="utf-8"))["items"]}

    @property
    def entries(self) -> list[dict]:
        self._load()
        return self._catalogue["entries"]

    def entry(self, definition_id: str) -> dict | None:
        return next((e for e in self.entries if e["id"] == definition_id), None)

    def _inside(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        path.relative_to(self.root.resolve())  # raises ValueError when outside the library
        return path

    # ── queries ──────────────────────────────────────────────────────────
    def search(self, query: str = "", category: str = "", level: str = "", limit: int = 20) -> dict:
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        cards = []
        for e in self.entries:
            if category and e["category"] != category.lower():
                continue
            if level and e["level"] != level.lower():
                continue
            lesson = self.lesson(e["id"])
            haystack = " ".join([e["id"], e["title"], e["summary"], e["category"],
                                 *lesson.get("concepts", []), *e["steps"]]).lower()
            matched = sorted(t for t in terms if t in haystack)
            if terms and not matched:
                continue
            cards.append({"id": e["id"], "title": e["title"], "category": e["category"], "level": e["level"],
                          "summary": e["summary"], "plugins": e["plugins"], "has_script": bool(e["scripts"]),
                          "geometry_inputs": e["geometry_inputs"], "licence": e["licence"],
                          "capsule_id": (e.get("capsule") or {}).get("capsule_id"),
                          "capsule_audited": (e.get("capsule") or {}).get("audited", False),
                          "matched_terms": matched, "preview_uri": f"almond://parametric/{e['id']}/preview"})
        cards.sort(key=lambda c: (-len(c["matched_terms"]), c["category"], c["id"]))
        return {"total": len(cards), "categories": sorted({e["category"] for e in self.entries}),
                "levels": ["beginner", "intermediate", "advanced"], "definitions": cards[:max(1, limit)]}

    def lesson(self, definition_id: str) -> dict:
        e = self.entry(definition_id)
        if e is None:
            raise KeyError(definition_id)
        return json.loads(self._inside(e["lesson"]).read_text(encoding="utf-8"))

    def record(self, definition_id: str) -> dict:
        self._load()
        return self._register[definition_id]

    def verify(self, definition_id: str) -> Path:
        """Return the definition path after checking it matches the register's output hash."""
        e = self.entry(definition_id)
        if e is None:
            raise KeyError(definition_id)
        path = self._inside(e["definition"])
        expected = self.record(definition_id)["derivation"][-1]["output_sha256"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"{definition_id}: definition file differs from the source register")
        return path

    def details(self, definition_id: str) -> dict:
        e = self.entry(definition_id)
        if e is None:
            raise KeyError(definition_id)
        path = self.verify(definition_id)
        lesson = self.lesson(definition_id)
        rec = self.record(definition_id)
        rights = rec["rights"]
        return {
            "id": e["id"], "title": e["title"], "category": e["category"], "level": e["level"],
            "summary": e["summary"], "definition_path": str(path), "preview_uri": f"almond://parametric/{e['id']}/preview",
            "how_to_use": lesson.get("how_to_use", []), "concepts": lesson.get("concepts", []),
            "steps": [{"title": s["title"], "explain": s.get("explain", "")} for s in lesson["steps"]],
            "inputs": e["inputs"], "geometry_inputs": e["geometry_inputs"], "plugins": e["plugins"],
            "scripts": e["scripts"],
            "value_overrides": {g: v.get("reason", "") for g, v in rec["derivation"][-1].get("value_overrides", {}).items()},
            "source": {"author": rec["source"]["author"], "repo_url": rec["source"]["repo_url"],
                       "path": rec["source"]["path"], "commit": rec["source"]["commit"]},
            "rights": {"licence": rights["licence"], "copyright": rights["copyright"], "licence_url": rights["licence_url"],
                       "licence_file": str(self._inside(rights["licence_file"])),
                       "note": "Adapted definition stays under its upstream licence; keep the LICENCE panel with every copy."},
            "capsule": self.capsule_summary(definition_id),
        }

    def preview(self, definition_id: str) -> bytes:
        e = self.entry(definition_id)
        if e is None:
            raise KeyError(definition_id)
        return self._inside(e["preview"]).read_bytes()

    # ── harnessed capsules ───────────────────────────────────────────────
    def capsule(self, definition_id: str) -> tuple[dict, Path] | None:
        """(manifest, manifest_path) of the definition's runnable capsule, verified against the register.

        Returns None when the definition has no harnessed derivative. Raises ValueError when the
        harnessed .ghx or the manifest differs from the register, so a tampered file is never run.
        """
        e = self.entry(definition_id)
        if e is None:
            raise KeyError(definition_id)
        cap = e.get("capsule")
        if not cap:
            return None
        rec = self.record(definition_id).get("harnessed")
        if not rec or rec.get("capsule_id") != cap["capsule_id"]:
            raise ValueError(f"{definition_id}: harnessed capsule is not in the source register")
        definition = self._inside(cap["definition"])
        manifest_path = self._inside(cap["manifest"])
        if _sha256(definition) != rec["derivation"]["output_sha256"]:
            raise ValueError(f"{definition_id}: harnessed definition differs from the source register")
        if _sha256(manifest_path) != rec["derivation"]["manifest_sha256"]:
            raise ValueError(f"{definition_id}: capsule manifest differs from the source register")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("capsule_id") != cap["capsule_id"] or manifest.get("definition_file") != definition.name:
            raise ValueError(f"{definition_id}: capsule manifest does not describe the harnessed definition")
        return manifest, manifest_path

    def capsule_manifests(self) -> tuple[list[dict], list[dict]]:
        """Every library capsule that passes verification, ready for the capsule registry.

        Returns (manifests, skipped); each manifest carries its absolute ``_manifest_path`` as
        the capsule registry expects, and each skipped entry says why.
        """
        manifests, skipped = [], []
        if not self.available:
            return manifests, skipped
        for e in self.entries:
            if not e.get("capsule"):
                continue
            try:
                found = self.capsule(e["id"])
            except (OSError, ValueError, KeyError) as exc:
                skipped.append({"file": e["capsule"].get("manifest", e["id"]), "errors": [str(exc)]})
                continue
            if found is None:
                continue
            manifest, manifest_path = found
            manifest["_manifest_path"] = str(manifest_path.resolve())
            manifests.append(manifest)
        return manifests, skipped

    def capsule_summary(self, definition_id: str) -> dict | None:
        """What get_parametric_definition reports about the runnable derivative."""
        e = self.entry(definition_id)
        cap = (e or {}).get("capsule")
        if not cap:
            return None
        try:
            found = self.capsule(definition_id)
        except (OSError, ValueError) as exc:
            return {"capsule_id": cap["capsule_id"], "integrity": f"FAILED: {exc}", "runnable": False}
        manifest, manifest_path = found
        audited = bool(manifest.get("audited"))
        return {
            "capsule_id": manifest["capsule_id"], "capability": manifest["capability"], "audited": audited,
            "runnable": audited, "status": (manifest.get("audit") or {}).get("status", ""),
            "audit_note": (manifest.get("audit") or {}).get("note", ""),
            "definition_path": str(self._inside(cap["definition"])), "manifest_path": str(manifest_path),
            "inputs": [{k: p[k] for k in ("name", "type", "units", "required", "default", "description") if k in p}
                       for p in manifest.get("inputs", [])],
            "outputs": [{k: p[k] for k in ("name", "type", "units", "semantics", "description") if k in p}
                        for p in manifest.get("outputs", [])],
            "integrity": "verified against the source register",
            "how_to_run": (f"run_gh_definition(capsule_id='{manifest['capsule_id']}', inputs={{...}}) with Rhino open; "
                           "geometry outputs are baked and returned as GUIDs" if audited else
                           "refused by run_gh_definition until a live run flips harness.audited in the lesson"),
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_in_grasshopper_script(path: Path) -> str:
    """C# for the bridge's execute message: open a .ghx in the Grasshopper editor.

    Uses the -Grasshopper command so no Grasshopper types are needed at compile
    time (the assembly may not be loaded yet). Opening solves the definition.
    """
    literal = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return (
        "public class Script\n{\n"
        "    public static List<Guid> Run(RhinoDoc doc)\n    {\n"
        f"        var file = \"{literal}\";\n"
        "        if (!System.IO.File.Exists(file)) throw new System.IO.FileNotFoundException(file);\n"
        "        Rhino.RhinoApp.RunScript(\"_-Grasshopper _Editor _Load _Enter\", false);\n"
        "        var ok = Rhino.RhinoApp.RunScript(\"_-Grasshopper _Document _Open \\\"\" + file + \"\\\" _Enter\", false);\n"
        "        if (!ok) throw new System.InvalidOperationException(\"Grasshopper did not open the definition\");\n"
        "        return new List<Guid>();\n    }\n}\n"
    )
