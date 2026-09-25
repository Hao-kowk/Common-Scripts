@echo off
chcp 65001 >nul

:: 创建大类
mkdir "E:\Design"
mkdir "E:\Browser"
mkdir "E:\Message"
mkdir "E:\Internet"
mkdir "E:\Security"
mkdir "E:\Tools"

:: 创建 Design 下的父类
mkdir "E:\Design\Adobe"

:: 创建 Internet 下的父类
mkdir "E:\Internet\VPN"
mkdir "E:\Internet\GameBooster"
mkdir "E:\Internet\Cloud"
mkdir "E:\Internet\Downloader"

:: 创建 Tools 下的父类
mkdir "E:\Tools\Office"
mkdir "E:\Tools\BandiFamily"
mkdir "E:\Tools\Input"
mkdir "E:\Tools\Green"
mkdir "E:\Tools\Transfer"
mkdir "E:\Tools\AI"
mkdir "E:\Tools\Dev\RPA"
mkdir "E:\Tools\Media"

echo.
echo 分类文件夹已创建完成！
pause