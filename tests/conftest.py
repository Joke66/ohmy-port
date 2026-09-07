import sys
from pathlib import Path

# 让测试能 import 项目根目录下的 serial_tool
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
