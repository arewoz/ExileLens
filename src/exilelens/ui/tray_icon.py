from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from exilelens.branding import app_icon


def create_tray_icon() -> QIcon:
    """Return the ExileLens tray icon.

    Uses the packaged multi-resolution artwork when it is available and falls
    back to a painted glyph so a missing asset never leaves an empty tray.
    """
    packaged = app_icon()
    if packaged is not None:
        return packaged
    return _painted_fallback_icon()


def _painted_fallback_icon() -> QIcon:
    """Multi-size painted glyph, visible on light and dark Windows taskbars."""
    icon = QIcon()
    for size in (16, 32):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = max(1, size // 16)
        rect = margin, margin, size - 2 * margin, size - 2 * margin

        painter.setBrush(QColor("#E8A317"))
        painter.setPen(QColor("#1A1A1A"))
        painter.drawEllipse(*rect)

        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(7, size // 2))
        painter.setFont(font)
        painter.setPen(QColor("#1A1A1A"))
        label = "P2" if size >= 24 else "P"
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, label)

        painter.end()
        icon.addPixmap(pixmap)

    return icon
