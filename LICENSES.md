# 许可证说明与合规指引

## 本项目许可证

OhmyPort 采用 **GPL-2.0** 许可证（见根目录 `LICENSE`）。

## 依赖及其许可证

| 依赖 | 许可证 | 与 GPL-2.0 兼容性 |
|---|---|---|
| pyserial | BSD-3-Clause | ✅ 兼容 |
| PySide6 | LGPL-3.0-only / GPL-2.0-only / GPL-3.0-only（三选一） | ✅ 可选 GPL-2.0-only，与项目一致 |
| pyqtgraph | MIT | ✅ 兼容 |
| pyqtdarktheme | MIT | ✅ 兼容 |
| Pillow | HPND（Historical Permission Notice and Disclaimer） | ✅ 兼容 |

## 兼容性结论

所有依赖均提供与 GPL-2.0 兼容的许可选项，其中 PySide6 可直接选择 **GPL-2.0-only**，因此 **当前项目以 GPL-2.0 整体发布不存在许可证冲突**。

## 使用场景指引

1. **仅公司内部员工使用（不分发 exe 给外部）**
   - GPL / LGPL 义务不触发，可直接使用、修改，无需公开源码。

2. **对外分发 exe 给客户**
   - **路径 A（开源合规）**：遵守 GPL-2.0，向接收方提供（或提供获取途径）本项目完整源码，并允许其再分发。
   - **路径 B（闭源）**：不能复用本项目 GPL-2.0 代码；需参考产品需求从零重写，依赖改用 MIT / Apache / BSD 许可，PySide6 选择 LGPL-3.0-only（需提供让用户替换 Qt 库的方式）。

> 以上为工程层面的许可梳理，正式对外发布前建议再由法务 / 负责人确认。
