# ============================================
#  OhmyPort 打包脚本 (PowerShell)
#  执行后生成 dist\OhmyPort.exe
#
#  用法（任选其一）：
#    1) 右键本文件 -> 使用 PowerShell 运行
#    2) 在终端执行：
#         powershell -ExecutionPolicy Bypass -File build.ps1
# ============================================

$ErrorActionPreference = "Stop"

# 切换到脚本所在目录
Set-Location -Path $PSScriptRoot

Write-Host "[1/3] 检查 PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "未检测到 PyInstaller，正在安装..." -ForegroundColor Yellow
    python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Host "PyInstaller 安装失败！" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
}

Write-Host "[2/3] 清理旧构建产物..." -ForegroundColor Cyan
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }

Write-Host "[3/3] 开始打包..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --windowed --onefile `
    --name OhmyPort `
    --icon my-icon.png `
    --collect-all qdarktheme `
    serial_tool.py

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "打包失败！" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Write-Host ""
Write-Host "打包完成：dist\OhmyPort.exe" -ForegroundColor Green
Read-Host "按回车退出"
