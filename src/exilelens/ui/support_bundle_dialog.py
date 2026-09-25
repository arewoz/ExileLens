"""Review dialog before exporting a local support bundle."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class SupportBundleReviewDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Support Bundle")
        layout = QVBoxLayout(self)
        body = QLabel(
            "This ZIP stays on your computer until you choose to share it.\n\n"
            "Included:\n"
            "• Extended diagnostic summary (versions, health, update status)\n"
            "• Sanitized diagnostic event history\n"
            "• Optional reproduction notes you entered\n"
            "• Sanitized tail of the application log\n\n"
            "Not included: clipboard text, build XML, raw paths, tokens, or automatic uploads."
        )
        body.setWordWrap(True)
        layout.addWidget(body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
