"""Small interactive PIN affordance positioned beside the passive item overlay."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from poe2value.ui.styles import PIN_AFFORDANCE_STYLESHEET
from poe2value.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy


class OverlayPinControl(QWidget):
    pin_clicked = Signal()
    limit_reached = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._can_pin = True
        self.setObjectName("overlayPinControl")
        apply_window_interaction_policy(
            self,
            WindowInteractionPolicy.INTERACTIVE_PIN_AFFORDANCE,
            activate_on_show=False,
        )
        self.setStyleSheet(PIN_AFFORDANCE_STYLESHEET)
        self.setFixedSize(52, 26)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        self._button = QPushButton("PIN")
        self._button.setObjectName("pinAffordanceButton")
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setFlat(True)
        self._button.clicked.connect(self._on_click)
        layout.addWidget(self._button)
        self.hide()

    def set_can_pin(self, allowed: bool) -> None:
        self._can_pin = allowed
        self._button.setEnabled(allowed)
        self._button.setToolTip("" if allowed else "Maximum 4 pinned items.")

    def sync_to_overlay(self, overlay: QWidget) -> None:
        if not overlay.isVisible():
            self.hide()
            return
        frame = overlay.frameGeometry()
        x = frame.right() - self.width() + 4
        y = frame.top() + 10
        self.move(QPoint(int(x), int(y)))
        if not self.isVisible():
            self.show()
        self.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_PIN_AFFORDANCE)

    def _on_click(self) -> None:
        if not self._can_pin:
            self.limit_reached.emit()
            return
        self.pin_clicked.emit()
