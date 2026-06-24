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
Compress-Archive -Path $Stage -DestinationPath $SetupZip -Force

Write-Host ""
Write-Host "Setup ZIP: $SetupZip"
