@echo off
rem Находит python.exe и pythonw.exe: сначала стандартная установка, затем PATH.
set "PY="
set "PYW="
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
  goto :found
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
  goto :found
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  set "PYW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
  goto :found
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  set "PYW=%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
  goto :found
)
where python >nul 2>&1 && (
  set "PY=python"
  set "PYW=pythonw"
  goto :found
)
echo.
echo [Ошибка] Python 3.10+ не найден.
echo Установите с https://www.python.org/downloads/
echo При установке отметьте "Add python.exe to PATH".
echo.
exit /b 1
:found
exit /b 0
