"""MARKET-03 — what a final item defence property means economically.

``Armour: 720``, ``Energy Shield: 386`` and ``Evasion Rating: 640`` are not ordinary
affixes. Each is the economic *result* of base defence, local flat and increased defence
affixes, quality, and whatever else the item does locally. Treating one as a stat whose
role follows from its magnitude produced the single biggest defect in the approved
corpus: five items whose defence property is the reason they are bought were classified
as merely substitutable, because their number sat under a provisional constant.

The number is not the signal. The context is:

* what the class is bought for;
* whether the item is a crafting base, a hybrid, or a finished piece;
* how much the base itself constrains the search;
* whether the rest of the item corroborates a defensive identity;
* whether local affixes materially changed the property, or the base produced it.

The same raw defence value therefore gets different roles on different items, which is
the point. An absolute threshold survives only as a last-resort tie-breaker where the
context says nothing.

This module decides **role**. It says nothing about search minimums; that is
``SearchRangePolicy``'s job.

Offline only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from poe2value.price_check.base_value import (
    BaseValueProfile,
    CraftingMode,
    DefenceArchetype,
)
from poe2value.price_check.market_mod import MarketMod, MarketRole, ModSource
from poe2value.price_check.market_profiles import BaseRelevance, ItemClassProfile

#: Final item properties this module reasons about. Weapon DPS properties are a separate
#: economic model and are deliberately out of scope here.
DEFENCE_PROPERTY_FAMILIES: dict[str, DefenceArchetype] = {
    "equip_ar": DefenceArchetype.ARMOUR,
    "equip_ev": DefenceArchetype.EVASION,
    "equip_es": DefenceArchetype.ENERGY_SHIELD,
}

#: Local affixes that feed each final property. A component here is represented *by* the
#: property and must never become a competing filter.
LOCAL_DEFENCE_FAMILIES: dict[DefenceArchetype, frozenset[str]] = {
    DefenceArchetype.ARMOUR: frozenset({"armour"}),
    DefenceArchetype.EVASION: frozenset({"evasion"}),
    DefenceArchetype.ENERGY_SHIELD: frozenset({"maximum_energy_shield", "energy_shield"}),
}

#: Families that corroborate a defensive identity when they appear beside a property.
_DEFENSIVE_SUPPORT = frozenset(
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
    }
)

#: Above this share of the final property, local affixes have materially changed it and
#: the base alone no longer represents it. Below it, the split is not clear enough to
#: claim either way.
_LOCALLY_ENHANCED_SHARE = 0.33


class DefenceEconomicSource(str, Enum):
    """Where the property's value came from."""

    #: The base produced it; no local affix contributes.
    BASE_INTRINSIC = "BASE_INTRINSIC"
    #: Local affixes moved it materially away from the base's own number.
    LOCALLY_ENHANCED = "LOCALLY_ENHANCED"
    #: Local affixes contribute, but not enough to claim they define it.
    MIXED = "MIXED"
    #: Not determinable from what the item printed. Never guessed.
    UNKNOWN = "UNKNOWN"


class DefenceRepresentation(str, Enum):
    """How the query should carry the property."""

    #: Needs its own equipment filter.
    PROPERTY_PRIMARY = "PROPERTY_PRIMARY"
    #: An exact-base constraint already guarantees it.
    BASE_REPRESENTED = "BASE_REPRESENTED"


@dataclass(frozen=True)
class DefencePropertyAssessment:
    family: str
    defence_type: DefenceArchetype
    economic_source: DefenceEconomicSource
    representation: DefenceRepresentation
    role: MarketRole
    is_primary: bool
    reasons: tuple[str, ...] = ()

    @property
    def base_represented(self) -> bool:
        return self.representation is DefenceRepresentation.BASE_REPRESENTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "defence_type": self.defence_type.value,
            "economic_source": self.economic_source.value,
            "representation": self.representation.value,
            "role": self.role.value,
            "is_primary": self.is_primary,
            "reasons": list(self.reasons),
        }


def _local_mods(mods: Sequence[MarketMod], defence: DefenceArchetype) -> list[MarketMod]:
    wanted = LOCAL_DEFENCE_FAMILIES.get(defence, frozenset())
    return [
        row
        for row in mods
        if row.stat_family in wanted and row.source not in {ModSource.PSEUDO, ModSource.PROPERTY}
    ]


def _economic_source(
    property_value: float, locals_: Sequence[MarketMod]
) -> tuple[DefenceEconomicSource, str]:
    """How much of the final property the item's own affixes explain.

    Only printed numbers are used. A percentage affix implies the pre-affix value
    arithmetically (``final / (1 + pct/100)``), which is an estimate rather than a
    reading — quality and other local effects also apply — so it decides only whether the
    local contribution is clearly material. Nothing here invents a base defence value; when
    the split cannot be argued from what the item printed, the answer is ``UNKNOWN``.
    """
    if property_value <= 0:
        return DefenceEconomicSource.UNKNOWN, "the property has no readable value"
    if not locals_:
        return (
            DefenceEconomicSource.BASE_INTRINSIC,
            "no local defence affix on the item, so the base produced this defence",
        )

    percent = 0.0
    flat_total = 0.0
    for row in locals_:
        text = row.source_text.lower()
        # "76% increased Energy Shield" scales the base; "+30 to maximum Energy Shield"
        # adds to it. The two combine differently and are counted apart.
        if "increased" in text or "reduced" in text:
            percent += float(row.raw_value)
        else:
            flat_total += float(row.raw_value)

    share = 0.0
    if percent > 0:
        share = max(share, percent / (100.0 + percent))
    if flat_total > 0:
        share = max(share, min(1.0, flat_total / property_value))

    if share <= 0:
        return DefenceEconomicSource.UNKNOWN, "local defence affixes present but not quantifiable"
    if share >= _LOCALLY_ENHANCED_SHARE:
        return (
            DefenceEconomicSource.LOCALLY_ENHANCED,
            f"local affixes account for roughly {share:.0%} of this defence",
        )
    return (
        DefenceEconomicSource.MIXED,
        f"local affixes contribute roughly {share:.0%}, not enough to define the property",
    )


def _representation(
    source: DefenceEconomicSource, base_profile: BaseValueProfile
) -> tuple[DefenceRepresentation, str]:
    """An exact base represents its own intrinsic defence, and nothing more.

    A base pinned by ``query.type`` guarantees the defence that base produces. It does not
    guarantee a defence that local affixes moved, so a locally enhanced property still
    needs its own equipment filter.
    """
    if base_profile.base_role is not BaseRelevance.EXACT:
        return (
            DefenceRepresentation.PROPERTY_PRIMARY,
            "the query does not pin an exact base, so the property needs its own filter",
        )
    if source is DefenceEconomicSource.BASE_INTRINSIC:
        return (
            DefenceRepresentation.BASE_REPRESENTED,
            "the exact base the query already asks for produces this defence",
        )
    return (
        DefenceRepresentation.PROPERTY_PRIMARY,
        "local affixes moved this defence away from the base's own value, so the base does "
        "not represent it",
    )


def _class_prices_this_defence(family: str, class_profile: ItemClassProfile) -> bool:
    """Does this item class get bought *for* its defence?

    Body armour and offhands do; boots are bought for movement, gloves and helmets for
    their affixes. The class profile already states this in its anchor candidates, so the
    answer is read from there rather than restated.
    """
    return family in class_profile.anchor_families


def _has_defensive_support(mods: Sequence[MarketMod], property_family: str) -> bool:
    """Does the rest of the item corroborate a defensive identity?

    A large defence number beside real life and resistances is a defensive item. The same
    property alone on an otherwise empty piece is the only thing the item has, not
    evidence that buyers choose it for that defence.
    """
    return any(
        row.stat_family in _DEFENSIVE_SUPPORT
        and row.market_role in {MarketRole.ANCHOR, MarketRole.FLEXIBLE}
        and row.stat_family != property_family
        for row in mods
    )


def _role(
    *,
    family: str,
    is_primary: bool,
    mods: Sequence[MarketMod],
    base_profile: BaseValueProfile,
    class_profile: ItemClassProfile,
    reasons: list[str],
) -> MarketRole:
    """The property's economic role, from context rather than magnitude."""
    if not is_primary:
        reasons.append("a secondary defence on this item; the primary one carries its identity")
        return MarketRole.OPTIONAL

    crafting = base_profile.crafting_mode
    base_role = base_profile.base_role

    if crafting is CraftingMode.CRAFTING_BASE and base_role in {
        BaseRelevance.EXACT,
        BaseRelevance.FAMILY,
    }:
        reasons.append(
            "this is bought as a base, and its defence is part of what makes the base worth "
            "buying"
        )
        return MarketRole.ANCHOR

    if _class_prices_this_defence(family, class_profile) and base_role in {
        BaseRelevance.EXACT,
        BaseRelevance.FAMILY,
    }:
        if crafting is CraftingMode.HYBRID_VALUE:
            reasons.append(
                "a base whose defence is why this class is bought, and the finished package "
                "does not erase that"
            )
            return MarketRole.ANCHOR
        if _has_defensive_support(mods, family):
            reasons.append(
                "this class is bought for its defence, and the rest of the item corroborates a "
                "defensive identity"
            )
            return MarketRole.ANCHOR
        reasons.append(
            "this class is bought for its defence, but nothing else on the item supports that "
            "identity"
        )
        return MarketRole.FLEXIBLE

    if base_role is BaseRelevance.CATEGORY:
        if _local_mods(mods, DEFENCE_PROPERTY_FAMILIES[family]):
            reasons.append(
                "equivalent bases substitute here, but the item did invest affixes in this "
                "defence"
            )
            return MarketRole.FLEXIBLE
        reasons.append(
            "equivalent bases substitute here and no affix invested in this defence, so it is "
            "incidental to the price"
        )
        return MarketRole.OPTIONAL

    reasons.append("real defence on a base that matters, but substitutable for this class")
    return MarketRole.FLEXIBLE


def assess_defence_properties(
    mods: Sequence[MarketMod],
    base_profile: BaseValueProfile,
    class_profile: ItemClassProfile,
) -> dict[str, DefencePropertyAssessment]:
    """Assess every final defence property on the item, keyed by ``mod_id``."""
    properties = [
        row
        for row in mods
        if row.stat_family in DEFENCE_PROPERTY_FAMILIES and row.source is ModSource.PROPERTY
    ]
    if not properties:
        return {}
    primary = max(properties, key=lambda row: row.raw_value)

    out: dict[str, DefencePropertyAssessment] = {}
    for row in properties:
        defence = DEFENCE_PROPERTY_FAMILIES[row.stat_family]
        locals_ = _local_mods(mods, defence)
        source, source_reason = _economic_source(row.raw_value, locals_)
        representation, representation_reason = _representation(source, base_profile)
        reasons: list[str] = []
        role = _role(
            family=row.stat_family,
            is_primary=row.mod_id == primary.mod_id,
            mods=mods,
            base_profile=base_profile,
            class_profile=class_profile,
            reasons=reasons,
        )
        reasons.extend((source_reason, representation_reason))
        out[row.mod_id] = DefencePropertyAssessment(
            family=row.stat_family,
            defence_type=defence,
            economic_source=source,
            representation=representation,
            role=role,
            is_primary=row.mod_id == primary.mod_id,
            reasons=tuple(reasons),
        )
    return out


def local_component_mod_ids(
    mods: Sequence[MarketMod], assessments: Mapping[str, DefencePropertyAssessment]
) -> frozenset[str]:
    """Local affixes whose concept a final property already carries.

    These become INFORMATIONAL with ``REPRESENTED_BY_PROPERTY`` coverage rather than
    competing with the property for a filter.
    """
    covered: set[str] = set()
    for assessment in assessments.values():
        if assessment.representation is DefenceRepresentation.BASE_REPRESENTED and (
            assessment.economic_source is DefenceEconomicSource.BASE_INTRINSIC
        ):
            # Nothing local contributed, so there is nothing to collapse.
            continue
        for row in _local_mods(mods, assessment.defence_type):
            covered.add(row.mod_id)
    return frozenset(covered)


def defence_property_families(mods: Iterable[MarketMod]) -> frozenset[str]:
    return frozenset(
        row.stat_family
        for row in mods
        if row.stat_family in DEFENCE_PROPERTY_FAMILIES and row.source is ModSource.PROPERTY
    )
