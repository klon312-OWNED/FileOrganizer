@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Добавляю фоновый агент в автозагрузку Windows...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pyw = $null;" ^
  "foreach ($v in 313,312,311,310) {" ^
  "  $cand = Join-Path $env:LOCALAPPDATA \"Programs\Python\Python$v\pythonw.exe\";" ^
  "  if (Test-Path $cand) { $pyw = $cand; break }" ^
  "};" ^
  "if (-not $pyw) { $pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source };" ^
  "if (-not $pyw) { Write-Host '[Ошибка] Python не найден.' -ForegroundColor Red; exit 1 };" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$startup = [Environment]::GetFolderPath('Startup');" ^
  "$lnk = $ws.CreateShortcut(\"$startup\FileOrganizerAgent.lnk\");" ^
  "$lnk.TargetPath = $pyw;" ^
  "$lnk.Arguments = '\"%~dp0run_background.pyw\"';" ^
  "$lnk.WorkingDirectory = '%~dp0';" ^
  "$lnk.WindowStyle = 7;" ^
  "$lnk.Save();" ^
  "Write-Host 'Готово: ярлык создан в папке автозагрузки.'"
echo.
echo Теперь агент будет запускаться автоматически при входе в Windows.
pause
