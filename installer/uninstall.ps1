# Удаление FileOrganizer (программа; настройки в ~/.file_organizer сохраняются).
$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\FileOrganizer"

Get-Process FileOrganizer, FileOrganizerAgent -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

$paths = @(
    (Join-Path $env:LOCALAPPDATA "Programs\FileOrganizer"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "FileOrganizer.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "FileOrganizer"),
    (Join-Path ([Environment]::GetFolderPath("Startup")) "FileOrganizerAgent.lnk")
)

foreach ($p in $paths) {
    if (Test-Path $p) {
        Remove-Item $p -Recurse -Force
        Write-Host "Удалено: $p"
    }
}

Write-Host "FileOrganizer удалён. Настройки остались в $env:USERPROFILE\.file_organizer"
