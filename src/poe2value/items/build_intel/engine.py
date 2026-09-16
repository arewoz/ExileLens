"""TIER-1 attach: whole-item exact eval already done. No extra PoB."""

from __future__ import annotations

from typing import Any

from poe2value.items.build_intel.axes import build_axes, pareto_status
from poe2value.items.build_intel.constraints import constraints_from_thresholds
from poe2value.items.build_intel.item_semantics import parse_item_semantics
from poe2value.items.build_intel.models import (
    BuildComparisonResult,
    BuildConfidence,
    BuildImpactExplanation,
    BuildVerdict,
    SlotComparisonNote,
    ThresholdEvent,
)
from poe2value.items.build_intel.relevance import assign_build_mods, candidate_synergy, important_mod_rows, rank_groups_for_decomposition
from poe2value.items.build_intel.thresholds import assess_thresholds
from poe2value.items.build_intel.verdicts import classify_product_verdict, classify_significance, overlay_verdict_label
from poe2value.items.decision import EvaluationConfidence, assess_confidence
from poe2value.items.ranking import enrich_slot_comparison
from poe2value.items.value_profiles import SCORE_SCALE


def _evidence_line(event: ThresholdEvent) -> dict[str, Any]:
    before = event.before
    after = event.after
    range_text = ""
    if before is not None and after is not None:
        if event.metric.endswith("_res") or event.metric in {"mana_sustain"}:
            range_text = f"{_fmt(before)} → {_fmt(after)}"
        else:
            range_text = f"{_fmt(before)} → {_fmt(after)}"
    return {
        "code": event.code,
        "metric": event.metric,
        "before": event.before,
        "after": event.after,
        "threshold": event.threshold,
        "detail": event.detail,
        "range_text": range_text,
        "text": f"{event.detail}" + (f"  {range_text}" if range_text else ""),
    }


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.2f}m"
        return f"{value:,.0f}"
    if abs(value - round(value)) < 0.05:
        return f"{value:.0f}"
    return f"{value:.1f}"


def _axis_reason(axis_id: str, axes: dict[str, Any]) -> dict[str, Any] | None:
    axis = axes.get(axis_id)
    if not axis:
        return None
    payload = axis.to_dict() if hasattr(axis, "to_dict") else dict(axis)
    if payload.get("delta_kind") in {"UNMEASURED", "UNSUPPORTED", "MISSING", "ESTIMATED"}:
        estimated = payload.get("delta_kind") == "ESTIMATED"
        return {
            "code": payload.get("delta_kind"),
            "metric": axis_id.lower(),
            "detail": f"{payload.get('label') or axis_id} {str(payload.get('delta_kind')).lower()}",
            "text": f"{payload.get('label') or axis_id} {'estimate only' if estimated else 'unmeasured'}",
            "range_text": "",
            "unmeasured": True,
        }
    pct = payload.get("percent_delta")
    if pct is None or abs(float(pct)) < 0.5:
        return None
    sign = "+" if float(pct) > 0 else ""
    current = payload.get("current")
    candidate = payload.get("candidate")
    range_text = ""
    if current is not None and candidate is not None:
        range_text = f"{_fmt(float(current))} → {_fmt(float(candidate))}"
    return {
        "code": f"{axis_id}_DELTA",
        "metric": axis_id.lower(),
        "detail": f"{sign}{float(pct):.1f}% {payload.get('label') or axis_id}",
        "text": f"{sign}{float(pct):.1f}% {payload.get('label') or axis_id}",
        "range_text": range_text,
        "before": current,
        "after": candidate,
        "percent_delta": pct,
    }


def _confidence(
    comparison: dict[str, Any],
    *,
    primary_metric: dict[str, Any] | None,
    decomposition_status: str,
    axes: dict[str, Any],
) -> tuple[str, list[str]]:
    base, reasons = assess_confidence(comparison, primary_metric=primary_metric)
    quality = str((comparison.get("evaluation_outcome") or {}).get("evaluation_quality") or "")
    if quality and quality != "FULL":
        return BuildConfidence.LOW.value, list(reasons) + [f"evaluation quality {quality}"]
    offense = axes.get("OFFENSE")
    kind = getattr(offense, "delta_kind", None) if offense is not None else None
    if kind in {"UNMEASURED", "UNSUPPORTED", "MISSING", "ESTIMATED"}:
        return BuildConfidence.LOW.value, list(reasons) + [f"offense {kind}"]
    if base == EvaluationConfidence.LOW:
        return BuildConfidence.LOW.value, list(reasons)
    if decomposition_status != "COMPLETE":
        extra = list(reasons) + ["semantic decomposition pending"]
        return BuildConfidence.ASSISTED.value, extra
    if base == EvaluationConfidence.HIGH:
        return BuildConfidence.HIGH.value, list(reasons) or ["exact PoB evaluation succeeded"]
    return BuildConfidence.ASSISTED.value, list(reasons)


def _slot_notes(payload: dict[str, Any], *, selected_slot: str) -> list[SlotComparisonNote]:
    notes: list[SlotComparisonNote] = []
    for comparison in payload.get("slot_comparisons") or []:
        intel = comparison.get("build_comparison") or {}
        outcome = comparison.get("evaluation_outcome") or {}
        outcome_verdict = str(outcome.get("verdict") or "")
        notes.append(
            SlotComparisonNote(
                pob_slot=str(comparison.get("pob_slot") or ""),
                product_slot=str(comparison.get("product_slot") or ""),
                product_verdict=str(intel.get("product_verdict") or comparison.get("verdict") or ""),
                score_delta=((comparison.get("value") or {}).get("score_delta")),
                selected=str(comparison.get("pob_slot") or "") == selected_slot,
                blocked=str(intel.get("product_verdict") or "") in {"BLOCKED", "UNSAFE"}
                or outcome_verdict in {"NOT_VIABLE", "NOT_EVALUATED"},
                verdict=outcome_verdict,
                final_score=outcome.get("final_score"),
            )
        )
    return notes


def compare_slot(
    comparison: dict[str, Any],
    *,
    raw_text: str = "",
    metadata: dict[str, Any] | None = None,
    primary_metric: dict[str, Any] | None = None,
    profile: str = "BALANCED",
    item_type: str = "",
) -> BuildComparisonResult:
    metric_profile = comparison.get("metric_profile") or comparison.get("normalized_metrics") or {}
    resist = comparison.get("resist_caps") or {}
    raw_current = (comparison.get("baseline") or {}).get("metrics") or {}
    raw_candidate = (comparison.get("candidate") or {}).get("metrics") or {}
    # A deferred restore (PERF-02) reports `pass: None` -- pending, not failed.
    restore_failed = (comparison.get("restore") or {}).get("pass") is False
    value = comparison.get("value") or {}
    outcome = comparison.get("evaluation_outcome") or {}
    # BuildComparisonResult is the compatibility/diagnostic aggregate. The
    # outcome's final score is the separate public score after semantic policy.
    raw_rating = outcome.get("raw_score")
    score_delta = (float(raw_rating) - SCORE_SCALE.equivalent
                   if raw_rating is not None else value.get("score_delta"))
    try:
        score_num = float(score_delta) if score_delta is not None else None
    except (TypeError, ValueError):
        score_num = None

    axes = build_axes(
        metric_profile,
        raw_current=raw_current,
        raw_candidate=raw_candidate,
        score_delta=score_num,
    )
    thresholds = assess_thresholds(
        metric_profile,
        resist,
        raw_current,
        raw_candidate,
        restore_failed=restore_failed,
    )
    hard_problems = constraints_from_thresholds(thresholds)
    build_fixes = [item for item in thresholds if item.is_build_fix]
    ranking_verdict = str(comparison.get("verdict") or "UNRESOLVED")
    product = classify_product_verdict(
        ranking_verdict=ranking_verdict,
        axes=axes,
        build_fixes=build_fixes,
        hard_problems=hard_problems,
        score_delta=score_num,
    )
    # The outcome's structured impact is the semantic authority for trustworthy
    # whole-item comparisons. Legacy raw AxisDelta rows remain explanation data.
    impact = outcome.get("item_impact") or {}
    if outcome.get("evaluation_quality") == "FULL" and not hard_problems and impact.get("pattern") == "TRADEOFF":
        product = BuildVerdict.TRADEOFF
    significance = classify_significance(axes, build_fixes=build_fixes, hard_problems=hard_problems)

    semantic = parse_item_semantics(
        raw_text,
        metadata=metadata,
        product_slot=str(comparison.get("product_slot") or ""),
        item_type=item_type,
    )
    mods = assign_build_mods(semantic, axes=axes, thresholds=thresholds, resist=resist)
    synergy = candidate_synergy(semantic)
    decomp_status = "PENDING" if rank_groups_for_decomposition(mods) else "SKIPPED"

    confidence, confidence_reasons = _confidence(
        comparison,
        primary_metric=primary_metric,
        decomposition_status=decomp_status,
        axes=axes,
    )

    improvements = []
    for axis_id in ("OFFENSE", "DEFENCE", "RECOVERY", "RESOURCE", "MOBILITY"):
        row = _axis_reason(axis_id, axes)
        if row and not row.get("unmeasured") and float(row.get("percent_delta") or 0) > 0:
            improvements.append(row)
    tradeoffs = []
    for axis_id in ("OFFENSE", "DEFENCE", "RECOVERY", "RESOURCE", "MOBILITY"):
        row = _axis_reason(axis_id, axes)
        if row and not row.get("unmeasured") and float(row.get("percent_delta") or 0) < 0:
            if axis_id == "MOBILITY" and float(row.get("percent_delta") or 0) <= -8:
                row["detail"] = "MAJOR MOBILITY LOSS"
                row["text"] = f"MAJOR MOBILITY LOSS  {row.get('range_text') or row['text']}"
            tradeoffs.append(row)
    primary = [_evidence_line(item) for item in build_fixes[:2]]
    if not primary:
        primary = [row for row in improvements[:2] if row]
    if not primary and tradeoffs:
        primary = tradeoffs[:1]

    profile_note = ""
    if profile and profile.upper() != "BALANCED":
        profile_note = f"Recommended for {profile.replace('_', ' ').title()} profile"

    explanation = BuildImpactExplanation(
        headline=overlay_verdict_label(product),
        primary_reasons=primary,
        build_fixes=[_evidence_line(item) for item in build_fixes],
        improvements=improvements,
        tradeoffs=tradeoffs,
        hard_problems=[item.to_dict() for item in hard_problems],
        mod_contributions=important_mod_rows(mods),
        synergy_findings=[item.to_dict() for item in synergy],
        confidence=confidence,
        profile_note=profile_note,
    )

    return BuildComparisonResult(
        product_verdict=product.value,
        ranking_verdict=ranking_verdict,
        significance=significance.value,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        axes=axes,
        thresholds=thresholds,
        build_fixes=build_fixes,
        hard_problems=hard_problems,
        mods=mods,
        explanation=explanation,
        best_slot=str(comparison.get("pob_slot") or ""),
        slot_opportunity="",
        pareto_status=("TRADEOFF" if outcome.get("evaluation_quality") == "FULL"
                       and not hard_problems and impact.get("pattern") == "TRADEOFF"
                       else pareto_status(axes, hard_break=bool(hard_problems))),
        contribution=[],
        synergy=synergy,
        decomposition_status=decomp_status,
        profile=profile,
        score_delta=score_num,
        rating=float(raw_rating) if raw_rating is not None else
               (float(value["rating"]) if value.get("rating") is not None else None),
        semantic=semantic.to_dict(),
        economics_seam={
            "build_value_delta": score_num,
            "price": None,
            "power_per_currency": None,
        },
    )


def attach_build_intelligence(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    raw_text = str((result.get("raw_input") or {}).get("raw_text") or "")
    metadata = result.get("metadata") or {}
    if hasattr(metadata, "__dict__") and not isinstance(metadata, dict):
        metadata = dict(metadata.__dict__)
    primary = result.get("primary_metric") or {}
    profile = str(result.get("value_profile") or "BALANCED")
    item_type = str((result.get("pob_parse") or {}).get("item", {}).get("type") or "")
    if not item_type:
        item_type = str(((result.get("pob_parse") or {}).get("item") or {}).get("type") or "")

    enriched_slots: list[dict[str, Any]] = []
    for comparison in result.get("slot_comparisons") or []:
        slot = dict(comparison)
        if not slot.get("metric_profile"):
            slot = enrich_slot_comparison(slot, offense_coverage=result.get("offense_coverage"))
        intel = compare_slot(
            slot,
            raw_text=raw_text,
            metadata=metadata,
            primary_metric=primary,
            profile=profile,
            item_type=item_type,
        )
        slot["build_comparison"] = intel.to_dict()
        enriched_slots.append(slot)
    result["slot_comparisons"] = enriched_slots

    recommendation = dict(result.get("recommendation") or {})
    selected_slot = str(recommendation.get("pob_slot") or "")
    matched = None
    for slot in enriched_slots:
        if str(slot.get("pob_slot") or "") == selected_slot:
            matched = slot
            break
    if matched is None and enriched_slots:
        matched = enriched_slots[0]
        selected_slot = str(matched.get("pob_slot") or selected_slot)
    if matched is not None:
        intel_payload = dict(matched.get("build_comparison") or {})
        notes = _slot_notes({**result, "slot_comparisons": enriched_slots}, selected_slot=selected_slot)
        intel_payload["slot_notes"] = [item.to_dict() for item in notes]
        recommendation["build_comparison"] = intel_payload
        result["recommendation"] = recommendation
        result["build_comparison"] = intel_payload
    # Preserve a later TIER-2 blob if the caller already attached one (rescore).
    prior = payload.get("build_intel_decomposition")
    if prior:
        result["build_intel_decomposition"] = prior
        result = attach_decomposition(result, prior)
    return result


def attach_decomposition(payload: dict[str, Any], decomp: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["build_intel_decomposition"] = decomp
    intel = dict(result.get("build_comparison") or {})
    if not intel:
        return result
    intel["contribution"] = list(decomp.get("contribution") or [])
    intel["synergy"] = list(decomp.get("synergy") or intel.get("synergy") or [])
    intel["decomposition_status"] = str(decomp.get("status") or "COMPLETE")
    if intel.get("decomposition_status") == "COMPLETE" and intel.get("confidence") == BuildConfidence.ASSISTED.value:
        reasons = [item for item in intel.get("confidence_reasons") or [] if "decomposition pending" not in item]
        intel["confidence"] = BuildConfidence.HIGH.value
        intel["confidence_reasons"] = reasons or ["exact PoB evaluation succeeded"]
    explanation = dict(intel.get("explanation") or {})
    if decomp.get("contribution"):
        explanation["mod_contributions"] = _merge_mod_contributions(
            list(explanation.get("mod_contributions") or []),
            list(decomp.get("contribution") or []),
        )
    if decomp.get("synergy"):
        explanation["synergy_findings"] = list(decomp.get("synergy") or [])
    intel["explanation"] = explanation
    result["build_comparison"] = intel
    recommendation = dict(result.get("recommendation") or {})
    if recommendation:
        recommendation["build_comparison"] = intel
        result["recommendation"] = recommendation
    return result


def _merge_mod_contributions(existing: list[dict[str, Any]], measured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_group = {str(item.get("group") or ""): item for item in measured}
    merged: list[dict[str, Any]] = []
    for row in existing:
        group = str(row.get("family") or row.get("label") or "")
        hit = None
        for key, item in by_group.items():
            if key and (key in group.lower() or str(item.get("label") or "").lower() == str(row.get("label") or "").lower()):
                hit = item
                break
        if hit and hit.get("marginal") is not None:
            row = dict(row)
            row["marginal"] = hit.get("marginal")
            row["measured"] = True
        merged.append(row)
    return merged or existing
