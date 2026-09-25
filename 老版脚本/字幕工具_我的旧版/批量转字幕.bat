@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if not defined PY if exist "C:\Users\Halpc_TUF\Documents\软件\AsrTools-v1.1.0\runtime\python.exe" set "PY=C:\Users\Halpc_TUF\Documents\软件\AsrTools-v1.1.0\runtime\python.exe"
if not defined PY for %%I in (python.exe) do if not defined PY set "PY=%%~$PATH:I"
if not defined PY goto nopython
"%PY%" "%~dp0bcut_transcribe.py" %*
goto done
:nopython
echo.
echo [ERROR] python.exe not found.
echo Please copy the AsrTools runtime folder here and rename it to: python
echo.
:done
pause
