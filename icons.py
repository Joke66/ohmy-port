"""OhmyPort 内嵌 SVG 图标集（无第三方图标库依赖）。

每个图标是 24×24 viewBox 的单色线性 SVG；颜色由调用方按主题前景色注入，
渲染为带 2x 高分屏的 QIcon。主题切换时调用方负责用新颜色重建图标。
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 名称 → SVG 路径内容（fill=none，stroke 使用 {c} 占位，由 make_icon 注入颜色）
_SVG: dict[str, str] = {
    # 串口 / 会话
    "add": '<path d="M12 5v14M5 12h14"/>',
    "port": (
        '<rect x="6" y="2.5" width="12" height="7" rx="2"/>'
        '<path d="M9 9.5v3M15 9.5v3M9 16.5c0-1.5 1.2-2.5 3-2.5s3 1 3 2.5"/>'
        '<path d="M8 19.5h8M9.5 21.5h5"/>'
    ),
    # 文件
    "save": (
        '<path d="M5 3h11l4 4v14H5z"/>'
        '<path d="M8 3v5h7V3"/>'
        '<path d="M8 14h8v7H8z"/>'
    ),
    "folder": '<path d="M3 6h6l2 2h10v11H3z"/>',
    "export": '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 20h16"/>',
    "import": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 20h16"/>',
    "quit": '<path d="M5 4h6M5 20h6M11 4v16"/><path d="M14 8l4 4-4 4"/>',
    # 视图 / 面板开关
    "sliders": (
        '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/>'
        '<circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>'
    ),
    "send": '<path d="M4 12l16-7-6 16-2-6z"/><path d="M12 15l8-10"/>',
    "reply": '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a6 6 0 0 1 0 12h-4"/>',
    "hex": '<path d="M8 6l-3 12M16 6l3 12M8 12h8M6.5 10h-1M6.5 14h-1M18.5 10h-1M18.5 14h-1"/>',
    "chart": '<path d="M4 20V4M4 20h16"/><path d="M8 16l4-6 3 3 5-8"/>',
    "wrap": '<path d="M4 7h16M4 12h16M4 17h9"/><path d="M17 15v6M14.5 18.5L17 21l2.5-2.5"/>',
    # 设置 / 日志
    "palette": (
        '<path d="M12 3a9 9 0 0 0 0 18h2c1.5 0 2-1 2-2 0-1.4-1-2-1-3.2 0-1 .8-1.8 1.8-1.8H18A3 3 0 0 0 21 11a8 8 0 0 0-9-8z"/>'
        '<circle cx="7.5" cy="10" r="1"/><circle cx="10.5" cy="6.8" r="1"/>'
        '<circle cx="14.5" cy="6.8" r="1"/><circle cx="17" cy="10" r="1"/>'
    ),
    "font": '<path d="M4 19L10 5h4l6 14"/><path d="M8 14h8"/><path d="M7 19h10"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5"/>',
    "filter": '<path d="M4 5h16l-6 7v5l-4 2v-7z"/>',
    "message": '<path d="M21 11.5a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5z"/><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01"/>',
    "convert": '<path d="M7 8h12M15 4l4 4-4 4"/><path d="M17 16H5M9 12l-4 4 4 4"/>',
    "shard": '<path d="M4 4h16v6H4z"/><rect x="4" y="14" width="16" height="6" rx="1"/>',
    "retention": '<path d="M12 4a8 8 0 1 1 0 16"/><path d="M12 8v4l3 2"/>',
    "tray": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M12 8v6M9 11l3 3 3-3"/>',
    "question": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.6 2.6 0 1 1 4 2.1c-1 .7-1.5 1.2-1.5 2.4"/><circle cx="12" cy="17" r="0.6" fill="{c}"/>',
    "update": '<path d="M20 12a8 8 0 1 1-3-6.2"/><path d="M20 3v5h-5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="8" r="0.8" fill="{c}"/>',
    # 会话操作
    "pause": '<path d="M9 6v12M15 6v12"/>',
    "clear": '<path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13"/>',
    "record": '<circle cx="12" cy="12" r="4" fill="{c}"/>',
    "fixed": '<path d="M12 4v16M7 8l-3 4 3 4M17 8l3 4-3 4"/>',
}

_cache: dict[tuple[str, str, int], QIcon] = {}


def make_icon(name: str, color: str, size: int = 18) -> QIcon:
    """按名称 + 前景色渲染图标；结果带缓存。"""
    key = (name, color.lower(), size)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    svg = _SVG.get(name)
    if not svg:
        return QIcon()
    body = svg.format(c=color)
    data = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        'fill="none" stroke="{c}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        + body + "</svg>"
    ).replace("{c}", color)
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    dpr = 2.0  # 高分屏 2x
    img = QImage(int(size * dpr), int(size * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    icon = QIcon(pm)
    _cache[key] = icon
    return icon


def set_action_icon(action, name: str, color: str, size: int = 18) -> None:
    """为 QAction 设置图标（供菜单 / 工具栏复用）。"""
    action.setIcon(make_icon(name, color, size))
