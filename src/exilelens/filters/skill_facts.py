"""Verified skill facts (types, weapon requirements) from the pinned PoB2 export (FILTER-08B).

These replace hand-curated skill->weapon guesses wherever PoB2 states a weapon requirement. They say
what a skill REQUIRES; they never say which stat is best for a build (that is measured separately).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FACTS_FILE = Path(__file__).with_name("data") / "poe2_skill_facts.json"

# PoB2 skill weapon-type name -> native filter item classes. "Staff" is PoB2's name for martial
# quarterstaves; both staff classes are kept because the data does not separate them (false-negative safe).
WEAPON_TYPE_CLASSES = {
    "Bow": ("Bows",), "Crossbow": ("Crossbows",), "Spear": ("Spears",),
    "Staff": ("Quarterstaves", "Staves"), "One Hand Mace": ("One Hand Maces",),
    "Two Hand Mace": ("Two Hand Maces",), "Talisman": ("Talismans",), "Flail": ("Flails",),
    "Claw": ("Claws",), "Dagger": ("Daggers",), "One Hand Axe": ("One Hand Axes",),
    "Two Hand Axe": ("Two Hand Axes",), "One Hand Sword": ("One Hand Swords",),
    "Two Hand Sword": ("Two Hand Swords",),
}

ELEMENT_TYPES = ("Fire", "Cold", "Lightning", "Chaos", "Physical")


@dataclass(frozen=True)
class SkillProfile:
    skill_id: str
    name: str
    types: frozenset[str]
    weapon_types: tuple[str, ...]

    @property
    def is_spell(self) -> bool:
        return "Spell" in self.types

    @property
    def is_attack(self) -> bool:
        return "Attack" in self.types

    @property
    def is_minion(self) -> bool:
        return bool(self.types & {"CreatesMinion", "Minion"})

    @property
    def is_projectile(self) -> bool:
        return "Projectile" in self.types

    @property
    def elements(self) -> tuple[str, ...]:
        return tuple(element for element in ELEMENT_TYPES if element in self.types)

    @property
    def weapon_classes(self) -> tuple[str, ...] | None:
        """Native classes the skill requires; None when PoB2 states no weapon requirement."""
        required = [kind for kind in self.weapon_types if kind != "None"]
        if not required or "None" in self.weapon_types:
            # Unarmed-capable or unrestricted skills cannot be narrowed by weapon class.
            return None
        classes: list[str] = []
        for kind in required:
            classes.extend(WEAPON_TYPE_CLASSES.get(kind, (f"<unmapped {kind}>",)))
        return tuple(dict.fromkeys(classes))


@lru_cache(maxsize=1)
def _skills() -> dict[str, dict]:
    payload = json.loads(FACTS_FILE.read_text(encoding="utf-8"))
    if not payload.get("pob_commit") or len(payload.get("skills", {})) < 300:
        raise ValueError("PoB2 skill facts snapshot is incomplete")
    return payload["skills"]


@lru_cache(maxsize=None)
def lookup(skill_id: str = "", name: str = "") -> SkillProfile | None:
    """Find a skill by PoB2 id (preferred) or exact display name. Ambiguous or unknown -> None."""
    skills = _skills()
    record = skills.get(skill_id) if skill_id else None
    key = skill_id
    if record is None and name:
        matches = [(sid, rec) for sid, rec in skills.items() if rec["name"] == name]
        player = [match for match in matches if match[0].endswith("Player")]
        pick = player or matches
        if len(pick) != 1:
            return None
        key, record = pick[0]
    if record is None:
        return None
    return SkillProfile(key, record["name"], frozenset(record["types"]), tuple(record["weapon_types"]))
