"""MARKET-03 — ``BaseValueProfile``: the base as a first-class market dimension.

MARKET-02 set ``query.type = <exact base>`` for every non-jewel item, unconditionally.
That is right for a crafting base whose whole value *is* the base, and wrong for an
ordinary finished rare where a buyer would take any equivalent piece — it silently
excludes the substitutes that would have told you what the item is worth.

This module decides, per item and with reasons:

* how much the base should constrain the search (:class:`BaseRelevance`);
* whether the item is priced as a finished rare or as a crafting base;
* which of item level, corrupted state and quality materially define its market.

Every conclusion carries reason codes, because a base constraint the product cannot
justify is a constraint the user cannot argue with.

**Thresholds here are provisional.** They are declared in one place, marked, and are to
be re-derived from the APPROVED corpus. Nothing in this module reads a price, a search
result or any live data — a base profile that learned from its own price would be a
feedback loop, not evidence.

Offline only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from exilelens.price_check.market_drivers import parse_equipment_properties
from exilelens.price_check.market_mod import MarketMod, MarketRole, ModSource
from exilelens.price_check.market_profiles import (
    BaseRelevance,
    ItemClassKey,
    ItemClassProfile,
    classify_item_class,
    profile_for,
)


class DefenceArchetype(str, Enum):
    ARMOUR = "ARMOUR"
    EVASION = "EVASION"
    ENERGY_SHIELD = "ENERGY_SHIELD"
    HYBRID = "HYBRID"
    NONE = "NONE"


class CraftingMode(str, Enum):
    #: Value is the affix package. The base is a container.
    FINISHED_RARE = "FINISHED_RARE"
    #: Value is the base plus its crafting potential, not a finished package.
    CRAFTING_BASE = "CRAFTING_BASE"
    #: Both matter: a real base identity under a real affix package.
    HYBRID_VALUE = "HYBRID_VALUE"


class BaseSignalSource(str, Enum):
    PARSED_ITEM = "PARSED_ITEM"
    CLASS_PROFILE = "CLASS_PROFILE"
    CORPUS_LABEL = "CORPUS_LABEL"


#: Provisional thresholds, all in one place so calibration has one target. None of
#: these is authority until the approved corpus re-derives it.
@dataclass(frozen=True)
class BaseThresholds:
    #: Explicit mods at or below this count make a rare look unfinished.
    sparse_affix_count: int = 2
    #: A finished package this size means the affixes, not the base, set the price.
    strong_package_material_mods: int = 4
    #: Item level at or above this is worth constraining for crafting affix access.
    crafting_item_level: int = 78
    #: How far below the item's own level a hybrid search may reach.
    hybrid_item_level_band: int = 5
    #: Quality at or above this is a crafting signal on an unfinished item.
    material_quality: int = 15

    provisional: bool = True


THRESHOLDS = BaseThresholds()

#: Base-name prefixes that denote a distinct base variant rather than a describing word.
#: Deliberately short: a wrong entry here invents a premium that does not exist. Extend
#: only with evidence.
SPECIAL_BASE_PREFIXES: frozenset[str] = frozenset({"runeforged"})

_QUALITY_RE = re.compile(r"(?im)^Quality:\s*\+?(\d+)")
_SOCKETS_RE = re.compile(r"(?im)^Sockets:\s*(\S+)")
_RUNE_RE = re.compile(r"(?im)^Rune:\s*(?!None\b)(\S+)")
_CORRUPTED_RE = re.compile(r"(?im)^Corrupted\s*$")
_ITEM_LEVEL_RE = re.compile(r"(?im)^Item Level:\s*(\d+)")


@dataclass(frozen=True)
class BaseValueProfile:
    """What the base contributes, and how much of it belongs in the query."""

    base_role: BaseRelevance
    reason_codes: tuple[str, ...]

    item_class: ItemClassKey
    exact_base: str | None = None
    base_family: str | None = None
    trade_category: str | None = None

    item_level: int | None = None
    rarity: str | None = None
    quality: int | None = None
    corrupted: bool = False

    defence_archetype: DefenceArchetype = DefenceArchetype.NONE
    base_defence_values: Mapping[str, float] = field(default_factory=dict)
    implicit_identity: tuple[str, ...] = ()
    special_state: tuple[str, ...] = ()

    crafting_mode: CraftingMode = CraftingMode.FINISHED_RARE
    confidence: float = 0.5
    source: BaseSignalSource = BaseSignalSource.PARSED_ITEM

    #: Metadata constraints this profile says are material. Anything not listed here
    #: must not reach the query, however easy it would be to add.
    item_level_min: int | None = None
    require_corrupted: bool | None = None
    quality_min: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_role": self.base_role.value,
            "reason_codes": list(self.reason_codes),
            "item_class": self.item_class.value,
            "exact_base": self.exact_base or "",
            "base_family": self.base_family or "",
            "trade_category": self.trade_category or "",
            "item_level": self.item_level,
            "rarity": self.rarity or "",
            "quality": self.quality,
            "corrupted": self.corrupted,
            "defence_archetype": self.defence_archetype.value,
            "base_defence_values": dict(self.base_defence_values),
            "implicit_identity": list(self.implicit_identity),
            "special_state": list(self.special_state),
            "crafting_mode": self.crafting_mode.value,
            "confidence": round(self.confidence, 3),
            "source": self.source.value,
            "item_level_min": self.item_level_min,
            "require_corrupted": self.require_corrupted,
            "quality_min": self.quality_min,
        }

    def explain(self) -> str:
        return f"{self.base_role.value} base ({self.crafting_mode.value}): " + "; ".join(
            self.reason_codes
        )


def base_variant_signals(special_state: Sequence[str]) -> tuple[str, ...]:
    """The subset of base state that makes this a *different base*, not a used one.

    An empty socket is the normal state of PoE2 armour and an installed rune is an added
    modifier, so neither says the buyer wants a different base. Only a base-name variant
    does. Treating sockets as a variant made every socketed rare look like a special
    base, which pushed ordinary finished items to FAMILY.
    """
    return tuple(row for row in special_state if row.startswith("special_base_variant:"))


def parse_special_state(item_raw: str, base_type: str | None) -> tuple[str, ...]:
    """Base-state facts that are not affixes: variant prefix, sockets, runes."""
    found: list[str] = []
    name = str(base_type or "").strip().lower()
    for prefix in SPECIAL_BASE_PREFIXES:
        if name.startswith(prefix):
            found.append(f"special_base_variant:{prefix}")
    sockets = _SOCKETS_RE.search(item_raw or "")
    if sockets and sockets.group(1).strip().lower() not in {"none", "-", ""}:
        found.append(f"sockets:{sockets.group(1).strip()}")
    if _RUNE_RE.search(item_raw or ""):
        found.append("rune_installed")
    return tuple(found)


def defence_archetype_for(properties: Mapping[str, float]) -> DefenceArchetype:
    """Which defence the base is built around, from the item's own property lines."""
    present = {
        DefenceArchetype.ARMOUR: float(properties.get("equip_ar") or 0.0),
        DefenceArchetype.EVASION: float(properties.get("equip_ev") or 0.0),
        DefenceArchetype.ENERGY_SHIELD: float(properties.get("equip_es") or 0.0),
    }
    nonzero = {key: value for key, value in present.items() if value > 0}
    if not nonzero:
        return DefenceArchetype.NONE
    if len(nonzero) > 1:
        return DefenceArchetype.HYBRID
    return next(iter(nonzero))


def base_family_key(
    item_class: ItemClassKey,
    archetype: DefenceArchetype,
    distinctive_implicit: str | None = None,
) -> str | None:
    """A family the market actually reasons about: "an energy shield boot".

    Trade2 has no base-family filter, so this is a *logical* family. It exists so the
    plan can state its intent, and the coverage report can say the query could not
    express it — rather than the intent quietly disappearing. Jewellery has no defence
    property, so there the family is named by the base's own implicit.
    """
    if archetype is not DefenceArchetype.NONE:
        return f"{item_class.value}/{archetype.value}"
    if distinctive_implicit:
        return f"{item_class.value}/{distinctive_implicit}"
    return None


def distinctive_implicit_family(mods: Sequence[MarketMod]) -> str | None:
    """The base implicit that adds something the item's own affixes do not.

    A Sapphire Ring's cold-resistance implicit on an item that already rolls cold
    resistance is just more of the same, and does not make the base family matter. An
    attribute implicit on an item with no attribute affix is the base contributing
    something of its own, which is exactly when a buyer cares which base it is.
    """
    explicit = {row.stat_family for row in mods if row.source is not ModSource.IMPLICIT}
    for row in mods:
        if row.source is ModSource.IMPLICIT and row.stat_family not in explicit:
            return row.stat_family
    return None


def _implicit_lines(mods: Sequence[MarketMod]) -> tuple[str, ...]:
    return tuple(row.source_text for row in mods if row.source is ModSource.IMPLICIT)


def _material_mod_count(mods: Sequence[MarketMod]) -> int:
    return sum(1 for row in mods if row.market_role in {MarketRole.ANCHOR, MarketRole.FLEXIBLE})


def _explicit_mod_count(mods: Sequence[MarketMod]) -> int:
    return sum(
        1
        for row in mods
        if row.source in {ModSource.EXPLICIT, ModSource.FRACTURED, ModSource.CRAFTED, ModSource.DESECRATED}
    )


def _crafting_mode(
    *,
    rarity: str | None,
    item_level: int | None,
    quality: int | None,
    explicit_mods: int,
    material_mods: int,
    special_state: Sequence[str],
    archetype: DefenceArchetype,
    reasons: list[str],
) -> CraftingMode:
    """Is this priced as a finished item, as a base, or as both?

    Rarity is a strong signal but never the definition: a rare with two affixes and a
    high item level is a crafting base, and a normal item with nothing going for it is
    neither.
    """
    normalized = str(rarity or "").strip().upper()
    unfinished = normalized in {"NORMAL", "MAGIC"} or explicit_mods <= THRESHOLDS.sparse_affix_count
    high_level = item_level is not None and item_level >= THRESHOLDS.crafting_item_level
    strong_package = material_mods >= THRESHOLDS.strong_package_material_mods
    variant = base_variant_signals(special_state)
    base_identity = bool(variant) or archetype is not DefenceArchetype.NONE

    if unfinished:
        if high_level or quality and quality >= THRESHOLDS.material_quality or special_state:
            reasons.append(
                "few or no finished affixes, with item level, quality or base state that "
                "a crafter would pay for"
            )
            return CraftingMode.CRAFTING_BASE
        reasons.append("few finished affixes and nothing about the base to sell")
        return CraftingMode.FINISHED_RARE

    if strong_package and base_identity and (variant or high_level):
        reasons.append("a real affix package on a base that also has its own identity")
        return CraftingMode.HYBRID_VALUE

    reasons.append("value is in the finished affix package")
    return CraftingMode.FINISHED_RARE


def _base_role(
    *,
    profile: ItemClassProfile,
    crafting_mode: CraftingMode,
    special_state: Sequence[str],
    archetype: DefenceArchetype,
    implicit_identity: Sequence[str],
    distinctive_implicit: str | None,
    material_mods: int,
    reasons: list[str],
) -> BaseRelevance:
    """How hard the base should constrain the search.

    The rule is a contest between two claims: how much identity the base has of its
    own, and how much of the price the affixes already explain.
    """
    strong_package = material_mods >= THRESHOLDS.strong_package_material_mods
    variant = base_variant_signals(special_state)

    if crafting_mode is CraftingMode.CRAFTING_BASE:
        reasons.append("a crafting base is bought as that exact base")
        return BaseRelevance.EXACT

    if variant and not strong_package:
        reasons.append("a distinct base variant with no finished package to dominate it")
        return BaseRelevance.EXACT

    if variant and strong_package:
        reasons.append(
            "a distinct base variant, but the finished package is strong enough that a "
            "buyer would take an equivalent piece"
        )
        return BaseRelevance.FAMILY

    if archetype is not DefenceArchetype.NONE and profile.base_relevance is BaseRelevance.FAMILY:
        reasons.append(
            f"the {archetype.value.lower().replace('_', ' ')} archetype is part of what is bought"
        )
        return BaseRelevance.FAMILY

    # The class profile's own view, and nothing about what Trade2 can express. A class
    # with no trade category still has an economic intent; degrading that intent to an
    # exact-base query is the constraint layer's job, and it records the loss.
    if profile.base_relevance is BaseRelevance.CATEGORY:
        reasons.append("an ordinary finished item; equivalent bases are substitutes")
    else:
        reasons.append(
            f"the class prices its base at {profile.base_relevance.value} level even when "
            f"the affixes are ordinary"
        )
    return profile.base_relevance


def build_base_profile(
    item_raw: str,
    mods: Sequence[MarketMod],
    *,
    category: str | None = None,
    base_type: str | None = None,
    rarity: str | None = None,
    item_level: int | None = None,
    quality: int | None = None,
    corrupted: bool | None = None,
) -> BaseValueProfile:
    """Decide what the base means for this item's market. No price is consulted."""
    item_class = classify_item_class(item_raw, category=category, base_type=base_type)
    profile = profile_for(item_class)
    raw = str(item_raw or "")

    if item_level is None:
        found = _ITEM_LEVEL_RE.search(raw)
        item_level = int(found.group(1)) if found else None
    if quality is None:
        found = _QUALITY_RE.search(raw)
        quality = int(found.group(1)) if found else None
    if corrupted is None:
        corrupted = bool(_CORRUPTED_RE.search(raw))

    properties = parse_equipment_properties(raw)
    archetype = defence_archetype_for(properties)
    special_state = parse_special_state(raw, base_type)
    implicit_identity = _implicit_lines(mods)
    distinctive_implicit = distinctive_implicit_family(mods)
    material_mods = _material_mod_count(mods)
    explicit_mods = _explicit_mod_count(mods)

    reasons: list[str] = []
    crafting_mode = _crafting_mode(
        rarity=rarity,
        item_level=item_level,
        quality=quality,
        explicit_mods=explicit_mods,
        material_mods=material_mods,
        special_state=special_state,
        archetype=archetype,
        reasons=reasons,
    )
    base_role = _base_role(
        profile=profile,
        crafting_mode=crafting_mode,
        special_state=special_state,
        archetype=archetype,
        implicit_identity=implicit_identity,
        distinctive_implicit=distinctive_implicit,
        material_mods=material_mods,
        reasons=reasons,
    )

    level_min, corrupted_rule, quality_min = _metadata_constraints(
        crafting_mode=crafting_mode,
        base_role=base_role,
        item_level=item_level,
        quality=quality,
        corrupted=bool(corrupted),
        reasons=reasons,
    )

    return BaseValueProfile(
        base_role=base_role,
        reason_codes=tuple(reasons),
        item_class=item_class,
        exact_base=str(base_type or "").strip() or None,
        base_family=base_family_key(item_class, archetype, distinctive_implicit),
        trade_category=profile.trade_category,
        item_level=item_level,
        rarity=str(rarity or "").strip().upper() or None,
        quality=quality,
        corrupted=bool(corrupted),
        defence_archetype=archetype,
        base_defence_values=dict(properties),
        implicit_identity=implicit_identity,
        special_state=special_state,
        crafting_mode=crafting_mode,
        confidence=_confidence(item_level=item_level, archetype=archetype, mods=mods),
        item_level_min=level_min,
        require_corrupted=corrupted_rule,
        quality_min=quality_min,
    )


def _metadata_constraints(
    *,
    crafting_mode: CraftingMode,
    base_role: BaseRelevance,
    item_level: int | None,
    quality: int | None,
    corrupted: bool,
    reasons: list[str],
) -> tuple[int | None, bool | None, int | None]:
    """Which parsed metadata is allowed into the query.

    The point is restraint. Item level, quality and corrupted state are all parsed for
    every item, and putting all three into every query would narrow the comparable set
    for reasons that have nothing to do with what the item is worth.
    """
    level_min: int | None = None
    if item_level is not None:
        if crafting_mode is CraftingMode.CRAFTING_BASE:
            # Affix access is the product, so the level is the product.
            level_min = item_level
            reasons.append(f"item level {item_level} gates the affixes a crafter is buying")
        elif crafting_mode is CraftingMode.HYBRID_VALUE:
            level_min = max(1, item_level - THRESHOLDS.hybrid_item_level_band)
            reasons.append(
                f"item level constrained loosely (>= {level_min}) because base access "
                f"contributes, but the package still dominates"
            )
        # A finished rare gets no item-level constraint at all: nobody pays for the
        # level of an item they are buying for its mods.

    corrupted_rule: bool | None = None
    if corrupted:
        corrupted_rule = True
        reasons.append("corrupted items are a different market and are compared to their own")
    elif crafting_mode is CraftingMode.CRAFTING_BASE:
        corrupted_rule = False
        reasons.append("a crafting base must be uncorrupted to be worth crafting on")

    quality_min: int | None = None
    if (
        crafting_mode is CraftingMode.CRAFTING_BASE
        and quality is not None
        and quality >= THRESHOLDS.material_quality
    ):
        quality_min = quality
        reasons.append(f"quality {quality} is part of what a crafting base sells for")

    return level_min, corrupted_rule, quality_min


def _confidence(*, item_level: int | None, archetype: DefenceArchetype, mods: Sequence[MarketMod]) -> float:
    """How much of the evidence this profile wanted was actually present."""
    score = 0.4
    if item_level is not None:
        score += 0.2
    if archetype is not DefenceArchetype.NONE:
        score += 0.2
    if any(row.has_tier_data for row in mods):
        score += 0.2
    return min(1.0, score)
