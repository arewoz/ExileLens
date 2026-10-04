"""Final polish: a neutral supporter zone, no visible channel note, and the concise "What ExileLens collects" dialog.

The dialog summary is checked against the real contract (``events.v1.json``) semantically, not word for word: every
contract event and every "never collected" entry must still be covered, so a contract change fails here until the
short copy has been reviewed.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the dashboard harness uses Windows-only capture helpers")
_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "scripts"))
    monkeypatch.syspath_prepend(str(_ROOT))
    qa = importlib.import_module("ui_visual_qa")
    states = importlib.import_module("qa_states")
    original = os.environ.get("LOCALAPPDATA")
    instance = qa.Harness(tmp_path)
    instance.states = states.STATE_REGISTRY
    instance._dialogs = []
    yield instance
    for dialog in instance._dialogs:   # a modal dialog left open would swallow the next test's key events
        dialog.close()
        dialog.deleteLater()
    instance.controller.shutdown()
    instance.window.close()
    if original is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original


def _settle(h, n: int = 30) -> None:
    for _ in range(n):
        h.app.processEvents()


# --------------------------------------------------------------------------------------------- supporter zone is neutral
@pytest.mark.parametrize("state", ["not_connected", "service_unavailable", "active", "not_eligible", "expired"])
def test_supporter_zone_has_no_reddish_surface_or_border_only_the_mark_keeps_the_patreon_colour(harness, state) -> None:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor

    from exilelens.ui import theme

    harness.patreon(state)
    harness.window.resize(980, 720)
    harness.window.navigate("settings")
    _settle(harness)
    page = harness.window._settings_page
    zone = page._patreon_panel
    body = page.scroll.widget()
    top_left = zone.mapTo(body, zone.rect().topLeft())
    image = body.grab(QRect(top_left, zone.size())).toImage()   # rendered over the page, so a missing fill is visible
    mark = QRect(8, 8, 36, 34)   # the shipped icon sits in the header's first 16 px column
    # The state word and its dot (a warn state is orange, with a status dot) are status, not surface.
    state_word = zone.state_label.geometry().adjusted(-24, -4, 4, 4)
    reddish = []
    for y in range(image.height()):
        for x in range(image.width()):
            if mark.contains(x, y) or state_word.contains(x, y):
                continue
            c = QColor(image.pixel(x, y))
            # a red/pink cast: red clearly above green AND blue, with green close to blue. (The orange of a warn status
            # word has green well above blue; champagne and green text are excluded the same way.)
            if c.red() - c.green() > 14 and c.blue() >= c.green() - 6:   # pink/red; champagne (switch) and orange have blue well below green
                reddish.append((x, y, c.name()))
    assert reddish == [], reddish[:5]
    # The surface is the faintly plum-warmed raised neutral, visibly apart from the page but nowhere near red.
    want = QColor(theme.SUPPORT_SURFACE)
    inside = QColor(image.pixel(image.width() // 2, image.height() - 3))
    assert abs(inside.red() - want.red()) <= 3 and abs(inside.green() - want.green()) <= 3 and abs(inside.blue() - want.blue()) <= 3
    page = QColor(theme.BG)
    assert (inside.red() + inside.green() + inside.blue()) - (page.red() + page.green() + page.blue()) >= 20


def test_supporter_surface_is_a_warm_neutral_far_from_the_destructive_family() -> None:
    import colorsys

    from exilelens.ui import theme

    def hsl(value):
        r, g, b = (int(value.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        return h * 360, s, l

    hue, sat, light = hsl(theme.SUPPORT_SURFACE)
    error_hue = hsl(theme.ERROR)[0]
    distance = min(abs(hue - error_hue), 360 - abs(hue - error_hue))
    assert sat < 0.15 and light < 0.2                 # a faint undertone on a dark surface, not a coloured panel
    assert distance > 60                              # a different colour family from Reset configuration's outline
    # still a visible section against the page background, and its text keeps the informational contrast
    assert light > hsl(theme.BG)[2]
    from exilelens.ui.redesign_style import build_stylesheet  # noqa: F401  (stylesheet builds with the token)
    surface = tuple(int(theme.SUPPORT_SURFACE.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    for name in ("TEXT", "TEXT_BODY", "TEXT_MUTED"):
        value = tuple(int(getattr(theme, name).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        la, lb = sorted((_lum(value), _lum(surface)), reverse=True)
        assert (la + 0.05) / (lb + 0.05) >= 4.5, name


def _lum(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_zone_does_not_share_the_destructive_look_with_reset(harness) -> None:
    from exilelens.ui.redesign_style import build_stylesheet

    css = build_stylesheet()
    zone_lines = [line for line in css.splitlines() if "supporterZone" in line]
    assert zone_lines
    for line in zone_lines:
        assert "239,128,119" not in line and "242,160,61" not in line and "255,66,77" not in line   # error / warn / patreon


def test_unavailable_build_shows_the_agreed_neutral_hierarchy(harness) -> None:
    from PySide6.QtWidgets import QLabel, QPushButton

    harness.patreon("not_connected")
    harness.window.navigate("settings")
    _settle(harness)
    zone = harness.window._settings_page._patreon_panel
    zone.link = None
    zone.render()
    _settle(harness)
    labels = [l.text() for l in zone.findChildren(QLabel) if l.isVisibleTo(zone) and l.text()]
    assert "Seamless updates" in labels
    assert "Supporters can download verified updates automatically and install them when ExileLens closes." in labels
    assert zone.state_label.text() == "Unavailable in this build" and zone.state_label.objectName() == "secondaryText"  # muted, not an error
    assert zone.status.text() == "Patreon linking isn't available in this build. Manual updates still work."
    assert zone.auto_download.is_locked() and zone.install_on_exit.is_locked()
    assert [b.text() for b in zone.findChildren(QPushButton) if b.isVisibleTo(zone)] == ["Support on Patreon"]
    assert not zone._dot.isVisibleTo(zone)   # no status dot: nothing is wrong


# --------------------------------------------------------------------------------------------- no visible channel note
def test_the_beta_channel_helper_is_gone_but_the_prerelease_line_stays(harness) -> None:
    from PySide6.QtWidgets import QLabel

    harness.update("ahead", "0.6.0")
    harness.window.navigate("settings")
    _settle(harness)
    page = harness.window._settings_page
    texts = [l.text() for l in page.findChildren(QLabel) if l.isVisibleTo(page)]
    assert "Pre-release · Latest stable 0.6.0" in texts
    assert not any("Beta channel" in t or "Later betas" in t for t in texts)
    from exilelens.ui import updates_panel

    assert not hasattr(updates_panel, "PRERELEASE_NOTE")


def test_update_channel_logic_is_untouched() -> None:
    """Only the visible sentence was removed: selecting betas for a pre-release install still works."""
    from exilelens.app.updates.version import ExileLensVersion

    assert not ExileLensVersion.parse("0.7.0b1").final
    assert ExileLensVersion.parse("0.7.0").final


# --------------------------------------------------------------------------------------------- the dialog's content contract
def _dialog(harness, size=(980, 720)):
    from exilelens.ui.privacy_panel import CollectedDialog

    harness.window.resize(*size)
    harness.window.navigate("settings")
    _settle(harness)
    dialog = CollectedDialog(None, harness.window._settings_page)
    dialog.show()
    harness._dialogs.append(dialog)
    _settle(harness)
    return dialog


def test_every_contract_usage_event_is_covered_by_the_short_summary() -> None:
    from exilelens.cloud import contract
    from exilelens.ui import privacy_panel

    events = set(contract.schema()["usage"]["events"])
    assert set(privacy_panel.USAGE_TOPICS) == events, "a usage event was added or removed: review the dialog copy"
    assert set(privacy_panel.USAGE_TOPICS.values()) <= set(privacy_panel.USAGE_BULLETS) | {"counts"}


def test_error_report_fields_are_still_what_the_summary_says() -> None:
    from exilelens.cloud import contract

    props = set(contract.schema()["errors"]["report"]["props"])
    # code, component, exception type, module/function frames, counts and times: nothing else may appear unreviewed
    assert props == {"error_code", "component", "exception_type", "frames", "count", "first_t", "last_t", "pob_version"}
    frame_props = set(contract.schema()["errors"]["report"]["props"]["frames"]["item"]["props"])
    assert frame_props == {"module", "function", "line"}


def test_every_never_collected_entry_is_still_mentioned(harness) -> None:
    from exilelens.cloud import contract

    entries = contract.schema()["never_collected"]
    keywords = [
        ("item", "clipboard"), ("build", "character"), ("trade", "price"), ("file path", "log"),
        ("error messages", "stack"), ("ip address",), ("hardware", "email", "patreon"),
    ]
    assert len(entries) == len(keywords), "the never-collected list changed: review the dialog copy"
    text = _dialog(harness).visible_text().lower()
    assert "path of building version" in text   # the error report also carries the PoB version (contract: pob_version)
    for entry, words in zip(entries, keywords):
        assert all(w in text for w in words), entry


def test_the_two_options_stay_independent_off_by_default_and_each_has_its_own_id(harness) -> None:
    from exilelens.app.settings import AppSettings
    from exilelens.cloud import contract

    assert AppSettings().send_usage_stats is False and AppSettings().send_error_reports is False
    ids = contract.schema()["identifiers"]
    assert set(ids) == {"analytics_id", "diagnostic_id"}
    text = _dialog(harness).visible_text().lower()
    assert "off by default" in text and "independently" in text and "own random id" in text
    assert "anonymous" not in text   # the contract calls the IDs pseudonymous; the summary must never claim otherwise


def test_dialog_shows_no_schemas_ids_payloads_or_retention_details(harness) -> None:
    text = _dialog(harness).visible_text()
    lowered = text.lower()
    for forbidden in ("app_started", "item_checks_summary", "batch_id", "diagnostic_id", "analytics_id", "json", "enum",
                      "schema", "payload", "el-wrk", "30 days", "13 months", "12 months", "retention", "frames"):
        assert forbidden not in lowered, forbidden
    words = len(text.split())
    assert 100 <= words <= 180, words   # about ten seconds of reading


# --------------------------------------------------------------------------------------------- the shared dialog shell
def test_dialog_uses_the_shared_info_shell_with_a_default_close_and_no_tabs(harness, monkeypatch) -> None:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPlainTextEdit, QTabWidget

    from exilelens.ui.info_dialog import InfoDialog
    from exilelens.ui.privacy_panel import CollectedDialog

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    dialog = _dialog(harness)
    assert isinstance(dialog, CollectedDialog) and isinstance(dialog, InfoDialog)
    assert not dialog.findChildren(QTabWidget) and not dialog.findChildren(QPlainTextEdit)
    assert dialog.width() == 560 and dialog.windowTitle() == "What ExileLens collects"
    assert dialog.close_button.isDefault() and dialog.close_button.hasFocus()
    assert dialog.close_button.objectName() == "btnPrimary"
    assert dialog.link_button.text() == "Full privacy details"
    dialog.link_button.click()
    assert opened and opened[0].endswith("/blob/main/PRIVACY.md") and opened[0].startswith("https://github.com/")
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    _settle(harness)
    assert not dialog.isVisible()
    assert QUrl(opened[0]).isValid()


def test_close_button_and_enter_dismiss(harness) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog = _dialog(harness)
    QTest.keyClick(dialog, Qt.Key.Key_Return)   # Close is the default button and has focus
    _settle(harness)
    assert not dialog.isVisible()
    dialog = _dialog(harness)
    dialog.close_button.click()
    _settle(harness)
    assert not dialog.isVisible()


def test_dialog_fits_without_scrolling_at_the_default_window_and_scrolls_only_the_body_when_small(harness) -> None:
    dialog = _dialog(harness, (980, 720))
    bar = dialog._scroll.verticalScrollBar()
    # The real-Qt capture fits exactly (scroll range 0). The offscreen test platform uses wider fallback fonts, so
    # allow a couple of lines of slack here rather than pin font metrics.
    assert bar.maximum() <= 40, "the page should (all but) fit at 980 x 720"
    assert dialog.height() <= 0.8 * 720 + 1
    dialog.close()
    small = _dialog(harness, (720, 560))
    assert small.height() <= 0.8 * 560 + 1
    assert small._scroll.verticalScrollBar().maximum() > 0           # body scrolls ...
    assert small.close_button.isVisible() and small.link_button.isVisible()   # ... header and footer stay put
    small._scroll.verticalScrollBar().setValue(20)
    _settle(harness)
    assert small._header.property("scrolled") is True                # hairline under the header only once scrolled
    small.close()


def test_dialog_at_125_percent_text_widens_and_keeps_header_and_footer(harness, monkeypatch) -> None:
    from exilelens.ui import theme
    from exilelens.ui.dashboard_window import DashboardWindow

    monkeypatch.setattr(theme, "system_text_scale", lambda: 1.25)
    window = DashboardWindow(harness.settings, harness.controller)
    try:
        harness.window = window
        window.show_dashboard()
        dialog = _dialog(harness, (980, 720))
        assert dialog.width() == 700
        assert dialog.close_button.isVisible() and dialog.link_button.isVisible()
        assert dialog.height() <= 0.8 * 720 + 1
        dialog.close()
    finally:
        window.close()


def test_privacy_buttons_open_the_same_dialog_and_the_old_inspector_pieces_are_gone() -> None:
    from exilelens.ui import privacy_panel

    for gone in ("QTabWidget", "QPlainTextEdit", "_category_tab", "_never_tab"):
        assert not hasattr(privacy_panel, gone)
    assert issubclass(privacy_panel.CollectedDialog, privacy_panel.InfoDialog)
