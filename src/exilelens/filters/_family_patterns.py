"""Stat-family definitions shared by the PoB2 pool exporter and runtime implicit matching (FILTER-08B).

Each family is a (family id, sensitivity probe id, relation, patterns) row. Patterns match ONE
normalised PoB2 stat line (numbers replaced by ``#``, signs dropped).

DIRECT   = the same stat the build-sensitivity probe applied.
NARROWED = the same effect restricted to a subset (spell crit, one element's spell levels). Only
           relevant when the build is verified (skill facts) to be in that subset.
"""
from __future__ import annotations

import re

# Number normalisation: "(5-8)", "+(5-8)", "+12", "1.5" -> "#" (signs are dropped).
NUMBER = re.compile(r"[-+]?\(?[-+]?\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?\)?")

ELEMENTS = ("Fire", "Cold", "Lightning", "Chaos", "Physical")

# (family id, probe id, relation, patterns). Patterns match one normalised stat line.
# DIRECT   = the same stat the build-sensitivity probe applied.
# NARROWED = the same effect restricted to a subset (e.g. spell crit, one element's
#            spell levels); only relevant when the build is verified to be in that subset.
FAMILIES = [
    ("SPELL_SKILL_LEVELS", "SPELL_SKILL_LEVELS", "DIRECT", [r"^# to Level of all Spell Skills$"]),
    ("PROJECTILE_SKILL_LEVELS", "PROJECTILE_SKILL_LEVELS", "DIRECT", [r"^# to Level of all Projectile Skills$"]),
    ("MINION_SKILL_LEVELS", "MINION_SKILL_LEVELS", "DIRECT", [r"^# to Level of all Minion Skills$"]),
    ("CAST_SPEED", "CAST_SPEED", "DIRECT", [r"^#% increased Cast Speed$", r"^#% increased Attack and Cast Speed$"]),
    ("ATTACK_SPEED", "ATTACK_SPEED", "DIRECT", [r"^#% increased Attack Speed$", r"^#% increased Attack and Cast Speed$"]),
    ("SPELL_DAMAGE", "SPELL_DAMAGE", "DIRECT", [r"^#% increased Spell Damage$"]),
    ("ATTACK_DAMAGE", "ATTACK_DAMAGE", "DIRECT", [r"^#% increased Attack Damage$"]),
    ("CRIT_CHANCE", "CRIT_CHANCE", "DIRECT", [r"^#% increased Critical Hit Chance$"]),
    ("CRIT_CHANCE_SPELL", "CRIT_CHANCE", "NARROWED", [r"^#% increased Critical Hit Chance for Spells$"]),
    ("CRIT_CHANCE_ATTACK", "CRIT_CHANCE", "NARROWED", [r"^#% increased Critical Hit Chance for Attacks$", r"^#% to Critical Hit Chance$"]),
    ("CRIT_MULTIPLIER", "CRIT_MULTIPLIER", "DIRECT", [r"^#% increased Critical Damage Bonus$"]),
    ("CRIT_MULTIPLIER_SPELL", "CRIT_MULTIPLIER", "NARROWED", [r"^#% increased Critical Spell Damage Bonus$"]),
    ("CRIT_MULTIPLIER_ATTACK", "CRIT_MULTIPLIER", "NARROWED", [r"^#% increased Critical Damage Bonus for Attack Damage$", r"^#% to Critical Damage Bonus$"]),
    ("MINION_DAMAGE", "MINION_DAMAGE", "DIRECT", [r"^Minions deal #% increased Damage$"]),
    ("MINION_SPEED", "MINION_ATTACK_SPEED", "DIRECT", [r"^Minions have #% increased Attack and Cast Speed$"]),
    ("IGNITE_MAGNITUDE", "IGNITE_MAGNITUDE", "DIRECT", [r"^#% increased Ignite Magnitude$"]),
    ("POISON_MAGNITUDE", "POISON_MAGNITUDE", "DIRECT", [r"^#% increased Magnitude of Poison you inflict$"]),
    ("POISON_DURATION", "POISON_DURATION", "DIRECT", [r"^#% increased Poison Duration$"]),
    ("LIFE", "LIFE", "DIRECT", [r"^# to maximum Life$"]),
    ("ENERGY_SHIELD", "ENERGY_SHIELD", "DIRECT", [r"^# to maximum Energy Shield$"]),
    ("MANA", "MANA", "DIRECT", [r"^# to maximum Mana$"]),
    ("ARMOUR", "ARMOUR", "DIRECT", [r"^# to Armour$"]),
    ("EVASION", "EVASION", "DIRECT", [r"^# to Evasion Rating$"]),
    ("FIRE_RES", "FIRE_RES", "DIRECT", [r"^#% to Fire Resistance$", r"^#% to Fire and Chaos Resistances$", r"^#% to all Elemental Resistances$"]),
    ("COLD_RES", "COLD_RES", "DIRECT", [r"^#% to Cold Resistance$", r"^#% to Cold and Chaos Resistances$", r"^#% to all Elemental Resistances$"]),
    ("LIGHTNING_RES", "LIGHTNING_RES", "DIRECT", [r"^#% to Lightning Resistance$", r"^#% to Lightning and Chaos Resistances$", r"^#% to all Elemental Resistances$"]),
    ("CHAOS_RES", "CHAOS_RES", "DIRECT", [r"^#% to Chaos Resistance$", r"^#% to (?:Fire|Cold|Lightning) and Chaos Resistances$"]),
    ("MOVEMENT_SPEED", "MOVEMENT_SPEED", "DIRECT", [r"^#% increased Movement Speed$"]),
    ("STRENGTH", "STRENGTH", "DIRECT", [r"^# to Strength$", r"^# to all Attributes$"]),
    ("DEXTERITY", "DEXTERITY", "DIRECT", [r"^# to Dexterity$", r"^# to all Attributes$"]),
    ("INTELLIGENCE", "INTELLIGENCE", "DIRECT", [r"^# to Intelligence$", r"^# to all Attributes$"]),
]
# Element-specific spell-skill levels: the SAME effect as the tested "+1 Spell Skills" for a spell of that element.
for _element in ELEMENTS:
    FAMILIES.append((f"SPELL_SKILL_LEVELS@{_element}", "SPELL_SKILL_LEVELS", "NARROWED",
                     [rf"^# to Level of all {_element} Spell Skills$"]))

_COMPILED = [(fid, probe, relation, [re.compile(p) for p in patterns]) for fid, probe, relation, patterns in FAMILIES]


def normalise(line: str) -> str:
    return NUMBER.sub("#", line).strip()


# Family id -> compiled patterns, for matching text such as base implicits.
PATTERNS = {fid: tuple(re.compile(p) for p in patterns) for fid, _probe, _relation, patterns in FAMILIES}
