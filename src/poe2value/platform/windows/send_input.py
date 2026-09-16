from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from poe2value.platform.windows.foreground_info import (
    evaluate_poe_foreground_match,
    get_foreground_window_info,
)
from poe2value.platform.windows.keyboard_state import is_shift_physically_down, keyboard_modifier_snapshot
from poe2value.platform.windows.low_level_keyboard import EXILELENS_INJECT_TAG

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else wintypes.ULONG


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def _configure_user32(api: Any) -> None:
    if api is None:
        return
    api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    api.SendInput.restype = wintypes.UINT


if user32 is not None:
    _configure_user32(user32)


def input_structure_size() -> int:
    return ctypes.sizeof(INPUT)


def _key_event(vk: int, key_up: bool = False) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(
        wVk=vk,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if key_up else 0,
        time=0,
        dwExtraInfo=EXILELENS_INJECT_TAG,
    )
    return inp


def build_ctrl_c_input_sequence() -> tuple[INPUT, INPUT, INPUT, INPUT]:
    return (
        _key_event(VK_CONTROL, False),
        _key_event(VK_C, False),
        _key_event(VK_C, True),
        _key_event(VK_CONTROL, True),
    )


def _last_error() -> int:
    if kernel32 is None:
        return 0
    return int(kernel32.GetLastError() or 0)


@dataclass(frozen=True)
class SendInputResult:
    ok: bool
    requested: int
    inserted: int
    last_error: int
    failure_stage: str
    foreground: dict[str, Any] | None = None
    poe_match: dict[str, Any] | None = None
    modifiers: dict[str, bool] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "requested": self.requested,
            "inserted": self.inserted,
            "last_error": self.last_error,
            "failure_stage": self.failure_stage,
            "foreground": self.foreground,
            "poe_match": self.poe_match,
            "modifiers": self.modifiers,
        }


def send_ctrl_c_to_foreground(
    *,
    require_poe_foreground: bool = True,
    require_shift_released: bool = True,
) -> SendInputResult:
    """Send one Ctrl+C chord to the foreground window (PoE2 copy item)."""
    from poe2value.security_audit import send_input_disabled

    if send_input_disabled():
        return SendInputResult(
            ok=False,
            requested=4,
            inserted=0,
            last_error=0,
            failure_stage="audit_disabled",
            foreground=None,
            poe_match=None,
            modifiers=None,
        )
    fg = get_foreground_window_info()
    fg_dict = fg.to_dict() if fg is not None else None
    poe_match = evaluate_poe_foreground_match()
    from poe2value.platform.windows.low_level_keyboard import hook_modifier_snapshot

    hook_modifiers = hook_modifier_snapshot()
    modifiers = hook_modifiers if hook_modifiers is not None else keyboard_modifier_snapshot()

    if user32 is None:
        return SendInputResult(
            ok=False,
            requested=4,
            inserted=0,
            last_error=0,
            failure_stage="not_windows",
            foreground=fg_dict,
            poe_match=poe_match,
            modifiers=modifiers,
        )

    # CP-04A: Ctrl+C injection has no bypass. The argument remains for API
    # compatibility with old diagnostics, but authorization is unconditional.
    if not bool(poe_match.get("accepted")):
        return SendInputResult(
            ok=False,
            requested=4,
            inserted=0,
            last_error=0,
            failure_stage="foreground_guard",
            foreground=fg_dict,
            poe_match=poe_match,
            modifiers=modifiers,
        )

    if require_shift_released and any(modifiers.get(name, False) for name in ("shift", "alt", "win")):
        return SendInputResult(
            ok=False,
            requested=4,
            inserted=0,
            last_error=0,
            failure_stage="modifier_still_down",
            foreground=fg_dict,
            poe_match=poe_match,
            modifiers=modifiers,
        )

    inputs = build_ctrl_c_input_sequence()
    array = (INPUT * len(inputs))(*inputs)
    inserted = int(
        user32.SendInput(
            len(inputs),
            ctypes.cast(array, ctypes.POINTER(INPUT)),
            ctypes.sizeof(INPUT),
        )
    )
    last_error = _last_error() if inserted != len(inputs) else 0
    if inserted == len(inputs):
        return SendInputResult(
            ok=True,
            requested=len(inputs),
            inserted=inserted,
            last_error=0,
            failure_stage="success",
            foreground=fg_dict,
            poe_match=poe_match,
            modifiers=modifiers,
        )
    stage = "sendinput_partial" if inserted > 0 else "sendinput_rejected"
    return SendInputResult(
        ok=False,
        requested=len(inputs),
        inserted=inserted,
        last_error=last_error,
        failure_stage=stage,
        foreground=fg_dict,
        poe_match=poe_match,
        modifiers=modifiers,
    )


def probe_send_ctrl_c(*, require_poe_foreground: bool = True) -> dict[str, Any]:
    """Real Windows probe for SendInput + clipboard sequence (dev/diagnostic)."""
    from poe2value.platform.windows.clipboard_identity import read_clipboard_sequence_number

    before = read_clipboard_sequence_number()
    result = send_ctrl_c_to_foreground(
        require_poe_foreground=require_poe_foreground,
        require_shift_released=False,
    )
    after = read_clipboard_sequence_number()
    return {
        "input_structure_bytes": input_structure_size(),
        "clipboard_sequence_before": before,
        "clipboard_sequence_after": after,
        "clipboard_advanced": (
            before is not None and after is not None and int(after) > int(before)
        ),
        "send_input": result.to_dict(),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(probe_send_ctrl_c(), indent=2))
