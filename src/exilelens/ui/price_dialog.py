from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from exilelens.items.price import SUPPORTED_CURRENCIES


class PriceDialog(QDialog):
    def __init__(self, item_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Price for Last Item")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(item_name or "Last evaluated item"))
        form = QFormLayout()
        self._amount = QDoubleSpinBox()
        self._amount.setDecimals(2)
        self._amount.setMinimum(0.01)
        self._amount.setMaximum(1_000_000)
        self._amount.setValue(1.0)
        self._currency = QComboBox()
        self._currency.setEditable(True)
        self._currency.addItems(list(SUPPORTED_CURRENCIES))
        self._currency.setCurrentText("Divine")
        form.addRow("Amount:", self._amount)
        form.addRow("Currency:", self._currency)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addLayout(buttons)

    def amount(self) -> float:
        return float(self._amount.value())

    def currency(self) -> str:
        return self._currency.currentText().strip()
