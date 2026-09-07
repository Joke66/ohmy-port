"""OhmyPort 公共常量与纯逻辑工具（不依赖 Qt）。"""

from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path

_BAUDS = ["115200", "57600", "38400", "19200", "9600", "4800", "2400", "921600"]
_ENCODINGS = [("UTF-8", "utf-8"), ("GBK", "gbk"), ("ASCII", "ascii")]
_NEWLINES = [("无", ""), ("\\r", "\r"), ("\\n", "\n"), ("\\r\\n", "\r\n")]

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
_APP_VERSION = "1.4.1"
_APP_AUTHOR = "ShineZhang"
_APP_DATE = "2026-09-07"
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
