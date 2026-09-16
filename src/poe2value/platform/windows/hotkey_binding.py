"""Parsing and validation for configurable Item Check keyboard chords."""

from __future__ import annotations

from dataclasses import dataclass

MODIFIER_ORDER = ("ctrl", "alt", "shift")
MODIFIER_VKS = {
    "shift": (0x10, 0xA0, 0xA1),
    "ctrl": (0x11, 0xA2, 0xA3),
    "alt": (0x12, 0xA4, 0xA5),
    "win": (0x5B, 0x5C),
}
ALIASES = {"control": "ctrl", "lctrl": "ctrl", "rctrl": "ctrl", "lshift": "shift", "rshift": "shift", "lalt": "alt", "ralt": "alt"}
FORBIDDEN_CTRL_KEYS = {"a", "c", "v", "x", "z"}


class HotkeyValidationError(ValueError):
    pass


@dataclass(frozen=True)
class HotkeyBinding:
    modifiers: frozenset[str]
    key: str
    vk: int

    @classmethod
    def parse(cls, text: str, *, refine_hotkey: str = "") -> "HotkeyBinding":
        raw = str(text or "").strip().lower().replace(" ", "")
        if raw in {"ctrl+d", "control+d"}:
            raw = "shift+c"
        tokens = [ALIASES.get(token, token) for token in raw.split("+") if token]
        modifiers = frozenset(token for token in tokens if token in MODIFIER_VKS)
        keys = [token for token in tokens if token not in MODIFIER_VKS]
        if "win" in modifiers:
            raise HotkeyValidationError("Windows-key combinations are reserved by the operating system.")
        if not modifiers:
            raise HotkeyValidationError("Choose at least one modifier (Shift, Ctrl, or Alt).")
        if len(keys) != 1:
            raise HotkeyValidationError("Choose exactly one letter, digit, or F1–F24 key.")
        key = keys[0]
        if len(key) == 1 and ("a" <= key <= "z" or "0" <= key <= "9"):
            vk = ord(key.upper())
        elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
            vk = 0x70 + int(key[1:]) - 1
        else:
            raise HotkeyValidationError("The key must be a letter, digit, or F1–F24.")
        if modifiers == {"ctrl"} and key in FORBIDDEN_CTRL_KEYS:
            raise HotkeyValidationError(f"Ctrl+{key.upper()} is a standard editing shortcut and cannot be used.")
        if modifiers == {"alt"} and key in {"f4", "tab"}:
            raise HotkeyValidationError("That shortcut is reserved by Windows.")
        binding = cls(modifiers=modifiers, key=key, vk=vk)
        if refine_hotkey:
            try:
                refine = cls.parse(refine_hotkey)
            except HotkeyValidationError:
                refine = None
            if refine is not None and binding == refine:
                raise HotkeyValidationError("That shortcut is already used by Refine Price Check.")
        return binding

    @property
    def canonical(self) -> str:
        parts = [name for name in MODIFIER_ORDER if name in self.modifiers]
        parts.append(self.key)
        return "+".join(parts)

    @property
    def display(self) -> str:
        labels = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
        parts = [labels[name] for name in MODIFIER_ORDER if name in self.modifiers]
        parts.append(self.key.upper())
        return " + ".join(parts)


def validate_hotkey(text: str, *, refine_hotkey: str = "") -> tuple[str, str]:
    try:
        binding = HotkeyBinding.parse(text, refine_hotkey=refine_hotkey)
    except HotkeyValidationError as exc:
        return "", str(exc)
    return binding.canonical, ""
