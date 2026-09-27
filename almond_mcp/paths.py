"""Resolve Almond's library, capsule, and state locations.

Resolution order for every library directory:

1. the explicit ``RHINO_MCP_*`` environment variable;
2. a directory of the same name at the repository root (development
   checkout — the directory sits next to the ``almond_mcp`` package);
3. the per-user data directory (``%LOCALAPPDATA%\\Almond`` on Windows),
   scaffolded on first use from the manifests bundled inside the wheel.

Third-party downloaded geometry is never bundled. The generated library
is bundled in full, and scaffolded into a versioned directory so upgrades
cannot reuse an old manifest or overwrite a user's previous asset pack.
"""
from __future__ import annotations

import os
import shutil
import sys
from importlib import resources
from pathlib import Path
from almond_mcp import __version__

APP_NAME = "Almond"

# One name drives all three locations: the repo directory, the wheel's
# bundled almond_mcp/data/<name>, and the user data directory.
LIBRARY_DIRS = {
    "RHINO_MCP_LIBRARY_DIR": "Grasshopperfiles",
    "RHINO_MCP_DRAWING_ASSET_DIR": "DrawingAssetfiles",
    "RHINO_MCP_DIAGRAM_ASSET_DIR": "DiagramAssetfiles",
    "RHINO_MCP_GENERATED_ASSET_DIR": "GeneratedAssetfiles",
    "RHINO_MCP_DRAWING_RECIPE_DIR": "DrawingRecipes",
    "RHINO_MCP_DRAFTING_DIR": "Draftingfiles",
    "RHINO_MCP_CAPSULE_DIR": "capsules",
    "RHINO_MCP_MATERIAL_DIR": "Materialfiles",
    "RHINO_MCP_CONSTRUCTION_DIR": "Constructionfiles",
    "RHINO_MCP_HISTORY_DIR": "Historyfiles",
}

STATE_DB_ENV = "RHINO_MCP_STATE_DB"
STATE_DB_NAME = "almond_state.sqlite3"


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def _repo_dir(name: str) -> Path | None:
    candidate = Path(__file__).resolve().parents[1] / name
    return candidate if candidate.is_dir() else None


def _bundled_data(name: str):
    """Return the wheel-bundled data directory for *name*, or None in a
    development checkout (where data/ is assembled only at build time)."""
    candidate = resources.files("almond_mcp").joinpath("data", name)
    return candidate if candidate.is_dir() else None


def _copy_missing(source, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        dest = target / entry.name
        if entry.is_dir():
            _copy_missing(entry, dest)
        elif not dest.exists():
            with resources.as_file(entry) as src:
                # Replace atomically; interruption cannot leave half a model.
                import tempfile
                with tempfile.NamedTemporaryFile(dir=target, delete=False) as handle:
                    pending = Path(handle.name)
                try:
                    shutil.copy2(src, pending)
                    os.replace(pending, dest)
                finally:
                    pending.unlink(missing_ok=True)


def _scaffold(name: str, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    bundled = _bundled_data(name)
    if bundled is None:
        return
    if name in {"GeneratedAssetfiles", "Draftingfiles"}:
        _copy_missing(bundled, target)
        return
    for entry in bundled.iterdir():
        dest = target / entry.name
        if dest.exists():
            continue
        if entry.is_dir():
            with resources.as_file(entry) as src:
                shutil.copytree(src, dest)
        else:
            with resources.as_file(entry) as src:
                shutil.copy2(src, dest)


def resolve_dir(env_var: str) -> str:
    """Resolve one of the LIBRARY_DIRS locations to an existing directory."""
    name = LIBRARY_DIRS[env_var]
    explicit = os.environ.get(env_var)
    if explicit:
        return explicit
    repo = _repo_dir(name)
    if repo is not None:
        return str(repo)
    target = user_data_dir() / name
    if name in {"GeneratedAssetfiles", "Draftingfiles"}:
        target = target / "releases" / __version__
    _scaffold(name, target)
    return str(target)


def resolve_state_db() -> str:
    explicit = os.environ.get(STATE_DB_ENV)
    if explicit:
        return explicit
    target = user_data_dir()
    target.mkdir(parents=True, exist_ok=True)
    return str(target / STATE_DB_NAME)
