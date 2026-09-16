from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32 if sys.platform == "win32" else None

VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_C = 0x43

# High bit set => key is currently held down.
_KEY_DOWN_MASK = 0x8000


def is_key_physically_down(vk: int) -> bool:
    """True when the given virtual key is physically down."""
    if user32 is None:
        return False
    state = int(user32.GetAsyncKeyState(int(vk)))
    return bool(state & _KEY_DOWN_MASK)


def is_shift_physically_down() -> bool:
    if user32 is None:
        return False
    return (
        is_key_physically_down(VK_SHIFT)
        or is_key_physically_down(VK_LSHIFT)
        or is_key_physically_down(VK_RSHIFT)
    )


def is_c_physically_down() -> bool:
    return is_key_physically_down(VK_C)


def is_ctrl_physically_down() -> bool:
    return (
        is_key_physically_down(VK_CONTROL)
        or is_key_physically_down(VK_LCONTROL)
        or is_key_physically_down(VK_RCONTROL)
    )


def is_price_check_combo_physically_down() -> bool:
    """True while Shift and/or C from the Price Check chord may still be held."""
    return is_shift_physically_down() or is_c_physically_down()


def is_hotkey_combo_physically_down(hotkey: str) -> bool:
    """True while the configured key or one of its non-Ctrl modifiers is down."""
    from poe2value.platform.windows.hotkey_binding import HotkeyBinding

    binding = HotkeyBinding.parse(hotkey)
    if is_key_physically_down(binding.vk):
        return True
    if "shift" in binding.modifiers and is_shift_physically_down():
        return True
    if "alt" in binding.modifiers and (
        is_key_physically_down(VK_MENU) or is_key_physically_down(VK_LMENU) or is_key_physically_down(VK_RMENU)
    ):
        return True
    return False


def keyboard_modifier_snapshot() -> dict[str, bool]:
    return {
        "shift": is_shift_physically_down(),
        "ctrl": is_ctrl_physically_down(),
        "alt": is_key_physically_down(VK_MENU) or is_key_physically_down(VK_LMENU) or is_key_physically_down(VK_RMENU),
        "win": is_key_physically_down(0x5B) or is_key_physically_down(0x5C),
        "c": is_c_physically_down(),
    }
