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

from serial_tool import SerialToolWindow, _MAX_LINES  # noqa: E402

LINE = "ERR 0x50 temp=25.3 volt=12.00 status=OK"


def burst_throughput(app, total=100_000, batch_size=200):
    win = SerialToolWindow()
    batch = [LINE] * batch_size
    t0 = time.time()
    for _ in range(total // batch_size):
        win._on_receive_batch(batch)
        win._flush()
    dt = time.time() - t0
    win.close()
    return total, dt


def main():
    app = QApplication([])

    total, dt = burst_throughput(app)
    rate = total / dt
    print("=" * 56)
    print("串口工具吞吐压测（离屏）")
    print("=" * 56)
    print(f"突发吞吐：{total:,} 行 / {dt:.3f}s = {rate:,.0f} 行/秒")
    print(f"历史上限：{_MAX_LINES:,} 行（环形缓冲，内存恒定）")
    print("-" * 56)
    print("对照（8N1，每行约 30 字节）：")
    for baud, label in [(115200, "115200"), (460800, "460800"), (921600, "921600")]:
        bps = baud / 10
        lines_s = bps / 30
        print(f"  {label:>6} ≈ {lines_s:,.0f} 行/秒  →  富余 {rate / lines_s:,.0f}x")
    print("=" * 56)


if __name__ == "__main__":
    main()
