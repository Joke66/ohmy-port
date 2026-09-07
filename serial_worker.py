"""串口后端：独立线程接收，通过回调把数据抛给上层（UI 只做队列消费）。"""

from __future__ import annotations

import threading
import time

import serial
from serial.tools import list_ports

from common import _READ_CHUNK


class SerialMonitor:
    """自包含串口封装（字节流）：连接 / 批量接收 / 发送。"""

    def __init__(self):
        self._serial = None
        self._callback = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frame_parser = None
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

    def set_frame_parser(self, parser) -> None:
        """设置帧解析器后，接收按帧切分并回调 list[(frame, checksum_ok)]；置 None 恢复按行。"""
        self._frame_parser = parser

    def send(self, data: bytes) -> bool:
        if self._serial is None or not self._serial.is_open:
            return False
        try:
            self._serial.write(data)
            return True
        except Exception:
            return False

    def set_dtr(self, value: bool) -> None:
        if self._serial is not None:
            try:
                self._serial.dtr = value
            except Exception:
                pass

    def set_rts(self, value: bool) -> None:
        if self._serial is not None:
            try:
                self._serial.rts = value
            except Exception:
                pass

    def _receive_loop(self) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                if self._serial is not None and self._serial.is_open:
                    chunk = self._serial.read(_READ_CHUNK)
                    if not chunk:
                        continue
                    self.rx_bytes += len(chunk)
                    if self._frame_parser is not None:
                        frames = self._frame_parser.feed(chunk)
                        if frames and self._callback is not None:
                            self._callback(frames)  # list[(bytes, bool)]
                    else:
                        buf += chunk
                        *lines, buf = buf.split(b"\n")
                        if lines and self._callback is not None:
                            cleaned = [l[:-1] if l.endswith(b"\r") else l for l in lines]
                            self._callback([(l, True) for l in cleaned])
            except Exception:
                if self._stop.is_set():
                    break
                time.sleep(0.02)
