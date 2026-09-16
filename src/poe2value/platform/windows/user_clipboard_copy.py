"""Track foreign Ctrl+C copies so passive clipboard routing can ignore them.

PoE2 Market "Copy Item" writes the clipboard without any Ctrl+C keystroke at all.
Item Check must react to that path, but not to a Ctrl+C that ExileLens does not
own — neither the player's own in-game Ctrl+C nor a Ctrl+C *injected by another
overlay* (Scalpel and other price checkers copy the hovered item with SendInput).
Injected foreign copies used to fall through this guard, so opening another
overlay opened ExileLens with it.

ExileLens' own injected copy carries ``EXILELENS_INJECT_TAG`` and is never noted
here; it is claimed upstream by hotkey sequence ownership.
"""

from __future__ import annotations

import logging
import time

from poe2value.platform.windows.keyboard_state import is_ctrl_physically_down

logger = logging.getLogger(__name__)

_LAST_FOREIGN_CTRL_C_MONOTONIC = 0.0
_LAST_FOREIGN_CTRL_C_SOURCE = ""
_DEFAULT_WINDOW_S = 1.0


def note_foreign_ctrl_c_copy(source: str = "physical") -> None:
    """Record a Ctrl+C that ExileLens does not own (physical, or injected by another app)."""
    global _LAST_FOREIGN_CTRL_C_MONOTONIC, _LAST_FOREIGN_CTRL_C_SOURCE
    _LAST_FOREIGN_CTRL_C_MONOTONIC = time.monotonic()
    _LAST_FOREIGN_CTRL_C_SOURCE = str(source or "")
    logger.info("foreign_ctrl_c_copy source=%s", _LAST_FOREIGN_CTRL_C_SOURCE)


# Historical name kept for callers and tests that predate injected-copy tracking.
note_user_ctrl_c_copy = note_foreign_ctrl_c_copy


def last_foreign_ctrl_c_source() -> str:
    return _LAST_FOREIGN_CTRL_C_SOURCE


def seconds_since_user_ctrl_c_copy() -> float | None:
    if _LAST_FOREIGN_CTRL_C_MONOTONIC <= 0:
        return None
    return max(0.0, time.monotonic() - _LAST_FOREIGN_CTRL_C_MONOTONIC)


seconds_since_foreign_ctrl_c_copy = seconds_since_user_ctrl_c_copy


def should_suppress_passive_item_clipboard(within_s: float = _DEFAULT_WINDOW_S) -> bool:
    """True when a clipboard update came from a Ctrl+C ExileLens does not own."""
    if is_ctrl_physically_down():
        return True
    elapsed = seconds_since_user_ctrl_c_copy()
    return elapsed is not None and elapsed <= within_s


def reset_user_ctrl_c_copy_state() -> None:
    global _LAST_FOREIGN_CTRL_C_MONOTONIC, _LAST_FOREIGN_CTRL_C_SOURCE
    _LAST_FOREIGN_CTRL_C_MONOTONIC = 0.0
    _LAST_FOREIGN_CTRL_C_SOURCE = ""


reset_foreign_ctrl_c_copy_state = reset_user_ctrl_c_copy_state
