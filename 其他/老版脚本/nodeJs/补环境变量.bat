@echo off
chcp 65001 >nul
title Node.js PATH fix
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix-npm-path.ps1"
echo.
pause
