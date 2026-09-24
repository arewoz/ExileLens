"""MARKET-03 — item-class market profiles.

A profile does **not** say "boots are movement speed plus life plus resistance". It
declares, for one item class:

* which semantic families are *candidates* for each market role;
* what a roll has to clear before a candidate family becomes an ANCHOR;
* which synergy tags form substitutable groups for that class;
* which economic concept wins when several representations are available;
* how much the base itself normally matters.

The item's actual rolls then decide the plan. Two pairs of boots with the same profile
can produce two anchors and one flexible, or one anchor and four flexible, and neither
is truncated — there is no driver count in this module or anywhere downstream.

**Calibration status.** Every ``min_value`` here is provisional. Absolute floors are a
static table by another name, and the brief forbids shipping one as authority, so they
are marked ``provisional=True`` and are to be re-derived from the APPROVED human corpus
before the product gate. Tier-percentile thresholds are preferred wherever the client
prints tier bounds, because those are read from the item rather than assumed.

Offline only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from exilelens.price_check.market_drivers import parsed_item_class


class ItemClassKey(str, Enum):
    """The economic classes the brief requires distinct profiles for (section 25)."""

    BOOTS = "boots"
    HELMET = "helmet"
    GLOVES = "gloves"
    BODY_ARMOUR = "body_armour"
    RING = "ring"
    AMULET = "amulet"
    BELT = "belt"
    JEWEL = "jewel"
    ATTACK_WEAPON = "attack_weapon"
    CASTER_WEAPON = "caster_weapon"
    OFFHAND = "offhand"
    OTHER = "other"


class BaseRelevance(str, Enum):
    """Default weight of the base type for a class, before the item is inspected."""

    NONE = "NONE"
    CATEGORY = "CATEGORY"
    FAMILY = "FAMILY"
    EXACT = "EXACT"


@dataclass(frozen=True)
class AnchorRule:
    """When a candidate family is strong enough to define the item's identity.

    ``min_tier_percentile`` is used when the client printed tier bounds: it asks "is
    this roll high inside its own tier", which is a statement about the item. Absolute
    ``min_value`` is the degraded path for implicits, runes and PoB exports.
    """

    family: str
    min_tier_percentile: float | None = None
    min_value: float | None = None
    note: str = ""
    provisional: bool = True

    def clears(self, *, raw_value: float, roll_percentile: float | None) -> bool:
        """Configured conditions are **conjunctive**.

        These used to be alternatives, so the presence of tier data bypassed the absolute
        floor entirely: with ``min_tier_percentile=0.0`` any roll inside its own tier
        became an anchor, and ``+8(5-10) to maximum Life`` on level-12 gloves passed. A
        tier percentile says the roll is good *for its tier*; the absolute floor says the
        tier is worth anything. Both are needed, and neither substitutes for the other.

        A condition that cannot be evaluated — a tier percentile with no tier data — is
        skipped rather than treated as failed.
        """
        checks: list[bool] = []
        if self.min_tier_percentile is not None and roll_percentile is not None:
            checks.append(roll_percentile >= self.min_tier_percentile)
        if self.min_value is not None:
            checks.append(float(raw_value) >= self.min_value)
        return all(checks) if checks else True

    def basis(self, *, roll_percentile: float | None) -> str:
        parts: list[str] = []
        if self.min_tier_percentile is not None and roll_percentile is not None:
            parts.append("tier percentile")
        if self.min_value is not None:
            parts.append("absolute floor (provisional)")
        return " and ".join(parts) if parts else "candidate family"


@dataclass(frozen=True)
class ItemClassProfile:
    key: ItemClassKey
    label: str
    anchor_candidates: tuple[AnchorRule, ...] = ()
    flexible_families: frozenset[str] = frozenset()
    optional_families: frozenset[str] = frozenset()
    dead_families: frozenset[str] = frozenset()
    #: Which representation wins inside a redundancy group for this class.
    preferred_representation: dict[str, str] | None = None
    #: Synergy tags whose members form substitutable COUNT groups for this class.
    synergy_groups: tuple[str, ...] = ()
    base_relevance: BaseRelevance = BaseRelevance.CATEGORY
    #: Item properties that carry economic meaning for this class.
    property_families: frozenset[str] = frozenset()
    #: Trade2 ``type_filters.category`` option for this class, when one covers it.
    #: ``None`` for classes that span several trade categories (weapons), where a
    #: category-only search would be meaninglessly broad.
    trade_category: str | None = None

    def anchor_rule(self, family: str) -> AnchorRule | None:
        for rule in self.anchor_candidates:
            if rule.family == family:
                return rule
        return None

    @property
    def anchor_families(self) -> frozenset[str]:
        return frozenset(rule.family for rule in self.anchor_candidates)


# Concepts that carry no market weight anywhere. Class profiles may add to this, and a
# class may *rescue* a family from it by listing the family as a candidate.
UNIVERSAL_DEAD_FAMILIES: frozenset[str] = frozenset(
    {"light_radius", "rarity_of_items_found", "item_rarity", "mana_regeneration_rate"}
)

#: Modifier text that carries no market weight regardless of item class. Used only for
#: mods the stat registry cannot map: "unsearchable" and "worthless" are different
#: claims, and only these may be called DEAD. Anything else unmappable is reported as
#: unsearchable instead, so a valuable mod ExileLens simply cannot query is never
#: quietly written off.
KNOWN_DEAD_MOD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"freeze duration", re.I),
    re.compile(r"ignite duration", re.I),
    re.compile(r"shock duration", re.I),
    re.compile(r"stun (?:duration|threshold)", re.I),
    re.compile(r"light radius", re.I),
    re.compile(r"mana regeneration", re.I),
    re.compile(r"(?:rarity|quantity) of items found", re.I),
    re.compile(r"charm (?:slot|charges)", re.I),
    re.compile(r"flask charges", re.I),
)


def is_known_dead_mod(text: str) -> bool:
    blob = str(text or "")
    return any(pattern.search(blob) for pattern in KNOWN_DEAD_MOD_PATTERNS)


_DEFENSIVE_CORE = frozenset(
    {
        "maximum_life",
        "total_life",
        "fire_resistance",
        "cold_resistance",
        "lightning_resistance",
        "chaos_resistance",
        "all_elemental_resistances",
        "total_elemental_resistance",
        "total_resistance",
        "maximum_energy_shield",
        "total_energy_shield",
    }
)

_ATTRIBUTES = frozenset({"strength", "dexterity", "intelligence", "all_attributes", "total_attributes"})

#: MARKET-03 registry-coverage closure. These stats were economically real all along;
#: until the authorised catalog fetch there was no verified trade id to search them
#: with, so they could not be a candidate for any role. Listing them completes the
#: mapping rather than re-weighting the model: no threshold changes, and no family
#: that was already a candidate moves.
_PENETRATION = frozenset(
    {"lightning_penetration", "fire_penetration", "cold_penetration", "elemental_penetration"}
)
_GAIN_AS_EXTRA = frozenset(
    {"gain_extra_lightning", "gain_extra_fire", "gain_extra_cold", "gain_extra_chaos"}
)

#: Resistances resolve to the pseudo total in every armour/jewellery class: buyers
#: substitute freely between which element it is (brief section 13).
_RES_TO_PSEUDO = {"elemental_resistance": "total_elemental_resistance"}

_ARMOUR_PROPERTIES = frozenset({"equip_ar", "equip_ev", "equip_es"})
_WEAPON_PROPERTIES = frozenset({"equip_dps", "equip_pdps", "equip_edps"})


PROFILES: dict[ItemClassKey, ItemClassProfile] = {
    ItemClassKey.BOOTS: ItemClassProfile(
        key=ItemClassKey.BOOTS,
        label="Boots",
        trade_category="armour.boots",
        anchor_candidates=(
            AnchorRule(
                "movement_speed",
                min_value=25.0,
                note="movement speed is the reason a pair of boots is bought at all",
            ),
            AnchorRule("maximum_life", min_tier_percentile=0.0, min_value=70.0),
        ),
        flexible_families=_DEFENSIVE_CORE | _ATTRIBUTES | {"equip_es", "equip_ar", "equip_ev"},
        optional_families=frozenset({"armour", "evasion", "maximum_mana", "total_mana"}),
        preferred_representation={**_RES_TO_PSEUDO, "energy_shield": "equip_es"},
        synergy_groups=("resistance_package", "survivability", "attribute_fixing"),
        base_relevance=BaseRelevance.CATEGORY,
        property_families=_ARMOUR_PROPERTIES,
    ),
    ItemClassKey.HELMET: ItemClassProfile(
        key=ItemClassKey.HELMET,
        label="Helmet",
        trade_category="armour.helmet",
        anchor_candidates=(AnchorRule("maximum_life", min_tier_percentile=0.0, min_value=70.0),),
        flexible_families=_DEFENSIVE_CORE | _ATTRIBUTES | {"equip_es", "equip_ar", "equip_ev"},
        optional_families=frozenset({"armour", "evasion", "maximum_mana", "total_mana"}),
        preferred_representation={**_RES_TO_PSEUDO, "energy_shield": "equip_es"},
        synergy_groups=("resistance_package", "survivability", "attribute_fixing"),
        base_relevance=BaseRelevance.CATEGORY,
        property_families=_ARMOUR_PROPERTIES,
    ),
    ItemClassKey.GLOVES: ItemClassProfile(
        key=ItemClassKey.GLOVES,
        label="Gloves",
        trade_category="armour.gloves",
        anchor_candidates=(AnchorRule("maximum_life", min_tier_percentile=0.0, min_value=70.0),),
        flexible_families=(
            _DEFENSIVE_CORE
            | _ATTRIBUTES
            | {"attack_speed", "critical_strike_chance", "equip_es", "equip_ar", "equip_ev"}
        ),
        optional_families=frozenset({"armour", "evasion", "maximum_mana", "total_mana"}),
        preferred_representation={**_RES_TO_PSEUDO, "energy_shield": "equip_es"},
        synergy_groups=("resistance_package", "survivability", "attack_offence", "attribute_fixing"),
        base_relevance=BaseRelevance.CATEGORY,
        property_families=_ARMOUR_PROPERTIES,
    ),
    ItemClassKey.BODY_ARMOUR: ItemClassProfile(
        key=ItemClassKey.BODY_ARMOUR,
        label="Body Armour",
        trade_category="armour.chest",
        anchor_candidates=(
            AnchorRule("maximum_life", min_tier_percentile=0.0, min_value=90.0),
            AnchorRule("equip_es", min_value=400.0, note="an ES chest is bought for its ES"),
            AnchorRule("equip_ar", min_value=800.0),
            AnchorRule("equip_ev", min_value=800.0),
        ),
        flexible_families=_DEFENSIVE_CORE | _ATTRIBUTES | _ARMOUR_PROPERTIES | {"spirit"},
        optional_families=frozenset({"armour", "evasion", "maximum_mana", "total_mana"}),
        preferred_representation={**_RES_TO_PSEUDO, "energy_shield": "equip_es"},
        synergy_groups=("survivability", "resistance_package", "attribute_fixing"),
        base_relevance=BaseRelevance.FAMILY,
        property_families=_ARMOUR_PROPERTIES,
    ),
    ItemClassKey.RING: ItemClassProfile(
        key=ItemClassKey.RING,
        label="Ring",
        trade_category="accessory.ring",
        anchor_candidates=(
            AnchorRule("maximum_life", min_tier_percentile=0.0, min_value=80.0),
            AnchorRule("lightning_spell_skills", min_value=1.0, note="+skill is a discrete premium"),
        ),
        flexible_families=(
            _DEFENSIVE_CORE
            | _ATTRIBUTES
            | {
                "cast_speed",
                "attack_speed",
                "spell_damage",
                "lightning_damage",
                "fire_damage",
                "cold_damage",
                "critical_strike_chance",
                "spell_critical_hit_chance",
            }
        ),
        optional_families=frozenset({"maximum_mana", "total_mana"}),
        preferred_representation=dict(_RES_TO_PSEUDO),
        synergy_groups=("resistance_package", "caster_offence", "attack_offence", "attribute_fixing"),
        base_relevance=BaseRelevance.CATEGORY,
    ),
    ItemClassKey.AMULET: ItemClassProfile(
        key=ItemClassKey.AMULET,
        label="Amulet",
        trade_category="accessory.amulet",
        anchor_candidates=(
            AnchorRule("lightning_spell_skills", min_value=1.0, note="+skill defines a caster amulet"),
            AnchorRule("all_spell_skills", min_value=1.0, note="+skill defines a caster amulet"),
            AnchorRule("maximum_life", min_tier_percentile=0.0, min_value=80.0),
        ),
        flexible_families=(
            _DEFENSIVE_CORE
            | _ATTRIBUTES
            | {
                "cast_speed",
                "attack_speed",
                "spell_damage",
                "lightning_damage",
                "fire_damage",
                "cold_damage",
                "critical_strike_chance",
                "spell_critical_hit_chance",
                "critical_strike_multiplier",
                "spirit",
            }
            | _PENETRATION
            | _GAIN_AS_EXTRA
        ),
        optional_families=frozenset({"maximum_mana", "total_mana"}),
        preferred_representation=dict(_RES_TO_PSEUDO),
        synergy_groups=("caster_offence", "attack_offence", "resistance_package", "attribute_fixing"),
        base_relevance=BaseRelevance.CATEGORY,
    ),
    ItemClassKey.BELT: ItemClassProfile(
        key=ItemClassKey.BELT,
        label="Belt",
        trade_category="accessory.belt",
        anchor_candidates=(AnchorRule("maximum_life", min_tier_percentile=0.0, min_value=80.0),),
        flexible_families=_DEFENSIVE_CORE | _ATTRIBUTES,
        optional_families=frozenset({"maximum_mana", "total_mana", "armour", "evasion"}),
        preferred_representation=dict(_RES_TO_PSEUDO),
        synergy_groups=("resistance_package", "survivability", "attribute_fixing"),
        base_relevance=BaseRelevance.CATEGORY,
    ),
    ItemClassKey.JEWEL: ItemClassProfile(
        key=ItemClassKey.JEWEL,
        label="Jewel",
        trade_category="jewel",
        # A jewel rarely has one identity-defining mod; its value is the combination.
        # Leaving anchors empty is a deliberate statement, not an omission: everything
        # useful lands in flexible and is expressed as a COUNT group (brief section 27).
        anchor_candidates=(),
        flexible_families=(
            _ATTRIBUTES
            | {
                "spell_damage",
                "lightning_damage",
                "fire_damage",
                "cold_damage",
                "physical_damage",
                "cast_speed",
                "attack_speed",
                "maximum_life",
                "maximum_energy_shield",
                "fire_resistance",
                "cold_resistance",
                "lightning_resistance",
                "chaos_resistance",
                "critical_strike_chance",
                "spell_critical_hit_chance",
                "critical_strike_multiplier",
            }
            | _PENETRATION
            | _GAIN_AS_EXTRA
        ),
        optional_families=frozenset({"maximum_mana", "total_mana"}),
        # Crit chance and crit multiplier stay distinct semantics (brief section 27).
        preferred_representation={},
        synergy_groups=("caster_offence", "attack_offence", "survivability", "attribute_fixing"),
        base_relevance=BaseRelevance.CATEGORY,
    ),
    ItemClassKey.ATTACK_WEAPON: ItemClassProfile(
        key=ItemClassKey.ATTACK_WEAPON,
        label="Attack Weapon",
        anchor_candidates=(
            AnchorRule("equip_dps", min_value=150.0, note="final DPS is the weapon's identity"),
            AnchorRule("equip_pdps", min_value=120.0),
            AnchorRule("equip_edps", min_value=120.0),
        ),
        flexible_families=(
            _WEAPON_PROPERTIES
            | _ATTRIBUTES
            | {
                "attack_speed",
                "critical_strike_chance",
                "critical_strike_multiplier",
                "physical_damage",
                "maximum_life",
            }
        ),
        optional_families=_DEFENSIVE_CORE,
        preferred_representation={"attack_dps": "equip_dps"},
        synergy_groups=("attack_offence",),
        base_relevance=BaseRelevance.FAMILY,
        property_families=_WEAPON_PROPERTIES,
    ),
    ItemClassKey.CASTER_WEAPON: ItemClassProfile(
        key=ItemClassKey.CASTER_WEAPON,
        label="Caster Weapon",
        anchor_candidates=(
            AnchorRule("lightning_spell_skills", min_value=1.0, note="+skill levels define a caster weapon"),
            AnchorRule("all_spell_skills", min_value=1.0, note="+skill levels define a caster weapon"),
            AnchorRule("spell_damage", min_tier_percentile=0.0, min_value=60.0),
        ),
        flexible_families=(
            _ATTRIBUTES
            | {
                "cast_speed",
                "spell_damage",
                "spell_critical_hit_chance",
                "critical_strike_multiplier",
                "lightning_damage",
                "fire_damage",
                "cold_damage",
                "maximum_life",
                "maximum_mana",
                "spirit",
            }
            | _PENETRATION
            | _GAIN_AS_EXTRA
        ),
        optional_families=_DEFENSIVE_CORE,
        preferred_representation={},
        synergy_groups=("caster_offence",),
        base_relevance=BaseRelevance.FAMILY,
    ),
    ItemClassKey.OFFHAND: ItemClassProfile(
        key=ItemClassKey.OFFHAND,
        label="Offhand",
        anchor_candidates=(
            AnchorRule("lightning_spell_skills", min_value=1.0),
            AnchorRule("equip_es", min_value=250.0),
        ),
        flexible_families=(
            _DEFENSIVE_CORE | _ATTRIBUTES | {"spell_damage", "cast_speed", "equip_es", "spirit"}
        ),
        optional_families=frozenset({"maximum_mana", "total_mana", "armour", "evasion"}),
        preferred_representation={**_RES_TO_PSEUDO, "energy_shield": "equip_es"},
        synergy_groups=("caster_offence", "resistance_package", "survivability"),
        base_relevance=BaseRelevance.FAMILY,
        property_families=frozenset({"equip_es", "equip_ar", "equip_ev"}),
    ),
    ItemClassKey.OTHER: ItemClassProfile(
        key=ItemClassKey.OTHER,
        label="Item",
        anchor_candidates=(AnchorRule("maximum_life", min_tier_percentile=0.0, min_value=80.0),),
        flexible_families=_DEFENSIVE_CORE | _ATTRIBUTES,
        optional_families=frozenset(),
        preferred_representation=dict(_RES_TO_PSEUDO),
        synergy_groups=("resistance_package", "survivability"),
        base_relevance=BaseRelevance.CATEGORY,
    ),
}


_CLASS_TOKENS: tuple[tuple[ItemClassKey, tuple[str, ...]], ...] = (
    (ItemClassKey.JEWEL, ("jewel",)),
    (ItemClassKey.BOOTS, ("boot", "greave", "sandal", "shoe", "slipper", "sabaton")),
    (ItemClassKey.GLOVES, ("glove", "gauntlet", "mitt")),
    (ItemClassKey.HELMET, ("helmet", "helm", "tiara", "crown", "circlet", "mask", "hood")),
    (ItemClassKey.BODY_ARMOUR, ("body armour", "body armor", "cuirass", "raiment", "robe", "vestment", "plate", "garb")),
    (ItemClassKey.RING, ("ring",)),
    (ItemClassKey.AMULET, ("amulet",)),
    (ItemClassKey.BELT, ("belt", "sash")),
    (ItemClassKey.OFFHAND, ("shield", "buckler", "focus", "foci", "quiver")),
    # Attack weapons are matched first so "Quarterstaves" cannot be read as a caster
    # "staves"; no attack token is a substring of a caster class name.
    (
        ItemClassKey.ATTACK_WEAPON,
        (
            "bow",
            "crossbow",
            "sword",
            "axe",
            "mace",
            "spear",
            "quarterstaff",
            "quarterstave",
            "claw",
            "dagger",
            "flail",
        ),
    ),
    (
        ItemClassKey.CASTER_WEAPON,
        ("wand", "sceptre", "scepter", "staff", "stave"),
    ),
)


def _word_in(blob: str, token: str) -> bool:
    if not blob or not token:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}s?(?![a-z])", blob) is not None


def _key_from_blob(blob: str) -> ItemClassKey | None:
    text = re.sub(r"\s+", " ", str(blob or "").strip().lower())
    if not text:
        return None
    # "Jewelled Gloves" is gloves, not a jewel — check the compound token first.
    if _word_in(text, "jewelled") or _word_in(text, "jeweled"):
        for key, tokens in _CLASS_TOKENS:
            if key is ItemClassKey.JEWEL:
                continue
            if any(_word_in(text, token) for token in tokens):
                return key
        return None
    for key, tokens in _CLASS_TOKENS:
        if any(token in text if " " in token else _word_in(text, token) for token in tokens):
            return key
    return None


def classify_item_class(
    item_raw: str,
    *,
    category: str | None = None,
    base_type: str | None = None,
) -> ItemClassKey:
    """Resolve the economic class. Parsed ``Item Class:`` wins over base-name tokens."""
    for blob in (parsed_item_class(item_raw), str(base_type or ""), str(category or "")):
        key = _key_from_blob(blob)
        if key is not None:
            return key
    header = "\n".join(str(item_raw or "").splitlines()[:6])
    return _key_from_blob(header) or ItemClassKey.OTHER


def profile_for(key: ItemClassKey) -> ItemClassProfile:
    return PROFILES.get(key, PROFILES[ItemClassKey.OTHER])


def profile_for_item(
    item_raw: str,
    *,
    category: str | None = None,
    base_type: str | None = None,
) -> ItemClassProfile:
    return profile_for(classify_item_class(item_raw, category=category, base_type=base_type))


def all_profiles() -> Iterable[ItemClassProfile]:
    return PROFILES.values()
