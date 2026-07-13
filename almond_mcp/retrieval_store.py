"""Persistent structured retrieval and scene state for AlmondMCP."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class AlmondStore:
    """SQLite-backed asset retrieval, spatial state, and generation plans."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT NOT NULL UNIQUE,
                    library_id TEXT NOT NULL DEFAULT 'ikea',
                    category TEXT NOT NULL,
                    series TEXT NOT NULL,
                    product TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    width_mm REAL NOT NULL,
                    depth_mm REAL NOT NULL,
                    height_mm REAL NOT NULL,
                    match_status TEXT NOT NULL,
                    geometry_source_type TEXT NOT NULL,
                    file_available INTEGER NOT NULL DEFAULT 0,
                    search_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS asset_fts USING fts5(
                    asset_id UNINDEXED,
                    search_text,
                    tokenize = 'unicode61 remove_diacritics 2'
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS asset_rtree USING rtree(
                    asset_rowid,
                    min_x, max_x,
                    min_y, max_y,
                    min_z, max_z
                );

                CREATE TABLE IF NOT EXISTS scenes (
                    scene_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    units TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rooms (
                    room_id TEXT PRIMARY KEY,
                    scene_id TEXT NOT NULL REFERENCES scenes(scene_id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    min_x REAL NOT NULL,
                    max_x REAL NOT NULL,
                    min_y REAL NOT NULL,
                    max_y REAL NOT NULL,
                    min_z REAL NOT NULL,
                    max_z REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS instances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL UNIQUE,
                    scene_id TEXT NOT NULL REFERENCES scenes(scene_id) ON DELETE CASCADE,
                    room_id TEXT REFERENCES rooms(room_id) ON DELETE SET NULL,
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
                    rhino_guid TEXT,
                    x_mm REAL NOT NULL,
                    y_mm REAL NOT NULL,
                    z_mm REAL NOT NULL,
                    rotation_degrees REAL NOT NULL,
                    scale REAL NOT NULL,
                    locked INTEGER NOT NULL DEFAULT 0,
                    min_x REAL NOT NULL,
                    max_x REAL NOT NULL,
                    min_y REAL NOT NULL,
                    max_y REAL NOT NULL,
                    min_z REAL NOT NULL,
                    max_z REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS instance_rtree USING rtree(
                    instance_rowid,
                    min_x, max_x,
                    min_y, max_y,
                    min_z, max_z
                );

                CREATE TABLE IF NOT EXISTS scene_revisions (
                    scene_id TEXT NOT NULL REFERENCES scenes(scene_id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    patch_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (scene_id, revision)
                );

                CREATE TABLE IF NOT EXISTS generation_plans (
                    plan_id TEXT PRIMARY KEY,
                    scene_id TEXT REFERENCES scenes(scene_id) ON DELETE SET NULL,
                    scope TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS generation_plan_steps (
                    plan_id TEXT NOT NULL REFERENCES generation_plans(plan_id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    input_refs_json TEXT NOT NULL,
                    output_refs_json TEXT NOT NULL,
                    PRIMARY KEY (plan_id, step_id)
                );

                CREATE TABLE IF NOT EXISTS capsules (
                    capsule_id TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    definition_file TEXT NOT NULL,
                    audited INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL DEFAULT '',
                    manifest_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_capsules_capability
                    ON capsules(capability, audited);

                CREATE INDEX IF NOT EXISTS idx_assets_category
                    ON assets(category, width_mm, depth_mm, height_mm);
                CREATE INDEX IF NOT EXISTS idx_instances_scene
                    ON instances(scene_id, room_id);
                CREATE INDEX IF NOT EXISTS idx_rooms_scene
                    ON rooms(scene_id);
                """
            )
            asset_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(assets)")
            }
            if "library_id" not in asset_columns:
                connection.execute(
                    "ALTER TABLE assets ADD COLUMN library_id TEXT NOT NULL DEFAULT 'ikea'"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assets_library_category
                ON assets(library_id, category, width_mm, depth_mm, height_mm)
                """
            )

    # Asset registry -----------------------------------------------------

    def sync_assets(
        self,
        assets: list[dict[str, Any]],
        library_id: str = "ikea",
    ) -> int:
        """Upsert one manifest and prune stale records only within its library."""
        library_id = library_id.strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", library_id):
            raise ValueError("library_id must be a short lowercase identifier.")
        now = _utc_now()
        seen: list[str] = []
        with self._connect() as connection:
            for source in assets:
                asset = {
                    key: value
                    for key, value in source.items()
                    if not key.startswith("_")
                }
                asset["library_id"] = library_id
                asset_id = str(asset["asset_id"])
                dimensions = asset.get("dimensions_mm", {})
                width = float(dimensions.get("width", 0))
                depth = float(dimensions.get("depth", 0))
                height = float(dimensions.get("height", 0))
                if min(width, depth, height) <= 0:
                    raise ValueError(f"Asset {asset_id} has invalid dimensions.")

                search_text = " ".join(
                    filter(
                        None,
                        [
                            asset_id,
                            asset.get("category", ""),
                            asset.get("series", ""),
                            asset.get("product", ""),
                            asset.get("variant", ""),
                            asset.get("brand", ""),
                            asset.get("source_class", ""),
                            " ".join(asset.get("tags", [])),
                        ],
                    )
                )
                geometry_source = asset.get("geometry_source", {})
                connection.execute(
                    """
                    INSERT INTO assets (
                        asset_id, library_id, category, series, product, variant,
                        width_mm, depth_mm, height_mm, match_status,
                        geometry_source_type, file_available, search_text,
                        metadata_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        library_id = excluded.library_id,
                        category = excluded.category,
                        series = excluded.series,
                        product = excluded.product,
                        variant = excluded.variant,
                        width_mm = excluded.width_mm,
                        depth_mm = excluded.depth_mm,
                        height_mm = excluded.height_mm,
                        match_status = excluded.match_status,
                        geometry_source_type = excluded.geometry_source_type,
                        file_available = excluded.file_available,
                        search_text = excluded.search_text,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        asset_id,
                        library_id,
                        asset.get("category", ""),
                        asset.get("series", ""),
                        asset.get("product", ""),
                        asset.get("variant", ""),
                        width,
                        depth,
                        height,
                        asset.get("match_status", ""),
                        geometry_source.get("type", "downloaded_asset"),
                        int(bool(asset.get("file_available"))),
                        search_text,
                        _json(asset),
                        now,
                    ),
                )
                asset_row = connection.execute(
                    "SELECT id FROM assets WHERE asset_id = ?",
                    (asset_id,),
                ).fetchone()
                row_id = int(asset_row["id"])

                connection.execute(
                    "DELETE FROM asset_fts WHERE asset_id = ?",
                    (asset_id,),
                )
                connection.execute(
                    "INSERT INTO asset_fts(asset_id, search_text) VALUES (?, ?)",
                    (asset_id, search_text),
                )
                connection.execute(
                    "DELETE FROM asset_rtree WHERE asset_rowid = ?",
                    (row_id,),
                )
                spatial = asset.get("spatial", {})
                bounds = spatial.get("local_aabb", {})
                minimum = bounds.get("min", [-width / 2, -depth / 2, 0])
                maximum = bounds.get("max", [width / 2, depth / 2, height])
                connection.execute(
                    """
                    INSERT INTO asset_rtree(
                        asset_rowid, min_x, max_x, min_y, max_y, min_z, max_z
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        float(minimum[0]),
                        float(maximum[0]),
                        float(minimum[1]),
                        float(maximum[1]),
                        float(minimum[2]),
                        float(maximum[2]),
                    ),
                )
                seen.append(asset_id)

            if seen:
                placeholders = ",".join("?" for _ in seen)
                stale_rows = connection.execute(
                    f"""
                    SELECT id, asset_id FROM assets
                    WHERE library_id = ? AND asset_id NOT IN ({placeholders})
                    """,
                    [library_id, *seen],
                ).fetchall()
            else:
                stale_rows = connection.execute(
                    "SELECT id, asset_id FROM assets WHERE library_id = ?",
                    (library_id,),
                ).fetchall()
            for stale in stale_rows:
                connection.execute(
                    "DELETE FROM asset_fts WHERE asset_id = ?",
                    (stale["asset_id"],),
                )
                connection.execute(
                    "DELETE FROM asset_rtree WHERE asset_rowid = ?",
                    (stale["id"],),
                )
                connection.execute(
                    "DELETE FROM assets WHERE id = ?",
                    (stale["id"],),
                )
        return len(seen)

    @staticmethod
    def compact_asset(asset: dict[str, Any]) -> dict[str, Any]:
        return {
            "asset_id": asset["asset_id"],
            "library_id": asset.get("library_id", "ikea"),
            "brand": asset.get("brand", "IKEA"),
            "source_class": asset.get("source_class", "ikea_catalogue"),
            "catalogue_status": asset.get("catalogue_status"),
            "category": asset.get("category"),
            "series": asset.get("series"),
            "product": asset.get("product"),
            "variant": asset.get("variant"),
            "size_mm": [
                asset.get("dimensions_mm", {}).get("width"),
                asset.get("dimensions_mm", {}).get("depth"),
                asset.get("dimensions_mm", {}).get("height"),
            ],
            "match": asset.get("match_status"),
            "source_type": asset.get("geometry_source", {}).get("type"),
            "available": bool(asset.get("file_available")),
        }

    def search_assets(
        self,
        query: str = "",
        library_id: str = "",
        category: str = "",
        max_width_mm: float = 0,
        max_depth_mm: float = 0,
        max_height_mm: float = 0,
        exact_dimensions_only: bool = False,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 50))
        offset = max(0, int(offset))
        clauses: list[str] = []
        parameters: list[Any] = []
        joins = ""
        ordering = "a.series, a.product, a.asset_id"

        if library_id.strip():
            clauses.append("a.library_id = ?")
            parameters.append(library_id.strip().lower())
        tokens = re.findall(r"[\w-]+", query.lower(), flags=re.UNICODE)
        if tokens:
            joins = "JOIN asset_fts ON asset_fts.asset_id = a.asset_id"
            fts_query = " OR ".join(f'"{token}"*' for token in tokens[:12])
            clauses.append("asset_fts MATCH ?")
            parameters.append(fts_query)
            ordering = "bm25(asset_fts), a.series, a.product"
        if category.strip():
            clauses.append("a.category = ?")
            parameters.append(category.strip().lower())
        if max_width_mm > 0:
            clauses.append("a.width_mm <= ?")
            parameters.append(float(max_width_mm))
        if max_depth_mm > 0:
            clauses.append("a.depth_mm <= ?")
            parameters.append(float(max_depth_mm))
        if max_height_mm > 0:
            clauses.append("a.height_mm <= ?")
            parameters.append(float(max_height_mm))
        if exact_dimensions_only:
            clauses.append("a.match_status = 'exact_dimensions'")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        count_sql = f"SELECT COUNT(*) AS count FROM assets a {joins} {where}"
        query_sql = f"""
            SELECT a.metadata_json
            FROM assets a
            {joins}
            {where}
            ORDER BY {ordering}
            LIMIT ? OFFSET ?
        """
        with self._connect() as connection:
            total = int(connection.execute(count_sql, parameters).fetchone()["count"])
            rows = connection.execute(
                query_sql,
                [*parameters, limit, offset],
            ).fetchall()
        assets = [
            self.compact_asset(_decode(row["metadata_json"], {}))
            for row in rows
        ]
        next_offset = offset + len(assets)
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset if next_offset < total else None,
            "assets": assets,
        }

    def get_asset(
        self,
        asset_id: str,
        library_id: str = "",
    ) -> dict[str, Any] | None:
        clauses = ["asset_id = ?"]
        parameters: list[Any] = [asset_id]
        if library_id.strip():
            clauses.append("library_id = ?")
            parameters.append(library_id.strip().lower())
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT metadata_json FROM assets WHERE {' AND '.join(clauses)}",
                parameters,
            ).fetchone()
        return _decode(row["metadata_json"], {}) if row else None

    def asset_stats(self, library_id: str = "") -> dict[str, Any]:
        where = ""
        parameters: list[Any] = []
        if library_id.strip():
            where = "WHERE library_id = ?"
            parameters.append(library_id.strip().lower())
        with self._connect() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) AS count FROM assets {where}",
                parameters,
            ).fetchone()["count"])
            categories = [
                {"category": row["category"], "count": int(row["count"])}
                for row in connection.execute(
                    f"""
                    SELECT category, COUNT(*) AS count FROM assets
                    {where}
                    GROUP BY category ORDER BY category
                    """,
                    parameters,
                )
            ]
            libraries = [
                {"library_id": row["library_id"], "count": int(row["count"])}
                for row in connection.execute(
                    """
                    SELECT library_id, COUNT(*) AS count FROM assets
                    GROUP BY library_id ORDER BY library_id
                    """
                )
            ]
        return {"total": total, "libraries": libraries, "categories": categories}

    # Capsule registry ---------------------------------------------------

    def sync_capsules(self, manifests: list[dict[str, Any]]) -> int:
        """Upsert capsule manifests and prune capsules absent from the batch."""
        now = _utc_now()
        seen: list[str] = []
        with self._connect() as connection:
            for manifest in manifests:
                if not isinstance(manifest, dict):
                    raise ValueError("Each capsule manifest must be a dict.")
                missing = [
                    key
                    for key in ("capsule_id", "capability", "definition_file",
                                "inputs", "outputs", "audited")
                    if key not in manifest
                ]
                if missing:
                    raise ValueError(
                        f"Capsule manifest is missing keys: {', '.join(missing)}"
                    )
                capsule_id = str(manifest["capsule_id"]).strip()
                if not capsule_id:
                    raise ValueError("capsule_id must be a non-empty string.")
                connection.execute(
                    """
                    INSERT INTO capsules (
                        capsule_id, capability, definition_file, audited,
                        title, manifest_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(capsule_id) DO UPDATE SET
                        capability = excluded.capability,
                        definition_file = excluded.definition_file,
                        audited = excluded.audited,
                        title = excluded.title,
                        manifest_json = excluded.manifest_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        capsule_id,
                        str(manifest["capability"]).strip().lower(),
                        str(manifest["definition_file"]).strip(),
                        int(bool(manifest["audited"])),
                        str(manifest.get("title", "")).strip(),
                        _json(manifest),
                        now,
                    ),
                )
                seen.append(capsule_id)

            if seen:
                placeholders = ",".join("?" for _ in seen)
                connection.execute(
                    f"DELETE FROM capsules WHERE capsule_id NOT IN ({placeholders})",
                    seen,
                )
            else:
                connection.execute("DELETE FROM capsules")
        return len(seen)

    @staticmethod
    def compact_capsule(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "capsule_id": manifest.get("capsule_id"),
            "capability": manifest.get("capability"),
            "structure_type": manifest.get("structure_type"),
            "definition_file": manifest.get("definition_file"),
            "title": manifest.get("title", ""),
            "audited": bool(manifest.get("audited")),
            "inputs": [port.get("name") for port in manifest.get("inputs", [])],
            "outputs": [port.get("name") for port in manifest.get("outputs", [])],
        }

    def search_capsules(
        self,
        query: str = "",
        capability: str = "",
        audited_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 50))
        offset = max(0, int(offset))
        clauses: list[str] = []
        parameters: list[Any] = []

        if capability.strip():
            clauses.append("capability = ?")
            parameters.append(capability.strip().lower())
        if audited_only:
            clauses.append("audited = 1")
        tokens = re.findall(r"[\w-]+", query.lower(), flags=re.UNICODE)
        for token in tokens[:12]:
            clauses.append(
                "(LOWER(capsule_id) LIKE ? OR LOWER(title) LIKE ? "
                "OR LOWER(definition_file) LIKE ? OR LOWER(manifest_json) LIKE ?)"
            )
            pattern = f"%{token}%"
            parameters.extend([pattern, pattern, pattern, pattern])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) AS count FROM capsules {where}",
                parameters,
            ).fetchone()["count"])
            rows = connection.execute(
                f"""
                SELECT manifest_json FROM capsules
                {where}
                ORDER BY audited DESC, capsule_id
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
        capsules = [
            self.compact_capsule(_decode(row["manifest_json"], {}))
            for row in rows
        ]
        next_offset = offset + len(capsules)
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset if next_offset < total else None,
            "capsules": capsules,
        }

    def get_capsule(self, capsule_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT manifest_json FROM capsules WHERE capsule_id = ?",
                (capsule_id.strip(),),
            ).fetchone()
        return _decode(row["manifest_json"], {}) if row else None

    # Scene ledger -------------------------------------------------------

    def create_scene(self, name: str, units: str = "mm") -> dict[str, Any]:
        units = units.lower().strip()
        if units not in {"mm", "cm", "m", "in", "ft"}:
            raise ValueError("units must be mm, cm, m, in, or ft.")
        scene_id = f"scene_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scenes(scene_id, name, units, revision, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (scene_id, name.strip() or "Untitled scene", units, now, now),
            )
        return self.get_scene(scene_id)

    def get_scene(self, scene_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            scene = connection.execute(
                "SELECT * FROM scenes WHERE scene_id = ?",
                (scene_id,),
            ).fetchone()
            if not scene:
                return None
            room_count = int(connection.execute(
                "SELECT COUNT(*) AS count FROM rooms WHERE scene_id = ?",
                (scene_id,),
            ).fetchone()["count"])
            instance_count = int(connection.execute(
                "SELECT COUNT(*) AS count FROM instances WHERE scene_id = ?",
                (scene_id,),
            ).fetchone()["count"])
        return {
            "scene_id": scene["scene_id"],
            "name": scene["name"],
            "units": scene["units"],
            "revision": int(scene["revision"]),
            "rooms": room_count,
            "instances": instance_count,
            "updated_at": scene["updated_at"],
        }

    def upsert_room(
        self,
        scene_id: str,
        name: str,
        bounds_mm: list[float],
        room_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if len(bounds_mm) != 6:
            raise ValueError("bounds_mm must be [min_x, min_y, min_z, max_x, max_y, max_z].")
        values = [float(value) for value in bounds_mm]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Room bounds must be finite.")
        min_x, min_y, min_z, max_x, max_y, max_z = values
        if min_x >= max_x or min_y >= max_y or min_z >= max_z:
            raise ValueError("Room bounds must have positive volume.")
        if not self.get_scene(scene_id):
            raise KeyError(f"Unknown scene_id: {scene_id}")
        room_id = room_id.strip() or f"room_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        patch = {
            "room_id": room_id,
            "name": name,
            "bounds_mm": values,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rooms(
                    room_id, scene_id, name,
                    min_x, max_x, min_y, max_y, min_z, max_z,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(room_id) DO UPDATE SET
                    name = excluded.name,
                    min_x = excluded.min_x,
                    max_x = excluded.max_x,
                    min_y = excluded.min_y,
                    max_y = excluded.max_y,
                    min_z = excluded.min_z,
                    max_z = excluded.max_z,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    room_id, scene_id, name.strip() or room_id,
                    min_x, max_x, min_y, max_y, min_z, max_z,
                    _json(metadata or {}), now, now,
                ),
            )
            revision = self._record_revision(
                connection, scene_id, "upsert_room", patch
            )
        return {"room_id": room_id, "scene_id": scene_id, "revision": revision}

    def upsert_instance(
        self,
        scene_id: str,
        asset_id: str,
        x_mm: float,
        y_mm: float,
        z_mm: float = 0,
        rotation_degrees: float = 0,
        scale: float = 1,
        room_id: str = "",
        instance_id: str = "",
        locked: bool = False,
        rhino_guid: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.get_scene(scene_id):
            raise KeyError(f"Unknown scene_id: {scene_id}")
        asset = self.get_asset(asset_id)
        if not asset:
            raise KeyError(f"Unknown asset_id: {asset_id}")
        numeric = [x_mm, y_mm, z_mm, rotation_degrees, scale]
        if not all(math.isfinite(float(value)) for value in numeric):
            raise ValueError("Instance transform values must be finite.")
        if scale <= 0:
            raise ValueError("scale must be greater than zero.")
        if room_id:
            with self._connect() as connection:
                room = connection.execute(
                    "SELECT scene_id FROM rooms WHERE room_id = ?",
                    (room_id,),
                ).fetchone()
            if not room or room["scene_id"] != scene_id:
                raise KeyError("room_id does not belong to the scene.")

        instance_id = instance_id.strip() or f"instance_{uuid.uuid4().hex[:12]}"
        bounds = self._world_aabb(
            asset,
            float(x_mm),
            float(y_mm),
            float(z_mm),
            float(rotation_degrees),
            float(scale),
        )
        now = _utc_now()
        patch = {
            "instance_id": instance_id,
            "asset_id": asset_id,
            "room_id": room_id or None,
            "transform": [x_mm, y_mm, z_mm, rotation_degrees, scale],
            "locked": bool(locked),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO instances(
                    instance_id, scene_id, room_id, asset_id, rhino_guid,
                    x_mm, y_mm, z_mm, rotation_degrees, scale, locked,
                    min_x, max_x, min_y, max_y, min_z, max_z,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instance_id) DO UPDATE SET
                    room_id = excluded.room_id,
                    asset_id = excluded.asset_id,
                    rhino_guid = excluded.rhino_guid,
                    x_mm = excluded.x_mm,
                    y_mm = excluded.y_mm,
                    z_mm = excluded.z_mm,
                    rotation_degrees = excluded.rotation_degrees,
                    scale = excluded.scale,
                    locked = excluded.locked,
                    min_x = excluded.min_x,
                    max_x = excluded.max_x,
                    min_y = excluded.min_y,
                    max_y = excluded.max_y,
                    min_z = excluded.min_z,
                    max_z = excluded.max_z,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    instance_id, scene_id, room_id or None, asset_id,
                    rhino_guid or None,
                    float(x_mm), float(y_mm), float(z_mm),
                    float(rotation_degrees), float(scale), int(bool(locked)),
                    *bounds, _json(metadata or {}), now, now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM instances WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            connection.execute(
                "DELETE FROM instance_rtree WHERE instance_rowid = ?",
                (row["id"],),
            )
            connection.execute(
                """
                INSERT INTO instance_rtree(
                    instance_rowid, min_x, max_x, min_y, max_y, min_z, max_z
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (row["id"], *bounds),
            )
            revision = self._record_revision(
                connection, scene_id, "upsert_instance", patch
            )
        return {
            "instance_id": instance_id,
            "scene_id": scene_id,
            "asset_id": asset_id,
            "world_aabb_mm": {
                "min": [bounds[0], bounds[2], bounds[4]],
                "max": [bounds[1], bounds[3], bounds[5]],
            },
            "revision": revision,
        }

    @staticmethod
    def _world_aabb(
        asset: dict[str, Any],
        x: float,
        y: float,
        z: float,
        rotation_degrees: float,
        scale: float,
    ) -> tuple[float, float, float, float, float, float]:
        dimensions = asset.get("dimensions_mm", {})
        width = float(dimensions.get("width", 0))
        depth = float(dimensions.get("depth", 0))
        height = float(dimensions.get("height", 0))
        bounds = asset.get("spatial", {}).get("local_aabb", {})
        minimum = bounds.get("min", [-width / 2, -depth / 2, 0])
        maximum = bounds.get("max", [width / 2, depth / 2, height])
        angle = math.radians(rotation_degrees)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        world_xy = []
        for local_x in (float(minimum[0]), float(maximum[0])):
            for local_y in (float(minimum[1]), float(maximum[1])):
                scaled_x = local_x * scale
                scaled_y = local_y * scale
                world_xy.append((
                    x + scaled_x * cosine - scaled_y * sine,
                    y + scaled_x * sine + scaled_y * cosine,
                ))
        return (
            min(point[0] for point in world_xy),
            max(point[0] for point in world_xy),
            min(point[1] for point in world_xy),
            max(point[1] for point in world_xy),
            z + float(minimum[2]) * scale,
            z + float(maximum[2]) * scale,
        )

    def validate_scene(self, scene_id: str, limit: int = 100) -> dict[str, Any]:
        if not self.get_scene(scene_id):
            raise KeyError(f"Unknown scene_id: {scene_id}")
        limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            collision_rows = connection.execute(
                """
                SELECT
                    ia.instance_id AS a,
                    ib.instance_id AS b,
                    ia.asset_id AS asset_a,
                    ib.asset_id AS asset_b
                FROM instance_rtree ra
                JOIN instance_rtree rb ON ra.instance_rowid < rb.instance_rowid
                    AND ra.min_x < rb.max_x AND ra.max_x > rb.min_x
                    AND ra.min_y < rb.max_y AND ra.max_y > rb.min_y
                    AND ra.min_z < rb.max_z AND ra.max_z > rb.min_z
                JOIN instances ia ON ia.id = ra.instance_rowid
                JOIN instances ib ON ib.id = rb.instance_rowid
                WHERE ia.scene_id = ? AND ib.scene_id = ?
                ORDER BY ia.instance_id, ib.instance_id
                LIMIT ?
                """,
                (scene_id, scene_id, limit),
            ).fetchall()
            outside_rows = connection.execute(
                """
                SELECT i.instance_id, i.room_id
                FROM instances i
                JOIN rooms r ON r.room_id = i.room_id
                WHERE i.scene_id = ?
                  AND (
                    i.min_x < r.min_x OR i.max_x > r.max_x OR
                    i.min_y < r.min_y OR i.max_y > r.max_y OR
                    i.min_z < r.min_z OR i.max_z > r.max_z
                  )
                ORDER BY i.instance_id
                LIMIT ?
                """,
                (scene_id, limit),
            ).fetchall()
        collisions = [
            {
                "instances": [row["a"], row["b"]],
                "assets": [row["asset_a"], row["asset_b"]],
                "kind": "physical_aabb",
            }
            for row in collision_rows
        ]
        outside = [
            {"instance_id": row["instance_id"], "room_id": row["room_id"]}
            for row in outside_rows
        ]
        return {
            "scene_id": scene_id,
            "passed": not collisions and not outside,
            "collision_count": len(collisions),
            "outside_room_count": len(outside),
            "collisions": collisions,
            "outside_room": outside,
            "method": "rtree_world_aabb_broad_phase",
        }

    def _record_revision(
        self,
        connection: sqlite3.Connection,
        scene_id: str,
        operation: str,
        patch: dict[str, Any],
    ) -> int:
        row = connection.execute(
            "SELECT revision FROM scenes WHERE scene_id = ?",
            (scene_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"Unknown scene_id: {scene_id}")
        revision = int(row["revision"]) + 1
        now = _utc_now()
        connection.execute(
            "UPDATE scenes SET revision = ?, updated_at = ? WHERE scene_id = ?",
            (revision, now, scene_id),
        )
        connection.execute(
            """
            INSERT INTO scene_revisions(scene_id, revision, operation, patch_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scene_id, revision, operation, _json(patch), now),
        )
        return revision

    # Dependency-aware generation plans --------------------------------

    def create_generation_plan(
        self,
        goal: str,
        scope: str = "house",
        scene_id: str = "",
    ) -> dict[str, Any]:
        scope = scope.lower().strip()
        if scope not in {"house", "interior", "structure", "drawing"}:
            raise ValueError("scope must be house, interior, structure, or drawing.")
        if scene_id and not self.get_scene(scene_id):
            raise KeyError(f"Unknown scene_id: {scene_id}")
        templates = {
            "house": [
                ("programme", "reason", []),
                ("retrieve_structural_logic", "retrieve", ["programme"]),
                ("generate_structure", "execute", ["retrieve_structural_logic"]),
                ("validate_structure", "validate", ["generate_structure"]),
                ("define_rooms", "execute", ["validate_structure"]),
                ("retrieve_assets", "retrieve", ["define_rooms"]),
                ("place_assets", "execute", ["retrieve_assets"]),
                ("validate_layout", "validate", ["place_assets"]),
                ("resolve_collisions", "resolve", ["validate_layout"]),
                ("final_validation", "validate", ["resolve_collisions"]),
            ],
            "interior": [
                ("inspect_rooms", "reason", []),
                ("retrieve_assets", "retrieve", ["inspect_rooms"]),
                ("place_assets", "execute", ["retrieve_assets"]),
                ("validate_layout", "validate", ["place_assets"]),
                ("resolve_collisions", "resolve", ["validate_layout"]),
                ("final_validation", "validate", ["resolve_collisions"]),
            ],
            "structure": [
                ("programme", "reason", []),
                ("retrieve_structural_logic", "retrieve", ["programme"]),
                ("generate_structure", "execute", ["retrieve_structural_logic"]),
                ("validate_structure", "validate", ["generate_structure"]),
            ],
            "drawing": [
                ("freeze_scene", "reason", []),
                ("retrieve_drawing_recipe", "retrieve", ["freeze_scene"]),
                ("retrieve_drawing_assets", "retrieve", ["retrieve_drawing_recipe"]),
                ("prepare_drawing_layers", "execute", ["retrieve_drawing_recipe"]),
                ("configure_projection", "execute", ["prepare_drawing_layers"]),
                ("generate_linework", "execute", ["configure_projection"]),
                ("apply_graphic_styles", "execute", ["generate_linework"]),
                ("create_layout", "execute", ["apply_graphic_styles"]),
                ("export_drawing", "execute", ["create_layout"]),
                ("validate_drawing", "validate", ["export_drawing"]),
            ],
        }
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_plans(
                    plan_id, scene_id, scope, goal, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (plan_id, scene_id or None, scope, goal.strip(), now, now),
            )
            for position, (step_id, kind, dependencies) in enumerate(templates[scope]):
                connection.execute(
                    """
                    INSERT INTO generation_plan_steps(
                        plan_id, step_id, position, kind, status,
                        depends_on_json, input_refs_json, output_refs_json
                    ) VALUES (?, ?, ?, ?, 'pending', ?, '[]', '[]')
                    """,
                    (plan_id, step_id, position, kind, _json(dependencies)),
                )
        return self.get_generation_plan(plan_id)

    def get_generation_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            plan = connection.execute(
                "SELECT * FROM generation_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if not plan:
                return None
            steps = connection.execute(
                """
                SELECT step_id, kind, status, depends_on_json,
                       input_refs_json, output_refs_json
                FROM generation_plan_steps
                WHERE plan_id = ?
                ORDER BY position
                """,
                (plan_id,),
            ).fetchall()
        return {
            "plan_id": plan["plan_id"],
            "scene_id": plan["scene_id"],
            "scope": plan["scope"],
            "goal": plan["goal"],
            "status": plan["status"],
            "steps": [
                {
                    "step_id": step["step_id"],
                    "kind": step["kind"],
                    "status": step["status"],
                    "depends_on": _decode(step["depends_on_json"], []),
                    "input_refs": _decode(step["input_refs_json"], []),
                    "output_refs": _decode(step["output_refs_json"], []),
                }
                for step in steps
            ],
        }

    def update_plan_step(
        self,
        plan_id: str,
        step_id: str,
        status: str,
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        status = status.lower().strip()
        if status not in {"pending", "running", "completed", "failed", "blocked"}:
            raise ValueError("Unsupported step status.")
        plan = self.get_generation_plan(plan_id)
        if not plan:
            raise KeyError(f"Unknown plan_id: {plan_id}")
        step_map = {step["step_id"]: step for step in plan["steps"]}
        if step_id not in step_map:
            raise KeyError(f"Unknown step_id: {step_id}")
        if status in {"running", "completed"}:
            incomplete = [
                dependency
                for dependency in step_map[step_id]["depends_on"]
                if step_map[dependency]["status"] != "completed"
            ]
            if incomplete:
                raise ValueError(
                    f"Step dependencies are incomplete: {', '.join(incomplete)}"
                )

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE generation_plan_steps
                SET status = ?, input_refs_json = ?, output_refs_json = ?
                WHERE plan_id = ? AND step_id = ?
                """,
                (
                    status,
                    _json(input_refs or []),
                    _json(output_refs or []),
                    plan_id,
                    step_id,
                ),
            )
            statuses = [
                row["status"]
                for row in connection.execute(
                    "SELECT status FROM generation_plan_steps WHERE plan_id = ?",
                    (plan_id,),
                )
            ]
            plan_status = (
                "failed" if "failed" in statuses
                else "blocked" if "blocked" in statuses
                else "completed" if all(item == "completed" for item in statuses)
                else "running" if any(item in {"running", "completed"} for item in statuses)
                else "pending"
            )
            connection.execute(
                "UPDATE generation_plans SET status = ?, updated_at = ? WHERE plan_id = ?",
                (plan_status, _utc_now(), plan_id),
            )
        return self.get_generation_plan(plan_id)

