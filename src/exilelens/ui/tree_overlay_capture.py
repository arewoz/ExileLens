"""Interactive calibration capture layer over the PoE client area.

INTERACTIVE_TRANSPARENT_CAPTURE: PoE tree stays 100% visible during capture.
Only a small edge instruction banner is painted; no full-area veil or dim layer.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from exilelens.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy

# Unit tests assert this stays False — no opaque/black full-area fill.
USES_FULL_AREA_VEIL = False


class CalibrationCaptureOverlay(QWidget):
    clicked_client = Signal(float, float)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_window_interaction_policy(
            self,
            WindowInteractionPolicy.INTERACTIVE_TRANSPARENT_CAPTURE,
            activate_on_show=True,
        )
        self.setWindowTitle("Tree Overlay Capture")
        self._prompt = "Click the node on the PoE passive tree."
        self._crosshair: tuple[float, float] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._banner = QWidget(self)
        self._banner.setObjectName("captureBanner")
        self._banner.setStyleSheet(
            "QWidget#captureBanner { background: rgba(18, 16, 14, 200); border-bottom: 1px solid rgba(255,220,80,120); }"
        )
        banner_layout = QVBoxLayout(self._banner)
        banner_layout.setContentsMargins(16, 10, 16, 10)
        self._label = QLabel(self._prompt)
        self._label.setStyleSheet("color: #fff6dc; font-size: 16px; font-weight: 700; background: transparent;")
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        cancel = QPushButton("Cancel (Esc)")
        cancel.clicked.connect(self._cancel)
        cancel.setFixedWidth(160)
        banner_layout.addWidget(self._label)
        banner_layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self._banner, alignment=Qt.AlignmentFlag.AlignTop)
        root.addStretch(1)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_TRANSPARENT_CAPTURE)
        self.grabKeyboard()
        self.setFocus()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.releaseKeyboard()
        self._crosshair = None
        super().hideEvent(event)

    def set_prompt(self, text: str) -> None:
        self._prompt = text
        self._label.setText(text + "\n\nEsc cancels.")
        self.update()

    def bind_client_rect(self, rect: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = rect
        self.setGeometry(int(x0), int(y0), max(64, int(x1 - x0)), max(64, int(y1 - y0)))

    def paintEvent(self, event) -> None:  # noqa: N802
        # Transparent capture: optional crosshair only — never a full-area veil.
        if self._crosshair is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self._crosshair
        pen = QPen(QColor(255, 220, 80, 220), 2)
        painter.setPen(pen)
        size = 14.0
        painter.drawLine(int(cx - size), int(cy), int(cx + size), int(cy))
        painter.drawLine(int(cx), int(cy - size), int(cx), int(cy + size))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        self._crosshair = (float(pos.x()), float(pos.y()))
        self.update()
        self.clicked_client.emit(float(pos.x()), float(pos.y()))
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.hide()
        self.releaseKeyboard()
