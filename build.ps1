# ============================================
#  OhmyPort 一键打包 + 生成发布产物 (PowerShell)
#
#  产物：
#    dist\OhmyPort.exe                    构建输出（未压缩）
#    release\OhmyPort_v<版本>\            发布目录
#      ├─ OhmyPort.exe                    未压缩
#      ├─ OhmyPort_v<版本>.zip            压缩包（含 exe + 使用说明）
#      └─ 使用说明.md
#
#  用法：
#    powershell -ExecutionPolicy Bypass -File build.ps1
# ============================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$AppName = "OhmyPort"
$Version = "1.0.0"   # 与 serial_tool.py 中 _APP_VERSION 保持一致

# [1/4] 检查 PyInstaller
Write-Host "[1/4] 检查 PyInstaller..." -ForegroundColor Cyan
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

# [2/4] 清理旧产物
Write-Host "[2/4] 清理旧构建产物..." -ForegroundColor Cyan
foreach ($d in @("build", "dist", "release")) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

# [3/4] 打包
Write-Host "[3/4] 开始打包..." -ForegroundColor Cyan
$env:QT_API = "pyside6"
python -m PyInstaller --noconfirm --clean --windowed --onefile `
    --name $AppName `
    --icon my-icon.png `
    --collect-all qdarktheme `
    --exclude-module PyQt5 `
    --exclude-module matplotlib `
    --exclude-module scipy `
    --exclude-module PIL `
    --exclude-module pytest `
    serial_tool.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "打包失败！" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# [4/4] 生成发布产物
Write-Host "[4/4] 生成发布产物..." -ForegroundColor Cyan
$releaseDir = Join-Path $PSScriptRoot "release\${AppName}_v${Version}"
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

# 未压缩
Copy-Item (Join-Path $PSScriptRoot "dist\${AppName}.exe") (Join-Path $releaseDir "${AppName}.exe") -Force
Copy-Item (Join-Path $PSScriptRoot "README.md") (Join-Path $releaseDir "使用说明.md") -Force

# 压缩包
$stage = Join-Path $env:TEMP "ohmyport_stage"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item (Join-Path $PSScriptRoot "dist\${AppName}.exe") (Join-Path $stage "${AppName}.exe") -Force
Copy-Item (Join-Path $PSScriptRoot "README.md") (Join-Path $stage "使用说明.md") -Force
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath (Join-Path $releaseDir "${AppName}_v${Version}.zip") -Force
Remove-Item $stage -Recurse -Force

Write-Host ""
Write-Host "打包完成！发布目录：$releaseDir" -ForegroundColor Green
Get-ChildItem $releaseDir | ForEach-Object {
    Write-Host ("  {0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
}
Read-Host "按回车退出"
