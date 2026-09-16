from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget


def pick_build_file(current: str = "") -> str:
    start = str(Path(current).parent) if current else ""
    path, _ = QFileDialog.getOpenFileName(
        None,
        "Select Path of Building 2 build XML",
        start,
        "PoB Build (*.xml);;All Files (*)",
    )
    return path or ""


def pick_pob_directory(current: str = "") -> str:
    path = QFileDialog.getExistingDirectory(
        None,
        "Select Path of Building Community (PoE2) installation",
        current or "",
    )
    return path or ""
