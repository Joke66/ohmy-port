# OhmyPort（C# / WPF 版）

Python + PySide6 版本的 C# + WPF 重写分支。**功能目标与原版一致**，用原生 Windows 运行时替代
PyInstaller 自解压，换取更小的体积和更快的启动。

- `master` 分支：Python 版本，继续可维护、可发版
- `wpf` 分支（本分支）：C# / WPF 实现，与 master 无共同祖先

## 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Windows | 10 1607+ / 11 | WPF 只支持 Windows |
| .NET SDK | **10.0.x** | `winget install Microsoft.DotNet.SDK.10` |
| IDE | 可选 | VS 2022 17.14+ / Rider / VS Code + C# Dev Kit |

## 构建与运行

```cmd
dotnet build OhmyPort.sln -c Release
dotnet run --project src\OhmyPort.App
dotnet test
```

## 解决方案结构

```
src/OhmyPort.Core/          纯逻辑（无 UI 依赖，可单测）
  Constants.cs              常量（波特率、编码、保留策略、性能参数）
  LogFilter.cs              多关键词过滤 / 高亮
  TextUtil.cs               数值提取、字节格式化、版本比较
  SendCodec.cs              HEX 与转义字符解析（GBK 需注册代码页提供程序）
  Serial/FrameParser.cs     自定义帧协议解析 + SUM8 / XOR8 / CRC16-Modbus
  Serial/SerialMonitor.cs   串口连接、接收线程、按行/按帧切分
  Serial/PortEnumerator.cs  串口枚举 + WMI 友好名
  Logging/LogManager.cs     日志写入 / 分片 / 保留清理
  Models/                   AppConfig（与旧版 JSON 兼容）、CommandItem、PlotRule
src/OhmyPort.App/           WPF 界面
  Controls/LogView.cs       基于 AvalonEdit 的日志控件（批量追加 / 着色 / 高亮 / 行数上限）
  Views/SessionView.xaml    单个串口会话的全部面板
  Themes/                   Dark.xaml（配色）+ Base.xaml（控件样式）
tests/OhmyPort.Core.Tests/  xUnit（移植自原版 pytest 用例）
```

## 进度

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 环境、解决方案骨架、单元测试 | ✅ |
| M1 | 串口连接/收发、日志显示、HEX/编码、发送历史、多会话标签页 | ✅ |
| M2 | 热插拔检测、连接状态指示、配置持久化 | ✅ |
| M3 | 保存日志、自动换行、字号缩放、Ctrl+F 搜索、上下分栏、暂停/清空/复制 | ✅ |
| M4 | 关键词过滤四模式（高亮/仅显示/排除/分栏） | ✅ |
| M5 | 发送辅助：命令页、定时循环、导入导出 | ✅ |
| M6 | 协议解析面板 + 自动应答 | ⏳（可选） |
| M7 | 数值绘图窗口 | ⏳（可选） |
| M8 | 日志录制 / 分片 / 保留策略 | ✅ |
| M9 | 四套主题、背景图、字体、托盘 | ✅ |
| M10 | 打包（dotnet publish + Inno Setup） | ✅ |

## 打包与发布

```cmd
powershell -ExecutionPolicy Bypass -File build.ps1
```

产物（`release\OhmyPort_v<版本>\`）：

| 文件 | 说明 |
|---|---|
| `OhmyPort.exe`（单文件，~67 MB） | 自包含，无需装 .NET 运行时，双击即用 |
| `OhmyPort_v<版本>.zip` | 绿色免安装版压缩包 |
| `OhmyPort_Setup_v<版本>.exe`（~62 MB） | Inno Setup 安装包（需本机装 Inno Setup 6） |

发布实测：单文件 exe 67 MB，冷启动 ~1.6s；文件夹模式（`-p:PublishSingleFile=false`）155 MB、启动 ~1.2s——单文件用启动时间换体积，当前默认单文件。

## 已知差异

- 配置文件名沿用 `serial_tool_config.json`，字段命名与原版一致（snake_case），老配置可直接读取。
- 流控：`System.IO.Ports` 不支持 DTR/DSR 流控，选该项时按无流控打开。
- 搜索用 AvalonEdit 内置 SearchPanel（Ctrl+F/F3/Shift+F3），而非原版的独立查找栏，命中计数略有差异。
- 日志控件为 AvalonEdit（虚拟化渲染）：5 万行上限实测追加 133ms / 再追加触发裁剪 192ms，实时 40 行/批平均 0.04ms，性能达标。
- 托盘用 WinForms NotifyIcon（WPF 无内置托盘），DPI 警告 WFO0003 已抑制。
- 背景模糊用 WPF BlurEffect 实时滤镜（不缓存预模糊图），与原版 PIL 预模糊观感略有差异。
