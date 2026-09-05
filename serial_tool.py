"""串口工具（独立工具）：实时串口日志 + 多关键词过滤 + 时间戳保存。

独立于「老化板上位机」，可单独运行：
    python serial_tool.py

也可由主工具通过「打开串口工具」按钮拉起。自包含：仅依赖 pyserial + PySide6。
"""

from __future__ import annotations

import datetime
import html
import re
import sys
import threading
from pathlib import Path

import serial
from serial.tools import list_ports

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

_BAUDS = ["115200", "57600", "38400", "19200", "9600", "4800", "2400"]
_RX_COLOR = "#3aa757"   # 收
_TX_COLOR = "#4a90d9"   # 发
_SYS_COLOR = "#888888"  # 系统
_HL_STYLE = "background-color:#fff59d;color:#000000;"  # 关键词高亮


def _now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _ts_name() -> str:
    return datetime.datetime.now().strftime("serial_%Y%m%d_%H%M%S")


class LogFilter:
    """多关键词过滤/高亮。

    mode:
      - highlight : 显示全部行，命中关键词高亮（类似 Notepad++ 标记全部）
      - include   : 仅显示命中行（类似 Notepad++ 查找全部），命中关键词高亮
      - exclude   : 隐藏命中行
    """

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
        return self.mode in ("highlight", "include", "window")


class SerialMonitor:
    """自包含的最小串口封装：连接 / 接收线程 / 发送。"""

    def __init__(self):
        self._serial = None
        self._callback = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @staticmethod
    def list_ports() -> list[tuple[str, str]]:
        return [(p.device, p.description or p.device) for p in list_ports.comports()]

    def connect(self, port: str, baudrate: int) -> bool:
        self.disconnect()
        try:
            self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=0.1)
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

    def send(self, data: str) -> bool:
        if self._serial is None or not self._serial.is_open:
            return False
        try:
            self._serial.write(data.encode("ascii"))
            return True
        except Exception:
            return False

    def _receive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._serial is not None and self._serial.is_open:
                    line = self._serial.readline()
                    if line and self._callback is not None:
                        self._callback(line.decode("ascii", errors="replace").rstrip("\r\n"))
            except Exception:
                if self._stop.is_set():
                    break


class MatchedWindow(QWidget):
    """命中行独立展示窗口。"""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("命中结果 - 串口工具")
        self.resize(640, 420)
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self.clear)
        bar.addWidget(clear_btn)
        bar.addStretch(1)
        v.addLayout(bar)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        v.addWidget(self.text)

    def clear(self) -> None:
        self.text.clear()

    def append_html(self, piece: str) -> None:
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(piece)
        self.text.setTextCursor(cursor)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)


class SerialToolWindow(QMainWindow):
    line_signal = Signal(str, str)  # (文本, 方向: rx/tx/sys)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("串口工具")
        self.resize(900, 640)
        self.serial = SerialMonitor()
        self._filter = LogFilter()
        self._buffer: list[tuple[str, str, str]] = []  # (时间, 方向, 文本)
        self._paused = False
        self._hex = False
        self._auto_scroll = True
        self._record_file = None
        self._matched_win: MatchedWindow | None = None
        self._programmatic_close = False
        self._build()
        self.line_signal.connect(self._on_line, Qt.QueuedConnection)
        self.serial.set_receive_callback(self._on_receive)
        self.refresh_ports()

    def _btn(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(slot)
        return btn

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        conn = QHBoxLayout()
        conn.addWidget(QLabel("端口"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(110)
        conn.addWidget(self.port_combo)
        conn.addWidget(self._btn("刷新", self.refresh_ports))
        conn.addWidget(QLabel("波特率"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(_BAUDS)
        conn.addWidget(self.baud_combo)
        self.connect_btn = self._btn("打开串口", self.toggle_connection)
        conn.addWidget(self.connect_btn)
        conn.addStretch(1)
        layout.addLayout(conn)

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
        self.mode_combo.addItem("单独窗口显示命中行", "window")
        self.mode_combo.currentIndexChanged.connect(self.apply_filter)
        filt.addWidget(self.mode_combo)
        self.case_check = QCheckBox("区分大小写")
        self.case_check.toggled.connect(self.apply_filter)
        filt.addWidget(self.case_check)
        filt.addWidget(self._btn("应用", self.apply_filter))
        layout.addLayout(filt)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text, 1)

        bar = QHBoxLayout()
        self.pause_btn = self._btn("暂停", self.toggle_pause)
        bar.addWidget(self.pause_btn)
        bar.addWidget(self._btn("清空", self.clear_log))
        self.hex_check = QCheckBox("HEX")
        self.hex_check.toggled.connect(self._rerender)
        bar.addWidget(self.hex_check)
        self.scroll_check = QCheckBox("自动滚动")
        self.scroll_check.setChecked(True)
        self.scroll_check.toggled.connect(lambda c: setattr(self, "_auto_scroll", c))
        bar.addWidget(self.scroll_check)
        self.record_btn = self._btn("开始记录", self.toggle_record)
        bar.addWidget(self.record_btn)
        bar.addWidget(self._btn("保存日志", self.save_log))
        bar.addStretch(1)
        layout.addLayout(bar)

        send = QHBoxLayout()
        send.addWidget(QLabel("发送"))
        self.send_edit = QLineEdit()
        self.send_edit.setPlaceholderText("输入要发送的数据，回车发送")
        self.send_edit.returnPressed.connect(self.send_raw)
        send.addWidget(self.send_edit, 1)
        send.addWidget(self._btn("发送", self.send_raw))
        layout.addLayout(send)

    # ---------- 串口 ----------
    def refresh_ports(self) -> None:
        self.port_combo.clear()
        for device, desc in self.serial.list_ports():
            self.port_combo.addItem(f"{device}（{desc}）", device)

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
            baud = int(self.baud_combo.currentText())
            if self.serial.connect(port, baud):
                self.connect_btn.setText("关闭串口")
                self._sys(f"已打开 {port} @ {baud}")
            else:
                self._sys(f"打开 {port} 失败")

    def _on_receive(self, line: str) -> None:
        self.line_signal.emit(line, "rx")

    def send_raw(self) -> None:
        data = self.send_edit.text()
        if not data:
            return
        if not self.serial.is_connected:
            self._sys("串口未打开，无法发送")
            return
        if self.serial.send(data):
            self.line_signal.emit(data, "tx")
            self.send_edit.clear()

    # ---------- 日志 ----------
    def _sys(self, text: str) -> None:
        self.line_signal.emit(text, "sys")

    def _dir_mark(self, d: str) -> str:
        return {"rx": "收←◆", "tx": "发→◇", "sys": "  ◆"}.get(d, "")

    def _on_line(self, text: str, direction: str) -> None:
        if self._paused and direction != "sys":
            return
        ts = _now()
        self._buffer.append((ts, direction, text))
        if self._record_file is not None:
            self._record_file.write(f"[{ts}] {self._dir_mark(direction)} {text}\n")
            self._record_file.flush()
        if self._filter.visible(text):
            self._append_html(self._render_line(ts, direction, text))
        if (self._filter.mode == "window" and self._matched_win is not None
                and self._filter.matched(text)):
            self._matched_win.append_html(self._render_line(ts, direction, text))
        self._scroll()

    def _render_line(self, ts: str, direction: str, text: str) -> str:
        color = {"rx": _RX_COLOR, "tx": _TX_COLOR, "sys": _SYS_COLOR}.get(direction, _SYS_COLOR)
        if self._hex:
            body = " ".join(f"{b:02X}" for b in text.encode("ascii", errors="replace"))
        else:
            body = html.escape(text)
            if self._filter.highlight_enabled():
                body = self._highlight(body, text)
        return (f'<span style="color:{color};">[{ts}] {self._dir_mark(direction)} '
                f'<span style="white-space:pre-wrap;">{body}</span></span><br>')

    def _highlight(self, body: str, raw: str) -> str:
        for kw in self._filter.matched(raw):
            esc = html.escape(kw)
            if self._filter.case_sensitive:
                body = body.replace(esc, f'<span style="{_HL_STYLE}">{esc}</span>')
            else:
                body = re.sub(
                    re.escape(esc),
                    lambda m: f'<span style="{_HL_STYLE}">{m.group(0)}</span>',
                    body, flags=re.IGNORECASE,
                )
        return body

    def _append_html(self, piece: str) -> None:
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(piece)
        self.log_text.setTextCursor(cursor)

    def _scroll(self) -> None:
        if self._auto_scroll:
            sb = self.log_text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _rerender(self) -> None:
        self.log_text.clear()
        for ts, direction, text in self._buffer:
            if self._filter.visible(text):
                self._append_html(self._render_line(ts, direction, text))
        self._scroll()

    def clear_log(self) -> None:
        self._buffer.clear()
        self.log_text.clear()

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText("继续" if self._paused else "暂停")
        if not self._paused:
            self._rerender()

    # ---------- 过滤 ----------
    def apply_filter(self) -> None:
        self._filter.keywords = LogFilter.parse_keywords(self.keyword_edit.text())
        self._filter.mode = self.mode_combo.currentData()
        self._filter.case_sensitive = self.case_check.isChecked()
        self._rerender()
        self._sync_matched_window()

    # ---------- 命中窗口 ----------
    def _sync_matched_window(self) -> None:
        if self._filter.mode == "window":
            self._open_matched_window()
            self._render_matched_window()
        elif self._matched_win is not None:
            self._programmatic_close = True
            self._matched_win.close()
            self._programmatic_close = False

    def _open_matched_window(self) -> None:
        if self._matched_win is None:
            self._matched_win = MatchedWindow()
            self._matched_win.closed.connect(self._on_matched_closed)
        self._matched_win.show()
        self._matched_win.raise_()

    def _render_matched_window(self) -> None:
        if self._matched_win is None:
            return
        self._matched_win.clear()
        for ts, direction, text in self._buffer:
            if self._filter.matched(text):
                self._matched_win.append_html(self._render_line(ts, direction, text))

    def _on_matched_closed(self) -> None:
        self._matched_win = None
        if self._programmatic_close:
            return  # 程序内切换模式关闭，不改模式
        idx = self.mode_combo.findData("highlight")
        if idx >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)
            self._filter.mode = "highlight"
            self._rerender()

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
            path = self._log_dir() / f"{_ts_name()}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            self._record_file = open(path, "a", encoding="utf-8")
            self.record_btn.setText("停止记录")
            self._sys(f"开始记录到: {path}")

    def save_log(self) -> None:
        default = str(self._log_dir() / f"{_ts_name()}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "保存串口日志", default, "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for ts, direction, text in self._buffer:
                    if self._filter.visible(text):
                        f.write(f"[{ts}] {self._dir_mark(direction)} {text}\n")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self._sys(f"日志已保存: {path}")

    def closeEvent(self, event) -> None:
        if self._record_file is not None:
            self._record_file.close()
            self._record_file = None
        if self._matched_win is not None:
            self._programmatic_close = True
            self._matched_win.close()
            self._programmatic_close = False
        self.serial.disconnect()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    win = SerialToolWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
