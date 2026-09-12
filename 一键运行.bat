@echo off
setlocal
cd /d "%~dp0"
title 美股因子策略 - 一键菜单

rem ============================================================
rem  双击本文件即可运行。
rem  本 .bat 必须与 _menu.py 放在同一个目录下。
rem  想放到桌面：右键本文件，发送到，桌面快捷方式。不要只复制 .bat 本身。
rem
rem  注意：本文件必须保存为 ANSI/GBK(936) 编码 + CRLF 换行。
rem  绝不要在批处理里执行 chcp：cmd.exe 按字节偏移续读本文件，
rem  切换代码页会让多字节中文的长度变化，导致后面每一行被截断。
rem ============================================================

set "PY=C:\Users\sailor\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

if not exist "%~dp0_menu.py" goto NOMENU

"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 goto NOPY

"%PY%" "%~dp0_menu.py"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" echo [WARN] python exited with code %RC%
echo ------------------------------------------------------------
pause
endlocal
exit /b 0

:NOMENU
echo [错误] 找不到 _menu.py
echo        请确认 一键运行.bat 与 _menu.py 在同一个目录下。
echo        当前目录是：
cd
echo.
pause
exit /b 1

:NOPY
echo [错误] 无法运行 Python：
echo        %PY%
echo        请检查 Python 是否已安装，或修改本文件里的 PY 路径。
echo.
pause
exit /b 1
