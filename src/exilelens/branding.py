"""Canonical product identity for the application.

The product is presented to users as **ExileLens**. See ``docs/BRANDING.md`` for
legacy identifiers kept for migration and external compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: User-facing product name. Use this instead of hard-coded strings.
APP_NAME = "ExileLens"

#: Windows AppUserModelID — keeps taskbar grouping and the pinned-shortcut icon
#: attached to ExileLens rather than to the host python.exe.
APP_USER_MODEL_ID = "ExileLens.App"

#: Basename (no extension) of the packaged Windows executable.
EXE_BASENAME = "ExileLens"

_ICON_RELATIVE = Path("assets") / "app"
_ICON_PNG_NAME = "exilelens.png"
_ICON_ICO_NAME = "exilelens.ico"


def window_title(context: str | None = None) -> str:
    """``"ExileLens"``, or ``"ExileLens — <context>"`` for a contextual window."""
    if not context:
        return APP_NAME
    return f"{APP_NAME} — {context}"


def _asset_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        roots.append(Path(bundle))
    # src/exilelens/branding.py -> repo root
    roots.append(Path(__file__).resolve().parents[2])
    exe_dir = Path(sys.executable).resolve().parent
    roots.append(exe_dir)
    roots.append(exe_dir.parent)
    return tuple(roots)


def _find_icon(name: str) -> Path | None:
    for root in _asset_roots():
        candidate = root / _ICON_RELATIVE / name
        if candidate.is_file():
            return candidate
    return None


def icon_png_path() -> Path | None:
    """Absolute path to the high-resolution source PNG, if bundled."""
    return _find_icon(_ICON_PNG_NAME)


def icon_ico_path() -> Path | None:
    """Absolute path to the multi-resolution Windows ICO, if bundled."""
    return _find_icon(_ICON_ICO_NAME)


def app_icon():
    """Return a ``QIcon`` for the product, or ``None`` when no asset is found.

    Imported lazily so this module stays usable without a Qt install.
    """
    path = icon_ico_path() or icon_png_path()
    if path is None:
        return None
    from PySide6.QtGui import QIcon

    icon = QIcon(str(path))
    return None if icon.isNull() else icon


def apply_windows_app_id() -> bool:
    """Set the process AppUserModelID so Windows groups/labels us as ExileLens."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # pragma: no cover - defensive, non-fatal
        return False
    return True
