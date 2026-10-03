"""Contracts the desktop UI redesign must keep: overlay styling untouched, privacy copy pinned to the
events contract, one shared status derivation, and the Patreon/Updates wording."""

from __future__ import annotations

import hashlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.ui import styles


# --------------------------------------------------------------------------------------- overlay unchanged
# These digests were taken from origin/main before the redesign. The overlay must not pick up dashboard tokens:
# if one of these fails, a dashboard change leaked into the overlay (or the overlay was changed on purpose and the
# digest needs a deliberate update in the same PR).
OVERLAY_STYLESHEET_SHA256 = "5155b59ad3c3f6c9db25e398b0a1085f51c0f1b75c56dbb06821828292beeda1"
OVERLAY_STYLESHEET_1X_SHA256 = "9fc81307f43bdc6b32733509c2bd84dfc9b83d425008b0f8b86940fef65f6077"
OVERLAY_INDEPENDENCE_SHA256 = "77702bc6aef7f26774c1d94ea32f7aded8901342a40312bf1d03561580a5da7e"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_overlay_stylesheets_are_byte_identical_to_the_pre_redesign_overlay() -> None:
    assert _sha(styles.OVERLAY_STYLESHEET) == OVERLAY_STYLESHEET_SHA256
    assert _sha(styles.overlay_stylesheet(1.0)) == OVERLAY_STYLESHEET_1X_SHA256
    assert _sha(styles.OVERLAY_THEME_INDEPENDENCE_STYLESHEET) == OVERLAY_INDEPENDENCE_SHA256


def test_dashboard_redesign_rules_stay_scoped_to_the_dashboard_root() -> None:
    from exilelens.ui.redesign_style import REDESIGN_STYLESHEET

    import re

    css = re.sub(r"/\*.*?\*/", "", REDESIGN_STYLESHEET, flags=re.S)
    for block in css.split("}"):
        selector = block.split("{", 1)[0].strip()
        if not selector:
            continue
        for part in selector.split(","):
            assert part.strip().startswith("QWidget#dashboardRoot"), part.strip()


# ----------------------------------------------------------------------------------------- privacy copy
def test_privacy_summaries_come_from_the_events_contract() -> None:
    from exilelens.cloud import contract
    from exilelens.ui.privacy_panel import category_summary

    categories = contract.schema()["categories"]
    assert set(categories) >= {"errors", "usage"}
    for key in ("errors", "usage"):
        assert category_summary(key) == categories[key]["summary"] != ""


def test_settings_privacy_rows_show_the_contract_text_and_two_independent_off_by_default_switches() -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.app.settings import AppSettings
    from exilelens.cloud import contract
    from exilelens.ui.privacy_panel import PrivacyPanel

    QApplication.instance() or QApplication([])
    panel = PrivacyPanel(AppSettings(), None)
    categories = contract.schema()["categories"]
    assert panel.errors_row.helper.text() == categories["errors"]["summary"]
    assert panel.usage_row.helper.text() == categories["usage"]["summary"]
    assert panel.errors_box is not panel.usage_box
    assert not panel.errors_box.isChecked() and not panel.usage_box.isChecked()
    assert panel.errors_box.accessibleName() and panel.usage_box.accessibleName()


def test_privacy_copy_never_calls_the_usage_id_anonymous() -> None:
    from exilelens.ui import patreon_panel, privacy_panel

    for text in (privacy_panel.PrivacyPanel.INTRO, patreon_panel.PRIVACY_LINE, privacy_panel.ERRORS_LABEL, privacy_panel.USAGE_LABEL):
        assert "anonymous" not in text.lower()


def test_patreon_copy_is_the_agreed_wording() -> None:
    from exilelens.ui import patreon_panel

    assert patreon_panel.PRIVACY_LINE == (
        "ExileLens never receives your Patreon name or email in the desktop app. The ExileLens service keeps only "
        "what it needs to confirm supporter status, separate from usage stats and error reports."
    )
    assert patreon_panel.FREE_LINE == "Manual updates and every core ExileLens feature remain free."
    assert patreon_panel.SUPPORT_HELP == "Help fund continued development and get seamless automatic updates."


# ---------------------------------------------------------------------------------------- status model
class _Row:
    def __init__(self, value: str, status: str = "ok") -> None:
        self.label, self.value, self.status, self.action = "x", value, status, ""


def _health(pob=("Connected", "ok"), build=("Loaded", "ok"), hotkey=("Shift+C", "ok")):
    from exilelens.ui.health import AppHealth

    items = {}
    for key, (value, status) in {"pob": pob, "build": build, "hotkey": hotkey}.items():
        items[key] = _Row(value, status)
    return type("H", (), {"pob": items["pob"], "build": items["build"], "hotkey": items["hotkey"]})()


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({}, "ready"),
        ({"pob": ("Not found", "error")}, "setup"),
        ({"pob": ("Connecting…", "warn")}, "connecting"),
        ({"pob": ("Not connected", "error")}, "disconnected"),
        ({"build": ("Not selected", "warn")}, "setup"),
        ({"build": ("Could not load", "error")}, "attention"),
        ({"build": ("loading…", "neutral")}, "loading"),
        ({"hotkey": ("Not active", "error")}, "attention"),
    ],
)
def test_status_classification_ladder(kwargs, expected) -> None:
    from exilelens.ui import status_model

    assert status_model.classify(_health(**kwargs)) == expected


def test_only_action_states_repeat_on_the_page() -> None:
    from exilelens.ui import status_model as sm

    def needs(key):
        word, tone = sm._WORDS[key]
        return sm.AppStatus(key, word, tone, "b", "", 0, None).needs_action  # type: ignore[arg-type]

    assert not needs(sm.READY) and not needs(sm.LOADING) and not needs(sm.CONNECTING)
    assert needs(sm.SETUP) and needs(sm.ATTENTION) and needs(sm.DISCONNECTED)


# ------------------------------------------------------------------------------------------------ fonts
def test_build_name_font_stack_falls_back_to_georgia_and_loader_is_safe_without_files() -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.ui import fonts, theme

    QApplication.instance() or QApplication([])
    assert theme.BUILD_NAME_FONT_FAMILY.startswith('"Spectral", "Georgia"')
    assert isinstance(fonts.register_bundled_fonts(), list)  # empty when the optional files are not shipped
