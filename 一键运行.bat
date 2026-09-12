@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title 美股因子策略 - 一键菜单

rem ============================================================
rem  双击本文件即可。需要放到项目目录（本 .bat 与 _menu.py 同级）。
rem  想放桌面：右键本文件 -> 发送到 -> 桌面快捷方式（不要只复制 .bat）。
rem ============================================================

set "PY=C:\Users\sailor\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

cd /d "%~dp0"

if not exist "%~dp0_menu.py" (
    echo [错误] 找不到 _menu.py，请确认本 .bat 与 _menu.py 在同一目录。
    echo 当前目录: %~dp0
    pause
    exit /b 1
)

"%PY%" "%~dp0_menu.py"

echo.
echo ------------------------------------------------------------
pause
endlocal
