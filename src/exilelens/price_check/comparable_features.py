from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from exilelens.price_check.stat_registry import DriverKind, all_families, primary_trade_stat_id


class ModImportance(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def _legacy_family_stat_ids() -> dict[str, str]:
    """Registry-backed explicit ids. Kept as a dict for older tests that inspect it."""
    mapping: dict[str, str] = {}
    for record in all_families():
        if record.driver_kind is DriverKind.EXACT_STAT:
            primary = primary_trade_stat_id(record.family)
            if primary:
                mapping[record.family] = primary
    return mapping


_FAMILY_STAT_IDS = _legacy_family_stat_ids()

_PSEUDO_STAT_IDS: dict[str, str] = {
    "total_elemental_resistance": "pseudo.pseudo_total_elemental_resistance",
    "total_fire_resistance": "pseudo.pseudo_total_fire_resistance",
    "total_cold_resistance": "pseudo.pseudo_total_cold_resistance",
    "total_chaos_resistance": "pseudo.pseudo_total_chaos_resistance",
    "total_life": "pseudo.pseudo_total_life",
    "total_mana": "pseudo.pseudo_total_mana",
    "total_energy_shield": "pseudo.pseudo_total_energy_shield",
}

_PSEUDO_MEMBERS: dict[str, frozenset[str]] = {
    "total_elemental_resistance": frozenset(
        {"fire_resistance", "cold_resistance", "lightning_resistance", "all_elemental_resistances"}
    ),
    "elemental_damage": frozenset({"lightning_damage", "fire_damage", "cold_damage", "spell_damage"}),
}

_MOD_MARKUP_RE = re.compile(r"\[([^|\]]+\|)?([^\]]+)\]")


def strip_mod_markup(text: str) -> str:
    return _MOD_MARKUP_RE.sub(lambda match: match.group(2), text)


_ELEMENT_RESISTANCE_RE = re.compile(r"\+(\d+)%\s+(?:to\s+)?(\w+)\s+Resistance", re.I)
_PERCENT_INC_RE = re.compile(r"(\d+)%\s+increased\s+(.+)", re.I)
_FLAT_RE = re.compile(r"\+(\d+)\s+to\s+maximum\s+(.+)", re.I)
_FLAT_MAXIMUM_RE = re.compile(r"\+(\d+)\s+maximum\s+(.+)", re.I)
_FLAT_TO_RE = re.compile(r"\+(\d+)\s+to\s+(.+)", re.I)
_ALL_ELEM_RES_RE = re.compile(r"\+(\d+)%\s+(?:to\s+)?all\s+Elemental\s+Resistances", re.I)
#: Trailing provenance tags the game appends to a mod line. They describe where the
#: mod came from, never what it does, so they must not leak into the family name.
_SOURCE_TAG_RE = re.compile(
    r"\s*\((?:implicit|explicit|crafted|rune|enchant(?:ed)?|fractured|desecrated|augmented|scourge)\)\s*$",
    re.I,
)


def strip_source_tags(text: str) -> str:
    """Drop trailing ``(rune)``/``(implicit)``/... provenance tags from a mod line."""
    previous = None
    current = str(text or "").strip()
    while previous != current:
        previous = current
        current = _SOURCE_TAG_RE.sub("", current).strip()
    return current


#: "Advanced Item Description" annotates every explicit roll with its tier range:
#: ``+38(36-40)% to Fire Resistance``, ``76(68-79)% increased Energy Shield``.
#: The range describes the mod's tier, not the roll on this item, so it is
#: removed before parsing. Base implicits carry no range, which is why they were
#: the only mods that still parsed before this existed.
_VALUE_RANGE_RE = re.compile(
    r"(?<=\d)\(\s*[+-]?\d+(?:\.\d+)?\s*-\s*[+-]?\d+(?:\.\d+)?\s*\)"
)


def strip_value_ranges(text: str) -> str:
    """Drop inline ``(low-high)`` tier annotations that follow a rolled value."""
    return _VALUE_RANGE_RE.sub("", str(text or ""))


def normalize_mod_text(text: str) -> str:
    """One canonical form for a mod line: no markup, no tier range, no provenance tag."""
    return strip_source_tags(strip_value_ranges(strip_mod_markup(str(text or "").strip())))


_MOD_LINE_RE = re.compile(
    r"^(\+?\d+%?|\d+%)\s+(.+)$|^(Gain|Adds|Grants|Regenerate)\s+.+$|^.+(increased|reduced|to)\s+.+$",
    re.I,
)

_FAMILY_ALIASES: dict[str, str] = {
    "life": "maximum_life",
    "mana": "maximum_mana",
    "energy shield": "maximum_energy_shield",
    "cast speed": "cast_speed",
    "attack speed": "attack_speed",
    "attack and cast speed": "attack_cast_speed",
    "lightning damage": "lightning_damage",
    "level of all lightning spell skills": "lightning_spell_skills",
    "fire damage": "fire_damage",
    "cold damage": "cold_damage",
    "spell damage": "spell_damage",
    "physical damage": "physical_damage",
    "fire resistance": "fire_resistance",
    "cold resistance": "cold_resistance",
    "lightning resistance": "lightning_resistance",
    "chaos resistance": "chaos_resistance",
    "all elemental resistances": "all_elemental_resistances",
    "critical strike chance": "critical_strike_chance",
    "critical strike multiplier": "critical_strike_multiplier",
    "strength": "strength",
    "dexterity": "dexterity",
    "intelligence": "intelligence",
    "armour": "armour",
    "evasion": "evasion",
    "evasion rating": "evasion",
    "energy shield (local)": "maximum_energy_shield",
    "movement speed": "movement_speed",
    "all attributes": "all_attributes",
    "critical hit chance": "critical_strike_chance",
    "critical hit chance for spells": "spell_critical_hit_chance",
    "critical strike chance for spells": "spell_critical_hit_chance",
    "critical damage bonus": "critical_strike_multiplier",
}

_CRIT_CHANCE_FAMILIES = frozenset({"critical_strike_chance", "spell_critical_hit_chance"})
_CRIT_MULTI_FAMILIES = frozenset({"critical_strike_multiplier"})
_CRIT_MULTI_STAT_HASH = "3556824919"
_SPELL_CRIT_STAT_HASH = "737908626"
_GENERIC_CRIT_CHANCE_STAT_HASH = "587431675"


def crit_family_from_label(label: str) -> str | None:
    """Map crit wording to a distinct family. Chance never becomes multiplier.

    Unsupported spell-crit-multi wording returns a distinct name that is not in
    the registry, so AUTO cannot substitute Critical Damage Bonus.
    """
    cleaned = re.sub(r"\s+", " ", str(label or "").lower().strip())
    if not cleaned:
        return None
    if "critical spell damage bonus" in cleaned:
        return "critical_spell_damage_bonus"
    if re.search(r"critical (?:hit|strike) chance for spells", cleaned):
        return "spell_critical_hit_chance"
    if re.search(r"critical (?:hit|strike) chance", cleaned):
        return "critical_strike_chance"
    if re.search(r"critical strike multiplier", cleaned) or re.search(
        r"(?<!spell )critical damage bonus", cleaned
    ):
        if "chance" in cleaned:
            return "critical_strike_chance"
        return "critical_strike_multiplier"
    return None


def _normalize_family_name(label: str) -> str:
    cleaned = re.sub(r"\s+", " ", label.lower().strip())
    crit = crit_family_from_label(cleaned)
    if crit is not None:
        return crit
    return _FAMILY_ALIASES.get(cleaned, cleaned.replace(" ", "_"))


class MarketRole(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class ComparableFeature:
    family: str
    pseudo_family: str | None
    value: float
    normalized_roll: float
    tier: str
    importance: ModImportance
    market_role: MarketRole
    trade_stat_id: str | None
    source_text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "pseudo_family": self.pseudo_family or "",
            "value": self.value,
            "normalized_roll": self.normalized_roll,
            "tier": self.tier,
            "importance": self.importance.value,
            "market_role": self.market_role.value,
            "trade_stat_id": self.trade_stat_id or "",
            "source_text": self.source_text,
        }


def _normalize_family_name(label: str) -> str:
    cleaned = re.sub(r"\s+", " ", label.lower().strip())
    return _FAMILY_ALIASES.get(cleaned, cleaned.replace(" ", "_"))


def _pseudo_for_family(family: str) -> str | None:
    if family in _PSEUDO_MEMBERS.get("total_elemental_resistance", frozenset()):
        return "total_elemental_resistance"
    if family in _PSEUDO_MEMBERS.get("elemental_damage", frozenset()):
        return "elemental_damage"
    if family == "maximum_life":
        return "total_life"
    if family == "maximum_mana":
        return "total_mana"
    if family in {"maximum_energy_shield", "energy_shield"}:
        return "total_energy_shield"
    return None


def _trade_stat_id(family: str, pseudo_family: str | None) -> str | None:
    if family in _CRIT_CHANCE_FAMILIES:
        primary = primary_trade_stat_id(family)
        if primary and _CRIT_MULTI_STAT_HASH in primary:
            return None
        return primary
    primary = primary_trade_stat_id(family)
    if primary:
        return primary
    if family in _FAMILY_STAT_IDS:
        return _FAMILY_STAT_IDS[family]
    if pseudo_family:
        pseudo_id = primary_trade_stat_id(pseudo_family)
        if pseudo_id:
            return pseudo_id
        return _PSEUDO_STAT_IDS.get(pseudo_family)
    return None


def _tier_for_value(family: str, value: float) -> str:
    thresholds: dict[str, tuple[float, float]] = {
        "cast_speed": (15.0, 25.0),
        "attack_speed": (10.0, 18.0),
        "lightning_damage": (20.0, 35.0),
        "maximum_life": (60.0, 90.0),
        "fire_resistance": (30.0, 40.0),
        "cold_resistance": (30.0, 40.0),
        "chaos_resistance": (20.0, 30.0),
    }
    low, high = thresholds.get(family, (0.0, 100.0))
    if value >= high:
        return "T1"
    if value >= low:
        return "T2"
    return "T3"


def _normalized_roll(family: str, value: float) -> float:
    thresholds: dict[str, tuple[float, float]] = {
        "cast_speed": (10.0, 35.0),
        "attack_speed": (5.0, 25.0),
        "lightning_damage": (10.0, 50.0),
        "maximum_life": (20.0, 100.0),
        "fire_resistance": (15.0, 45.0),
        "cold_resistance": (15.0, 45.0),
        "chaos_resistance": (10.0, 35.0),
        "maximum_mana": (50.0, 180.0),
        "maximum_energy_shield": (40.0, 100.0),
    }
    low, high = thresholds.get(family, (0.0, max(value, 1.0)))
    span = max(high - low, 1.0)
    return max(0.0, min(1.0, (value - low) / span))


def _market_importance(family: str, *, category: str | None, value: float = 0.0) -> tuple[ModImportance, MarketRole]:
    category_lower = str(category or "").lower()
    caster_signal = any(token in category_lower for token in ("ring", "amulet", "staff", "wand", "sceptre"))
    weapon_signal = any(token in category_lower for token in ("staff", "wand", "bow", "crossbow", "weapon"))
    armor_signal = any(
        token in category_lower
        for token in ("gloves", "boots", "helmet", "body", "cuirass", "shield", "greaves", "sabatons", "buckle")
    )

    high_families = {
        "cast_speed",
        "attack_speed",
        "attack_cast_speed",
        "lightning_damage",
        "fire_damage",
        "cold_damage",
        "spell_damage",
        "physical_damage",
    }
    medium_families = {
        "fire_resistance",
        "cold_resistance",
        "lightning_resistance",
        "chaos_resistance",
        "all_elemental_resistances",
        "maximum_life",
        "critical_strike_chance",
        "spell_critical_hit_chance",
        "critical_strike_multiplier",
    }
    if family in {"cast_speed", "spell_damage", "lightning_spell_skills", "spell_critical_hit_chance"} and caster_signal:
        return ModImportance.CRITICAL, MarketRole.CRITICAL
    if family in {"maximum_life", "maximum_energy_shield", "energy_shield"} and armor_signal and value >= 40:
        return ModImportance.HIGH, MarketRole.HIGH
    if family in {"lightning_damage", "fire_damage", "cold_damage"} and (caster_signal or weapon_signal):
        return ModImportance.HIGH, MarketRole.HIGH
    if family in high_families:
        return ModImportance.HIGH, MarketRole.HIGH
    if family in medium_families:
        return ModImportance.MEDIUM, MarketRole.MEDIUM
    return ModImportance.LOW, MarketRole.LOW


#: Mod shapes the generic "+N to X" / "N% increased X" chain cannot read, because the
#: economic name is not the tail of the sentence. Checked before that chain. Each entry
#: is anchored so a differently-scoped stat -- "Monster Damage penetrates", "Allies in
#: your Presence Gain", "Attacks Gain" -- does not collapse into the plain one.
_SHAPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^damage penetrates\s+([\d.]+)%\s+(fire|cold|lightning|chaos) resistance$", re.I),
        "{2}_penetration",
    ),
    (
        re.compile(r"^damage penetrates\s+([\d.]+)%\s+elemental resistances?$", re.I),
        "elemental_penetration",
    ),
    (
        re.compile(
            r"^gain\s+([\d.]+)%\s+of damage as extra (fire|cold|lightning|chaos) damage$", re.I
        ),
        "gain_extra_{2}",
    ),
)


def _shape_family(text: str) -> tuple[str, float] | None:
    for pattern, template in _SHAPE_PATTERNS:
        found = pattern.search(text)
        if not found:
            continue
        groups = found.groups()
        family = template.format(*(("",) + tuple(row.lower() for row in groups)))
        return family, float(groups[0])
    return None


def parse_feature_from_mod(line: str, *, category: str | None = None) -> ComparableFeature | None:
    text = normalize_mod_text(line)
    if not text:
        return None

    shaped = _shape_family(text)
    if shaped is not None:
        family, value = shaped
        pseudo = _pseudo_for_family(family)
        importance, market_role = _market_importance(family, category=category, value=value)
        return ComparableFeature(
            family=family,
            pseudo_family=pseudo,
            value=value,
            normalized_roll=_normalized_roll(family, value),
            tier=_tier_for_value(family, value),
            importance=importance,
            market_role=market_role,
            trade_stat_id=_trade_stat_id(family, pseudo),
            source_text=text,
        )

    family: str | None = None
    value = 0.0

    match = _ALL_ELEM_RES_RE.search(text)
    if match:
        family = "all_elemental_resistances"
        value = float(match.group(1))
    else:
        match = _ELEMENT_RESISTANCE_RE.search(text)
        if match:
            value = float(match.group(1))
            element = match.group(2).lower()
            family = _normalize_family_name(f"{element} resistance")
        else:
            match = _FLAT_RE.search(text)
            if match and match.group(2).lower().startswith("maximum "):
                value = float(match.group(1))
                family = _normalize_family_name(match.group(2))
            else:
                match = _FLAT_MAXIMUM_RE.search(text)
                if match:
                    value = float(match.group(1))
                    family = _normalize_family_name(f"maximum {match.group(2)}")
                else:
                    match = _FLAT_TO_RE.search(text)
                    if match:
                        value = float(match.group(1))
                        family = _normalize_family_name(match.group(2))
                    else:
                        match = _PERCENT_INC_RE.search(text)
                        if match:
                            value = float(match.group(1))
                            family = _normalize_family_name(match.group(2))

    if family is None:
        return None

    pseudo = _pseudo_for_family(family)
    importance, market_role = _market_importance(family, category=category, value=value)
    tier = _tier_for_value(family, value)
    normalized = _normalized_roll(family, value)
    return ComparableFeature(
        family=family,
        pseudo_family=pseudo,
        value=value,
        normalized_roll=normalized,
        tier=tier,
        importance=importance,
        market_role=market_role,
        trade_stat_id=_trade_stat_id(family, pseudo),
        source_text=text,
    )


def extract_mod_lines(item_raw: str) -> list[str]:
    lines = [line.strip() for line in item_raw.replace("\r\n", "\n").split("\n") if line.strip()]
    mods: list[str] = []
    for line in lines:
        if line.startswith(
            ("Rarity:", "Item Class:", "--------", "Requirements:", "LevelReq:", "Implicits:", "Quality:")
        ):
            continue
        if line == "__UNNAMED__":
            continue
        if _MOD_LINE_RE.match(line) or line.startswith("+") or "increased" in line.lower():
            mods.append(line)
    return mods


def build_features(item_raw: str, *, category: str | None = None) -> tuple[ComparableFeature, ...]:
    return tuple(
        feature
        for line in extract_mod_lines(item_raw)
        for feature in [parse_feature_from_mod(line, category=category)]
        if feature is not None
    )


def important_features(features: Iterable[ComparableFeature]) -> tuple[ComparableFeature, ...]:
    return tuple(
        row for row in features if row.importance in {ModImportance.CRITICAL, ModImportance.HIGH}
    )


def _value_proximity_score(query_value: float, listing_value: float) -> float:
    if query_value <= 0 and listing_value <= 0:
        return 1.0
    baseline = max(abs(query_value), 1.0)
    delta = abs(query_value - listing_value) / baseline
    if delta <= 0.1:
        return 1.0
    if delta <= 0.25:
        return 0.92
    if delta <= 0.4:
        return 0.85
    if delta <= 0.6:
        return 0.6
    return max(0.0, 0.4 - (delta - 0.6))


def feature_pair_score(query: ComparableFeature, listing: ComparableFeature) -> float:
    if query.family == listing.family:
        return _value_proximity_score(query.value, listing.value)
    if query.pseudo_family and query.pseudo_family == listing.pseudo_family:
        return 0.85 * _value_proximity_score(query.value, listing.value)
    members = _PSEUDO_MEMBERS.get(query.pseudo_family or "", frozenset())
    if listing.family in members:
        return 0.75 * _value_proximity_score(query.value, listing.value)
    if query.pseudo_family == "elemental_damage" and listing.family in _PSEUDO_MEMBERS["elemental_damage"]:
        return 0.75 * _value_proximity_score(query.value, listing.value)
    return 0.0


def best_feature_score(query: ComparableFeature, listing_features: Iterable[ComparableFeature]) -> float:
    return max((feature_pair_score(query, row) for row in listing_features), default=0.0)


FAMILY_MATCH_THRESHOLD = 0.85
