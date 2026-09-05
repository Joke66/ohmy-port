# OhmyPort

基于 Python + PySide6 的独立串口调试工具。
![输入图片说明](image.png)
## 功能特性

- **串口收发**：真·HEX 收发、编码选择（ASCII / UTF-8 / GBK）、完整串口参数（数据位/停止位/校验位/流控）、端口热插拔自动检测
- **多关键词过滤**：高亮 / 仅显示命中行 / 排除命中行 / 上下分栏显示命中行
- **数值绘图**：独立窗口、黑底折线图、自定义提取规则（正则捕获组或关键词）、时间横轴、缺失保持上一值
- **日志**：连接后自动保存（COM口+时间戳命名）、自动分片（大小可配）、毫秒级时间戳、保存目录可配置
- **发送辅助**：SSCOM 式命令（名称+内容）、页签分页（每页 8 个）、定时循环发送、右键编辑/删除
- **自动应答**：按关键词自动回复
- **主题**：深色 / 护眼 / 白天（基于 pyqtdarktheme）

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行

```bash
python serial_tool.py
```

## 打包为 EXE

Windows 下双击运行 `build.bat`，或在命令行执行：

```bash
python -m PyInstaller --noconfirm --clean --windowed --onefile --name SerialTool --collect-all qdarktheme serial_tool.py
```

打包产物在 `dist\SerialTool.exe`（依赖 `pyinstaller`，首次请先 `pip install pyinstaller`）。

## 使用说明

1. 选择端口和波特率，点击「打开串口」；连接成功后自动开始保存日志（可在「设置」关闭）。
2. 发送区输入内容，回车或点「发送」；勾选「HEX发送」可发送十六进制（如 `01 03 00 0A`）。
3. 「视图 → 发送辅助」添加常用命令（名称+内容），点击按钮即发送，右键按钮编辑/删除。
4. 「视图 → 数值绘图」打开绘图窗口，添加提取规则（如 `temp=(\d+\.?\d*)` 或关键词 `NTC`），实时绘制曲线。
5. 「视图 → 主题」切换深色 / 护眼 / 白天。
6. 「设置 → 日志保存目录」可自定义日志保存位置；「设置 → 日志分片大小」调整单文件上限。

## 版本信息

- 版本：1.2.0
- 作者：zhangyaoxing
- 日期：2026-09-05
