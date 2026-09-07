"""日志管理：记录文件打开/写入/轮转/关闭，以及日志目录保留清理。"""

from __future__ import annotations

import datetime
import re
import time
from pathlib import Path

from common import _LOG_RETENTION_DAYS


class LogManager:
    """单个会话的记录文件管理 + 日志目录保留清理。"""

    def __init__(self):
        self._stem = "serial"
        self._file = None
        self._path = ""
        self.error = ""

    @property
    def is_open(self) -> bool:
        return self._file is not None

    def open(self, stem: str, log_dir: Path) -> str | None:
        """以端口名 stem 打开新记录文件，成功返回路径，失败返回 None。"""
        self._stem = re.sub(r"[^0-9A-Za-z_-]", "_", stem) or "serial"
        name = f"{self._stem}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path = Path(log_dir) / name
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "a", encoding="utf-8")
            self._path = str(path)
            self.error = ""
            return self._path
        except OSError as exc:
            self._file = None
            self._path = ""
            self.error = str(exc)
            return None

    def write(self, line: str) -> None:
        """写一行；异常时记录错误并关闭（磁盘满/权限）。"""
        if self._file is None:
            return
        try:
            self._file.write(line + "\n")
        except OSError as exc:
            self.error = str(exc)
            self.close()

    def flush(self, shard_mb: int, log_dir: Path) -> None:
        """刷新并检查大小，超限自动分片；异常时记录错误并关闭。"""
        if self._file is None:
            return
        try:
            self._file.flush()
            if self._file.tell() >= shard_mb * 1024 * 1024:
                self.rotate(log_dir)
        except OSError as exc:
            self.error = str(exc)
            self.close()

    def rotate(self, log_dir: Path) -> None:
        self.close()
        self.open(self._stem, log_dir)

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        self._file = None
        self._path = ""

    @staticmethod
    def clean_old_logs(log_dir: Path, retention: str) -> None:
        days = _LOG_RETENTION_DAYS.get(retention, 0)
        if not days or not Path(log_dir).is_dir():
            return
        cutoff = time.time() - days * 86400
        try:
            for f in Path(log_dir).glob("*.txt"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError:
                    pass
        except OSError:
            pass
