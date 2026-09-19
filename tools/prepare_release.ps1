# Build-only release pipeline; no upload, install into Rhino, or live MCP changes.
[CmdletBinding()]
param([string]$YakExecutable = "C:\Program Files\Rhino 8\System\Yak.exe")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$scratch = Join-Path ([IO.Path]::GetTempPath()) ("almond-release-" + [guid]::NewGuid().ToString("N"))
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
$previousLinkMode = $env:UV_LINK_MODE
$previousHost = $env:ALMOND_ARCHIVE_TEST_HOST
$env:UV_PROJECT_ENVIRONMENT = Join-Path $scratch "build-env"
$env:UV_LINK_MODE = "copy"
Push-Location $repo
try {
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Dependency sync failed." }
    $python = Join-Path $env:UV_PROJECT_ENVIRONMENT "Scripts/python.exe"
    $version = & $python -c 'from almond_mcp import __version__; print(__version__)'
    if ($LASTEXITCODE -ne 0) { throw "Version read failed." }
    $output = Join-Path $repo "dist/release-$version"
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    & dotnet build tests/archive_host/ArchiveHost.csproj -c Release -o (Join-Path $scratch "host")
    if ($LASTEXITCODE -ne 0) { throw "Archive host build failed." }
    $env:ALMOND_ARCHIVE_TEST_HOST = Join-Path $scratch "host/ArchiveHost.exe"
    & $python -m pytest -q --junitxml (Join-Path $output "tests.xml")
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    & $python tools/document_generation_sources.py --check
    if ($LASTEXITCODE -ne 0) { throw "Source check failed." }
    & uv build --out-dir $output
    if ($LASTEXITCODE -ne 0) { throw "Python build failed." }
    $wheel = @(Get-ChildItem -LiteralPath $output -Filter *.whl)
    if ($wheel.Count -ne 1) { throw "Expected one wheel in release directory." }
    & $python tools/verify_release.py $wheel[0].FullName
    if ($LASTEXITCODE -ne 0) { throw "Python package verification failed." }
    $install = Join-Path $scratch "install-env"
    & uv venv $install
    if ($LASTEXITCODE -ne 0) { throw "Clean environment creation failed." }
    $installedPython = Join-Path $install "Scripts/python.exe"
    & uv pip install --python $installedPython $wheel[0].FullName
    if ($LASTEXITCODE -ne 0) { throw "Clean wheel install failed." }
    Push-Location $scratch
    try {
        & $installedPython (Join-Path $repo "tools/verify_object_archive_install.py") (Join-Path $output "clean-install.json")
        if ($LASTEXITCODE -ne 0) { throw "Installed package smoke test failed." }
    } finally { Pop-Location }
    & (Join-Path $repo "tools/build_yak.ps1") -PythonExecutable $python -YakExecutable $YakExecutable
    [xml]$project = Get-Content -LiteralPath (Join-Path $repo "RhinoAlmondBridge/RhinoAlmondBridge.csproj")
    $bridgeVersion = $project.Project.PropertyGroup.Version
    $yakName = "almondbridge-$bridgeVersion-rh8_0-win.yak"
    Copy-Item -LiteralPath (Join-Path $repo "dist/yak/$yakName") -Destination $output
    & $python tools/verify_yak.py (Join-Path $output $yakName) --report (Join-Path $output "yak-verification.json")
    if ($LASTEXITCODE -ne 0) { throw "Final Yak check failed." }
    Copy-Item -LiteralPath (Join-Path $repo "docs/rhino-archive-quickstart.md") -Destination $output
    Copy-Item -LiteralPath (Join-Path $repo "docs/food4rhino-listing.md") -Destination $output
    $zip = Join-Path $output "almondbridge-$bridgeVersion-food4rhino.zip"
    Compress-Archive -LiteralPath @((Join-Path $output $yakName), (Join-Path $output "rhino-archive-quickstart.md")) -DestinationPath $zip -Force
    $checksums = Get-ChildItem -LiteralPath $output -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" -and $_.Name -notlike ".*" } | Sort-Object Name | ForEach-Object {
        "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.Name
    }
    $checksums | Set-Content -LiteralPath (Join-Path $output "SHA256SUMS.txt") -Encoding ascii
    Write-Host "Prepared release artifacts: $output"
    Write-Host "Pending: Rhino in-process smoke test and explicit publication. Nothing has been uploaded."
} finally {
    Pop-Location
    $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    $env:UV_LINK_MODE = $previousLinkMode
    $env:ALMOND_ARCHIVE_TEST_HOST = $previousHost
}
