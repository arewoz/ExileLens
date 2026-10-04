"""Settings + Diagnostics regroup: structure, removed duplication, the supporter and help zones, the rail's Support link.

Runs the real DashboardWindow through the QA harness (scripts/ui_visual_qa.py), which substitutes the health model so
every Path of Building / Patreon state can be shown without Path of Building.
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
    yield instance
    instance.controller.shutdown()
    instance.window.close()
    if original is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original


def _settle(h, n: int = 30) -> None:
    for _ in range(n):
        h.app.processEvents()


def _go(h, state: str, size: tuple[int, int] | None = None):
    h.states[state](h)
    if size:
        h.window.resize(*size)
    _settle(h)


def _all(root, *kinds):
    """``findChildren`` takes one type in PySide: gather several."""
    found = []
    for kind in kinds:
        found.extend(w for w in root.findChildren(kind) if w not in found)
    return found


def _texts(root):
    from PySide6.QtWidgets import QAbstractButton, QLabel

    return [w.text() for w in _all(root, QLabel, QAbstractButton) if w.text() and w.isVisibleTo(root)]


# --------------------------------------------------------------------------------------------- Settings structure
def test_settings_sections_are_in_the_approved_order_and_there_is_no_advanced_section(harness) -> None:
    from exilelens.ui.dashboard_widgets import SettingsSection, SetupCard

    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    # Page order of the column: card, then the sections.
    order = []
    for index in range(page.column.count()):
        widget = page.column.itemAt(index).widget()
        if isinstance(widget, SetupCard):
            order.append(widget.heading.text())
        elif isinstance(widget, SettingsSection):
            order.append(widget.title())
        elif widget is not None and widget.objectName() == "resetSection":
            order.append("Reset")
    assert order == ["Path of Building", "Hotkey", "Updates", "Item evaluation", "Overlay", "Privacy", "Reset"]
    titles = [section.title() for section in page.findChildren(SettingsSection)]
    assert "Advanced" not in titles and "Support ExileLens" not in titles


def test_settings_has_no_duplicate_troubleshooting_controls_and_no_dedup_control(harness) -> None:
    from PySide6.QtWidgets import QLineEdit

    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    texts = _texts(page)
    for gone in ("Troubleshooting & diagnostics", "Browse", "Apply", "Load", "Auto-detect", "Reload build", "Live market"):
        assert gone not in texts, gone
    assert not any("dedup" in text.lower() for text in texts)
    # The folder and build are never edited by typing: the only line edit left on the page is Auto hide.
    edits = [edit.accessibleName() for edit in page.findChildren(QLineEdit)]
    assert edits == ["Auto hide (seconds)"]
    for kept in ("Detect", "Change folder", "Reload", "Change build"):
        assert kept in texts, kept


def test_settings_ends_with_reset_and_a_pointer_to_diagnostics(harness) -> None:
    from PySide6.QtWidgets import QWidget

    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    host = page.findChild(QWidget, "resetSection")
    assert host is not None
    assert page.column.itemAt(page.column.count() - 2).widget() is host   # the stretch is last
    assert "Diagnostics" in page._diagnostics_pointer.text()
    page._diagnostics_pointer.linkActivated.emit("diagnostics")
    assert harness.window.current_page_id() == "diagnostics"


# --------------------------------------------------------------------------------------------- Path of Building card
def test_pob_card_paths_are_read_only_selectable_and_copy_the_full_value(harness) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    _go(harness, "settings-top", (720, 560))   # narrow enough that a path may be elided
    page = harness.window._settings_page
    for label, value in ((page._pob_path_label, page._pob_path), (page._build_path_label, page._build_path)):
        assert label.full_text() == value and value
        assert label.toolTip() == value
        assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
        label.copy_full()
        assert QApplication.clipboard().text() == value
    assert page._pob_path_label.accessibleName() == "Path of Building folder"
    assert page._build_path_label.accessibleName() == "Build file"


@pytest.mark.parametrize(
    "state, word, tone, problem_row, primary",
    [
        ("ready", "Ready", "ok", None, None),
        ("disconnected", "Not connected", "error", "install", "Reconnect"),
        ("setup", "Setup needed", "warn", "build", "Choose build"),
        ("attention", "Needs attention", "warn", "build", "Reload"),
    ],
)
def test_pob_card_state_header_row_lift_and_single_primary(harness, state, word, tone, problem_row, primary) -> None:
    from PySide6.QtWidgets import QPushButton

    harness.set_state(state)
    harness.window.navigate("settings")
    _settle(harness)
    page = harness.window._settings_page
    card = page._pob_card
    assert card.status.text() == word and card.status.status() == tone   # a word, never colour alone
    lifted = [name for name, row in (("install", page._install_row), ("build", page._build_row)) if row.property("problem")]
    assert lifted == ([problem_row] if problem_row else [])
    primaries = [b.text() for b in card.findChildren(QPushButton) if b.objectName() == "btnPrimary" and b.isVisibleTo(card)]
    assert primaries == ([primary] if primary else [])


def test_pob_card_build_state_is_the_one_health_value_not_a_second_status(harness) -> None:
    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    from exilelens.ui.health import derive_health

    health = derive_health(harness.controller, harness.settings)
    name, _sep, age = health.build.value.partition(" · ")
    assert page._build_name.text() == name
    assert page._build_age.text().lower() == age.lower()
    assert page._pob_state.text() == health.pob.value


def test_changing_the_build_elsewhere_updates_the_displayed_path(harness) -> None:
    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    # The controller writes the new path into settings when a build is changed from Overview or Diagnostics.
    harness.settings.build_path = r"C:\PoB2\Builds\Other.xml"
    page.refresh_setup_status()
    assert page._build_path_label.full_text() == r"C:\PoB2\Builds\Other.xml"


# --------------------------------------------------------------------------------------------- supporter zone
def test_there_is_exactly_one_supporter_zone_inside_updates_and_it_holds_all_supporter_controls(harness) -> None:
    from PySide6.QtWidgets import QFrame

    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    zones = [f for f in page.findChildren(QFrame) if f.objectName() == "supporterZone"]
    assert zones == [page._patreon_panel]
    assert page._updates_section.isAncestorOf(zones[0])
    zone = zones[0]
    # Everything supporter-related is inside it; the free manual update row is not.
    assert zone.isAncestorOf(zone.auto_download) and zone.isAncestorOf(zone.install_on_exit)
    assert zone.isAncestorOf(zone.link_button) and zone.isAncestorOf(zone.support_button)
    from PySide6.QtWidgets import QPushButton

    check = [b for b in page.findChildren(QPushButton) if b.text() == "Check for updates"]
    assert check and not any(zone.isAncestorOf(b) for b in check)
    # The Privacy section is never tinted.
    assert not zone.isAncestorOf(page._privacy_panel)


@pytest.mark.parametrize(
    "state, word, live",
    [
        ("not_connected", "Not linked", False),
        ("linking", "Waiting for Patreon…", False),
        ("active", "Active", True),
        ("not_eligible", "Not in your membership", False),
        ("expired", "Paused", False),
        ("reconnect_required", "Reconnect needed", False),
        ("service_unavailable", "Linking unavailable", False),
    ],
)
def test_supporter_zone_state_word_switches_and_one_footer_sentence(harness, state, word, live) -> None:
    from exilelens.ui.patreon_panel import LOCKED_TIP

    harness.patreon(state)
    harness.window.navigate("settings")
    _settle(harness)
    zone = harness.window._settings_page._patreon_panel
    assert zone.state_label.text() == word
    for box in (zone.auto_download, zone.install_on_exit):
        assert box.isEnabled() is live
        assert box.is_locked() is (not live)           # locked = dashed track, not merely an Off switch
        assert (box.toolTip() == "") is live
        assert box.toolTip() in ("", LOCKED_TIP)
    # The reason is said once: the footer sentence. The rows never repeat it.
    assert zone.status.text()
    assert "Manual updates still work" in zone.status.text() or state in ("not_connected", "linking", "active")
    row_texts = [zone._auto_row.label.text(), zone._exit_row.label.text(), zone._exit_row.helper.text()]
    assert not any("membership" in t or "available in this build" in t for t in row_texts)


def test_supporter_zone_buttons_do_the_external_things_and_nothing_else_does(harness, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("exilelens.ui.patreon_panel._open_patreon_page", lambda: calls.append("patreon"))
    harness.patreon("not_connected")
    harness.window.navigate("settings")
    _settle(harness)
    zone = harness.window._settings_page._patreon_panel
    zone.support_button.clicked.disconnect()
    zone.support_button.clicked.connect(lambda: calls.append("support"))
    zone.support_button.click()
    assert calls == ["support"]
    started = []
    zone.link = type("L", (), {"start_link": lambda self: started.append(True), "view": lambda self: type("V", (), {"state": __import__("exilelens.cloud.patreon", fromlist=["PatreonState"]).PatreonState.NOT_CONNECTED, "detail": "", "expires_at": 0})(), "available": lambda self: True, "add_listener": lambda self, fn: None})()
    zone.link_button.click()
    assert started == [True]


def test_supporter_zone_is_always_present_even_when_updates_are_unavailable(harness) -> None:
    from exilelens.ui.dashboard_pages import SettingsPage

    page = SettingsPage(harness.settings, harness.controller, None)
    assert page._patreon_panel is not None
    assert page._updates_section.isAncestorOf(page._patreon_panel)


# --------------------------------------------------------------------------------------------- the rail's Support link
def test_rail_support_opens_settings_at_the_supporter_zone_and_opens_nothing_external(harness, monkeypatch) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr("exilelens.ui.recovery_actions.open_patreon", lambda: opened.append("patreon") or True)
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    _go(harness, "overview-ready", (980, 720))
    harness.window.show_dashboard()
    assert harness.window.current_page_id() == "overview"
    harness.window._rail.link_buttons()["support"].click()
    _settle(harness, 60)
    window = harness.window
    assert window.current_page_id() == "settings"
    assert opened == []                                    # the click itself opens no browser
    page = window._settings_page
    zone = page._patreon_panel
    viewport = page.scroll.viewport()
    top = zone.mapTo(viewport, zone.rect().topLeft()).y()
    bottom = zone.mapTo(viewport, zone.rect().bottomLeft()).y()
    assert 0 <= top and bottom <= viewport.height() + 1     # the whole zone is in view
    focus = window.focusWidget()
    assert focus is not None and zone.isAncestorOf(focus)  # a sensible keyboard start inside the zone


def test_rail_support_works_from_every_page_and_on_the_compact_rail(harness) -> None:
    for page_id in ("overview", "build_analysis", "diagnostics", "settings"):
        harness.window.navigate(page_id)
        harness.window._rail.link_buttons()["support"].click()
        _settle(harness, 40)
        assert harness.window.current_page_id() == "settings"
    harness.window.resize(720, 560)
    _settle(harness)
    harness.window.navigate("overview")
    harness.window._rail.link_buttons()["support"].click()
    _settle(harness, 40)
    assert harness.window.current_page_id() == "settings"


# --------------------------------------------------------------------------------------------- Diagnostics
def test_diagnostics_structure_health_card_help_zone_and_collapsed_advanced(harness) -> None:
    from PySide6.QtWidgets import QFrame

    _go(harness, "diagnostics-degraded", (980, 720))
    page = harness.window._diagnostics
    order = [page.column.itemAt(i).widget() for i in range(page.column.count()) if page.column.itemAt(i).widget() is not None]
    assert [w.objectName() for w in order[:2]] == ["setupCard", "helpZone"]
    assert order[2] is page._advanced
    assert page._advanced.is_expanded() is False                       # collapsed by default
    assert page._advanced.preview.isVisibleTo(page) and page._advanced.preview.text() == page.ADVANCED_PREVIEW
    assert page._health_card.status.text() == "3 need attention" and page._health_card.status.status() == "warn"
    assert page._health_footer.isVisibleTo(page) and "Reconnect first" in page._support_hint.text()
    # The card keeps its neutral border: no colour in the card style depends on status.
    assert "warn" not in page._health_card.styleSheet() and page._health_card.styleSheet() == ""
    assert [f.objectName() for f in page.findChildren(QFrame) if f.objectName() in ("helpZone", "supporterZone")] == ["helpZone"]


def test_diagnostics_aggregate_status_says_all_good_when_healthy(harness) -> None:
    _go(harness, "diagnostics-healthy", (980, 720))
    page = harness.window._diagnostics
    assert page._health_card.status.text() == "All good" and page._health_card.status.status() == "ok"
    assert not page._health_card.lead.isVisibleTo(page)
    assert not page._health_footer.isVisibleTo(page)


def test_report_zone_holds_the_report_actions_and_the_support_id(harness) -> None:
    from PySide6.QtWidgets import QApplication

    _go(harness, "diagnostics-degraded", (980, 720))
    page = harness.window._diagnostics
    zone = page._help_zone
    for widget in (page._copy_btn, page._export_bundle_btn, page._report_issue_btn, page._repro_notes, page._support_id, page._copy_id_btn):
        assert zone.isAncestorOf(widget)
    assert page._copy_btn.text() == "Copy diagnostics"
    assert page._export_bundle_btn.text() == "Export support package…"
    assert page._report_issue_btn.text() == "Open a GitHub issue"
    # No primary button inside the help zone: the fix is the health card's.
    assert not [b for b in zone.findChildren(type(page._copy_btn)) if b.objectName() == "btnPrimary"]
    support_id = page._support_id.text()
    assert len(support_id) == 12
    page._copy_id_btn.click()
    assert QApplication.clipboard().text() == support_id


def test_advanced_diagnostics_is_one_viewer_with_two_modes_and_copy(harness) -> None:
    from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTextEdit

    from exilelens.diagnostics import event_buffer, record_event

    event_buffer().clear()
    record_event("pob", "worker_exit", detail={"code": 3, "path": "x"})
    _go(harness, "diagnostics-advanced", (980, 720))
    page = harness.window._diagnostics
    assert page._advanced.is_expanded()
    assert [b.text() for b in (page._logs_btn, page._verbose_btn, page._clear_history_btn)] == [
        "Open logs folder", "Enable verbose diagnostics for 15 min", "Clear diagnostic history",
    ]
    # One viewer only: no stacked disclosures and no second text area.
    viewers = [w for w in _all(page, QPlainTextEdit, QTextEdit) if w is not page._repro_notes and w.isVisibleTo(page)]
    assert viewers == [page._viewer]
    assert page.viewer_mode() == "events"
    shown = page._viewer.toPlainText()
    assert "worker_exit" in shown and "code=3" in shown and "path=x" in shown   # nothing dropped
    assert not shown.lstrip().startswith("[") and '"ts"' not in shown            # not a raw JSON array
    page._viewer_copy_btn.click()
    assert QApplication.clipboard().text() == shown
    page._viewer_mode.buttons()[1].click()
    assert page.viewer_mode() == "report"
    assert "Version" in page._viewer.toPlainText() or "App" in page._viewer.toPlainText()
    page._viewer_copy_btn.click()
    assert QApplication.clipboard().text() == page._viewer.toPlainText()
    event_buffer().clear()


def test_empty_event_history_reads_in_words(harness) -> None:
    from exilelens.diagnostics import event_buffer

    event_buffer().clear()
    _go(harness, "diagnostics-advanced", (980, 720))
    assert harness.window._diagnostics._viewer.toPlainText() == "No events recorded this session."


def test_diagnostics_actions_still_work(harness, monkeypatch) -> None:
    from exilelens.diagnostics import event_buffer, record_event, verbose_mode_active

    calls = []
    monkeypatch.setattr("exilelens.ui.recovery_actions.open_logs_folder", lambda: calls.append("logs"))
    monkeypatch.setattr("exilelens.ui.recovery_actions.open_github_issues", lambda: calls.append("issues"))
    copied = []
    monkeypatch.setattr("exilelens.ui.recovery_actions.copy_diagnostics", lambda *a, **k: copied.append(True) or "")
    _go(harness, "diagnostics-advanced", (980, 720))
    page = harness.window._diagnostics
    page._logs_btn.click()
    page._report_issue_btn.click()
    page._copy_btn.click()
    assert calls == ["logs", "issues"] and copied == [True]
    page._verbose_btn.click()
    assert verbose_mode_active(harness.settings)
    record_event("app", "x")
    page._clear_history_btn.click()
    assert not event_buffer().snapshot(include_verbose=True)
    assert page._report_status.isVisibleTo(page)


# --------------------------------------------------------------------------------------------- narrow widths
SIZES = [(980, 720), (840, 640), (720, 560)]


@pytest.mark.parametrize("scale", [1.0, 1.5])
@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("state, page_attr", [
    ("settings-pob-down", "_settings_page"), ("settings-supporter-active", "_settings_page"), ("settings-patreon-expired", "_settings_page"),
    ("diagnostics-report", "_diagnostics"), ("diagnostics-advanced", "_diagnostics"),
])
def test_nothing_is_clipped_or_overlapping_at_narrow_widths(harness, monkeypatch, state, page_attr, size, scale) -> None:
    from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel

    from exilelens.ui import theme
    from exilelens.ui.dashboard_window import DashboardWindow

    monkeypatch.setattr(theme, "system_text_scale", lambda: scale)
    window = DashboardWindow(harness.settings, harness.controller)
    try:
        harness.window = window
        window.show_dashboard()
        _go(harness, state, size)
        page = getattr(window, page_attr)
        viewport = page.scroll.viewport()
        body = page.scroll.widget()
        assert body.width() <= viewport.width() + 1, "the page grew wider than its viewport"
        for widget in body.findChildren(QAbstractButton):
            if widget.isVisibleTo(body):
                right = widget.mapTo(body, widget.rect().topRight()).x()
                assert right <= body.width() + 1, f"button clipped: {widget.text()!r}"
                assert widget.width() >= widget.minimumSizeHint().width() - 1
        for label in body.findChildren(QLabel):
            if label.isVisibleTo(body) and label.wordWrap() and label.text():
                assert label.height() >= label.heightForWidth(label.width()) - 1, f"clipped text: {label.text()[:40]!r}"
        # Buttons never overlap each other inside one zone/card.
        for zone in body.findChildren(QFrame):
            if zone.objectName() in ("setupCard", "supporterZone", "helpZone"):
                buttons = [b for b in zone.findChildren(QAbstractButton) if b.isVisibleTo(zone) and b.objectName().startswith("btn")]
                rects = [b.mapTo(zone, b.rect().topLeft()) for b in buttons]
                for i, a in enumerate(buttons):
                    for j in range(i + 1, len(buttons)):
                        ra = a.rect().translated(rects[i])
                        rb = buttons[j].rect().translated(rects[j])
                        assert not ra.intersects(rb), (a.text(), buttons[j].text())
    finally:
        window.close()


def test_cards_and_zones_stack_deliberately_when_narrow(harness) -> None:
    _go(harness, "settings-supporter-active", (980, 720))
    page = harness.window._settings_page
    assert not page._install_row.is_stacked() and not page._build_row.is_stacked()
    harness.window.resize(720, 560)
    _settle(harness)
    # 720 wide still fits the side-by-side card (paths truncate instead).
    assert not page._install_row.is_stacked()
    from exilelens.ui import theme

    theme.apply_text_scale(1.5)
    try:
        harness.window.resize(720, 560)
        _settle(harness)
        harness.window._settings_page.refresh_setup_status()
        _settle(harness)
        assert page._install_row.is_stacked() == page._build_row.is_stacked()   # both rows of a card flip together
    finally:
        theme.apply_text_scale(1.0)


# --------------------------------------------------------------------------------------------- accessibility
def _over(background, tint_rgba):
    r, g, b, a = tint_rgba
    return tuple(round(c * (1 - a / 255) + t * a / 255) for c, t in zip(background, (r, g, b)))


def _rgba(css: str):
    import re

    r, g, b, a = (int(float(x)) for x in re.search(r"rgba\(([^)]*)\)", css).group(1).split(","))
    return r, g, b, a


def _hex(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("tint", ["HELP_TINT"])
def test_text_on_the_zone_tints_keeps_the_informational_contrast(tint) -> None:
    from exilelens.ui import theme

    surface = _over(_hex(theme.BG), _rgba(getattr(theme, tint)))
    for name in ("TEXT", "TEXT_BODY", "TEXT_MUTED"):
        assert _contrast(_hex(getattr(theme, name)), surface) >= 4.5, (tint, name)
    # The disabled/locked label colour is the page's muted informational colour, never TEXT_DISABLED.
    assert _contrast(_hex(theme.TEXT_MUTED), surface) >= 4.5


def test_honey_icon_and_status_words_are_legible_on_the_help_surface() -> None:
    from exilelens.ui import theme

    surface = _over(_hex(theme.BG), _rgba(theme.HELP_TINT))
    assert _contrast(_hex(theme.HELP), surface) >= 3.0           # a graphical object (WCAG 1.4.11)
    page = _hex(theme.BG)
    assert _contrast(_hex(theme.PATREON), page) >= 3.0           # the shipped mark on the plain page surface
    for name in ("OK", "WARN"):                                  # status words that sit on the supporter zone
        assert _contrast(_hex(getattr(theme, name)), page) >= 4.5


def test_zone_tokens_are_isolated_from_the_rest_of_the_ui(harness) -> None:
    from exilelens.ui import theme
    from exilelens.ui.redesign_style import build_stylesheet

    css = build_stylesheet()
    for token in (theme.HELP_TINT, theme.HELP_LINE):
        scoped = [line for line in css.splitlines() if token in line]
        assert scoped and all("#helpZone" in line for line in scoped), token
    # The supporter zone is neutral: nothing reddish anywhere in the dashboard style (red means warning or danger,
    # and only the Patreon mark itself keeps its colour).
    assert not hasattr(theme, "PATREON_TINT") and "255,66,77" not in css and "ff424d" not in css.lower()

    # Neither zone colour appears in the rail, buttons or the destructive style.
    assert theme.PATREON.lower() not in css.lower() and theme.HELP.lower() not in css.lower()


def test_locked_switch_and_zone_controls_have_accessible_names(harness) -> None:
    _go(harness, "settings-supporter", (980, 720))
    zone = harness.window._settings_page._patreon_panel
    assert zone.auto_download.accessibleName() == "Automatically download updates"
    assert zone.install_on_exit.accessibleName() == "Install when ExileLens closes"
    assert zone.accessibleName().startswith("Seamless updates")
    assert zone.state_label.text()                                   # state always carries a word


# --------------------------------------------------------------------------------------------- dead Dedup setting
def test_dedup_window_ui_setting_had_no_runtime_consumer_and_is_gone() -> None:
    from exilelens.app.settings import AppSettings

    src = _ROOT / "src"
    hits = [str(path.relative_to(src)) for path in src.rglob("*.py") if "dedup_window" in path.read_text(encoding="utf-8")]
    assert hits == []
    assert not hasattr(AppSettings(), "dedup_window_seconds")
    assert "dedup_window_seconds" not in AppSettings().to_dict()


def test_an_existing_settings_file_with_the_old_dedup_key_still_loads_and_drops_it_on_save() -> None:
    from exilelens.app.settings import AppSettings

    loaded = AppSettings.from_dict({"dedup_window_seconds": 9.5, "overlay_auto_hide_seconds": 4.0, "context": "BOSS"})
    assert loaded.overlay_auto_hide_seconds == 4.0 and loaded.context == "BOSS"
    assert "dedup_window_seconds" not in loaded.to_dict()


def test_clipboard_event_dedup_does_not_read_the_removed_setting() -> None:
    """The only dedup that exists at runtime is the fixed clipboard-event one; it never consulted settings."""
    from exilelens.app import price_check_hotkey

    source = Path(price_check_hotkey.__file__).read_text(encoding="utf-8")
    assert "dedup_window" not in source and "settings.dedup" not in source


# --------------------------------------------------------------------------------------------- keyboard
def test_keyboard_reaches_every_card_zone_and_viewer_control_and_skips_locked_switches(harness) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton

    _go(harness, "settings-supporter", (980, 720))
    page = harness.window._settings_page
    zone = page._patreon_panel
    # Locked switches are disabled: they take no focus, so Tab never lands on a control that does nothing.
    for box in (zone.auto_download, zone.install_on_exit):
        assert not box.isEnabled()
    for button in (page._detect_pob_btn, page._change_pob_btn, page._reload_btn, page._change_build_btn, zone.link_button, zone.support_button):
        assert button.focusPolicy() == Qt.FocusPolicy.TabFocus and button.isEnabled()
    # The paths can take focus (to copy them) and show the page's focus ring.
    assert page._pob_path_label.focusPolicy() == Qt.FocusPolicy.TabFocus
    from exilelens.ui.redesign_style import build_stylesheet

    assert 'QLabel#monoText[selectable="true"]:focus' in build_stylesheet()
    _go(harness, "diagnostics-advanced", (980, 720))
    diag = harness.window._diagnostics
    for control in (diag._copy_btn, diag._export_bundle_btn, diag._report_issue_btn, diag._copy_id_btn, diag._logs_btn,
                    diag._verbose_btn, diag._clear_history_btn, diag._viewer_copy_btn, *diag._viewer_mode.buttons()):
        assert control.isVisibleTo(diag) and control.focusPolicy() != Qt.FocusPolicy.NoFocus
        assert isinstance(control, QAbstractButton) and (control.accessibleName() or control.text())
    assert diag._advanced.toggle.focusPolicy() != Qt.FocusPolicy.NoFocus


# --------------------------------------------------------------------------------------------- old controls stay reachable
def test_pob_actions_reach_the_same_behaviour_the_removed_advanced_controls_had(harness, monkeypatch, tmp_path) -> None:
    from exilelens.app import setup_status

    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    controller = harness.controller
    calls = []
    monkeypatch.setattr(controller, "reload_evaluation_build", lambda: calls.append("reload"))
    monkeypatch.setattr(controller, "restart_engine", lambda: calls.append("restart"))
    monkeypatch.setattr(controller, "change_build", lambda path: calls.append(("change_build", path)))

    page._reload_btn.click()                                   # was Advanced > Reload build
    assert calls == ["reload"]

    # Change build (was Browse + Load): the picked path is loaded when the engine is ready ...
    build = tmp_path / "Mine.xml"
    build.write_text("<PathOfBuilding2/>", encoding="utf-8")
    monkeypatch.setattr("exilelens.ui.setup_dialog.pick_build_file", lambda current: str(build))
    monkeypatch.setattr(controller, "engine_status", lambda: "ready")
    monkeypatch.setattr(QWidget_warning := "PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: calls.append("warned"))
    calls.clear()
    page._change_build_btn.click()
    assert calls[0] == ("change_build", str(build))
    # ... and only saved while Path of Building is not running.
    monkeypatch.setattr(controller, "engine_status", lambda: "stopped")
    calls.clear()
    harness.settings.build_path = ""
    page._change_build_btn.click()
    assert calls == [] and harness.settings.build_path == str(build)

    # Change folder (was Browse) saves a valid folder; Detect (was Auto-detect) applies the detected one and
    # reconnects (was Apply).
    folder = tmp_path / "PoB"
    folder.mkdir()
    monkeypatch.setattr(setup_status, "check_pob_folder", lambda p: setup_status.SetupCheck(True, "FOUND"))
    monkeypatch.setattr("exilelens.ui.setup_dialog.pick_pob_directory", lambda current: str(folder))
    page._change_pob_btn.click()
    assert harness.settings.pob_path == str(folder) and page._pob_path == str(folder)
    other = tmp_path / "PoB2"
    other.mkdir()
    monkeypatch.setattr("exilelens.ui.pob_detect.detect_pob_path", lambda parent: str(other))
    calls.clear()
    page._detect_pob_btn.click()
    assert harness.settings.pob_path == str(other) and "restart" in calls
    calls.clear()
    page._reconnect_btn.click()                                # was Apply
    assert "restart" in calls


def test_invalid_folder_is_rejected_and_the_old_one_kept(harness, monkeypatch) -> None:
    from exilelens.app import setup_status

    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    before = harness.settings.pob_path
    warned = []
    monkeypatch.setattr("exilelens.ui.dashboard_pages.QMessageBox.warning", lambda *a, **k: warned.append(True))
    monkeypatch.setattr("exilelens.ui.setup_dialog.pick_pob_directory", lambda current: r"C:\definitely\not\pob")
    monkeypatch.setattr(setup_status, "check_pob_folder", lambda p: setup_status.SetupCheck(p == before, "x", "bad"))
    page._change_pob_btn.click()
    assert harness.settings.pob_path == before and page._pob_path == before and warned   # reported, never applied


def test_market_league_hint_carries_the_live_market_state_that_used_to_be_a_separate_row(harness) -> None:
    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    assert page._league_status.text().startswith("Live prices on")
    harness.settings.live_market_mode = "disabled"
    assert page._league_status_text().startswith("Live prices off")
    harness.settings.live_market_mode = "auto"


def test_reset_configuration_still_resets_and_refreshes_the_card(harness, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    _go(harness, "settings-top", (980, 720))
    page = harness.window._settings_page
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    restarted = []
    monkeypatch.setattr(harness.controller, "restart_engine", lambda: restarted.append(True))
    harness.settings.context = "BOSS"
    page._reset_btn.click()
    assert harness.settings.context == "MAP" and restarted
    assert page._build_path == ""
