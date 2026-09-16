"""MARKET-03 — ``MarketMod``: one economic characteristic of an item.

This replaces :class:`~poe2value.price_check.market_drivers.MarketPriceDriver` as the
unit the market engine reasons about. The difference is not cosmetic:

* a driver was *either selected or not*; a mod carries a
  :class:`MarketRole` on a five-value scale, so an item can express two anchors and
  four flexible characteristics without anything being deleted;
* a driver carried one ``search_min`` produced by a fixed haircut; a mod carries the
  roll, the tier bounds it came from, the roll's percentile inside that tier, and the
  :class:`SearchRangePolicy` that says how to turn those into a filter;
* a driver had no direction; a mod does, so a harmful stat can be searched with a
  maximum rather than a minimum.

Extraction here is deliberately *complete and unranked*: every parseable
characteristic becomes a mod, including ones that will turn out to be worthless.
Deciding what matters is :mod:`poe2value.price_check.desirability`'s job, and there is
no top-N anywhere in this module.

Offline only. Nothing here touches the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable

from poe2value.price_check.comparable_features import (
    ComparableFeature,
    build_features,
    normalize_mod_text,
    parse_feature_from_mod,
    strip_mod_markup,
)
from poe2value.price_check.market_drivers import parse_equipment_properties, tagged_mod_lines
from poe2value.price_check.mod_tier import TierRange, parse_tier_range, tier_range_for_value
from poe2value.price_check.stat_registry import DriverKind, get_family, trade_stat_ids


class ModSource(str, Enum):
    """Where the characteristic comes from. Not the same as its market worth."""

    EXPLICIT = "EXPLICIT"
    IMPLICIT = "IMPLICIT"
    RUNE = "RUNE"
    BONDED = "BONDED"
    FRACTURED = "FRACTURED"
    CRAFTED = "CRAFTED"
    DESECRATED = "DESECRATED"
    #: A derived item property (Armour, Energy Shield, DPS) rather than a mod line.
    PROPERTY = "PROPERTY"
    #: A total the trade site exposes that no single mod line prints.
    PSEUDO = "PSEUDO"


class Direction(str, Enum):
    """Which way the market wants this number to move.

    Semantic, not numeric. ``38% reduced Freeze Duration on you`` prints a positive
    number and more of it is better, so it is ``HIGHER_BETTER`` despite "reduced".
    ``increased Attribute Requirements`` is ``LOWER_BETTER`` despite "increased".
    """

    HIGHER_BETTER = "HIGHER_BETTER"
    LOWER_BETTER = "LOWER_BETTER"
    EXACT = "EXACT"
    BOOLEAN = "BOOLEAN"


class MarketRole(str, Enum):
    """How this characteristic participates in the search plan.

    Distinct from :class:`poe2value.price_check.comparable_features.MarketRole`, which
    is the older CRITICAL/HIGH/MEDIUM/LOW similarity weight and is unrelated.
    """

    #: Removing it changes the item's economic identity. Compiles to a hard AND filter.
    ANCHOR = "ANCHOR"
    #: Real value, but buyers substitute between them. Compiles into a COUNT group.
    FLEXIBLE = "FLEXIBLE"
    #: Plausibly priced, not required. Shown, not emitted, one click from the user.
    OPTIONAL = "OPTIONAL"
    #: True of the item but redundant or non-economic. Shown under MORE STATS.
    INFORMATIONAL = "INFORMATIONAL"
    #: No market effect on this item class.
    DEAD = "DEAD"


class SearchRangePolicy(str, Enum):
    """How the roll becomes a filter bound.

    ``ROLL_SENSITIVE`` is declared but not calibrated in this slice: the model must
    leave room for stats whose price moves inside a single tier, without MARKET-03
    guessing that curve before it is measured.
    """

    #: Continuous stat with trustworthy tier bounds — floor at the tier minimum.
    TIER_FLOOR = "TIER_FLOOR"
    #: Continuous stat whose price moves within its tier. Reserved; not yet calibrated.
    ROLL_SENSITIVE = "ROLL_SENSITIVE"
    #: Discrete stat with meaningful steps (+skills, sockets, movement-speed tiers).
    BREAKPOINT = "BREAKPOINT"
    #: The roll itself is the search value.
    EXACT = "EXACT"
    #: Aggregate total; relaxed as a sum, never per component (brief section 22).
    PSEUDO_AGGREGATE = "PSEUDO_AGGREGATE"
    #: A final item property (Armour / Evasion / Energy Shield / DPS). It has no affix
    #: tier by nature — it is the sum of base, affixes and quality — so it is relaxed as
    #: a total rather than treated as a stat whose tier is merely missing.
    PROPERTY = "PROPERTY"
    #: Continuous stat with no tier annotation — the pre-MARKET-03 haircut applies.
    DEGRADED_NO_TIER = "DEGRADED_NO_TIER"


#: Economic concepts whose members must never be emitted as independent filters.
#: The compiler asserts at most one member of a group reaches the query.
REDUNDANCY_GROUPS: dict[str, frozenset[str]] = {
    "elemental_resistance": frozenset(
        {
            "fire_resistance",
            "cold_resistance",
            "lightning_resistance",
            "all_elemental_resistances",
            "total_elemental_resistance",
            "total_resistance",
        }
    ),
    "life": frozenset({"maximum_life", "total_life"}),
    "mana": frozenset({"maximum_mana", "total_mana"}),
    "energy_shield": frozenset(
        {"maximum_energy_shield", "energy_shield", "total_energy_shield", "equip_es"}
    ),
    "armour": frozenset({"armour", "equip_ar"}),
    "evasion": frozenset({"evasion", "equip_ev"}),
    "attributes": frozenset(
        {"strength", "dexterity", "intelligence", "all_attributes", "total_attributes"}
    ),
    "attack_dps": frozenset({"equip_dps", "equip_pdps", "equip_edps", "physical_damage"}),
    "movement_speed": frozenset({"movement_speed", "pseudo_movement_speed"}),
}

_FAMILY_TO_REDUNDANCY_GROUP: dict[str, str] = {
    family: group for group, members in REDUNDANCY_GROUPS.items() for family in members
}

#: Synergy tags describe *why* several characteristics travel together in the market.
#: A flexible COUNT group is built per tag, not per stat.
SYNERGY_TAGS: dict[str, frozenset[str]] = {
    "survivability": frozenset(
        {
            "maximum_life",
            "total_life",
            "maximum_energy_shield",
            "total_energy_shield",
            "equip_es",
            "equip_ar",
            "equip_ev",
            "armour",
            "evasion",
        }
    ),
    "resistance_package": frozenset(
        {
            "fire_resistance",
            "cold_resistance",
            "lightning_resistance",
            "chaos_resistance",
            "all_elemental_resistances",
            "total_elemental_resistance",
            "total_resistance",
        }
    ),
    "caster_offence": frozenset(
        {
            "spell_damage",
            "cast_speed",
            "lightning_spell_skills",
            "all_spell_skills",
            "spell_critical_hit_chance",
            "lightning_damage",
            "fire_damage",
            "cold_damage",
            "lightning_penetration",
            "fire_penetration",
            "cold_penetration",
            "elemental_penetration",
            "gain_extra_lightning",
            "gain_extra_fire",
            "gain_extra_cold",
            "gain_extra_chaos",
        }
    ),
    "attack_offence": frozenset(
        {
            "physical_damage",
            "attack_speed",
            "attack_cast_speed",
            "critical_strike_chance",
            "critical_strike_multiplier",
            "equip_dps",
            "equip_pdps",
            "equip_edps",
        }
    ),
    "attribute_fixing": frozenset(
        {"strength", "dexterity", "intelligence", "all_attributes", "total_attributes"}
    ),
    "mobility": frozenset({"movement_speed", "pseudo_movement_speed"}),
}

#: Stats with meaningful discrete steps. Their default floor must not cross a step.
BREAKPOINT_FAMILIES: frozenset[str] = frozenset(
    {
        "lightning_spell_skills",
        "all_spell_skills",
        "movement_speed",
        "pseudo_movement_speed",
    }
)

#: Item properties, not mod lines. These are derived and always carry PROPERTY source.
PROPERTY_FAMILIES: frozenset[str] = frozenset(
    {"equip_ar", "equip_ev", "equip_es", "equip_dps", "equip_pdps", "equip_edps"}
)

#: Text shapes whose printed number the market wants *low*. Checked against the mod
#: line, because the family alone cannot distinguish a requirement from a benefit, and
#: a mod that prints a negative number is not automatically one the buyer wants smaller.
_LOWER_BETTER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"increased\s+attribute\s+requirement", re.I),
    re.compile(r"increased\s+(?:strength|dexterity|intelligence)\s+requirement", re.I),
    re.compile(r"reduced\s+(?:maximum\s+)?life\b", re.I),
    re.compile(r"reduced\s+(?:maximum\s+)?energy\s+shield\b", re.I),
    re.compile(r"increased\s+(?:damage\s+)?taken\b", re.I),
    # "-20 to Total Mana Cost of Skills": a more negative number is the better item, so
    # the market wants the *lowest* value, not the highest.
    re.compile(r"to\s+total\s+mana\s+cost", re.I),
    re.compile(r"mana\s+cost\s+of\s+skills", re.I),
)

_RUNE_TAG_RE = re.compile(r"\((?:rune|soul\s*core)\)\s*$", re.I)
#: Rune-granted mods are printed either with a trailing tag or with a ``Bonded:``
#: prefix behind PoB's brace markup (``{enchant}{rune}Bonded: +40 to maximum Life``),
#: which ``strip_mod_markup`` does not remove.
_BONDED_RE = re.compile(r"\(bonded\)\s*$|^(?:\{[a-z]+\})*\s*bonded\s*:", re.I)
_RUNE_MARKUP_RE = re.compile(r"\{rune\}|\{soulcore\}", re.I)


@dataclass(frozen=True)
class MarketMod:
    """One economic characteristic, with everything needed to price and to explain it."""

    mod_id: str
    stat_family: str
    label: str
    source: ModSource
    source_text: str
    raw_value: float

    trade_stat_ids: tuple[str, ...] = ()
    pseudo_id: str | None = None
    equipment_key: str | None = None
    driver_kind: DriverKind = DriverKind.EXACT_STAT

    #: Tier bounds as printed by Advanced Item Description. ``None`` when the client
    #: did not print them — the normal case for implicits, runes and PoB exports.
    tier_min: float | None = None
    tier_max: float | None = None
    roll_percentile: float | None = None
    tier: str | None = None

    direction: Direction = Direction.HIGHER_BETTER
    range_policy: SearchRangePolicy = SearchRangePolicy.DEGRADED_NO_TIER

    market_role: MarketRole = MarketRole.INFORMATIONAL
    desirability_score: float = 0.0
    desirability_reasons: tuple[str, ...] = ()
    synergy_tags: tuple[str, ...] = ()
    redundancy_group: str | None = None
    component_families: tuple[str, ...] = ()

    #: Display only. Never an input to query planning (brief section 8).
    build_relevance: float | None = None

    #: True when a base constraint the query already carries guarantees this
    #: characteristic, so emitting a filter for it would ask twice. Set by defence
    #: semantics; it changes *representation*, never the economic role.
    base_represented: bool = False

    @property
    def has_tier_data(self) -> bool:
        return self.tier_min is not None and self.tier_max is not None

    @property
    def is_queryable(self) -> bool:
        if self.driver_kind is DriverKind.EQUIPMENT_FILTER:
            return bool(self.equipment_key)
        return bool(self.trade_stat_ids)

    def with_role(
        self,
        role: MarketRole,
        *,
        score: float | None = None,
        reasons: Iterable[str] | None = None,
    ) -> MarketMod:
        return replace(
            self,
            market_role=role,
            desirability_score=self.desirability_score if score is None else float(score),
            desirability_reasons=tuple(reasons) if reasons is not None else self.desirability_reasons,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mod_id": self.mod_id,
            "stat_family": self.stat_family,
            "label": self.label,
            "source": self.source.value,
            "source_text": self.source_text,
            "raw_value": self.raw_value,
            "trade_stat_ids": list(self.trade_stat_ids),
            "pseudo_id": self.pseudo_id or "",
            "equipment_key": self.equipment_key or "",
            "driver_kind": self.driver_kind.value,
            "tier": self.tier or "",
            "tier_min": self.tier_min,
            "tier_max": self.tier_max,
            "roll_percentile": self.roll_percentile,
            "direction": self.direction.value,
            "range_policy": self.range_policy.value,
            "market_role": self.market_role.value,
            "desirability_score": round(self.desirability_score, 4),
            "desirability_reasons": list(self.desirability_reasons),
            "synergy_tags": list(self.synergy_tags),
            "redundancy_group": self.redundancy_group or "",
            "component_families": list(self.component_families),
            "build_relevance": self.build_relevance,
            "base_represented": self.base_represented,
        }


def redundancy_group_for(family: str) -> str | None:
    return _FAMILY_TO_REDUNDANCY_GROUP.get(family)


def synergy_tags_for(family: str) -> tuple[str, ...]:
    return tuple(sorted(tag for tag, members in SYNERGY_TAGS.items() if family in members))


def direction_for(family: str, source_text: str) -> Direction:
    """Semantic direction. Line text wins over family, because families are ambiguous."""
    text = str(source_text or "")
    for pattern in _LOWER_BETTER_PATTERNS:
        if pattern.search(text):
            return Direction.LOWER_BETTER
    return Direction.HIGHER_BETTER


def range_policy_for(
    family: str,
    *,
    source: ModSource,
    tier: TierRange | None,
) -> SearchRangePolicy:
    """Pick the default policy. The engine may override; the compiler may not."""
    if source is ModSource.PROPERTY:
        return SearchRangePolicy.PROPERTY
    if source is ModSource.PSEUDO:
        return SearchRangePolicy.PSEUDO_AGGREGATE
    if source is ModSource.FRACTURED:
        # A fractured roll is the reason the item exists; it is not relaxed by default.
        return SearchRangePolicy.EXACT
    if family in BREAKPOINT_FAMILIES:
        return SearchRangePolicy.BREAKPOINT
    if tier is not None:
        return SearchRangePolicy.TIER_FLOOR
    return SearchRangePolicy.DEGRADED_NO_TIER


def _source_for_line(line: str, *, implicit: bool) -> ModSource:
    stripped = strip_mod_markup(line)
    if _BONDED_RE.search(line) or _BONDED_RE.search(stripped):
        return ModSource.BONDED
    if _RUNE_TAG_RE.search(line) or _RUNE_MARKUP_RE.search(line):
        return ModSource.RUNE
    lowered = line.lower()
    if "(implicit)" in lowered:
        return ModSource.IMPLICIT
    if "(fractured)" in lowered:
        return ModSource.FRACTURED
    if "(crafted)" in lowered:
        return ModSource.CRAFTED
    if "(desecrated)" in lowered:
        return ModSource.DESECRATED
    return ModSource.IMPLICIT if implicit else ModSource.EXPLICIT


def _mod_id(family: str, source: ModSource) -> str:
    return f"{family}:{source.value}"


#: Family prefix for a mod line the stat registry cannot map to a Trade2 stat.
UNMAPPED_FAMILY_PREFIX = "unmapped:"


def _unmapped_family(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalize_mod_text(text).lower()).strip("_")
    return f"{UNMAPPED_FAMILY_PREFIX}{slug[:60] or 'mod'}"


def _build_unmapped_mod(line: str, *, source: ModSource) -> MarketMod:
    """A mod the item has but the market cannot be searched on.

    These must still exist as objects. The product gate requires every meaningful mod
    to be *visible* (brief section 52), and a characteristic the human corpus labels
    DEAD cannot be graded if extraction silently dropped it. They are never queryable:
    ``trade_stat_ids`` is empty, so the compiler cannot emit them even by mistake.
    """
    cleaned = strip_mod_markup(line)
    tier = parse_tier_range(line)
    family = _unmapped_family(cleaned)
    return MarketMod(
        mod_id=_mod_id(family, source),
        stat_family=family,
        label=normalize_mod_text(cleaned),
        source=source,
        source_text=cleaned,
        raw_value=float(tier.value) if tier else 0.0,
        trade_stat_ids=(),
        tier_min=tier.low if tier else None,
        tier_max=tier.high if tier else None,
        roll_percentile=round(tier.percentile, 4) if tier else None,
        direction=direction_for(family, cleaned),
        range_policy=SearchRangePolicy.DEGRADED_NO_TIER,
        market_role=MarketRole.INFORMATIONAL,
    )


def _sum_families(features: Iterable[ComparableFeature], families: Iterable[str]) -> tuple[float, int]:
    """Total and contributor count. ``all_*`` mods count triple, as one mod."""
    wanted = set(families)
    total = 0.0
    contributors = 0
    for row in features:
        if row.family not in wanted:
            continue
        contributors += 1
        if row.family in {"all_elemental_resistances", "all_attributes"}:
            total += 3.0 * float(row.value)
        else:
            total += float(row.value)
    return total, contributors


def _build_mod(
    family: str,
    value: float,
    *,
    source: ModSource,
    source_text: str,
    tier: TierRange | None,
) -> MarketMod | None:
    record = get_family(family)
    if record is None:
        return None
    # The parser names a family from the mod's wording, which can be an alias of the
    # registry's own name ("level_of_all_spell_skills" for "all_spell_skills"). Class
    # profiles and redundancy groups are keyed on the canonical name, so resolve it here
    # rather than leaving two spellings of one concept loose in the system.
    family = record.family
    ids = trade_stat_ids(family)
    return MarketMod(
        mod_id=_mod_id(family, source),
        stat_family=family,
        label=record.label,
        source=source,
        source_text=source_text,
        raw_value=float(value),
        trade_stat_ids=ids,
        pseudo_id=ids[0] if record.driver_kind is DriverKind.PSEUDO and ids else None,
        equipment_key=record.equipment_key,
        driver_kind=record.driver_kind,
        tier_min=tier.low if tier else None,
        tier_max=tier.high if tier else None,
        roll_percentile=round(tier.percentile, 4) if tier else None,
        direction=direction_for(family, source_text),
        range_policy=range_policy_for(family, source=source, tier=tier),
        synergy_tags=synergy_tags_for(family),
        redundancy_group=redundancy_group_for(family),
        component_families=record.component_families,
    )


@dataclass(frozen=True)
class ExtractedMods:
    """Everything the item says, parsed. No ranking, no selection, no cap."""

    mods: tuple[MarketMod, ...]
    unparsed_mod_texts: tuple[str, ...]
    features: tuple[ComparableFeature, ...] = field(default=())

    def by_family(self, family: str) -> tuple[MarketMod, ...]:
        return tuple(row for row in self.mods if row.stat_family == family)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mods": [row.to_dict() for row in self.mods],
            "unparsed_mod_texts": list(self.unparsed_mod_texts),
        }


def extract_market_mods(item_raw: str, *, category: str | None = None) -> ExtractedMods:
    """Parse every economic characteristic of an item.

    Explicit and implicit mod lines, derived item properties and trade pseudos all
    become :class:`MarketMod` instances. Tier bounds are attached wherever the client
    printed them. Nothing is ranked or dropped here — that is deliberate, and is what
    lets an item express any number of relevant characteristics.
    """
    features = build_features(item_raw, category=category)
    tagged = tagged_mod_lines(item_raw)
    mods: list[MarketMod] = []
    seen: set[str] = set()
    unparsed: list[str] = []

    for line, _legacy_kind in tagged:
        cleaned = strip_mod_markup(line)
        source = _source_for_line(line, implicit=_legacy_kind.value == "IMPLICIT")
        feature = parse_feature_from_mod(line, category=category)
        mod = None
        if feature is not None:
            tier = tier_range_for_value(line, feature.value) or parse_tier_range(line)
            mod = _build_mod(
                feature.family,
                feature.value,
                source=source,
                source_text=cleaned,
                tier=tier,
            )
        if mod is None:
            unparsed.append(cleaned)
            mod = _build_unmapped_mod(line, source=source)
        if mod.mod_id in seen:
            continue
        seen.add(mod.mod_id)
        mods.append(mod)

    for family, value in parse_equipment_properties(item_raw).items():
        mod = _build_mod(
            family,
            value,
            source=ModSource.PROPERTY,
            source_text=f"{get_family(family).label if get_family(family) else family} {value:g}",
            tier=None,
        )
        if mod is None or mod.mod_id in seen:
            continue
        seen.add(mod.mod_id)
        mods.append(mod)

    for mod in _pseudo_mods(features):
        if mod.mod_id in seen:
            continue
        seen.add(mod.mod_id)
        mods.append(mod)

    parsed_texts = {normalize_mod_text(row.source_text) for row in features}
    for line, _kind in tagged:
        cleaned = strip_mod_markup(line)
        if normalize_mod_text(cleaned) not in parsed_texts and cleaned not in unparsed:
            unparsed.append(cleaned)

    return ExtractedMods(
        mods=tuple(mods),
        unparsed_mod_texts=tuple(dict.fromkeys(unparsed)),
        features=tuple(features),
    )


def _pseudo_mods(features: Iterable[ComparableFeature]) -> list[MarketMod]:
    """Trade totals the item does not print as a single line.

    A pseudo is only created when the item actually has contributing mods, and a
    resistance/attribute total needs at least two contributors — a single resistance
    roll is better represented by its own stat than by a total of one.
    """
    rows = tuple(features)
    made: list[MarketMod] = []

    def add(family: str, total: float, components: tuple[str, ...]) -> None:
        if total <= 0:
            return
        mod = _build_mod(
            family,
            total,
            source=ModSource.PSEUDO,
            source_text=f"{family.replace('_', ' ')} from {', '.join(components)}",
            tier=None,
        )
        if mod is not None:
            made.append(mod)

    ele_components = ("fire_resistance", "cold_resistance", "lightning_resistance")
    ele_families = ele_components + ("all_elemental_resistances",)
    ele_total, ele_contributors = _sum_families(rows, ele_families)
    chaos_total, chaos_contributors = _sum_families(rows, ("chaos_resistance",))
    attr_total, attr_contributors = _sum_families(
        rows, ("strength", "dexterity", "intelligence", "all_attributes")
    )
    life_total, life_contributors = _sum_families(rows, ("maximum_life",))
    mana_total, mana_contributors = _sum_families(rows, ("maximum_mana",))
    es_total, es_contributors = _sum_families(rows, ("maximum_energy_shield", "energy_shield"))

    if ele_contributors >= 2:
        add("total_elemental_resistance", ele_total, ele_components)
    # "Total resistance" needs a real elemental package underneath it. One elemental
    # roll beside one chaos roll is two separate suffixes, and folding them into a
    # total both misreads the market and lets chaos be counted twice — once inside the
    # total and once as its own filter, since chaos is not in the elemental redundancy
    # group.
    if chaos_contributors and ele_contributors >= 2:
        add("total_resistance", ele_total + chaos_total, ("elemental", "chaos_resistance"))
    if attr_contributors >= 2:
        add("total_attributes", attr_total, ("strength", "dexterity", "intelligence"))
    # A total over one contributor is that contributor, printed twice. It was the main
    # source of the duplicate primary rows MARKET-03 exists to remove, so totals need
    # at least two sources before they are worth a row of their own.
    if life_contributors >= 2:
        add("total_life", life_total, ("maximum_life",))
    if mana_contributors >= 2:
        add("total_mana", mana_total, ("maximum_mana",))
    if es_contributors >= 2:
        add("total_energy_shield", es_total, ("maximum_energy_shield",))
    return made
