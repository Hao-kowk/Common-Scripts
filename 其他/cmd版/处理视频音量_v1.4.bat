@echo off
setlocal
set "PS=%~dp0音量处理_v1.4.ps1"
if not exist "%PS%" set "PS=%~dp0process.ps1"
if not exist "%PS%" (
  echo.
  echo [ERROR] 音量处理_v1.4.ps1 not found next to this file.
  echo Please copy both files together.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS%" %*
echo.
pause
