"""MARKET-03 — ``MarketDesirabilityEngine``.

Its job is **not** to produce a price. It answers one question per characteristic:

    does this materially define what buyers pay for *this* item?

and records why. The answer is a :class:`~exilelens.price_check.market_mod.MarketRole`,
assigned to every characteristic the item has. There is deliberately no top-N, no
``max_selected`` and no list slice anywhere in this module: an item may come out with
one anchor and five flexible characteristics, or four anchors and one, and the query
compiler — not this engine — decides how to express that without an unbounded query.

Market importance is kept strictly separate from build importance (brief section 8).
Nothing here reads PoB, DPS deltas or profile scores; ``build_relevance`` stays unset
and is display-only.

Signals, in the order consulted:

1. the item-class profile's candidate families;
2. redundancy resolution — one canonical representation per economic concept;
3. tier bounds and roll percentile, when the client printed them;
4. the absolute (provisional) floor, when it did not;
5. synergy support from the rest of the item;
6. source provenance — a base implicit is not the same claim as a rolled affix.

Learned market signatures and cached observations are further inputs the brief calls
for; they are wired in a later slice and are deliberately absent rather than faked.

Offline only. No network, no live probing (brief section 29).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from exilelens.price_check.market_mod import (
    ExtractedMods,
    MarketMod,
    MarketRole,
    ModSource,
    UNMAPPED_FAMILY_PREFIX,
    extract_market_mods,
)
from exilelens.price_check.base_value import BaseValueProfile, build_base_profile
from exilelens.price_check.defence_semantics import (
    DefencePropertyAssessment,
    assess_defence_properties,
    local_component_mod_ids,
)
from exilelens.price_check.market_profiles import (
    is_known_dead_mod,
    UNIVERSAL_DEAD_FAMILIES,
    ItemClassKey,
    ItemClassProfile,
    classify_item_class,
    profile_for,
)

#: Preference order inside a redundancy group when the class profile does not name a
#: winner. A pseudo total beats its components; a final item property beats the local
#: affix that produced it.
_REPRESENTATION_FALLBACK: dict[str, tuple[str, ...]] = {
    "elemental_resistance": (
        "total_elemental_resistance",
        "total_resistance",
        "all_elemental_resistances",
    ),
    "life": ("maximum_life", "total_life"),
    "mana": ("maximum_mana", "total_mana"),
    "energy_shield": ("equip_es", "maximum_energy_shield", "total_energy_shield"),
    "armour": ("equip_ar", "armour"),
    "evasion": ("equip_ev", "evasion"),
    "attributes": ("total_attributes", "all_attributes"),
    "attack_dps": ("equip_dps", "equip_pdps", "equip_edps"),
    "movement_speed": ("movement_speed", "pseudo_movement_speed"),
}

_ROLE_BASE_SCORE: dict[MarketRole, float] = {
    MarketRole.ANCHOR: 1.0,
    MarketRole.FLEXIBLE: 0.6,
    MarketRole.OPTIONAL: 0.3,
    MarketRole.INFORMATIONAL: 0.1,
    MarketRole.DEAD: 0.0,
}


@dataclass(frozen=True)
class DesirabilityResult:
    """Every characteristic of the item, classified, with the reasoning kept."""

    item_class: ItemClassKey
    profile_label: str
    mods: tuple[MarketMod, ...]
    unparsed_mod_texts: tuple[str, ...] = ()
    #: Flexible mods clustered by shared synergy tag. Becomes one COUNT group each.
    synergy_clusters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    tier_data_available: bool = False
    #: Present only on a base-aware pass. Keyed by ``mod_id``.
    defence_assessments: Mapping[str, DefencePropertyAssessment] = field(default_factory=dict)

    def role(self, role: MarketRole) -> tuple[MarketMod, ...]:
        return tuple(row for row in self.mods if row.market_role is role)

    @property
    def anchors(self) -> tuple[MarketMod, ...]:
        return self.role(MarketRole.ANCHOR)

    @property
    def flexible(self) -> tuple[MarketMod, ...]:
        return self.role(MarketRole.FLEXIBLE)

    @property
    def optional(self) -> tuple[MarketMod, ...]:
        return self.role(MarketRole.OPTIONAL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_class": self.item_class.value,
            "profile_label": self.profile_label,
            "tier_data_available": self.tier_data_available,
            "mods": [row.to_dict() for row in self.mods],
            "unparsed_mod_texts": list(self.unparsed_mod_texts),
            "synergy_clusters": [
                {"tag": tag, "families": list(families)} for tag, families in self.synergy_clusters
            ],
            "defence_assessments": {
                key: value.to_dict() for key, value in self.defence_assessments.items()
            },
        }


def _representation_winner(
    group: str,
    candidates: Iterable[MarketMod],
    profile: ItemClassProfile,
) -> MarketMod:
    """One canonical row per economic concept (brief section 6).

    The class profile names the winner where the class has an opinion — resistances
    resolve to the pseudo total on armour, energy shield resolves to the final item
    property. Otherwise a fixed preference order applies, and a genuine tie is broken
    by rolled affix over base implicit, then by value.
    """
    rows = list(candidates)
    preferred = (profile.preferred_representation or {}).get(group)
    for family in ((preferred,) if preferred else ()) + _REPRESENTATION_FALLBACK.get(group, ()):
        same_family = [row for row in rows if row.stat_family == family]
        if same_family:
            return _best_of(same_family)
    return _best_of(rows)


def _best_of(rows: list[MarketMod]) -> MarketMod:
    """The strongest claim among equivalent rows.

    An item can carry the same family twice — a rune-granted ``Bonded: +40 to maximum
    Life`` beside an explicit ``+214 to maximum Life``. The rolled affix is the item's
    real economic claim, and among equals the larger roll wins.
    """
    rank = {ModSource.IMPLICIT: 2, ModSource.BONDED: 1, ModSource.RUNE: 1}
    return min(rows, key=lambda row: (rank.get(row.source, 0), -row.raw_value, row.mod_id))


def _score(mod: MarketMod, role: MarketRole, *, synergy_support: int) -> float:
    """Ordering weight for the panel. Never a threshold, never a cap."""
    score = _ROLE_BASE_SCORE[role]
    if role is MarketRole.DEAD:
        return 0.0
    if mod.roll_percentile is not None:
        # A roll high inside its own tier is worth more than the same number would be
        # at the bottom of a better tier.
        score += 0.15 * mod.roll_percentile
    if mod.source is ModSource.IMPLICIT:
        score -= 0.05
    score += 0.03 * max(0, synergy_support - 1)
    return round(max(0.0, score), 4)


class MarketDesirabilityEngine:
    """Classify every characteristic of one item. No selection, no truncation."""

    def classify(
        self,
        item_raw: str,
        *,
        category: str | None = None,
        base_type: str | None = None,
        rarity: str | None = None,
        extracted: ExtractedMods | None = None,
        base_profile: BaseValueProfile | None = None,
    ) -> DesirabilityResult:
        item_class = classify_item_class(item_raw, category=category, base_type=base_type)
        profile = profile_for(item_class)
        found = extracted if extracted is not None else extract_market_mods(item_raw, category=category)

        winners = self._resolve_redundancy(found.mods, profile)
        synergy_support = self._synergy_support(found.mods)

        classified: list[MarketMod] = []
        for mod in found.mods:
            role, reasons = self._role_for(
                mod,
                profile=profile,
                is_representation_winner=mod.mod_id in winners,
            )
            support = synergy_support.get(mod.stat_family, 0)
            classified.append(
                mod.with_role(role, score=_score(mod, role, synergy_support=support), reasons=reasons)
            )

        assessments: dict[str, DefencePropertyAssessment] = {}
        if base_profile is not None:
            classified, assessments = self._apply_defence_semantics(
                classified, base_profile=base_profile, profile=profile
            )

        ordered = tuple(
            sorted(classified, key=lambda row: (-row.desirability_score, row.stat_family))
        )
        return DesirabilityResult(
            item_class=item_class,
            profile_label=profile.label,
            mods=ordered,
            unparsed_mod_texts=found.unparsed_mod_texts,
            synergy_clusters=self._clusters(ordered, profile),
            tier_data_available=any(row.has_tier_data for row in found.mods),
            defence_assessments=assessments,
        )

    def _apply_defence_semantics(
        self,
        classified: list[MarketMod],
        *,
        base_profile: BaseValueProfile,
        profile: ItemClassProfile,
    ) -> tuple[list[MarketMod], dict[str, DefencePropertyAssessment]]:
        """Re-decide the final defence properties with the base in view.

        A defence property's role depends on what the base is and how the item is being
        bought, which is not known during the first pass — the base profile is derived
        from that pass. So this runs after it, and touches only the defence properties
        and the local affixes they represent. Nothing else is re-scored, so the two
        passes cannot chase each other.
        """
        assessments = assess_defence_properties(classified, base_profile, profile)
        if not assessments:
            return classified, {}
        collapsed = local_component_mod_ids(classified, assessments)

        updated: list[MarketMod] = []
        for mod in classified:
            assessment = assessments.get(mod.mod_id)
            if assessment is not None:
                mod = replace(
                    mod.with_role(
                        assessment.role,
                        score=_score(mod, assessment.role, synergy_support=1),
                        reasons=assessment.reasons,
                    ),
                    base_represented=assessment.base_represented,
                )
            elif mod.mod_id in collapsed:
                mod = mod.with_role(
                    MarketRole.INFORMATIONAL,
                    score=_score(mod, MarketRole.INFORMATIONAL, synergy_support=1),
                    reasons=("already represented by the final item defence property",),
                )
            updated.append(mod)
        return updated, assessments

    # -- internals ---------------------------------------------------------------

    def _resolve_redundancy(
        self, mods: Iterable[MarketMod], profile: ItemClassProfile
    ) -> frozenset[str]:
        """Mod ids that are the canonical representation of their economic concept.

        A mod with no redundancy group is always its own representation.
        """
        grouped: dict[str, list[MarketMod]] = {}
        winners: set[str] = set()
        for mod in mods:
            if not mod.redundancy_group:
                winners.add(mod.mod_id)
                continue
            grouped.setdefault(mod.redundancy_group, []).append(mod)
        for group, rows in grouped.items():
            winners.add(_representation_winner(group, rows, profile).mod_id)
        return frozenset(winners)

    def _synergy_support(self, mods: Iterable[MarketMod]) -> dict[str, int]:
        """How many other characteristics share a synergy tag with each family.

        A resistance roll on an item that has two other resistances is part of a
        package; the same roll alone is not.
        """
        by_tag: dict[str, set[str]] = {}
        for mod in mods:
            for tag in mod.synergy_tags:
                by_tag.setdefault(tag, set()).add(mod.stat_family)
        support: dict[str, int] = {}
        for mod in mods:
            reach = set()
            for tag in mod.synergy_tags:
                reach |= by_tag.get(tag, set())
            support[mod.stat_family] = len(reach)
        return support

    def _role_for(
        self,
        mod: MarketMod,
        *,
        profile: ItemClassProfile,
        is_representation_winner: bool,
    ) -> tuple[MarketRole, tuple[str, ...]]:
        family = mod.stat_family
        reasons: list[str] = []

        if family.startswith(UNMAPPED_FAMILY_PREFIX) or not mod.is_queryable:
            if is_known_dead_mod(mod.source_text):
                return MarketRole.DEAD, ("no market effect",)
            # Unsearchable is not the same claim as worthless. A "+3 to Level of all
            # Spell Skills" the registry cannot map is one of the most valuable mods
            # in the game; calling it DEAD would be a lie the panel then repeats.
            return (
                MarketRole.INFORMATIONAL,
                ("ExileLens cannot search this modifier on trade yet",),
            )
        if family in profile.dead_families or (
            family in UNIVERSAL_DEAD_FAMILIES and family not in profile.flexible_families
        ):
            return MarketRole.DEAD, (f"no market effect on {profile.label.lower()}",)

        if not is_representation_winner:
            return (
                MarketRole.INFORMATIONAL,
                (f"already represented by the canonical {mod.redundancy_group} row",),
            )

        rule = profile.anchor_rule(family)
        if rule is not None:
            if rule.clears(raw_value=mod.raw_value, roll_percentile=mod.roll_percentile):
                reasons.append(
                    f"anchor for {profile.label.lower()} by {rule.basis(roll_percentile=mod.roll_percentile)}"
                )
                if rule.note:
                    reasons.append(rule.note)
                if mod.roll_percentile is not None:
                    reasons.append(f"roll sits {mod.roll_percentile:.0%} into its tier")
                return MarketRole.ANCHOR, tuple(reasons)
            reasons.append("anchor candidate, but the roll is below the class threshold")
            return MarketRole.FLEXIBLE, tuple(reasons)

        if family in profile.flexible_families:
            reasons.append(f"priced but substitutable on {profile.label.lower()}")
            if mod.source is ModSource.IMPLICIT:
                reasons.append("base implicit, not a rolled affix")
            return MarketRole.FLEXIBLE, tuple(reasons)

        if family in profile.optional_families:
            return MarketRole.OPTIONAL, ("occasionally priced on this class",)

        # A searchable, non-junk mod the class profile does not list. The profile is a
        # prior, not an inventory — cast speed does turn up on a helmet — so this is
        # OPTIONAL rather than INFORMATIONAL: visible in the panel and one click from
        # the query, instead of hidden under MORE STATS because a table was incomplete.
        return (
            MarketRole.OPTIONAL,
            (f"not a known driver for {profile.label.lower()} — shown in case it matters",),
        )

    def _clusters(
        self, mods: Iterable[MarketMod], profile: ItemClassProfile
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Flexible characteristics grouped into substitutable sets.

        Each cluster becomes one COUNT group. Two passes: first the class's own synergy
        tags, then everything still unclaimed into one remainder group — buyers
        substitute across concepts too, which is the brief's own boots example
        ("at least 1 of: total res, energy shield, attribute"). A cluster of one is not
        a choice, so it is dropped and the compiler treats that mod on its own.
        """
        flexible = [row for row in mods if row.market_role is MarketRole.FLEXIBLE]
        clusters: list[tuple[str, tuple[str, ...]]] = []
        claimed: set[str] = set()
        for tag in profile.synergy_groups:
            members = tuple(
                row.stat_family
                for row in flexible
                if tag in row.synergy_tags and row.stat_family not in claimed
            )
            if len(members) >= 2:
                clusters.append((tag, members))
                claimed.update(members)
        remainder = tuple(row.stat_family for row in flexible if row.stat_family not in claimed)
        if len(remainder) >= 2:
            clusters.append(("substitutable", remainder))
        return tuple(clusters)


def classify_item(
    item_raw: str,
    *,
    category: str | None = None,
    base_type: str | None = None,
    rarity: str | None = None,
) -> DesirabilityResult:
    """Convenience wrapper around :class:`MarketDesirabilityEngine`."""
    return MarketDesirabilityEngine().classify(
        item_raw, category=category, base_type=base_type, rarity=rarity
    )


def classify_with_base(
    item_raw: str,
    *,
    category: str | None = None,
    base_type: str | None = None,
    rarity: str | None = None,
    item_level: int | None = None,
    quality: int | None = None,
    corrupted: bool | None = None,
) -> tuple[DesirabilityResult, BaseValueProfile]:
    """Classify, derive the base profile, then re-decide the defence properties.

    Two passes, in this order for a reason. The base profile reads how finished the item
    is, which needs roles; the defence properties need the base profile. Running the base
    profile against the first pass and letting the second pass touch only the defence
    properties keeps that dependency one-directional.
    """
    engine = MarketDesirabilityEngine()
    first = engine.classify(item_raw, category=category, base_type=base_type, rarity=rarity)
    profile = build_base_profile(
        item_raw,
        first.mods,
        category=category,
        base_type=base_type,
        rarity=rarity,
        item_level=item_level,
        quality=quality,
        corrupted=corrupted,
    )
    second = engine.classify(
        item_raw,
        category=category,
        base_type=base_type,
        rarity=rarity,
        base_profile=profile,
    )
    return second, profile
