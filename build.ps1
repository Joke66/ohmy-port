# ============================================
#  OhmyPort（C# / WPF 版）一键发布脚本 (PowerShell)
#
#  产物：
#    publish\OhmyPort\                    自包含发布文件夹（含 exe + 运行时）
#    release\OhmyPort_v<版本>\             发布目录（保留历史版本）
#      ├─ OhmyPort\                       绿色免安装版文件夹（解压即用）
#      ├─ OhmyPort_v<版本>.zip             绿色版压缩包
#      └─ OhmyPort_Setup_v<版本>.exe       安装包（需 Inno Setup 6）
#
#  用法：
#    powershell -ExecutionPolicy Bypass -File build.ps1
# ============================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$AppName = "OhmyPort"
$Version = "2.0.0"          # 与 OhmyPort.Core/Constants.cs 中 AppInfo.Version 保持一致
$DotNet  = "dotnet"

# [1/4] 检查 .NET SDK
Write-Host "[1/4] 检查 .NET SDK..." -ForegroundColor Cyan
& $DotNet --list-sdks *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "未检测到 .NET SDK，请先安装：winget install Microsoft.DotNet.SDK.10" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# [2/4] 清理旧产物（保留 release 下历史版本）
Write-Host "[2/4] 清理旧产物..." -ForegroundColor Cyan
foreach ($d in @("publish")) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

# [3/4] 发布（自包含 + 单文件，无需目标机器装 .NET 运行时）
Write-Host "[3/4] 发布（self-contained 单文件）..." -ForegroundColor Cyan
& $DotNet publish "src\$AppName.App\$AppName.App.csproj" `
    -c Release `
    -r win-x64 `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:EnableCompressionInSingleFile=true `
    -p:DebugType=None -p:DebugSymbols=false `
    -o "publish\$AppName"
if ($LASTEXITCODE -ne 0) {
    Write-Host "发布失败！" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# [4/4] 生成发布产物
Write-Host "[4/4] 生成发布产物..." -ForegroundColor Cyan
$releaseDir = Join-Path $PSScriptRoot "release\${AppName}_v${Version}"
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

# 绿色免安装版文件夹
$greenDir = Join-Path $releaseDir $AppName
if (Test-Path $greenDir) { Remove-Item $greenDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $greenDir | Out-Null
Copy-Item (Join-Path $PSScriptRoot "publish\$AppName\*") $greenDir -Recurse -Force
Copy-Item (Join-Path $PSScriptRoot "README.md") (Join-Path $greenDir "使用说明.md") -Force

# 绿色版压缩包
Compress-Archive -Path $greenDir -DestinationPath (Join-Path $releaseDir "${AppName}_v${Version}.zip") -Force

# 安装包（可选，需 Inno Setup 6）
Write-Host "[5/5] 生成安装包（可选）..." -ForegroundColor Cyan
$iscc = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /DMyAppVersion=$Version "installer.iss"
    if ($LASTEXITCODE -eq 0) {
        Copy-Item (Join-Path $PSScriptRoot "Output\OhmyPort_Setup_v$Version.exe") (Join-Path $releaseDir "OhmyPort_Setup_v$Version.exe") -Force
        Write-Host "  安装包已生成：OhmyPort_Setup_v$Version.exe" -ForegroundColor Green
    } else {
        Write-Host "  安装包编译失败！" -ForegroundColor Yellow
    }
} else {
    Write-Host "  未检测到 Inno Setup 6，跳过安装包生成（仅绿色版）" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "发布完成！发布目录：$releaseDir" -ForegroundColor Green
Get-ChildItem $releaseDir | ForEach-Object {
    Write-Host ("  {0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
}
Read-Host "按回车退出"
