"""Pure edits for logical MARKET-03 plans and the explicit legacy hypothesis seam."""

from __future__ import annotations

from typing import Any, Mapping

from poe2value.price_check.market_drivers import MatchMode, PriceCheckHypothesis


def family_of(row_key: str) -> str:
    """The stat family a panel row key refers to."""
    return str(row_key or "").split(":", 1)[0]


def apply_panel_edits(
    hypothesis: PriceCheckHypothesis, edits: Mapping[str, Any]
) -> PriceCheckHypothesis:
    """Return the hypothesis the user's edits describe.

    Families the panel did not mention keep whatever state they already had — an edit is a
    change to what the user touched, not a redeclaration of everything else.
    """
    rows = list(edits.get("filters") or ())
    by_family: dict[str, dict[str, Any]] = {}
    for row in rows:
        family = family_of(row.get("key", ""))
        if family:
            by_family.setdefault(family, row)

    enabled_ids: list[str] = []
    search_mins: dict[str, float] = {}
    for driver in hypothesis.available_drivers:
        row = by_family.get(driver.family)
        if row is None:
            if driver.enabled:
                enabled_ids.append(driver.driver_id)
            continue
        if bool(row.get("enabled")):
            enabled_ids.append(driver.driver_id)
        minimum = row.get("minimum")
        if minimum is not None:
            search_mins[driver.driver_id] = float(minimum)

    match_mode = hypothesis.match_mode
    count_min = hypothesis.count_min
    if match_mode is MatchMode.COUNT and count_min is not None:
        # A COUNT group cannot ask for more matches than it has filters left.
        count_min = max(1, min(int(count_min), max(1, len(enabled_ids))))

    return hypothesis.refined(
        enabled_ids=enabled_ids,
        search_mins=search_mins,
        match_mode=match_mode,
        count_min=count_min,
    )


def apply_plan_edits(plan, edits: Mapping[str, Any]):
    """Patch rows by exact mod identity, preserving roles, groups and base policy."""
    from dataclasses import replace
    import math

    by_key = {str(row.get("key", "")): row for row in edits.get("filters", ())}
    active = {row.mod.mod_id for row in plan.emitted_filters if row.enabled}
    updated = {}
    for row in plan.characteristics:
        edit = by_key.get(row.mod.mod_id)
        if edit is None:
            updated[row.mod.mod_id] = row
            continue
        changes = {"enabled": bool(edit.get("enabled", row.mod.mod_id in active))}
        for field in ("minimum", "maximum"):
            if field in edit:
                value = edit[field]
                if value is not None:
                    value = float(value)
                    if not math.isfinite(value):
                        raise ValueError("search bounds must be finite")
                changes[field] = value
                if value != getattr(row, field):
                    changes["reason"] = "set by you"
        if not changes["enabled"] and row.mod.mod_id in active:
            changes["omission_reason"] = "disabled by you"
        elif changes["enabled"] and row.omission_reason == "disabled by you":
            changes["omission_reason"] = ""
        candidate = replace(row, **changes)
        if candidate.minimum is not None and candidate.maximum is not None and candidate.minimum > candidate.maximum:
            raise ValueError("minimum exceeds maximum")
        updated[row.mod.mod_id] = candidate
    def rows(values):
        return tuple(updated[row.mod.mod_id] for row in values)
    anchors = rows(plan.anchors)
    existing = {row.mod.mod_id for row in plan.emitted_filters}
    anchors += tuple(row for key, row in updated.items()
                     if key not in existing and key in by_key and row.enabled and row.mod.is_queryable)
    return replace(plan, characteristics=rows(plan.characteristics), anchors=anchors,
                   flexible_groups=tuple(replace(group, filters=rows(group.filters),
                       count_min=max(1, min(int(edits.get("count_min", group.count_min)),
                                            sum(row.enabled for row in rows(group.filters)))))
                                         for group in plan.flexible_groups),
                   optional=rows(plan.optional))
