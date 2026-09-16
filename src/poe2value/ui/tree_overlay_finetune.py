"""Fine-tune transform without typing matrices."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from poe2value.tree.calibration_session import CalibrationSession
from poe2value.ui.window_policy import WindowInteractionPolicy, apply_window_interaction_policy


class OverlayFineTuneDialog(QDialog):
    def __init__(self, session: CalibrationSession, on_change, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_TOOL, activate_on_show=True)
        self.setWindowTitle("Fine Tune Overlay")
        self._session = session
        self._on_change = on_change
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Every click redraws BUILD PATH immediately."))
        layout.addLayout(self._row("X", [(-10, "-10"), (-1, "-1"), (1, "+1"), (10, "+10")], "x"))
        layout.addLayout(self._row("Y", [(-10, "-10"), (-1, "-1"), (1, "+1"), (10, "+10")], "y"))
        layout.addLayout(self._row("Scale", [(-0.01, "-1%"), (-0.001, "-0.1%"), (0.001, "+0.1%"), (0.01, "+1%")], "s"))
        done = QPushButton("Looks Good")
        done.clicked.connect(self.accept)
        layout.addWidget(done)

    def _row(self, title: str, steps: list[tuple[float, str]], axis: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        for value, label in steps:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, v=value, a=axis: self._nudge(a, v))
            row.addWidget(btn)
        return row

    def _nudge(self, axis: str, value: float) -> None:
        if axis == "x":
            self._session.nudge(ddx=value)
        elif axis == "y":
            self._session.nudge(ddy=value)
        else:
            self._session.nudge(dscale=value)
        self._on_change()
