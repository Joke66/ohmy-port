"""串口工具（独立工具）：实时串口日志 + 多关键词过滤 + 时间戳保存 + 高级串口调试。

独立于「老化板上位机」，可单独运行：
    python serial_tool.py

也可由主工具通过「打开串口工具」按钮拉起。自包含：仅依赖 pyserial + PySide6。

功能概览：
- 真·HEX 收发、编码选择（ASCII/UTF-8/GBK）、完整串口参数（菜单展开）
- 多关键词过滤（高亮/仅显示/排除/上下分栏）
- 发送辅助（换行/历史/定时发送/快捷按钮）、收发统计
- 端口热插拔自动检测、深色主题、字体缩放、自动保存分片
- 数值曲线绘图、脚本/自动应答（菜单展开）
"""

from __future__ import annotations

import collections
import datetime
import queue
import re
import sys
import threading
import time
from pathlib import Path

import serial
from serial.tools import list_ports

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPainter, QPen, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

_BAUDS = ["115200", "57600", "38400", "19200", "9600", "4800", "2400", "921600"]
_ENCODINGS = [("UTF-8", "utf-8"), ("GBK", "gbk"), ("ASCII", "ascii")]
_NEWLINES = [("无", ""), ("\\r", "\r"), ("\\n", "\n"), ("\\r\\n", "\r\n")]
_HL_BG = QColor("#fff59d")
_HL_FG = QColor("#000000")

# 性能 / 行为参数
_MAX_LINES = 50_000
_FLUSH_MS = 80
_READ_CHUNK = 4096
_HL_INTERVAL = 0.5
_HOTPLUG_MS = 2000
_RECORD_MAX_BYTES = 5 * 1024 * 1024  # 单文件 5MB 自动分片
_PLOT_WINDOW = 600

_DARK_QSS = """
QWidget { background-color: #1e1e1e; color: #d4d4d4; font-size: 13px; }
QPushButton { background-color: #2d2d2d; border: 1px solid #3c3c3c; padding: 5px 10px; border-radius: 3px; }
QPushButton:hover { background-color: #3c3c3c; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTableWidget { background-color: #252525; border: 1px solid #3c3c3c; }
QComboBox QAbstractItemView { background-color: #252525; selection-background-color: #0e639c; }
QPlainTextEdit { background-color: #1e1e1e; }
QHeaderView::section { background-color: #2d2d2d; border: 1px solid #3c3c3c; }
QMenuBar { background-color: #252525; }
QMenu { background-color: #2d2d2d; }
QMenu::item:selected { background-color: #0e639c; }
"""

_NUM_RE = re.compile(r"-?\d+\.?\d*")


def _now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _ts_name() -> str:
    return datetime.datetime.now().strftime("serial_%Y%m%d_%H%M%S")


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _extract_numbers(text: str) -> list[float]:
    return [float(m) for m in _NUM_RE.findall(text)]


class LogFilter:
    """多关键词过滤/高亮。mode: highlight / include / exclude / split。"""

    def __init__(self, keywords=None, mode="highlight", case_sensitive=False):
        self.keywords = [k for k in (keywords or []) if k]
        self.mode = mode
        self.case_sensitive = case_sensitive

    @staticmethod
    def parse_keywords(text: str) -> list[str]:
        for sep in (",", ";", "\n", "\t", " "):
            text = text.replace(sep, ",")
        seen: list[str] = []
        for k in text.split(","):
            k = k.strip()
            if k and k not in seen:
                seen.append(k)
        return seen

    def matched(self, line: str) -> list[str]:
        hay = line if self.case_sensitive else line.lower()
        hits: list[str] = []
        for k in self.keywords:
            needle = k if self.case_sensitive else k.lower()
            if needle and needle in hay:
                hits.append(k)
        return hits

    def visible(self, line: str) -> bool:
        if not self.keywords:
            return True
        hit = bool(self.matched(line))
        if self.mode == "include":
            return hit
        if self.mode == "exclude":
            return not hit
        return True

    def highlight_enabled(self) -> bool:
        return self.mode in ("highlight", "include", "split")


class SerialMonitor:
    """自包含串口封装（字节流）：连接 / 批量接收 / 发送。"""

    def __init__(self):
        self._serial = None
        self._callback = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @staticmethod
    def list_ports() -> list[tuple[str, str]]:
        return [(p.device, p.description or p.device) for p in list_ports.comports()]

    def connect(self, port: str, baudrate: int = 115200, bytesize: int = 8,
                parity: str = "N", stopbits: float = 1, flow: str = "none") -> bool:
        self.disconnect()
        kwargs = dict(
            bytesize=bytesize, parity=parity, stopbits=stopbits,
            rtscts=(flow == "rtscts"), dsrdtr=(flow == "dsrdtr"),
            xonxoff=(flow == "xonxoff"),
        )
        try:
            self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=0.1, **kwargs)
        except Exception:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        return True

    def disconnect(self) -> None:
        self._stop.set()
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._serial = None

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def set_receive_callback(self, cb) -> None:
        self._callback = cb

    def send(self, data: bytes) -> bool:
        if self._serial is None or not self._serial.is_open:
            return False
        try:
            self._serial.write(data)
            return True
        except Exception:
            return False

    def _receive_loop(self) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                if self._serial is not None and self._serial.is_open:
                    chunk = self._serial.read(_READ_CHUNK)
                    if not chunk:
                        continue
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    if lines and self._callback is not None:
                        cleaned = [l[:-1] if l.endswith(b"\r") else l for l in lines]
                        self._callback(cleaned)  # list[bytes]
            except Exception:
                if self._stop.is_set():
                    break


class PlotWidget(QWidget):
    """简易实时曲线：把收到的数值按通道绘制（QPainter，无第三方依赖）。"""

    _COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples: collections.deque = collections.deque(maxlen=_PLOT_WINDOW)
        self.setMinimumHeight(180)

    def add_sample(self, values: list[float]) -> None:
        if values:
            self._samples.append(list(values))
            self.update()

    def clear(self) -> None:
        self._samples.clear()
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#fafafa"))
        p.setPen(QPen(QColor("#dddddd")))
        p.drawLine(0, h // 2, w, h // 2)
        if len(self._samples) < 2:
            p.end()
            return
        n_channels = max((len(s) for s in self._samples), default=0)
        if n_channels == 0:
            p.end()
            return
        all_vals = [v for s in self._samples for v in s]
        lo, hi = min(all_vals), max(all_vals)
        if hi - lo < 1e-9:
            hi = lo + 1.0
        pad = 8
        top, bottom = pad, h - pad
        xs = list(self._samples)
        n = len(xs)
        for ch in range(n_channels):
            pts = []
            for i, s in enumerate(xs):
                if ch < len(s):
                    x = pad + i * (w - 2 * pad) / max(1, n - 1)
                    y = bottom - (s[ch] - lo) / (hi - lo) * (bottom - top)
                    pts.append((x, y))
            if len(pts) >= 2:
                pen = QPen(QColor(self._COLORS[ch % len(self._COLORS)]))
                pen.setWidth(2)
                p.setPen(pen)
                for i in range(1, len(pts)):
                    p.drawLine(int(pts[i - 1][0]), int(pts[i - 1][1]), int(pts[i][0]), int(pts[i][1]))
        p.end()


class ShortcutButton(QPushButton):
    """快捷发送按钮：单击发送，双击编辑命令文本。"""

    def __init__(self, text: str, on_edit):
        super().__init__(text)
        self._on_edit = on_edit

    def mouseDoubleClickEvent(self, event) -> None:
        self._on_edit(self)
        super().mouseDoubleClickEvent(event)


class _WheelZoomFilter(QObject):
    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                obj.zoomIn(1)
            elif delta < 0:
                obj.zoomOut(1)
            return True
        return False


class SerialToolWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("串口工具")
        self.resize(980, 720)
        self.serial = SerialMonitor()
        self._filter = LogFilter()
        self._buffer: collections.deque = collections.deque(maxlen=_MAX_LINES)
        self._pending: "queue.Queue[tuple[str, str, object]]" = queue.Queue()
        self._paused = False
        self._hex = False
        self._auto_scroll = True
        self._record_file = None
        self._last_highlight = 0.0
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._rate: collections.deque = collections.deque()  # (mono, rx, tx)
        self._known_ports: set[str] = set()
        self._dark = False
        self._send_commands: list[str] = [""] * 8
        self._wheel_filter = _WheelZoomFilter(self)
        self._build()
        self._build_menu()
        self.serial.set_receive_callback(self._on_receive_batch)
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(_FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()
        self._hotplug_timer = QTimer(self)
        self._hotplug_timer.setInterval(_HOTPLUG_MS)
        self._hotplug_timer.timeout.connect(self._check_hotplug)
        self._hotplug_timer.start()
        self._timer_send = QTimer(self)
        self._timer_send.timeout.connect(self._timer_send_tick)
        self.refresh_ports()

    # ---------- UI 构建 ----------
    def _btn(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(slot)
        return btn

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        view = menubar.addMenu("视图")

        acts = [
            ("串口参数", self.serial_params_panel),
            ("发送辅助", self.send_assist_panel),
            ("数值绘图", self.plot_panel),
            ("自动应答", self.auto_reply_panel),
        ]
        for label, panel in acts:
            a = QAction(label, self, checkable=True)
            a.toggled.connect(panel.setVisible)
            view.addAction(a)

        view.addSeparator()
        self.dark_action = QAction("深色主题", self, checkable=True)
        self.dark_action.toggled.connect(self._apply_theme)
        view.addAction(self.dark_action)

        zoom_in = QAction("字体增大", self)
        zoom_in.triggered.connect(lambda: self.log_text.zoomIn(1))
        zoom_out = QAction("字体减小", self)
        zoom_out.triggered.connect(lambda: self.log_text.zoomOut(1))
        zoom_reset = QAction("重置字体", self)
        zoom_reset.triggered.connect(self._reset_font)
        view.addSeparator()
        view.addAction(zoom_in)
        view.addAction(zoom_out)
        view.addAction(zoom_reset)

        help_menu = menubar.addMenu("帮助")
        about = QAction("关于", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # 连接行
        conn = QHBoxLayout()
        conn.addWidget(QLabel("端口"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(120)
        conn.addWidget(self.port_combo)
        conn.addWidget(self._btn("刷新", self.refresh_ports))
        conn.addWidget(QLabel("波特率"))
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(_BAUDS)
        self.baud_combo.setCurrentText("115200")
        conn.addWidget(self.baud_combo)
        self.connect_btn = self._btn("打开串口", self.toggle_connection)
        conn.addWidget(self.connect_btn)
        conn.addStretch(1)
        layout.addLayout(conn)

        # 完整串口参数（隐藏面板）
        self.serial_params_panel = QWidget()
        sp = QHBoxLayout(self.serial_params_panel)
        sp.setContentsMargins(0, 0, 0, 0)
        sp.addWidget(QLabel("数据位"))
        self.databits_combo = QComboBox()
        for v in ("8", "7", "6", "5"):
            self.databits_combo.addItem(v, int(v))
        sp.addWidget(self.databits_combo)
        sp.addWidget(QLabel("停止位"))
        self.stopbits_combo = QComboBox()
        for label, v in (("1", 1), ("1.5", 1.5), ("2", 2)):
            self.stopbits_combo.addItem(label, v)
        sp.addWidget(self.stopbits_combo)
        sp.addWidget(QLabel("校验位"))
        self.parity_combo = QComboBox()
        for label, v in (("无", "N"), ("奇", "O"), ("偶", "E"), ("标记", "M"), ("空格", "S")):
            self.parity_combo.addItem(label, v)
        sp.addWidget(self.parity_combo)
        sp.addWidget(QLabel("流控"))
        self.flow_combo = QComboBox()
        for label, v in (("无", "none"), ("RTS/CTS", "rtscts"), ("DTR/DSR", "dsrdtr"), ("XON/XOFF", "xonxoff")):
            self.flow_combo.addItem(label, v)
        sp.addWidget(self.flow_combo)
        sp.addStretch(1)
        self.serial_params_panel.setVisible(False)
        layout.addWidget(self.serial_params_panel)

        # 过滤行
        filt = QHBoxLayout()
        filt.addWidget(QLabel("关键词"))
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("多个关键词用逗号/空格分隔，如 Err,Timeout,0x50")
        self.keyword_edit.returnPressed.connect(self.apply_filter)
        filt.addWidget(self.keyword_edit, 1)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("显示全部并高亮", "highlight")
        self.mode_combo.addItem("仅显示命中行", "include")
        self.mode_combo.addItem("排除命中行", "exclude")
        self.mode_combo.addItem("上下分栏显示命中行", "split")
        self.mode_combo.currentIndexChanged.connect(self.apply_filter)
        filt.addWidget(self.mode_combo)
        self.case_check = QCheckBox("区分大小写")
        self.case_check.toggled.connect(self.apply_filter)
        filt.addWidget(self.case_check)
        filt.addWidget(QLabel("编码"))
        self.encoding_combo = QComboBox()
        for label, codec in _ENCODINGS:
            self.encoding_combo.addItem(label, codec)
        self.encoding_combo.currentIndexChanged.connect(self._rerender)
        filt.addWidget(self.encoding_combo)
        self.hex_view_check = QCheckBox("HEX显示")
        self.hex_view_check.toggled.connect(self._on_hex_view)
        filt.addWidget(self.hex_view_check)
        filt.addWidget(self._btn("应用", self.apply_filter))
        layout.addLayout(filt)

        # 上：日志内容
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(_MAX_LINES)
        self.log_text.installEventFilter(self._wheel_filter)
        layout.addWidget(self.log_text, 3)

        # 下：命中结果面板
        self.matched_panel = QWidget()
        mp = QVBoxLayout(self.matched_panel)
        mp.setContentsMargins(0, 4, 0, 0)
        mp.setSpacing(2)
        mp_bar = QHBoxLayout()
        mp_bar.addWidget(QLabel("命中结果"))
        mp_bar.addWidget(self._btn("清空", self._clear_matched))
        mp_bar.addStretch(1)
        mp.addLayout(mp_bar)
        self.matched_text = QPlainTextEdit()
        self.matched_text.setReadOnly(True)
        self.matched_text.setMaximumBlockCount(_MAX_LINES)
        self.matched_text.installEventFilter(self._wheel_filter)
        mp.addWidget(self.matched_text)
        self.matched_panel.setVisible(False)
        layout.addWidget(self.matched_panel, 1)

        # 发送辅助（隐藏面板）
        self.send_assist_panel = QWidget()
        sa = QVBoxLayout(self.send_assist_panel)
        sa.setContentsMargins(0, 0, 0, 0)
        sa.setSpacing(3)
        timer_row = QHBoxLayout()
        self.timer_check = QCheckBox("定时发送")
        self.timer_check.toggled.connect(self._on_timer_toggle)
        timer_row.addWidget(self.timer_check)
        timer_row.addWidget(QLabel("间隔(ms)"))
        self.timer_spin = QSpinBox()
        self.timer_spin.setRange(10, 3_600_000)
        self.timer_spin.setValue(1000)
        self.timer_spin.valueChanged.connect(self._on_timer_interval)
        timer_row.addWidget(self.timer_spin)
        timer_row.addStretch(1)
        sa.addLayout(timer_row)
        short_row = QHBoxLayout()
        short_row.addWidget(QLabel("快捷发送(双击编辑)"))
        self.short_btns: list[ShortcutButton] = []
        for i in range(8):
            btn = ShortcutButton(f"F{i + 1}", self._edit_shortcut)
            btn.setToolTip("双击设置命令，单击发送")
            btn.clicked.connect(lambda _=False, idx=i: self._send_shortcut(idx))
            self.short_btns.append(btn)
            short_row.addWidget(btn)
        short_row.addStretch(1)
        sa.addLayout(short_row)
        self.send_assist_panel.setVisible(False)
        layout.addWidget(self.send_assist_panel)

        # 底部操作行 + 统计
        bar = QHBoxLayout()
        self.pause_btn = self._btn("暂停", self.toggle_pause)
        bar.addWidget(self.pause_btn)
        bar.addWidget(self._btn("清空", self.clear_log))
        self.scroll_check = QCheckBox("自动滚动")
        self.scroll_check.setChecked(True)
        self.scroll_check.toggled.connect(lambda c: setattr(self, "_auto_scroll", c))
        bar.addWidget(self.scroll_check)
        self.record_btn = self._btn("开始记录", self.toggle_record)
        bar.addWidget(self.record_btn)
        bar.addWidget(self._btn("保存日志", self.save_log))
        bar.addStretch(1)
        self.stat_label = QLabel("RX: 0 B  TX: 0 B")
        self.stat_label.setStyleSheet("color: #888888;")
        bar.addWidget(self.stat_label)
        layout.addLayout(bar)

        # 发送行
        send = QHBoxLayout()
        self.send_combo = QComboBox()
        self.send_combo.setEditable(True)
        self.send_combo.setInsertPolicy(QComboBox.NoInsert)
        self.send_combo.lineEdit().setPlaceholderText("发送内容（HEX 模式输入如 01 03 00 0A）")
        self.send_combo.lineEdit().returnPressed.connect(self.send_raw)
        send.addWidget(self.send_combo, 1)
        self.newline_combo = QComboBox()
        for label, v in _NEWLINES:
            self.newline_combo.addItem(label, v)
        send.addWidget(self.newline_combo)
        self.hex_send_check = QCheckBox("HEX发送")
        send.addWidget(self.hex_send_check)
        send.addWidget(self._btn("发送", self.send_raw))
        layout.addLayout(send)

        # 数值绘图（隐藏面板）
        self.plot_panel = QWidget()
        pp = QVBoxLayout(self.plot_panel)
        pp.setContentsMargins(0, 4, 0, 0)
        pp_bar = QHBoxLayout()
        pp_bar.addWidget(QLabel("数值曲线（提取每行数字）"))
        pp_bar.addWidget(self._btn("清空", self._clear_plot))
        pp_bar.addStretch(1)
        pp.addLayout(pp_bar)
        self.plot_widget = PlotWidget()
        pp.addWidget(self.plot_widget)
        self.plot_panel.setVisible(False)
        layout.addWidget(self.plot_panel)

        # 自动应答（隐藏面板）
        self.auto_reply_panel = QWidget()
        ar = QVBoxLayout(self.auto_reply_panel)
        ar.setContentsMargins(0, 4, 0, 0)
        ar_bar = QHBoxLayout()
        self.auto_enable = QCheckBox("启用自动应答")
        ar_bar.addWidget(self.auto_enable)
        ar_bar.addWidget(self._btn("添加规则", self._add_auto_rule))
        ar_bar.addWidget(self._btn("删除选中", self._del_auto_rule))
        ar_bar.addStretch(1)
        ar.addLayout(ar_bar)
        self.auto_table = QTableWidget(0, 2)
        self.auto_table.setHorizontalHeaderLabels(["触发关键词", "应答内容"])
        self.auto_table.horizontalHeader().setStretchLastSection(True)
        ar.addWidget(self.auto_table)
        self.auto_reply_panel.setVisible(False)
        layout.addWidget(self.auto_reply_panel)

    # ---------- 串口 ----------
    def refresh_ports(self) -> None:
        current = self.port_combo.currentData()
        self.port_combo.clear()
        for device, desc in self.serial.list_ports():
            self.port_combo.addItem(f"{device}（{desc}）", device)
        self._known_ports = {d for d, _ in self.serial.list_ports()}
        if current:
            idx = self.port_combo.findData(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def _check_hotplug(self) -> None:
        if self.serial.is_connected:
            return
        current = {d for d, _ in self.serial.list_ports()}
        if current != self._known_ports:
            self._known_ports = current
            self.refresh_ports()

    def toggle_connection(self) -> None:
        if self.serial.is_connected:
            self.serial.disconnect()
            self.connect_btn.setText("打开串口")
            self._sys("已关闭串口")
        else:
            port = self.port_combo.currentData()
            if not port:
                self._sys("请选择串口")
                return
            try:
                baud = int(self.baud_combo.currentText())
            except ValueError:
                self._sys("波特率无效")
                return
            kwargs = dict(
                bytesize=self.databits_combo.currentData(),
                parity=self.parity_combo.currentData(),
                stopbits=self.stopbits_combo.currentData(),
                flow=self.flow_combo.currentData(),
            )
            if self.serial.connect(port, baud, **kwargs):
                self.connect_btn.setText("关闭串口")
                self._sys(f"已打开 {port} @ {baud}")
            else:
                self._sys(f"打开 {port} 失败")

    def _on_receive_batch(self, lines: list[bytes]) -> None:
        for line in lines:
            self._pending.put((_now(), "rx", line))

    # ---------- 发送 ----------
    def send_raw(self) -> None:
        text = self.send_combo.currentText()
        if not text:
            return
        if self.hex_send_check.isChecked():
            data = self._parse_hex(text)
            if data is None:
                self._sys("HEX 格式无效（示例：01 03 00 0A）")
                return
        else:
            nl = self.newline_combo.currentData()
            data = (text + nl).encode(self._encoding(), errors="replace")
        if self._do_send(data):
            self._add_send_history(text)
            self.send_combo.setCurrentText("")

    def _parse_hex(self, text: str) -> bytes | None:
        t = text.replace(" ", "").replace("0x", "").replace("0X", "")
        try:
            return bytes.fromhex(t)
        except ValueError:
            return None

    def _send_text(self, text: str) -> None:
        nl = self.newline_combo.currentData()
        self._do_send((text + nl).encode(self._encoding(), errors="replace"))

    def _do_send(self, data: bytes) -> bool:
        if not self.serial.is_connected:
            self._sys("串口未打开，无法发送")
            return False
        if self.serial.send(data):
            self._tx_bytes += len(data)
            self._pending.put((_now(), "tx", data))
            return True
        return False

    def _add_send_history(self, text: str) -> None:
        if self.send_combo.findText(text) < 0:
            self.send_combo.addItem(text)
        while self.send_combo.count() > 50:
            self.send_combo.removeItem(0)

    def _timer_send_tick(self) -> None:
        if self.serial.is_connected and self.send_combo.currentText():
            self.send_raw()

    def _on_timer_toggle(self, checked: bool) -> None:
        if checked:
            self._timer_send.start(self.timer_spin.value())
        else:
            self._timer_send.stop()

    def _on_timer_interval(self, ms: int) -> None:
        if self.timer_check.isChecked():
            self._timer_send.start(ms)

    def _send_shortcut(self, idx: int) -> None:
        cmd = self._send_commands[idx]
        if not cmd:
            self._sys(f"快捷按钮 F{idx + 1} 未设置（双击编辑）")
            return
        if self.hex_send_check.isChecked():
            data = self._parse_hex(cmd)
            if data is None:
                self._sys("快捷命令 HEX 格式无效")
                return
        else:
            nl = self.newline_combo.currentData()
            data = (cmd + nl).encode(self._encoding(), errors="replace")
        self._do_send(data)

    def _edit_shortcut(self, btn: ShortcutButton) -> None:
        idx = self.short_btns.index(btn)
        text, ok = QInputDialog.getText(self, "编辑快捷命令", f"F{idx + 1} 命令：",
                                        text=self._send_commands[idx])
        if ok:
            self._send_commands[idx] = text
            btn.setText(text if text else f"F{idx + 1}")

    # ---------- 日志 ----------
    def _encoding(self) -> str:
        return self.encoding_combo.currentData()

    def _sys(self, text: str) -> None:
        self._pending.put((_now(), "sys", text))

    def _dir_mark(self, d: str) -> str:
        return {"rx": "收←◆", "tx": "发→◇", "sys": "  ◆"}.get(d, "")

    def _payload_text(self, payload) -> str:
        if isinstance(payload, bytes):
            return payload.decode(self._encoding(), errors="replace")
        return payload

    def _format_line(self, ts: str, direction: str, payload) -> str:
        if isinstance(payload, bytes):
            if self._hex:
                body = payload.hex(" ").upper()
            else:
                body = payload.decode(self._encoding(), errors="replace")
        else:
            body = payload
        return f"[{ts}] {self._dir_mark(direction)} {body}"

    def _flush(self) -> None:
        items: list[tuple[str, str, object]] = []
        while True:
            try:
                items.append(self._pending.get_nowait())
            except queue.Empty:
                break
        if not items:
            return
        pieces: list[str] = []
        matched_pieces: list[str] = []
        plot_values: list[float] = []
        for ts, direction, payload in items:
            if self._paused and direction != "sys":
                continue
            self._buffer.append((ts, direction, payload))
            text = self._payload_text(payload)
            if direction == "rx":
                self._rx_bytes += len(payload) + 1 if isinstance(payload, bytes) else 0
            if self._record_file is not None:
                self._record_file.write(self._format_line(ts, direction, payload) + "\n")
            if self._filter.visible(text):
                pieces.append(self._format_line(ts, direction, payload))
            if self._filter.mode == "split" and self._filter.matched(text):
                matched_pieces.append(self._format_line(ts, direction, payload))
            if direction == "rx" and not self.plot_panel.isHidden():
                plot_values.extend(_extract_numbers(text))
        if pieces:
            self.log_text.appendPlainText("\n".join(pieces))
        if matched_pieces:
            self.matched_text.appendPlainText("\n".join(matched_pieces))
        if plot_values:
            self.plot_widget.add_sample(plot_values[:6])
        if self._record_file is not None:
            self._record_file.flush()
            if self._record_file.tell() >= _RECORD_MAX_BYTES:
                self._rotate_record()
        self._update_stats()
        self._scroll()
        self._maybe_highlight()
        if self.auto_enable.isChecked():
            for ts, direction, payload in items:
                if direction == "rx":
                    self._check_auto_reply(self._payload_text(payload))

    def _scroll(self) -> None:
        if self._auto_scroll:
            sb = self.log_text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _rerender(self) -> None:
        self.log_text.clear()
        pieces: list[str] = []
        for ts, direction, payload in self._buffer:
            text = self._payload_text(payload)
            if self._filter.visible(text):
                pieces.append(self._format_line(ts, direction, payload))
        if pieces:
            self.log_text.appendPlainText("\n".join(pieces))
        self._scroll()
        self._render_matched()
        self._apply_highlight(self.log_text)
        self._last_highlight = time.monotonic()

    def _on_hex_view(self, checked: bool) -> None:
        self._hex = checked
        self._rerender()

    def clear_log(self) -> None:
        self._buffer.clear()
        self.log_text.clear()
        self.matched_text.clear()
        self.plot_widget.clear()

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText("继续" if self._paused else "暂停")
        if not self._paused:
            self._rerender()

    # ---------- 统计 ----------
    def _update_stats(self) -> None:
        now = time.monotonic()
        self._rate.append((now, self._rx_bytes, self._tx_bytes))
        while self._rate and now - self._rate[0][0] > 1.0:
            self._rate.popleft()
        if len(self._rate) >= 2:
            t0, rx0, tx0 = self._rate[0]
            dt = now - t0
            rx_rate = (self._rx_bytes - rx0) / dt if dt > 0 else 0
            tx_rate = (self._tx_bytes - tx0) / dt if dt > 0 else 0
            self.stat_label.setText(
                f"RX: {_fmt_bytes(self._rx_bytes)} ({_fmt_bytes(int(rx_rate))}/s)   "
                f"TX: {_fmt_bytes(self._tx_bytes)} ({_fmt_bytes(int(tx_rate))}/s)")
        else:
            self.stat_label.setText(f"RX: {_fmt_bytes(self._rx_bytes)}   TX: {_fmt_bytes(self._tx_bytes)}")

    # ---------- 高亮 ----------
    def _maybe_highlight(self) -> None:
        now = time.monotonic()
        if now - self._last_highlight < _HL_INTERVAL:
            return
        self._last_highlight = now
        self._apply_highlight(self.log_text)
        if self._filter.mode == "split":
            self._apply_highlight(self.matched_text)

    def _apply_highlight(self, widget: QPlainTextEdit) -> None:
        if self._hex or not self._filter.highlight_enabled() or not self._filter.keywords:
            widget.setExtraSelections([])
            return
        fmt = QTextCharFormat()
        fmt.setBackground(_HL_BG)
        fmt.setForeground(_HL_FG)
        flags = (QTextDocument.FindFlag.FindCaseSensitively
                 if self._filter.case_sensitive else QTextDocument.FindFlag(0))
        doc = widget.document()
        selections: list = []
        for kw in self._filter.keywords:
            cursor = doc.find(kw, 0, flags)
            while not cursor.isNull():
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                selections.append(sel)
                cursor = doc.find(kw, cursor.position(), flags)
        widget.setExtraSelections(selections)

    # ---------- 过滤 ----------
    def apply_filter(self) -> None:
        self._filter.keywords = LogFilter.parse_keywords(self.keyword_edit.text())
        self._filter.mode = self.mode_combo.currentData()
        self._filter.case_sensitive = self.case_check.isChecked()
        self._rerender()
        self.matched_panel.setVisible(self._filter.mode == "split")

    def _render_matched(self) -> None:
        if self._filter.mode != "split":
            return
        self.matched_text.clear()
        pieces: list[str] = []
        for ts, direction, payload in self._buffer:
            if self._filter.matched(self._payload_text(payload)):
                pieces.append(self._format_line(ts, direction, payload))
        if pieces:
            self.matched_text.appendPlainText("\n".join(pieces))
        self._apply_highlight(self.matched_text)

    def _clear_matched(self) -> None:
        self.matched_text.clear()

    # ---------- 绘图 ----------
    def _clear_plot(self) -> None:
        self.plot_widget.clear()

    # ---------- 自动应答 ----------
    def _add_auto_rule(self) -> None:
        row = self.auto_table.rowCount()
        self.auto_table.insertRow(row)
        self.auto_table.setItem(row, 0, QTableWidgetItem(""))
        self.auto_table.setItem(row, 1, QTableWidgetItem(""))

    def _del_auto_rule(self) -> None:
        row = self.auto_table.currentRow()
        if row >= 0:
            self.auto_table.removeRow(row)

    def _check_auto_reply(self, text: str) -> None:
        for row in range(self.auto_table.rowCount()):
            trigger_item = self.auto_table.item(row, 0)
            resp_item = self.auto_table.item(row, 1)
            trigger = trigger_item.text().strip() if trigger_item else ""
            response = resp_item.text().strip() if resp_item else ""
            if trigger and response and trigger.lower() in text.lower():
                self._send_text(response)

    # ---------- 保存 ----------
    def _log_dir(self) -> Path:
        return Path(__file__).resolve().parent / "Logs"

    def toggle_record(self) -> None:
        if self._record_file is not None:
            self._record_file.close()
            self._record_file = None
            self.record_btn.setText("开始记录")
            self._sys("已停止记录")
        else:
            self._open_record_file()
            self.record_btn.setText("停止记录")

    def _open_record_file(self) -> None:
        path = self._log_dir() / f"{_ts_name()}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._record_file = open(path, "a", encoding="utf-8")
        self._sys(f"开始记录到: {path}")

    def _rotate_record(self) -> None:
        if self._record_file is not None:
            self._record_file.close()
        self._open_record_file()
        self._sys("文件已达上限，已分片到新文件")

    def save_log(self) -> None:
        default = str(self._log_dir() / f"{_ts_name()}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "保存串口日志", default, "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for ts, direction, payload in self._buffer:
                    if self._filter.visible(self._payload_text(payload)):
                        f.write(self._format_line(ts, direction, payload) + "\n")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self._sys(f"日志已保存: {path}")

    # ---------- 主题 / 字体 ----------
    def _apply_theme(self, checked: bool) -> None:
        self._dark = checked
        self.setStyleSheet(_DARK_QSS if checked else "")

    def _reset_font(self) -> None:
        f = self.log_text.font()
        f.setPointSize(10)
        self.log_text.setFont(f)
        self.matched_text.setFont(f)

    def _show_about(self) -> None:
        QMessageBox.about(self, "关于", "<h3>串口工具</h3><p>独立串口调试工具。</p>")

    def closeEvent(self, event) -> None:
        self._flush_timer.stop()
        self._hotplug_timer.stop()
        self._timer_send.stop()
        if self._record_file is not None:
            self._record_file.close()
            self._record_file = None
        self.serial.disconnect()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    win = SerialToolWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
