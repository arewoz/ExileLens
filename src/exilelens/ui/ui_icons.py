"""Bundled vector icons for dashboard and tray actions."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap

from exilelens.ui.styles import clamp_ui_scale

_ICON_DIR = Path("assets") / "ui"
_ICON_FILES = {
    "discord": "discord.svg",
    "github": "github.svg",
    "download": "download.svg",
}


def _asset_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.append(Path(bundle))
    # src/exilelens/ui/ui_icons.py -> repo root
    roots.append(Path(__file__).resolve().parents[3])
    exe_dir = Path(sys.executable).resolve().parent
    roots.append(exe_dir)
    roots.append(exe_dir.parent)
    return tuple(roots)


def icon_path(name: str) -> Path | None:
    filename = _ICON_FILES.get(name)
    if filename is None:
        return None
    for root in _asset_roots():
        candidate = root / _ICON_DIR / filename
        if candidate.is_file():
            return candidate
    return None


def _icon_from_svg(path: Path) -> QIcon | None:
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return None
    icon = QIcon()
    for side in (16, 20, 24, 32):
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return None if icon.isNull() else icon


@lru_cache(maxsize=len(_ICON_FILES))
def load_icon(name: str) -> QIcon | None:
    path = icon_path(name)
    if path is None:
        return None
    if path.suffix.lower() == ".svg":
        return _icon_from_svg(path)
    icon = QIcon(str(path))
    return None if icon.isNull() else icon


def icon_pixel_size(ui_scale: float = 1.0) -> int:
    return max(14, int(round(16 * clamp_ui_scale(ui_scale))))


def icon_size(ui_scale: float = 1.0) -> QSize:
    side = icon_pixel_size(ui_scale)
    return QSize(side, side)


def apply_button_icon(button, name: str, *, ui_scale: float = 1.0) -> None:
    icon = load_icon(name)
    if icon is None:
        return
    button.setIcon(icon)
    button.setIconSize(icon_size(ui_scale))


def apply_action_icon(action, name: str, *, ui_scale: float = 1.0) -> None:
    icon = load_icon(name)
    if icon is None:
        return
    action.setIcon(icon)
    action.setIconVisibleInMenu(True)
