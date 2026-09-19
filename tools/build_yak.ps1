# Fresh isolated build. Does not install or publish anything.
[CmdletBinding()]
param(
    [string]$PythonExecutable = "python",
    [string]$YakExecutable = "C:\Program Files\Rhino 8\System\Yak.exe"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$stageRoot = Join-Path ([IO.Path]::GetTempPath()) ("almond-yak-" + [guid]::NewGuid().ToString("N"))
$stage = Join-Path $stageRoot "package"
$bin = Join-Path $stageRoot "build"
New-Item -ItemType Directory -Path $stage -Force | Out-Null
if (-not (Test-Path -LiteralPath $YakExecutable)) { throw "Yak executable not found: $YakExecutable" }
Push-Location $repo
try {
    & $PythonExecutable tools/document_generation_sources.py --check
    if ($LASTEXITCODE -ne 0) { throw "Source documentation check failed." }
    & dotnet build RhinoAlmondBridge/RhinoAlmondBridge.csproj -c Release -o $bin
    if ($LASTEXITCODE -ne 0) { throw "Bridge build failed." }
    Copy-Item -LiteralPath (Join-Path $bin "RhinoAlmondBridge.dll") -Destination (Join-Path $stage "RhinoAlmondBridge.rhp")
    Get-ChildItem -LiteralPath $bin -Filter *.dll | Where-Object Name -ne "RhinoAlmondBridge.dll" | ForEach-Object {
        if ($_.Name -match '^(RhinoCommon|Grasshopper|GH_IO|Karamba|Kangaroo)') { throw "Forbidden runtime dependency: $($_.Name)" }
        Copy-Item -LiteralPath $_.FullName -Destination $stage
    }
    & $PythonExecutable tools/build_archive_bundle.py (Join-Path $stage "archive")
    if ($LASTEXITCODE -ne 0) { throw "Archive bundle build failed." }
    Copy-Item -LiteralPath (Join-Path $repo "RhinoAlmondBridge/yak/manifest.yml") -Destination $stage
    Copy-Item -LiteralPath (Join-Path $repo "assets/almond-icon-48.png") -Destination (Join-Path $stage "icon.png")
    foreach ($file in @("LICENSE", "THIRD-PARTY-NOTICES.md")) { Copy-Item -LiteralPath (Join-Path $repo $file) -Destination $stage }
    Copy-Item -LiteralPath (Join-Path $repo "docs/rhino-archive-quickstart.md") -Destination (Join-Path $stage "GETTING-STARTED.md")
    Push-Location $stage
    try {
        & $YakExecutable build --platform win
        if ($LASTEXITCODE -ne 0) { throw "Yak build failed." }
    } finally { Pop-Location }
    $packages = @(Get-ChildItem -LiteralPath $stage -Filter *.yak)
    if ($packages.Count -ne 1 -or $packages[0].Name -notmatch '-rh8_0-win\.yak$') { throw "Expected one Rhino 8.0 Windows Yak package." }
    & $PythonExecutable tools/verify_yak.py $packages[0].FullName
    if ($LASTEXITCODE -ne 0) { throw "Yak contents verification failed." }
    $output = Join-Path $repo "dist/yak"
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    Copy-Item -LiteralPath $packages[0].FullName -Destination $output
    Write-Host "Built and verified: $(Join-Path $output $packages[0].Name)"
    Write-Host "Unpublished staging folder: $stage"
} finally { Pop-Location }
