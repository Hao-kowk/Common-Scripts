@echo off
chcp 936 >nul
setlocal enabledelayedexpansion

echo ============================================
echo  更新 BiliTools 到「1.4.6 命名优化版」
echo ============================================
echo.

rem ---------- 1. 找新版 exe（就在本文件旁边）----------
set "SRC="
if exist "%~dp0BiliTools_1.4.6_命名优化版.exe" set "SRC=%~dp0BiliTools_1.4.6_命名优化版.exe"
if not defined SRC if exist "%~dp0bilitools.exe" set "SRC=%~dp0bilitools.exe"
if not defined SRC if exist "%~dp0..\BiliTools-构建\src-tauri\target\release\bilitools.exe" set "SRC=%~dp0..\BiliTools-构建\src-tauri\target\release\bilitools.exe"
if not defined SRC (
  echo 【错误】没找到新版 exe。
  echo   请把本文件和「BiliTools_1.4.6_命名优化版.exe」放在同一个文件夹里。
  echo.
  pause
  exit /b 1
)
echo 新版 exe：%SRC%
echo.

rem ---------- 2. 从注册表找 BiliTools 装在哪 ----------
set "INSTDIR="
for /f "tokens=2,*" %%A in ('reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "BiliTools" 2^>nul ^| findstr /i "InstallLocation"') do if not defined INSTDIR set "INSTDIR=%%B"
if not defined INSTDIR for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "BiliTools" 2^>nul ^| findstr /i "InstallLocation"') do if not defined INSTDIR set "INSTDIR=%%B"
if not defined INSTDIR for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "BiliTools" 2^>nul ^| findstr /i "InstallLocation"') do if not defined INSTDIR set "INSTDIR=%%B"

if defined INSTDIR (
  set "INSTDIR=!INSTDIR:"=!"
  echo 安装目录（从注册表读到）：!INSTDIR!
) else (
  echo 没能从注册表找到安装目录。
  echo 请把 BiliTools 的安装文件夹拖进本窗口后按回车（或直接粘贴路径）：
  set /p "INSTDIR="
  set "INSTDIR=!INSTDIR:"=!"
)

if not exist "!INSTDIR!\bilitools.exe" (
  echo.
  echo 【错误】在「!INSTDIR!」里没找到 bilitools.exe，请确认路径填对了。
  echo.
  pause
  exit /b 1
)

rem ---------- 3. 替换 ----------
echo.
echo 即将替换：!INSTDIR!\bilitools.exe
echo 【重要】请先完全退出 BiliTools（包括右下角托盘图标 → 退出），然后按任意键继续。
echo 如果没退出，替换会失败（文件被占用）。
pause >nul

copy /Y "%SRC%" "!INSTDIR!\bilitools.exe" >nul
if errorlevel 1 (
  echo.
  echo 【失败】替换没成功。两个常见原因：
  echo   1. BiliTools 还开着 —— 完全退出后再试
  echo   2. 没有管理员权限 —— 右键本文件，选「以管理员身份运行」
) else (
  echo.
  echo 【成功】已替换成「1.4.6 命名优化版」。
  echo 打开软件后看「关于」页，会显示：v1.4.6 命名优化版
)
echo.
pause
