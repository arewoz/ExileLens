"""One-time PoE2 league picker.

MARKET-01B10. When live market search cannot work out which league to search, the app
asks the user once instead of showing a dead end. The answer is persisted, so this
dialog is not expected to appear again.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from exilelens.price_check.league_resolver import SAVED_LEAGUE_STALE


class LeagueSelectionDialog(QDialog):
    """Modal league picker. `selected_league()` is valid once the dialog is accepted."""

    def __init__(
        self,
        leagues,
        *,
        current: str = "",
        failure_code: str = "",
        stale_league: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select PoE2 league")
        self.setModal(True)
        self.setMinimumWidth(360)

        self._leagues = [str(row) for row in (leagues or []) if str(row).strip()]

        root = QVBoxLayout(self)

        if stale_league or failure_code == SAVED_LEAGUE_STALE:
            headline = QLabel(
                f"Your saved league “{stale_league}” is no longer available.\n"
                "Choose a current league."
                if stale_league
                else "Your saved league is no longer available.\nChoose a current league."
            )
        else:
            headline = QLabel(
                "Live market search needs to know which league to look in.\n"
                "This is asked once and remembered."
            )
        headline.setWordWrap(True)
        root.addWidget(headline)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for name in self._leagues:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._list.addItem(item)
        root.addWidget(self._list, 1)

        if not self._leagues:
            empty = QLabel(
                "The league list could not be loaded (the trade service may be rate "
                "limited). Try again in a minute, or set the league in "
                "Settings → Market."
            )
            empty.setWordWrap(True)
            root.addWidget(empty)

        self._select_current(current)
        self._list.itemDoubleClicked.connect(lambda _item: self._accept())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Use this league")
        ok.setEnabled(self._list.currentRow() >= 0)
        self._list.currentRowChanged.connect(lambda row: ok.setEnabled(row >= 0))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _select_current(self, current: str) -> None:
        cleaned = str(current or "").strip().lower()
        if cleaned:
            for row in range(self._list.count()):
                if self._list.item(row).text().strip().lower() == cleaned:
                    self._list.setCurrentRow(row)
                    return
        # Default to the first entry, which the catalog orders as the active league.
        if self._list.count():
            self._list.setCurrentRow(0)

    def _accept(self) -> None:
        if self._list.currentRow() < 0:
            return
        self.accept()

    def selected_league(self) -> str:
        item = self._list.currentItem()
        return item.text() if item is not None else ""


def prompt_for_league(
    leagues,
    *,
    current: str = "",
    failure_code: str = "",
    stale_league: str = "",
    parent=None,
) -> str | None:
    """Show the picker and return the chosen league, or None if the user cancelled."""
    dialog = LeagueSelectionDialog(
        leagues,
        current=current,
        failure_code=failure_code,
        stale_league=stale_league,
        parent=parent,
    )
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        chosen = dialog.selected_league().strip()
        return chosen or None
    finally:
        dialog.deleteLater()
