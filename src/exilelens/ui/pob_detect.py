"""Shared UI action: detect Path of Building automatically (bounded, local; see pob_discovery)."""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget


def detect_pob_path(parent: QWidget | None, *, notify_none: bool = True) -> str | None:
    """One clear installation is returned, several are offered in a chooser, none returns None.

    Validation is the existing PoB2 boundary inside discovery; callers decide whether to save the path.
    """
    from exilelens.pob_discovery import find_pob_installation

    result = find_pob_installation()
    chosen = result.selected
    if chosen is None and result.ambiguous:
        labels = [candidate.display() for candidate in result.ambiguous]
        label, accepted = QInputDialog.getItem(
            parent, "Path of Building", "Multiple Path of Building installations were found:", labels, 0, False
        )
        if not accepted:
            return None
        chosen = result.ambiguous[labels.index(label)]
    if chosen is None:
        if notify_none:
            QMessageBox.information(
                parent,
                "Path of Building",
                "Path of Building could not be detected automatically. Use Browse to choose its installation folder.",
            )
        return None
    return str(chosen.path)
