"""MARKET-03 — ``MarketSearchPlan``, ``TradeQueryCompiler`` and coverage reporting.

The plan is the item's economic identity expressed as a search:

* **base constraints**, from a :class:`~exilelens.price_check.base_value.BaseValueProfile`;
* **anchor mods** — hard requirements;
* **flexible groups** — substitutable sets, one ``count`` group each;
* **optional mods** — visible in the panel, deliberately not in the query;
* **informational and dead mods** — carried so the panel can show everything.

Two invariants govern this module, and they pull in opposite directions:

**Economic intent is preserved.** Every characteristic keeps the role the desirability
engine gave it, whatever the Trade2 grammar can do with it. A mod that cannot be
searched is never quietly relabelled OPTIONAL or DEAD, and a substitutable set that
Trade2 cannot express as an OR stays a substitutable set in the plan.

**Trade compilability is separate.** The compiler returns a
:class:`CompiledTradeQuery` — a body *and* a :class:`CompilationCoverageReport` saying
what the body could not express. A query that quietly covers less than the plan claims
is how a price estimate becomes confidently wrong, so the gap is reported rather than
absorbed. ``ANCHOR`` + ``UNSEARCHABLE`` is a serious hole; ``INFORMATIONAL`` +
``UNSEARCHABLE`` is usually harmless. Downstream trust and explanation read the report.

Weighted groups (``weight`` / ``weight2``) are valid Trade2 syntax and are deliberately
unused: a weighted score cannot be explained to a user in one line.

Offline only. Compilation ends in the existing local validator, so a malformed body
fails here rather than spending a request on an HTTP 400.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from exilelens.price_check.base_value import (
    BaseValueProfile,
    CraftingMode,
    build_base_profile,
)
from exilelens.price_check.desirability import DesirabilityResult, classify_with_base
from exilelens.price_check.market_drivers import canonical_search_min
from exilelens.price_check.market_mod import (
    Direction,
    MarketMod,
    MarketRole,
    ModSource,
    SearchRangePolicy,
)
from exilelens.price_check.market_profiles import BaseRelevance, ItemClassKey
from exilelens.price_check.stat_registry import DriverKind
from exilelens.price_check.trade2_query_validation import validate_trade2_search_body

_RARITY_OPTIONS = {"RARE": "rare", "MAGIC": "magic", "NORMAL": "normal", "UNIQUE": "unique"}


class PlanCompilationError(ValueError):
    """The plan cannot become a valid Trade2 body. Raised locally, never sent."""


class Coverage(str, Enum):
    """How a characteristic reaches — or fails to reach — the market query."""

    #: Emitted as its own stat filter.
    SEARCHABLE = "SEARCHABLE"
    #: The economic concept reaches the query as a pseudo total.
    REPRESENTED_BY_PSEUDO = "REPRESENTED_BY_PSEUDO"
    #: The economic concept reaches the query as a final item property.
    REPRESENTED_BY_PROPERTY = "REPRESENTED_BY_PROPERTY"
    #: Intrinsic to a base constraint the query already carries. An implicit granted by
    #: an exact base needs no stat filter of its own: asking for the base has asked for
    #: it. Distinct from the pseudo and property cases, which represent a concept through
    #: another *stat*, not through the base identity.
    REPRESENTED_BY_BASE = "REPRESENTED_BY_BASE"
    #: No trade stat exists for it. The market cannot be asked about this at all.
    UNSEARCHABLE = "UNSEARCHABLE"
    #: Real and searchable, but the group semantics it belongs to cannot be expressed —
    #: Trade2 has no way to say "this stat OR this item property".
    UNREPRESENTABLE_GROUP_SEMANTICS = "UNREPRESENTABLE_GROUP_SEMANTICS"


#: Coverage values that mean "the query asks about this concept by another route".
_REPRESENTED_ELSEWHERE = frozenset(
    {
        Coverage.REPRESENTED_BY_PSEUDO,
        Coverage.REPRESENTED_BY_PROPERTY,
        Coverage.REPRESENTED_BY_BASE,
    }
)


class CoverageSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"


#: Roles whose omission actually costs the estimate something.
_MATERIAL_ROLES = frozenset({MarketRole.ANCHOR, MarketRole.FLEXIBLE})


@dataclass(frozen=True)
class BaseConstraints:
    """What the query says about the item itself, before any stat filter."""

    base_role: BaseRelevance
    base_type: str | None = None
    trade_category: str | None = None
    rarity: str | None = None
    item_level: int | None = None
    corrupted: bool | None = None
    quality: int | None = None
    base_family: str | None = None
    degraded_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_role": self.base_role.value,
            "base_type": self.base_type or "",
            "trade_category": self.trade_category or "",
            "base_family": self.base_family or "",
            "rarity": self.rarity or "",
            "item_level": self.item_level,
            "corrupted": self.corrupted,
            "quality": self.quality,
            "degraded_reason": self.degraded_reason,
        }


@dataclass(frozen=True)
class PlannedCharacteristic:
    """One characteristic of the item, with its economic role and its query coverage.

    Every parsed characteristic gets one of these, including the ones that will never
    reach a query. That is the point: the plan is the economic statement, and the
    coverage fields record where the statement and the query diverge.
    """

    mod: MarketMod
    economic_role: MarketRole
    coverage: Coverage
    original_plan_group: str
    minimum: float | None = None
    maximum: float | None = None
    policy: SearchRangePolicy = SearchRangePolicy.DEGRADED_NO_TIER
    reason: str = ""
    omitted_from_query: bool = False
    omission_reason: str = ""
    #: True when a FLEXIBLE mod had no substitutable partner on this item and became a
    #: hard filter anyway. Broadening relaxes these before it touches a real anchor.
    promoted_from_flexible: bool = False
    enabled: bool = True

    @property
    def family(self) -> str:
        return self.mod.stat_family

    @property
    def is_material(self) -> bool:
        return self.economic_role in _MATERIAL_ROLES

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "label": self.mod.label,
            "actual_value": self.mod.raw_value,
            "economic_role": self.economic_role.value,
            "coverage": self.coverage.value,
            "original_plan_group": self.original_plan_group,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "policy": self.policy.value,
            "reason": self.reason,
            "omitted_from_query": self.omitted_from_query,
            "omission_reason": self.omission_reason,
            "promoted_from_flexible": self.promoted_from_flexible,
            "enabled": self.enabled,
        }


#: Historical name kept so callers reading a filter row need not care about the rename.
PlannedFilter = PlannedCharacteristic


@dataclass(frozen=True)
class FlexibleGroup:
    """A set of substitutable characteristics, and how many of them are required."""

    tag: str
    filters: tuple[PlannedCharacteristic, ...]
    count_min: int

    @property
    def is_heterogeneous(self) -> bool:
        """True when the group mixes stat filters with item properties.

        Trade2 cannot express a choice across those, so such a group is where economic
        intent and query capability part company.
        """
        kinds = {row.mod.driver_kind is DriverKind.EQUIPMENT_FILTER for row in self.filters}
        return len(kinds) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "count_min": self.count_min,
            "heterogeneous": self.is_heterogeneous,
            "filters": [row.to_dict() for row in self.filters],
        }


@dataclass(frozen=True)
class MarketSearchPlan:
    """The logical search. Complete, whatever the Trade2 grammar can express of it."""

    item_class: ItemClassKey
    base: BaseConstraints
    base_profile: BaseValueProfile | None = None
    #: Every parsed characteristic, whatever its role.
    characteristics: tuple[PlannedCharacteristic, ...] = ()
    anchors: tuple[PlannedCharacteristic, ...] = ()
    flexible_groups: tuple[FlexibleGroup, ...] = ()
    optional: tuple[PlannedCharacteristic, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def promoted(self) -> tuple[PlannedCharacteristic, ...]:
        return tuple(row for row in self.anchors if row.promoted_from_flexible)

    @property
    def true_anchors(self) -> tuple[PlannedCharacteristic, ...]:
        return tuple(row for row in self.anchors if not row.promoted_from_flexible)

    @property
    def emitted_filters(self) -> tuple[PlannedCharacteristic, ...]:
        rows = list(self.anchors)
        for group in self.flexible_groups:
            rows.extend(group.filters)
        return tuple(rows)

    def with_role(self, role: MarketRole) -> tuple[PlannedCharacteristic, ...]:
        return tuple(row for row in self.characteristics if row.economic_role is role)

    @property
    def informational(self) -> tuple[MarketMod, ...]:
        return tuple(row.mod for row in self.with_role(MarketRole.INFORMATIONAL))

    @property
    def dead(self) -> tuple[MarketMod, ...]:
        return tuple(row.mod for row in self.with_role(MarketRole.DEAD))

    @property
    def unsearchable(self) -> tuple[MarketMod, ...]:
        return tuple(
            row.mod for row in self.characteristics if row.coverage is Coverage.UNSEARCHABLE
        )

    def summary(self) -> str:
        parts: list[str] = []
        if self.anchors:
            parts.append(" + ".join(row.mod.label for row in self.anchors))
        for group in self.flexible_groups:
            names = " / ".join(row.mod.label for row in group.filters)
            parts.append(f"{group.count_min} of ({names})")
        base = self.base.base_type or self.base.trade_category or ""
        joined = ", ".join(parts)
        return f"{base}, {joined}" if base and joined else base or joined or "base only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_class": self.item_class.value,
            "base": self.base.to_dict(),
            "base_profile": self.base_profile.to_dict() if self.base_profile else None,
            "characteristics": [row.to_dict() for row in self.characteristics],
            "anchors": [row.to_dict() for row in self.anchors],
            "flexible_groups": [row.to_dict() for row in self.flexible_groups],
            "optional": [row.to_dict() for row in self.optional],
            "summary": self.summary(),
            "notes": list(self.notes),
        }


# --- coverage reporting -------------------------------------------------------


@dataclass(frozen=True)
class CoverageEntry:
    family: str
    label: str
    economic_role: MarketRole
    coverage: Coverage
    original_plan_group: str
    omitted_from_query: bool
    omission_reason: str = ""

    @property
    def is_hole(self) -> bool:
        """Omitted *and* not covered by some other representation.

        A component folded into a pseudo, a local affix behind a final property and an
        implicit guaranteed by an exact base are all absent from the query on purpose,
        because the query already asks for the concept another way. Counting those as
        holes would make every well-formed query look lossy.
        """
        if not self.omitted_from_query or self.economic_role not in _MATERIAL_ROLES:
            return False
        return self.coverage not in _REPRESENTED_ELSEWHERE

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "label": self.label,
            "economic_role": self.economic_role.value,
            "coverage": self.coverage.value,
            "original_plan_group": self.original_plan_group,
            "omitted_from_query": self.omitted_from_query,
            "omission_reason": self.omission_reason,
        }


@dataclass(frozen=True)
class CompilationCoverageReport:
    """What the compiled query does *not* say about the item.

    Severity is deliberately blunt: an omitted ANCHOR means the query is not asking
    about something that defines the item, and no amount of comparables will fix that.
    """

    entries: tuple[CoverageEntry, ...]
    base_notes: tuple[str, ...] = ()

    @property
    def holes(self) -> tuple[CoverageEntry, ...]:
        return tuple(row for row in self.entries if row.is_hole)

    @property
    def anchor_holes(self) -> tuple[CoverageEntry, ...]:
        return tuple(row for row in self.holes if row.economic_role is MarketRole.ANCHOR)

    @property
    def severity(self) -> CoverageSeverity:
        if self.anchor_holes:
            return CoverageSeverity.SERIOUS
        if self.holes:
            return CoverageSeverity.MINOR
        return CoverageSeverity.NONE

    @property
    def fully_covered(self) -> bool:
        return self.severity is CoverageSeverity.NONE

    @property
    def unsearchable(self) -> tuple[CoverageEntry, ...]:
        """Characteristics no trade stat can express, whatever their role.

        Kept separate from holes: a hole is something the query *could* have asked and
        did not, while these cannot be asked at all. Both matter to the reader, for
        different reasons.
        """
        return tuple(
            row
            for row in self.entries
            if row.coverage is Coverage.UNSEARCHABLE and row.economic_role is not MarketRole.DEAD
        )

    def explain(self) -> tuple[str, ...]:
        """Plain sentences for the panel. No enum names, no internal vocabulary."""
        lines: list[str] = []
        for row in self.anchor_holes:
            lines.append(f"Not included in the search: {row.label}. {row.omission_reason}")
        for row in self.holes:
            if row in self.anchor_holes:
                continue
            lines.append(f"{row.label} could not be included: {row.omission_reason}")
        for row in self.unsearchable:
            lines.append(f"{row.label} cannot be searched on trade, so the estimate ignores it")
        return tuple(lines) + self.base_notes

    def trust_evidence(self) -> dict[str, Any]:
        """The fields the trust layer needs, without it importing the planner."""
        return {
            "coverage_severity": self.severity.value,
            "omitted_anchor_labels": tuple(row.label for row in self.anchor_holes),
            "omitted_flexible_labels": tuple(
                row.label for row in self.holes if row not in self.anchor_holes
            ),
            "unsearchable_labels": tuple(row.label for row in self.unsearchable),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "fully_covered": self.fully_covered,
            "entries": [row.to_dict() for row in self.entries],
            "holes": [row.to_dict() for row in self.holes],
            "base_notes": list(self.base_notes),
            "unsearchable": [row.to_dict() for row in self.unsearchable],
            "explain": list(self.explain()),
        }


@dataclass(frozen=True, init=False)
class CompiledTradeQuery:
    """Immutable wire body and its coverage; callers receive a fresh JSON copy."""

    _body_json: str
    coverage: CompilationCoverageReport
    summary: str = ""

    def __init__(self, body: dict[str, Any], coverage: CompilationCoverageReport, summary: str = ""):
        import json
        object.__setattr__(self, "_body_json", json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False))
        object.__setattr__(self, "coverage", coverage)
        object.__setattr__(self, "summary", summary)

    @property
    def body(self) -> dict[str, Any]:
        import json
        return json.loads(self._body_json)

    @property
    def query_fingerprint(self) -> str:
        import hashlib
        return hashlib.sha256(self._body_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {"body": self.body, "coverage": self.coverage.to_dict(), "summary": self.summary,
                "query_fingerprint": self.query_fingerprint}


# --- range policy -------------------------------------------------------------


def resolve_range(mod: MarketMod) -> tuple[float | None, float | None, str]:
    """Turn one mod's roll into a search bound, per its own policy.

    Returns ``(minimum, maximum, reason)``. The reason is written for a person: it says
    *why* the bound is what it is, in the game's own terms, and never names an internal
    policy. A filter the product cannot explain is a filter the user cannot correct.

    This decides how close a comparable has to be. It does **not** decide whether the
    characteristic belongs in the query at all — that is the role, and a loose floor must
    never be used to soften a role that was wrong.
    """
    value = float(mod.raw_value)

    if mod.direction is Direction.BOOLEAN:
        return None, None, "matched on presence, not on a number"
    if mod.direction is Direction.EXACT or mod.range_policy is SearchRangePolicy.EXACT:
        return value, value, "matched exactly"
    if mod.direction is Direction.LOWER_BETTER:
        # Semantic, not numeric: the market wants this number no higher than the item's.
        return None, value, f"lower is better here, so capped at {_fmt(value)}"

    if value < 0:
        # A beneficial family printing a negative number is a penalty on this item.
        # Relaxing downwards would accept items with an even worse roll, so it is held.
        return value, None, "a negative roll, held at the item's own value"

    policy = mod.range_policy
    if policy is SearchRangePolicy.ROLL_SENSITIVE:
        # Declared but uncalibrated. Fall back rather than invent a curve, and say so.
        policy = (
            SearchRangePolicy.TIER_FLOOR if mod.has_tier_data else SearchRangePolicy.DEGRADED_NO_TIER
        )

    if policy is SearchRangePolicy.TIER_FLOOR and mod.tier_min is not None:
        floor = float(mod.tier_min)
        return floor, None, f"same affix tier ({_fmt(floor)}-{_fmt(float(mod.tier_max))})"

    if policy is SearchRangePolicy.BREAKPOINT:
        if mod.tier_min is not None:
            floor = float(mod.tier_min)
            return floor, None, f"this stat moves in steps — same step ({_fmt(floor)}+)"
        return value, None, "this stat moves in steps, and the game did not show its range"

    if policy is SearchRangePolicy.PSEUDO_AGGREGATE:
        haircut = 5.0 if value >= 20 else 2.0
        floor = max(1.0, round(value - haircut, 1))
        return floor, None, f"a combined total, relaxed from {_fmt(value)}"

    if policy is SearchRangePolicy.PROPERTY:
        # A final property is base plus affixes plus quality; it has no affix tier to
        # preserve, so it is relaxed as a total.
        floor, _label = canonical_search_min(mod.stat_family, value)
        return float(floor), None, f"the item's final total, relaxed from {_fmt(value)}"

    floor, _label = canonical_search_min(mod.stat_family, value)
    return float(floor), None, f"the game did not show this roll's range — relaxed from {_fmt(value)}"


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


# --- plan construction --------------------------------------------------------


def _flexible_count_min(size: int) -> int:
    """How many of a substitutable set a buyer should have to match.

    Half the set, rounded down, never below one. The brief's own boots example — "at
    least 1 of: total res, energy shield, attribute" — is the three-member case. This is
    provisional and calibratable; it is not a driver cap, because nothing is removed
    from the group.
    """
    return max(1, size // 2)


def _representatives(result: DesirabilityResult) -> dict[str, MarketMod]:
    """The mod that carries each economic concept into the query."""
    best: dict[str, MarketMod] = {}
    for mod in result.mods:
        group = mod.redundancy_group
        if not group:
            continue
        current = best.get(group)
        if current is None or mod.desirability_score > current.desirability_score:
            best[group] = mod
    return best


def _is_base_represented(mod: MarketMod, base_role: BaseRelevance) -> bool:
    """Does a base constraint the query already carries guarantee this characteristic?

    Two cases. An implicit is granted by the base itself, so pinning the exact base asks
    for it. And a defence property the base produces unaided is likewise guaranteed —
    defence semantics decides that one, because a locally enhanced property is *not*
    represented by its base.
    """
    if mod.base_represented:
        return True
    return mod.source is ModSource.IMPLICIT and base_role is BaseRelevance.EXACT


def _coverage_for(
    mod: MarketMod,
    representatives: Mapping[str, MarketMod],
    base_role: BaseRelevance = BaseRelevance.CATEGORY,
) -> Coverage:
    if not mod.is_queryable:
        return Coverage.UNSEARCHABLE
    if _is_base_represented(mod, base_role):
        return Coverage.REPRESENTED_BY_BASE
    representative = representatives.get(mod.redundancy_group or "")
    if representative is not None:
        if representative.source is ModSource.PSEUDO:
            return Coverage.REPRESENTED_BY_PSEUDO
        if representative.driver_kind is DriverKind.EQUIPMENT_FILTER:
            return Coverage.REPRESENTED_BY_PROPERTY
    return Coverage.SEARCHABLE


def _characteristic(
    mod: MarketMod,
    *,
    representatives: Mapping[str, MarketMod],
    group: str,
    base_role: BaseRelevance = BaseRelevance.CATEGORY,
    promoted: bool = False,
    omitted: bool = False,
    omission_reason: str = "",
) -> PlannedCharacteristic:
    minimum, maximum, reason = resolve_range(mod)
    return PlannedCharacteristic(
        mod=mod,
        economic_role=mod.market_role,
        coverage=_coverage_for(mod, representatives, base_role),
        original_plan_group=group,
        minimum=minimum,
        maximum=maximum,
        policy=mod.range_policy,
        reason=reason,
        omitted_from_query=omitted,
        omission_reason=omission_reason,
        promoted_from_flexible=promoted,
    )


def _base_constraints(profile: BaseValueProfile) -> BaseConstraints:
    """Turn a base profile into the constraints the query is allowed to carry."""
    role = profile.base_role
    degraded = ""
    if role is BaseRelevance.CATEGORY and not profile.trade_category:
        role = BaseRelevance.EXACT
        degraded = "no single trade category covers this class; using the exact base"
    elif role is BaseRelevance.FAMILY and not profile.trade_category:
        role = BaseRelevance.EXACT
        degraded = "no single trade category covers this class; using the exact base"
    elif role is BaseRelevance.FAMILY:
        # Trade2 has no base-family filter. The family is stated in the plan and lost
        # in the query, which the coverage report records rather than absorbs.
        degraded = (
            f"trade has no base-family filter, so '{profile.base_family}' compiles as "
            f"the broader category '{profile.trade_category}'"
        )
    return BaseConstraints(
        base_role=role,
        base_type=profile.exact_base,
        trade_category=profile.trade_category,
        base_family=profile.base_family,
        rarity=profile.rarity,
        item_level=profile.item_level_min,
        corrupted=profile.require_corrupted,
        quality=profile.quality_min,
        degraded_reason=degraded,
    )


def build_plan(
    result: DesirabilityResult,
    base_profile: BaseValueProfile,
) -> MarketSearchPlan:
    """Turn a classified item and its base profile into a search plan.

    Every anchor becomes a hard filter. Flexible mods are grouped by the clusters the
    desirability engine found; a flexible mod in no cluster is a requirement on its own,
    because there is nothing for a buyer to substitute it against. Nothing is dropped
    for being the fourth or fifth relevant characteristic, and nothing loses its role
    for being hard to compile.
    """
    representatives = _representatives(result)
    base = _base_constraints(base_profile)
    base_role = base.base_role
    notes: list[str] = []
    characteristics: list[PlannedCharacteristic] = []
    assigned: dict[str, PlannedCharacteristic] = {}

    def remember(row: PlannedCharacteristic) -> PlannedCharacteristic:
        characteristics.append(row)
        assigned[row.mod.mod_id] = row
        return row

    def emittable(mod: MarketMod) -> bool:
        """A mod the query can usefully ask about on its own.

        A base-guaranteed implicit is excluded here rather than filtered later: asking
        for the exact base has already asked for it, and emitting a second filter would
        narrow the search to items carrying the value twice.
        """
        return mod.is_queryable and not _is_base_represented(mod, base_role)

    def characteristic(mod: MarketMod, group: str, **kwargs) -> PlannedCharacteristic:
        return _characteristic(
            mod, representatives=representatives, group=group, base_role=base_role, **kwargs
        )

    anchors = tuple(
        remember(characteristic(mod, "anchor")) for mod in result.anchors if emittable(mod)
    )

    clustered: set[str] = set()
    groups: list[FlexibleGroup] = []
    by_family = {mod.stat_family: mod for mod in result.mods}
    for tag, families in result.synergy_clusters:
        # Decide whether the group survives *before* recording its members. A cluster
        # can lose a member to base representation and drop below two, and a member
        # recorded for a group that never forms would then be recorded a second time as
        # a lone flexible mod.
        candidates = tuple(
            by_family[family]
            for family in families
            if family in by_family and emittable(by_family[family])
        )
        if len(candidates) < 2:
            continue
        members = tuple(remember(characteristic(mod, f"flexible:{tag}")) for mod in candidates)
        groups.append(
            FlexibleGroup(tag=tag, filters=members, count_min=_flexible_count_min(len(members)))
        )
        clustered.update(row.family for row in members)

    lone = tuple(
        remember(characteristic(mod, "anchor:promoted", promoted=True))
        for mod in result.flexible
        if emittable(mod) and mod.stat_family not in clustered
    )
    if lone:
        anchors = anchors + lone
        notes.append(
            "required "
            + ", ".join(row.mod.label for row in lone)
            + " despite being substitutable: nothing on this item stands in for it. "
            "These relax first if the search comes back thin"
        )

    optional = tuple(
        remember(
            characteristic(
                mod,
                "optional",
                omitted=True,
                omission_reason="held out of the query on purpose; one click away in the panel",
            )
        )
        for mod in result.optional
        if emittable(mod)
    )

    # Everything else still gets a characteristic. A mod with no row is indistinguishable
    # from a mod that was lost.
    for mod in result.mods:
        if mod.mod_id in assigned:
            continue
        coverage = _coverage_for(mod, representatives, base_role)
        if coverage is Coverage.UNSEARCHABLE:
            reason = "no trade stat maps to this modifier"
        elif coverage is Coverage.REPRESENTED_BY_PSEUDO:
            reason = "covered by the pseudo total for this concept"
        elif coverage is Coverage.REPRESENTED_BY_PROPERTY:
            reason = "covered by the final item property for this concept"
        elif coverage is Coverage.REPRESENTED_BY_BASE:
            reason = "guaranteed by the exact base the query already asks for"
        else:
            reason = "not an economic driver for this item"
        remember(
            characteristic(
                mod,
                mod.market_role.value.lower(),
                omitted=True,
                omission_reason=reason,
            )
        )

    plan = MarketSearchPlan(
        item_class=result.item_class,
        base=base,
        base_profile=base_profile,
        characteristics=tuple(characteristics),
        anchors=anchors,
        flexible_groups=tuple(groups),
        optional=optional,
        notes=tuple(notes),
    )

    unsearchable_material = [
        row for row in plan.characteristics if row.coverage is Coverage.UNSEARCHABLE and row.is_material
    ]
    if unsearchable_material:
        notes.append(
            f"{len(unsearchable_material)} priced modifier(s) cannot be searched on trade: "
            + ", ".join(row.mod.label or row.mod.source_text for row in unsearchable_material)
        )
        plan = replace(plan, notes=tuple(notes))
    return plan


def plan_for_item(
    item_raw: str,
    *,
    category: str | None = None,
    base_type: str | None = None,
    rarity: str | None = None,
    item_level: int | None = None,
    quality: int | None = None,
    corrupted: bool | None = None,
) -> MarketSearchPlan:
    result, profile = classify_with_base(
        item_raw,
        category=category,
        base_type=base_type,
        rarity=rarity,
        item_level=item_level,
        quality=quality,
        corrupted=corrupted,
    )
    return build_plan(result, profile)


# --- compilation --------------------------------------------------------------


def _value_block(row: PlannedCharacteristic) -> dict[str, float]:
    block: dict[str, float] = {}
    if row.minimum is not None:
        block["min"] = row.minimum
    if row.maximum is not None:
        block["max"] = row.maximum
    return block


def _stat_filters(row: PlannedCharacteristic) -> list[dict[str, Any]]:
    value = _value_block(row)
    return [
        {"id": stat_id, "value": dict(value), "disabled": False}
        for stat_id in row.mod.trade_stat_ids
    ]


def _assert_no_redundant_pair(rows: Sequence[PlannedCharacteristic]) -> None:
    """No two emitted filters may describe the same economic concept.

    This is the invariant that stops a pseudo total and one of its components both
    constraining the same query, which silently narrows the search to items that happen
    to carry the value twice.
    """
    seen: dict[str, str] = {}
    for row in rows:
        group = row.mod.redundancy_group
        if not group:
            continue
        if group in seen:
            raise PlanCompilationError(
                f"redundancy group {group!r} would be filtered twice: {seen[group]} and {row.family}"
            )
        seen[group] = row.family


class TradeQueryCompiler:
    """``MarketSearchPlan`` -> a validated body plus a coverage report."""

    def compile(self, plan: MarketSearchPlan) -> CompiledTradeQuery:
        logical_plan = plan
        plan = replace(plan, anchors=tuple(row for row in plan.anchors if row.enabled),
                       flexible_groups=tuple(replace(group, filters=tuple(row for row in group.filters if row.enabled),
                                                     count_min=min(group.count_min, sum(row.enabled for row in group.filters)))
                                             for group in plan.flexible_groups if any(row.enabled for row in group.filters)))
        _assert_no_redundant_pair(plan.emitted_filters)

        emitted: set[str] = set()
        omissions: dict[str, tuple[Coverage, str]] = {}

        query: dict[str, Any] = {"status": {"option": "available"}}
        filters: dict[str, Any] = {}
        type_filters: dict[str, Any] = {}
        base = plan.base

        if base.base_role in {BaseRelevance.EXACT, BaseRelevance.FAMILY} and base.base_role is BaseRelevance.EXACT:
            if base.base_type:
                query["type"] = base.base_type
            elif base.trade_category:
                type_filters["category"] = {"option": base.trade_category}
        elif base.base_role in {BaseRelevance.CATEGORY, BaseRelevance.FAMILY} and base.trade_category:
            type_filters["category"] = {"option": base.trade_category}

        rarity = _RARITY_OPTIONS.get(str(base.rarity or "").upper())
        if rarity:
            type_filters["rarity"] = {"option": rarity}
        if type_filters:
            filters["type_filters"] = {"filters": type_filters}

        misc: dict[str, Any] = {}
        if base.item_level is not None:
            misc["ilvl"] = {"min": int(base.item_level)}
        if base.corrupted is not None:
            misc["corrupted"] = {"option": "true" if base.corrupted else "false"}
        if base.quality is not None:
            misc["quality"] = {"min": int(base.quality)}
        if misc:
            filters["misc_filters"] = {"filters": misc}

        equipment = self._equipment_filters(plan, emitted)
        if equipment:
            filters["equipment_filters"] = {"filters": equipment}
        if filters:
            query["filters"] = filters

        stats = self._stat_groups(plan, emitted, omissions)
        if stats:
            query["stats"] = stats
        elif "type" not in query and not equipment:
            # A category with no stat filter at all is "every rare pair of boots" — not
            # a price check. With nothing to constrain, the base is the only signal
            # left, so pin it rather than send a search that means nothing.
            if base.base_type:
                query["type"] = base.base_type
            else:
                raise PlanCompilationError("plan has no stat filters and no base type to search on")

        body = {"query": query, "sort": {"price": "asc"}}
        validation = validate_trade2_search_body(body)
        if not validation.ok or validation.body != body:
            raise PlanCompilationError(validation.fatal or "compiled body needs repair; coverage would change")

        return CompiledTradeQuery(
            body=validation.body,
            coverage=self._coverage_report(logical_plan, emitted, omissions),
            summary=plan.summary(),
        )

    # -- internals ---------------------------------------------------------------

    def _equipment_filters(self, plan: MarketSearchPlan, emitted: set[str]) -> dict[str, Any]:
        """Item properties go in ``equipment_filters``, never in a stat group.

        Anchors only. An equipment filter is unconditional, so emitting one for a
        *flexible* member would turn a characteristic the buyer could substitute into a
        requirement — the opposite of what the plan says.
        """
        out: dict[str, Any] = {}
        for row in plan.anchors:
            if row.mod.driver_kind is not DriverKind.EQUIPMENT_FILTER or not row.mod.equipment_key:
                continue
            block = _value_block(row)
            if block:
                out[row.mod.equipment_key] = block
                emitted.add(row.mod.mod_id)
        return out

    def _stat_groups(
        self,
        plan: MarketSearchPlan,
        emitted: set[str],
        omissions: dict[str, tuple[Coverage, str]],
    ) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        hard: list[dict[str, Any]] = []

        for row in plan.anchors:
            if row.mod.driver_kind is DriverKind.EQUIPMENT_FILTER:
                continue
            variants = _stat_filters(row)
            if not variants:
                continue
            if len(variants) == 1:
                hard.append(variants[0])
            else:
                # Alias-OR: the same economic stat under several catalog prefixes.
                # Trade2 has no `or` group, so this is a COUNT of one.
                groups.append({"type": "count", "value": {"min": 1}, "filters": variants})
            emitted.add(row.mod.mod_id)
        if hard:
            groups.insert(0, {"type": "and", "filters": hard})

        for group in plan.flexible_groups:
            variants: list[dict[str, Any]] = []
            carried: list[PlannedCharacteristic] = []
            dropped: list[PlannedCharacteristic] = []
            for row in group.filters:
                if row.mod.driver_kind is DriverKind.EQUIPMENT_FILTER:
                    # Trade2 cannot express "this stat OR this item property": an
                    # equipment filter is always a hard AND. Emitting it would turn a
                    # substitutable member into a requirement and silently narrow the
                    # search, so it is dropped and the remaining members need one fewer
                    # match to stay no stricter than the plan intended.
                    dropped.append(row)
                    continue
                # One id per mod, not every alias prefix: in a group with two or more
                # members, `min: 2` over alias variants could be satisfied by two
                # prefixes of the *same* stat, which is not two characteristics.
                variants.extend(_stat_filters(row)[:1])
                carried.append(row)

            minimum = group.count_min - len(dropped)
            for row in dropped:
                omissions[row.mod.mod_id] = (
                    Coverage.UNREPRESENTABLE_GROUP_SEMANTICS,
                    f"trade cannot express a choice between a stat and an item property, "
                    f"so '{row.mod.label}' was left out of the '{group.tag}' group",
                )
            if not variants or minimum < 1:
                # Nothing left that is looser than a hard requirement. Emitting the
                # remainder would demand every survivor, which is stricter than the
                # plan said, so the whole group stays out of the query.
                for row in carried:
                    omissions[row.mod.mod_id] = (
                        Coverage.UNREPRESENTABLE_GROUP_SEMANTICS,
                        f"the '{group.tag}' group could not be expressed without making "
                        f"'{row.mod.label}' mandatory, which the plan does not ask for",
                    )
                continue
            groups.append(
                {"type": "count", "value": {"min": min(minimum, len(variants))}, "filters": variants}
            )
            for row in carried:
                emitted.add(row.mod.mod_id)

        return groups

    def _coverage_report(
        self,
        plan: MarketSearchPlan,
        emitted: set[str],
        omissions: Mapping[str, tuple[Coverage, str]],
    ) -> CompilationCoverageReport:
        entries: list[CoverageEntry] = []
        for row in plan.characteristics:
            coverage = row.coverage
            omitted = row.mod.mod_id not in emitted
            reason = row.omission_reason
            if row.mod.mod_id in omissions:
                coverage, reason = omissions[row.mod.mod_id]
            elif not omitted:
                reason = ""
            elif not reason:
                reason = "not emitted by the compiled query"
            entries.append(
                CoverageEntry(
                    family=row.family,
                    label=row.mod.label or row.mod.source_text,
                    economic_role=row.economic_role,
                    coverage=coverage,
                    original_plan_group=row.original_plan_group,
                    omitted_from_query=omitted,
                    omission_reason=reason,
                )
            )
        base_notes: list[str] = []
        if plan.base.degraded_reason:
            base_notes.append(plan.base.degraded_reason)
        return CompilationCoverageReport(entries=tuple(entries), base_notes=tuple(base_notes))

    def group_omissions(self, plan: MarketSearchPlan) -> tuple[str, ...]:
        """Flexible groups the Trade2 grammar cannot express, and why."""
        return tuple(
            row.omission_reason
            for row in self.compile(plan).coverage.holes
            if row.coverage is Coverage.UNREPRESENTABLE_GROUP_SEMANTICS
        )


def compile_plan(plan: MarketSearchPlan) -> CompiledTradeQuery:
    return TradeQueryCompiler().compile(plan)
