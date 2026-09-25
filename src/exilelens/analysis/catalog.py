from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ProbeDefinition:
    probe_id: str
    family: str
    label: str
    unit: str
    magnitudes: tuple[float, ...]
    default_magnitude: float
    line_fn: Callable[[float], str]
    confidence: str
    nonlinear_sampling: bool = False
    eligible_slots: tuple[str, ...] | None = None
    notes: str = ""

    def line(self, magnitude: float) -> str:
        return self.line_fn(magnitude)


# Magnitudes are centralized here. They are local measurement increments, not universal weights.
PROBE_MAGNITUDES: dict[str, tuple[float, ...]] = {
    "CAST_SPEED": (5.0, 10.0, 20.0),
    "SPELL_DAMAGE": (10.0, 20.0),
    "ATTACK_DAMAGE": (10.0, 20.0),
    "ATTACK_SPEED": (5.0, 10.0),
    "CRIT_CHANCE": (5.0,),
    "CRIT_MULTIPLIER": (20.0,),
    "SPELL_SKILL_LEVELS": (1.0,),
    "MINION_DAMAGE": (10.0, 20.0),
    "MINION_ATTACK_SPEED": (5.0, 10.0),
    "MINION_CAST_SPEED": (5.0, 10.0),
    "MINION_SKILL_LEVELS": (1.0,),
    "IGNITE_MAGNITUDE": (100.0,),
    "POISON_MAGNITUDE": (100.0,),
    "POISON_DURATION": (20.0,),
    "PROJECTILE_SKILL_LEVELS": (1.0,),
    "LIFE": (50.0,),
    "ENERGY_SHIELD": (50.0,),
    "MANA": (50.0,),
    "ARMOUR": (200.0,),
    "EVASION": (200.0,),
    "FIRE_RES": (20.0,),
    "COLD_RES": (20.0,),
    "LIGHTNING_RES": (20.0,),
    "CHAOS_RES": (20.0,),
    "MOVEMENT_SPEED": (10.0,),
    "STRENGTH": (20.0,),
    "DEXTERITY": (20.0,),
    "INTELLIGENCE": (20.0,),
}


def _pct_inc(stat: str) -> Callable[[float], str]:
    return lambda mag: f"{int(mag) if mag == int(mag) else mag}% increased {stat}"


def _plus_max(stat: str) -> Callable[[float], str]:
    return lambda mag: f"+{int(mag)} to maximum {stat}"


def _plus_res(element: str) -> Callable[[float], str]:
    return lambda mag: f"+{int(mag)}% to {element} Resistance"


def _plus_attr(stat: str) -> Callable[[float], str]:
    return lambda mag: f"+{int(mag)} to {stat}"


def default_catalog() -> dict[str, ProbeDefinition]:
    defs = [
        ProbeDefinition(
            "CAST_SPEED",
            "offense",
            "Cast Speed",
            "percent",
            PROBE_MAGNITUDES["CAST_SPEED"],
            10.0,
            _pct_inc("Cast Speed"),
            "high",
            nonlinear_sampling=True,
        ),
        ProbeDefinition(
            "SPELL_DAMAGE",
            "offense",
            "Spell Damage",
            "percent",
            PROBE_MAGNITUDES["SPELL_DAMAGE"],
            20.0,
            _pct_inc("Spell Damage"),
            "high",
        ),
        ProbeDefinition(
            "ATTACK_DAMAGE",
            "offense",
            "Attack Damage",
            "percent",
            PROBE_MAGNITUDES["ATTACK_DAMAGE"],
            20.0,
            _pct_inc("Attack Damage"),
            "medium",
        ),
        ProbeDefinition(
            "ATTACK_SPEED",
            "offense",
            "Attack Speed",
            "percent",
            PROBE_MAGNITUDES["ATTACK_SPEED"],
            10.0,
            _pct_inc("Attack Speed"),
            "medium",
        ),
        ProbeDefinition(
            "CRIT_CHANCE",
            "offense",
            "Critical Hit Chance",
            "percent",
            PROBE_MAGNITUDES["CRIT_CHANCE"],
            5.0,
            lambda mag: f"{int(mag)}% increased Critical Hit Chance",
            "medium",
        ),
        ProbeDefinition(
            "CRIT_MULTIPLIER",
            "offense",
            "Critical Damage Bonus",
            "percent",
            PROBE_MAGNITUDES["CRIT_MULTIPLIER"],
            20.0,
            lambda mag: f"{int(mag)}% increased Critical Damage Bonus",
            "medium",
        ),
        ProbeDefinition(
            "SPELL_SKILL_LEVELS",
            "offense",
            "Spell Skill Levels",
            "levels",
            PROBE_MAGNITUDES["SPELL_SKILL_LEVELS"],
            1.0,
            lambda mag: f"+{int(mag)} to Level of all Spell Skills",
            "medium",
        ),
        ProbeDefinition(
            "MINION_DAMAGE",
            "offense",
            "Minion Damage",
            "percent",
            PROBE_MAGNITUDES["MINION_DAMAGE"],
            20.0,
            _pct_inc("Minion Damage"),
            "high",
        ),
        ProbeDefinition("IGNITE_MAGNITUDE", "offense", "Ignite Magnitude", "percent",
                        PROBE_MAGNITUDES["IGNITE_MAGNITUDE"], 100.0, _pct_inc("Ignite Magnitude"), "medium"),
        ProbeDefinition("POISON_MAGNITUDE", "offense", "Poison Magnitude", "percent",
                        PROBE_MAGNITUDES["POISON_MAGNITUDE"], 100.0, _pct_inc("Poison Magnitude"), "medium"),
        ProbeDefinition("POISON_DURATION", "offense", "Poison Duration", "percent",
                        PROBE_MAGNITUDES["POISON_DURATION"], 20.0, _pct_inc("Poison Duration"), "medium"),
        ProbeDefinition("PROJECTILE_SKILL_LEVELS", "offense", "Projectile Skill Levels", "levels",
                        PROBE_MAGNITUDES["PROJECTILE_SKILL_LEVELS"], 1.0,
                        lambda mag: f"+{int(mag)} to Level of all Projectile Skills", "medium"),
        ProbeDefinition(
            "MINION_ATTACK_SPEED",
            "offense",
            "Minion Attack Speed",
            "percent",
            PROBE_MAGNITUDES["MINION_ATTACK_SPEED"],
            10.0,
            lambda mag: f"Minions have {int(mag)}% increased Attack Speed",
            "high",
        ),
        ProbeDefinition(
            "MINION_CAST_SPEED",
            "offense",
            "Minion Cast Speed",
            "percent",
            PROBE_MAGNITUDES["MINION_CAST_SPEED"],
            10.0,
            lambda mag: f"Minions have {int(mag)}% increased Cast Speed",
            "high",
        ),
        ProbeDefinition(
            "MINION_SKILL_LEVELS",
            "offense",
            "Minion Skill Levels",
            "levels",
            PROBE_MAGNITUDES["MINION_SKILL_LEVELS"],
            1.0,
            lambda mag: f"+{int(mag)} to Level of all Minion Skills",
            "medium",
        ),
        ProbeDefinition(
            "LIFE",
            "defense",
            "Life",
            "flat",
            PROBE_MAGNITUDES["LIFE"],
            50.0,
            _plus_max("Life"),
            "high",
        ),
        ProbeDefinition(
            "ENERGY_SHIELD",
            "defense",
            "Energy Shield",
            "flat",
            PROBE_MAGNITUDES["ENERGY_SHIELD"],
            50.0,
            _plus_max("Energy Shield"),
            "high",
        ),
        ProbeDefinition(
            "MANA",
            "defense",
            "Mana",
            "flat",
            PROBE_MAGNITUDES["MANA"],
            50.0,
            _plus_max("Mana"),
            "medium",
        ),
        ProbeDefinition(
            "ARMOUR",
            "defense",
            "Armour",
            "flat",
            PROBE_MAGNITUDES["ARMOUR"],
            200.0,
            lambda mag: f"+{int(mag)} to Armour",
            "medium",
        ),
        ProbeDefinition(
            "EVASION",
            "defense",
            "Evasion",
            "flat",
            PROBE_MAGNITUDES["EVASION"],
            200.0,
            lambda mag: f"+{int(mag)} to Evasion",
            "medium",
        ),
        ProbeDefinition(
            "FIRE_RES",
            "resistance",
            "Fire Resistance",
            "resistance",
            PROBE_MAGNITUDES["FIRE_RES"],
            20.0,
            _plus_res("Fire"),
            "high",
        ),
        ProbeDefinition(
            "COLD_RES",
            "resistance",
            "Cold Resistance",
            "resistance",
            PROBE_MAGNITUDES["COLD_RES"],
            20.0,
            _plus_res("Cold"),
            "high",
        ),
        ProbeDefinition(
            "LIGHTNING_RES",
            "resistance",
            "Lightning Resistance",
            "resistance",
            PROBE_MAGNITUDES["LIGHTNING_RES"],
            20.0,
            _plus_res("Lightning"),
            "high",
        ),
        ProbeDefinition(
            "CHAOS_RES",
            "resistance",
            "Chaos Resistance",
            "resistance",
            PROBE_MAGNITUDES["CHAOS_RES"],
            20.0,
            _plus_res("Chaos"),
            "high",
        ),
        ProbeDefinition(
            "MOVEMENT_SPEED",
            "utility",
            "Movement Speed",
            "percent",
            PROBE_MAGNITUDES["MOVEMENT_SPEED"],
            10.0,
            _pct_inc("Movement Speed"),
            "high",
        ),
        ProbeDefinition(
            "STRENGTH",
            "utility",
            "Strength",
            "flat",
            PROBE_MAGNITUDES["STRENGTH"],
            20.0,
            _plus_attr("Strength"),
            "medium",
        ),
        ProbeDefinition(
            "DEXTERITY",
            "utility",
            "Dexterity",
            "flat",
            PROBE_MAGNITUDES["DEXTERITY"],
            20.0,
            _plus_attr("Dexterity"),
            "medium",
        ),
        ProbeDefinition(
            "INTELLIGENCE",
            "utility",
            "Intelligence",
            "flat",
            PROBE_MAGNITUDES["INTELLIGENCE"],
            20.0,
            _plus_attr("Intelligence"),
            "medium",
        ),
    ]
    return {item.probe_id: item for item in defs}


UNSUPPORTED_PROBE_IDS = frozenset(
    {
        "GENERIC_GEM_LEVELS",
        "LOCAL_WEAPON_DAMAGE",
        "IMPLICIT_ONLY_BASE_SHIFT",
    }
)


class ProbeCatalog:
    def __init__(self, probes: dict[str, ProbeDefinition] | None = None) -> None:
        self._probes = probes or default_catalog()

    def get(self, probe_id: str) -> ProbeDefinition | None:
        return self._probes.get(probe_id)

    def require(self, probe_id: str) -> ProbeDefinition:
        probe = self.get(probe_id)
        if probe is None:
            raise KeyError(probe_id)
        return probe

    def all(self) -> list[ProbeDefinition]:
        return list(self._probes.values())

    def stage2_ids(self) -> tuple[str, ...]:
        return (
            "CAST_SPEED",
            "SPELL_DAMAGE",
            "LIFE",
            "ENERGY_SHIELD",
            "MANA",
            "FIRE_RES",
            "COLD_RES",
            "LIGHTNING_RES",
            "CHAOS_RES",
            "MOVEMENT_SPEED",
            "SPELL_SKILL_LEVELS",
        )

    def is_unsupported(self, probe_id: str) -> bool:
        return probe_id in UNSUPPORTED_PROBE_IDS or probe_id not in self._probes
