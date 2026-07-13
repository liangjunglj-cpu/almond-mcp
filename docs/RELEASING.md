# Releasing almond-mcp

Two artifacts ship per release: the Python package (PyPI) and the bridge
(Yak). Keep their versions in lockstep — `pyproject.toml`,
`almond_mcp/__init__.py.__version__`, and `RhinoAlmondBridge/yak/manifest.yml`.
Exception: Yak listings are immutable, so a metadata-only fix (description,
keywords, icon) is re-pushed as a bridge-only patch bump without a PyPI
release (e.g. bridge 0.2.1 over python 0.2.0).

## Pre-flight

```powershell
$env:UV_LINK_MODE = 'copy'      # OneDrive checkouts only
uv run pytest                    # 23 tests, no Rhino needed
uv run almond-mcp doctor         # with Rhino + bridge running
uv build                         # wheel + sdist into dist/
```

Audit the artifacts before publishing — **no .skp/.ghx/.dll may appear**:

```powershell
uv run python -c "import zipfile; print('\n'.join(zipfile.ZipFile(sorted(__import__('glob').glob('dist/*.whl'))[-1]).namelist()))"
```

Re-read `docs/licensing-audit.md` if any asset or dependency changed.

## PyPI

First time: create the `almond-mcp` project by publishing; get an API token
from https://pypi.org/manage/account/token/.

```powershell
# dry run against TestPyPI first
uv publish --publish-url https://test.pypi.org/legacy/ --token $env:TEST_PYPI_TOKEN
uvx --index-url https://test.pypi.org/simple/ --from almond-mcp almond-mcp --version

# the real thing
uv publish --token $env:PYPI_TOKEN
```

## Yak (bridge)

Build the plugin in Visual Studio (Release), then:

```powershell
powershell -File tools\build_yak.ps1        # assembles + builds dist\yak\*.yak
& "C:\Program Files\Rhino 8\System\Yak.exe" login          # Rhino account
& "C:\Program Files\Rhino 8\System\Yak.exe" push dist\yak\almondbridge-0.2.0-rh8_0-any.yak
& "C:\Program Files\Rhino 8\System\Yak.exe" search almondbridge   # verify
```

Test locally before pushing: `_PackageManager` → gear icon → "Install from
file". Yak versions are immutable once pushed — bump the version for any fix.

When rebuilding the plugin, set `<Version>` in `RhinoAlmondBridge.csproj` to
the release version so the assembly version matches the manifest (yak warns
on mismatch but still builds).

## After publishing

1. Tag: `git tag v0.2.0 && git push --tags`.
2. Smoke-test the true first-run path on a machine (or fresh user profile)
   without a checkout: `uvx almond-mcp doctor`, then `fetch-assets`, then a
   Claude conversation that places a furniture block.
3. Optional discoverability: list the server on the MCP registry
   (https://registry.modelcontextprotocol.io) and consider an MCPB bundle
   for one-click Claude Desktop install.
