# OhmyPort — AGENTS.md

> 本文件是 AI 编程智能体的工作入口，每次对话都会加载到上下文中，请保持精简。
> 详细内容放入 docs/ 或 reference/，通过引用链接。八板块按公司《AI智能体编程指导手册》3.3 节组织。

## 1. 模块概述

OhmyPort 是一个 Windows 串口调试助手，C# / WPF 实现（.NET 10）。它是 Python + PySide6 原版（master 分支）的 C# 重写分支（wpf 分支），功能目标与原版一致：用原生 Windows 运行时替代 PyInstaller 自解压，换取更小体积与更快启动。

核心能力：多串口会话、文本/HEX 收发、关键词过滤四模式、命令页 + 定时循环发送、日志录制/分片/保留、四套主题/背景皮肤/托盘。

模块边界：

- `OhmyPort.Core`：纯逻辑，无 UI 依赖，可单元测试（串口收发、帧协议解析、发送编解码、日志过滤、配置读写、日志落盘、文本工具、数值提取）。
- `OhmyPort.App`：WPF 界面（主窗口、会话视图、日志控件、主题、对话框、托盘、背景皮肤）。

## 2. 工作准则

1. 文档与代码必须保持一致、同步更新：代码修改后自动分析并同步修改受影响文档（docs/req、docs/design）。
2. 代码注释统一使用简体中文。
3. 编码阶段必须基于 docs/req 研发需求文档和 docs/design 设计文档生成代码。
4. 修改代码前先给出完整 diff 信息供人工审核。
5. 功能目标与 Python 原版一致，界面体验尽量对齐原版，具体实现可自由取舍。
6. 配置字段名沿用旧版 `serial_tool_config.json` 的 snake_case，改字段前先看 docs/design/接口文档.md 的兼容性说明，避免破坏老配置。
7. 本分支（wpf）与 master（Python 版）无共同祖先，改动不要跨分支混写。

## 3. 文档目录结构

```
docs/
├── req/
│   └── 研发需求文档.md            功能需求清单（倒推自代码，单一真相源）
├── design/
│   ├── 设计文档.md                总设计：架构 / 数据流 / 线程模型 / 技术栈 / 模块划分
│   ├── 子设计-Core逻辑层.md       OhmyPort.Core 各组件设计
│   ├── 子设计-App界面层.md        OhmyPort.App 各视图 / 控件设计
│   └── 接口文档.md                Core↔App 接口契约 + 配置 JSON 结构 + 日志格式
├── test/                          可选：测试用例说明
├── issue/                         可选：问题记录
├── task/                          可选：代码生成方案文档
reference/                         被引用的私有文档（gitignore 不上库）
```

## 4. 代码目录结构

```
OhmyPort.sln                        解决方案（src + tests 两个解决方案文件夹）
Directory.Build.props               全局属性：LangVersion latest / Nullable / Version=1.8.8 / zh-Hans
build.ps1                           一键发布脚本（dotnet publish + Inno Setup）
installer.iss                       Inno Setup 安装脚本
src/OhmyPort.Core/                  纯逻辑层（无 UI）
├── AppPaths.cs                     可写数据目录解析（exe 同级优先，否则 %APPDATA%\OhmyPort）
├── ConfigService.cs                配置读写（Load / Save，损坏回退默认值）
├── Constants.cs                    应用元信息 + 串口默认值 + 性能参数 + 日志保留 + 主题标识
├── LogFilter.cs                    多关键词过滤四模式 + 命中判定
├── SendCodec.cs                    HEX 解析 / 转义字符解析 / 编码获取（UTF-8/GBK/ASCII）
├── TextUtil.cs                     字节格式化 / 数字提取 / 版本解析比较
├── Logging/LogManager.cs           日志落盘 / 分片 / 保留清理
├── Models/AppConfig.cs             应用配置模型（与旧版 JSON 兼容）+ Normalize 校验
├── Models/CommandItem.cs           命令项 + 命令页解析（CommandPages）
├── Models/PlotRule.cs              数值提取规则（正则捕获组 / 关键词取数字）
└── Serial/
    ├── FrameParser.cs              自定义帧协议解析（帧头/长度/校验 SUM8/XOR8/CRC16-Modbus）
    ├── PortEnumerator.cs           串口枚举 + WMI 友好名
    └── SerialMonitor.cs            串口后端：接收线程 + 事件回调 + 收发
src/OhmyPort.App/                   WPF 界面层
├── App.xaml / App.xaml.cs          启动入口 + 全局异常处理 + --stress 压测入口
├── MainWindow.xaml / .xaml.cs      主窗口：菜单/工具栏/会话标签/发送辅助面板/配置导入导出/托盘
├── IconGlyph.cs                    菜单图标附加属性（XAML 几何 → 主题着色 Path）
├── ThemeService.cs                 四套主题 + 系统深浅跟随 + 背景半透明画刷 + 标题栏深色
├── StressTest.cs                   日志控件性能压测（--stress）
├── Controls/LogView.cs             基于 AvalonEdit 的日志控件（批量追加/裁剪/着色/关键词高亮/查找）
├── Assets/Icons.xaml               图标几何资源
├── Themes/Base.xaml                控件通用样式
├── Themes/Dark.xaml / Light.xaml / Eye.xaml   三套配色字典（auto 解析到 dark/light）
└── Views/
    ├── SessionView.xaml / .xaml.cs 单个串口会话视图（连接/收发/过滤/记录/状态统计）
    ├── CommandPageContent.cs       命令页内容（4 列按钮网格）
    ├── CommandEditDialog.xaml / .xaml.cs   命令编辑对话框（添加/编辑/重命名页）
    ├── CycleDialog.xaml / .xaml.cs 定时循环发送设置
    ├── BackgroundDialog.cs         背景皮肤对话框
    ├── CloseConfirmDialog.cs       关闭确认（托盘/退出/不再提示）
    ├── ComboSelectDialog.cs        下拉选择对话框（保留策略/字体）
    └── NumberInputDialog.cs        数字输入对话框（分片大小）
tests/OhmyPort.Core.Tests/          xUnit（移植自原版 pytest）
├── CommandPagesTests.cs / FrameParserTests.cs / LogFilterTests.cs
├── PlotRuleTests.cs / SendCodecTests.cs / TextUtilTests.cs
```

## 5. 架构概要

分层：`OhmyPort.App`（WPF 界面）→ `OhmyPort.Core`（无 UI 逻辑）。Core 不引用任何 UI 类型，通过 `System.IO.Ports` 直接操作串口。

线程模型：

- 每个 `SessionView` 持有一个 `SerialMonitor`，其内部有一个后台接收线程 `ReceiveLoop`，读串口 → 按行/按帧切分 → 通过 `Received` 事件抛到 UI 线程的 `ConcurrentQueue`。
- UI 用 `DispatcherTimer`（80ms，`UiDefaults.FlushMs`）批量消费队列，攒成一批字符串后一次性 `LogView.AppendLines` 写入 AvalonEdit，避免高频刷新卡 UI。
- 暂停（`_paused`）只冻结 rx/tx 显示，后台仍接收并缓冲；恢复时 `ReRender()` 全量重建。

数据流：串口字节 → `SerialMonitor.ReceiveLoop` → `Frame`（或行）→ `SessionView.OnReceived` 入 `_pending` 队列 → `Flush()` 每 80ms 出队 → 写文件（`LogManager`）+ 过滤 + 格式化 → `LogView`。

配置流：`ConfigService.Load()` 读 `serial_tool_config.json` → `AppConfig.Normalize()` 裁剪 → 注入各 `SessionView`；关闭时 `SaveConfig()` 从各会话回读状态写回 JSON。

## 6. 编译方法

环境：Windows 10 1607+ / 11，.NET SDK 10.0.x（`winget install Microsoft.DotNet.SDK.10`）。

```cmd
dotnet build OhmyPort.sln -c Release
dotnet run --project src\OhmyPort.App
dotnet test
```

发布（自包含单文件 + Inno Setup 安装包）：

```cmd
powershell -ExecutionPolicy Bypass -File build.ps1
```

私有环境配置（如特定 SDK 路径）写入 reference/ 私有文件，不要写进本文件。

## 7. 部署方法

`build.ps1` 产物输出到 `release\OhmyPort_v<版本>\`：

- `OhmyPort.exe`（单文件，约 67 MB，自包含免装 .NET，双击即用）
- `OhmyPort_v<版本>.zip`（绿色免安装版）
- `OhmyPort_Setup_v<版本>.exe`（Inno Setup 安装包，需本机装 Inno Setup 6）

目标机器无需预装 .NET 运行时。配置与日志写在 exe 同级目录（不可写时落到 `%APPDATA%\OhmyPort`）。

## 8. 调试方法

- 日志目录：`Logs\`（exe 同级或 `%APPDATA%\OhmyPort\Logs`），文件名为 `<端口>_yyyyMMdd_HHmmss.txt`。
- 崩溃日志：`error.log`（exe 同级），关键词 `未处理的错误`、异常堆栈，用于快速定位未捕获异常。
- 串口错误：`SerialMonitor.LastError`，连接失败时弹窗提示，关键词 `打开失败` / `端口不存在` / `被其它软件占用`。
- 性能压测：`OhmyPort.exe --stress`，结果写入 `stress_result.txt`（关键词 `append_50000_lines_ms`、`batch_200_avg_ms`）。
- 常见异常原因：GBK 未注册（`SendCodec` 静态构造已处理）、WMI 不可用（`PortEnumerator` 退回裸端口名）、DTR/DSR 流控不支持（按无流控打开）。
