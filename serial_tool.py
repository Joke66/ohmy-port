"""串口工具（独立工具）：实时串口日志 + 多关键词过滤 + 时间戳保存。

独立于「老化板上位机」，可单独运行：
    python serial_tool.py

也可由主工具通过「打开串口工具」按钮拉起。自包含：仅依赖 pyserial + PySide6。

性能要点（实时性优化）：
- 接收线程用 read() 批量读 + 按 \\n 切分，一次性回调一批行；
- 主线程用 QTimer 定时 flush（默认 80ms），把一批行合成纯文本一次性 appendPlainText；
- 日志视图用 QPlainTextEdit（比 QTextEdit+HTML 快一个数量级）；
- 关键词高亮用 QPlainTextEdit 的 ExtraSelection（原生 C++ 查找，不逐行拼 HTML）；
- 历史行数封顶（环形 buffer + setMaximumBlockCount），内存恒定。
"""

from __future__ import annotations

import collections
import datetime
import queue
import sys
import threading
import time
from pathlib import Path

import serial
from serial.tools import list_ports

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

_BAUDS = ["115200", "57600", "38400", "19200", "9600", "4800", "2400"]
_HL_BG = QColor("#fff59d")  # 关键词高亮背景
_HL_FG = QColor("#000000")

# 性能参数
_MAX_LINES = 50_000      # 历史行数上限（环形缓冲）
_FLUSH_MS = 80           # UI 批量刷新间隔
_READ_CHUNK = 4096       # 串口批量读块大小
_HL_INTERVAL = 0.5       # 高亮重算节流（秒）


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
      - split     : 主视图显示全部，命中行同时在下栏单独展示
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
        return self.mode in ("highlight", "include", "split")


class SerialMonitor:
    """自包含的最小串口封装：连接 / 批量接收线程 / 发送。"""

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
                        decoded = [l.decode("ascii", errors="replace").rstrip("\r") for l in lines]
                        self._callback(decoded)  # 批量回调
            except Exception:
                if self._stop.is_set():
                    break


class SerialToolWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("串口工具")
        self.resize(900, 680)
        self.serial = SerialMonitor()
        self._filter = LogFilter()
        self._buffer: collections.deque = collections.deque(maxlen=_MAX_LINES)
        self._pending: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
        self._paused = False
        self._hex = False
        self._auto_scroll = True
        self._record_file = None
        self._last_highlight = 0.0
        self._build()
        self.serial.set_receive_callback(self._on_receive_batch)
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(_FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()
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
        self.mode_combo.addItem("上下分栏显示命中行", "split")
        self.mode_combo.currentIndexChanged.connect(self.apply_filter)
        filt.addWidget(self.mode_combo)
        self.case_check = QCheckBox("区分大小写")
        self.case_check.toggled.connect(self.apply_filter)
        filt.addWidget(self.case_check)
        filt.addWidget(self._btn("应用", self.apply_filter))
        layout.addLayout(filt)

        # 上：日志内容
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(_MAX_LINES)
        layout.addWidget(self.log_text, 3)

        # 下：命中结果面板（默认隐藏，分栏模式时显示）
        self.matched_panel = QWidget()
        mp = QVBoxLayout(self.matched_panel)
        mp.setContentsMargins(0, 6, 0, 0)
        mp.setSpacing(2)
        mp_bar = QHBoxLayout()
        mp_bar.addWidget(QLabel("命中结果"))
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_matched)
        mp_bar.addWidget(clear_btn)
        mp_bar.addStretch(1)
        mp.addLayout(mp_bar)
        self.matched_text = QPlainTextEdit()
        self.matched_text.setReadOnly(True)
        self.matched_text.setMaximumBlockCount(_MAX_LINES)
        mp.addWidget(self.matched_text)
        self.matched_panel.setVisible(False)
        layout.addWidget(self.matched_panel, 1)

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

    def _on_receive_batch(self, lines: list[str]) -> None:
        for line in lines:
            self._pending.put((_now(), "rx", line))

    def send_raw(self) -> None:
        data = self.send_edit.text()
        if not data:
            return
        if not self.serial.is_connected:
            self._sys("串口未打开，无法发送")
            return
        if self.serial.send(data):
            self._pending.put((_now(), "tx", data))
            self.send_edit.clear()

    # ---------- 日志 ----------
    def _sys(self, text: str) -> None:
        self._pending.put((_now(), "sys", text))

    def _dir_mark(self, d: str) -> str:
        return {"rx": "收←◆", "tx": "发→◇", "sys": "  ◆"}.get(d, "")

    def _format_line(self, ts: str, direction: str, text: str) -> str:
        if self._hex:
            body = " ".join(f"{b:02X}" for b in text.encode("ascii", errors="replace"))
        else:
            body = text
        return f"[{ts}] {self._dir_mark(direction)} {body}"

    def _flush(self) -> None:
        items: list[tuple[str, str, str]] = []
        while True:
            try:
                items.append(self._pending.get_nowait())
            except queue.Empty:
                break
        if not items:
            return
        pieces: list[str] = []
        matched_pieces: list[str] = []
        for ts, direction, text in items:
            if self._paused and direction != "sys":
                continue
            self._buffer.append((ts, direction, text))
            if self._record_file is not None:
                self._record_file.write(f"[{ts}] {self._dir_mark(direction)} {text}\n")
            if self._filter.visible(text):
                pieces.append(self._format_line(ts, direction, text))
            if self._filter.mode == "split" and self._filter.matched(text):
                matched_pieces.append(self._format_line(ts, direction, text))
        if pieces:
            self.log_text.appendPlainText("\n".join(pieces))
        if matched_pieces:
            self.matched_text.appendPlainText("\n".join(matched_pieces))
        if self._record_file is not None:
            self._record_file.flush()
        self._scroll()
        self._maybe_highlight()

    def _scroll(self) -> None:
        if self._auto_scroll:
            sb = self.log_text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _rerender(self) -> None:
        self.log_text.clear()
        pieces: list[str] = []
        for ts, direction, text in self._buffer:
            if self._filter.visible(text):
                pieces.append(self._format_line(ts, direction, text))
        if pieces:
            self.log_text.appendPlainText("\n".join(pieces))
        self._scroll()
        self._render_matched()
        self._apply_highlight(self.log_text)
        self._last_highlight = time.monotonic()

    def clear_log(self) -> None:
        self._buffer.clear()
        self.log_text.clear()
        self.matched_text.clear()

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText("继续" if self._paused else "暂停")
        if not self._paused:
            self._rerender()

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
        for ts, direction, text in self._buffer:
            if self._filter.matched(text):
                pieces.append(self._format_line(ts, direction, text))
        if pieces:
            self.matched_text.appendPlainText("\n".join(pieces))
        self._apply_highlight(self.matched_text)

    def _clear_matched(self) -> None:
        self.matched_text.clear()

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
        self._flush_timer.stop()
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
