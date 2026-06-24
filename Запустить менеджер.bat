@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_python.bat"
if errorlevel 1 pause & exit /b 1
start "" "%PYW%" "%~dp0run.py"
