# 子设计 — OhmyPort.Core 逻辑层

> 覆盖 `src/OhmyPort.Core/` 全部组件。所有组件均无 UI 依赖，可直接单元测试。

## 1. 常量与元信息 — `Constants.cs`

- `AppInfo`：应用名/版本/作者/日期/项目地址/更新 API。
- `SerialDefaults`：波特率列表、编码表（UTF-8/GBK/ASCII）、发送换行表（无/`\r`/`\n`/`\r\n`）。
- `UiDefaults`：性能参数——日志上限 50000 行、刷新 80ms、读块 4096 字节、高亮重算 0.5s、热插拔 2s、绘图窗口 600 点、发送历史 50 条。
- `LogRetention`：日志保留选项（一周/一月/半年/一年/无限制 → 天数）。
- `Themes`：主题标识（auto/black/day/eye）。

## 2. 路径与配置 — `AppPaths.cs` / `ConfigService.cs`

- `AppPaths`：数据目录解析——exe 同级可写则用 exe 同级，否则落到 `%APPDATA%\OhmyPort`；派生 `ConfigPath`、`DefaultLogDir`、`DefaultBgDir`。
- `ConfigService`：`Load()` 文件不存在/损坏回退默认配置并 `Normalize()`；`Save()` 序列化写回。异常仅吞 IOException/UnauthorizedAccessException/JsonException。

## 3. 配置模型 — `Models/AppConfig.cs`

- `SessionConfig`：单会话持久化状态（端口/波特率/自定义波特率/过滤关键词/过滤模式/区分大小写/过滤开关/字号）。
- `AppConfig`：全局配置（主题/命令页/命令/自动记录/分片大小/保留策略/字体/换行/关闭行为/背景皮肤字段/会话列表）。
- 关键约束：
  - 字段命名用 `PropertyNamingPolicy.SnakeCaseLower`，与旧版 `serial_tool_config.json` 一致。
  - `JsonOptions`：忽略注释、容忍尾逗号、UnsafeRelaxedJsonEscaping（中文不转义）。
  - `Normalize()`：把外部来源配置裁剪到合法范围（主题/页数/分片/保留/关闭行为/背景参数/过滤模式/字号）。
  - `FlexibleStringConverter`：兼容波特率字段既可能是字符串也可能是数字的旧写法。

## 4. 命令模型 — `Models/CommandItem.cs`

- `CommandItem`：名称 + 内容 + 是否参与定时循环 + 所属页号。
- `CommandPages.Load(pages, commands, currentPages)`：解析命令页与命令——无 pages 时保留默认页；页号越界回退第 1 页；名称与内容都为空的命令丢弃。

## 5. 发送编解码 — `SendCodec.cs`

- 静态构造注册代码页提供程序（GBK/936）。
- `ParseHex(text)`：HEX 字符串 → 字节，忽略空格、容忍 `0x` 前缀；奇数长度或非法字符返回 null。
- `ParseEscaped(text, encoding)`：转义解析——`\r \n \t \0 \xNN \\`，代理对按一个字符编码避免 emoji 拆半，未知转义原样保留。
- `GetEncoding(key)`：按配置键取 UTF-8（无 BOM、容忍非法字节）/GBK/ASCII。

## 6. 过滤 — `LogFilter.cs`

- `FilterModes`：highlight（显示全部并高亮）/ include（仅显示命中行）/ exclude（排除命中行）/ split（上下分栏显示命中行）。
- `ParseKeywords`：把 `,;空白换行` 统一成分隔符后去重解析。
- `Matched(line)`：返回命中的关键词（保持配置顺序），大小写敏感性可配。
- `Visible(line)`：判定该行是否应显示在主导出区。
- `HighlightEnabled`：该模式是否需要高亮命中关键词。

## 7. 文本工具 — `TextUtil.cs`

- `FormatBytes`：字节数人类可读（B/KB/MB）。
- `ExtractNumbers`：提取全部数字（含负号与小数）。
- `FormatValue`：绘图数值格式（整数不带小数点，小数最多 4 位去尾零）。
- `ParseVersion` / `CompareVersions`：版本号解析与比较。

## 8. 串口后端 — `Serial/SerialMonitor.cs`

- `SerialSettings`：端口/波特率/数据位/校验/停止位/流控。
- `SerialMonitor`：
  - 独立后台线程 `ReceiveLoop`，`ReadTimeout=100ms` 轮询读，`WriteTimeout=1000ms`。
  - 接收通过 `Received` 事件（`IReadOnlyList<Frame>`）抛出，回调异常被吞，不中断接收线程。
  - `SetFrameParser(parser)`：置非 null 按帧切分，置 null 恢复按行（`SplitLines`，处理 `\r\n`）。
  - `Connect` 失败写 `LastError` 返回 false；`Disconnect` 设置停止信号 + Join 1s。
  - `Send`/`SetDtr`/`SetRts` 均加锁保护 `_port`，异常静默（虚拟串口可能不支持 DTR/RTS）。
  - `RxBytes` 用 `Interlocked.Add` 累计。

## 9. 帧协议解析 — `Serial/FrameParser.cs`

- `ChecksumKind`：None / Sum8 / Xor8 / Crc16Modbus。
- 帧结构约定：`[帧头][长度字段?][数据][校验][帧尾]`；长度字段紧跟帧头，值为数据字节数（可用 `LengthBase` 微调）；校验覆盖校验字节之前所有内容。
- 属性：`Header`/`Tail`/`LengthSize`/`LengthBase`/`BigEndian`/`Checksum`。
- `Feed(data)`：喂入字节流返回能切出的所有完整帧；`ExtractOne` 先找帧头（保留可能的前缀尾巴），再按长度或帧尾定界。
- 校验算法：`Sum8`（和取低 8 位）、`Xor8`（异或）、`Crc16Modbus`（多项式 0xA001、初值 0xFFFF、结果低字节在前比较）。
- `ParseChecksum(value)`：字符串（none/sum8/xor8/crc16_modbus）→ 枚举。
- `ChecksumBytes(kind, data)`：计算校验字节（发送侧自动追加 / 校验计算器共用），CRC16-Modbus 低字节在前；配套 `ChecksumKeys` 常量类提供配置键。
- 注意：线程不安全，需在单一接收线程内使用（与 Python 版一致）。

## 10. 端口枚举 — `Serial/PortEnumerator.cs`

- `PortInfo(PortName, Description)`：系统名 + WMI 友好名，`Display` 为 `COM3  USB-SERIAL CH340` 形式。
- `ListPorts`：`SerialPort.GetPortNames()` 去重、按数字自然排序（COM2 < COM10）；`QueryDescriptions` 用 WMI 查 `Win32_PnPEntity` 的 Caption 提取友好名，失败退回裸端口名。
- `ListPortsAsync`：后台线程枚举避免 WMI 阻塞 UI。

## 11. 数值提取规则 — `Models/PlotRule.cs`

- 构造时解析正则，含捕获组才启用正则匹配；否则按关键词取其后第一个数字。
- `Match(text)`：正则捕获组命中且可解析为数值返回该值，否则退回 `TextUtil.ExtractNumbers` 取第一个；关键词模式取关键词之后的第一个数字。
- 对应 Python 版 plot_widget.PlotRule，目前仅 Core 层实现，UI 未接线（M7 待做）。

## 11.1 协议字段解析 — `Models/ProtocolField.cs`

- `FieldTypes`：类型键常量（uint8/int8/uint16/int16/uint32/int32/float32/float64/hex/ascii）+ 下拉选项表（显示名/键/固定字节数）+ `IsValid`/`SizeOf`/`LabelOf`。
- `ProtocolField`：名称、偏移（相对数据区起始）、类型键、字节序、系数 `Scale`、零点 `Bias`、`Length`（hex/ascii 用）。
- `FieldValue(Name, TypeLabel, Text, RawHex, Ok)`：单个字段的解析结果。
- `ProtocolDecoder.Decode(frame, offsetBase, fields)`：纯函数、无状态；`offsetBase` 为数据区在帧内的起始下标（帧头 + 长度字段长度）。
  - 数值类型按字节序读原始值，物理值 = 原始值 × Scale + Bias，用 `TextUtil.FormatValue` 格式化。
  - hex 输出空格分隔大写十六进制；ascii 按 ASCII 解码并去掉尾部 `\0`。
  - 越界或类型非法返回 `Ok = false`、值显示「—」，不影响其它字段。
- 与 `FrameParser` 的分工：`FrameParser` 负责切帧 / 验校验，`ProtocolDecoder` 负责帧内字段取值；两者都无 UI 依赖。

## 12. 日志落盘 — `Logging/LogManager.cs`

- `Open(stem, logDir)`：以端口名 sanitize 后的 stem 生成 `<stem>_yyyyMMdd_HHmmss.txt`，`FileShare.Read` 允许外部查看。
- `Write(line)`：UTF-8 追加一行 + `\r\n`，异常记录 `Error` 并关闭。
- `Flush(shardMb, logDir)`：刷盘并在超过分片大小时 `RotateCore` 分片。
- `Rotate` / `Close` / `CleanOldLogs`：手动分片、关闭、按保留策略清理旧 `.txt`（异常逐文件吞掉）。
- `SanitizeStem`：端口名 → 安全文件名（非 `[0-9A-Za-z_-]` 替换为 `_`）。

## 13. 待接线（后续里程碑）

- `PlotRule`：Core 已完整，App 未实现绘图窗口（M7）。`FrameParser` 已于第一批接线（协议帧解析面板）。
