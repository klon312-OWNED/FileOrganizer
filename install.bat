@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  ========================================
echo   Установка FileOrganizer
echo  ========================================
echo.
set /p AUTOSTART="Добавить фоновый агент в автозагрузку? (y/N): "
if /i "%AUTOSTART%"=="y" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\setup.ps1" -Autostart
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\setup.ps1"
)
pause
