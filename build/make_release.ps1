# Build release: exe + setup ZIP.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot "build.ps1")

$Python = $null
foreach ($v in 313, 312, 311, 310) {
    $cand = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
    if (Test-Path $cand) { $Python = $cand; break }
}
$Version = (& $Python -c "import sys; sys.path.insert(0, r'$Root'); from organizer import __version__; print(__version__)").Trim()

$Stage = Join-Path $Root "dist\FileOrganizer-Setup-$Version-win64"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $Stage "FileOrganizer") -Force | Out-Null
Copy-Item (Join-Path $Root "dist\FileOrganizer\*") (Join-Path $Stage "FileOrganizer") -Recurse
Copy-Item (Join-Path $Root "install.bat") $Stage
Copy-Item (Join-Path $Root "installer") $Stage -Recurse

$SetupZip = Join-Path $Root "dist\FileOrganizer-Setup-$Version-win64.zip"
if (Test-Path $SetupZip) { Remove-Item $SetupZip -Force }
# Compress-Archive can silently produce a 0-byte zip on large trees; use .NET instead.
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $Stage,
    $SetupZip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $true
)

$zipLen = (Get-Item $SetupZip).Length
if ($zipLen -lt 1MB) {
    throw "Setup ZIP too small ($zipLen bytes) — packaging failed: $SetupZip"
}

Write-Host ""
Write-Host "Setup ZIP: $SetupZip ($([math]::Round($zipLen / 1MB, 1)) MB)"
