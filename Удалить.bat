@echo off
chcp 65001 >nul
echo Удаление FileOrganizer...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\uninstall.ps1"
pause
