# 子设计 — OhmyPort.App 界面层

> 覆盖 `src/OhmyPort.App/` 全部视图与控件。依赖 `OhmyPort.Core`，不反向。

## 1. 启动入口与全局异常 — `App.xaml` / `App.xaml.cs`

- `App.xaml`：`StartupUri=MainWindow.xaml`，MergedDictionaries 固定为 `Dark.xaml` + `Base.xaml` + `Icons.xaml`（约定 [0] 为可切换主题字典）。
- `App.OnStartup`：
  - `--stress` 参数触发 `StressTest.Run()` 后直接退出（不加载主界面）。
  - 注册 GBK 代码页提供程序（.NET Core 起默认不含）。
  - 挂 `DispatcherUnhandledException` / `AppDomain.UnhandledException`，写 `error.log` 并弹窗，`Dispatcher` 异常 `Handled=true` 避免崩溃。

## 2. 主窗口 — `MainWindow.xaml` / `.xaml.cs`

职责：会话管理、菜单/工具栏编排、发送辅助面板、配置导入导出、托盘、背景皮肤、全局设置下发。

- 会话模型：`_sessions: List<SessionView>`，每个会话是一个 `TabItem`（Header 用 DataTemplate 显示连接绿点 + 标题 + 关闭按钮）。
- 会话操作：`AddSession` / `CloseSession`（至少保留一个，关闭后重新编号刷新「串口N」标题）；标签右键菜单（重命名/复制会话/关闭）、双击标题重命名；`DuplicateSession` 新建会话并 `CopyStateFrom` 复制配置；`CustomTitle` 按会话持久化。
- 快捷键：`OnPreviewKeyDown` 处理 Ctrl+T（新建）/ Ctrl+S（保存日志）/ Ctrl+Enter（发送）/ Ctrl+=、-、0（字号）。
- 菜单/工具栏：工具栏 ToggleButton 把状态写回对应菜单项再复用菜单处理逻辑（`OnToolbarToggleClick`），`SyncMenuState`/`SyncToolbarState` 保证两者一致。
- 全局设置：`ApplyGlobalSettings` 把换行/日志目录/分片/自动记录/主题着色下发到所有会话。
- 发送辅助：`RebuildCommandTabs` 按 `_config.Pages` 重建命令页；`SendCommand` 调当前会话 `SendCommandContent`；命令页右键菜单支持新增/重命名/删除页。
- 定时循环：`_cycleTimer`（DispatcherTimer）每 tick 取 `Cycle=true` 的命令轮流发送到当前活动会话；发完一条后按该命令 `DelayMs`（>0）或全局间隔动态更新 `Interval`；`SetCycleEnabled/Interval` 控制启停与间隔。
- 配置导入导出：`OnExportConfigClick` 序列化到用户选的文件；`OnImportConfigClick` 反序列化 + `Normalize` 后对齐会话数、全局设置、主题、背景，再保存。
- 关闭流程：`OnClosing` 按 `CloseBehavior`（tray/exit）+ `CloseConfirm` 决定托盘还是退出；`OnClosed` 停所有定时器、dispose 托盘、`SaveConfig`、逐个 `session.Shutdown()`。
- 背景皮肤：`ApplyBackground` 加载背景图（4K 按 1920 宽解码）、设 `BlurEffect` 半径（`BgBlur*3` 上限 36）、设遮罩 `BgVeilLayer.Opacity`，并调 `ThemeService.SetSurfaceTranslucency(true)` 让容器半透明。
- 强调色：`OnChooseAccentClick` 用 WinForms `ColorDialog` 选色 → `ThemeService.SetAccent` → 保存 `accent_color`。
- 窗口记忆：`RestoreWindowPlacement` 启动时恢复（越界回退居中），`SaveWindowPlacement` 退出时记录 `window_left/top/width/height`。
- 时间戳：视图菜单「时间戳」子菜单（完整/仅秒/不显示）改当前会话 `TimestampMode`，`SyncTimestampMenu` 随会话切换同步。

## 3. 会话视图 — `Views/SessionView.xaml` / `.xaml.cs`

单个串口会话的完整面板，含 9 行布局：

1. 端口配置行（端口下拉 + 刷新 + 波特率可编辑下拉）。
2. 完整串口参数（数据位/停止位/校验位/流控/DTR/RTS，默认隐藏，视图菜单打开）。
3. 关键词过滤（关键词/模式/区分大小写/正则/编码/HEX 显示/应用，默认隐藏）。
4. 协议帧解析（帧头/帧尾/长度字段/长度基准/字节序/校验/「字段...」按钮，详情可折叠，默认隐藏）。
5. 日志区（`LogView`）。
6. 帧字段解析结果（名称/类型/值/原始 HEX 表格，默认隐藏，视图菜单「字段解析」打开）。
7. 命中结果分栏（split 模式显示）。
8. 日志操作行（打开串口/暂停/清空/固定显示/开始记录）。
9. 消息发送（发送下拉 + 换行 + HEX 发送 + 校验 + 发送按钮）。

关键行为：

- 连接：`OnConnectClick` 校验端口/波特率后 `SerialMonitor.Connect`，成功后设 DTR/RTS、写系统日志、按 `AutoRecord` 自动开始记录，并聚焦发送框。
- 接收→显示：`OnReceived` 入队 → `Flush()` 出队（80ms）→ 写文件 + 过滤 + 格式化 + 分栏，末尾 `LogManager.Flush` 处理分片/错误。
- 过滤：`ApplyFilter` 重建 `LogFilter`（含正则开关）并 `ReRender` 全量重绘；`ToggleFilter` 关闭时清高亮并隐藏分栏。
- 发送：`SendRaw` 读输入 → `SendContent`（HEX/文本 + 换行）→ 选中校验时追加校验字节（换行前）→ 成功后入队 Tx 回显、计 `_txBytes`、写发送历史、置 `_responsePending`。发送历史支持上下键回填、右键清空。
- 应答高亮：发送后收到的第一条 RX 用 `ResponseMark`（`RECV <<<<<<<<<<`）着色（`_responsePending` 一次性消耗）。
- HEX 显示：`_hexView` 时 `FormatHexDisplay` 用 `HexText.Rows` 按 16 字节分行 + ASCII 对照，首行带时间戳/方向前缀、续行对齐。
- 时间戳：`TimestampMode`（full/sec/off）控制 `FormatLine` 的时间戳；落盘 `FormatRecordLine` 始终保留完整时间戳。
- 协议帧解析：`ApplyProtocol` 由帧头/帧尾/长度/校验字段构造 `FrameParser` 并 `SetFrameParser`；未启用时置 null 回退按行。帧校验失败在 `Flush` 中追加系统提示。详情字段可由 `OnToggleProtocolDetailClick` 折叠。
- 字段解析：`Flush` 记录最近一帧（`_latestFrame`）并置脏；`MaybeRefreshFields` 限速 150ms、面板不可见时不解码，`RefreshFields` 调 `ProtocolDecoder.Decode` 刷新表格（越界字段标红）。数据区偏移 `_frameDataOffset = 帧头长度 + 长度字段长度`。字段定义由 `ProtocolFieldDialog` 编辑，按会话持久化。
- 曲线采集：`Flush` 中对接收行调 `_plotHub.Feed(text)`（暂停显示时仍采集）；`ClearLog` 一并清空曲线数据。规则由 `SetPlotRules` 写入（配置恢复 / 曲线窗口编辑）。
- 记录：`StartRecord`/`StopRecord` 用 `LogManager` 落盘；`ToggleRecord` 切换；`SyncRecordButton` 更新按钮文案。
- 状态：`StatusText` 拼端口/波特率/编码/连接状态/RX/TX 字节与实时速率（`SampleRate` 每秒采样增量），`StatusChanged` 通知主窗口刷新状态栏。
- 热插拔：`_hotplugTimer`（2s）检测连接端口被拔出则自动断开，端口集合变化则刷新列表。
- 生命周期：`Shutdown` 停定时器、关日志、断开串口。

## 4. 日志控件 — `Controls/LogView.cs`

基于 AvalonEdit `TextEditor` 的虚拟化文本视图：

- 只读、无行号、禁用水平滚动、撤销栈上限 0、关闭超链接。
- 内置 `SearchPanel`（Ctrl+F / F3 / Shift+F3 / Esc）。
- `AppendLines(lines, follow)`：批量插入（`Document.BeginUpdate`）+ `TrimToMaxLines`（超出 `MaxLines` 从头部删）+ 按需 `ScrollToEnd`。
- `ZoomIn/Out/Reset`：字号缩放（6~72，默认 12），Ctrl+滚轮也缩放。
- `ApplyTheme`：AvalonEdit 不参与全局样式，背景透明、前景/选区/光标显式绑定资源，避免深色主题白底白字。
- `SetKeywords` / `RefreshHighlight`：关键词高亮重算。
- `LogColorizer`（`DocumentColorizingTransformer`）：无状态按行着色——时间戳 `[HH:mm:ss.fff] `、`SEND >>>>>>>>>>` 标记（Tx）、`◆ ` 系统标记、`RECV <<<<<<<<<<` 应答标记、关键词高亮（背景+前景）。
- 方向标记常量：`TxMark = "SEND >>>>>>>>>>"`、`SysMark = "◆ "`、`ResponseMark = "RECV <<<<<<<<<<"`。

## 4.1 实时曲线画布 — `Controls/PlotCanvas.cs`

- `FrameworkElement` 直接 `OnRender` 绘制：背景取 `Brush.LogBackground`、网格取 `Brush.Border`、刻度文字取 `Brush.Muted`（主题切换后下一次重绘生效）。
- 布局：左侧 60px 刻度区、底部 24px、顶部图例行；Y 轴 4 段自动缩放（全系列极值合并 + 5% 余量，退化时 ±1）。
- 折线：8 色固定调色板按系列序号取色；`NaN` 断开 figure；X 按 `Capacity` 铺满（数据未满时从左向右生长，满了之后滚动）。
- 图例：色块 + 名称 + 最新值，宽度不够时截断。

## 5. 主题系统 — `ThemeService.cs`
- 四套主题：auto/black/day/eye；auto 按注册表 `AppsUseLightTheme` 解析为 black/day。
- `Apply(key)`：切换 MergedDictionaries[0] 为对应 `Themes/*.xaml`，刷新标题栏并触发 `ThemeChanged`。
- `RefreshIfAuto`：auto 模式下轮询（2s）检测系统深浅变化。
- `ApplyTitleBarTheme`：通过 DWM `DWMWA_USE_IMMERSIVE_DARK_MODE`（20，回退 19）设置标题栏深浅。
- `SetSurfaceTranslucency`：背景皮肤开启时把 `Brush.MenuBar`/`Brush.Surface`/`Brush.LogSurface` 换半透明，让背景图透出。
- `SetAccent(hex)`：自定义强调色覆盖 `Brush.Accent`/`AccentHover`/`AccentPressed`/`AccentForeground`（Hover 变亮、Pressed 变暗、前景按亮度取黑白）；`ApplyDictionary` 每次切换主题后重新应用。
- `AttachWindow`：给代码 new 的对话框补 `Theme.Window` 样式与背景/前景资源引用。
- `GetBrush(key)` / `IsDark`：日志着色与标题栏判断用。

## 6. 菜单图标 — `IconGlyph.cs`

附加属性 `app:IconGlyph.Name`，XAML 里写图标名，运行时按 `Icon.<name>` 几何生成 16×16 单色 Path 挂到 `MenuItem.Icon`，颜色跟随 `Brush.Foreground`。

## 7. 对话框 — `Views/*`

- `CommandEditDialog`：命令名称 + 内容（多行，支持转义）+ 所属页（页满/新建页）+ 发送后延时；`pageOnly` 模式复用于重命名页。
- `CycleDialog`：定时循环发送设置——启用开关、间隔（10ms~1h 钳制）、勾选参与循环的命令列表（`CycleItem` 双向绑定）；关闭弹窗不停止循环。
- `BackgroundDialog`：背景图目录选择/打开/刷新、图片下拉、模糊滑杆（0~50）、遮罩滑杆（0~100%）、启用开关。
- `CloseConfirmDialog`：关闭时「最小化到托盘 / 直接退出」+ 不再提示。
- `ComboSelectDialog`：通用下拉选择（日志保留策略/字体）。
- `NumberInputDialog`：通用数字输入（日志分片大小，钳制范围）。
- `ChecksumCalculatorDialog`：校验计算器，HEX 输入 → SUM8/XOR8/CRC16-Modbus 结果 + 复制。
- `ProtocolFieldDialog`：协议字段编辑，一行一个字段（名称/偏移/类型/长度/大端/系数/偏移量），确定时统一校验；`FieldRow` 保存文本态输入。
- `PlotRuleDialog`：曲线提取规则编辑，一行一条曲线（名称 + 正则/关键词）。
- `PlotWindow`（独立窗口，非模态）：工具栏（提取规则/清空/暂停刷新/窗口点数）+ `PlotCanvas` 绘图；60ms 定时重绘，数据来自所属会话的 `PlotHub`（关窗不丢数据，重开接上）；会话关闭时一并关闭。
- `FileSendDialog`：文件发送对话框——文件/格式（HEX/文本行/二进制）/分包大小/分包间隔/进度；后台线程逐块调用会话 `SendRawBytes`，支持取消。

## 8. 性能压测 — `StressTest.cs`

`--stress` 入口：一次性灌 5 万行、再灌 5 万行触发裁剪、200 批实时追加、滚底、全文本长度；结果写 `stress_result.txt` 后退出。用于回归 AvalonEdit 性能。

## 9. 资源与主题文件

- `Themes/Base.xaml`：控件通用样式（窗口、按钮、标签等）。
- `Themes/Dark.xaml` / `Light.xaml` / `Eye.xaml`：三套配色字典（画刷键如 `Brush.Window`/`Brush.Surface`/`Brush.LogSurface`/`Brush.LogTimestamp`/`Brush.LogTx`/`Brush.LogSys`/`Brush.HighlightBg`/`Brush.HighlightFg`）。
- `Assets/Icons.xaml`：图标几何资源（`Icon.save`、`Icon.folder`、`Icon.sliders` 等）。
