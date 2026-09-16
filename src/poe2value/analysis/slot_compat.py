from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from poe2value.items.slots import ProductSlot

# PoE2 ModItem.lua weight keys → product slots. Derived from PoB data, not PoE1 memory.
_TAG_TO_SLOTS: dict[str, tuple[str, ...]] = {
    "ring": (ProductSlot.RING_1.value, ProductSlot.RING_2.value),
    "amulet": (ProductSlot.AMULET.value,),
    "belt": (ProductSlot.BELT.value,),
    "helmet": (ProductSlot.HELMET.value,),
    "gloves": (ProductSlot.GLOVES.value,),
    "boots": (ProductSlot.BOOTS.value,),
    "body_armour": (ProductSlot.BODY_ARMOUR.value,),
    "armour": (
        ProductSlot.HELMET.value,
        ProductSlot.BODY_ARMOUR.value,
        ProductSlot.GLOVES.value,
        ProductSlot.BOOTS.value,
    ),
    "str_armour": (ProductSlot.HELMET.value, ProductSlot.BODY_ARMOUR.value, ProductSlot.GLOVES.value, ProductSlot.BOOTS.value),
    "dex_armour": (ProductSlot.HELMET.value, ProductSlot.BODY_ARMOUR.value, ProductSlot.GLOVES.value, ProductSlot.BOOTS.value),
    "int_armour": (ProductSlot.HELMET.value, ProductSlot.BODY_ARMOUR.value, ProductSlot.GLOVES.value, ProductSlot.BOOTS.value),
    "str_dex_armour": (ProductSlot.HELMET.value, ProductSlot.BODY_ARMOUR.value, ProductSlot.GLOVES.value, ProductSlot.BOOTS.value),
    "str_int_armour": (ProductSlot.HELMET.value, ProductSlot.BODY_ARMOUR.value, ProductSlot.GLOVES.value, ProductSlot.BOOTS.value),
    "dex_int_armour": (ProductSlot.HELMET.value, ProductSlot.BODY_ARMOUR.value, ProductSlot.GLOVES.value, ProductSlot.BOOTS.value),
    "str_dex_int_armour": (ProductSlot.HELMET.value, ProductSlot.BODY_ARMOUR.value, ProductSlot.GLOVES.value, ProductSlot.BOOTS.value),
    "focus": (ProductSlot.OFFHAND_1.value,),
    "shield": (ProductSlot.OFFHAND_1.value,),
    "quiver": (ProductSlot.OFFHAND_1.value,),
}

WEAPON_TAGS = frozenset(
    {
        "wand",
        "staff",
        "warstaff",
        "bow",
        "crossbow",
        "mace",
        "axe",
        "sword",
        "spear",
        "claw",
        "dagger",
        "flail",
        "sceptre",
        "talisman",
        "trap",
    }
)

_PROBE_LINE_NEEDLES: dict[str, tuple[str, ...]] = {
    "CAST_SPEED": ("increased Cast Speed",),
    "SPELL_DAMAGE": ("increased Spell Damage",),
    "ATTACK_DAMAGE": ("increased Attack Damage",),
    "ATTACK_SPEED": ("increased Attack Speed",),
    "CRIT_CHANCE": ("increased Critical Hit Chance", "increased Critical Strike Chance"),
    "CRIT_MULTIPLIER": ("increased Critical Damage Bonus", "to Critical Damage Bonus"),
    "SPELL_SKILL_LEVELS": ("to Level of all Spell Skills",),
    "LIFE": ("to maximum Life",),
    "ENERGY_SHIELD": ("to maximum Energy Shield",),
    "MANA": ("to maximum Mana",),
    "ARMOUR": ("to Armour",),
    "EVASION": ("to Evasion",),
    "FIRE_RES": ("to Fire Resistance",),
    "COLD_RES": ("to Cold Resistance",),
    "LIGHTNING_RES": ("to Lightning Resistance",),
    "CHAOS_RES": ("to Chaos Resistance",),
    "MOVEMENT_SPEED": ("increased Movement Speed",),
    "STRENGTH": ("to Strength",),
    "DEXTERITY": ("to Dexterity",),
    "INTELLIGENCE": ("to Intelligence",),
}

_ENTRY_RE = re.compile(
    r'\["(?P<id>[^"]+)"\]\s*=\s*\{.*?weightKey\s*=\s*\{(?P<keys>.*?)\}'
    r".*?weightVal\s*=\s*\{(?P<vals>.*?)\}",
    re.DOTALL,
)
_STR_RE = re.compile(r'"([^"]+)"')
_NUM_RE = re.compile(r"-?\d+")


def _parse_moditem(text: str) -> list[tuple[str, list[str], list[int]]]:
    rows: list[tuple[str, list[str], list[int]]] = []
    for match in _ENTRY_RE.finditer(text):
        blob = match.group(0)
        keys = _STR_RE.findall(match.group("keys"))
        vals = [int(x) for x in _NUM_RE.findall(match.group("vals"))]
        rows.append((blob, keys, vals))
    return rows


def _slots_for_weights(keys: list[str], vals: list[int]) -> set[str]:
    slots: set[str] = set()
    for key, val in zip(keys, vals):
        if val <= 0:
            continue
        if key in WEAPON_TAGS:
            continue
        mapped = _TAG_TO_SLOTS.get(key)
        if mapped:
            slots.update(mapped)
    return slots


@lru_cache(maxsize=4)
def load_slot_compat(pob_path: str) -> dict[str, dict[str, Any]]:
    from poe2value.config import PobConfig

    path = PobConfig(pob_path=Path(pob_path)).program_path / "Data" / "ModItem.lua"
    result: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return {probe_id: {"slots": set(), "confidence": "low", "source": "missing"} for probe_id in _PROBE_LINE_NEEDLES}
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = _parse_moditem(text)
    for probe_id, needles in _PROBE_LINE_NEEDLES.items():
        slots: set[str] = set()
        matched = 0
        for blob, keys, vals in rows:
            if not any(needle in blob for needle in needles):
                continue
            # Skip local-percent armour lines that are not global pools when probing jewellery.
            if probe_id in {"ARMOUR", "EVASION", "ENERGY_SHIELD"} and "LocalIncreased" in blob:
                continue
            if probe_id == "CAST_SPEED" and ("Allies in your Presence" in blob or "during any Flask Effect" in blob):
                continue
            if probe_id == "ATTACK_SPEED" and "Allies in your Presence" in blob:
                continue
            if "Minions have" in blob:
                continue
            found = _slots_for_weights(keys, vals)
            if found:
                matched += 1
                slots.update(found)
        result[probe_id] = {
            "slots": frozenset(slots),
            "confidence": "high" if matched else "low",
            "source": "pob_moditem",
            "matches": matched,
        }
    return result


def slot_compatibility(
    probe_id: str,
    product_slot: str,
    *,
    pob_path: str,
) -> dict[str, Any]:
    table = load_slot_compat(pob_path)
    info = table.get(probe_id) or {"slots": frozenset(), "confidence": "low", "source": "unknown"}
    legal = product_slot in info["slots"]
    confidence = info["confidence"] if legal else ("high" if info["confidence"] == "high" else "medium")
    return {
        "probe_id": probe_id,
        "product_slot": product_slot,
        "compatible": legal,
        "SLOT_COMPATIBILITY_CONFIDENCE": confidence if legal else "high",
        "confidence": "high" if legal else "low",
        "source": info.get("source"),
    }
