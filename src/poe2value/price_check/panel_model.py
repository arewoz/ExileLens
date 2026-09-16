"""MARKET-03 — the one canonical view model behind the interactive Price Check panel.

The panel renders this and nothing else. It does not re-derive which stats matter, which
ranges to use, or which base to compare against: that is the search plan's job, and a
second opinion living in the widget layer is how a UI drifts away from the query it
claims to describe.

Three translations happen here, and only here:

**Roles become emphasis, not vocabulary.** A user never reads ANCHOR or FLEXIBLE. They
see a required row, a substitutable group, an unchecked option, or a subdued line under
More Stats.

**Coverage becomes a sentence.** "Included in Energy Shield 135" and "ExileLens cannot
search this yet" are different facts with different consequences, and collapsing either
into a single "ignored" bucket is how a price estimate hides what it did not ask.

**The plan and the compiled query are shown as two things.** Trade2 cannot express "this
stat OR this item property", so the panel states the substitution it understands *and*
that the query could not carry it. Pretending both filters were sent would be a lie about
the number underneath.

Pure and offline: no Qt, no network, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from poe2value.price_check.base_value import BaseValueProfile, CraftingMode
from poe2value.price_check.comparable_features import normalize_mod_text
from poe2value.price_check.market_mod import Direction, MarketMod, MarketRole, ModSource
from poe2value.price_check.market_plan import (
    CompilationCoverageReport,
    CompiledTradeQuery,
    Coverage,
    CoverageSeverity,
    MarketSearchPlan,
    PlannedCharacteristic,
)
from poe2value.price_check.market_profiles import BaseRelevance


class RowEmphasis(str, Enum):
    """How prominent a row is. The user-facing shadow of ``MarketRole``."""

    #: Checked, visually led. The item is not this item without it.
    REQUIRED = "REQUIRED"
    #: Checked, shown as one of a set the buyer would swap between.
    SUBSTITUTABLE = "SUBSTITUTABLE"
    #: Unchecked, one click from the query.
    AVAILABLE = "AVAILABLE"
    #: Subdued, under More Stats, with a reason it is not its own filter.
    DETAIL = "DETAIL"


class PanelState(str, Enum):
    """What the panel is doing, so it can appear before the market answers."""

    CAPTURED = "CAPTURED"
    SEARCHING = "SEARCHING"
    QUEUED = "QUEUED"
    UPDATING = "UPDATING"
    READY = "READY"
    NO_RESULTS = "NO_RESULTS"
    ERROR = "ERROR"


#: Trust states, spelled the way they are shown.
TRUST_LABELS: dict[str, str] = {
    "HIGH CONFIDENCE": "HIGH CONFIDENCE",
    "ASSISTED ESTIMATE": "ASSISTED ESTIMATE",
    "NEEDS REFINEMENT": "NEEDS REFINEMENT",
    "BASE MARKET ESTIMATE": "BASE MARKET ESTIMATE",
    "MARKET ESTIMATE": "MARKET ESTIMATE",
}

_STATE_TEXT: dict[PanelState, str] = {
    PanelState.CAPTURED: "Reading item…",
    PanelState.SEARCHING: "Checking market…",
    PanelState.QUEUED: "Waiting for market…",
    PanelState.UPDATING: "Updating…",
    PanelState.NO_RESULTS: "No comparable listings found.",
}


@dataclass(frozen=True)
class FilterRow:
    """One line the user can read, check, and edit."""

    key: str
    name: str
    value_text: str
    emphasis: RowEmphasis
    enabled: bool
    minimum: float | None = None
    maximum: float | None = None
    #: Why the bound is what it is: "same affix tier (85-99)".
    range_note: str = ""
    #: Secondary, for the compact row's second line or a tooltip.
    tier_note: str = ""
    #: Why this row is not its own filter, when it is not.
    coverage_note: str = ""
    editable: bool = True
    #: The engine's own words, for a developer tooltip. Never shown by default.
    debug_role: str = ""
    debug_coverage: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "value_text": self.value_text,
            "emphasis": self.emphasis.value,
            "enabled": self.enabled,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "range_note": self.range_note,
            "tier_note": self.tier_note,
            "coverage_note": self.coverage_note,
            "editable": self.editable,
            "debug_role": self.debug_role,
            "debug_coverage": self.debug_coverage,
        }


@dataclass(frozen=True)
class SubstitutableGroup:
    """A set the buyer would swap between, and whether the query could say so."""

    caption: str
    rows: tuple[FilterRow, ...]
    count_min: int
    #: Set when Trade2 could not carry the either/or. Shown, never swallowed.
    limitation: str = ""

    @property
    def expressed_in_query(self) -> bool:
        return not self.limitation

    def to_dict(self) -> dict[str, Any]:
        return {
            "caption": self.caption,
            "count_min": self.count_min,
            "limitation": self.limitation,
            "expressed_in_query": self.expressed_in_query,
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class ComparableRow:
    price_text: str
    stats_text: str
    normalized_text: str = ""
    is_closest: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "price_text": self.price_text,
            "stats_text": self.stats_text,
            "normalized_text": self.normalized_text,
            "is_closest": self.is_closest,
        }


@dataclass(frozen=True)
class PriceCheckPanelModel:
    item_name: str
    base_line: str
    state: PanelState
    state_text: str = ""

    trust_label: str = ""
    trust_note: str = ""
    price_text: str = ""
    listing_count: int = 0

    #: "Compare: Equivalent ES boots" — BaseValueProfile in the user's language.
    compare_text: str = ""
    compare_detail: str = ""

    required: tuple[FilterRow, ...] = ()
    substitutable: tuple[SubstitutableGroup, ...] = ()
    more_stats: tuple[FilterRow, ...] = ()
    comparables: tuple[ComparableRow, ...] = ()

    #: Sentences about what the search could not ask. Never a bare "ignored" list.
    limitations: tuple[str, ...] = ()
    serious_limitation: bool = False
    user_refined: bool = False

    @property
    def has_market_answer(self) -> bool:
        return self.state is PanelState.READY and bool(self.price_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_name": self.item_name,
            "base_line": self.base_line,
            "state": self.state.value,
            "state_text": self.state_text,
            "trust_label": self.trust_label,
            "trust_note": self.trust_note,
            "price_text": self.price_text,
            "listing_count": self.listing_count,
            "compare_text": self.compare_text,
            "compare_detail": self.compare_detail,
            "required": [row.to_dict() for row in self.required],
            "substitutable": [row.to_dict() for row in self.substitutable],
            "more_stats": [row.to_dict() for row in self.more_stats],
            "comparables": [row.to_dict() for row in self.comparables],
            "limitations": list(self.limitations),
            "serious_limitation": self.serious_limitation,
            "user_refined": self.user_refined,
        }


# --- base, in the user's language ---------------------------------------------


def compare_text_for(profile: BaseValueProfile | None) -> tuple[str, str]:
    """Turn a base profile into a sentence. No enum ever reaches the panel."""
    if profile is None:
        return "", ""
    noun = _class_noun(profile)
    if profile.crafting_mode is CraftingMode.CRAFTING_BASE:
        detail = f"exact base · item level {profile.item_level_min}+" if profile.item_level_min else "exact base"
        return f"Crafting base: {profile.exact_base or noun}", detail
    if profile.base_role is BaseRelevance.EXACT:
        return f"Compare: exact {profile.exact_base or noun}", ""
    if profile.base_role is BaseRelevance.FAMILY:
        archetype = _archetype_word(profile)
        label = f"Equivalent {archetype} {noun}".replace("  ", " ").strip()
        return f"Compare: {label}", ""
    if profile.base_role is BaseRelevance.CATEGORY:
        return f"Compare: similar {noun}", ""
    return f"Compare: any {noun}", ""


def _class_noun(profile: BaseValueProfile) -> str:
    return profile.item_class.value.replace("_", " ")


def _archetype_word(profile: BaseValueProfile) -> str:
    words = {
        "ENERGY_SHIELD": "ES",
        "ARMOUR": "armour",
        "EVASION": "evasion",
        "HYBRID": "hybrid",
    }
    return words.get(profile.defence_archetype.value, "")


# --- coverage, as a sentence --------------------------------------------------


def coverage_note_for(row: PlannedCharacteristic, plan: MarketSearchPlan) -> str:
    """Why this characteristic is not its own filter, in the item's own words.

    Each branch is a genuinely different fact. A component folded into a total is fully
    accounted for; a modifier no trade stat can express is not accounted for at all, and
    the difference decides whether the price can be trusted.
    """
    if row.economic_role is MarketRole.DEAD:
        # Checked before UNSEARCHABLE on purpose. A worthless modifier that trade also
        # cannot express is worthless, not a gap in the search — telling the user
        # ExileLens "cannot search" it would invent a limitation that costs nothing.
        return "no effect on price for this item"
    if row.coverage is Coverage.UNSEARCHABLE:
        return "ExileLens cannot search this modifier on trade yet"
    if not row.omitted_from_query:
        # This row *is* the representation the others fold into. "Energy Shield 135,
        # included in the item's final total" would be describing it as its own component.
        return ""
    if row.coverage is Coverage.REPRESENTED_BY_PSEUDO:
        holder = _representative_name(plan, row, prefer_pseudo=True)
        return f"included in {holder}" if holder else "included in a combined total"
    if row.coverage is Coverage.REPRESENTED_BY_PROPERTY:
        holder = _representative_name(plan, row, prefer_property=True)
        return f"included in {holder}" if holder else "included in the item's final total"
    if row.coverage is Coverage.REPRESENTED_BY_BASE:
        return "guaranteed by the exact base being compared"
    if row.coverage is Coverage.UNREPRESENTABLE_GROUP_SEMANTICS:
        return "trade cannot express this either/or, so it is not in the query"
    if row.omitted_from_query:
        return "not in the search — click to add it"
    return ""


def _representative_name(
    plan: MarketSearchPlan,
    row: PlannedCharacteristic,
    *,
    prefer_pseudo: bool = False,
    prefer_property: bool = False,
) -> str:
    group = row.mod.redundancy_group
    if not group:
        return ""
    for candidate in plan.characteristics:
        if candidate.mod.redundancy_group != group or candidate.mod.mod_id == row.mod.mod_id:
            continue
        if prefer_pseudo and candidate.mod.source is not ModSource.PSEUDO:
            continue
        if prefer_property and candidate.mod.source is not ModSource.PROPERTY:
            continue
        return f"{candidate.mod.label} {_number(candidate.mod.raw_value)}"
    return ""


# --- rows ---------------------------------------------------------------------


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _display_name(mod: MarketMod) -> str:
    """The registry's label for a filter row; the mod's own words for a detail row.

    A detail row must read as the item reads. Showing "Maximum Energy Shield 76" for a
    line that actually says "76% increased Energy Shield" describes a different modifier.
    """
    return mod.label or normalize_mod_text(mod.source_text)


def _detail_text(mod: MarketMod) -> str:
    text = normalize_mod_text(mod.source_text).strip()
    if text:
        return text
    return f"{_display_name(mod)} {_number(mod.raw_value)}"


def _tier_note(mod: MarketMod) -> str:
    if mod.tier_min is None or mod.tier_max is None:
        return ""
    note = f"{_number(mod.tier_min)}–{_number(mod.tier_max)}"
    if mod.roll_percentile is not None:
        note = f"{note} · {mod.roll_percentile:.0%} roll"
    return note


def _row_for(
    row: PlannedCharacteristic,
    plan: MarketSearchPlan,
    *,
    emphasis: RowEmphasis,
    enabled: bool,
    use_mod_text: bool = False,
) -> FilterRow:
    mod = row.mod
    return FilterRow(
        key=mod.mod_id,
        name=_detail_text(mod) if use_mod_text else _display_name(mod),
        value_text=_number(mod.raw_value),
        emphasis=emphasis,
        enabled=enabled,
        minimum=row.minimum,
        maximum=row.maximum,
        range_note=row.reason,
        tier_note=_tier_note(mod),
        coverage_note=coverage_note_for(row, plan),
        editable=mod.is_queryable and mod.direction is not Direction.BOOLEAN,
        debug_role=row.economic_role.value,
        debug_coverage=row.coverage.value,
    )


# --- assembly -----------------------------------------------------------------


def build_panel_model(
    *,
    item_name: str,
    plan: MarketSearchPlan | None = None,
    compiled: CompiledTradeQuery | None = None,
    trust: Any | None = None,
    price_text: str = "",
    listing_count: int = 0,
    comparables: Sequence[ComparableRow] = (),
    state: PanelState = PanelState.SEARCHING,
    state_text: str = "",
    user_refined: bool = False,
) -> PriceCheckPanelModel:
    """Assemble everything the panel shows.

    ``plan`` is optional so the panel can appear the moment the item is captured, with
    its name and base, while the market is still being asked.
    """
    base_line = ""
    compare_text = ""
    compare_detail = ""
    if plan is not None and plan.base_profile is not None:
        profile = plan.base_profile
        parts = [profile.exact_base or "", (profile.rarity or "").title()]
        if profile.item_level is not None:
            parts.append(f"ilvl {profile.item_level}")
        base_line = " · ".join(part for part in parts if part)
        compare_text, compare_detail = compare_text_for(profile)

    resolved_state_text = state_text or _STATE_TEXT.get(state, "")

    if plan is None:
        return PriceCheckPanelModel(
            item_name=item_name,
            base_line=base_line,
            state=state,
            state_text=resolved_state_text,
            compare_text=compare_text,
            compare_detail=compare_detail,
            user_refined=user_refined,
        )

    report = compiled.coverage if compiled is not None else None
    unexpressed = _unexpressed_groups(report)

    required = tuple(
        _row_for(row, plan, emphasis=RowEmphasis.REQUIRED, enabled=row.enabled) for row in plan.anchors
    )

    groups: list[SubstitutableGroup] = []
    for group in plan.flexible_groups:
        rows = tuple(
            _row_for(row, plan, emphasis=RowEmphasis.SUBSTITUTABLE, enabled=row.enabled)
            for row in group.filters
        )
        limitation = ""
        if any(row.family in unexpressed for row in group.filters):
            limitation = "Market search cannot express this exact either/or."
        groups.append(
            SubstitutableGroup(
                caption=f"At least {group.count_min} of",
                rows=rows,
                count_min=group.count_min,
                limitation=limitation,
            )
        )

    emitted = {row.family for row in plan.emitted_filters}
    more: list[FilterRow] = []
    for row in plan.characteristics:
        if row.family in emitted:
            continue
        emphasis = (
            RowEmphasis.AVAILABLE
            if row.economic_role is MarketRole.OPTIONAL and row.mod.is_queryable
            else RowEmphasis.DETAIL
        )
        more.append(
            _row_for(
                row,
                plan,
                emphasis=emphasis,
                enabled=False,
                use_mod_text=emphasis is RowEmphasis.DETAIL,
            )
        )
    more.sort(key=lambda row: (row.emphasis is not RowEmphasis.AVAILABLE, row.name))

    trust_label = ""
    trust_note = ""
    if trust is not None:
        raw_state = getattr(getattr(trust, "state", None), "value", "") or str(getattr(trust, "state", ""))
        trust_label = TRUST_LABELS.get(raw_state, raw_state)
        trust_note = str(getattr(trust, "note", "") or "")

    limitations = tuple(report.explain()) if report is not None else ()
    serious = report is not None and report.severity is CoverageSeverity.SERIOUS

    return PriceCheckPanelModel(
        item_name=item_name,
        base_line=base_line,
        state=state,
        state_text=resolved_state_text,
        trust_label=trust_label,
        trust_note=trust_note,
        price_text=price_text,
        listing_count=listing_count,
        compare_text=compare_text,
        compare_detail=compare_detail,
        required=required,
        substitutable=tuple(groups),
        more_stats=tuple(more),
        comparables=tuple(comparables),
        limitations=limitations,
        serious_limitation=serious,
        user_refined=user_refined,
    )


def _unexpressed_groups(report: CompilationCoverageReport | None) -> frozenset[str]:
    if report is None:
        return frozenset()
    return frozenset(
        row.family
        for row in report.entries
        if row.coverage is Coverage.UNREPRESENTABLE_GROUP_SEMANTICS
    )


# --- from a real result -------------------------------------------------------

#: How many comparables the panel shows. Enough to see the shape of the market,
#: few enough to stay compact.
COMPARABLE_LIMIT = 4


def comparable_rows_from_estimate(estimate: Any, plan: MarketSearchPlan | None) -> tuple[ComparableRow, ...]:
    """Turn real listings into one compact line each.

    The stats shown are the ones the search actually filtered on, so a comparable reads
    as an answer to the query rather than a dump of everything the listing happens to
    carry. Nothing is synthesised: a listing with no parseable stats shows its price
    alone.
    """
    from poe2value.price_check.market_mod import extract_market_mods
    from poe2value.price_check.presentation import format_comparable_price

    wanted = [row.family for row in plan.emitted_filters] if plan is not None else []
    labels = {row.family: row.mod.label for row in (plan.emitted_filters if plan else ())}
    rows: list[ComparableRow] = []
    for index, listing in enumerate(tuple(getattr(estimate, "comparables", ()) or ())[:COMPARABLE_LIMIT]):
        price_text = format_comparable_price(listing)
        values: dict[str, float] = {}
        raw = str(getattr(listing, "item_raw", "") or "")
        if raw:
            for mod in extract_market_mods(raw).mods:
                if mod.stat_family in wanted and mod.stat_family not in values:
                    values[mod.stat_family] = mod.raw_value
        summary = " · ".join(
            f"{_number(values[family])} {labels.get(family, family)}"
            for family in wanted
            if family in values
        )
        rows.append(
            ComparableRow(
                price_text=price_text,
                stats_text=summary,
                normalized_text=str(getattr(listing, "normalized_currency", "") or ""),
                is_closest=index == 0,
            )
        )
    return tuple(rows)


def panel_model_for_result(
    *,
    item_name: str,
    plan: MarketSearchPlan | None,
    compiled: CompiledTradeQuery | None,
    result: Any,
    presentation: Mapping[str, Any] | None = None,
    trust: Any = None,
    user_refined: bool = False,
) -> PriceCheckPanelModel:
    """Build the panel model from what the price-check pipeline actually produced."""
    view = dict(presentation or {})
    estimate = getattr(result, "estimate", None)

    state = PanelState.READY
    if view.get("awaiting_live_refresh") or view.get("blocker") == "queued_live_refresh":
        state = PanelState.QUEUED
    elif view.get("blocker") in {"acquisition_failed", "league_required"}:
        state = PanelState.ERROR
    elif not view.get("show_currency") and not int(view.get("comparable_count") or 0):
        state = PanelState.NO_RESULTS

    price_text = str(view.get("market_price") or "") if view.get("show_currency") else ""
    comparables = comparable_rows_from_estimate(estimate, plan) if estimate is not None else ()

    return build_panel_model(
        item_name=item_name,
        plan=plan,
        compiled=compiled,
        trust=trust,
        price_text=price_text,
        listing_count=int(view.get("comparable_count") or 0),
        comparables=comparables,
        state=state,
        state_text=str(view.get("subtitle") or "") if state is not PanelState.READY else "",
        user_refined=user_refined,
    )
