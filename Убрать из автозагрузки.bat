@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$startup = [Environment]::GetFolderPath('Startup');" ^
  "$p = Join-Path $startup 'FileOrganizerAgent.lnk';" ^
  "if (Test-Path $p) { Remove-Item $p; Write-Host 'Удалено из автозагрузки.' } else { Write-Host 'Ярлык не найден.' }"
pause
