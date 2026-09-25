@echo off
setlocal
set PYTHONIOENCODING=utf-8
set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if not defined PY if exist "C:\Users\Halpc_TUF\AppData\Local\Programs\Python\Python312\python.exe" set "PY=C:\Users\Halpc_TUF\AppData\Local\Programs\Python\Python312\python.exe"
if not defined PY for %%I in (py.exe) do if not defined PY set "PY=%%~$PATH:I"
if not defined PY for %%I in (python.exe) do if not defined PY set "PY=%%~$PATH:I"
if not defined PY (
  echo.
  echo 【错误】没有找到 Python，程序没法运行。
  echo.
  echo 正常情况下应该有这个文件：
  echo   C:\Users\Halpc_TUF\AppData\Local\Programs\Python\Python312\python.exe
  echo 如果它不见了，说明 Python 被删了或挪位置了。
  echo.
  pause
  exit /b 1
)
"%PY%" "%~dp0..\批量转字幕_v1.2.py" %*
echo.
pause
