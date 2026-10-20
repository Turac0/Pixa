"""Inline SVG icons (stroke style, 24x24) tinted to the current theme."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
    '<path d="M7 3v5h8V3"/><rect x="7" y="13" width="10" height="8" rx="1"/>',
    "print": '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/>'
    '<path d="M7 14h10v7H7z"/>',
    "preview": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/>'
    '<circle cx="12" cy="12" r="3"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>',
    "select": '<path d="m4 4 7 17 2.5-7.5L21 11z"/>',
    "edit-text": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "add-text": '<path d="M5 6V4h14v2"/><path d="M12 4v16"/><path d="M9 20h6"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/>'
    '<path d="m21 15-5-5L5 21"/>',
    "highlight": '<path d="m9 11-6 6v3h9l3-3"/>'
    '<path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/>',
    "box": '<rect x="3.5" y="5.5" width="17" height="13" rx="1"/>',
    "rotate-left": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "rotate-right": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "delete": '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/>'
    '<path d="M10 11v6M14 11v6"/>',
    "zoom-in": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M11 8v6M8 11h6"/>',
    "zoom-out": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M8 11h6"/>',
    "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "insert-pdf": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
    '<path d="M14 3v6h6"/><path d="M12 12v6M9 15h6"/>',
    "blank-page": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
    '<path d="M14 3v6h6"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
    '<path d="M14 3v6h6"/><path d="M8 13h8M8 17h5"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "chevron-up": '<path d="M6 15l6-6 6 6"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "minus": '<path d="M6 12h12"/>',
    "plus": '<path d="M12 6v12M6 12h12"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5" stroke-width="2.6"/>',
    "dot": '<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',
    "theme": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
    'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
}

_cache: dict[tuple[str, str], QIcon] = {}


def svg(name: str, color: str, opacity: float = 1.0) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-opacity="{opacity}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{_PATHS[name].replace('currentColor', color)}</svg>"
    ).encode()


def pixmap(name: str, color: str, size: int = 48, opacity: float = 1.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg(name, color, opacity)))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QPixmap.fromImage(image)


def icon(name: str, color: str, active_color: str | None = None) -> QIcon:
    key = (name, color + (active_color or ""))
    if key not in _cache:
        ic = QIcon()
        ic.addPixmap(pixmap(name, color), QIcon.Mode.Normal, QIcon.State.Off)
        ic.addPixmap(pixmap(name, active_color or color), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(pixmap(name, color, opacity=0.35), QIcon.Mode.Disabled)
        _cache[key] = ic
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()


def app_icon_image(size: int) -> QImage:
    """The Pixa logo: a white document on a rounded blue gradient square."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.06
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0, QColor("#6d84ff"))
    grad.setColorAt(1, QColor("#3f55d6"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, size * 0.22, size * 0.22)
    inset = size * 0.22
    QSvgRenderer(QByteArray(svg("file", "#ffffff"))).render(
        p, QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    )
    p.end()
    return image


def app_icon() -> QIcon:
    ic = QIcon()
    for size in (16, 32, 64, 128, 256):
        ic.addPixmap(QPixmap.fromImage(app_icon_image(size)))
    return ic
