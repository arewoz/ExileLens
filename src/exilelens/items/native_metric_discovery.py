"""Conservative discovery of separate damage values calculated by PoB.

The selected primary resolver remains the authority for every field, with one
narrow exception (:func:`promote_unresolved_primary_with_component`): when the
resolver proves the selected group has *no* usable offense output at all (a
synthetic/wrapper/spawn skill, not merely a slow damage axis), and native
discovery independently proves a same-owner, identity-stable measurement for a
real component, that component's own before/after numbers replace the
permanently-zero placeholder. This never composes or weights skills together --
it substitutes one already-measured, single-identity component for a skill that
produced nothing to measure, and it always says so in the result.
"""

from __future__ import annotations

from typing import Any

from exilelens.items.offense_coverage import RESPONSE_ABS_EPS
from exilelens.items.primary_metric import (
    DamageOwner,
    DamageProvenance,
    DamageQuantity,
    OffenseKind,
    PrimaryMetricConfidence,
    PrimaryMetricSelection,
    resolve_primary_metric,
)

MAX_REPORT_GROUPS = 24
MAX_SECONDARY_COMPONENTS = 3
_IDENTITY_FIELDS = (
    "skill_id", "source", "slot", "actor_id", "actor_skill", "stat_set_key",
    "part_key", "stage_count", "calculation_mode", "show_average", "gems",
)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _metrics(row: dict[str, Any]) -> dict[str, Any]:
    output = row.get("output") or {}
    result = {key: value for key, value in output.items() if key != "Minion"}
    result.update({f"Minion.{key}": value for key, value in (output.get("Minion") or {}).items()})
    return result


def _identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(tuple(row.get(key) or ()) if key == "gems" else row.get(key) for key in _IDENTITY_FIELDS)


def _is_significant_offense_value(value: float | None) -> bool:
    """A PoB offensive output large enough to be real damage, not floating-point noise.

    Reuses the exact threshold ``offense_coverage.RESPONSE_ABS_EPS`` (and
    ``primary_metric._OFFENSE_EPS``, the same 0.5) already use to decide whether a
    PoB damage field is usable evidence one layer above this module. A fractional
    value such as an incidental ignite tick of ``1.3e-6`` is PoB rounding noise, not
    a real damage source: admitting it as fallback component evidence produces a
    mathematically valid but semantically meaningless percentage delta (a near-zero
    denominator turns any change into a manufactured +/-100%). This is the one
    numerical-significance gate every component-eligibility and percent-delta
    computation in this module goes through, instead of scattered ad-hoc `> 0` /
    `!= 0` checks.
    """
    return value is not None and value > RESPONSE_ABS_EPS


def should_discover_components(build: dict[str, Any], primary: PrimaryMetricSelection) -> bool:
    """Skip ordinary single-skill/full-build paths without a PoB report pass."""
    if primary.provenance == DamageProvenance.POB_FULL_BUILD:
        return False
    hints = build.get("native_damage_group_indices") or []
    if not isinstance(hints, list) or len(hints) < 2:
        return False
    if int(build.get("skill_group_count") or 0) > MAX_REPORT_GROUPS or len(hints) > MAX_REPORT_GROUPS:
        return False
    # A very large, unstructured player skill list is not evidence that any
    # particular secondary group matters. Minion actors are explicitly scoped.
    return len(hints) <= 8 or primary.damage_owner == DamageOwner.MINION


def _selection(row: dict[str, Any]) -> tuple[dict[str, Any], float] | None:
    if not row.get("enabled") or not row.get("slot_enabled") or not row.get("skill_id") or not row.get("output"):
        return None
    if row.get("stat_set_count", 0) > 1 and not row.get("stat_set_resolved"):
        return None
    if row.get("part_count", 0) > 1 and not row.get("part_resolved"):
        return None
    metrics = _metrics(row)
    selected = resolve_primary_metric({"main_skill_identity": row}, metrics)
    if selected.confidence != PrimaryMetricConfidence.HIGH or selected.selected == OffenseKind.UNRESOLVED:
        return None
    if selected.provenance != DamageProvenance.POB_PRIMARY_SKILL:
        return None
    value = _number(metrics.get(selected.pob_field))
    if not _is_significant_offense_value(value):
        return None
    return selected.to_dict(), value


def select_baseline_components(
    build: dict[str, Any], primary: PrimaryMetricSelection, metrics: dict[str, Any], report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Primary plus up to three directly measured groups, never sorted by DPS.

    Same damage owner and quantity are semantic relationships, not fake
    importance weights. Ties use the player's PoB group order.
    """
    rows = report.get("groups") or []
    main_index = build.get("main_socket_group")
    selected: list[dict[str, Any]] = []
    primary_value = _number(metrics.get(primary.pob_field))
    if primary.provenance == DamageProvenance.POB_PRIMARY_SKILL and primary_value is not None and primary_value > 0:
        main_row = next((row for row in rows if row.get("index") == main_index), None)
        if main_row:
            selected.append({
                "index": main_index, "identity": main_row, "metric": primary.to_dict(),
                "before": primary_value, "primary": True,
            })
    secondary: list[dict[str, Any]] = []
    for row in rows:
        if row.get("index") == main_index:
            continue
        chosen = _selection(row)
        if chosen is None:
            continue
        metric, value = chosen
        secondary.append({"index": row["index"], "identity": row, "metric": metric,
                          "before": value, "primary": False})
    secondary.sort(key=lambda component: (
        component["metric"]["metric_source"] != primary.damage_owner.value,
        component["metric"]["semantic_quantity"] != primary.semantic_quantity.value,
        component["index"],
    ))
    selected.extend(secondary[:MAX_SECONDARY_COMPONENTS])
    return selected


def _bridge_key(row: dict[str, Any]) -> str:
    return "|".join((
        str(row.get("skill_id") or ""), "item" if row.get("source") else "gem",
        str(row.get("slot") or ""), str(row.get("stat_set_key") or ""),
        str(row.get("actor_id") or ""), str(row.get("actor_skill") or ""),
        ",".join(str(gem) for gem in row.get("gems") or []),
    ))


def candidate_keys(components: list[dict[str, Any]]) -> list[str]:
    return [_bridge_key(component["identity"]) for component in components if not component["primary"]]


def compare_native_components(
    primary: PrimaryMetricSelection, components: list[dict[str, Any]], comparison: dict[str, Any],
) -> dict[str, Any]:
    """Match every component to the same PoB group, owner, state and field."""
    baseline = comparison.get("baseline") or {}
    candidate = comparison.get("candidate") or {}
    report_rows = (candidate.get("component_report") or {}).get("groups") or []
    entries: list[dict[str, Any]] = []
    for component in components:
        original = component["identity"]
        if component["primary"]:
            after_row = candidate.get("primary_skill")
        else:
            matches = [row for row in report_rows if row.get("output") and _identity(row) == _identity(original)]
            after_row = matches[0] if len(matches) == 1 else None
        after_metrics = candidate.get("metrics") if component["primary"] else _metrics(after_row or {})
        field = component["metric"]["pob_field"]
        after_value = _number((after_metrics or {}).get(field))
        same = bool(after_row and _identity(original) == _identity(after_row))
        candidate_metric = comparison.get("candidate_primary_metric") if component["primary"] else None
        if not component["primary"] and after_row and after_value is not None and after_value > 0:
            chosen = _selection(after_row)
            candidate_metric = chosen[0] if chosen else None
        if candidate_metric and after_value is not None and after_value > 0 and any(
            candidate_metric.get(key) != component["metric"].get(key)
            for key in ("pob_field", "metric_source", "semantic_quantity", "metric_scope", "ailment")
        ):
            same = False
        status = "MEASURED" if same and after_value is not None else "UNAVAILABLE"
        before = component["before"]
        entries.append({
            "name": component["metric"]["skill_name"],
            "index": component["index"],
            "owner": component["metric"]["metric_source"],
            "stat_set_key": component["metric"]["primary_skill"].get("stat_set_key") or "",
            "part_key": component["metric"]["primary_skill"].get("part_key") or "",
            "semantic_quantity": component["metric"]["semantic_quantity"],
            "field": field,
            "provenance": DamageProvenance.POB_COMPONENT.value,
            "status": status,
            "before": before,
            "after": after_value if status == "MEASURED" else None,
            "percent_delta": (
                ((after_value / before) - 1) * 100
                if status == "MEASURED" and _is_significant_offense_value(before)
                else None
            ),
            "reason": "" if status == "MEASURED" else "COMPONENT_IDENTITY_OR_OUTPUT_CHANGED",
        })
    name_counts = {row["name"]: sum(other["name"] == row["name"] for other in entries) for row in entries}
    for row in entries:
        row["label"] = (
            f"{row['name']} (PoB group {row['index']})"
            if name_counts[row["name"]] > 1 else row["name"]
        )
    full_status = primary.full_dps_status
    if primary.provenance == DamageProvenance.POB_FULL_BUILD:
        scope, provenance = "FULL", DamageProvenance.POB_FULL_BUILD.value
        composition_status = "COMPLETE"
    elif primary.provenance == DamageProvenance.POB_PRIMARY_SKILL and len(entries) >= 2:
        scope, provenance = "PARTIAL", DamageProvenance.POB_COMPONENT.value
        # Multiple independently measured PoB groups make this a partial
        # component *report*, but their mere presence does not prove that they
        # are all materially relevant to the item's overall damage effect.
        composition_status = "NOT_ASSESSED"
    elif primary.provenance == DamageProvenance.POB_PRIMARY_SKILL:
        scope, provenance = "PRIMARY", DamageProvenance.POB_PRIMARY_SKILL.value
        composition_status = "NOT_ASSESSED"
    else:
        scope, provenance = "PARTIAL", DamageProvenance.UNAVAILABLE.value
        composition_status = "PARTIAL"
    return {
        "damage_scope": scope,
        "provenance": provenance,
        "full_build": {"available": primary.provenance == DamageProvenance.POB_FULL_BUILD,
                       "field": primary.pob_field if primary.provenance == DamageProvenance.POB_FULL_BUILD else "",
                       "status": full_status},
        "primary_skill_metric": primary.to_dict(),
        "components": entries,
        "fallback_reason": "FULL_DPS_NOT_CONFIGURED" if full_status == "NOT_CONFIGURED" else "",
        "composition_status": composition_status,
        "overall_damage_verdict": "UNCERTAIN" if composition_status == "PARTIAL" else "NOT_DERIVED",
        "baseline_fingerprint": baseline.get("fingerprint_hash") or "",
    }


def promote_unresolved_primary_with_component(
    metric_profile: dict[str, dict[str, Any]], comparison: dict[str, Any], *, primary_confidence: str = "low",
) -> tuple[dict[str, dict[str, Any]], str, str]:
    """Replace a proven-zero placeholder offense delta with a measured component's.

    Only fires when :func:`resolve_primary_metric` reported the narrowest possible
    failure -- CombinedDPS/FullDPS/TotalDPS/DoT were *all* ~0, i.e. the selected PoB
    group is a synthetic/wrapper/spawn skill with nothing to measure at all
    (``DamageQuantity.UNRESOLVED``). A skill with real but ambiguous output (mixed
    hit/DoT/ailment composition) is a different, already-handled case and is left
    untouched.

    The candidate is native discovery's own top-sorted PLAYER entry whose identity
    matched baseline to candidate (``status == "MEASURED"``) -- the same deterministic,
    non-name-based ordering `select_baseline_components` already uses (owner match,
    quantity match, PoB group index). No skill is picked by name, and nothing here
    weighs or combines components; at most one substitution happens, and it is always
    reported via ``substituted_component`` rather than presented as the selected skill.

    Returns the (possibly updated) metric_profile and the PoB field the offense delta
    now reflects, so the caller can keep ``primary_metric_field`` in sync.
    """
    offense = dict(metric_profile.get("primary_offense") or {})
    fallback_field = str(offense.get("pob_field") or "CombinedDPS")
    primary_ref = comparison.get("baseline_primary_metric") or {}
    if str(primary_ref.get("semantic_quantity") or "") != DamageQuantity.UNRESOLVED.value:
        return metric_profile, fallback_field, primary_confidence

    components = (comparison.get("native_damage_discovery") or {}).get("components") or []
    chosen = next(
        (
            entry for entry in components
            if entry.get("status") == "MEASURED"
            and entry.get("owner") == DamageOwner.PLAYER.value
            and isinstance(entry.get("before"), (int, float))
            and isinstance(entry.get("after"), (int, float))
            # A component whose OWN baseline output is noise-sized must never win
            # the fallback slot merely because it is first in PoB group order and
            # "measured" -- see `_is_significant_offense_value`. Preserved below it:
            # deterministic PoB-group-order selection among genuinely-eligible
            # components, unchanged.
            and _is_significant_offense_value(entry.get("before"))
        ),
        None,
    )
    if chosen is None:
        return metric_profile, fallback_field, primary_confidence

    before, after = float(chosen["before"]), float(chosen["after"])
    absolute_delta = after - before
    percent_delta = ((after / before) - 1.0) * 100.0 if _is_significant_offense_value(before) else None
    direction = "neutral" if abs(absolute_delta) < 1e-9 else ("positive" if absolute_delta > 0 else "negative")
    label = str(chosen.get("label") or chosen.get("name") or "Damage")
    metric_profile = dict(metric_profile)
    metric_profile["primary_offense"] = {
        **offense,
        "label": f"{label} (measured component)",
        "pob_field": str(chosen.get("field") or fallback_field),
        "current": before,
        "candidate": after,
        "absolute_delta": absolute_delta,
        "percent_delta": percent_delta,
        "absolute": absolute_delta,
        "percent": percent_delta,
        "direction": direction,
        "availability": "available",
        "confidence": "high",
        "delta_kind": "MEASURED_ZERO" if before == 0 and after == 0 else "MEASURED",
        "coverage_state": "PARTIAL",
        "provenance": DamageProvenance.POB_COMPONENT.value,
        "substituted_component": {
            "name": chosen.get("name"),
            "index": chosen.get("index"),
            "owner": chosen.get("owner"),
            "reason": (
                "the selected PoB skill has no usable offense output; using this "
                "build's own measured native PLAYER component instead"
            ),
        },
    }
    # native discovery's own `_selection()` only admits HIGH-confidence, identity-matched
    # rows into `components` -- the substitute skill's own resolution is exactly as
    # trustworthy as any other confidently-identified PoB skill, so this does not
    # force `primary_confidence` down to "low" purely because the ORIGINAL (unresolved)
    # selection was low-confidence. That does NOT mean the overall evaluation is FULL
    # quality, though: a substitution is definitionally partial coverage of the build's
    # true damage (one secondary skill standing in for a primary that measured nothing
    # at all). `evaluation_outcome.assess_quality` reads the `substituted_component` key
    # set above and caps quality at PARTIAL whenever it is present -- that is the
    # correct, single place this truthfulness signal is enforced, not here and not by
    # lying about this component's own identification confidence.
    return metric_profile, str(chosen.get("field") or fallback_field), "high"
