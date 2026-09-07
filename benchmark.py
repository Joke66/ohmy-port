"""串口工具吞吐压测（离屏）：模拟高频 RX，测处理速率与实时保持能力。

用法：python benchmark.py
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from common import _MAX_LINES  # noqa: E402
from serial_tool import SerialToolWindow  # noqa: E402

LINE = "ERR 0x50 temp=25.3 volt=12.00 status=OK"


def bench_burst(win, total=100_000, batch_size=200, highlight=False):
    """模拟串口回调 → 队列 → UI 刷新，测量整条处理链路的吞吐。"""
    s = win.active_session()
    if highlight:
        # 模拟关键词高亮场景：多关键词、区分大小写关闭
        s._filter.keywords = ["ERR", "temp", "OK"]
        s._filter.mode = "highlight"
        s._filter.case_sensitive = False
    batch = [(LINE.encode(), True)] * batch_size
    t0 = time.time()
    for _ in range(total // batch_size):
        s._on_receive_batch(batch)
        s._flush()
    dt = time.time() - t0
    return total, dt


def report(label, total, dt):
    rate = total / dt if dt > 0 else float("inf")
    print(f"{label:<22} {total:>9,} 行 / {dt:7.3f}s = {rate:>10,.0f} 行/秒")
    return rate


def main():
    app = QApplication([])

    print("=" * 62)
    print("串口工具吞吐压测（离屏，PYTHON + PySide6 渲染链路）")
    print("=" * 62)
    win = SerialToolWindow()

    r_plain = report("普通显示", *bench_burst(win, highlight=False))
    r_hl = report("关键词高亮", *bench_burst(win, highlight=True))

    win._force_quit = True  # 避免离屏环境触发关闭确认弹窗而阻塞
    win.close()
    print(f"历史上限：{_MAX_LINES:,} 行（环形缓冲，内存恒定）")
    print("-" * 62)
    print("对照（8N1，每行约 30 字节）：")
    for baud, label in [(115200, "115200"), (460800, "460800"), (921600, "921600")]:
        lines_s = (baud / 10) / 30
        print(f"  {label:>6} ≈ {lines_s:>8,.0f} 行/秒  →  普通富余 {r_plain / lines_s:>6,.0f}x"
              f"  高亮富余 {r_hl / lines_s:>6,.0f}x")
    print("=" * 62)


if __name__ == "__main__":
    main()
