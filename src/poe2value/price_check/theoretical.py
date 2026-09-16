from __future__ import annotations

import re

from poe2value.price_check.models import PriceConfidence, TheoreticalTier

_SKILL_RE = re.compile(r"\+(\d+) to (?:Level of )?([\w ]+) Skills?", re.I)
_CAST_SPEED_RE = re.compile(r"(\d+)% increased Cast Speed", re.I)
_SPELL_DAMAGE_RE = re.compile(r"(\d+)% increased Spell Damage", re.I)
_LIFE_RE = re.compile(r"\+(\d+) to maximum Life", re.I)


def _important_mod_lines(item_raw: str) -> list[str]:
    lines = [line.strip() for line in item_raw.replace("\r\n", "\n").split("\n") if line.strip()]
    mods: list[str] = []
    for line in lines:
        if line.startswith(("Rarity:", "Item Class:", "--------", "Requirements:", "LevelReq:", "Implicits:")):
            continue
        if _SKILL_RE.search(line) or _CAST_SPEED_RE.search(line) or _SPELL_DAMAGE_RE.search(line) or _LIFE_RE.search(line):
            mods.append(line)
        elif line.startswith("+") or "increased" in line.lower() or "reduced" in line.lower():
            mods.append(line)
    return mods[:6]


def classify_theoretical_desirability(item_raw: str) -> tuple[TheoreticalTier, tuple[str, ...], PriceConfidence]:
    """Minimal desirability classifier — not a price estimator."""
    text = item_raw.lower()
    mods = _important_mod_lines(item_raw)
    score = 0
    if _SKILL_RE.search(item_raw):
        score += 2
    if _CAST_SPEED_RE.search(item_raw):
        score += 2
    if _SPELL_DAMAGE_RE.search(item_raw):
        score += 2
    if "rarity: rare" in text or text.startswith("rarity: rare"):
        score += 1
    if score >= 5:
        return TheoreticalTier.HIGH_VALUE_RARE, tuple(mods), PriceConfidence.LOW
    if score >= 2:
        return TheoreticalTier.MODERATE_VALUE, tuple(mods), PriceConfidence.LOW
    if mods:
        return TheoreticalTier.LOW_VALUE, tuple(mods), PriceConfidence.LOW
    return TheoreticalTier.UNKNOWN, tuple(mods), PriceConfidence.NONE
