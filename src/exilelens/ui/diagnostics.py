from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout

from exilelens.app.controller import EvaluationController
from exilelens.app.settings import AppSettings


class DiagnosticsWindow(QDialog):
    def __init__(self, controller: EvaluationController, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.setWindowTitle("Diagnostics")
        self.resize(520, 400)

        layout = QVBoxLayout(self)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        layout.addWidget(self._text)

        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        copy_btn = QPushButton("Copy Diagnostic Report")
        copy_btn.clicked.connect(self._copy_report)
        row.addWidget(refresh)
        row.addWidget(copy_btn)
        row.addStretch()
        layout.addLayout(row)

        self.refresh()

    def refresh(self) -> None:
        self._text.setPlainText(self.controller.diagnostic_report())

    def _copy_report(self) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(self._text.toPlainText())
