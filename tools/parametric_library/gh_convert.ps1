# Convert Grasshopper archives between binary .gh and XML .ghx using Rhino 8's GH_IO.dll.
# Reads/writes the archive tree only; no component is instantiated or solved, embedded scripts never run.
# Usage: powershell -File gh_convert.ps1 -InputPath <file|dir> -OutDir <dir> [-ToBinary]
param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [switch]$ToBinary
)
$ErrorActionPreference = 'Stop'
Add-Type -Path 'C:\Program Files\Rhino 8\Plug-ins\Grasshopper\GH_IO.dll'
New-Item -ItemType Directory -Force $OutDir | Out-Null
$pattern = if ($ToBinary) { '*.ghx' } else { '*.gh' }
$files = if (Test-Path $InputPath -PathType Container) {
    Get-ChildItem -Path $InputPath -Recurse -Filter $pattern | Where-Object { $_.Extension -eq $pattern.Substring(1) }
} else { Get-Item $InputPath }
$results = @()
foreach ($f in $files) {
    $archive = New-Object GH_IO.Serialization.GH_Archive
    $ext = if ($ToBinary) { '.gh' } else { '.ghx' }
    $rel = if (Test-Path $InputPath -PathType Container) {
        $f.FullName.Substring((Resolve-Path $InputPath).Path.Length).TrimStart('\')
    } else { $f.Name }
    $target = Join-Path $OutDir ([IO.Path]::ChangeExtension($rel, $ext))
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    $ok = $false; $err = ''
    try {
        $ok = $archive.ReadFromFile($f.FullName)
        if ($ok) {
            if ($ToBinary) { if (-not $archive.WriteToFile($target, $true, $false)) { throw "write failed" } }
            else { [IO.File]::WriteAllText($target, $archive.Serialize_Xml(), (New-Object Text.UTF8Encoding($false))) }
        }
    } catch { $err = $_.Exception.Message }
    $results += [pscustomobject]@{ source = $f.FullName; target = $target; ok = $ok; error = $err;
        messages = ($archive.Messages | ForEach-Object { $_.Message }) -join ' | ' }
}
$results | ConvertTo-Json -Depth 3
