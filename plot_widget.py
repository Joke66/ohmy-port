"""数值绘图：规则提取（PlotRule）、折线图（PlotWidget）、独立绘图窗口（PlotWindow）。"""

from __future__ import annotations

import collections
import re
import time

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from common import _PLOT_WINDOW, _extract_numbers

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
