"""Explicit window interaction policies.

PASSIVE_OVERLAY: gameplay item overlay — click-through, dismissed by global click.
INTERACTIVE_TOOL: Tree Coach / Analyze Build / calibration wizard — real input.
INTERACTIVE_TRANSPARENT_CAPTURE: calibration capture — real input, visually transparent.
PERSISTENT_TREE_OVERLAY: live heatmap — click-through, not dismissed by global click.
"""

from __future__ import annotations

import ctypes
import sys
import weakref
from enum import Enum
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

_INTERACTIVE_WINDOWS: weakref.WeakSet[QWidget] = weakref.WeakSet()


class WindowInteractionPolicy(str, Enum):
    PASSIVE_OVERLAY = "passive_overlay"
    INTERACTIVE_TOOL = "interactive_tool"
    INTERACTIVE_PIN_AFFORDANCE = "interactive_pin_affordance"
    INTERACTIVE_OVERLAY_CHROME = "interactive_overlay_chrome"
    INTERACTIVE_TRANSPARENT_CAPTURE = "interactive_transparent_capture"
    PERSISTENT_TREE_OVERLAY = "persistent_tree_overlay"


def _win32() -> bool:
    return sys.platform == "win32"


def _exstyle_api() -> tuple[Any, Any] | None:
    if not _win32():
        return None
    user32 = ctypes.windll.user32
    getter = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    setter = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    getter.restype = ctypes.c_ssize_t
    getter.argtypes = [ctypes.c_void_p, ctypes.c_int]
    setter.restype = ctypes.c_ssize_t
    setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    return getter, setter


def native_extended_style(widget: QWidget) -> int:
    api = _exstyle_api()
    if api is None:
        return 0
    getter, _setter = api
    return int(getter(int(widget.winId()), GWL_EXSTYLE) or 0)


def apply_native_extended_style(widget: QWidget, policy: WindowInteractionPolicy) -> None:
    api = _exstyle_api()
    if api is None:
        return
    getter, setter = api
    hwnd = int(widget.winId())
    style = int(getter(hwnd, GWL_EXSTYLE) or 0)
    if policy in {WindowInteractionPolicy.PASSIVE_OVERLAY, WindowInteractionPolicy.PERSISTENT_TREE_OVERLAY}:
        style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        style &= ~WS_EX_APPWINDOW
    elif policy in {
        WindowInteractionPolicy.INTERACTIVE_PIN_AFFORDANCE,
        WindowInteractionPolicy.INTERACTIVE_OVERLAY_CHROME,
    }:
        style |= WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE
        style &= ~(WS_EX_TRANSPARENT | WS_EX_APPWINDOW)
    else:
        style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        style |= WS_EX_APPWINDOW | WS_EX_TOPMOST
    setter(hwnd, GWL_EXSTYLE, style)


def register_interactive_window(widget: QWidget) -> None:
    _INTERACTIVE_WINDOWS.add(widget)


def unregister_interactive_window(widget: QWidget) -> None:
    _INTERACTIVE_WINDOWS.discard(widget)


def _widget_geometry_contains(widget: QWidget, x: int, y: int) -> bool:
    handle = widget.windowHandle()
    ratio = float(handle.devicePixelRatio()) if handle is not None else 1.0
    if ratio <= 0:
        ratio = 1.0
    geo = widget.frameGeometry()
    local_x = int(round(x / ratio))
    local_y = int(round(y / ratio))
    return geo.contains(local_x, local_y) or geo.contains(int(x), int(y))


def _is_overlay_chrome_control(widget: QWidget) -> bool:
    from PySide6.QtWidgets import QAbstractButton, QAbstractSlider, QComboBox, QLineEdit, QAbstractSpinBox

    return isinstance(
        widget,
        (QAbstractButton, QAbstractSlider, QComboBox, QLineEdit, QAbstractSpinBox),
    )


def _control_under_point(root: QWidget, x: int, y: int) -> bool:
    from PySide6.QtWidgets import QApplication

    handle = root.windowHandle()
    ratio = float(handle.devicePixelRatio()) if handle is not None else 1.0
    if ratio <= 0:
        ratio = 1.0
    hits = (
        QApplication.widgetAt(int(round(x / ratio)), int(round(y / ratio))),
        QApplication.widgetAt(int(x), int(y)),
    )
    for hit in hits:
        if hit is None:
            continue
        ancestor: QWidget | None = hit
        belongs = False
        while ancestor is not None:
            if ancestor is root:
                belongs = True
                break
            ancestor = ancestor.parentWidget()
        if not belongs:
            continue
        current: QWidget | None = hit
        while current is not None:
            if _is_overlay_chrome_control(current):
                return True
            if current is root:
                break
            current = current.parentWidget()
    return False


def interactive_window_contains(x: int, y: int) -> bool:
    """True when a global (physical or logical) point is inside an interactive tool."""
    for widget in list(_INTERACTIVE_WINDOWS):
        try:
            if widget is None or not widget.isVisible():
                continue
            if widget.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen):
                continue
            if _widget_geometry_contains(widget, x, y):
                return True
        except RuntimeError:
            continue
    return False


def click_blocks_item_dismiss(x: int, y: int) -> bool:
    """True when a click must not dismiss the item overlay.

    Dashboard / Tree Coach / pin affordance swallow the click. The gameplay
    overlay is interactive only on chrome (Pin, More info, Close). Clicks on the
    card body still dismiss, matching the original click-to-dismiss contract.
    """
    for widget in list(_INTERACTIVE_WINDOWS):
        try:
            if widget is None or not widget.isVisible():
                continue
            if widget.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen):
                continue
            if not _widget_geometry_contains(widget, x, y):
                continue
            policy_value = str(widget.property("windowInteractionPolicy") or "")
            if policy_value == WindowInteractionPolicy.INTERACTIVE_OVERLAY_CHROME.value:
                if _control_under_point(widget, x, y):
                    return True
                continue
            return True
        except RuntimeError:
            continue
    return False


def _click_through_flags(transparent_input: Any, no_focus: Any) -> Qt.WindowType:
    flags = (
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
    )
    if transparent_input is not None:
        flags |= transparent_input
    if no_focus is not None:
        flags |= no_focus
    return flags


def apply_window_interaction_policy(
    widget: QWidget,
    policy: WindowInteractionPolicy,
    *,
    activate_on_show: bool = True,
) -> None:
    widget.setProperty("windowInteractionPolicy", policy.value)
    transparent_input = getattr(Qt.WindowType, "WindowTransparentForInput", None)
    no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)

    if policy in {WindowInteractionPolicy.PASSIVE_OVERLAY, WindowInteractionPolicy.PERSISTENT_TREE_OVERLAY}:
        unregister_interactive_window(widget)
        widget.setWindowFlags(_click_through_flags(transparent_input, no_focus))
        widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        return

    if policy is WindowInteractionPolicy.INTERACTIVE_PIN_AFFORDANCE or policy is WindowInteractionPolicy.INTERACTIVE_OVERLAY_CHROME:
        register_interactive_window(widget)
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        if no_focus is not None:
            flags |= no_focus
        widget.setWindowFlags(flags)
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        return

    if policy is WindowInteractionPolicy.INTERACTIVE_TRANSPARENT_CAPTURE:
        register_interactive_window(widget)
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        widget.setWindowFlags(flags)
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        return

    flags = widget.windowFlags()
    flags |= Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
    flags &= ~Qt.WindowType.FramelessWindowHint
    flags &= ~Qt.WindowType.Tool
    flags |= Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMinimizeButtonHint
    if transparent_input is not None:
        flags &= ~transparent_input
    if no_focus is not None:
        flags &= ~no_focus
    widget.setWindowFlags(flags)
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
    # Tree Coach must not steal keyboard focus from PoE2 on open. Clicks on the
    # coach still activate it; returning to the game restores Ctrl+C.
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not activate_on_show)
    register_interactive_window(widget)


def describe_interaction(widget: QWidget) -> dict[str, Any]:
    policy_value = widget.property("windowInteractionPolicy")
    try:
        policy = WindowInteractionPolicy(str(policy_value))
    except ValueError:
        policy = None
    flags = widget.windowFlags()
    transparent_input = getattr(Qt.WindowType, "WindowTransparentForInput", None)
    no_focus = getattr(Qt.WindowType, "WindowDoesNotAcceptFocus", None)
    native = native_extended_style(widget) if widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created) or widget.winId() else 0
    click_through = bool(widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
    if transparent_input is not None:
        click_through = click_through or bool(flags & transparent_input)
    if native:
        click_through = click_through or bool(native & WS_EX_TRANSPARENT)
    no_focus_flag = bool(no_focus and flags & no_focus)
    return {
        "policy": policy.value if policy else policy_value,
        "interactive": policy
        in {
            WindowInteractionPolicy.INTERACTIVE_TOOL,
            WindowInteractionPolicy.INTERACTIVE_TRANSPARENT_CAPTURE,
            WindowInteractionPolicy.INTERACTIVE_PIN_AFFORDANCE,
            WindowInteractionPolicy.INTERACTIVE_OVERLAY_CHROME,
        },
        "click_through": click_through,
        "wa_transparent_for_mouse": bool(widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)),
        "window_transparent_for_input": bool(transparent_input and flags & transparent_input),
        "window_does_not_accept_focus": no_focus_flag,
        "tool_window": bool(flags & Qt.WindowType.Tool),
        "ws_ex_transparent": bool(native & WS_EX_TRANSPARENT),
        "ws_ex_noactivate": bool(native & WS_EX_NOACTIVATE),
        "global_click_dismiss": policy is WindowInteractionPolicy.PASSIVE_OVERLAY,
        "persistent": policy is WindowInteractionPolicy.PERSISTENT_TREE_OVERLAY,
        "accepts_focus": policy
        in {
            WindowInteractionPolicy.INTERACTIVE_TOOL,
            WindowInteractionPolicy.INTERACTIVE_TRANSPARENT_CAPTURE,
        },
        "show_without_activating": bool(widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)),
    }
