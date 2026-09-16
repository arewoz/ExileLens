"""Hook-observed chord state for Item Check release detection.

GetAsyncKeyState can disagree with WH_KEYBOARD_LL when swallowed chord events never
reach the normal input path. Release detection must follow what the hook actually saw.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from poe2value.platform.windows.hotkey_binding import MODIFIER_VKS, HotkeyBinding


def modifier_name_for_vk(vk: int) -> str | None:
    for name, vks in MODIFIER_VKS.items():
        if int(vk) in vks:
            return name
    return None


@dataclass
class HotkeyChordTracker:
    binding: HotkeyBinding
    _armed: bool = False
    _key_down: bool = False
    _modifiers_down: set[str] = field(default_factory=set)
    _recent_events: deque[tuple[int, bool]] = field(default_factory=lambda: deque(maxlen=16))

    def reset(self) -> None:
        self._armed = False
        self._key_down = False
        self._modifiers_down.clear()
        self._recent_events.clear()

    def arm(self) -> None:
        self._armed = True

    def disarm(self) -> None:
        self._armed = False

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def key_down(self) -> bool:
        return self._key_down

    @property
    def modifiers_down(self) -> frozenset[str]:
        return frozenset(self._modifiers_down)

    def observe(self, *, vk: int, is_down: bool) -> bool:
        """Record a hook key event. Returns True when the armed chord fully released."""
        self._recent_events.append((int(vk), bool(is_down)))
        mod = modifier_name_for_vk(vk)
        if mod is not None:
            if is_down:
                self._modifiers_down.add(mod)
            else:
                self._modifiers_down.discard(mod)
        if int(vk) == int(self.binding.vk):
            self._key_down = bool(is_down)
        if not self._armed:
            return False
        if self.binding_keys_down():
            return False
        self.disarm()
        return True

    def binding_keys_down(self) -> bool:
        if self._key_down:
            return True
        return any(mod in self._modifiers_down for mod in self.binding.modifiers)

    def modifier_snapshot(self) -> dict[str, bool]:
        return {
            "shift": "shift" in self._modifiers_down,
            "ctrl": "ctrl" in self._modifiers_down,
            "alt": "alt" in self._modifiers_down,
            "win": "win" in self._modifiers_down,
            "c": self._key_down,
        }

    def diagnostics(self) -> dict[str, object]:
        return {
            "armed": self._armed,
            "key_down": self._key_down,
            "modifiers_down": sorted(self._modifiers_down),
            "recent_events": list(self._recent_events),
        }
