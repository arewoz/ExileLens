"""What's New in the real dashboard: when it opens, what dismisses it, and every way back to it."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the dashboard harness uses Windows-only capture helpers")
_ROOT = Path(__file__).resolve().parents[1]

from exilelens.app.updates.version import ExileLensVersion  # noqa: E402
from exilelens.whats_new import content  # noqa: E402

V = ExileLensVersion.parse


def _hl(ident, introduced, priority=10, link=None, text="One plain sentence about the change."):
    return {"id": ident, "title": ident.replace("-", " ").title(), "text": text, "introduced": introduced,
            "priority": priority, "link": link}


def _rel(version, previous, highlights=(), minor=(), limitations=(), action=None):
    return {"version": version, "released": "2026-10-04", "previous": previous, "highlights": list(highlights),
            "minor": [{"id": f"m-{version.replace('.', '')}-{i}", "text": t, "introduced": version} for i, t in enumerate(minor)],
            "limitations": [{"id": f"l-{version.replace('.', '')}-{i}", "text": t, "introduced": version} for i, t in enumerate(limitations)],
            "action": action}


def _catalog(*releases):
    return content.parse_document({"schema": 1, "releases": list(releases)})


CATALOG = _catalog(
    _rel("0.7.0", "0.6.0", [_hl("alpha", "0.7.0", 1), _hl("beta", "0.7.0", 2)], ["Old fix."]),
    _rel("0.8.0", "0.7.0",
         [_hl("gamma", "0.8.0", 1, {"label": "Open Settings", "destination": "settings"}), _hl("delta", "0.8.0", 2)],
         ["New fix one.", "New fix two."], ["Beta only."]),
)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "scripts"))
    monkeypatch.syspath_prepend(str(_ROOT))
    qa = importlib.import_module("ui_visual_qa")
    original = os.environ.get("LOCALAPPDATA")
    instance = qa.Harness(tmp_path)
    flow = instance.window.release_notes
    flow.auto_enabled = True
    flow.installed = V("0.8.0")
    flow._catalog_provider = lambda: CATALOG
    flow._navigate = instance.window.open_destination
    flow.settle_seconds = 0.4
    instance.flow = flow
    instance.opened = []
    from PySide6.QtGui import QDesktopServices

    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: instance.opened.append(url.toString()) or True))
    instance.window.hide()
    _settle(instance)
    yield instance
    if flow.dialog is not None:
        flow.dialog.close()
    instance.controller.shutdown()
    instance.window.close()
    if original is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original


def _settle(h, n: int = 30) -> None:
    for _ in range(n):
        h.app.processEvents()


def _wait(ms: int) -> None:
    from PySide6.QtTest import QTest

    QTest.qWait(ms)


def _open_dashboard(h) -> None:
    h.window.hide()
    h.window.show_dashboard()
    _settle(h)


def _saved_version() -> str:
    from exilelens.app.settings import load_settings_result

    return load_settings_result().settings.last_seen_release_notes_version


# ------------------------------------------------------------------------------------------------ trigger
def test_tray_only_startup_never_creates_a_dialog(harness) -> None:
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _settle(harness)
    assert harness.flow.dialog is None and harness.flow.pending()
    harness.window.hide()
    _wait(100)
    assert harness.flow.dialog is None


def test_upgrade_shows_once_when_the_player_opens_the_dashboard(harness) -> None:
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(harness)
    dialog = harness.flow.dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.windowTitle() == "What's new in ExileLens 0.8.0"
    assert dialog.meta_label.text() == "Updated from 0.7.0 · No action needed"
    assert harness.settings.last_seen_release_notes_version == "0.7.0"      # shown is not seen
    dialog.close_button.click()
    _settle(harness)
    assert harness.flow.dialog is None and harness.settings.last_seen_release_notes_version == "0.8.0"
    _open_dashboard(harness)
    assert harness.flow.dialog is None


def test_legacy_profile_without_a_stored_version_sees_the_installed_notes_once(harness) -> None:
    assert harness.settings.last_seen_release_notes_version == ""
    _open_dashboard(harness)
    dialog = harness.flow.dialog
    assert dialog is not None and "Updated from" not in dialog.meta_label.text()
    dialog.close_button.click()
    _settle(harness)
    _open_dashboard(harness)
    assert harness.flow.dialog is None


@pytest.mark.parametrize("stored", ["0.8.0", "0.9.0"])
def test_same_version_and_downgrade_never_show(harness, stored) -> None:
    harness.settings.last_seen_release_notes_version = stored
    _open_dashboard(harness)
    assert harness.flow.dialog is None and not harness.flow.pending()


def test_source_runs_do_not_show_automatically_but_keep_the_manual_entry_points(harness) -> None:
    harness.flow.auto_enabled = False
    _open_dashboard(harness)
    assert harness.flow.dialog is None
    assert harness.flow.show_manual() and harness.flow.dialog is not None


@pytest.mark.parametrize("state", ["setup", "pob-missing", "disconnected", "build-failed"])
def test_setup_states_defer_without_marking_anything_seen(harness, state) -> None:
    harness.set_state(state)
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(harness)
    _wait(60)
    assert harness.flow.dialog is None and harness.settings.last_seen_release_notes_version == "0.7.0"
    harness.set_state("ready")
    _open_dashboard(harness)
    assert harness.flow.dialog is not None


def test_orange_needs_attention_states_do_not_block(harness) -> None:
    harness.set_state("attention")
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(harness)
    assert harness.flow.dialog is not None


def test_a_transient_connecting_state_settles_without_blocking_the_ui(harness) -> None:
    harness.set_state("connecting")
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(harness)
    assert harness.flow.dialog is None                  # waiting: no dialog yet, and this call returned immediately
    harness.set_state("ready")
    _wait(500)
    assert harness.flow.dialog is not None


def test_a_state_that_never_settles_defers_to_the_next_open(harness) -> None:
    harness.set_state("connecting")
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(harness)
    _wait(700)                                           # settle_seconds is 0.4 in this harness
    assert harness.flow.dialog is None
    harness.set_state("ready")
    _settle(harness)
    assert harness.flow.dialog is None                   # no timer left running
    _open_dashboard(harness)
    assert harness.flow.dialog is not None


def test_the_one_time_privacy_card_is_not_a_blocker(harness) -> None:
    harness.consent_card(True)
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(harness)
    assert harness.flow.dialog is not None


def test_never_stacks_over_another_modal_or_the_setup_window(harness) -> None:
    from exilelens.ui.privacy_panel import CollectedDialog

    harness.settings.last_seen_release_notes_version = "0.7.0"
    modal = CollectedDialog(None, harness.window)
    modal.open()
    _settle(harness)
    _open_dashboard(harness)
    assert harness.flow.dialog is None
    modal.close()
    _settle(harness)
    harness.flow._blocked = lambda: True
    _open_dashboard(harness)
    assert harness.flow.dialog is None


@pytest.mark.parametrize("provider", [lambda: None, lambda: _catalog(_rel("0.5.0", None, [_hl("old-news", "0.5.0")]))])
def test_missing_or_unmatched_notes_fail_closed(harness, provider) -> None:
    harness.flow._catalog_provider = provider
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(harness)          # re-syncs the entry points
    assert harness.flow.dialog is None and not harness.flow.has_notes() and not harness.flow.show_manual()
    assert not harness.window._rail.version_button().is_interactive()
    assert harness.window._rail.version_text() == "ExileLens 0.7.0b1"


# ------------------------------------------------------------------------------------------------ seen semantics
def _shown(h):
    h.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(h)
    assert h.flow.dialog is not None
    return h.flow.dialog


def test_escape_marks_seen(harness) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog = _shown(harness)
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    _settle(harness)
    assert not dialog.isVisible() and _saved_version() == "0.8.0"


def test_title_bar_close_marks_seen(harness) -> None:
    dialog = _shown(harness)
    dialog.close()
    _settle(harness)
    assert harness.flow.dialog is None and _saved_version() == "0.8.0"


def test_enter_and_space_on_done_dismiss(harness) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog = _shown(harness)
    assert dialog.close_button.hasFocus() and dialog.close_button.isDefault()
    QTest.keyClick(dialog.close_button, Qt.Key.Key_Space)
    _settle(harness)
    assert _saved_version() == "0.8.0"
    harness.settings.last_seen_release_notes_version = "0.7.0"
    _open_dashboard(harness)
    QTest.keyClick(harness.flow.dialog, Qt.Key.Key_Return)
    _settle(harness)
    assert harness.flow.dialog is None


def test_full_release_notes_opens_github_and_neither_closes_nor_marks_seen(harness) -> None:
    dialog = _shown(harness)
    assert dialog.link_button.text() == "Full release notes"
    dialog.link_button.click()
    _settle(harness)
    assert harness.opened == ["https://github.com/arewoz/ExileLens/releases/tag/v0.8.0"]
    assert dialog.isVisible() and harness.settings.last_seen_release_notes_version == "0.7.0" and _saved_version() != "0.8.0"


def test_a_crash_before_dismissal_shows_the_notes_again(harness) -> None:
    from exilelens.app.settings import AppSettings

    dialog = _shown(harness)
    # The process dies here: nothing was written, so a fresh run with the same profile still has the old value.
    assert _saved_version() in ("", "0.7.0") and _saved_version() != "0.8.0"
    reopened = AppSettings.from_dict({"last_seen_release_notes_version": "0.7.0"})
    from exilelens.whats_new import trigger

    assert trigger.evaluate(reopened, V("0.8.0"), CATALOG) is not None
    dialog.close()


def test_a_highlight_link_marks_seen_then_navigates(harness) -> None:
    harness.window.navigate("overview")
    dialog = _shown(harness)
    assert [b.text() for b in dialog.links] == ["Open Settings"]
    dialog.links[0].click()
    _settle(harness)
    assert harness.flow.dialog is None and _saved_version() == "0.8.0"
    assert harness.window.current_page_id() == "settings"


@pytest.mark.parametrize(
    ("destination", "page"),
    [("overview", "overview"), ("build_analysis", "build_analysis"), ("diagnostics", "diagnostics"), ("updates", "settings")],
)
def test_every_allowlisted_destination_opens_its_page(harness, destination, page) -> None:
    harness.window.open_destination(destination)
    assert harness.window.current_page_id() == page


def test_unknown_destinations_do_nothing(harness) -> None:
    harness.window.navigate("diagnostics")
    harness.window.open_destination("https://example.com")
    harness.window.open_destination("quit")
    assert harness.window.current_page_id() == "diagnostics"


def test_skipped_releases_show_one_cumulative_dialog_and_no_second_one(harness) -> None:
    harness.settings.last_seen_release_notes_version = "0.6.0"
    _open_dashboard(harness)
    dialog = harness.flow.dialog
    assert dialog.windowTitle() == "What's new since ExileLens 0.6.0"
    assert dialog.meta_label.text() == "Updated from 0.6.0 to 0.8.0 · No action needed"
    text = dialog.visible_text()
    assert "Alpha" in text and "Gamma" in text and "0.7.0" in text and "0.8.0" in text
    dialog.close_button.click()
    _settle(harness)
    assert harness.flow.dialog is None
    _open_dashboard(harness)
    assert harness.flow.dialog is None


# ------------------------------------------------------------------------------------------------ the dialog
def test_dialog_shell_size_and_structure(harness) -> None:
    from PySide6.QtWidgets import QTabWidget

    harness.window.resize(980, 720)
    dialog = _shown(harness)
    assert dialog.width() == 560 and dialog.height() <= int(harness.window.height() * 0.75) + 1
    assert dialog.close_button.text() == "Done" and dialog.close_button.isDefault()
    assert dialog.close_button.objectName() == "btnPrimary" and dialog.link_button.objectName() == "btnTertiary"
    assert not dialog.findChildren(QTabWidget)
    text = dialog.visible_text()
    assert "Fixes and smaller improvements" in text and "Known limitations" in text and "Beta only." in text
    assert "R2" not in text and "gamma" not in text            # headline is the title, never the stable id


def test_long_content_scrolls_in_the_body_only_and_keeps_header_and_footer(harness) -> None:
    from exilelens.ui.whats_new_dialog import WhatsNewDialog

    long_release = _rel("0.8.0", "0.7.0", [_hl(f"item-{i}", "0.8.0", i, text="A longer sentence. " * 6) for i in range(1, 5)],
                        [f"Smaller improvement number {i} with a bit more words in it." for i in range(6)], ["Limit one.", "Limit two."])
    summary = content.automatic_summary(_catalog(long_release), V("0.8.0"), V("0.7.0"))
    harness.window.resize(720, 560)
    dialog = WhatsNewDialog(summary, parent=harness.window)
    dialog.open()
    _settle(harness)
    assert dialog.height() <= int(harness.window.height() * 0.75) + 1
    bar = dialog._scroll.verticalScrollBar()
    assert bar.maximum() > 0 and dialog.close_button.isVisible() and dialog.link_button.isVisible()
    assert dialog._header.property("scrolled") in (None, False)
    bar.setValue(bar.maximum())
    _settle(harness)
    assert dialog._header.property("scrolled") is True
    dialog.close()


def test_action_note_comes_first_with_its_link(harness) -> None:
    from exilelens.ui.whats_new_dialog import WhatsNewDialog

    release = _rel("0.8.0", "0.7.0", [_hl("a-thing", "0.8.0")],
                   action={"text": "Set the shortcut again if it stops working.", "link": {"label": "Open Settings", "destination": "settings"}})
    summary = content.automatic_summary(_catalog(release), V("0.8.0"), V("0.7.0"))
    assert summary.meta == "Updated from 0.7.0 · One thing to check"
    dialog = WhatsNewDialog(summary, parent=harness.window)
    dialog.open()
    _settle(harness)
    assert dialog.visible_text().index("One thing to check.") < dialog.visible_text().index("A Thing")
    assert [b.text() for b in dialog.links] == ["Open Settings"]
    dialog.close()


def test_keyboard_and_accessibility_contract(harness) -> None:
    from PySide6.QtCore import Qt

    dialog = _shown(harness)
    assert dialog.accessibleName() == "What's new in ExileLens 0.8.0"
    assert dialog.link_button.accessibleName() == "Full release notes, opens GitHub in your browser"
    assert dialog._scroll.focusPolicy() == Qt.FocusPolicy.TabFocus      # the body is a focus stop (arrows, PgUp/PgDn, Home/End)
    assert dialog.isModal()
    flags = dialog.windowFlags()
    assert not flags & Qt.WindowType.WindowMinimizeButtonHint and not flags & Qt.WindowType.WindowMaximizeButtonHint
    assert not dialog.isSizeGripEnabled()


# ------------------------------------------------------------------------------------------------ entry points
def test_rail_version_opens_the_installed_notes_for_the_installed_version_only(harness) -> None:
    harness.flow.installed = V("0.8.0")
    harness.window._rail.set_whats_new_available("0.8.0")
    harness.settings.last_seen_release_notes_version = "0.6.0"     # a skipped-release state must not leak into a manual open
    _open_dashboard(harness)
    harness.flow.dialog.close()
    _settle(harness)
    button = harness.window._rail.version_button()
    assert button.is_interactive() and button.toolTip() == "What's new in 0.8.0" and button.text() == "ExileLens 0.7.0b1"
    button.click()
    _settle(harness)
    dialog = harness.flow.dialog
    assert dialog.windowTitle() == "What's new in ExileLens 0.8.0" and dialog.meta_label.text() == "Released 4 Oct 2026"
    assert "Alpha" not in dialog.visible_text()
    dialog.close()


def test_rail_version_is_plain_text_without_notes_and_hidden_when_compact(harness) -> None:
    harness.flow._catalog_provider = lambda: None
    harness.window._sync_whats_new_entry()
    button = harness.window._rail.version_button()
    assert not button.is_interactive() and button.toolTip() == ""
    from PySide6.QtCore import Qt

    assert button.focusPolicy() == Qt.FocusPolicy.NoFocus and button.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    harness.flow._catalog_provider = lambda: CATALOG
    harness.window._sync_whats_new_entry()
    assert button.focusPolicy() == Qt.FocusPolicy.TabFocus
    harness.window.resize(720, 560)
    _settle(harness)
    assert harness.window._rail.is_compact() and not harness.window._rail._version_row_widget.isVisible()
    assert not any("new" in b.text().lower() for b in harness.window._rail.findChildren(type(button)) if b is not button and b.text())


def _updates_panel(h):
    h.window.navigate("settings")
    _settle(h)
    return h.window._settings_page._updates_panel


@pytest.mark.parametrize("state", ["current", "ahead", "failed", "unavailable"])
def test_settings_updates_show_the_installed_links(harness, state) -> None:
    panel = _updates_panel(harness)
    harness.update(state, "0.6.0")
    assert not panel._installed_links.isHidden()
    assert panel._whats_new_btn.text() == "What's new" and panel._full_notes_btn.text() == "Full release notes"
    panel._full_notes_btn.click()
    assert harness.opened[-1].endswith("/releases/tag/v0.8.0")
    panel._whats_new_btn.click()
    _settle(harness)
    assert harness.flow.dialog is not None and harness.flow.dialog.meta_label.text().startswith("Released")


@pytest.mark.parametrize(
    ("state", "download"), [("available", None), ("available", "downloading"), ("available", "ready"), ("verification_failed", None)]
)
def test_settings_updates_stay_clean_when_the_row_is_about_an_update(harness, state, download) -> None:
    panel = _updates_panel(harness)
    harness.update(state, "0.9.0", download=download)
    assert panel._installed_links.isHidden()


def test_settings_updates_without_notes_offer_only_the_github_link(harness) -> None:
    harness.flow._catalog_provider = lambda: None
    panel = _updates_panel(harness)
    harness.update("current", "0.7.0b1")
    assert panel._whats_new_btn.isHidden() and not panel._full_notes_btn.isHidden()


def test_the_pre_install_github_button_is_called_full_release_notes(harness) -> None:
    button = harness.window._update_notice_whats_new
    assert button.text() == "Full release notes"
    assert "What's new" not in [b.text() for b in harness.window._update_notice.findChildren(type(button))]


# ------------------------------------------------------------------------------------------------ update notice interaction
def _tray(pending: bool):
    shown = []
    tray = SimpleNamespace(
        dashboard=SimpleNamespace(release_notes=SimpleNamespace(pending=lambda: pending)),
        showMessage=lambda *args: shown.append(args),
    )
    tray._whats_new_will_acknowledge = lambda: __import__("exilelens.ui.tray", fromlist=["TrayManager"]).TrayManager._whats_new_will_acknowledge(tray)
    return tray, shown


def _notice(kind: str):
    return SimpleNamespace(kind=kind, title="t", message="m")


def test_the_success_notice_is_dropped_only_when_whats_new_will_acknowledge(harness) -> None:
    from exilelens.ui.tray import TrayManager

    tray, shown = _tray(pending=True)
    TrayManager._show_install_outcome(tray, _notice("updated"))
    assert shown == []
    tray, shown = _tray(pending=False)
    TrayManager._show_install_outcome(tray, _notice("updated"))
    assert len(shown) == 1


@pytest.mark.parametrize("kind", ["restored", "failed", "not_installed"])
def test_failure_and_rollback_notices_are_never_suppressed(harness, kind) -> None:
    from exilelens.ui.tray import TrayManager

    tray, shown = _tray(pending=True)
    TrayManager._show_install_outcome(tray, _notice(kind))
    assert len(shown) == 1


def test_fresh_install_hook_records_without_writing_a_file(tmp_path, monkeypatch) -> None:
    from exilelens.app.main import ExileLensApp
    from exilelens.app.settings import AppSettings, SettingsLoadResult

    app = SimpleNamespace(settings=AppSettings())
    ExileLensApp._record_fresh_install_release_notes(app, SettingsLoadResult(app.settings, loaded_from_disk=False))
    from exilelens._version import __version__

    assert app.settings.last_seen_release_notes_version == __version__
    existing = SimpleNamespace(settings=AppSettings())
    ExileLensApp._record_fresh_install_release_notes(existing, SettingsLoadResult(existing.settings, loaded_from_disk=True))
    assert existing.settings.last_seen_release_notes_version == ""
