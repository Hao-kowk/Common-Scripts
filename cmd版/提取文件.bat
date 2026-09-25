@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0提取文件_v1.0.ps1" %*
echo.
pause
