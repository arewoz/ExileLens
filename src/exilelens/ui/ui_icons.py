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
    "patreon": "patreon.svg",
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


# --- secondary outline family ---------------------------------------------------------
#
# Heroicons outline (MIT, https://heroicons.com), 24px grid, stroke 1.75 -- the same family
# the shipped ``download.svg`` belongs to. Used only where a control genuinely needs an icon
# (the 64px compact rail, the refresh action, the warning / failure glyphs). Branded marks
# (Patreon, Discord, GitHub) always come from ``assets/ui`` unchanged.
_OUTLINE_PATHS = {
    "home": "m2.25 12 8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25",
    "chart": "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z",
    "cog": "M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
    "pulse": "M3 12h3.5l2.5-6.5 4 13 2.5-6.5H21",
    "check": "m4.5 12.75 6 6 9-13.5",
    "warn": "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z",
    "xc": "m9.75 9.75 4.5 4.5m0-4.5-4.5 4.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
    "refresh": "M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99",
    "chevd": "m19.5 8.25-7.5 7.5-7.5-7.5",
    "chevr": "m8.25 4.5 7.5 7.5-7.5 7.5",
    "x": "M6 18 18 6M6 6l12 12",
}


@lru_cache(maxsize=256)
def outline_icon(name: str, color: str = "#c4c0b6", size: int = 20) -> QIcon:
    """A coloured outline icon from the secondary family. Empty QIcon for an unknown name."""
    path_data = _OUTLINE_PATHS.get(name)
    if path_data is None:
        return QIcon()
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="{path_data}"/></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    icon = QIcon()
    for side in sorted({size, size * 2}):
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
