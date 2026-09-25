@echo off
setlocal enabledelayedexpansion

set "success=0"
set "failed=0"
set "total=0"

echo 当前文件夹: %cd%
echo 即将转换所有 .m4a 文件...
echo.

for %%a in (*.m4a) do (
    set /a total+=1
    echo [ !total! ] 正在处理: "%%a"
    ffmpeg -f lavfi -i "color=c=black:s=1440x2560:r=30,format=yuv420p" -i "%%a" -c:v libx264 -preset ultrafast -crf 28 -g 30 -c:a aac -b:a 128k -shortest "%%~na.mp4"
    
    if errorlevel 1 (
        echo [失败] %%a 处理失败，继续下一个...
        set /a failed+=1
    ) else (
        echo [完成] %%a 转换成功
        set /a success+=1
    )
    echo --------------------------------------
)

echo.
echo ========== 全部任务执行完毕 ==========
echo 成功: !success! 个
echo 失败: !failed! 个
echo 合计: !total! 个
echo.
pause