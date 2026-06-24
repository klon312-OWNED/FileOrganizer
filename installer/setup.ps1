# Установка FileOrganizer в %LOCALAPPDATA%\Programs\FileOrganizer
param(
    [switch]$Autostart,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\FileOrganizer"
$ScriptDir = Split-Path $PSScriptRoot -Leaf
$Root = if ($ScriptDir -eq "installer") { Split-Path $PSScriptRoot -Parent } else { $PSScriptRoot }

# Источник: собранная папка dist или portable-распаковка рядом с installer
$Source = Join-Path $Root "dist\FileOrganizer"
if (-not (Test-Path (Join-Path $Source "FileOrganizer.exe"))) {
    $Source = Join-Path $Root "FileOrganizer"
}
if (-not (Test-Path (Join-Path $Source "FileOrganizer.exe"))) {
    $Source = $Root
}
if (-not (Test-Path (Join-Path $Source "FileOrganizer.exe"))) {
    Write-Host "[Ошибка] FileOrganizer.exe не найден. Сначала соберите проект: build\build.ps1" -ForegroundColor Red
    if (-not $Silent) { Read-Host "Нажмите Enter" }
    exit 1
}

function New-Shortcut($Target, $Args, $LinkPath, $Description, $WorkDir) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($LinkPath)
    $lnk.TargetPath = $Target
    if ($Args) { $lnk.Arguments = $Args }
    $lnk.WorkingDirectory = $WorkDir
    $lnk.Description = $Description
    $lnk.WindowStyle = 1
    $lnk.Save()
}

Write-Host "Установка FileOrganizer..."
Write-Host "  Из:  $Source"
Write-Host "  В:   $InstallDir"

if (Test-Path $InstallDir) {
    Get-Process FileOrganizer, FileOrganizerAgent -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Remove-Item $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $InstallDir -Recurse -Force

$MgrExe = Join-Path $InstallDir "FileOrganizer.exe"
$AgentExe = Join-Path $InstallDir "FileOrganizerAgent.exe"
$Desktop = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "FileOrganizer"
New-Item -ItemType Directory -Path $StartMenu -Force | Out-Null

New-Shortcut $MgrExe $null (Join-Path $Desktop "FileOrganizer.lnk") "Сортировщик файлов" $InstallDir
New-Shortcut $MgrExe $null (Join-Path $StartMenu "FileOrganizer.lnk") "Менеджер файлов" $InstallDir
New-Shortcut $AgentExe $null (Join-Path $StartMenu "Фоновый агент.lnk") "Фоновая сортировка" $InstallDir

$Startup = [Environment]::GetFolderPath("Startup")
$StartupLnk = Join-Path $Startup "FileOrganizerAgent.lnk"
if ($Autostart) {
    New-Shortcut $AgentExe $null $StartupLnk "Фоновый агент сортировки" $InstallDir
} elseif (Test-Path $StartupLnk) {
    Remove-Item $StartupLnk -Force
}

Write-Host ""
Write-Host "Установка завершена!" -ForegroundColor Green
Write-Host "  Ярлык на рабочем столе: FileOrganizer"
Write-Host "  Папка: $InstallDir"
if ($Autostart) { Write-Host "  Фоновый агент добавлен в автозагрузку." }

if (-not $Silent) {
    $launch = Read-Host "Запустить менеджер сейчас? (Y/n)"
    if ($launch -ne "n" -and $launch -ne "N") {
        Start-Process $MgrExe
    }
}
