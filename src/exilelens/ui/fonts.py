"""Bundled UI fonts.

Spectral is used only for the build name on the Overview page. Font files are read from ``assets/fonts``
(shipped inside the package, never downloaded at runtime). When they are absent the build-name font stack falls
through to Georgia, so the page looks right either way.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

from exilelens.ui.ui_icons import _asset_roots

_FONT_DIR = Path("assets") / "fonts"
_registered: list[str] | None = None


def font_files() -> list[Path]:
    for root in _asset_roots():
        folder = root / _FONT_DIR
        if folder.is_dir():
            found = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".ttf", ".otf"))
            if found:
                return found
    return []


def register_bundled_fonts() -> list[str]:
    """Register every bundled font with Qt once; returns the families that loaded."""
    global _registered
    if _registered is not None:
        return _registered
    families: list[str] = []
    for path in font_files():
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            for family in QFontDatabase.applicationFontFamilies(font_id):
                if family not in families:
                    families.append(family)
    _registered = families
    return families
