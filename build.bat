@echo off
chcp 65001 >nul
REM ============================================
REM  串口工具打包脚本
REM  执行后生成 dist\SerialTool.exe
REM ============================================
cd /d "%~dp0"

echo [1/3] 检查 PyInstaller...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo 未检测到 PyInstaller，正在安装...
    python -m pip install pyinstaller
)

echo [2/3] 清理旧构建产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 开始打包...
python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name OhmyPort ^
  --icon my-icon.png ^
  --collect-all qdarktheme ^
  serial_tool.py

if errorlevel 1 (
    echo.
    echo 打包失败！
    pause
    exit /b 1
)

echo.
echo 打包完成：dist\SerialTool.exe
pause
