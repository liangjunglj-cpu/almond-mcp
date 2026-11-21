# Build-only release pipeline; no upload, install into Rhino, or live MCP changes.
[CmdletBinding()]
param([string]$YakExecutable = "C:\Program Files\Rhino 8\System\Yak.exe")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$scratch = Join-Path ([IO.Path]::GetTempPath()) ("almond-release-" + [guid]::NewGuid().ToString("N"))
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
$previousLinkMode = $env:UV_LINK_MODE
$previousHost = $env:ALMOND_ARCHIVE_TEST_HOST
$previousModelBase = $env:ALMOND_MODEL_BASE_URL
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
    $sdist = @(Get-ChildItem -LiteralPath $output -Filter *.tar.gz)
    if ($sdist.Count -ne 1) { throw "Expected one sdist in release directory." }
    if ($wheel[0].Length -ge 100MB) { throw "Wheel is $([math]::Round($wheel[0].Length / 1MB, 1)) MiB; PyPI refuses files over 100 MB." }
    # The wheel has no generated model files; installs download them from the GitHub release
    # v<version>. Stage every verified GLB + contract (from the sdist) for that upload.
    $models = Join-Path $output "models"
    if (Test-Path -LiteralPath $models) { Remove-Item -LiteralPath $models -Recurse -Force }
    & $python tools/verify_release.py $wheel[0].FullName --sdist $sdist[0].FullName --stage-models $models
    if ($LASTEXITCODE -ne 0) { throw "Python package verification failed." }
    $install = Join-Path $scratch "install-env"
    & uv venv $install
    if ($LASTEXITCODE -ne 0) { throw "Clean environment creation failed." }
    $installedPython = Join-Path $install "Scripts/python.exe"
    & uv pip install --python $installedPython $wheel[0].FullName
    if ($LASTEXITCODE -ne 0) { throw "Clean wheel install failed." }
    Push-Location $scratch
    try {
        # The clean install downloads models on first use: serve them from the staged release folder.
        $env:ALMOND_MODEL_BASE_URL = ([Uri]((Resolve-Path -LiteralPath $models).Path + "\")).AbsoluteUri.TrimEnd("/")
        & $installedPython (Join-Path $repo "tools/verify_object_archive_install.py") (Join-Path $output "clean-install.json")
        if ($LASTEXITCODE -ne 0) { throw "Installed package smoke test failed." }
    } finally { Pop-Location; $env:ALMOND_MODEL_BASE_URL = $previousModelBase }
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
    $checksums = @(Get-ChildItem -LiteralPath $output -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" -and $_.Name -notlike ".*" } | Sort-Object Name | ForEach-Object {
        "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.Name
    })
    # The release model files sit in models/ (uploaded flat as release assets).
    $checksums += Get-ChildItem -LiteralPath $models -File | Sort-Object Name | ForEach-Object {
        "{0}  models/{1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.Name
    }
    $checksums | Set-Content -LiteralPath (Join-Path $output "SHA256SUMS.txt") -Encoding ascii
    Write-Host "Prepared release artifacts: $output"
    Write-Host "Pending: Rhino in-process smoke test and explicit publication. Nothing has been uploaded."
    # PyPI gets the wheel only: the sdist carries the models plus the generation evidence and is over
    # PyPI's 100 MB file limit. It goes to the GitHub release with the Yak, SHA256SUMS.txt and the
    # model files, which wheel installs download on first use (almond_mcp/model_store.py).
    Write-Host "PyPI (wheel only): uv publish `"$($wheel[0].FullName)`""
    Write-Host ("GitHub release only: {0} ({1:N1} MiB)" -f $sdist[0].Name, ($sdist[0].Length / 1MB))
    $modelFiles = @(Get-ChildItem -LiteralPath $models -File)
    Write-Host ("GitHub release model files: {0} files ({1:N1} MiB) in {2}" -f $modelFiles.Count, (($modelFiles | Measure-Object Length -Sum).Sum / 1MB), $models)
    Write-Host "Attach them to the release BEFORE publishing the wheel to PyPI (installs download from it):"
    Write-Host "  gh release upload v$version (Get-ChildItem -LiteralPath `"$models`" -File).FullName"
} finally {
    Pop-Location
    $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    $env:UV_LINK_MODE = $previousLinkMode
    $env:ALMOND_ARCHIVE_TEST_HOST = $previousHost
    $env:ALMOND_MODEL_BASE_URL = $previousModelBase
}
