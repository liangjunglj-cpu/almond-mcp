# Fresh isolated build. Does not install or publish anything.
# Produces one Yak per platform, both for every Rhino 8 service release (tag rh8_0):
#   almondbridge-<version>-rh8_0-win.yak  net48 build (unchanged Windows package)
#   almondbridge-<version>-rh8_0-mac.yak  net7.0 build for Rhino 8 for Mac
# Separate distributions rather than one multi-framework "any" package: Rhino 8 for Windows runs .NET 7 by
# default and would load a net7.0 folder, which would change what Windows users run.
[CmdletBinding()]
param(
    [string]$PythonExecutable = "python",
    [string]$YakExecutable = "C:\Program Files\Rhino 8\System\Yak.exe",
    [ValidateSet("all", "win", "mac")]
    [string]$Platform = "all"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$stageRoot = Join-Path ([IO.Path]::GetTempPath()) ("almond-yak-" + [guid]::NewGuid().ToString("N"))
$archive = Join-Path $stageRoot "archive"
if (-not (Test-Path -LiteralPath $YakExecutable)) { throw "Yak executable not found: $YakExecutable" }
$targets = @(
    @{ Platform = "win"; Framework = "net48" },
    @{ Platform = "mac"; Framework = "net7.0" }
) | Where-Object { $Platform -eq "all" -or $_.Platform -eq $Platform }
Push-Location $repo
try {
    & $PythonExecutable tools/document_generation_sources.py --check
    if ($LASTEXITCODE -ne 0) { throw "Source documentation check failed." }
    & $PythonExecutable tools/build_archive_bundle.py $archive
    if ($LASTEXITCODE -ne 0) { throw "Archive bundle build failed." }
    $output = Join-Path $repo "dist/yak"
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    foreach ($target in $targets) {
        $platformTag = $target.Platform
        $stage = Join-Path $stageRoot "package-$platformTag"
        $bin = Join-Path $stageRoot "build-$platformTag"
        New-Item -ItemType Directory -Path $stage -Force | Out-Null
        & dotnet build RhinoAlmondBridge/RhinoAlmondBridge.csproj -c Release -f $target.Framework -o $bin
        if ($LASTEXITCODE -ne 0) { throw "Bridge build failed ($($target.Framework))." }
        Copy-Item -LiteralPath (Join-Path $bin "RhinoAlmondBridge.dll") -Destination (Join-Path $stage "RhinoAlmondBridge.rhp")
        Get-ChildItem -LiteralPath $bin -Filter *.dll | Where-Object Name -ne "RhinoAlmondBridge.dll" | ForEach-Object {
            if ($_.Name -match '^(RhinoCommon|Grasshopper|GH_IO|Eto|Rhino\.UI|Karamba|Kangaroo|System\.Drawing)') { throw "Forbidden runtime dependency: $($_.Name)" }
            Copy-Item -LiteralPath $_.FullName -Destination $stage
        }
        Copy-Item -LiteralPath $archive -Destination (Join-Path $stage "archive") -Recurse
        Copy-Item -LiteralPath (Join-Path $repo "RhinoAlmondBridge/yak/manifest.yml") -Destination $stage
        Copy-Item -LiteralPath (Join-Path $repo "assets/almond-icon-48.png") -Destination (Join-Path $stage "icon.png")
        foreach ($file in @("LICENSE", "THIRD-PARTY-NOTICES.md")) { Copy-Item -LiteralPath (Join-Path $repo $file) -Destination $stage }
        Copy-Item -LiteralPath (Join-Path $repo "docs/rhino-archive-quickstart.md") -Destination (Join-Path $stage "GETTING-STARTED.md")
        Push-Location $stage
        try {
            & $YakExecutable build --platform $platformTag
            if ($LASTEXITCODE -ne 0) { throw "Yak build failed ($platformTag)." }
        } finally { Pop-Location }
        $packages = @(Get-ChildItem -LiteralPath $stage -Filter *.yak)
        if ($packages.Count -ne 1 -or $packages[0].Name -notmatch "-rh8_0-$platformTag\.yak$") { throw "Expected one Rhino 8.0 $platformTag Yak package." }
        & $PythonExecutable tools/verify_yak.py $packages[0].FullName
        if ($LASTEXITCODE -ne 0) { throw "Yak contents verification failed ($platformTag)." }
        Copy-Item -LiteralPath $packages[0].FullName -Destination $output
        Write-Host "Built and verified: $(Join-Path $output $packages[0].Name)"
        Write-Host "Unpublished staging folder: $stage"
    }
} finally { Pop-Location }
