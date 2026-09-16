"""Compact Tree Coach legend. Colors come from centralized heatmap bands."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from poe2value.tree.heatmap import BAND_FILL_HEX, BAND_LABEL
from poe2value.tree.models import HeatmapBand


class _Swatch(QWidget):
    def __init__(self, color: str, kind: str = "dot", parent=None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._kind = kind
        self.setFixedSize(14, 14)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(QColor("#1a1814"))
        if self._kind == "star":
            painter.drawEllipse(1, 1, 12, 12)
            painter.setPen(QColor("#ffd27a"))
            painter.drawEllipse(3, 3, 8, 8)
        elif self._kind == "diamond":
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QPolygon

            painter.setBrush(QColor("#7dcf7d"))
            painter.drawPolygon(QPolygon([QPoint(7, 1), QPoint(13, 7), QPoint(7, 13), QPoint(1, 7)]))
        elif self._kind == "alloc":
            painter.setBrush(QColor("#e8dcc4"))
            painter.setPen(QColor("#f6edd4"))
            painter.drawEllipse(1, 1, 12, 12)
        else:
            painter.drawEllipse(1, 1, 12, 12)


class TreeLegendWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(10)
        order = [
            HeatmapBand.UNKNOWN,
            HeatmapBand.LOW,
            HeatmapBand.USEFUL,
            HeatmapBand.HIGH,
            HeatmapBand.EXCEPTIONAL,
        ]
        for band in order:
            row.addWidget(_Swatch(BAND_FILL_HEX[band]))
            label = QLabel(BAND_LABEL[band])
            label.setObjectName("compactNote")
            row.addWidget(label)
        row.addWidget(_Swatch("#e8dcc4", "alloc"))
        alloc = QLabel("Allocated")
        alloc.setObjectName("compactNote")
        row.addWidget(alloc)
        row.addWidget(_Swatch("#ffd27a", "star"))
        best = QLabel("Best Next Point")
        best.setObjectName("compactNote")
        row.addWidget(best)
        row.addWidget(_Swatch("#7dcf7d", "diamond"))
        brk = QLabel("Breakpoint")
        brk.setObjectName("compactNote")
        row.addWidget(brk)
        row.addStretch(1)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
