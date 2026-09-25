@echo off
setlocal enabledelayedexpansion
set "success=0"
set "failed=0"
set "total=0"

echo 正在为所有 .mp4 文件烧录同名的 .ass 字幕...
echo.
for %%v in (*.mp4) do (
    set /a total+=1
    set "assfile=%%~nv.ass"
    if exist "!assfile!" (
        echo [ !total! ] 正在处理: "%%v"
        ffmpeg -i "%%v" -vf "ass=!assfile!" -c:v libx264 -preset faster -crf 23 -c:a copy "%%~nv_带字幕.mp4"
        if errorlevel 1 (
            echo [失败] %%v
            set /a failed+=1
        ) else (
            echo [完成] %%v
            set /a success+=1
        )
    ) else (
        echo [跳过] 找不到字幕文件: "!assfile!"
        set /a failed+=1
    )
    echo --------------------------------------
)

echo.
echo ========== 全部完成 ==========
echo 成功: !success! 个
echo 失败/跳过: !failed! 个
echo 合计: !total! 个
pause