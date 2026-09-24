"""DOC-UX-01: overlay hotkey hint follows the configured chord.

The overlay hint label was hardcoded to "Shift+C to analyze" while the
onboarding card, overview page, and health row all render the configured
chord via ``health.hotkey_display``. After a rebind the hint disagreed with
every other surface. ``PriceCheckPanel.set_hotkey_hint_text`` (wired through
``Overlay._sync_hotkey_hint``) closes that gap; the constructor default is
unchanged so callers that never set a chord render exactly as before.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from poe2value.ui.overlay_presentation import ItemOverlayPanel

pytestmark = pytest.mark.itemcheck


def _make_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_hint_defaults_to_shift_c() -> None:
    _make_app()
    panel = ItemOverlayPanel()

    assert panel._hotkey_hint.text() == "Shift+C to analyze"


def test_hint_shows_configured_chord() -> None:
    _make_app()
    panel = ItemOverlayPanel()
    panel.set_hotkey_hint_text("Ctrl + Alt + X to analyze")

    assert panel._hotkey_hint.text() == "Ctrl + Alt + X to analyze"


def test_hint_empty_text_falls_back_to_default() -> None:
    _make_app()
    panel = ItemOverlayPanel()
    panel.set_hotkey_hint_text("Ctrl + Alt + X to analyze")
    panel.set_hotkey_hint_text("")

    assert panel._hotkey_hint.text() == "Shift+C to analyze"


def test_hotkey_display_formats_default_chord() -> None:
    from types import SimpleNamespace

    from poe2value.ui.health import hotkey_display

    assert hotkey_display(SimpleNamespace(price_check_hotkey="shift+c")) == "Shift + C"
