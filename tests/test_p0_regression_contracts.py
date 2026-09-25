"""Executable P0 regression contracts for the release 0.4.0b1 gate.

These tests deliberately exercise the production Qt/controller paths while keeping
the OS-owned hooks themselves out of the deterministic test boundary.  Windows
registration still requires packaged-runtime validation; the state transitions
after a hook or clipboard notification are fully executable here.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.app.settings import AppSettings

pytestmark = pytest.mark.itemcheck


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _market_ring() -> str:
    return """Item Class: Rings
Rarity: Rare
Test Ring
Sapphire Ring
--------
Item Level: 80
--------
+20 to maximum Life
"""


def test_hotkey_shift_c_after_focus_recovers_missed_keyup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A focus-loss missed KEYUP resets the real hook state and permits one new capture."""
    _app()
    import exilelens.app.price_check_hotkey as hotkey_module
    from exilelens.app.price_check_hotkey import PriceCheckHotkeyController
    from exilelens.platform.windows.hotkey_binding import HotkeyBinding
    from exilelens.platform.windows.low_level_keyboard import LowLevelKeyboardHook

    foreground = {"poe": True}
    monkeypatch.setattr(hotkey_module, "is_poe_foreground", lambda: foreground["poe"])
    monkeypatch.setattr(
        hotkey_module,
        "evaluate_poe_foreground_match",
        lambda: {"poe_match_result": "match", "accepted": foreground["poe"]},
    )
    hotkey = PriceCheckHotkeyController(release_wait_ms=100)
    hotkey._active = True
    hotkey._combo_physically_down = lambda: False  # type: ignore[method-assign]
    low = LowLevelKeyboardHook(HotkeyBinding.parse("shift+c"))
    hotkey.hook._low_level = low
    low.triggered.connect(hotkey.hook.triggered)
    low.binding_released.connect(hotkey.hook.binding_released)
    captured: list[tuple[int, object]] = []
    hotkey.capture_requested.connect(lambda request_id, anchor: captured.append((request_id, anchor)))

    # Normal hook path sees Shift+C and arms both matcher and chord tracker.
    low.process_key_event(vk=0x10, is_down=True, poe_foreground=True)
    low.process_key_event(vk=0x43, is_down=True, poe_foreground=True)
    _app().processEvents()
    assert hotkey.waiting_for_release
    assert low.chord_tracker.armed and low.matcher.key_down

    # Alt-Tab/focus loss swallows the KEYUP. The watchdog must cancel and reset.
    foreground["poe"] = False
    hotkey._on_release_watchdog()
    assert not hotkey.waiting_for_release
    assert not low.chord_tracker.armed
    assert not low.chord_tracker.binding_keys_down()
    assert not low.matcher.key_down

    # Back in PoE, one legitimate next press/release produces exactly one capture.
    foreground["poe"] = True
    low.process_key_event(vk=0x10, is_down=True, poe_foreground=True)
    low.process_key_event(vk=0x43, is_down=True, poe_foreground=True)
    _app().processEvents()
    low.process_key_event(vk=0x43, is_down=False, poe_foreground=True)
    low.process_key_event(vk=0x10, is_down=False, poe_foreground=True)
    _app().processEvents()
    assert len(captured) == 1
    assert captured[0][0] == 2
    assert not hotkey.waiting_for_release
    hotkey.deleteLater()


def test_item_capture_fail_rejects_empty_and_routes_real_watcher_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty owned Shift+C read fails visibly; watcher events still carry usable items."""
    _app()
    from exilelens.app.price_check_capture import PriceCheckCaptureCoordinator
    from exilelens.platform.windows.clipboard import ClipboardWatcher

    coordinator = PriceCheckCaptureCoordinator(
        send_copy=lambda: True,
        read_sequence=lambda: 1,
        read_text=lambda: "",
        is_poe_foreground_fn=lambda: True,
    )
    failed: list[tuple[int, str]] = []
    ready: list[tuple[int, str]] = []
    coordinator.capture_failed.connect(lambda request_id, message: failed.append((request_id, message)))
    coordinator.capture_ready.connect(lambda request_id, text, _anchor, _sequence: ready.append((request_id, text)))
    assert coordinator.begin_capture((120, 240), request_id=40) == 40
    assert coordinator.route_clipboard_event(text="", sequence=2, anchor_screen_px=(120, 240))
    assert failed == [(40, "Could not read hovered item.")]
    assert ready == []
    assert coordinator.is_idle

    # A failed owned capture must not strand the coordinator or replay stale text.
    assert coordinator.begin_capture((120, 240), request_id=41) == 41
    assert coordinator.route_clipboard_event(text=_market_ring(), sequence=2, anchor_screen_px=(120, 240))
    assert ready == [(41, _market_ring())]
    assert coordinator.is_idle

    watcher = ClipboardWatcher()
    # Win32 sequence identity is platform-owned; make this test prove the watcher
    # event path itself without depending on unrelated desktop clipboard traffic.
    monkeypatch.setattr(watcher, "_next_sequence", lambda: 41)
    received: list[object] = []
    watcher.clipboard_event.connect(received.append)

    assert watcher.inject_text("", sequence=40) is None
    event = watcher.inject_text(_market_ring(), sequence=41)

    assert event is not None
    assert received == [event]
    assert event.sequence == 41
    assert event.copy_anchor_screen_px is not None
    assert event.content_hash
    watcher.set_enabled(False)


def test_overlay_missing_item_check_first_paint_is_visible_and_onscreen() -> None:
    """Accepted Item Check first-paint reaches a visible, screen-clamped Qt overlay."""
    _app()
    from PySide6.QtGui import QGuiApplication
    from exilelens.ui.overlay import OverlayWindow

    overlay = OverlayWindow(AppSettings())
    overlay.set_anchor_cursor(11, (40, 40), physical_anchor=(40, 40))
    overlay.show_analyzing(11)
    _app().processEvents()

    assert overlay.isVisible()
    assert overlay.requested_visible
    screen = QGuiApplication.screenAt(overlay.frameGeometry().center()) or QGuiApplication.primaryScreen()
    assert screen is not None
    assert screen.availableGeometry().intersects(overlay.frameGeometry())
    overlay.dismiss()
    overlay.deleteLater()


def test_overlay_unrecoverable_native_production_wiring(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """A native Windows Qt session proves all production lifecycle wiring."""
    assert sys.platform == "win32", "overlay-unrecoverable is a native Windows release contract"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = _app()
    assert app.platformName().lower() == "windows"
    app.setQuitOnLastWindowClosed(False)

    from exilelens.app.main import ExileLensApp
    from exilelens.app.settings import settings_path
    from exilelens.platform.windows.mouse_hook import WM_LBUTTONDOWN
    from exilelens.ui.pinned_item_overlay import PinnedItemOverlay

    runtime = ExileLensApp()
    runtime.settings.context = "BOSS"
    quit_requested: list[bool] = []
    runtime._compose_primary_ui(quit_callback=lambda: quit_requested.append(True))

    def cleanup() -> None:
        from PySide6.QtCore import QCoreApplication, QEvent

        runtime.controller.shutdown()
        menu = runtime.tray.contextMenu()
        runtime.tray.setContextMenu(None)
        if menu is not None:
            menu.deleteLater()
        runtime.tray.deleteLater()
        runtime.dashboard.deleteLater()
        runtime.overlay.deleteLater()
        runtime.controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

    request.addfinalizer(cleanup)
    monkeypatch.setattr(runtime.controller.price_check_hotkey, "start", lambda: True)
    runtime._wire_signals()
    assert runtime.controller is not None
    assert runtime.overlay is not None
    assert runtime.dashboard is not None
    assert runtime.tray is not None
    controller = runtime.controller
    overlay = runtime.overlay

    # A real controller signal opens the real overlay. The OS hook itself is the
    # external boundary; its built-in simulator still traverses the production
    # MouseClickDismissHook.clicked -> ItemDismissController queued connection.
    controller.evaluation_started.emit(21)
    controller.analyzing.emit(21)
    app.processEvents()
    assert overlay.isVisible() and overlay.requested_visible
    dismissed_generation = controller.presentation_generation
    controller.item_dismiss._active = True
    controller.item_dismiss.hook.simulate_click(WM_LBUTTONDOWN)
    app.processEvents()
    assert controller.presentation_generation == dismissed_generation + 1
    assert not overlay.isVisible()
    assert not overlay.requested_visible

    stale_result = {
        "request_meta": {"request_id": 21, "presentation_generation": dismissed_generation},
        "presentation": {"item_name": "Stale result", "compact_surface": True},
    }
    controller.evaluation_finished.emit(21, stale_result)
    app.processEvents()
    assert not overlay.isVisible()
    assert not overlay.requested_visible

    # Substitute only the completed evaluation payload, then drive the real
    # overlay Pin button and the real pinned overlay Unpin button.
    result = {
        "raw_input": {"content_hash": "native-overlay-contract"},
        "pob_parse": {"display_name": "Native Contract Ring"},
        "recommendation": {"evaluation_outcome": {"verdict": "SIDEGRADE"}},
        "request_meta": {
            "request_id": 22,
            "presentation_generation": controller.presentation_generation,
        },
        "presentation": {
            "item_name": "Native Contract Ring",
            "rarity": "Rare",
            "base_type": "Sapphire Ring",
            "compact_surface": True,
            "surface_mode": "PASSIVE_COMPACT",
        },
    }
    controller._last_result = result
    controller.evaluation_started.emit(22)
    controller.evaluation_finished.emit(22, result)
    app.processEvents()
    assert overlay.isVisible()
    overlay._panel._pin_button.click()
    app.processEvents()
    assert not overlay.isVisible()
    assert len(controller._pinned_windows) == 1
    pinned = next(iter(controller._pinned_windows.values()))
    assert isinstance(pinned, PinnedItemOverlay)
    assert pinned.isVisible()
    assert controller._pin_compare.pinned_count() == 1

    pinned._unpin_btn.click()
    app.processEvents()
    assert controller._pinned_windows == {}
    assert controller._pin_compare.pinned_count() == 0
    assert not pinned.isVisible()

    # Trigger the QAction created by TrayManager.rebuild_menu(), not its handler.
    # The production composition's explicit callback seam intercepts only the
    # irreversible process-wide quit boundary.
    exit_action = next(action for action in runtime.tray.contextMenu().actions() if action.text() == "Exit")
    exit_action.trigger()
    app.processEvents()
    assert quit_requested == [True]
    saved = json.loads(settings_path().read_text(encoding="utf-8"))
    assert saved["context"] == "BOSS"
