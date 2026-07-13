# Assemble and build the AlmondBridge Yak package.
#
# Prerequisites: a Release build of RhinoAlmondBridge (see
# RhinoAlmondBridge\BUILD.md) and Rhino 8 installed (for yak.exe).
#
# Usage:  powershell -File tools\build_yak.ps1
# Output: dist\yak\almondbridge-<version>-rh8_0-any.yak

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $repo "dist\yak"
$yak = "C:\Program Files\Rhino 8\System\Yak.exe"

# Prefer a fresh Release build; fall back to the staged binaries checked
# into dist\bridge when building from a clean checkout.
$bin = Join-Path $repo "RhinoAlmondBridge\bin\Release\net48"
if (-not (Test-Path (Join-Path $bin "RhinoAlmondBridge.rhp"))) {
    $bin = Join-Path $repo "dist\bridge"
}
if (-not (Test-Path (Join-Path $bin "RhinoAlmondBridge.rhp"))) {
    throw "No RhinoAlmondBridge.rhp in bin\Release\net48 or dist\bridge - build the plugin first (RhinoAlmondBridge\BUILD.md)."
}
if (-not (Test-Path $yak)) {
    throw "Yak.exe not found at $yak - is Rhino 8 installed?"
}

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -Confirm:$false }
New-Item -ItemType Directory -Force $stage | Out-Null

# Plugin + runtime dependencies (root-level DLLs only; Roslyn satellite
# resource folders are skipped to keep the package small).
Copy-Item (Join-Path $bin "RhinoAlmondBridge.rhp") $stage
Copy-Item (Join-Path $bin "*.dll") $stage
# The .rhp IS the plugin assembly; don't ship the same assembly twice.
Remove-Item (Join-Path $stage "RhinoAlmondBridge.dll") -ErrorAction SilentlyContinue

# Package metadata. THIRD-PARTY-NOTICES.md must ship with the compiled
# bridge (Newtonsoft.Json / Roslyn notices).
Copy-Item (Join-Path $repo "RhinoAlmondBridge\yak\manifest.yml") $stage
Copy-Item (Join-Path $repo "assets\almond-icon-48.png") (Join-Path $stage "icon.png")
Copy-Item (Join-Path $repo "THIRD-PARTY-NOTICES.md") $stage
Copy-Item (Join-Path $repo "LICENSE") $stage

Push-Location $stage
try {
    & $yak build
    Get-ChildItem *.yak | ForEach-Object { Write-Host "Built $($_.FullName)" }
} finally {
    Pop-Location
}
