@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0process.ps1" %*
echo.
pause
