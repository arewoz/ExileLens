"""Passive Companion analysis card.

The primary tooltip is the quick decision surface. This card is the detailed analysis
surface: axes, trade-offs, mod importance, the full current-item case, the upgrade path,
raw PoB before/after figures, coverage limits and diagnostics. It expands on the
tooltip's conclusion — it never repeats it.
"""

from __future__ import annotations

from typing import Any

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from poe2value.ui.styles import (
    OVERLAY_STYLESHEET,
    OVERLAY_WINDOW_BORDER_RGBA,
    OVERLAY_WINDOW_GRADIENT_BOTTOM,
    OVERLAY_WINDOW_GRADIENT_TOP,
)
from poe2value.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy

AUX_COMPANION_WIDTH = 300

# The card is a side panel, not a second tooltip: it stays bounded.
MAX_COMPANION_SECTIONS = 7
MAX_LINES_PER_SECTION = 6


class AuxEdgeCompanion(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("auxEdgeCompanion")
        if parent is None:
            apply_window_interaction_policy(self, WindowInteractionPolicy.PASSIVE_OVERLAY)
        self.setFixedWidth(AUX_COMPANION_WIDTH)
        self.setStyleSheet(OVERLAY_STYLESHEET)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(4)
        self._title = QLabel("DETAILED ANALYSIS")
        self._title.setObjectName("warningTitle")
        self._subtitle = QLabel("")
        self._subtitle.setObjectName("compactNote")
        self._subtitle.setWordWrap(True)
        self._subtitle.hide()
        root.addWidget(self._title)
        root.addWidget(self._subtitle)
        self._line_labels: list[QLabel] = []
        self._line_layout = root
        self._section_ids: list[str] = []
        self.hide()

    @property
    def section_ids(self) -> list[str]:
        """Ids of the analysis sections currently rendered — used by tests and tracing."""
        return list(self._section_ids)

    def is_alive(self) -> bool:
        """True while this widget and its permanent children still exist in C++.

        The companion is owned by the overlay. When that overlay is destroyed —
        including by garbage collection, which is how it happens in practice —
        Qt deletes the C++ children while Python wrappers survive. A queued
        signal or a late worker result can then still reach ``set_content``, and
        writing through a dangling wrapper raises from libshiboken or, outside a
        test, faults the process.

        ``shiboken6.isValid`` is the explicit validity check for exactly this.
        It is deliberately used instead of catching RuntimeError, which would
        also swallow unrelated programming errors.
        """
        if not shiboken6.isValid(self):
            return False
        return all(shiboken6.isValid(child) for child in (self._title, self._subtitle))

    def show(self) -> None:
        # Same dangling-wrapper class as set_content/clear: the overlay's layout
        # and positioning code also calls show()/hide() on the companion, and a
        # late call after destruction would fault rather than merely raise.
        if not self.is_alive():
            return
        super().show()

    def hide(self) -> None:
        if not self.is_alive():
            return
        super().hide()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.parent() is None:
            apply_native_extended_style(self, WindowInteractionPolicy.PASSIVE_OVERLAY)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(*OVERLAY_WINDOW_GRADIENT_TOP))
        gradient.setColorAt(1.0, QColor(*OVERLAY_WINDOW_GRADIENT_BOTTOM))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(*OVERLAY_WINDOW_BORDER_RGBA), 1))
        painter.drawPath(path)
        super().paintEvent(event)

    def clear(self) -> None:
        if not self.is_alive():
            # Destroyed with its owning overlay: drop the Python-side state so a
            # repeat call is still cheap, and touch no C++ object.
            self._line_labels.clear()
            self._section_ids.clear()
            return
        for label in self._line_labels:
            if not shiboken6.isValid(label):
                continue
            self._line_layout.removeWidget(label)
            label.deleteLater()
        self._line_labels.clear()
        self._section_ids.clear()
        self._subtitle.setText("")
        self._subtitle.hide()
        self.hide()

    def _add(self, text: str, *, object_name: str) -> None:
        if not self.is_alive():
            return
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._line_layout.addWidget(label)
        self._line_labels.append(label)

    def set_content(self, block: dict[str, Any]) -> None:
        """Render a companion payload.

        Accepts the detailed `{title, subtitle, sections:[{title, lines}]}` payload, and
        still accepts the older flat `{title, lines}` shape.
        """
        if not self.is_alive():
            # Late queued update after the owning overlay was destroyed. Nothing
            # to render into; returning is correct and must stay silent.
            return
        self.clear()
        block = block or {}
        sections = list(block.get("sections") or [])
        if not sections:
            lines = list(block.get("lines") or [])
            if not lines:
                return
            sections = [{"id": "lines", "title": str(block.get("title") or ""), "lines": lines}]

        self._title.setText(str(block.get("title") or "DETAILED ANALYSIS"))
        subtitle = str(block.get("subtitle") or "").strip()
        self._subtitle.setText(subtitle)
        self._subtitle.setVisible(bool(subtitle))

        rendered = 0
        for section in sections[:MAX_COMPANION_SECTIONS]:
            lines = [
                str(line.get("text") if isinstance(line, dict) else line).strip()
                for line in (section.get("lines") or [])
            ]
            lines = [line for line in lines if line]
            if not lines:
                continue
            title = str(section.get("title") or "").strip()
            if title:
                self._add(title, object_name="warningTitle")
            for line in lines[:MAX_LINES_PER_SECTION]:
                self._add(line, object_name="whyLabel")
            self._section_ids.append(str(section.get("id") or title))
            rendered += 1

        if not rendered:
            self.clear()
            return
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.adjustSize()
        self.setFixedHeight(self.height())
        self.show()
