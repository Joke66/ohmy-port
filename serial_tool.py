"""OhmyPort（串口工具）：多串口并行监听 + 实时日志 + 多关键词过滤 + 数值绘图。

独立于「老化板上位机」，可单独运行：
    python serial_tool.py

依赖：pyserial + PySide6 + pyqtgraph + pyqtdarktheme。

功能概览：
- 多串口：一个窗口内标签页并行监听多个串口，各串口参数/显示/过滤/记录/统计独立
- 真·HEX 收发、编码选择、完整串口参数、端口热插拔自动检测
- 多关键词过滤（高亮/仅显示/排除/上下分栏）
- 数值曲线绘图（独立窗口，可选监听串口）
- 日志：连接后自动保存（COM口+时间戳）、自动分片、精确时间戳、目录可配置
- 发送辅助（SSCOM 式命令、页签分页、定时循环发送）
- 三种主题（深色/护眼/白天）
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

import serial
from serial.tools import list_ports

import pyqtgraph as pg
import qdarktheme
from PIL import Image, ImageFilter

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPalette, QPixmap, QShortcut, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSlider, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

_BAUDS = ["115200", "57600", "38400", "19200", "9600", "4800", "2400", "921600"]
_ENCODINGS = [("UTF-8", "utf-8"), ("GBK", "gbk"), ("ASCII", "ascii")]
_NEWLINES = [("无", ""), ("\\r", "\r"), ("\\n", "\n"), ("\\r\\n", "\r\n")]
_HL_BG = QColor("#fff59d")
_HL_FG = QColor("#000000")
_SEARCH_BG = QColor("#ffb74d")
_SEARCH_BG_CURRENT = QColor("#ff9800")

# 性能 / 行为参数
_MAX_LINES = 50_000
_FLUSH_MS = 80
_READ_CHUNK = 4096
_HL_INTERVAL = 0.5
_HOTPLUG_MS = 2000
_PLOT_WINDOW = 600

_DATA_DIR: Path | None = None


def _exe_dir() -> Path:
    """exe 或脚本所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    """可写数据目录：优先 exe 同级，不可写则落到 %APPDATA%\\OhmyPort。"""
    global _DATA_DIR
    if _DATA_DIR is None:
        base = _exe_dir()
        probe = base / ".ohmyport_probe"
        try:
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            _DATA_DIR = base
        except OSError:
            appdata = Path(os.environ.get("APPDATA") or str(Path.home())) / "OhmyPort"
            try:
                appdata.mkdir(parents=True, exist_ok=True)
            except OSError:
                appdata = base
            _DATA_DIR = appdata
    return _DATA_DIR


# 日志保留策略：显示名 / 配置键 / 保留天数（0 表示无限制）
_LOG_RETENTION_OPTIONS = [
    ("一周", "week", 7),
    ("一个月", "month", 30),
    ("半年", "half_year", 180),
    ("一年", "year", 365),
    ("无限制", "unlimited", 0),
]
_LOG_RETENTION_KEYS = [k for _, k, _ in _LOG_RETENTION_OPTIONS]
_LOG_RETENTION_DAYS = {k: d for _, k, d in _LOG_RETENTION_OPTIONS}


_APP_NAME = "OhmyPort"
_APP_VERSION = "1.3.1"
_APP_AUTHOR = "ShineZhang"
_APP_DATE = "2026-09-05"
_APP_URL = "https://gitee.com/Shine_Zhang/ohmy-port"
_UPDATE_API = "https://gitee.com/api/v5/repos/Shine_Zhang/ohmy-port/releases/latest"
_UPDATE_PAGE = "https://gitee.com/Shine_Zhang/ohmy-port/releases"


def _parse_version(text: str) -> tuple:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return ()
    return tuple(int(x) for x in m.groups())


_THEME_CFG = {
    "black": {"theme": "dark"},
    "day": {"theme": "light"},
    "eye": {
        "theme": "light",
        "custom_colors": {
            "background": "#c8e6c9",
            "foreground": "#1f3b26",
            "primary": "#2e7d32",
            "input.background": "#eaf6ec",
            "border": "#a5d6a7",
        },
    },
}

_NUM_RE = re.compile(r"-?\d+\.?\d*")


def _now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _extract_numbers(text: str) -> list[float]:
    return [float(m) for m in _NUM_RE.findall(text)]


def _make_btn(text: str, slot) -> QPushButton:
    btn = QPushButton(text)
    btn.clicked.connect(slot)
    return btn


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
        self.rx_bytes = 0
        self.last_error = ""

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
        except Exception as exc:
            self.last_error = str(exc)
            return False
        self.last_error = ""
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
                    self.rx_bytes += len(chunk)
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    if lines and self._callback is not None:
                        cleaned = [l[:-1] if l.endswith(b"\r") else l for l in lines]
                        self._callback(cleaned)  # list[bytes]
            except Exception:
                if self._stop.is_set():
                    break
                time.sleep(0.02)


_PLOT_COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c"]


class PlotRule:
    """单条数值提取规则：正则(带捕获组)或关键词(取其后第一个数字)。"""

    def __init__(self, name: str, pattern: str):
        self.name = name
        self.pattern = pattern
        self._regex = None
        try:
            rx = re.compile(pattern)
            if rx.groups >= 1:
                self._regex = rx
        except re.error:
            self._regex = None

    def match(self, text: str) -> float | None:
        if self._regex is not None:
            m = self._regex.search(text)
            if not m:
                return None
            try:
                return float(m.group(1))
            except (ValueError, TypeError):
                pass
            nums = _extract_numbers(m.group(0))
            return nums[0] if nums else None
        if self.pattern:
            idx = text.lower().find(self.pattern.lower())
            if idx >= 0:
                nums = _extract_numbers(text[idx + len(self.pattern):])
                return nums[0] if nums else None
        return None


class PlotWidget(QWidget):
    """实时折线图（pyqtgraph）：黑底 + 命名通道图例，横轴为时间（秒）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t0: float | None = None
        self._curves: list = []
        self._data: list[collections.deque] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pw = pg.PlotWidget()
        self._pw.setBackground("#000000")
        self._pw.showGrid(x=True, y=True, alpha=0.25)
        self._pw.setLabel("bottom", "时间 (s)", color="#cccccc")
        self._pw.setLabel("left", "数值", color="#cccccc")
        for axis in ("bottom", "left"):
            self._pw.getAxis(axis).setTextPen("#cccccc")
            self._pw.getAxis(axis).setPen("#666666")
        layout.addWidget(self._pw)
        self.setMinimumHeight(200)
        self.set_channels([])

    def has_channels(self) -> bool:
        return bool(self._curves)

    def set_channels(self, names: list[str], show_legend: bool = True) -> None:
        self._curves = []
        self._data = []
        self._pw.clear()
        if show_legend:
            legend = self._pw.addLegend()
            legend.setLabelTextColor("#cccccc")
        for i, name in enumerate(names):
            color = _PLOT_COLORS[i % len(_PLOT_COLORS)]
            curve = self._pw.plot([], [], pen=pg.mkPen(color, width=2),
                                  name=(name if show_legend else None))
            self._curves.append(curve)
            self._data.append(collections.deque(maxlen=_PLOT_WINDOW))

    def add_sample(self, row: list) -> None:
        if self._t0 is None:
            self._t0 = time.monotonic()
        x = time.monotonic() - self._t0
        for i, v in enumerate(row):
            if v is not None and i < len(self._data):
                self._data[i].append((x, float(v)))
        for i, curve in enumerate(self._curves):
            data = self._data[i]
            if data:
                curve.setData([p[0] for p in data], [p[1] for p in data])

    def clear(self) -> None:
        self._t0 = None
        for data in self._data:
            data.clear()
        for curve in self._curves:
            curve.setData([], [])


def _fmt_val(v: float) -> str:
    if v == int(v):
        return str(int(v))
    return f"{v:.4f}".rstrip("0").rstrip(".")


class PlotWindow(QDialog):
    """数值绘图独立窗口：黑底折线图 + 右侧提取结果分栏 + 串口来源选择。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数值绘图")
        self.resize(900, 560)
        self._plot_rules: list[PlotRule] = []
        self._plot_last: list[float | None] = []
        self._sessions: list = []
        self._build()
        self._apply_rules()

    def _build(self) -> None:
        pp = QVBoxLayout(self)
        pp.setContentsMargins(8, 8, 8, 8)
        pp.setSpacing(4)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("数值曲线"))
        bar.addWidget(QLabel("串口:"))
        self._source_combo = QComboBox()
        bar.addWidget(self._source_combo)
        bar.addWidget(self._btn("添加规则", self._add_rule))
        bar.addWidget(self._btn("删除选中", self._del_rule))
        bar.addWidget(self._btn("清空", self.clear_plot))
        bar.addStretch(1)
        pp.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        self.plot_widget = PlotWidget()
        lv.addWidget(self.plot_widget, 1)
        hint = QLabel("规则：正则用 ( ) 圈出数值，如 temp=(\\d+\\.?\\d*)；"
                      "普通关键词则取关键词之后的第一个数字。无规则时不绘图。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888;")
        lv.addWidget(hint)
        self.rule_table = QTableWidget(0, 2)
        self.rule_table.setHorizontalHeaderLabels(["通道名", "命中规则"])
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        self.rule_table.itemChanged.connect(self._on_rule_changed)
        lv.addWidget(self.rule_table, 1)
        splitter.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        rv.addWidget(QLabel("提取结果"))
        self.result_table = QTableWidget(0, 2)
        self.result_table.setHorizontalHeaderLabels(["关键词", "数值"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        rv.addWidget(self.result_table, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([620, 220])
        pp.addWidget(splitter, 1)

    def _btn(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(slot)
        return btn

    def set_sessions(self, sessions: list) -> None:
        current = self._source_combo.currentData()
        self._sessions = list(sessions)
        self._source_combo.blockSignals(True)
        self._source_combo.clear()
        for s in self._sessions:
            self._source_combo.addItem(s.title(), s)
        if current in self._sessions:
            self._source_combo.setCurrentIndex(self._sessions.index(current))
        self._source_combo.blockSignals(False)

    def feed_from_session(self, session, texts: list[str]) -> None:
        if self._source_combo.currentData() is session:
            self.feed_texts(texts)

    # ---- 规则 ----
    def _add_rule(self) -> None:
        row = self.rule_table.rowCount()
        self.rule_table.insertRow(row)
        self.rule_table.setItem(row, 0, QTableWidgetItem(""))
        self.rule_table.setItem(row, 1, QTableWidgetItem(""))

    def _del_rule(self) -> None:
        row = self.rule_table.currentRow()
        if row >= 0:
            self.rule_table.removeRow(row)
            self._apply_rules()

    def _on_rule_changed(self, _item) -> None:
        self._apply_rules()

    def _apply_rules(self) -> None:
        rules: list[PlotRule] = []
        for row in range(self.rule_table.rowCount()):
            name_item = self.rule_table.item(row, 0)
            rule_item = self.rule_table.item(row, 1)
            name = (name_item.text() if name_item else "").strip()
            pattern = (rule_item.text() if rule_item else "").strip()
            if name or pattern:
                rules.append(PlotRule(name or f"通道{len(rules) + 1}", pattern))
        new_names = [r.name for r in rules]
        old_names = [r.name for r in self._plot_rules]
        self._plot_rules = rules
        if new_names != old_names or not self.plot_widget.has_channels():
            self._plot_last = [None] * len(rules)
            self.plot_widget.set_channels(new_names, show_legend=bool(rules))
            self.plot_widget.clear()
        self._rebuild_result_table()

    # ---- 数据接入 ----
    def feed_texts(self, texts: list[str]) -> None:
        if not texts or not self.isVisible() or not self._plot_rules:
            return
        rule_row: list[float | None] = [None] * len(self._plot_rules)
        for text in texts:
            for i, rule in enumerate(self._plot_rules):
                v = rule.match(text)
                if v is not None:
                    rule_row[i] = v
        for i in range(len(rule_row)):
            if rule_row[i] is None:
                rule_row[i] = self._plot_last[i]
            else:
                self._plot_last[i] = rule_row[i]
        self.plot_widget.add_sample(rule_row)
        self._update_values()

    # ---- 提取结果分栏 ----
    def _rebuild_result_table(self) -> None:
        self.result_table.setRowCount(len(self._plot_rules))
        for row, rule in enumerate(self._plot_rules):
            self.result_table.setItem(row, 0, QTableWidgetItem(rule.pattern or rule.name))
            last = self._plot_last[row] if row < len(self._plot_last) else None
            self.result_table.setItem(row, 1, QTableWidgetItem("--" if last is None else _fmt_val(last)))

    def _update_values(self) -> None:
        for row, last in enumerate(self._plot_last):
            item = self.result_table.item(row, 1)
            if item is not None:
                item.setText("--" if last is None else _fmt_val(last))

    def clear_plot(self) -> None:
        self.plot_widget.clear()
        self._plot_last = [None] * len(self._plot_rules)
        self._update_values()


class CommandButton(QPushButton):
    """命令按钮：单击发送，右键编辑/删除。"""

    def __init__(self, text: str, on_send, on_edit, on_delete):
        super().__init__(text)
        self._on_edit = on_edit
        self._on_delete = on_delete
        self.clicked.connect(on_send)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction("编辑", self._on_edit)
        menu.addAction("删除", self._on_delete)
        menu.exec(event.globalPos())
        menu.deleteLater()


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


class BgCentralWidget(QWidget):
    """整窗口背景层：在 paintEvent 中绘制一张（模糊）图片，作为唯一背景。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_pixmap: QPixmap | None = None
        self._bg_scaled: QPixmap | None = None

    def set_bg_pixmap(self, pixmap: QPixmap | None) -> None:
        self._bg_pixmap = pixmap
        self._bg_scaled = None
        self.update()

    def paintEvent(self, event) -> None:
        if self._bg_pixmap is not None and not self._bg_pixmap.isNull():
            if self._bg_scaled is None or self._bg_scaled.size() != self.size():
                self._bg_scaled = self._bg_pixmap.scaled(
                    self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                )
            p = QPainter(self)
            p.drawPixmap((self.width() - self._bg_scaled.width()) // 2,
                         (self.height() - self._bg_scaled.height()) // 2,
                         self._bg_scaled)
            p.end()
        else:
            super().paintEvent(event)


class BgPlainTextEdit(QPlainTextEdit):
    """透明日志框：背景透明，露出下方整窗口的唯一背景图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._default_base = self.palette().brush(QPalette.Base)
        self._default_window = self.palette().brush(QPalette.Window)
        self._default_autofill = self.autoFillBackground()
        self._default_vp_autofill = self.viewport().autoFillBackground()

    def set_transparent(self, flag: bool) -> None:
        pal = self.palette()
        if flag:
            pal.setBrush(QPalette.Base, QColor(0, 0, 0, 0))
            pal.setBrush(QPalette.Window, QColor(0, 0, 0, 0))
            self.setAutoFillBackground(False)
            self.setStyleSheet("QPlainTextEdit { background: transparent; }")
            self.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
            self.viewport().setAutoFillBackground(False)
        else:
            pal.setBrush(QPalette.Base, self._default_base)
            pal.setBrush(QPalette.Window, self._default_window)
            self.setAutoFillBackground(self._default_autofill)
            self.setStyleSheet("")
            self.viewport().setAttribute(Qt.WA_TranslucentBackground, False)
            self.viewport().setAutoFillBackground(self._default_vp_autofill)
        self.setPalette(pal)
        # 重新抛光，确保样式表/调色板变更立即生效
        self.style().unpolish(self)
        self.style().polish(self)
        self.viewport().style().unpolish(self.viewport())
        self.viewport().style().polish(self.viewport())
        self.update()


class CycleDialog(QDialog):
    """定时循环发送设置弹窗：启用/间隔/勾选参与循环的命令。"""

    def __init__(self, window):
        super().__init__(window)
        self._win = window
        self.setWindowTitle("定时循环发送")
        self.resize(460, 420)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.enable_check = QCheckBox("启用定时循环发送")
        self.enable_check.setChecked(self._win._cycle_enabled)
        self.enable_check.toggled.connect(self._win._set_cycle_enabled)
        top.addWidget(self.enable_check)
        top.addWidget(QLabel("间隔(ms)"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 3_600_000)
        self.interval_spin.setValue(self._win._cycle_interval)
        self.interval_spin.valueChanged.connect(self._win._set_cycle_interval)
        top.addWidget(self.interval_spin)
        top.addStretch(1)
        layout.addLayout(top)
        layout.addWidget(QLabel("勾选参与循环发送的命令："))
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list_widget, 1)
        self._refresh()

    def _refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, cmd in enumerate(self._win._commands):
            chk = QCheckBox(cmd.get("name") or f"命令{i + 1}")
            chk.setChecked(bool(cmd.get("cycle")))
            chk.setToolTip(cmd.get("content") or "")
            chk.toggled.connect(lambda checked, idx=i: self._win._set_command_cycle(idx, checked))
            self.list_layout.addWidget(chk)
        self.list_layout.addStretch(1)


class SerialSession(QWidget):
    """单个串口会话：独立的串口参数、显示、过滤、记录、统计。"""

    def __init__(self, window, index: int):
        super().__init__(window)
        self.window = window
        self.index = index
        self.serial = SerialMonitor()
        self._filter = LogFilter()
        self._buffer: collections.deque = collections.deque(maxlen=_MAX_LINES)
        self._pending: "queue.Queue[tuple[str, str, object]]" = queue.Queue()
        self._paused = False
        self._hex = False
        self._frozen = False
        self._filter_enabled = False
        self._record_file = None
        self._last_highlight = 0.0
        self._tx_bytes = 0
        self._rate: collections.deque = collections.deque()
        self._known_ports: set[str] = set()
        self._search_text = ""
        self._search_matches: list = []
        self._search_current = -1
        self._search_reverse = True
        self._last_search_refresh = 0.0
        self._suppress_scroll = False
        self._build()
        self.serial.set_receive_callback(self._on_receive_batch)
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(_FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()
        self._hotplug_timer = QTimer(self)
        self._hotplug_timer.setInterval(_HOTPLUG_MS)
        self._hotplug_timer.timeout.connect(self._check_hotplug)
        self._hotplug_timer.start()
        self.refresh_ports()

    def title(self) -> str:
        if self.serial.is_connected:
            return self.port_combo.currentData() or f"串口{self.index + 1}"
        return f"串口{self.index + 1}"

    def shutdown(self) -> None:
        self._flush_timer.stop()
        self._hotplug_timer.stop()
        if self._record_file is not None:
            self._record_file.close()
            self._record_file = None
        self.serial.disconnect()

    # ---------- UI 构建 ----------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # 连接行
        conn = QHBoxLayout()
        conn.addWidget(QLabel("端口"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(120)
        conn.addWidget(self.port_combo)
        conn.addWidget(_make_btn("刷新", self.refresh_ports))
        conn.addWidget(QLabel("波特率"))
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(_BAUDS)
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setMinimumWidth(90)
        conn.addWidget(self.baud_combo)
        self.connect_btn = _make_btn("打开串口", self.toggle_connection)
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
        self.keyword_edit.returnPressed.connect(self._enable_filter)
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
        self.filter_btn = _make_btn("应用", self.toggle_filter)
        filt.addWidget(self.filter_btn)
        layout.addLayout(filt)

        # 查找栏（Ctrl+F 显示，Esc 关闭）
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.addWidget(QLabel("查找"))
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("输入关键词，回车查找")
        self.find_input.returnPressed.connect(self._search_activate)
        fb.addWidget(self.find_input, 1)
        self.find_dir_combo = QComboBox()
        self.find_dir_combo.addItem("倒序", True)
        self.find_dir_combo.addItem("正序", False)
        self.find_dir_combo.currentIndexChanged.connect(self._on_find_dir_changed)
        fb.addWidget(self.find_dir_combo)
        self.find_case_check = QCheckBox("区分大小写")
        self.find_case_check.toggled.connect(self._on_find_case_changed)
        fb.addWidget(self.find_case_check)
        fb.addWidget(_make_btn("上一个", self._search_prev))
        fb.addWidget(_make_btn("下一个", self._search_next))
        self.find_count_label = QLabel("")
        fb.addWidget(self.find_count_label)
        fb.addWidget(_make_btn("✕", self._hide_find_bar))
        self.find_bar.setVisible(False)
        layout.addWidget(self.find_bar)

        # 上：日志内容
        self.log_text = BgPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(_MAX_LINES)
        self.log_text.installEventFilter(self.window._wheel_filter)
        self.log_text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_text.customContextMenuRequested.connect(self._show_log_menu)
        self.log_text.verticalScrollBar().valueChanged.connect(self._on_log_scrolled)
        layout.addWidget(self.log_text, 3)

        self.find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.find_shortcut.activated.connect(self._show_find_bar)
        self._esc_shortcut = QShortcut(QKeySequence("Esc"), self.find_bar)
        self._esc_shortcut.activated.connect(self._hide_find_bar)

        # 下：命中结果面板
        self.matched_panel = QWidget()
        mp = QVBoxLayout(self.matched_panel)
        mp.setContentsMargins(0, 4, 0, 0)
        mp.setSpacing(2)
        mp_bar = QHBoxLayout()
        mp_bar.addWidget(QLabel("命中结果"))
        mp_bar.addWidget(_make_btn("清空", self._clear_matched))
        mp_bar.addStretch(1)
        mp.addLayout(mp_bar)
        self.matched_text = BgPlainTextEdit()
        self.matched_text.setReadOnly(True)
        self.matched_text.setMaximumBlockCount(_MAX_LINES)
        self.matched_text.installEventFilter(self.window._wheel_filter)
        mp.addWidget(self.matched_text)
        self.matched_panel.setVisible(False)
        layout.addWidget(self.matched_panel, 1)

        # 底部操作行 + 统计
        bar = QHBoxLayout()
        self.pause_btn = _make_btn("暂停", self.toggle_pause)
        bar.addWidget(self.pause_btn)
        bar.addWidget(_make_btn("清空", self.clear_log))
        self.fixed_check = QCheckBox("固定显示")
        self.fixed_check.setChecked(False)
        self.fixed_check.setToolTip("固定模式下不刷新显示，但后台持续接收、记录、缓冲")
        self.fixed_check.toggled.connect(self._on_fixed_toggle)
        bar.addWidget(self.fixed_check)
        self.record_btn = _make_btn("开始记录", self.toggle_record)
        bar.addWidget(self.record_btn)
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
        send.addWidget(_make_btn("发送", self.send_raw))
        layout.addLayout(send)

        # 自动应答（隐藏面板）
        self.auto_reply_panel = QWidget()
        ar = QVBoxLayout(self.auto_reply_panel)
        ar.setContentsMargins(0, 4, 0, 0)
        ar_bar = QHBoxLayout()
        self.auto_enable = QCheckBox("启用自动应答")
        ar_bar.addWidget(self.auto_enable)
        ar_bar.addWidget(_make_btn("添加规则", self._add_auto_rule))
        ar_bar.addWidget(_make_btn("删除选中", self._del_auto_rule))
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
        current = {d for d, _ in self.serial.list_ports()}
        if self.serial.is_connected:
            port = self.port_combo.currentData()
            if port and port not in current:
                # 连接中的端口被拔出：自动断开并提示
                self._known_ports = current
                self.serial.disconnect()
                self.connect_btn.setText("打开串口")
                self._sys(f"串口 {port} 已断开")
                if self._record_file is not None:
                    self._stop_record()
                self.window.update_session_title(self)
            return
        if current != self._known_ports:
            self._known_ports = current
            self.refresh_ports()

    def toggle_connection(self) -> None:
        if self.serial.is_connected:
            self.serial.disconnect()
            self.connect_btn.setText("打开串口")
            self._sys("已关闭串口")
            if self._record_file is not None:
                self._stop_record()
            self.window.update_session_title(self)
        else:
            port = self.port_combo.currentData()
            if not port:
                self._sys("请选择串口")
                QMessageBox.warning(self, "串口连接", "请先选择串口")
                return
            try:
                baud = int(self.baud_combo.currentText())
            except ValueError:
                self._sys("波特率无效")
                QMessageBox.warning(self, "串口连接", "波特率无效")
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
                if self.window._auto_record and self._record_file is None:
                    self._start_record()
                self.window.update_session_title(self)
                self.window._save_config()
            else:
                reason = self.serial.last_error or "未知错误"
                self._sys(f"打开 {port} 失败：{reason}")
                QMessageBox.warning(
                    self, "串口连接",
                    f"串口 {port} 打开失败：\n{reason}\n\n"
                    "常见原因：端口不存在 / 被其它软件占用 / 无访问权限。",
                )

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

    def send_command_content(self, content: str) -> None:
        if not content:
            return
        if self.hex_send_check.isChecked():
            data = self._parse_hex(content)
            if data is None:
                self._sys("命令 HEX 格式无效")
                return
        else:
            nl = self.newline_combo.currentData()
            data = (content + nl).encode(self._encoding(), errors="replace")
        self._do_send(data)

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

    # ---------- 日志 ----------
    def _encoding(self) -> str:
        return self.encoding_combo.currentData()

    def _sys(self, text: str) -> None:
        self._pending.put((_now(), "sys", text))

    def _dir_mark(self, d: str) -> str:
        return {"rx": "", "tx": "SEND >>>>>>>>>>", "sys": "◆ "}.get(d, "")

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
        return f"[{ts}] {self._dir_mark(direction)}{body}"

    def _record_line(self, ts: str, direction: str, payload) -> str:
        # 记录固定为文本形式，不受「HEX 显示」切换影响
        body = self._payload_text(payload)
        return f"[{ts}] {self._dir_mark(direction)}{body}"

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
        rx_texts: list[str] = []
        for ts, direction, payload in items:
            self._buffer.append((ts, direction, payload))
            text = self._payload_text(payload)
            if self._record_file is not None:
                self._record_file.write(self._record_line(ts, direction, payload) + "\n")
            if self._paused and direction != "sys":
                continue  # 暂停只冻结显示（日志+绘图），后台仍缓冲/记录
            if self._filter.visible(text):
                pieces.append(self._format_line(ts, direction, payload))
            if self._filter.mode == "split" and self._filter.matched(text):
                matched_pieces.append(self._format_line(ts, direction, payload))
            if direction == "rx":
                rx_texts.append(text)
        self._suppress_scroll = True
        try:
            if pieces:
                self.log_text.appendPlainText("\n".join(pieces))
            if matched_pieces:
                self.matched_text.appendPlainText("\n".join(matched_pieces))
        finally:
            self._suppress_scroll = False
        if rx_texts:
            self.window.plot_window.feed_from_session(self, rx_texts)
        if self._record_file is not None:
            self._record_file.flush()
            if self._record_file.tell() >= self.window._shard_mb * 1024 * 1024:
                self._rotate_record()
        self._update_stats()
        if not self._frozen:
            self._scroll()
        self._maybe_highlight()
        if self._search_text:
            now = time.monotonic()
            if now - self._last_search_refresh > 0.5:
                self._last_search_refresh = now
                self._refresh_search()
        if self.auto_enable.isChecked():
            for ts, direction, payload in items:
                if direction == "rx":
                    self._check_auto_reply(self._payload_text(payload))

    def _scroll(self) -> None:
        self._suppress_scroll = True
        try:
            sb = self.log_text.verticalScrollBar()
            sb.setValue(sb.maximum())
        finally:
            self._suppress_scroll = False

    def _rerender(self) -> None:
        self._suppress_scroll = True
        try:
            self.log_text.clear()
            pieces: list[str] = []
            for ts, direction, payload in self._buffer:
                text = self._payload_text(payload)
                if self._filter.visible(text):
                    pieces.append(self._format_line(ts, direction, payload))
            if pieces:
                self.log_text.appendPlainText("\n".join(pieces))
        finally:
            self._suppress_scroll = False
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
        self.window.plot_window.clear_plot()

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText("继续" if self._paused else "暂停")
        if not self._paused:
            self._rerender()

    def _set_frozen(self, frozen: bool) -> None:
        if self._frozen == frozen:
            return
        self._frozen = frozen
        self.fixed_check.blockSignals(True)
        self.fixed_check.setChecked(frozen)
        self.fixed_check.blockSignals(False)

    def _on_fixed_toggle(self, checked: bool) -> None:
        self._set_frozen(checked)
        if not checked:
            self._scroll()

    def _on_log_scrolled(self, _value: int) -> None:
        if self._suppress_scroll:
            return
        sb = self.log_text.verticalScrollBar()
        dist = sb.maximum() - sb.value()
        page = max(1, sb.pageStep())
        if self._frozen and dist < page / 10:
            self._set_frozen(False)
        elif not self._frozen and dist > page / 3:
            self._set_frozen(True)

    # ---------- 查找 ----------
    def _show_find_bar(self) -> None:
        self.find_bar.setVisible(True)
        self.find_input.setFocus()
        self.find_input.selectAll()

    def _hide_find_bar(self) -> None:
        self.find_bar.setVisible(False)
        self.find_input.clear()
        self._search_text = ""
        self._search_matches = []
        self._search_current = -1
        self._update_search_count()
        self._apply_highlight(self.log_text)

    def _on_find_dir_changed(self) -> None:
        self._search_reverse = bool(self.find_dir_combo.currentData())
        if self._search_matches:
            self._search_current = len(self._search_matches) - 1 if self._search_reverse else 0
            self._goto_match(self._search_current)
            self._update_search_count()
            self._apply_highlight(self.log_text)

    def _on_find_case_changed(self) -> None:
        if self._search_text:
            self._do_search()

    def _scan_matches(self) -> list:
        kw = self._search_text
        matches: list = []
        if kw:
            flags = (QTextDocument.FindFlag.FindCaseSensitively
                     if self.find_case_check.isChecked() else QTextDocument.FindFlag(0))
            doc = self.log_text.document()
            cursor = doc.find(kw, 0, flags)
            while not cursor.isNull():
                matches.append(cursor)
                cursor = doc.find(kw, cursor.position(), flags)
        return matches

    def _search_activate(self) -> None:
        if self.find_input.text() != self._search_text:
            self._do_search()
            if self._search_matches:
                self._set_frozen(True)
        else:
            self._search_next()

    def _do_search(self) -> None:
        self._search_text = self.find_input.text()
        self._search_matches = self._scan_matches()
        if self._search_matches:
            self._search_current = len(self._search_matches) - 1 if self._search_reverse else 0
            self._goto_match(self._search_current)
        else:
            self._search_current = -1
        self._update_search_count()
        self._apply_highlight(self.log_text)

    def _refresh_search(self) -> None:
        self._search_matches = self._scan_matches()
        if not self._search_matches:
            self._search_current = -1
        elif self._search_current < 0 or self._search_current >= len(self._search_matches):
            self._search_current = len(self._search_matches) - 1 if self._search_reverse else 0
        self._update_search_count()
        self._apply_highlight(self.log_text)

    def _goto_match(self, idx: int) -> None:
        if 0 <= idx < len(self._search_matches):
            self._suppress_scroll = True
            try:
                self.log_text.setTextCursor(self._search_matches[idx])
                self.log_text.ensureCursorVisible()
            finally:
                self._suppress_scroll = False

    def _update_search_count(self) -> None:
        n = len(self._search_matches)
        if not self._search_text:
            self.find_count_label.setText("")
        elif n == 0:
            self.find_count_label.setText("0/0")
        else:
            cur = self._search_current + 1 if self._search_current >= 0 else 0
            self.find_count_label.setText(f"{cur}/{n}")

    def _search_next(self) -> None:
        if not self._search_matches:
            return
        if self._search_reverse:
            self._search_current = (self._search_current - 1) % len(self._search_matches)
        else:
            self._search_current = (self._search_current + 1) % len(self._search_matches)
        self._goto_match(self._search_current)
        self._update_search_count()
        self._apply_highlight(self.log_text)

    def _search_prev(self) -> None:
        if not self._search_matches:
            return
        if self._search_reverse:
            self._search_current = (self._search_current + 1) % len(self._search_matches)
        else:
            self._search_current = (self._search_current - 1) % len(self._search_matches)
        self._goto_match(self._search_current)
        self._update_search_count()
        self._apply_highlight(self.log_text)

    # ---------- 统计 ----------
    def _update_stats(self) -> None:
        now = time.monotonic()
        rx = self.serial.rx_bytes
        self._rate.append((now, rx, self._tx_bytes))
        while self._rate and now - self._rate[0][0] > 1.0:
            self._rate.popleft()
        if len(self._rate) >= 2:
            t0, rx0, tx0 = self._rate[0]
            dt = now - t0
            rx_rate = (rx - rx0) / dt if dt > 0 else 0
            tx_rate = (self._tx_bytes - tx0) / dt if dt > 0 else 0
            self.stat_label.setText(
                f"RX: {_fmt_bytes(rx)} ({_fmt_bytes(int(rx_rate))}/s)   "
                f"TX: {_fmt_bytes(self._tx_bytes)} ({_fmt_bytes(int(tx_rate))}/s)")
        else:
            self.stat_label.setText(f"RX: {_fmt_bytes(rx)}   TX: {_fmt_bytes(self._tx_bytes)}")

    # ---------- 高亮 ----------
    def _maybe_highlight(self) -> None:
        now = time.monotonic()
        if now - self._last_highlight < _HL_INTERVAL:
            return
        self._last_highlight = now
        self._apply_highlight(self.log_text)
        if self._filter.mode == "split":
            self._apply_highlight(self.matched_text)

    def _filter_selections(self, widget: QPlainTextEdit) -> list:
        if self._hex or not self._filter.highlight_enabled() or not self._filter.keywords:
            return []
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
        return selections

    def _search_selections(self, widget: QPlainTextEdit) -> list:
        if widget is not self.log_text or not self._search_matches:
            return []
        fmt = QTextCharFormat()
        fmt.setBackground(_SEARCH_BG)
        fmt.setForeground(QColor("#000000"))
        cur_fmt = QTextCharFormat()
        cur_fmt.setBackground(_SEARCH_BG_CURRENT)
        cur_fmt.setForeground(QColor("#000000"))
        selections: list = []
        for i, cursor in enumerate(self._search_matches):
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = cur_fmt if i == self._search_current else fmt
            selections.append(sel)
        return selections

    def _apply_highlight(self, widget: QPlainTextEdit) -> None:
        widget.setExtraSelections(self._filter_selections(widget) + self._search_selections(widget))

    # ---------- 过滤 ----------
    def toggle_filter(self) -> None:
        if self._filter_enabled:
            self._filter_enabled = False
            self._filter.keywords = []
            self.filter_btn.setText("应用")
            self._rerender()
            self.matched_panel.setVisible(False)
        else:
            self._enable_filter()

    def _enable_filter(self) -> None:
        self._filter_enabled = True
        self.apply_filter()
        self.filter_btn.setText("关闭")

    def apply_filter(self) -> None:
        if not self._filter_enabled:
            return
        self._filter.keywords = LogFilter.parse_keywords(self.keyword_edit.text())
        self._filter.mode = self.mode_combo.currentData()
        self._filter.case_sensitive = self.case_check.isChecked()
        self._rerender()
        self.matched_panel.setVisible(self._filter.mode == "split")
        self.window._save_config()

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
    def _log_basename(self) -> str:
        port = self.port_combo.currentData() or ""
        port = re.sub(r"[^0-9A-Za-z_-]", "_", port) or "serial"
        return f"{port}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _show_log_menu(self, pos) -> None:
        menu = self.log_text.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("保存日志", self.save_log)
        menu.addAction("打开日志目录", self.window._open_log_dir)
        menu.exec(self.log_text.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def toggle_record(self) -> None:
        if self._record_file is not None:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self) -> None:
        if self._record_file is None:
            self._open_record_file()
        if self._record_file is not None:
            self.record_btn.setText("停止记录")

    def _stop_record(self) -> None:
        if self._record_file is not None:
            self._record_file.close()
            self._record_file = None
        self.record_btn.setText("开始记录")
        self._sys("已停止记录")

    def _open_record_file(self) -> None:
        path = self.window._log_dir() / f"{self._log_basename()}.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._record_file = open(path, "a", encoding="utf-8")
        except OSError as exc:
            self._record_file = None
            self._sys(f"记录启动失败：{exc}")
            QMessageBox.warning(self, "记录失败", f"无法创建日志文件：\n{path}\n\n{exc}")
            return
        self._sys(f"开始记录到: {path}")

    def _rotate_record(self) -> None:
        if self._record_file is not None:
            self._record_file.close()
        self._open_record_file()
        self._sys("文件已达上限，已分片到新文件")

    def save_log(self) -> None:
        default = str(self.window._log_dir() / f"{self._log_basename()}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "保存串口日志", default, "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for ts, direction, payload in self._buffer:
                    f.write(self._record_line(ts, direction, payload) + "\n")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self._sys(f"日志已保存: {path}")


class SerialToolWindow(QMainWindow):
    _update_result = Signal(str, str, str)  # (status: update/none/error, tag, url)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{_APP_NAME} v{_APP_VERSION}")
        self.resize(980, 720)
        self._sessions: list[SerialSession] = []
        self._theme = "black"
        self._remembered_sessions: list[dict] = []
        self._pages: list[str] = ["第1页"]
        self._commands: list[dict] = []
        self._cycle_enabled = False
        self._cycle_interval = 1000
        self._cycle_dialog: CycleDialog | None = None
        self._log_dir_override: str | None = None
        self._auto_record = True
        self._shard_mb = 5
        self._log_retention = "month"
        self._last_update_check = ""
        self._bg_dir = str(_data_dir() / "background")
        self._bg_image = ""
        self._bg_blur = 10
        self._bg_enabled = False
        self._cycle_idx = 0
        self._wheel_filter = _WheelZoomFilter(self)
        self._load_config()
        self._build()
        self.plot_window = PlotWindow(self)
        self._build_menu()
        self._apply_theme_qss()
        self.plot_window.finished.connect(lambda _r: self.plot_action.setChecked(False))
        self._timer_send = QTimer(self)
        self._timer_send.timeout.connect(self._timer_send_tick)
        for _ in range(max(1, len(self._remembered_sessions))):
            self._add_session()
        for i, s in enumerate(self._sessions):
            if i < len(self._remembered_sessions):
                self._apply_remembered_state(s, self._remembered_sessions[i])
        self._apply_background()
        self._clean_old_logs()
        self._update_result.connect(self._on_update_result)
        QTimer.singleShot(2500, self._check_update)

    # ---------- UI ----------
    def _build(self) -> None:
        central = BgCentralWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(_make_btn("＋ 添加串口", self._add_session))
        top.addStretch(1)
        layout.addLayout(top)

        self.session_tabs = QTabWidget()
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self._close_session)
        self.session_tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.session_tabs, 1)

        # 发送辅助（全局，隐藏面板）
        self.send_assist_panel = QWidget()
        sa = QVBoxLayout(self.send_assist_panel)
        sa.setContentsMargins(0, 0, 0, 0)
        sa.setSpacing(3)
        bar = QHBoxLayout()
        bar.addWidget(_make_btn("添加命令", self._add_command))
        bar.addWidget(_make_btn("添加页", lambda: self._add_page()))
        bar.addWidget(_make_btn("定时循环发送...", self._open_cycle_dialog))
        bar.addStretch(1)
        sa.addLayout(bar)
        self.command_tabs = QTabWidget()
        self.command_tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.command_tabs.tabBar().customContextMenuRequested.connect(self._show_tab_menu)
        self.command_tabs.tabBarDoubleClicked.connect(self._rename_page)
        sa.addWidget(self.command_tabs, 1)
        self.send_assist_panel.setVisible(False)
        layout.addWidget(self.send_assist_panel)
        self._rebuild_command_tabs()

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # ---------- 文件 ----------
        file_menu = menubar.addMenu("文件")
        save_log_action = QAction("保存日志", self)
        save_log_action.setShortcut(QKeySequence("Ctrl+S"))
        save_log_action.triggered.connect(self._save_log_active)
        file_menu.addAction(save_log_action)
        open_log_dir_action = QAction("打开日志目录", self)
        open_log_dir_action.triggered.connect(self._open_log_dir)
        file_menu.addAction(open_log_dir_action)
        file_menu.addSeparator()
        export_action = QAction("导出配置...", self)
        export_action.triggered.connect(self._export_config)
        file_menu.addAction(export_action)
        import_action = QAction("导入配置...", self)
        import_action.triggered.connect(self._import_config)
        file_menu.addAction(import_action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # ---------- 视图 ----------
        view = menubar.addMenu("视图")

        self.params_action = QAction("串口参数", self, checkable=True)
        self.params_action.toggled.connect(self._toggle_active_params)
        view.addAction(self.params_action)

        self.send_assist_action = QAction("发送辅助", self, checkable=True)
        self.send_assist_action.toggled.connect(self.send_assist_panel.setVisible)
        view.addAction(self.send_assist_action)

        self.auto_reply_action = QAction("自动应答", self, checkable=True)
        self.auto_reply_action.toggled.connect(self._toggle_active_auto_reply)
        view.addAction(self.auto_reply_action)

        self.plot_action = QAction("数值绘图", self, checkable=True)
        self.plot_action.toggled.connect(self._toggle_plot_window)
        view.addAction(self.plot_action)

        zoom_in = QAction("字体增大", self)
        zoom_in.setShortcut(QKeySequence("Ctrl+="))
        zoom_in.triggered.connect(lambda: self._zoom_log(1))
        zoom_out = QAction("字体减小", self)
        zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        zoom_out.triggered.connect(lambda: self._zoom_log(-1))
        zoom_reset = QAction("重置字体", self)
        zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        zoom_reset.triggered.connect(self._reset_font)
        view.addSeparator()
        view.addAction(zoom_in)
        view.addAction(zoom_out)
        view.addAction(zoom_reset)

        # ---------- 设置 ----------
        settings_menu = menubar.addMenu("设置")
        theme_menu = settings_menu.addMenu("主题")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for label, key in (("黑色", "black"), ("护眼", "eye"), ("白天", "day")):
            a = QAction(label, self, checkable=True)
            a.setChecked(self._theme == key)
            a.triggered.connect(lambda _=False, k=key: self._set_theme(k))
            theme_group.addAction(a)
            theme_menu.addAction(a)
        bg_action = QAction("背景皮肤...", self)
        bg_action.triggered.connect(self._open_background_dialog)
        settings_menu.addAction(bg_action)
        settings_menu.addSeparator()
        self.auto_record_action = QAction("连接后自动保存日志", self, checkable=True)
        self.auto_record_action.setChecked(self._auto_record)
        self.auto_record_action.toggled.connect(self._set_auto_record)
        settings_menu.addAction(self.auto_record_action)
        log_dir_action = QAction("日志保存目录...", self)
        log_dir_action.triggered.connect(self._choose_log_dir)
        settings_menu.addAction(log_dir_action)
        shard_action = QAction("日志分片大小...", self)
        shard_action.triggered.connect(self._set_shard_size)
        settings_menu.addAction(shard_action)
        retention_action = QAction("日志保留策略...", self)
        retention_action.triggered.connect(self._set_log_retention)
        settings_menu.addAction(retention_action)

        # ---------- 帮助 ----------
        help_menu = menubar.addMenu("帮助")
        docs_action = QAction("使用说明", self)
        docs_action.triggered.connect(self._open_docs)
        help_menu.addAction(docs_action)
        check_update_action = QAction("检查更新", self)
        check_update_action.triggered.connect(self._check_update_manual)
        help_menu.addAction(check_update_action)
        help_menu.addSeparator()
        about = QAction("关于", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    # ---------- 会话管理 ----------
    def active_session(self) -> SerialSession | None:
        w = self.session_tabs.currentWidget()
        return w if isinstance(w, SerialSession) else None

    def _apply_remembered_state(self, s: SerialSession, r: dict) -> None:
        port = r.get("port")
        if port:
            idx = s.port_combo.findData(port)
            if idx >= 0:
                s.port_combo.setCurrentIndex(idx)
        baud = r.get("baud")
        if baud:
            s.baud_combo.setCurrentText(str(baud))
        if r.get("filter_keywords"):
            s.keyword_edit.setText(r["filter_keywords"])
        mode = r.get("filter_mode")
        if mode:
            idx = s.mode_combo.findData(mode)
            if idx >= 0:
                s.mode_combo.setCurrentIndex(idx)
        s.case_check.setChecked(bool(r.get("filter_case")))
        fs = r.get("font_size")
        if isinstance(fs, int) and fs > 0:
            f = s.log_text.font()
            f.setPointSize(fs)
            s.log_text.setFont(f)
            s.matched_text.setFont(f)
        if r.get("filter_enabled"):
            s._enable_filter()

    def _add_session(self) -> None:
        s = SerialSession(self, len(self._sessions))
        self._sessions.append(s)
        if self._bg_enabled and self._bg_image:
            self._set_session_transparent(s, True)
        idx = self.session_tabs.addTab(s, s.title())
        self.session_tabs.setCurrentIndex(idx)
        self.plot_window.set_sessions(self._sessions)
        self._sync_menu_state()

    def _close_session(self, idx: int) -> None:
        if self.session_tabs.count() <= 1:
            QMessageBox.information(self, "串口", "至少保留一个串口标签页")
            return
        s = self.session_tabs.widget(idx)
        if not isinstance(s, SerialSession):
            return
        s.shutdown()
        self.session_tabs.removeTab(idx)
        self._sessions.remove(s)
        s.deleteLater()
        for i, sess in enumerate(self._sessions):
            sess.index = i
            self.session_tabs.setTabText(i, sess.title())
        self.plot_window.set_sessions(self._sessions)
        self._sync_menu_state()

    def update_session_title(self, session: SerialSession) -> None:
        if session in self._sessions:
            idx = self._sessions.index(session)
            self.session_tabs.setTabText(idx, session.title())
        self.plot_window.set_sessions(self._sessions)

    def _on_tab_changed(self, _idx: int) -> None:
        self._sync_menu_state()

    def _sync_menu_state(self) -> None:
        s = self.active_session()
        self.params_action.setChecked(bool(s and not s.serial_params_panel.isHidden()))
        self.auto_reply_action.setChecked(bool(s and not s.auto_reply_panel.isHidden()))

    def _toggle_active_params(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            s.serial_params_panel.setVisible(checked)

    def _toggle_active_auto_reply(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            s.auto_reply_panel.setVisible(checked)

    # ---------- 定时循环发送（全局，发给当前标签页） ----------
    def _timer_send_tick(self) -> None:
        s = self.active_session()
        if s is None or not s.serial.is_connected:
            return
        checked = [i for i, c in enumerate(self._commands) if c.get("cycle") and c.get("content")]
        if not checked:
            return
        idx = checked[self._cycle_idx % len(checked)]
        self._cycle_idx += 1
        self._send_command(idx)

    def _set_cycle_enabled(self, enabled: bool) -> None:
        self._cycle_enabled = enabled
        if enabled:
            self._cycle_idx = 0
            self._timer_send.start(self._cycle_interval)
        else:
            self._timer_send.stop()

    def _set_cycle_interval(self, ms: int) -> None:
        self._cycle_interval = ms
        if self._cycle_enabled:
            self._timer_send.start(ms)

    def _set_command_cycle(self, idx: int, checked: bool) -> None:
        if 0 <= idx < len(self._commands):
            self._commands[idx]["cycle"] = checked
            self._save_config()

    def _open_cycle_dialog(self) -> None:
        if self._cycle_dialog is None:
            self._cycle_dialog = CycleDialog(self)
        self._cycle_dialog._refresh()
        self._cycle_dialog.show()
        self._cycle_dialog.raise_()

    # ---- 命令按钮 ----
    def _rebuild_command_tabs(self) -> None:
        self.command_tabs.clear()
        for p, pname in enumerate(self._pages):
            w = QWidget()
            grid = QGridLayout(w)
            grid.setContentsMargins(4, 4, 4, 4)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(6)
            k = 0
            for idx, cmd in enumerate(self._commands):
                if cmd.get("page") != p:
                    continue
                btn = CommandButton(
                    cmd.get("name") or f"命令{idx + 1}",
                    lambda _=False, i=idx: self._send_command(i),
                    lambda _=False, i=idx: self._edit_command(i),
                    lambda _=False, i=idx: self._delete_command(i),
                )
                btn.setFixedSize(120, 34)
                btn.setToolTip((cmd.get("name") or "") + "\n" + (cmd.get("content") or ""))
                r, c = divmod(k, 4)
                grid.addWidget(btn, r, c, Qt.AlignLeft | Qt.AlignTop)
                k += 1
            self.command_tabs.addTab(w, pname)

    def _commands_changed(self) -> None:
        self._rebuild_command_tabs()
        if self._cycle_dialog is not None:
            self._cycle_dialog._refresh()
        self._save_config()

    def _add_page(self, name: str | None = None) -> int:
        if name is None:
            name = f"第{len(self._pages) + 1}页"
        self._pages.append(name)
        self._commands_changed()
        return len(self._pages) - 1

    def _rename_page(self, idx: int | None = None) -> None:
        if idx is None:
            idx = self.command_tabs.currentIndex()
        if idx < 0 or idx >= len(self._pages):
            return
        text, ok = QInputDialog.getText(self, "重命名页", "页名称：", text=self._pages[idx])
        if ok and text.strip():
            self._pages[idx] = text.strip()
            self._commands_changed()

    def _delete_page(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._pages):
            return
        if len(self._pages) <= 1:
            self._active_sys("至少保留一个页")
            return
        count = sum(1 for c in self._commands if c.get("page") == idx)
        msg = f"确定删除页「{self._pages[idx]}」吗？"
        if count:
            msg += f"\n该页有 {count} 条命令，将一并删除。"
        if QMessageBox.question(self, "删除页", msg) != QMessageBox.Yes:
            return
        del self._pages[idx]
        self._commands = [c for c in self._commands if c.get("page") != idx]
        for c in self._commands:
            if c.get("page", 0) > idx:
                c["page"] -= 1
        self._commands_changed()

    def _show_tab_menu(self, pos) -> None:
        idx = self.command_tabs.tabBar().tabAt(pos)
        menu = QMenu(self)
        menu.addAction("新增页", lambda: self._add_page())
        if idx >= 0:
            menu.addAction("重命名页", lambda: self._rename_page(idx))
            menu.addAction("删除该页", lambda: self._delete_page(idx))
        menu.exec(self.command_tabs.tabBar().mapToGlobal(pos))

    def _add_command(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("添加命令")
        form = QFormLayout(dlg)
        name_edit = QLineEdit()
        content_edit = QPlainTextEdit()
        content_edit.setFixedHeight(80)
        page_combo = QComboBox()
        first_free = -1
        for i, pname in enumerate(self._pages):
            cnt = sum(1 for c in self._commands if c.get("page") == i)
            page_combo.addItem(f"{pname}（{cnt}/8）", i)
            if cnt < 8 and first_free < 0:
                first_free = i
        page_combo.addItem("（新建页）", -1)
        if first_free >= 0:
            page_combo.setCurrentIndex(first_free)
        else:
            page_combo.setCurrentIndex(page_combo.count() - 1)
        form.addRow("命令名称", name_edit)
        form.addRow("命令内容", content_edit)
        form.addRow("所属页", page_combo)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        name = name_edit.text().strip()
        content = content_edit.toPlainText()
        if not name and not content:
            return
        page = page_combo.currentData()
        if page == -1:
            page = len(self._pages)
            self._pages.append(f"第{page + 1}页")
        else:
            cnt = sum(1 for c in self._commands if c.get("page") == page)
            if cnt >= 8:
                QMessageBox.warning(self, "添加命令", "该页已满（每页最多 8 个），请选择其它页或新建页")
                return
        self._commands.append({
            "name": name or f"命令{len(self._commands) + 1}",
            "content": content,
            "cycle": False,
            "page": page,
        })
        self._commands_changed()

    def _edit_command(self, idx: int) -> None:
        cmd = self._commands[idx]
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑命令")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(cmd.get("name") or "")
        content_edit = QPlainTextEdit()
        content_edit.setPlainText(cmd.get("content") or "")
        content_edit.setFixedHeight(80)
        form.addRow("命令名称", name_edit)
        form.addRow("命令内容", content_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        cmd["name"] = name_edit.text().strip() or cmd.get("name")
        cmd["content"] = content_edit.toPlainText()
        self._commands_changed()

    def _delete_command(self, idx: int) -> None:
        cmd = self._commands[idx]
        if QMessageBox.question(self, "删除命令",
                                f"确定删除命令「{cmd.get('name')}」吗？") != QMessageBox.Yes:
            return
        del self._commands[idx]
        self._commands_changed()

    def _send_command(self, idx: int) -> None:
        content = self._commands[idx].get("content") or ""
        if not content:
            self._active_sys("命令内容为空")
            return
        s = self.active_session()
        if s is None:
            return
        s.send_command_content(content)

    # ---------- 全局反馈 ----------
    def _active_sys(self, text: str) -> None:
        s = self.active_session()
        if s:
            s._sys(text)

    # ---------- 绘图 ----------
    def _toggle_plot_window(self, checked: bool) -> None:
        self.plot_window.setVisible(checked)

    # ---------- 字体 ----------
    def _zoom_log(self, step: int) -> None:
        s = self.active_session()
        if s:
            if step > 0:
                s.log_text.zoomIn(step)
            else:
                s.log_text.zoomOut(-step)
            self._save_config()

    def _reset_font(self) -> None:
        s = self.active_session()
        if s:
            f = s.log_text.font()
            f.setPointSize(10)
            s.log_text.setFont(f)
            s.matched_text.setFont(f)
            self._save_config()

    # ---------- 保存 / 目录 ----------
    def _log_dir(self) -> Path:
        if self._log_dir_override:
            return Path(self._log_dir_override)
        return _data_dir() / "Logs"

    def _choose_log_dir(self) -> None:
        start = self._log_dir()
        start.mkdir(parents=True, exist_ok=True)
        path = QFileDialog.getExistingDirectory(self, "选择日志保存目录", str(start))
        if path:
            self._log_dir_override = path
            self._active_sys(f"日志保存目录已设为: {path}")

    def _open_log_dir(self) -> None:
        path = self._log_dir()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---------- 配置 ----------
    def _config_path(self) -> Path:
        return _data_dir() / "serial_tool_config.json"

    def _load_config(self) -> None:
        path = self._config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(data.get("theme"), str) and data["theme"] in ("black", "eye", "day"):
            self._theme = data["theme"]
        if isinstance(data.get("auto_record"), bool):
            self._auto_record = data["auto_record"]
        if isinstance(data.get("shard_mb"), int):
            self._shard_mb = max(1, data["shard_mb"])
        if isinstance(data.get("log_retention"), str) and data["log_retention"] in _LOG_RETENTION_KEYS:
            self._log_retention = data["log_retention"]
        if isinstance(data.get("last_update_check"), str):
            self._last_update_check = data["last_update_check"]
        if isinstance(data.get("log_dir"), str) and data["log_dir"]:
            self._log_dir_override = data["log_dir"]
        if isinstance(data.get("bg_dir"), str) and data["bg_dir"]:
            self._bg_dir = data["bg_dir"]
        if isinstance(data.get("bg_image"), str):
            self._bg_image = data["bg_image"]
        if isinstance(data.get("bg_blur"), int):
            self._bg_blur = max(0, min(50, data["bg_blur"]))
        if isinstance(data.get("bg_enabled"), bool):
            self._bg_enabled = data["bg_enabled"]
        sessions = data.get("sessions")
        if isinstance(sessions, list) and sessions:
            self._remembered_sessions = [d for d in sessions if isinstance(d, dict)]
        else:
            # 兼容旧版单会话字段
            self._remembered_sessions = [{
                "port": data.get("port"),
                "baud": data.get("baud"),
                "filter_keywords": data.get("filter_keywords", ""),
                "filter_mode": data.get("filter_mode", "highlight"),
                "filter_case": bool(data.get("filter_case")),
                "filter_enabled": bool(data.get("filter_enabled")),
                "font_size": data.get("font_size"),
            }]
        pages = data.get("pages")
        if isinstance(pages, list) and pages:
            self._pages = [str(p) for p in pages]
        cmds = data.get("commands")
        if isinstance(cmds, list):
            loaded = []
            for c in cmds:
                if isinstance(c, dict) and (c.get("name") or c.get("content")):
                    page = c.get("page")
                    if not isinstance(page, int) or page < 0 or page >= len(self._pages):
                        page = 0
                    loaded.append({
                        "name": str(c.get("name") or ""),
                        "content": str(c.get("content") or ""),
                        "cycle": bool(c.get("cycle")),
                        "page": page,
                    })
            self._commands = loaded

    def _config_data(self) -> dict:
        sessions = []
        for s in self._sessions:
            fs = s.log_text.font().pointSize()
            sessions.append({
                "port": s.port_combo.currentData(),
                "baud": s.baud_combo.currentText(),
                "filter_keywords": s.keyword_edit.text(),
                "filter_mode": s.mode_combo.currentData(),
                "filter_case": s.case_check.isChecked(),
                "filter_enabled": s._filter_enabled,
                "font_size": fs if fs > 0 else 10,
            })
        return {
            "theme": self._theme,
            "pages": self._pages,
            "commands": self._commands,
            "auto_record": self._auto_record,
            "shard_mb": self._shard_mb,
            "log_retention": self._log_retention,
            "last_update_check": self._last_update_check,
            "log_dir": self._log_dir_override,
            "bg_dir": self._bg_dir,
            "bg_image": self._bg_image,
            "bg_blur": self._bg_blur,
            "bg_enabled": self._bg_enabled,
            "sessions": sessions,
        }

    def _save_config(self) -> None:
        try:
            self._config_path().write_text(
                json.dumps(self._config_data(), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _set_auto_record(self, enabled: bool) -> None:
        self._auto_record = enabled
        self._save_config()

    def _set_shard_size(self) -> None:
        value, ok = QInputDialog.getInt(self, "日志分片大小", "每个日志文件最大大小（MB）：",
                                        self._shard_mb, 1, 1024)
        if ok:
            self._shard_mb = value
            self._save_config()
            self._active_sys(f"日志分片大小已设为 {value} MB")

    # ---------- 日志保留 ----------
    def _set_log_retention(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("日志保留策略")
        form = QFormLayout(dlg)
        combo = QComboBox()
        for label, key, _days in _LOG_RETENTION_OPTIONS:
            combo.addItem(label, key)
        idx = combo.findData(self._log_retention)
        combo.setCurrentIndex(idx if idx >= 0 else 1)
        form.addRow("保留时长", combo)
        tip = QLabel("到期自动清理旧日志文件（仅 .txt 日志）。「无限制」表示不清理。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888888;")
        form.addRow("", tip)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        self._log_retention = combo.currentData()
        self._save_config()
        self._clean_old_logs()

    def _clean_old_logs(self) -> None:
        days = _LOG_RETENTION_DAYS.get(self._log_retention, 0)
        if not days:
            return
        log_dir = self._log_dir()
        if not log_dir.is_dir():
            return
        cutoff = time.time() - days * 86400
        try:
            for f in log_dir.glob("*.txt"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    # ---------- 自动更新 ----------
    def _check_update(self) -> None:
        today = datetime.date.today().isoformat()
        if self._last_update_check == today:
            return
        self._last_update_check = today
        self._save_config()
        threading.Thread(target=self._do_check_update, daemon=True).start()

    def _check_update_manual(self) -> None:
        self._active_sys("正在检查更新...")
        threading.Thread(target=self._do_check_update, kwargs={"manual": True}, daemon=True).start()

    def _do_check_update(self, manual: bool = False) -> None:
        try:
            import urllib.request
            req = urllib.request.Request(_UPDATE_API, headers={"User-Agent": _APP_NAME})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            tag = str(data.get("tag_name") or data.get("name") or "")
            latest = _parse_version(tag)
            current = _parse_version(_APP_VERSION)
            if latest and current and latest > current:
                html_url = str(data.get("html_url") or _UPDATE_PAGE)
                self._update_result.emit("update", tag, html_url)
            elif manual:
                self._update_result.emit("none", "", "")
        except Exception:
            if manual:
                self._update_result.emit("error", "", "")

    def _on_update_result(self, status: str, tag: str, url: str) -> None:
        if status == "update":
            self._prompt_update(tag, url)
        elif status == "none":
            QMessageBox.information(self, "检查更新", f"当前已是最新版本（{_APP_VERSION}）。")
        else:
            QMessageBox.warning(self, "检查更新", "检查更新失败，请稍后重试或检查网络。")

    def _prompt_update(self, tag: str, url: str) -> None:
        ret = QMessageBox.question(
            self, "发现新版本",
            f"发现新版本 {tag}（当前 {_APP_VERSION}）。\n是否前往 Gitee 下载？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if ret == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(url))

    # ---------- 文件菜单辅助 ----------
    def _save_log_active(self) -> None:
        s = self.active_session()
        if s is not None:
            s.save_log()

    def _open_docs(self) -> None:
        QDesktopServices.openUrl(QUrl(_APP_URL))

    # ---------- 配置导出 / 导入 ----------
    def _export_config(self) -> None:
        default = str(Path.home() / "ohmyport_config.json")
        path, _ = QFileDialog.getSaveFileName(self, "导出配置", default, "JSON 文件 (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self._config_data(), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self._active_sys(f"配置已导出: {path}")

    def _import_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", f"无法读取配置文件：\n{exc}")
            return
        if not isinstance(data, dict):
            QMessageBox.warning(self, "导入失败", "配置文件格式无效")
            return
        # 全局设置
        if isinstance(data.get("theme"), str) and data["theme"] in ("black", "eye", "day"):
            self._theme = data["theme"]
            self._apply_theme_qss()
        if isinstance(data.get("auto_record"), bool):
            self._auto_record = data["auto_record"]
            self.auto_record_action.setChecked(self._auto_record)
        if isinstance(data.get("shard_mb"), int):
            self._shard_mb = max(1, data["shard_mb"])
        if isinstance(data.get("log_retention"), str) and data["log_retention"] in _LOG_RETENTION_KEYS:
            self._log_retention = data["log_retention"]
        if isinstance(data.get("log_dir"), str):
            self._log_dir_override = data["log_dir"] or None
        if isinstance(data.get("bg_image"), str):
            self._bg_image = data["bg_image"]
        if isinstance(data.get("bg_blur"), int):
            self._bg_blur = max(0, min(50, data["bg_blur"]))
        if isinstance(data.get("bg_enabled"), bool):
            self._bg_enabled = data["bg_enabled"]
        self._apply_background()
        # 命令页 / 命令
        pages = data.get("pages")
        if isinstance(pages, list) and pages:
            self._pages = [str(p) for p in pages]
        cmds = data.get("commands")
        if isinstance(cmds, list):
            loaded = []
            for c in cmds:
                if isinstance(c, dict) and (c.get("name") or c.get("content")):
                    page = c.get("page")
                    if not isinstance(page, int) or page < 0 or page >= len(self._pages):
                        page = 0
                    loaded.append({
                        "name": str(c.get("name") or ""),
                        "content": str(c.get("content") or ""),
                        "cycle": bool(c.get("cycle")),
                        "page": page,
                    })
            self._commands = loaded
        self._rebuild_command_tabs()
        # 会话
        sessions = data.get("sessions")
        if isinstance(sessions, list) and sessions:
            self._remembered_sessions = [d for d in sessions if isinstance(d, dict)]
            target = max(1, len(self._remembered_sessions))
            while len(self._sessions) < target:
                self._add_session()
            while len(self._sessions) > target:
                self._close_session(len(self._sessions) - 1)
            for i, s in enumerate(self._sessions):
                if i < len(self._remembered_sessions):
                    self._apply_remembered_state(s, self._remembered_sessions[i])
        self._save_config()
        self._active_sys(f"配置已导入: {path}")

    # ---------- 主题 ----------
    def _set_theme(self, theme: str) -> None:
        self._theme = theme
        self._apply_theme_qss()
        self._save_config()

    def _apply_theme_qss(self) -> None:
        qdarktheme.setup_theme(**_THEME_CFG.get(self._theme, _THEME_CFG["day"]))

    # ---------- 背景皮肤 ----------
    def _refresh_bg_combo(self, combo: QComboBox) -> None:
        combo.clear()
        combo.addItem("无", "")
        d = Path(self._bg_dir)
        if d.is_dir():
            exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix.lower() in exts:
                    combo.addItem(f.name, f.name)
        if self._bg_image:
            idx = combo.findData(self._bg_image)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _open_background_dialog(self) -> None:
        bg_dir = Path(self._bg_dir)
        bg_dir.mkdir(parents=True, exist_ok=True)
        dlg = QDialog(self)
        dlg.setWindowTitle("背景皮肤")
        form = QFormLayout(dlg)

        combo = QComboBox()
        self._refresh_bg_combo(combo)

        # 背景图存放提示行
        hint_row = QWidget()
        hl = QHBoxLayout(hint_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(f"背景图存放目录：{bg_dir}")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888;")
        hl.addWidget(hint, 1)
        hl.addWidget(_make_btn("打开目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(bg_dir)))))
        hl.addWidget(_make_btn("刷新", lambda: self._refresh_bg_combo(combo)))
        form.addRow("", hint_row)

        form.addRow("背景图片", combo)
        blur_slider = QSlider(Qt.Horizontal)
        blur_slider.setRange(0, 50)
        blur_slider.setValue(self._bg_blur)
        form.addRow("模糊强度", blur_slider)
        enable_check = QCheckBox("启用背景")
        enable_check.setChecked(self._bg_enabled)
        form.addRow("", enable_check)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        self._bg_image = combo.currentData() or ""
        self._bg_blur = blur_slider.value()
        self._bg_enabled = enable_check.isChecked()
        self._apply_background()
        self._save_config()

    def _set_session_transparent(self, s, flag: bool) -> None:
        s.setAttribute(Qt.WA_TranslucentBackground, flag)
        for panel in (s.serial_params_panel, s.find_bar, s.matched_panel):
            panel.setAttribute(Qt.WA_TranslucentBackground, flag)
        s.log_text.set_transparent(flag)
        s.matched_text.set_transparent(flag)

    def _set_containers_transparent(self, flag: bool) -> None:
        for s in self._sessions:
            self._set_session_transparent(s, flag)
        self.send_assist_panel.setAttribute(Qt.WA_TranslucentBackground, flag)
        for tw in (self.session_tabs, self.command_tabs):
            tw.setAttribute(Qt.WA_TranslucentBackground, flag)
            for pane in tw.findChildren(QStackedWidget):
                pane.setAttribute(Qt.WA_TranslucentBackground, flag)

    def _apply_background(self) -> None:
        central = self.centralWidget()

        def _clear():
            central.set_bg_pixmap(None)
            self._set_containers_transparent(False)

        if not self._bg_enabled or not self._bg_image:
            _clear()
            return
        src = Path(self._bg_dir) / self._bg_image
        if not src.exists():
            _clear()
            return
        cache_dir = _data_dir() / "bg_cache"
        try:
            st = src.stat()
            key = hashlib.md5(
                f"{src}|{st.st_mtime}|{st.st_size}|{self._bg_blur}".encode("utf-8")
            ).hexdigest()[:12]
        except OSError:
            _clear()
            return
        bg_path = cache_dir / f"bg_{key}.png"
        if not bg_path.exists():
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                img = Image.open(src).convert("RGB")
                img.thumbnail((1920, 1080), Image.LANCZOS)
                img.filter(ImageFilter.GaussianBlur(max(1, self._bg_blur * 3))).save(bg_path)
            except Exception:
                _clear()
                return
        central.set_bg_pixmap(QPixmap(bg_path.as_posix()))
        self._set_containers_transparent(True)

    def _show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("关于")
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"<h3>{_APP_NAME} v{_APP_VERSION}</h3>"
            f"<p>作者：{_APP_AUTHOR}<br>发布日期：{_APP_DATE}</p>"
            f"<p>仓库：<a href='{_APP_URL}'>{_APP_URL}</a></p>"
            "<p>多串口并行调试工具：数值绘图、日志自动保存、多关键词过滤、"
            "自动应答、SSCOM 式命令发送。</p>",
        )
        for label in box.findChildren(QLabel):
            label.setOpenExternalLinks(True)
        box.exec()

    def closeEvent(self, event) -> None:
        self._save_config()
        self._timer_send.stop()
        for s in self._sessions:
            s.shutdown()
        super().closeEvent(event)


def _resource_path(filename: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / filename
    return Path(__file__).resolve().parent / filename


def _install_excepthook() -> None:
    """把未捕获异常写到 error.log（exe 同级，不可写则落到数据目录）。"""
    import traceback

    def hook(exc_type, exc_value, exc_tb) -> None:
        log = _data_dir() / "error.log"
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
                f.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        except Exception:
            pass
        try:
            QMessageBox.critical(
                None, f"{_APP_NAME} 程序异常",
                f"发生未捕获异常，已记录到：\n{log}\n\n请把该文件反馈给开发者。",
            )
        except Exception:
            pass

    sys.excepthook = hook


def main() -> None:
    app = QApplication(sys.argv)
    _install_excepthook()
    icon = QIcon(str(_resource_path("my-icon.ico")))
    app.setWindowIcon(icon)
    win = SerialToolWindow()
    win.setWindowIcon(icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
