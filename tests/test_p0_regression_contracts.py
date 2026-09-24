"""Executable P0 regression contracts for the release 0.4.0b1 gate.

These tests deliberately exercise the production Qt/controller paths while keeping
the OS-owned hooks themselves out of the deterministic test boundary.  Windows
registration still requires packaged-runtime validation; the state transitions
after a hook or clipboard notification are fully executable here.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from poe2value.app.settings import AppSettings

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
    import poe2value.app.price_check_hotkey as hotkey_module
    from poe2value.app.price_check_hotkey import PriceCheckHotkeyController
    from poe2value.platform.windows.hotkey_binding import HotkeyBinding
    from poe2value.platform.windows.low_level_keyboard import LowLevelKeyboardHook

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
    from poe2value.app.price_check_capture import PriceCheckCaptureCoordinator
    from poe2value.platform.windows.clipboard import ClipboardWatcher

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
    from poe2value.ui.overlay import OverlayWindow

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


def test_overlay_unrecoverable_click_pin_and_tray_exit_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dismiss, pin, and the actual tray Exit handler always leave a recovery path."""
    app = _app()
    from poe2value.app.item_dismiss import ItemDismissController
    from poe2value.platform.windows.mouse_hook import WM_LBUTTONDOWN
    from poe2value.ui.overlay import OverlayWindow
    from poe2value.ui.tray import TrayManager

    overlay = OverlayWindow(AppSettings())
    overlay.show_analyzing(21)
    controller = SimpleNamespace(
        has_inflight_gameplay_request=False,
        presentation_generation=3,
        invalidated=0,
    )
    controller.invalidate_presentation = lambda: setattr(controller, "invalidated", controller.invalidated + 1)
    dismiss = ItemDismissController()
    dismiss.bind(overlay=overlay, controller=controller)
    dismiss._active = True
    dismiss._on_hook_click(WM_LBUTTONDOWN, 0, 0)
    assert controller.invalidated == 1
    assert not overlay.isVisible()
    assert not overlay.requested_visible

    overlay.show_analyzing(22)
    pinned: list[bool] = []
    overlay.set_pin_handlers(on_pin=lambda: pinned.append(True) or True, can_pin=lambda: True)
    overlay._on_pin_clicked()
    assert pinned == [True]
    assert not overlay.isVisible()

    saved: list[bool] = []
    quit_called: list[bool] = []
    monkeypatch.setattr("poe2value.ui.tray.save_settings", lambda _settings: saved.append(True))
    monkeypatch.setattr(app, "quit", lambda: quit_called.append(True))
    tray_like = SimpleNamespace(
        dashboard=SimpleNamespace(_remember_geometry=lambda: None),
        overlay=SimpleNamespace(remember_position=lambda: None),
        settings=AppSettings(),
    )
    TrayManager._quit(tray_like)
    assert saved == [True]
    assert quit_called == [True]
    dismiss.stop()
    overlay.deleteLater()
