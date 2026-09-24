"""Clipboard locale detection and low-cost header normalization.

PoB evaluation still requires English mod/base text (see docs/internal/implementation/LOCALIZATION_FR_CLIPBOARD.md).
This module only normalizes stable structural headers so recognition can proceed.
"""

from __future__ import annotations

import re

_LOCALE_UNKNOWN = "unknown"
_LOCALE_EN = "en"
_LOCALE_FR = "fr"

# Leading header labels that differ between English and French clients.
_HEADER_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^Rareté\s*:\s*", re.I), "Rarity: "),
    (re.compile(r"^Classe d'objet\s*:\s*", re.I), "Item Class: "),
    (re.compile(r"^Qualité\s*:\s*", re.I), "Quality: "),
    (re.compile(r"^Niveau d'objet\s*:\s*", re.I), "Item Level: "),
    (re.compile(r"^Niveau requis\s*:\s*", re.I), "LevelReq: "),
    (re.compile(r"^Exigences\s*:\s*", re.I), "Requirements: "),
    (re.compile(r"^Implicites\s*:\s*", re.I), "Implicits: "),
    (re.compile(r"^Emplacements\s*:\s*", re.I), "Sockets: "),
    (re.compile(r"^Rune\s*:\s*", re.I), "Rune: "),
)

_RARITY_ALIASES = {
    "MAGIE": "MAGIC",
    "MAGIQUE": "MAGIC",
    "NORMALE": "NORMAL",
    "RARE": "RARE",
    "UNIQUE": "UNIQUE",
    "RELIQUE": "RELIC",
}

_STATUS_ALIASES = {
    "non identifié": "unidentified",
    "corrompu": "corrupted",
    "corrompue": "corrupted",
}


def detect_clipboard_locale(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith(("Rareté:", "Rareté :", "Classe d'objet:")):
        return _LOCALE_FR
    if stripped.startswith(("Rarity:", "Item Class:")):
        return _LOCALE_EN
    if re.search(r"(?m)^Rareté\s*:", text):
        return _LOCALE_FR
    if re.search(r"(?m)^Rarity\s*:", text):
        return _LOCALE_EN
    return _LOCALE_UNKNOWN


def normalize_clipboard_text(text: str) -> tuple[str, str]:
    """Return canonical English-oriented clipboard text and a locale tag."""
    locale = detect_clipboard_locale(text)
    if locale != _LOCALE_FR:
        return text, locale

    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        normalized = line
        for pattern, replacement in _HEADER_ALIASES:
            if pattern.match(normalized):
                normalized = pattern.sub(replacement, normalized, count=1)
                break
        if normalized.startswith("Rarity:"):
            label, value = normalized.split(":", 1)
            rarity = value.strip().upper()
            normalized = f"{label}: {_RARITY_ALIASES.get(rarity, rarity)}"
        lowered = normalized.strip().lower()
        if lowered in _STATUS_ALIASES:
            normalized = _STATUS_ALIASES[lowered]
        lines.append(normalized)
    return "\n".join(lines), locale
