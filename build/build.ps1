# Build FileOrganizer (PyInstaller) and portable ZIP.
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$Python = $null
foreach ($v in 313, 312, 311, 310) {
    $cand = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
    if (Test-Path $cand) { $Python = $cand; break }
}
if (-not $Python) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python) { throw "Python 3.10+ not found." }

Write-Host "Python: $Python"
& $Python -m pip install -q -r requirements.txt pyinstaller

Write-Host "Running PyInstaller..."
& $Python -m PyInstaller "build\file_organizer.spec" --noconfirm --distpath dist --workpath build\work --clean

$DistDir = Join-Path $Root "dist\FileOrganizer"
if (-not (Test-Path (Join-Path $DistDir "FileOrganizer.exe"))) {
    throw "Build failed: FileOrganizer.exe not found."
}

$Version = (& $Python -c "import sys; sys.path.insert(0, r'$Root'); from organizer import __version__; print(__version__)").Trim()
$ZipName = "FileOrganizer-$Version-win64.zip"
$ZipPath = Join-Path $Root "dist\$ZipName"

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $DistDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Done:"
Write-Host "  $DistDir"
Write-Host "  $ZipPath"
