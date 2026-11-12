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

import qdarktheme
from PIL import Image, ImageFilter

try:  # darkdetect 随 qdarktheme 安装；缺失时"跟随系统"回退到手动判断一次
    import darkdetect
except Exception:  # pragma: no cover - 平台差异
    darkdetect = None

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation,
                           QSize, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFont,
                           QFontDatabase, QIcon, QKeySequence, QPainter, QPalette,
                           QPixmap, QShortcut, QTextCharFormat, QTextCursor, QTextDocument)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSlider, QSpinBox, QSplitter, QStackedWidget, QSystemTrayIcon, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QToolBar, QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from common import (
    _APP_AUTHOR, _APP_DATE, _APP_NAME, _APP_URL, _APP_VERSION,
    _BAUDS, _ENCODINGS, _NEWLINES, _HL_INTERVAL, _HOTPLUG_MS, _FLUSH_MS,
    _LOG_RETENTION_KEYS, _LOG_RETENTION_OPTIONS, _MAX_LINES,
    _THEME_CFG, _UPDATE_API, _UPDATE_PAGE,
    _data_dir, _extract_numbers, _fmt_bytes, _now, _parse_version,
    LogFilter,
)
from serial_worker import SerialMonitor
from plot_widget import PlotRule, PlotWindow, _fmt_val
from log_manager import LogManager
from frame_parser import FrameParser
from icons import set_action_icon

# 日志配色（随主题）：时间戳 / 发送 / 系统 / 高亮
_LOG_THEME_COLORS = {
    "black": {
        "ts": "#8a9199", "tx": "#4fc3f7", "sys": "#8a9199",
        "hl_bg": "#6d5c00", "hl_fg": "#ffffff",
        "search_bg": "#8a4d00", "search_bg_cur": "#a86100", "search_fg": "#ffffff",
        "muted": "#9aa0a6",
    },
    "day": {
        "ts": "#6b7280", "tx": "#0e7490", "sys": "#6b7280",
        "hl_bg": "#fff59d", "hl_fg": "#000000",
        "search_bg": "#ffb74d", "search_bg_cur": "#ff9800", "search_fg": "#000000",
        "muted": "#6b7280",
    },
    "eye": {
        "ts": "#5b6b5e", "tx": "#0e7490", "sys": "#5b6b5e",
        "hl_bg": "#fff59d", "hl_fg": "#000000",
        "search_bg": "#ffb74d", "search_bg_cur": "#ff9800", "search_fg": "#000000",
        "muted": "#5b6b5e",
    },
}


# 已连接标签页文字颜色（绿点）
_CONNECTED_COLOR = "#4caf50"

# ============================================================
# OhmyPort UI 精修覆盖层：追加在 qdarktheme 主题样式之后。
# 只做尺寸 / 排版细节微调（圆角、内边距、最小高度、表头/菜单/提示行距），
# 不写任何硬编码颜色 —— 颜色全部沿用 qdarktheme 主题（黑/护眼/白天）自身定义，
# 因此三套主题下自动协调，也不会破坏背景皮肤 / 日志透明机制。
# 注意：特异性与 qdarktheme 基础规则相同，本文件在其后生效即为覆盖意图；
# 保留 qdarktheme 的 :hover/:pressed/:focus 状态规则不受影响。
# ============================================================
_UI_QSS = """
QPushButton {
    padding: 3px 14px;
    border-radius: 6px;
}
CommandButton {
    padding: 6px 12px;
    border-radius: 8px;
    font-weight: 600;
}
QToolButton {
    padding: 3px 8px;
    border-radius: 6px;
}
QComboBox {
    min-height: 24px;
    padding: 1px 10px 1px 8px;
    border-radius: 6px;
}
QComboBox::drop-down {
    width: 20px;
}
QLineEdit, QAbstractSpinBox {
    min-height: 22px;
    padding: 2px 8px;
    border-radius: 6px;
}
QTabBar::tab {
    padding: 5px 10px;
    min-width: 36px;
}
QMenu::item {
    padding: 5px 20px;
}
QToolTip {
    padding: 4px 9px;
}
QHeaderView::section {
    padding: 4px 8px;
    font-weight: 600;
}
QTableView::item, QTreeView::item, QListWidget::item {
    padding: 4px 6px;
}
"""

# ============================================================
# 动作按钮角色配色（随主题）：
#   role="primary"  —— 填充强调色（发送 / 打开串口）
#   role="danger"   —— 红色警示填充（关闭串口 / 停止记录）
#   role="outline"  —— 强调色描边（暂停中「继续」等激活态）
# 颜色取自各主题 qdarktheme 主色的语义近似值，随主题切换自动重生成。
# ============================================================
_ROLE_PALETTE = {
    "black": {
        "accent": "#8ab4f7", "accent_fg": "#202124",
        "danger": "#e57373", "danger_fg": "#202124",
    },
    "day": {
        "accent": "#1a73e8", "accent_fg": "#ffffff",
        "danger": "#d93025", "danger_fg": "#ffffff",
    },
    "eye": {
        "accent": "#2e7d32", "accent_fg": "#ffffff",
        "danger": "#b3261e", "danger_fg": "#ffffff",
    },
}


def _rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.3f})"


def _role_qss(theme: str) -> str:
    """生成动作按钮角色样式（追加在 _UI_QSS 之后，主题相关）。"""
    pal = _ROLE_PALETTE.get(theme, _ROLE_PALETTE["day"])
    acc, acc_fg = pal["accent"], pal["accent_fg"]
    dng, dng_fg = pal["danger"], pal["danger_fg"]
    acc_hover = QColor(acc).lighter(105).name()
    acc_press = QColor(acc).darker(112).name()
    dng_hover = QColor(dng).lighter(108).name()
    dng_press = QColor(dng).darker(112).name()
    # 透明占位边框保证与普通按钮同高、状态切换不抖动
    return f"""
QPushButton[role="primary"] {{
    background-color: {acc};
    color: {acc_fg};
    border: 1px solid transparent;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background-color: {acc_hover}; }}
QPushButton[role="primary"]:pressed {{ background-color: {acc_press}; }}
QPushButton[role="danger"] {{
    background-color: {dng};
    color: {dng_fg};
    border: 1px solid transparent;
    font-weight: 600;
}}
QPushButton[role="danger"]:hover {{ background-color: {dng_hover}; }}
QPushButton[role="danger"]:pressed {{ background-color: {dng_press}; }}
QPushButton[role="outline"] {{
    background-color: transparent;
    color: {acc};
    border: 1px solid {acc};
    font-weight: 600;
}}
QPushButton[role="outline"]:hover {{ background-color: {_rgba(acc, 0.12)}; }}
QPushButton[role="outline"]:pressed {{ background-color: {_rgba(acc, 0.24)}; }}
QPushButton[role="dangerText"] {{
    color: {dng};
    background-color: transparent;
    border: 1px solid {dng};
    font-weight: 600;
}}
QPushButton[role="dangerText"]:hover {{ background-color: {_rgba(dng, 0.10)}; }}
QPushButton[role="dangerText"]:pressed {{ background-color: {_rgba(dng, 0.22)}; }}
QDialogButtonBox QPushButton, QMessageBox QPushButton {{
    min-width: 84px;
}}
"""


def _set_role(btn: QPushButton, role: str) -> None:
    """设置按钮角色并强制 repolish，使属性选择器样式立即生效。"""
    btn.setProperty("role", role)
    st = btn.style()
    st.unpolish(btn)
    st.polish(btn)
    btn.update()


def _confirm_danger(parent, title: str, text: str, ok_text: str = "删除") -> bool:
    """统一"破坏性操作"确认框：红色确认按钮 + 默认取消，降低误操作风险。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(text)
    ok_btn = box.addButton(ok_text, QMessageBox.ButtonRole.DestructiveRole)
    cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    _set_role(ok_btn, "dangerText")
    box.setDefaultButton(cancel_btn)
    box.exec()
    return box.clickedButton() is ok_btn


# 主窗口 / 会话页统一边距与间距（略增呼吸感，但保持工具类密度）
_LAYOUT_MARGIN = (8, 6, 8, 6)
_LAYOUT_SPACING = 5
_MAX_H = 16777215  # Qt 布局允许的最大高度（对齐 QWIDGETSIZE_MAX）


def _start_fold(panel: QWidget, expand: bool) -> None:
    """以高度动画展开(true)/收起(false)菜单型面板；旧动画自动接管，避免竞态。"""
    prev = getattr(panel, "_fold_anim", None)
    anim = QPropertyAnimation(panel, b"maximumHeight", panel)
    panel._fold_anim = anim  # 先替换引用，使旧动画的 finished 回调失效
    if prev is not None:
        try:
            prev.stop()
        except Exception:
            pass
    if expand:
        panel.setMaximumHeight(0)
        panel.setVisible(True)
        panel.updateGeometry()
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(0)
        anim.setEndValue(max(1, panel.sizeHint().height()))
    else:
        anim.setDuration(140)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.setStartValue(max(1, panel.height()))
        anim.setEndValue(0)

    def _done():
        if getattr(panel, "_fold_anim", None) is anim:
            if expand:
                panel.setMaximumHeight(_MAX_H)
            else:
                panel.setVisible(False)
                panel.setMaximumHeight(_MAX_H)
            panel._fold_anim = None

    anim.finished.connect(_done)
    anim.start()

# 日志等宽字体选项
_FONT_OPTIONS = [
    ("系统默认等宽", "default"),
    ("Consolas", "Consolas"),
    ("Cascadia Code", "Cascadia Code"),
    ("JetBrains Mono", "JetBrains Mono"),
]

# 日志默认字号（用户可再放大/缩小/在配置中记住）
_DEFAULT_FONT_SIZE = 11

# 高数据量渲染优化：按颜色缓存 QTextCharFormat，避免每段重复创建 QColor/格式对象
_char_format_cache: dict[str, QTextCharFormat] = {}
_default_char_format = QTextCharFormat()


def _char_format(color: str | None) -> QTextCharFormat:
    """返回（缓存的）字符格式；color 为 hex 字符串，None 表示默认前景色。"""
    if color is None:
        return _default_char_format
    fmt = _char_format_cache.get(color)
    if fmt is None:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        _char_format_cache[color] = fmt
    return fmt


_hl_format_cache: dict[tuple[str, str], QTextCharFormat] = {}


def _highlight_format(bg: str, fg: str) -> QTextCharFormat:
    """返回（缓存的）关键词高亮格式（背景+前景）。"""
    key = (bg, fg)
    fmt = _hl_format_cache.get(key)
    if fmt is None:
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(bg))
        fmt.setForeground(QColor(fg))
        _hl_format_cache[key] = fmt
    return fmt


def _make_btn(text: str, slot) -> QPushButton:
    btn = QPushButton(text)
    btn.clicked.connect(slot)
    return btn


def _disable_combo_autocomplete(combo: QComboBox) -> None:
    """关闭可编辑 QComboBox 的自动补全（下拉历史仍可用）。

    Qt 会给可编辑下拉框自动装一个大小写不敏感的 QCompleter（内联补全模式）：
    输入 "P" 而历史里恰好有 "p" 时，回车会"接受补全"把输入替换成 "p"，
    发送框/波特率框这类以输入内容为准的地方会因此发错数据，必须关掉。
    """
    edit = combo.lineEdit()
    if edit is not None:
        edit.setCompleter(None)


def _load_pages_commands(data: dict, current_pages: list[str]) -> tuple[list[str], list[dict]]:
    """从配置 dict 解析发送辅助的命令页与命令（导出/导入/启动共用，纯逻辑）。"""
    pages = list(current_pages)
    if isinstance(data.get("pages"), list) and data["pages"]:
        pages = [str(p) for p in data["pages"]]
    commands: list[dict] = []
    cmds = data.get("commands")
    if isinstance(cmds, list):
        for c in cmds:
            if isinstance(c, dict) and (c.get("name") or c.get("content")):
                page = c.get("page")
                if not isinstance(page, int) or page < 0 or page >= len(pages):
                    page = 0  # 越界/非法页回退到第 1 页
                commands.append({
                    "name": str(c.get("name") or ""),
                    "content": str(c.get("content") or ""),
                    "cycle": bool(c.get("cycle")),
                    "page": page,
                })
    return pages, commands


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


class _LogWheelFilter(QObject):
    """日志区滚轮：向上滚动（远离底部）时通知会话进入固定模式。"""

    def __init__(self, session):
        super().__init__()
        self._session = session

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Wheel:
            if event.angleDelta().y() > 0:
                self._session._on_wheel_up()
        return False


class _BaudMenuFilter(QObject):
    """波特率输入框右键：弹出删除自定义波特率的菜单。"""

    def __init__(self, session):
        super().__init__()
        self._session = session

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.ContextMenu:
            self._session._show_baud_menu(event.globalPos())
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
        self._logmgr = LogManager()
        self._stat_text = "RX: 0 B   TX: 0 B"
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
        self._hl_regex = None
        self._hl_regex_key = None
        self._connected_baud: str | None = None
        self._custom_bauds: list[str] = []
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
            return f"● {self.port_combo.currentData() or f'串口{self.index + 1}'}"
        return f"串口{self.index + 1}"

    def shutdown(self) -> None:
        self._flush_timer.stop()
        self._hotplug_timer.stop()
        self._logmgr.close()
        self.serial.disconnect()

    # ---------- UI 构建 ----------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*_LAYOUT_MARGIN)
        layout.setSpacing(_LAYOUT_SPACING)

        # 端口连接配置（可折叠面板；「打开/关闭串口」按钮移至日志操作行常驻）
        self.conn_panel = QWidget()
        conn = QHBoxLayout(self.conn_panel)
        conn.setContentsMargins(0, 0, 0, 0)
        conn.addWidget(QLabel("端口"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(120)
        conn.addWidget(self.port_combo)
        refresh_btn = _make_btn("刷新", self.refresh_ports)
        refresh_btn.setToolTip("重新扫描可用串口")
        conn.addWidget(refresh_btn)
        conn.addWidget(QLabel("波特率"))
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(_BAUDS)
        _disable_combo_autocomplete(self.baud_combo)  # 防止自定义波特率被历史值补全改写
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setMinimumWidth(90)
        self.baud_combo.setToolTip("可直接输入自定义波特率（连接成功后加入下拉列表并记住，右键可删除）")
        self._baud_menu_filter = _BaudMenuFilter(self)
        self.baud_combo.lineEdit().installEventFilter(self._baud_menu_filter)
        conn.addWidget(self.baud_combo)
        conn.addStretch(1)
        layout.addWidget(self.conn_panel)

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
        self.dtr_check = QCheckBox("DTR")
        self.dtr_check.setChecked(True)
        self.dtr_check.toggled.connect(self.serial.set_dtr)
        sp.addWidget(self.dtr_check)
        self.rts_check = QCheckBox("RTS")
        self.rts_check.setChecked(True)
        self.rts_check.toggled.connect(self.serial.set_rts)
        sp.addWidget(self.rts_check)
        sp.addStretch(1)
        self.serial_params_panel.setVisible(False)
        layout.addWidget(self.serial_params_panel)

        # 关键词过滤（可折叠面板）
        self.filter_panel = QWidget()
        filt = QHBoxLayout(self.filter_panel)
        filt.setContentsMargins(0, 0, 0, 0)
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
        self.filter_panel.setVisible(False)
        layout.addWidget(self.filter_panel)

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
        self.log_text.setFont(self.window._make_log_font(_DEFAULT_FONT_SIZE))
        self.log_text.installEventFilter(self.window._wheel_filter)
        self.log_text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_text.customContextMenuRequested.connect(self._show_log_menu)
        self._log_wheel_filter = _LogWheelFilter(self)
        self.log_text.viewport().installEventFilter(self._log_wheel_filter)
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
        self.matched_text.setFont(self.window._make_log_font(_DEFAULT_FONT_SIZE))
        self.matched_text.installEventFilter(self.window._wheel_filter)
        mp.addWidget(self.matched_text)
        self.matched_panel.setVisible(False)
        layout.addWidget(self.matched_panel, 1)

        # 日志操作行（RX/TX 统计已上移至主窗口状态栏）
        bar = QHBoxLayout()
        self.connect_btn = _make_btn("打开串口", self.toggle_connection)
        self.connect_btn.setToolTip("打开 / 关闭当前串口")
        _set_role(self.connect_btn, "primary")
        bar.addWidget(self.connect_btn)
        self.pause_btn = _make_btn("暂停", self.toggle_pause)
        self.pause_btn.setToolTip("暂停刷新显示（后台仍持续接收、记录、缓冲）")
        bar.addWidget(self.pause_btn)
        clear_btn = _make_btn("清空", self.clear_log)
        clear_btn.setToolTip("清空显示与缓冲区（不影响已写入的日志文件）")
        bar.addWidget(clear_btn)
        self.fixed_check = QCheckBox("固定显示")
        self.fixed_check.setChecked(False)
        self.fixed_check.setToolTip("固定显示：日志持续追加但保持当前滚动位置（不自动跟随到底部），"
                                    "后台仍持续接收、记录、缓冲；向上滚动鼠标滚轮可快速进入")
        self.fixed_check.toggled.connect(self._on_fixed_toggle)
        bar.addWidget(self.fixed_check)
        self.record_btn = _make_btn("开始记录", self.toggle_record)
        self.record_btn.setToolTip("手动开始 / 停止日志记录")
        bar.addWidget(self.record_btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        # 消息发送（可折叠面板）
        self.send_panel = QWidget()
        send = QHBoxLayout(self.send_panel)
        send.setContentsMargins(0, 0, 0, 0)
        self.send_combo = QComboBox()
        self.send_combo.setEditable(True)
        self.send_combo.setInsertPolicy(QComboBox.NoInsert)
        _disable_combo_autocomplete(self.send_combo)  # 保证发送内容与输入完全一致
        self.send_combo.lineEdit().setPlaceholderText("发送内容（HEX 模式输入如 01 03 00 0A）")
        self.send_combo.lineEdit().returnPressed.connect(self.send_raw)
        send.addWidget(self.send_combo, 1)
        self.newline_combo = QComboBox()
        for label, v in _NEWLINES:
            self.newline_combo.addItem(label, v)
        send.addWidget(self.newline_combo)
        self.hex_send_check = QCheckBox("HEX发送")
        send.addWidget(self.hex_send_check)
        self.send_btn = _make_btn("发送", self.send_raw)
        self.send_btn.setToolTip("发送当前输入内容")
        _set_role(self.send_btn, "primary")
        send.addWidget(self.send_btn)
        self.send_panel.setVisible(False)
        layout.addWidget(self.send_panel)

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

        # 协议解析（隐藏面板）
        self.protocol_panel = QWidget()
        pf = QHBoxLayout(self.protocol_panel)
        pf.setContentsMargins(0, 4, 0, 0)
        self.protocol_enable = QCheckBox("启用协议解析")
        pf.addWidget(self.protocol_enable)
        pf.addWidget(QLabel("帧头(hex)"))
        self.protocol_header = QLineEdit()
        self.protocol_header.setPlaceholderText("如 AA 55")
        pf.addWidget(self.protocol_header)
        pf.addWidget(QLabel("帧尾(hex)"))
        self.protocol_tail = QLineEdit()
        self.protocol_tail.setPlaceholderText("可空，如 0D 0A")
        pf.addWidget(self.protocol_tail)
        pf.addWidget(QLabel("长度字节"))
        self.protocol_len_size = QComboBox()
        for label, v in (("无", 0), ("1", 1), ("2", 2), ("4", 4)):
            self.protocol_len_size.addItem(label, v)
        pf.addWidget(self.protocol_len_size)
        pf.addWidget(QLabel("校验"))
        self.protocol_checksum = QComboBox()
        for label, key in (("无", "none"), ("SUM8", "sum8"), ("XOR8", "xor8"), ("CRC16-Modbus", "crc16_modbus")):
            self.protocol_checksum.addItem(label, key)
        pf.addWidget(self.protocol_checksum)
        pf.addWidget(_make_btn("应用", self._apply_protocol))
        pf.addStretch(1)
        self.protocol_panel.setVisible(False)
        layout.addWidget(self.protocol_panel)

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

    def _set_conn_visible(self, visible: bool) -> None:
        """显示/隐藏端口连接配置面板（动画），并同步视图菜单勾选状态。"""
        _start_fold(self.conn_panel, visible)
        self.window._set_action_checked(self.window.conn_action, visible)

    def _add_baud_item(self, text: str) -> None:
        """把波特率加入下拉列表（去重）；非预设项同时记入自定义列表以便持久化。"""
        text = text.strip()
        if not text:
            return
        if self.baud_combo.findText(text) < 0:
            self.baud_combo.addItem(text)
        if text not in _BAUDS and text not in self._custom_bauds:
            self._custom_bauds.append(text)

    def _commit_custom_baud(self) -> None:
        """提交当前编辑框输入的合法波特率到下拉列表（连接成功时调用）。"""
        text = self.baud_combo.currentText().strip()
        if not text:
            return
        try:
            baud = int(text)
        except ValueError:
            return
        if baud <= 0:
            return
        self._add_baud_item(text)
        self.baud_combo.setCurrentText(text)

    def _delete_current_custom_baud(self) -> None:
        """删除当前（非预设）自定义波特率。"""
        text = self.baud_combo.currentText().strip()
        if not text or text in _BAUDS:
            return
        idx = self.baud_combo.findText(text)
        if idx >= 0:
            self.baud_combo.removeItem(idx)
        if text in self._custom_bauds:
            self._custom_bauds.remove(text)
        if self._connected_baud == text:
            self._connected_baud = None
        self.baud_combo.setCurrentText("115200")
        self.window._save_config()

    def _clear_custom_bauds(self) -> None:
        """清空所有自定义波特率，恢复到只含预设。"""
        for text in list(self._custom_bauds):
            idx = self.baud_combo.findText(text)
            if idx >= 0:
                self.baud_combo.removeItem(idx)
        self._custom_bauds.clear()
        if self._connected_baud not in _BAUDS:
            self._connected_baud = None
        self.baud_combo.setCurrentText("115200")
        self.window._save_config()

    def _show_baud_menu(self, global_pos) -> None:
        """右键波特率输入框：删除自定义波特率。"""
        menu = QMenu(self)
        text = self.baud_combo.currentText().strip()
        is_custom = bool(text) and text not in _BAUDS
        del_action = menu.addAction(f"删除自定义波特率 {text}" if is_custom else "删除当前自定义波特率")
        del_action.setEnabled(is_custom)
        clear_action = menu.addAction("清空全部自定义波特率")
        clear_action.setEnabled(bool(self._custom_bauds))
        chosen = menu.exec(global_pos)
        if chosen is del_action and is_custom:
            self._delete_current_custom_baud()
        elif chosen is clear_action:
            self._clear_custom_bauds()
        menu.deleteLater()

    def _check_hotplug(self) -> None:
        current = {d for d, _ in self.serial.list_ports()}
        if self.serial.is_connected:
            port = self.port_combo.currentData()
            if port and port not in current:
                # 连接中的端口被拔出：自动断开并提示
                self._known_ports = current
                self.serial.disconnect()
                self.connect_btn.setText("打开串口")
                _set_role(self.connect_btn, "primary")
                self._sys(f"串口 {port} 已断开")
                if self._logmgr.is_open:
                    self._stop_record()
                self._set_conn_visible(True)
                self.window.update_session_title(self)
            return
        if current != self._known_ports:
            self._known_ports = current
            self.refresh_ports()

    def toggle_connection(self) -> None:
        if self.serial.is_connected:
            self.serial.disconnect()
            self.connect_btn.setText("打开串口")
            _set_role(self.connect_btn, "primary")
            self._sys("已关闭串口")
            if self._logmgr.is_open:
                self._stop_record()
            self._set_conn_visible(True)
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
            if baud <= 0:
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
                _set_role(self.connect_btn, "danger")
                self._sys(f"已打开 {port} @ {baud}")
                self._connected_baud = str(baud)  # 只记录连接成功的波特率
                self._commit_custom_baud()  # 连接成功后加入下拉列表
                if self.window._auto_record and not self._logmgr.is_open:
                    self._start_record()
                self._set_conn_visible(False)  # 连接成功后自动收起端口连接配置
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

    def _on_receive_batch(self, items) -> None:
        for payload, ok in items:
            self._pending.put((_now(), "rx", payload))
            if not ok:
                self._pending.put((_now(), "sys", f"帧校验失败: {payload.hex(' ').upper()}"))

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
            data = self._parse_escaped(text) + nl.encode(self._encoding(), errors="replace")
        if self._do_send(data):
            self._add_send_history(text)

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
            data = self._parse_escaped(content) + nl.encode(self._encoding(), errors="replace")
        self._do_send(data)

    def _parse_hex(self, text: str) -> bytes | None:
        t = text.replace(" ", "").replace("0x", "").replace("0X", "")
        try:
            return bytes.fromhex(t)
        except ValueError:
            return None

    def _parse_escaped(self, text: str) -> bytes:
        """解析转义字符：\\r \\n \\t \\0 \\xNN \\\\，其余按当前编码编码。"""
        enc = self._encoding()
        out = bytearray()
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if c == "\\" and i + 1 < n:
                nxt = text[i + 1]
                if nxt == "r":
                    out.append(0x0D); i += 2; continue
                if nxt == "n":
                    out.append(0x0A); i += 2; continue
                if nxt == "t":
                    out.append(0x09); i += 2; continue
                if nxt == "0":
                    out.append(0x00); i += 2; continue
                if nxt == "\\":
                    out.extend(b"\\"); i += 2; continue
                if nxt in "xX" and i + 3 < n:
                    try:
                        out.append(int(text[i + 2:i + 4], 16)); i += 4; continue
                    except ValueError:
                        pass
                out.extend((c + nxt).encode(enc, errors="replace")); i += 2; continue
            out.extend(c.encode(enc, errors="replace"))
            i += 1
        return bytes(out)

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

    def _display_body(self, payload) -> str:
        if isinstance(payload, bytes):
            if self._hex:
                return payload.hex(" ").upper()
            return payload.decode(self._encoding(), errors="replace")
        return str(payload)

    def _log_colors(self) -> dict:
        return _LOG_THEME_COLORS.get(self.window._resolved_theme(), _LOG_THEME_COLORS["day"])

    def _format_line(self, ts: str, direction: str, payload) -> str:
        return f"[{ts}] {self._dir_mark(direction)}{self._display_body(payload)}"

    def _highlight_regex(self):
        """返回（缓存的）关键词合并正则；关键词或大小写变化时自动重编译。"""
        kws = self._filter.keywords
        case = self._filter.case_sensitive
        key = (tuple(kws), case)
        if not kws:
            self._hl_regex = None
            self._hl_regex_key = key
            return None
        if self._hl_regex_key != key:
            self._hl_regex = re.compile(
                "|".join(re.escape(k) for k in kws), 0 if case else re.IGNORECASE)
            self._hl_regex_key = key
        return self._hl_regex

    def _format_segments(self, ts: str, direction: str, payload) -> list:
        """把一行拆成 [(文本, QTextCharFormat)] 段，关键词命中内联高亮。"""
        c = self._log_colors()
        if direction == "tx":
            body_color = c["tx"]
        elif direction == "sys":
            body_color = c["sys"]
        else:
            body_color = None
        ts_fmt = _char_format(c["ts"])
        body_fmt = _char_format(body_color)
        body = self._display_body(payload)
        mark = self._dir_mark(direction)
        segs = [("[" + ts + "] ", ts_fmt)]
        if mark:
            segs.append((mark, body_fmt))
        # 内联关键词高亮：随数据插入时一次性着色，避免周期性全文档扫描 + 海量 ExtraSelection
        if (not self._hex and self._filter.highlight_enabled()
                and self._filter.keywords and body):
            rx = self._highlight_regex()
            if rx is not None:
                hl_fmt = _highlight_format(c["hl_bg"], c["hl_fg"])
                pos = 0
                for m in rx.finditer(body):
                    if m.start() > pos:
                        segs.append((body[pos:m.start()], body_fmt))
                    segs.append((m.group(0), hl_fmt))
                    pos = m.end()
                if pos < len(body):
                    segs.append((body[pos:], body_fmt))
                return segs
        segs.append((body, body_fmt))
        return segs

    def _append_colored_lines(self, widget: QPlainTextEdit, lines: list) -> None:
        sb = widget.verticalScrollBar()
        old = sb.value()
        cursor = widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        # 批量插入合并为单个编辑块，避免逐段触发文档布局/重绘（高数据量下显著提速）
        cursor.beginEditBlock()
        try:
            for segments in lines:
                for text, fmt in segments:
                    cursor.insertText(text, fmt)
                cursor.insertBlock()
        finally:
            cursor.endEditBlock()
        sb.setValue(old)  # 保持原滚动位置；自动滚动由 _scroll 显式处理

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
        lines: list = []
        matched_lines: list = []
        rx_texts: list[str] = []
        for ts, direction, payload in items:
            self._buffer.append((ts, direction, payload))
            text = self._payload_text(payload)
            if self._logmgr.is_open:
                self._logmgr.write(self._record_line(ts, direction, payload))
            if self._paused and direction != "sys":
                continue  # 暂停只冻结显示（日志+绘图），后台仍缓冲/记录
            if self._filter.visible(text):
                lines.append(self._format_segments(ts, direction, payload))
            if self._filter.mode == "split" and self._filter.matched(text):
                matched_lines.append(self._format_segments(ts, direction, payload))
            if direction == "rx":
                rx_texts.append(text)
        self._suppress_scroll = True
        try:
            if lines:
                self._append_colored_lines(self.log_text, lines)
            if matched_lines:
                self._append_colored_lines(self.matched_text, matched_lines)
        finally:
            self._suppress_scroll = False
        if rx_texts:
            self.window.plot_window.feed_from_session(self, rx_texts)
        if self._logmgr.is_open:
            self._logmgr.flush(self.window._shard_mb, self.window._log_dir())
            if self._logmgr.error:
                self._sys(f"记录写入失败：{self._logmgr.error}")
                QMessageBox.warning(self, "记录失败", f"日志写入失败，已停止记录：\n{self._logmgr.error}")
                self._logmgr.close()
                self._sync_record_btn()
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
            lines: list = []
            for ts, direction, payload in self._buffer:
                text = self._payload_text(payload)
                if self._filter.visible(text):
                    lines.append(self._format_segments(ts, direction, payload))
            if lines:
                self._append_colored_lines(self.log_text, lines)
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
        _set_role(self.pause_btn, "outline" if self._paused else "")
        if not self._paused:
            self._rerender()

    def _set_frozen(self, frozen: bool) -> None:
        if self._frozen == frozen:
            return
        self._frozen = frozen
        self.fixed_check.blockSignals(True)
        self.fixed_check.setChecked(frozen)
        self.fixed_check.blockSignals(False)
        self._show_fixed_hint("已进入固定显示" if frozen else "已退出固定显示")

    def _on_fixed_toggle(self, checked: bool) -> None:
        self._set_frozen(checked)
        if not checked:
            self._scroll()

    def _on_wheel_up(self) -> None:
        # 滚轮向上滚动（远离底部）→ 立即进入固定显示
        if not self._frozen:
            self._set_frozen(True)

    def _show_fixed_hint(self, text: str) -> None:
        vp = self.log_text.viewport()
        pos = vp.mapToGlobal(QPoint(vp.width() // 2, 20))
        QToolTip.showText(pos, text, self.log_text)

    # ---------- 查找 ----------
    def _set_search_visible(self, visible: bool) -> None:
        """显示/隐藏查找栏（动画），并同步视图菜单勾选状态。"""
        _start_fold(self.find_bar, visible)
        self.window._set_action_checked(self.window.search_action, visible)
        if visible:
            self.find_input.setFocus()
            self.find_input.selectAll()
        else:
            self.find_input.clear()
            self._search_text = ""
            self._search_matches = []
            self._search_current = -1
            self._update_search_count()
            self._apply_highlight(self.log_text)

    def _show_find_bar(self) -> None:
        self._set_search_visible(True)

    def _hide_find_bar(self) -> None:
        self._set_search_visible(False)

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
            self._stat_text = (
                f"RX: {_fmt_bytes(rx)} ({_fmt_bytes(int(rx_rate))}/s)   "
                f"TX: {_fmt_bytes(self._tx_bytes)} ({_fmt_bytes(int(tx_rate))}/s)")
        else:
            self._stat_text = f"RX: {_fmt_bytes(rx)}   TX: {_fmt_bytes(self._tx_bytes)}"
        self.window._session_stats_updated(self)

    # ---------- 高亮 ----------
    def _maybe_highlight(self) -> None:
        # 关键词高亮已内联到插入路径，这里仅负责查找(Ctrl+F)高亮的周期刷新
        now = time.monotonic()
        if now - self._last_highlight < _HL_INTERVAL:
            return
        self._last_highlight = now
        self._apply_highlight(self.log_text)
        if self._filter.mode == "split":
            self._apply_highlight(self.matched_text)

    def _search_selections(self, widget: QPlainTextEdit) -> list:
        if widget is not self.log_text or not self._search_matches:
            return []
        c = self._log_colors()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(c["search_bg"]))
        fmt.setForeground(QColor(c["search_fg"]))
        cur_fmt = QTextCharFormat()
        cur_fmt.setBackground(QColor(c["search_bg_cur"]))
        cur_fmt.setForeground(QColor(c["search_fg"]))
        selections: list = []
        for i, cursor in enumerate(self._search_matches):
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = cur_fmt if i == self._search_current else fmt
            selections.append(sel)
        return selections

    def _apply_highlight(self, widget: QPlainTextEdit) -> None:
        widget.setExtraSelections(self._search_selections(widget))

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
        lines: list = []
        for ts, direction, payload in self._buffer:
            if self._filter.matched(self._payload_text(payload)):
                lines.append(self._format_segments(ts, direction, payload))
        if lines:
            self._append_colored_lines(self.matched_text, lines)
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

    # ---------- 协议解析 ----------
    def _apply_protocol(self) -> None:
        if not self.protocol_enable.isChecked():
            self.serial.set_frame_parser(None)
            self._sys("协议解析已关闭")
            return

        def parse_hex(text: str) -> bytes | None:
            if not text.strip():
                return b""
            t = text.replace(" ", "").replace("0x", "").replace("0X", "")
            try:
                return bytes.fromhex(t)
            except ValueError:
                return None

        header = parse_hex(self.protocol_header.text())
        tail = parse_hex(self.protocol_tail.text())
        if header is None or tail is None:
            self._sys("帧头/帧尾 HEX 格式无效")
            QMessageBox.warning(self, "协议解析", "帧头/帧尾必须是十六进制（如 AA 55）")
            return
        length_size = self.protocol_len_size.currentData()
        checksum = self.protocol_checksum.currentData()
        if not header and not tail and not length_size:
            self._sys("协议解析配置无效")
            QMessageBox.warning(self, "协议解析", "请至少配置帧头、帧尾或长度字节之一")
            return
        parser = FrameParser(header=header, tail=tail, length_size=length_size, checksum=checksum)
        self.serial.set_frame_parser(parser)
        self._sys(f"协议解析已启用：帧头={header.hex(' ').upper() or '无'} "
                  f"帧尾={tail.hex(' ').upper() or '无'} 长度字节={length_size or '无'} 校验={checksum}")

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
        if self._logmgr.is_open:
            self._stop_record()
        else:
            self._start_record()

    def _sync_record_btn(self) -> None:
        """按记录状态刷新按钮文本与角色（记录中 danger 红色）。"""
        if self._logmgr.is_open:
            self.record_btn.setText("停止记录")
            _set_role(self.record_btn, "danger")
        else:
            self.record_btn.setText("开始记录")
            _set_role(self.record_btn, "")

    def _start_record(self) -> None:
        if not self._logmgr.is_open:
            self._open_record_file()
        self._sync_record_btn()

    def _stop_record(self) -> None:
        if self._logmgr.is_open:
            self._logmgr.close()
        self._sync_record_btn()
        self._sys("已停止记录")

    def _open_record_file(self) -> None:
        port = self.port_combo.currentData() or ""
        path = self._logmgr.open(port, self.window._log_dir())
        if path:
            self._sys(f"开始记录到: {path}")
        else:
            self._sys(f"记录启动失败：{self._logmgr.error}")
            QMessageBox.warning(self, "记录失败", f"无法创建日志文件：\n{self._logmgr.error}")

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
        self._theme = "auto"
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
        self._font_family = "Consolas"
        self._wrap_enabled = True
        self._close_behavior = "exit"
        self._close_confirm = True
        self._force_quit = False
        self._bg_dir = str(_data_dir() / "background")
        self._bg_image = ""
        self._bg_blur = 10
        self._bg_enabled = False
        self._cycle_idx = 0
        self._wheel_filter = _WheelZoomFilter(self)
        self._auto_theme_timer: QTimer | None = None
        self._last_auto_theme: str | None = None
        self._load_config()
        self._build()
        self.plot_window = PlotWindow(self)
        self._build_menu()
        self._setup_tray()
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
        self._start_auto_theme_watch()

    # ---------- UI ----------
    def _build(self) -> None:
        central = BgCentralWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(*_LAYOUT_MARGIN)
        layout.setSpacing(_LAYOUT_SPACING)

        self.session_tabs = QTabWidget()
        self.session_tabs.setTabsClosable(True)
        self.session_tabs.tabCloseRequested.connect(self._close_session)
        self.session_tabs.currentChanged.connect(self._on_tab_changed)
        # 右键标签页标签 → 重新显示连接配置等
        self.session_tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_tabs.tabBar().customContextMenuRequested.connect(self._show_session_tab_menu)
        # 「＋ 新建串口」并入标签栏右上角，替代独立整行按钮
        add_tab_btn = QToolButton(self.session_tabs)
        add_tab_btn.setText("＋")
        add_tab_btn.setToolTip("添加串口会话")
        add_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_tab_btn.setFixedSize(26, 26)
        add_tab_btn.clicked.connect(self._add_session)
        self.session_tabs.setCornerWidget(add_tab_btn, Qt.Corner.TopRightCorner)
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

        # 主窗口状态栏：常驻显示当前会话的连接状态与统计
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet(f"color: {self._muted_color()};")
        self._session_count_label = QLabel("")
        self._session_count_label.setStyleSheet(f"color: {self._muted_color()};")
        sb = self.statusBar()
        sb.addWidget(self._status_label, 1)
        sb.addPermanentWidget(self._session_count_label)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # 顶部工具栏：常用会话操作 + 视图开关（与菜单共享 QAction，状态自动同步）
        self._toolbar = QToolBar("主工具栏", self)
        self._toolbar.setObjectName("mainToolBar")
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(18, 18))
        self._toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(self._toolbar)
        self._icon_actions: list[tuple[object, str]] = []  # (QAction, 图标名)

        def _ico(action, name: str) -> None:
            """给动作配图标并登记，便于主题切换时换色。"""
            self._icon_actions.append((action, name))

        # ---------- 文件 ----------
        file_menu = menubar.addMenu("文件")
        save_log_action = QAction("保存日志", self)
        save_log_action.setShortcut(QKeySequence("Ctrl+S"))
        save_log_action.triggered.connect(self._save_log_active)
        file_menu.addAction(save_log_action)
        _ico(save_log_action, "save")
        self._toolbar.addAction(save_log_action)
        open_log_dir_action = QAction("打开日志目录", self)
        open_log_dir_action.triggered.connect(self._open_log_dir)
        file_menu.addAction(open_log_dir_action)
        _ico(open_log_dir_action, "folder")
        self._toolbar.addAction(open_log_dir_action)
        self._toolbar.addSeparator()
        file_menu.addSeparator()
        export_action = QAction("导出配置...", self)
        export_action.triggered.connect(self._export_config)
        file_menu.addAction(export_action)
        _ico(export_action, "export")
        import_action = QAction("导入配置...", self)
        import_action.triggered.connect(self._import_config)
        file_menu.addAction(import_action)
        _ico(import_action, "import")
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        _ico(quit_action, "quit")

        # ---------- 视图 ----------
        view = menubar.addMenu("视图")

        self.conn_action = QAction("端口连接配置", self, checkable=True)
        self.conn_action.toggled.connect(self._toggle_active_conn)
        view.addAction(self.conn_action)
        _ico(self.conn_action, "port")
        self._toolbar.addAction(self.conn_action)

        self.params_action = QAction("串口参数", self, checkable=True)
        self.params_action.toggled.connect(self._toggle_active_params)
        view.addAction(self.params_action)
        _ico(self.params_action, "sliders")
        self._toolbar.addAction(self.params_action)

        self.filter_action = QAction("关键词过滤", self, checkable=True)
        self.filter_action.toggled.connect(self._toggle_active_filter)
        view.addAction(self.filter_action)
        _ico(self.filter_action, "filter")
        self._toolbar.addAction(self.filter_action)

        self.search_action = QAction("关键词搜索", self, checkable=True)
        self.search_action.toggled.connect(self._toggle_active_search)
        view.addAction(self.search_action)
        _ico(self.search_action, "search")
        self._toolbar.addAction(self.search_action)

        self.send_action = QAction("消息发送", self, checkable=True)
        self.send_action.toggled.connect(self._toggle_active_send)
        view.addAction(self.send_action)
        _ico(self.send_action, "message")
        self._toolbar.addAction(self.send_action)

        self.send_assist_action = QAction("发送辅助", self, checkable=True)
        self.send_assist_action.toggled.connect(self._toggle_send_assist)
        view.addAction(self.send_assist_action)
        _ico(self.send_assist_action, "send")
        self._toolbar.addAction(self.send_assist_action)

        self.auto_reply_action = QAction("自动应答", self, checkable=True)
        self.auto_reply_action.toggled.connect(self._toggle_active_auto_reply)
        view.addAction(self.auto_reply_action)
        _ico(self.auto_reply_action, "reply")
        self._toolbar.addAction(self.auto_reply_action)

        self.protocol_action = QAction("协议解析", self, checkable=True)
        self.protocol_action.toggled.connect(self._toggle_active_protocol)
        view.addAction(self.protocol_action)
        _ico(self.protocol_action, "hex")
        self._toolbar.addAction(self.protocol_action)

        self.plot_action = QAction("数值绘图", self, checkable=True)
        self.plot_action.toggled.connect(self._toggle_plot_window)
        view.addAction(self.plot_action)
        _ico(self.plot_action, "chart")
        self._toolbar.addAction(self.plot_action)

        view.addSeparator()
        self._toolbar.addSeparator()
        self.wrap_action = QAction("自动换行", self, checkable=True)
        self.wrap_action.setChecked(self._wrap_enabled)
        self.wrap_action.toggled.connect(self._toggle_wrap)
        view.addAction(self.wrap_action)
        _ico(self.wrap_action, "wrap")
        self._toolbar.addAction(self.wrap_action)
        ascii_hex_action = QAction("ASCII/HEX 转换...", self)
        ascii_hex_action.triggered.connect(self._open_ascii_hex_dialog)
        view.addAction(ascii_hex_action)
        _ico(ascii_hex_action, "convert")
        self._toolbar.addAction(ascii_hex_action)

        # ---------- 设置 ----------
        settings_menu = menubar.addMenu("设置")
        theme_menu = settings_menu.addMenu("主题")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        # auto：跟随系统深浅色；black=深色 / day=白天 / eye=护眼（浅绿）
        for label, key in (("跟随系统", "auto"), ("深色", "black"), ("白天", "day"), ("护眼", "eye")):
            a = QAction(label, self, checkable=True)
            a.setChecked(self._theme == key)
            a.triggered.connect(lambda _=False, k=key: self._set_theme(k))
            theme_group.addAction(a)
            theme_menu.addAction(a)
        bg_action = QAction("背景皮肤...", self)
        bg_action.triggered.connect(self._open_background_dialog)
        settings_menu.addAction(bg_action)
        _ico(bg_action, "palette")
        settings_menu.addSeparator()
        font_action = QAction("字体...", self)
        font_action.triggered.connect(self._choose_font)
        settings_menu.addAction(font_action)
        _ico(font_action, "font")
        zoom_in = QAction("字体增大", self)
        zoom_in.setShortcut(QKeySequence("Ctrl+="))
        zoom_in.triggered.connect(lambda: self._zoom_log(1))
        zoom_out = QAction("字体减小", self)
        zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        zoom_out.triggered.connect(lambda: self._zoom_log(-1))
        zoom_reset = QAction("重置字体", self)
        zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        zoom_reset.triggered.connect(self._reset_font)
        settings_menu.addAction(zoom_in)
        settings_menu.addAction(zoom_out)
        settings_menu.addAction(zoom_reset)
        settings_menu.addSeparator()
        self.auto_record_action = QAction("连接后自动保存日志", self, checkable=True)
        self.auto_record_action.setChecked(self._auto_record)
        self.auto_record_action.toggled.connect(self._set_auto_record)
        settings_menu.addAction(self.auto_record_action)
        log_dir_action = QAction("日志保存目录...", self)
        log_dir_action.triggered.connect(self._choose_log_dir)
        settings_menu.addAction(log_dir_action)
        _ico(log_dir_action, "folder")
        shard_action = QAction("日志分片大小...", self)
        shard_action.triggered.connect(self._set_shard_size)
        settings_menu.addAction(shard_action)
        _ico(shard_action, "shard")
        retention_action = QAction("日志保留策略...", self)
        retention_action.triggered.connect(self._set_log_retention)
        settings_menu.addAction(retention_action)
        _ico(retention_action, "retention")
        settings_menu.addSeparator()
        self.tray_action = QAction("关闭时最小化到托盘", self, checkable=True)
        self.tray_action.setChecked(self._close_behavior == "tray")
        self.tray_action.toggled.connect(self._set_close_behavior)
        settings_menu.addAction(self.tray_action)
        _ico(self.tray_action, "tray")
        self.close_confirm_action = QAction("关闭时询问", self, checkable=True)
        self.close_confirm_action.setChecked(self._close_confirm)
        self.close_confirm_action.toggled.connect(self._set_close_confirm)
        settings_menu.addAction(self.close_confirm_action)

        # ---------- 帮助 ----------
        help_menu = menubar.addMenu("帮助")
        docs_action = QAction("使用说明", self)
        docs_action.triggered.connect(self._open_docs)
        help_menu.addAction(docs_action)
        _ico(docs_action, "question")
        check_update_action = QAction("检查更新", self)
        check_update_action.triggered.connect(self._check_update_manual)
        help_menu.addAction(check_update_action)
        _ico(check_update_action, "update")
        help_menu.addSeparator()
        about = QAction("关于", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)
        _ico(about, "info")

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
        custom_bauds = r.get("custom_bauds")
        if isinstance(custom_bauds, list):
            for b in custom_bauds:
                if isinstance(b, str):
                    s._add_baud_item(b)
        baud = r.get("baud")
        if baud:
            s.baud_combo.setCurrentText(str(baud))
            s._connected_baud = str(baud)
            if str(baud) not in _BAUDS:
                s._add_baud_item(str(baud))
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
        self._apply_font_to_session(s)
        self._apply_wrap_to_session(s)
        self.session_tabs.addTab(s, s.title())
        self._apply_tab_indicator(s)
        self.session_tabs.setCurrentIndex(self.session_tabs.count() - 1)
        self.plot_window.set_sessions(self._sessions)
        self._sync_menu_state()
        self._refresh_statusbar()

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
            self._apply_tab_indicator(sess)
        self.plot_window.set_sessions(self._sessions)
        self._sync_menu_state()
        self._refresh_statusbar()

    def _apply_tab_indicator(self, session: SerialSession) -> None:
        """刷新标签页文字与连接状态颜色（已连接显示绿点）。"""
        if session not in self._sessions:
            return
        idx = self._sessions.index(session)
        self.session_tabs.setTabText(idx, session.title())
        if session.serial.is_connected:
            self.session_tabs.tabBar().setTabTextColor(idx, QColor(_CONNECTED_COLOR))
        else:
            self.session_tabs.tabBar().setTabTextColor(idx, QColor())

    def update_session_title(self, session: SerialSession) -> None:
        if session in self._sessions:
            self._apply_tab_indicator(session)
        self.plot_window.set_sessions(self._sessions)
        self._refresh_statusbar()

    def _on_tab_changed(self, _idx: int) -> None:
        self._sync_menu_state()
        self._refresh_statusbar()

    def _refresh_statusbar(self) -> None:
        """刷新主窗口状态栏：当前会话的连接状态 / 参数 / RX-TX 统计。"""
        s = self.active_session()
        if s is None:
            self._status_label.setText("就绪")
            self._session_count_label.setText("")
            return
        port = s.port_combo.currentData() or "未选端口"
        baud = s.baud_combo.currentText()
        enc = s.encoding_combo.currentText()
        conn = "已连接" if s.serial.is_connected else "未连接"
        self._status_label.setText(f"{port} @ {baud} · {enc} · {conn}    {s._stat_text}")
        self._session_count_label.setText(f"{len(self._sessions)} 个会话")

    def _session_stats_updated(self, session: SerialSession) -> None:
        """会话统计更新回调：若为当前激活会话则刷新状态栏（高频，仅文本比较后更新）。"""
        if session is not self.active_session():
            return
        port = session.port_combo.currentData() or "未选端口"
        baud = session.baud_combo.currentText()
        enc = session.encoding_combo.currentText()
        conn = "已连接" if session.serial.is_connected else "未连接"
        text = f"{port} @ {baud} · {enc} · {conn}    {session._stat_text}"
        if self._status_label.text() != text:
            self._status_label.setText(text)

    def _toggle_send_assist(self, checked: bool) -> None:
        """视图菜单「发送辅助」：动画展开 / 收起全局面板。"""
        _start_fold(self.send_assist_panel, checked)

    def _set_action_checked(self, action, checked: bool) -> None:
        """设置动作勾选状态但不触发其 toggled（避免重复折叠动画 / 级联）。"""
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)

    def _sync_menu_state(self) -> None:
        s = self.active_session()
        self._set_action_checked(self.conn_action, bool(s and not s.conn_panel.isHidden()))
        self._set_action_checked(self.params_action, bool(s and not s.serial_params_panel.isHidden()))
        self._set_action_checked(self.filter_action, bool(s and not s.filter_panel.isHidden()))
        self._set_action_checked(self.search_action, bool(s and not s.find_bar.isHidden()))
        self._set_action_checked(self.send_action, bool(s and not s.send_panel.isHidden()))
        self._set_action_checked(self.auto_reply_action, bool(s and not s.auto_reply_panel.isHidden()))
        self._set_action_checked(self.protocol_action, bool(s and not s.protocol_panel.isHidden()))

    def _toggle_active_conn(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            s._set_conn_visible(checked)

    def _toggle_active_filter(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            _start_fold(s.filter_panel, checked)

    def _toggle_active_search(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            s._set_search_visible(checked)

    def _toggle_active_send(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            _start_fold(s.send_panel, checked)

    def _toggle_active_params(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            _start_fold(s.serial_params_panel, checked)

    def _toggle_active_auto_reply(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            _start_fold(s.auto_reply_panel, checked)

    def _toggle_active_protocol(self, checked: bool) -> None:
        s = self.active_session()
        if s:
            _start_fold(s.protocol_panel, checked)

    def _show_session_tab_menu(self, pos) -> None:
        """右键串口标签页：切换该会话连接配置的显示/隐藏。"""
        idx = self.session_tabs.tabBar().tabAt(pos)
        menu = QMenu(self)
        toggle_conn = None
        visible = False
        if 0 <= idx < len(self._sessions):
            visible = not self._sessions[idx].conn_panel.isHidden()
            toggle_conn = menu.addAction("隐藏连接配置" if visible else "显示连接配置")
        close_tab = menu.addAction("关闭该串口会话")
        chosen = menu.exec(self.session_tabs.tabBar().mapToGlobal(pos))
        if chosen is toggle_conn and toggle_conn is not None:
            if 0 <= idx < len(self._sessions):
                self._sessions[idx]._set_conn_visible(not visible)
                self.session_tabs.setCurrentIndex(idx)
        elif chosen is close_tab:
            if idx >= 0:
                self._close_session(idx)
        menu.deleteLater()

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
                btn.setFixedHeight(34)
                btn.setMinimumWidth(100)
                btn.setToolTip((cmd.get("name") or "") + "\n" + (cmd.get("content") or ""))
                r, c = divmod(k, 4)
                grid.addWidget(btn, r, c, Qt.AlignLeft | Qt.AlignTop)
                k += 1
            grid.setColumnStretch(4, 1)
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
        if not _confirm_danger(self, "删除页", msg):
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
        if not _confirm_danger(self, "删除命令",
                               f"确定删除命令「{cmd.get('name')}」吗？"):
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
            f = self._make_log_font(_DEFAULT_FONT_SIZE)
            s.log_text.setFont(f)
            s.matched_text.setFont(f)
            self._save_config()

    def _make_log_font(self, point_size: int) -> QFont:
        family = self._font_family
        if family not in ("", "default") and family not in QFontDatabase.families():
            family = "default"  # 未安装则回退到系统默认等宽
        if family in ("", "default"):
            f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        else:
            f = QFont(family)
        f.setPointSize(max(1, point_size))
        return f

    def _apply_font_to_session(self, s) -> None:
        fs = s.log_text.font().pointSize()
        if fs <= 0:
            fs = _DEFAULT_FONT_SIZE
        f = self._make_log_font(fs)
        s.log_text.setFont(f)
        s.matched_text.setFont(f)

    def _apply_wrap_to_session(self, s) -> None:
        mode = (QPlainTextEdit.LineWrapMode.WidgetWidth if self._wrap_enabled
                else QPlainTextEdit.LineWrapMode.NoWrap)
        s.log_text.setLineWrapMode(mode)
        s.matched_text.setLineWrapMode(mode)

    def _toggle_wrap(self, checked: bool) -> None:
        self._wrap_enabled = checked
        for s in self._sessions:
            self._apply_wrap_to_session(s)
        self._save_config()

    def _choose_font(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("日志字体")
        form = QFormLayout(dlg)
        combo = QComboBox()
        for label, key in _FONT_OPTIONS:
            combo.addItem(label, key)
        idx = combo.findData(self._font_family)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("等宽字体", combo)
        tip = QLabel("字体未安装时会自动回退到系统默认等宽字体。")
        tip.setStyleSheet(f"color: {self._muted_color()};")
        form.addRow("", tip)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        self._font_family = combo.currentData()
        for s in self._sessions:
            self._apply_font_to_session(s)
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
        if isinstance(data.get("theme"), str) and data["theme"] in ("auto", "black", "eye", "day"):
            self._theme = data["theme"]
        if isinstance(data.get("auto_record"), bool):
            self._auto_record = data["auto_record"]
        if isinstance(data.get("shard_mb"), int):
            self._shard_mb = max(1, data["shard_mb"])
        if isinstance(data.get("log_retention"), str) and data["log_retention"] in _LOG_RETENTION_KEYS:
            self._log_retention = data["log_retention"]
        if isinstance(data.get("last_update_check"), str):
            self._last_update_check = data["last_update_check"]
        if isinstance(data.get("font_family"), str) and data["font_family"] in [k for _, k in _FONT_OPTIONS]:
            self._font_family = data["font_family"]
        if isinstance(data.get("wrap_enabled"), bool):
            self._wrap_enabled = data["wrap_enabled"]
        if isinstance(data.get("close_behavior"), str) and data["close_behavior"] in ("exit", "tray"):
            self._close_behavior = data["close_behavior"]
        if isinstance(data.get("close_confirm"), bool):
            self._close_confirm = data["close_confirm"]
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
        self._pages, self._commands = _load_pages_commands(data, self._pages)

    def _config_data(self) -> dict:
        sessions = []
        for s in self._sessions:
            fs = s.log_text.font().pointSize()
            sessions.append({
                "port": s.port_combo.currentData(),
                "baud": s._connected_baud,
                "custom_bauds": s._custom_bauds,
                "filter_keywords": s.keyword_edit.text(),
                "filter_mode": s.mode_combo.currentData(),
                "filter_case": s.case_check.isChecked(),
                "filter_enabled": s._filter_enabled,
                "font_size": fs if fs > 0 else _DEFAULT_FONT_SIZE,
            })
        return {
            "theme": self._theme,
            "pages": self._pages,
            "commands": self._commands,
            "auto_record": self._auto_record,
            "shard_mb": self._shard_mb,
            "log_retention": self._log_retention,
            "last_update_check": self._last_update_check,
            "font_family": self._font_family,
            "wrap_enabled": self._wrap_enabled,
            "close_behavior": self._close_behavior,
            "close_confirm": self._close_confirm,
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
        tip.setStyleSheet(f"color: {self._muted_color()};")
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
        LogManager.clean_old_logs(self._log_dir(), self._log_retention)

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
        if isinstance(data.get("theme"), str) and data["theme"] in ("auto", "black", "eye", "day"):
            self._theme = data["theme"]
            self._apply_theme_qss()
        if isinstance(data.get("auto_record"), bool):
            self._auto_record = data["auto_record"]
            self.auto_record_action.setChecked(self._auto_record)
        if isinstance(data.get("shard_mb"), int):
            self._shard_mb = max(1, data["shard_mb"])
        if isinstance(data.get("log_retention"), str) and data["log_retention"] in _LOG_RETENTION_KEYS:
            self._log_retention = data["log_retention"]
        if isinstance(data.get("font_family"), str) and data["font_family"] in [k for _, k in _FONT_OPTIONS]:
            self._font_family = data["font_family"]
        if isinstance(data.get("wrap_enabled"), bool):
            self._wrap_enabled = data["wrap_enabled"]
        if isinstance(data.get("close_behavior"), str) and data["close_behavior"] in ("exit", "tray"):
            self._close_behavior = data["close_behavior"]
        if isinstance(data.get("close_confirm"), bool):
            self._close_confirm = data["close_confirm"]
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
        self._pages, self._commands = _load_pages_commands(data, self._pages)
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
        for s in self._sessions:
            self._apply_font_to_session(s)
            self._apply_wrap_to_session(s)
        self._save_config()
        self._active_sys(f"配置已导入: {path}")

    # ---------- 主题 ----------
    def _live_resolved_theme(self) -> str:
        """实时解析系统深浅（仅主题切换/轮询时调用，避免热路径每行都查 darkdetect）。"""
        if darkdetect is not None:
            try:
                return "black" if darkdetect.isDark() else "day"
            except Exception:
                pass
        return "day"

    def _resolved_theme(self) -> str:
        """返回当前实际主题（auto 已解析）；热路径友好，使用缓存值。"""
        if self._theme != "auto":
            return self._theme
        if self._last_auto_theme not in ("black", "day"):
            self._last_auto_theme = self._live_resolved_theme()
        return self._last_auto_theme

    def _set_theme(self, theme: str) -> None:
        self._theme = theme
        if theme == "auto":
            self._last_auto_theme = self._live_resolved_theme()
        self._apply_theme_qss()
        self._refresh_muted_labels()
        self._save_config()

    def _apply_theme_qss(self) -> None:
        resolved = self._resolved_theme()
        cfg = dict(_THEME_CFG.get(resolved, _THEME_CFG["day"]))
        cfg["additional_qss"] = _UI_QSS + _role_qss(resolved)
        qdarktheme.setup_theme(**cfg)
        self._refresh_icons()

    def _refresh_muted_labels(self) -> None:
        """主题 / 系统深浅切换后刷新状态栏等次要文字颜色。"""
        muted = self._muted_color()
        self._status_label.setStyleSheet(f"color: {muted};")
        self._session_count_label.setStyleSheet(f"color: {muted};")

    def _start_auto_theme_watch(self) -> None:
        """auto 模式轮询系统深浅色：变化时重设实际主题（保存仍为 auto）。"""
        if self._theme == "auto":
            self._last_auto_theme = self._live_resolved_theme()
        if darkdetect is None or self._auto_theme_timer is not None:
            return
        timer = QTimer(self)
        timer.setInterval(2000)
        timer.timeout.connect(self._poll_auto_theme)
        timer.start()
        self._auto_theme_timer = timer

    def _poll_auto_theme(self) -> None:
        if self._theme != "auto":
            return
        cur = self._live_resolved_theme()
        if cur != self._last_auto_theme:
            self._last_auto_theme = cur
            self._apply_theme_qss()
            self._refresh_muted_labels()

    def _icon_color(self) -> str:
        """图标前景色：随主题自适应（QSS 无法引用，故用与 muted 近似的中性色）。"""
        muted = self._muted_color()
        # muted 在暗色下偏亮、浅色下偏暗，直接用即可保证可见性
        return muted

    def _refresh_icons(self) -> None:
        """按当前主题重绘菜单 / 工具栏图标（颜色随主题切换）。"""
        color = self._icon_color()
        for action, name in getattr(self, "_icon_actions", []):
            try:
                set_action_icon(action, name, color)
            except Exception:
                pass

    def _muted_color(self) -> str:
        """返回当前主题下的次要文字色（统计/提示等弱化文字）。"""
        resolved = self._resolved_theme()
        return _LOG_THEME_COLORS.get(resolved, _LOG_THEME_COLORS["day"]).get("muted", "#888888")

    # ---------- 背景皮肤 ----------
    def _refresh_bg_combo(self, combo: QComboBox, directory: str | None = None) -> None:
        combo.clear()
        combo.addItem("无", "")
        d = Path(directory if directory is not None else self._bg_dir)
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
        state = {"dir": str(bg_dir)}

        def refresh() -> None:
            self._refresh_bg_combo(combo, state["dir"])

        refresh()

        # 背景图存放提示行
        hint_row = QWidget()
        hl = QHBoxLayout(hint_row)
        hl.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(f"背景图存放目录：{state['dir']}")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {self._muted_color()};")
        hl.addWidget(hint, 1)

        def choose_dir() -> None:
            path = QFileDialog.getExistingDirectory(dlg, "选择背景图目录", state["dir"])
            if not path:
                return
            Path(path).mkdir(parents=True, exist_ok=True)
            state["dir"] = path
            hint.setText(f"背景图存放目录：{path}")
            refresh()

        hl.addWidget(_make_btn("选择目录...", choose_dir))
        hl.addWidget(_make_btn("打开目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(state["dir"]))))
        hl.addWidget(_make_btn("刷新", refresh))
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
        self._bg_dir = state["dir"]
        self._bg_image = combo.currentData() or ""
        self._bg_blur = blur_slider.value()
        self._bg_enabled = enable_check.isChecked()
        self._apply_background()
        self._save_config()

    def _set_session_transparent(self, s, flag: bool) -> None:
        s.setAttribute(Qt.WA_TranslucentBackground, flag)
        for panel in (s.conn_panel, s.serial_params_panel, s.filter_panel, s.find_bar,
                      s.matched_panel, s.send_panel, s.auto_reply_panel, s.protocol_panel):
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

    def _open_ascii_hex_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("ASCII / HEX 转换")
        dlg.resize(640, 460)
        layout = QVBoxLayout(dlg)

        sep_combo = QComboBox()
        sep_combo.addItem("空格分隔", " ")
        sep_combo.addItem("无分隔", "")
        sep_combo.addItem("0x 逗号", "0x,")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("HEX 格式:"))
        bar.addWidget(sep_combo)
        bar.addStretch(1)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Vertical)
        ascii_edit = QPlainTextEdit()
        ascii_edit.setPlaceholderText("输入文本，例如 hello")
        hex_edit = QPlainTextEdit()
        hex_edit.setPlaceholderText("输入十六进制，例如 68 65 6C 6C 6F")

        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(QLabel("ASCII 文本"))
        tl.addWidget(ascii_edit)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel("HEX"))
        bl.addWidget(hex_edit)
        splitter.addWidget(top)
        splitter.addWidget(bottom)
        layout.addWidget(splitter, 1)

        guard = {"busy": False}

        def ascii_to_hex() -> None:
            hx = ascii_edit.toPlainText().encode("utf-8").hex().upper()
            sep = sep_combo.currentData()
            if sep == " ":
                out = " ".join(hx[i:i + 2] for i in range(0, len(hx), 2))
            elif sep == "":
                out = hx
            else:
                out = ", ".join("0x" + hx[i:i + 2] for i in range(0, len(hx), 2))
            guard["busy"] = True
            hex_edit.setPlainText(out)
            guard["busy"] = False

        def hex_to_ascii() -> None:
            t = hex_edit.toPlainText()
            t = (t.replace("0x", "").replace("0X", "")
                 .replace(",", "").replace(" ", "").replace("\n", ""))
            try:
                data = bytes.fromhex(t)
            except ValueError:
                return
            guard["busy"] = True
            ascii_edit.setPlainText(data.decode("utf-8", errors="replace"))
            guard["busy"] = False

        def on_ascii_changed() -> None:
            if not guard["busy"]:
                ascii_to_hex()

        def on_hex_changed() -> None:
            if not guard["busy"]:
                hex_to_ascii()

        def on_sep_changed() -> None:
            if ascii_edit.toPlainText():
                ascii_to_hex()

        ascii_edit.textChanged.connect(on_ascii_changed)
        hex_edit.textChanged.connect(on_hex_changed)
        sep_combo.currentIndexChanged.connect(on_sep_changed)

        dlg.exec()

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

    def _setup_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(QIcon(str(_resource_path("my-icon.ico"))), self)
        self.tray_icon.setToolTip(_APP_NAME)
        menu = QMenu()
        show_action = menu.addAction("显示主窗口")
        show_action.triggered.connect(self._show_from_tray)
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_from_tray()

    def _quit(self) -> None:
        self._force_quit = True
        self.close()

    def _set_close_behavior(self, checked: bool) -> None:
        self._close_behavior = "tray" if checked else "exit"
        self._save_config()

    def _set_close_confirm(self, checked: bool) -> None:
        self._close_confirm = checked
        self._save_config()

    def _should_tray_on_close(self) -> bool:
        if self._force_quit:
            return False
        if self._close_confirm:
            dlg = QMessageBox(self)
            dlg.setWindowTitle("关闭")
            dlg.setIcon(QMessageBox.Icon.Question)
            dlg.setText("关闭时是否最小化到托盘？")
            tray_btn = dlg.addButton("最小化到托盘", QMessageBox.ButtonRole.YesRole)
            exit_btn = dlg.addButton("直接退出", QMessageBox.ButtonRole.NoRole)
            noask = QCheckBox("不再提示")
            dlg.setCheckBox(noask)
            dlg.exec()
            tray = dlg.clickedButton() is tray_btn
            if noask.isChecked():
                self._close_confirm = False
                self._close_behavior = "tray" if tray else "exit"
                self._save_config()
            return tray
        return self._close_behavior == "tray"

    def closeEvent(self, event) -> None:
        if self._should_tray_on_close():
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                _APP_NAME, "已最小化到托盘，双击图标恢复", QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            self._save_config()
            self._timer_send.stop()
            for s in self._sessions:
                s.shutdown()
            self.tray_icon.hide()
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
    # Windows 任务栏图标：设置 AppUserModelID，避免显示 Python 默认图标
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ShineZhang.OhmyPort")
        except Exception:
            pass
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

