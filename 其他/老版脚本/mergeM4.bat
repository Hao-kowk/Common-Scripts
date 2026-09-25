@echo off
chcp 1252 >nul
setlocal enabledelayedexpansion

:input
set /p x="Enter the number of videos: "
echo %x%|findstr "^[0-9][0-9]*$" >nul
if errorlevel 1 (
    echo Invalid input, please enter a number.
    goto input
)

set /p name="Enter output file name (without extension): "

(for /l %%i in (1,1,%x%) do echo file '%%i.mp4') > "merge.txt"

ffmpeg -f concat -safe 0 -i "merge.txt" -c copy "%name%.mp4"

del "merge.txt"
echo Done. Output: %name%.mp4
pause