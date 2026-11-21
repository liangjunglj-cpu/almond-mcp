"""Generated model files on demand.

The PyPI wheel carries the generated library's manifest, catalogue and
previews but not the model files (GLB + ``.almond.json`` contract), which
would push it past PyPI's 100 MB file limit. Every code path that opens a
generated model calls :func:`ensure_generated_files` first; in a repository
checkout (or the Rhino plugin) the files are already present and nothing is
downloaded. On a wheel install the first use downloads the two files into the
versioned user data directory (``paths.resolve_dir``).

Download source, in order:

1. ``$ALMOND_MODEL_BASE_URL/<file name>`` when that variable is set (mirror,
   offline share or tests; ``https://``, ``http://`` or ``file://``). It is
   then the only source.
2. the GitHub release of this exact package version:
   ``https://github.com/liangjunglj-cpu/almond-mcp/releases/download/v<version>/<file name>``
3. the manifest's recorded ``download_url`` / ``contract_download_url`` (raw
   files on the repository's master branch), only if it is ``https://``.

The manifest's sha256 is authoritative for every source: a download is
streamed into a temporary file beside the target, hashed, and moved into place
only when the hash matches. A mismatching download is deleted, never kept.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from almond_mcp import __version__, paths

BASE_URL_ENV = "ALMOND_MODEL_BASE_URL"
RELEASE_DOWNLOAD = "https://github.com/liangjunglj-cpu/almond-mcp/releases/download/v{version}"
TIMEOUT_S = 60.0
MAX_BYTES = 200_000_000  # largest generated GLB is ~5 MB; refuse anything absurd
FETCH_HINT = ("run `almond-mcp fetch-assets --generated` on a connected machine "
              f"(or point {BASE_URL_ENV} at a folder or mirror holding the release's model files)")

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_verified: dict[str, tuple[int, int]] = {}  # path -> (size, mtime_ns) whose hash matched


class ModelUnavailable(OSError):
    """A generated model file is not on disk and could not be downloaded.

    An OSError, so callers that already report file errors report this too."""


def library_dir() -> Path:
    return Path(paths.resolve_dir("RHINO_MCP_GENERATED_ASSET_DIR"))


def release_base_url(version: str = __version__) -> str:
    return RELEASE_DOWNLOAD.format(version=version)


def _files(asset: dict) -> list[tuple[str, str, str, str]]:
    """(role, manifest relative path, expected sha256, recorded fallback URL) per file."""
    out = [("model", asset.get("file"), asset.get("sha256"), asset.get("download_url"))]
    if asset.get("contract_file"):
        out.append(("contract", asset.get("contract_file"), asset.get("contract_sha256"),
                    asset.get("contract_download_url")))
    return out


def is_obtainable(asset: dict) -> bool:
    """True when every file of *asset* has a verifiable sha256 and a safe release name,
    so it can be fetched on demand."""
    return all(rel and _NAME.match(PurePosixPath(str(rel)).name) and _HEX64.match(str(sha or ""))
               for _, rel, sha, _ in _files(asset))


def _target(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ModelUnavailable(f"Manifest file is outside the generated library: {rel}")
    return target


def is_local(asset: dict, root: Path | None = None) -> bool:
    """Model (and contract) present on disk. Existence only; hashes are checked on use."""
    root = Path(root) if root is not None else library_dir()
    try:
        return all(_target(root, rel).is_file() for _, rel, _, _ in _files(asset) if rel)
    except ModelUnavailable:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _matches(path: Path, expected: str) -> bool:
    stat = path.stat()
    key = str(path)
    if _verified.get(key) == (stat.st_size, stat.st_mtime_ns):
        return True
    if sha256_file(path) != expected.upper():
        return False
    _verified[key] = (stat.st_size, stat.st_mtime_ns)
    return True


def candidate_urls(name: str, recorded: str | None = None, version: str = __version__) -> list[str]:
    """Download URLs for one release file name, in the order they are tried."""
    override = os.environ.get(BASE_URL_ENV, "").strip()
    if override:
        return [override.rstrip("/") + "/" + quote(name)]
    urls = [release_base_url(version) + "/" + quote(name)]
    if recorded and urlsplit(recorded).scheme == "https" and recorded not in urls:
        urls.append(recorded)
    return urls


def _fetch(url: str, target: Path, expected: str, timeout: float) -> None:
    """Stream *url* into a temp file beside *target*; replace *target* only on a hash match."""
    if urlsplit(url).scheme not in {"https", "http", "file"}:
        raise ValueError(f"unsupported URL scheme: {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": f"almond-mcp/{__version__}"})
    handle = tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", suffix=".part", delete=False)
    pending = Path(handle.name)
    try:
        digest, size = hashlib.sha256(), 0
        # Default SSL context: on Windows it reads the system store, so an
        # inspecting corporate proxy's root certificate is trusted.
        with handle, urllib.request.urlopen(request, timeout=timeout) as response:
            for chunk in iter(lambda: response.read(1 << 20), b""):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError(f"download exceeds {MAX_BYTES} bytes")
                digest.update(chunk)
                handle.write(chunk)
        actual = digest.hexdigest().upper()
        if actual != expected.upper():
            raise ValueError(f"sha256 mismatch (expected {expected.upper()}, got {actual})")
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)


def _lock(target: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(target), threading.Lock())


def _in_checkout(root: Path) -> bool:
    repo = paths._repo_dir("GeneratedAssetfiles")
    return repo is not None and repo.resolve() == root.resolve()


def ensure_generated_files(asset: dict, root: Path | str | None = None, *,
                           timeout: float = TIMEOUT_S) -> dict[str, Path]:
    """Return {"model": path, "contract": path} for a generated asset, downloading
    missing or hash-mismatched files first. Raises ModelUnavailable with a clear
    message when a file cannot be obtained."""
    root = Path(root) if root is not None else library_dir()
    asset_id = asset.get("asset_id", "?")
    if not is_obtainable(asset):
        missing = [rel for _, rel, _, _ in _files(asset) if not rel or not _target(root, rel).is_file()]
        if missing:
            raise ModelUnavailable(f"Model file missing for {asset_id} and the manifest has no verifiable "
                                   f"checksum to download it: {', '.join(map(str, missing))}")
        return {role: _target(root, rel) for role, rel, _, _ in _files(asset)}
    result: dict[str, Path] = {}
    for role, rel, expected, recorded in _files(asset):
        target = _target(root, rel)
        with _lock(target):
            if target.is_file() and _matches(target, expected):
                result[role] = target
                continue
            if _in_checkout(root):
                # A source checkout is the source of truth: never download into or overwrite it.
                state = "does not match the manifest sha256" if target.is_file() else "is missing"
                raise ModelUnavailable(f"{rel} in the repository checkout {state} for {asset_id}; "
                                       "rebuild the manifest or restore the file.")
            name = PurePosixPath(rel).name
            errors = []
            for url in candidate_urls(name, recorded):
                try:
                    _fetch(url, target, expected, timeout)
                    _verified.pop(str(target), None)
                    break
                except (OSError, ValueError, urllib.error.URLError) as exc:
                    errors.append(f"{url}: {exc}")
            else:
                raise ModelUnavailable(
                    f"Could not download {name} for {asset_id} (the PyPI package does not include model "
                    f"files). Tried: {'; '.join(errors)}. To fix: {FETCH_HINT}.")
            result[role] = target
    return result


def ensure_all(assets: list[dict], root: Path | str | None = None, *, timeout: float = TIMEOUT_S,
               report=None) -> dict:
    """Prefetch every generated asset. Returns counts plus per-asset errors."""
    root = Path(root) if root is not None else library_dir()
    counts = {"present": 0, "downloaded": 0, "failed": 0}
    errors: dict[str, str] = {}
    for asset in assets:
        was_local = is_local(asset, root)
        try:
            ensure_generated_files(asset, root, timeout=timeout)
        except ModelUnavailable as exc:
            counts["failed"] += 1
            errors[asset.get("asset_id", "?")] = str(exc)
            if report:
                report("failed", asset, str(exc))
            continue
        state = "present" if was_local else "downloaded"
        counts[state] += 1
        if report:
            report(state, asset, "")
    return {**counts, "errors": errors, "library_dir": str(root)}
