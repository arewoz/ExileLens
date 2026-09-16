"""Choose the features that give a rare item its economic identity.

MARKET-01B13. `important_features` keeps CRITICAL/HIGH only, which is right for the
items it was written for and wrong for the ones it silently drops: a Jade Amulet whose
four mods score MEDIUM / MEDIUM / LOW / LOW yields an empty set, so the remote query
degenerates to the base type and the "estimate" is a base-type market price wearing the
label of an item valuation.

This module adds a bounded fallback on top of that vocabulary rather than changing it.
CRITICAL/HIGH stays primary; when it produces nothing, at most two market-relevant
MEDIUM features are promoted; LOW is promoted only when there is nothing stronger at all
and the family is one buyers actually search on. When even that finds nothing, the caller
is told so explicitly, so the result can be presented as a base estimate instead of
passing for an item estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from poe2value.price_check.comparable_features import (
    ComparableFeature,
    ModImportance,
    important_features,
)

# A modded rare needs at least one feature to be more than its base type; two make the
# neighbourhood specific enough to be worth calling comparable.
MIN_ECONOMIC_IDENTITY = 1
PREFERRED_ECONOMIC_IDENTITY = 2

# The cap that keeps this a fallback rather than a clone search (§3, §7).
MAX_FALLBACK_FEATURES = 2

# MEDIUM families that carry real market demand. Deliberately not "every MEDIUM": a
# fallback built from whatever happens to be MEDIUM produces narrow, nonsense queries.
FALLBACK_MEDIUM_FAMILIES = frozenset(
    {
        "maximum_life",
        "maximum_energy_shield",
        "energy_shield",
        "maximum_mana",
        "fire_resistance",
        "cold_resistance",
        "lightning_resistance",
        "chaos_resistance",
        "all_elemental_resistances",
        "critical_strike_chance",
        "critical_strike_multiplier",
    }
)

# LOW families worth a query only when nothing stronger exists. Attributes and raw
# defences are searched by real buyers; a mana regeneration roll is not.
FALLBACK_LOW_FAMILIES = frozenset(
    {
        "strength",
        "dexterity",
        "intelligence",
        "armour",
        "evasion",
    }
)


class IdentitySource(str, Enum):
    """Where a query's economic identity came from."""

    PRIMARY = "PRIMARY"
    FALLBACK_MEDIUM = "FALLBACK_MEDIUM"
    FALLBACK_LOW = "FALLBACK_LOW"
    BASE_ONLY = "BASE_ONLY"


@dataclass(frozen=True)
class EconomicIdentity:
    """The features a query should search on, and how they were chosen."""

    features: tuple[ComparableFeature, ...]
    source: IdentitySource
    reason: str

    @property
    def is_base_only(self) -> bool:
        return self.source is IdentitySource.BASE_ONLY or not self.features

    @property
    def used_fallback(self) -> bool:
        return self.source in {IdentitySource.FALLBACK_MEDIUM, IdentitySource.FALLBACK_LOW}

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source.value,
            "reason": self.reason,
            "features": [row.to_dict() for row in self.features],
        }


def _query_safe(feature: ComparableFeature) -> bool:
    """A feature the trade query can actually express."""
    return bool(feature.trade_stat_id) and feature.value > 0


def _rank_key(feature: ComparableFeature) -> tuple[float, float, str]:
    """Best roll first, then largest value, then the family name for determinism."""
    return (-float(feature.normalized_roll or 0.0), -float(feature.value or 0.0), feature.family)


def _candidates(
    features: Iterable[ComparableFeature],
    importance: ModImportance,
    allowed_families: frozenset[str],
) -> list[ComparableFeature]:
    rows = [
        row
        for row in features
        if row.importance is importance and row.family in allowed_families and _query_safe(row)
    ]
    rows.sort(key=_rank_key)
    # One feature per family — two rolls of the same family narrow the search without
    # adding identity.
    picked: list[ComparableFeature] = []
    seen: set[str] = set()
    for row in rows:
        key = row.pseudo_family or row.family
        if key in seen:
            continue
        seen.add(key)
        picked.append(row)
    return picked


def select_economic_identity(
    features: Iterable[ComparableFeature],
    *,
    max_fallback: int = MAX_FALLBACK_FEATURES,
) -> EconomicIdentity:
    """The features that should carry the remote query, and where they came from.

    Stage 1 is the existing CRITICAL/HIGH set, returned untouched — an item that already
    has high-importance mods takes exactly the path it took before this module existed.
    """
    rows = tuple(features)

    primary = important_features(rows)
    if len(primary) >= MIN_ECONOMIC_IDENTITY:
        return EconomicIdentity(
            features=primary,
            source=IdentitySource.PRIMARY,
            reason=f"{len(primary)} high-importance feature{'s' if len(primary) != 1 else ''}",
        )

    medium = _candidates(rows, ModImportance.MEDIUM, FALLBACK_MEDIUM_FAMILIES)
    if medium:
        chosen = tuple(medium[: max(1, min(max_fallback, PREFERRED_ECONOMIC_IDENTITY))])
        return EconomicIdentity(
            features=chosen,
            source=IdentitySource.FALLBACK_MEDIUM,
            reason=(
                f"no high-importance mods; searched on {len(chosen)} market-relevant "
                f"medium feature{'s' if len(chosen) != 1 else ''}"
            ),
        )

    low = _candidates(rows, ModImportance.LOW, FALLBACK_LOW_FAMILIES)
    if low:
        chosen = tuple(low[: max(1, min(max_fallback, PREFERRED_ECONOMIC_IDENTITY))])
        return EconomicIdentity(
            features=chosen,
            source=IdentitySource.FALLBACK_LOW,
            reason=(
                f"no medium or high mods; searched on {len(chosen)} low-importance "
                f"feature{'s' if len(chosen) != 1 else ''} buyers still filter on"
            ),
        )

    return EconomicIdentity(
        features=(),
        source=IdentitySource.BASE_ONLY,
        reason="no market-relevant affix to search on",
    )
