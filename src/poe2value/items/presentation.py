from __future__ import annotations

from enum import Enum
from typing import Any

from poe2value.items.display_thresholds import DEFAULT_DISPLAY_THRESHOLDS, is_display_worthy
from poe2value.items.formatting import format_current_candidate, format_metric_delta
from poe2value.items.presentation_copy import (
    apply_passive_aux_companion_policy,
    apply_presentation_dedupe,
    dedupe_reason_blocks,
    dedupe_warnings,
    recommendation_tag_display,
    should_show_why_not_section,
    verdict_headline,
    verdict_subtitle,
    why_section_title,
)
from poe2value.items.decision import derive_swap_risk
from poe2value.items.offense_coverage import (
    OffenseCoverageState,
    offense_claim_allowed,
    offense_comparison_limited,
    offense_delta_comparable,
)
from poe2value.items.upgrade_path import build_repair_steps


class PopupDensity(str, Enum):
    COMPACT = "COMPACT"
    STANDARD = "STANDARD"
    DETAILED = "DETAILED"


class SurfaceMode(str, Enum):
    """Which product surface a presentation is being rendered for.

    Generic shared primitive: the passive overlay, the pinned card and the dashboard
    all need to name their surface. It carries no per-surface product behaviour.
    """

    PASSIVE_COMPACT = "PASSIVE_COMPACT"
    PINNED_EXTENDED = "PINNED_EXTENDED"
    DASHBOARD_FULL = "DASHBOARD_FULL"


_DENSITY_ROW_LIMITS = {
    PopupDensity.COMPACT: 4,
    PopupDensity.STANDARD: 6,
    PopupDensity.DETAILED: 8,
}

MAX_NORMAL_ROWS = DEFAULT_DISPLAY_THRESHOLDS.max_overlay_rows
MAJOR_DEFENSE_LOSS_PCT = 6.0
ZERO_ABS = 0.5
ZERO_PCT = 0.05

ROW_PRIORITY = (
    "primary_offense",
    "cast_attack_speed",
    "ehp",
    "worst_max_hit",
    "lightning_res",
    "fire_res",
    "cold_res",
    "chaos_res",
    "life",
    "energy_shield",
    "movement_speed",
    "mana",
)

PRIORITY_INDEX = {key: index for index, key in enumerate(ROW_PRIORITY)}
EMPHASIS_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "muted": 4}

SECTION_IDS = ("header", "baseline", "metrics", "warnings", "verdict", "value", "why_not_upgrade", "upgrade_path")

VERDICT_LABELS = {
    "STRONG_UPGRADE": "STRONG UPGRADE",
    "CLEAR_UPGRADE": "CLEAR UPGRADE",
    "OFFENSE_UPGRADE": "OFFENSE UPGRADE",
    "DEFENSE_UPGRADE": "DEFENSE UPGRADE",
    "TRADEOFF": "TRADEOFF",
    "SIDEGRADE": "SIDEGRADE",
    "DOWNGRADE": "DOWNGRADE",
    "STRONG_DOWNGRADE": "STRONG DOWNGRADE",
    "UNRESOLVED": "UNRESOLVED",
    "NO_CHANGE": "NO CHANGE",
    "MAJOR_UPGRADE": "MAJOR UPGRADE",
    "MEANINGFUL_UPGRADE": "MEANINGFUL UPGRADE",
    "MINOR_UPGRADE": "MINOR UPGRADE",
    "BUILD_FIX": "BUILD FIX",
    "BLOCKED": "BLOCKED",
    "UNSAFE": "UNSAFE DOWNGRADE",
}

VERDICT_EMPHASIS = {
    "STRONG_UPGRADE": "critical",
    "CLEAR_UPGRADE": "high",
    "OFFENSE_UPGRADE": "high",
    "DEFENSE_UPGRADE": "high",
    "TRADEOFF": "high",
    "SIDEGRADE": "medium",
    "DOWNGRADE": "high",
    "STRONG_DOWNGRADE": "critical",
    "UNRESOLVED": "medium",
    "NO_CHANGE": "low",
    "MAJOR_UPGRADE": "critical",
    "MEANINGFUL_UPGRADE": "high",
    "MINOR_UPGRADE": "medium",
    "BUILD_FIX": "high",
    "BLOCKED": "critical",
    "UNSAFE": "critical",
    # EvaluationOutcome public verdicts.
    "MINOR_DOWNGRADE": "high",
    "MEANINGFUL_DOWNGRADE": "critical",
    "NOT_VIABLE": "critical",
    "POTENTIAL_UPGRADE": "medium",
    "POTENTIAL_DOWNGRADE": "medium",
    "UNCERTAIN": "medium",
    "NOT_EVALUATED": "medium",
}

CAP_STATE_LABELS = {
    "CAP_LOST": "CAP LOST",
    "BELOW_CAP_WORSENED": "Below cap — worse",
    "BELOW_CAP_IMPROVED": "Below cap — better",
    "BELOW_CAP_UNCHANGED": "Still below cap",
    "CAPPED_STAYS_CAPPED": "Capped",
    "OVER_CAP_REDUCED_BUT_STILL_CAPPED": "Overcap reduced",
    "CAP_REACHED": "Cap reached",
    "UNKNOWN": "",
    "FURTHER_BELOW_CAP": "Below cap — worse",
    "STILL_BELOW_CAP": "Still below cap",
    "CAP_MAINTAINED": "Capped",
    "CAP_GAINED": "Cap reached",
}

CAP_STATE_EMPHASIS = {
    "CAP_LOST": "critical",
    "BELOW_CAP_WORSENED": "high",
    "BELOW_CAP_IMPROVED": "medium",
    "BELOW_CAP_UNCHANGED": "high",
    "CAPPED_STAYS_CAPPED": "medium",
    "OVER_CAP_REDUCED_BUT_STILL_CAPPED": "medium",
    "CAP_REACHED": "high",
    "FURTHER_BELOW_CAP": "high",
    "STILL_BELOW_CAP": "high",
    "CAP_MAINTAINED": "medium",
    "CAP_GAINED": "high",
}

DISPLAYED_CAP_STATES = {
    "CAP_LOST",
    "BELOW_CAP_WORSENED",
    "BELOW_CAP_IMPROVED",
    "BELOW_CAP_UNCHANGED",
    "OVER_CAP_REDUCED_BUT_STILL_CAPPED",
    "CAP_REACHED",
    "FURTHER_BELOW_CAP",
    "STILL_BELOW_CAP",
    "CAP_GAINED",
}

CRITICAL_WARNING_CODES = {
    "RES_CAP_LOST",
    "MAIN_SKILL_INVALID",
    "BUILD_INVALID",
    "RESOURCE_FAILURE",
}


def build_presentation(
    result: dict[str, Any],
    *,
    build_name: str = "",
    loadout_name: str = "",
    item_set_name: str = "",
    context: str = "MAP",
    value_profile: str = "BALANCED",
    popup_density: str = PopupDensity.STANDARD.value,
    decision_enabled: bool = True,
    multi_profile_enabled: bool = True,
    best_slot_enabled: bool = True,
) -> dict[str, Any]:
    metadata = result.get("metadata") or {}
    pob_parse = result.get("pob_parse") or {}
    identity = pob_parse.get("identity") or {}
    density = PopupDensity(str(popup_density or PopupDensity.COMPACT.value).upper())
    if density not in PopupDensity:
        density = PopupDensity.COMPACT
    row_limit = _DENSITY_ROW_LIMITS[density]

    recommendation = result.get("recommendation") or {}
    decision = result.get("decision") or {}
    best_slot = result.get("best_slot") or {}
    multi_profile = result.get("multi_profile") or {}
    metrics = recommendation.get("normalized_metrics") or recommendation.get("metric_profile") or {}
    warnings = list(recommendation.get("warnings") or [])
    resist = recommendation.get("resist_caps") or {}
    value = recommendation.get("value") or result.get("value") or {}
    power = recommendation.get("power_per_currency") or result.get("power_per_currency")
    primary_metric = result.get("primary_metric") or {}
    native_discovery = recommendation.get("native_damage_discovery") or result.get("native_damage_discovery") or {}
    offense_coverage = result.get("offense_coverage")
    if offense_coverage is None:
        offense_coverage = recommendation.get("offense_coverage")

    name = (
        metadata.get("name")
        or pob_parse.get("display_name")
        or identity.get("name")
        or "Unknown item"
    )
    base_type = metadata.get("base_type") or identity.get("base_name") or ""
    rarity = (metadata.get("rarity") or identity.get("rarity") or "").upper()
    slot = recommendation.get("pob_slot") or recommendation.get("product_slot") or ""
    baseline_item = recommendation.get("baseline_item") or {}
    baseline_name = baseline_item.get("display_name") or baseline_item.get("name")
    if baseline_item.get("empty"):
        baseline_name = f"Empty {slot} Slot" if slot else "Empty slot"
    if baseline_name:
        baseline_line = f"vs {baseline_name}" + (f" · {slot}" if slot else "")
    else:
        baseline_parts = [part for part in (f"vs {slot}" if slot else "", loadout_name or build_name, context) if part]
        baseline_line = " · ".join(baseline_parts)
    set_label = item_set_name or loadout_name or build_name
    baseline_meta = " · ".join(part for part in (set_label, context, value_profile) if part)
    pob_baseline_label = f"PoB baseline: {baseline_name}" if baseline_name else "PoB baseline"
    compared_against = {
        "title": "COMPARED AGAINST",
        "name": baseline_name or slot,
        "base_type": baseline_item.get("base_type") or "",
        "slot": slot,
        "item_set": item_set_name or baseline_item.get("item_set_name") or "",
        "loadout": loadout_name or baseline_item.get("loadout_name") or "",
        "source": "PoB baseline (not automatically in-game equipped gear)",
        "raw": baseline_item.get("raw") or "",
    }

    forced_keys = {item.get("metric") for item in warnings if item.get("severity") == "critical"}
    warning_keys = {item.get("metric") for item in warnings if item.get("severity") in {"critical", "warning"}}
    offense_state = str((offense_coverage or {}).get("state") or "")
    primary_offense = metrics.get("primary_offense") or {}
    delta_kind = str(primary_offense.get("delta_kind") or "MEASURED")
    candidate_block = recommendation.get("candidate") or {}
    same_skill_zero = (
        delta_kind == "MEASURED_ZERO"
        and candidate_block.get("item_present") is True
        and bool((recommendation.get("baseline") or {}).get("primary_skill"))
        and bool(candidate_block.get("primary_skill"))
        and offense_delta_comparable(
            recommendation, primary_offense,
            primary_field=str(primary_offense.get("pob_field") or primary_metric.get("pob_field") or "CombinedDPS"),
            primary_confidence=str(primary_metric.get("confidence") or "high"),
        )
    )

    compact_notes: list[str] = []
    candidates: list[dict[str, Any]] = []
    for key in ROW_PRIORITY:
        metric = metrics.get(key)
        if not metric or metric.get("availability") == "missing":
            continue
        cap_state = None
        if key.endswith("_res"):
            element = key.replace("_res", "")
            resist_info = (resist.get("elements") or {}).get(element) or {}
            cap_state = resist_info.get("state")
            if cap_state not in DISPLAYED_CAP_STATES:
                cap_state = None
            metric = {
                **metric,
                "uncapped_current": resist_info.get("uncapped_current"),
                "uncapped_candidate": resist_info.get("uncapped_candidate"),
                "cap_current": resist_info.get("cap_current"),
                "cap_candidate": resist_info.get("cap_candidate"),
            }
        abs_delta = float(metric.get("absolute_delta") or 0)
        pct = metric.get("percent_delta")
        stable = _is_stable(abs_delta, pct)
        forced = key in forced_keys or cap_state in {"CAP_LOST", "CAP_REACHED", "BELOW_CAP_WORSENED"}
        if key == "ehp" and _major_loss(abs_delta, pct):
            forced = True
        if key == "worst_max_hit" and _major_loss(abs_delta, pct):
            forced = True
        if key == "primary_offense" and stable and key not in forced_keys:
            if offense_claim_allowed(offense_coverage, delta_kind=delta_kind) or same_skill_zero:
                compact_notes.append("Damage stable")
            elif offense_comparison_limited(offense_coverage, delta_kind=delta_kind):
                compact_notes.append("Offense comparison limited")
            continue
        if key == "primary_offense" and delta_kind in {"UNMEASURED", "UNSUPPORTED", "MISSING"}:
            # A number PoB printed for an unverified metric is not the build's damage.
            compact_notes.append("Damage not measured")
            continue
        if key == "primary_offense" and delta_kind == "ESTIMATED":
            metric = {**metric, "label": f"{metric.get('label') or 'Damage'} (estimate)"}
        if not is_display_worthy(key=key, absolute_delta=abs_delta, percent_delta=pct, forced=forced):
            if cap_state in {"BELOW_CAP_WORSENED", "BELOW_CAP_UNCHANGED", "FURTHER_BELOW_CAP", "STILL_BELOW_CAP"} and abs(abs_delta) >= 0.5:
                pass
            else:
                continue
        emphasis = _row_emphasis(
            key=key,
            cap_state=cap_state,
            abs_delta=abs_delta,
            pct=pct,
            forced_critical=key in forced_keys,
            warning=key in warning_keys,
        )
        candidates.append(
            {
                "key": key,
                "label": metric.get("label") or key,
                "absolute_delta": abs_delta,
                "percent_delta": None if pct is None else float(pct),
                "delta_text": format_metric_delta(metric),
                "range_text": format_current_candidate(metric),
                "direction": metric.get("direction"),
                "importance": metric.get("importance"),
                "emphasis": emphasis,
                "cap_state": cap_state,
                "cap_label": CAP_STATE_LABELS.get(cap_state or "", ""),
                "warning": key in warning_keys,
                "delta_kind": delta_kind if key == "primary_offense" else "MEASURED",
            }
        )

    rows = _select_rows(candidates, max_rows=row_limit)

    why_block = []
    if decision_enabled and decision:
        for item in decision.get("why_reasons") or []:
            why_block.append(
                {
                    "explanation": item.get("explanation"),
                    "severity": item.get("severity"),
                    "code": item.get("code"),
                    "category": item.get("category"),
                }
            )
        why_block = why_block[:4 if density == PopupDensity.COMPACT else 6]

    profile_row = []
    if multi_profile_enabled and multi_profile:
        for key in multi_profile.get("profile_order") or []:
            info = (multi_profile.get("profiles") or {}).get(key) or {}
            if info.get("rating") is None:
                continue
            profile_row.append(
                {
                    "profile": key,
                    "label": key[:3].title(),
                    "rating": info.get("rating"),
                    "rating_text": f"{float(info['rating']):.0f}",
                    "verdict": info.get("verdict"),
                    "active": key == value_profile,
                }
            )

    best_slot_headline = ""
    if best_slot_enabled:
        best_slot_headline = str(best_slot.get("label") or decision.get("best_slot_label") or "")

    warning_views = [_warning_view(item) for item in warnings if item.get("severity") in {"critical", "warning"}]

    badges = []
    flags = []
    confidence = str(decision.get("confidence") or "").upper()
    if confidence == "LOW":
        flags.append("LOW_CONFIDENCE_EVAL")
        badges.append({"id": "low_confidence", "label": "Low confidence", "emphasis": "muted"})
    if decision.get("build_repair"):
        badges.append({"id": "build_repair", "label": "BUILD REPAIR", "emphasis": "high"})
    if offense_state in {"LIMITED", "UNAVAILABLE", "INSENSITIVE"}:
        flags.append("OFFENSE_COVERAGE_LIMITED")
        badges.append(
            {
                "id": "offense_coverage_limited",
                "label": "OFFENSE COVERAGE LIMITED",
                "emphasis": "muted",
            }
        )
    elif primary_metric.get("low_confidence") or primary_metric.get("confidence") == "low":
        flags.append("LOW_CONFIDENCE_OFFENSE")
        if not any(item.get("id") == "offense_coverage_limited" for item in badges):
            badges.append(
                {
                    "id": "low_confidence",
                    "label": "OFFENSE COVERAGE LIMITED",
                    "emphasis": "muted",
                }
            )
    if primary_metric.get("selected") == "UNRESOLVED":
        flags.append("OFFENSE_UNRESOLVED")

    price_block = _build_price_block(result, power=power, value_profile=value_profile)

    intel = result.get("build_comparison") or recommendation.get("build_comparison") or {}
    intel_axes = _axis_rows(intel)
    intel_mods = list((intel.get("explanation") or {}).get("mod_contributions") or [])
    intel_tradeoffs = list((intel.get("explanation") or {}).get("tradeoffs") or [])
    intel_hard = list((intel.get("explanation") or {}).get("hard_problems") or [])
    slot_options = _slot_options(result, intel)
    slot_alternate_line = str(slot_options.get("compact_line") or "")

    verdict = str(intel.get("product_verdict") or recommendation.get("verdict") or "UNRESOLVED")
    ranking_verdict = recommendation.get("verdict") or "UNRESOLVED"
    if ranking_verdict == "NO_CHANGE" and str(intel.get("product_verdict") or "") not in {"BUILD_FIX", "BLOCKED", "UNSAFE"}:
        verdict = ranking_verdict
        verdict_label = verdict_headline(ranking_verdict, decision)
    else:
        verdict_label = str((intel.get("explanation") or {}).get("headline") or "") or verdict_headline(ranking_verdict, decision)
    recommendation_tag = recommendation_tag_display(
        verdict_label,
        str(decision.get("recommendation_tag") or ""),
    )
    # The EvaluationOutcome is the one player-facing verdict. Ranking / product
    # verdicts and the ranking-derived style tag stay internal once it exists.
    outcome = dict(recommendation.get("evaluation_outcome") or {})
    if outcome:
        verdict = str(outcome.get("verdict") or verdict)
        verdict_label = str(outcome.get("verdict_label") or verdict_label)
        recommendation_tag = ""
    outcome_failed = bool(outcome) and outcome.get("final_score") is None
    if (
        intel.get("score_delta") is not None
        and not outcome_failed
        and verdict not in {"SIDEGRADE", "NO_CHANGE", "UNRESOLVED"}
    ):
        try:
            recommendation_tag = recommendation_tag or f"Build Value {float(intel['score_delta']):+.1f}"
        except (TypeError, ValueError):
            pass
    verdict_explanation = verdict_subtitle(ranking_verdict, decision, recommendation)
    if intel.get("explanation"):
        intel_reasons = list((intel.get("explanation") or {}).get("improvements") or [])
        if not intel_reasons:
            intel_reasons = list((intel.get("explanation") or {}).get("primary_reasons") or [])
        rebuilt = [
            {
                "explanation": item.get("text") or item.get("detail") or item.get("explanation"),
                "severity": "positive",
                "code": item.get("code"),
                "category": "INTEL",
            }
            for item in intel_reasons[: 4 if density == PopupDensity.COMPACT else 6]
            if item.get("text") or item.get("detail") or item.get("explanation")
        ]
        if rebuilt:
            why_block = rebuilt
        if intel_reasons:
            verdict_explanation = " · ".join(
                str(item.get("text") or item.get("detail") or "")
                for item in intel_reasons[:2]
                if item.get("text") or item.get("detail")
            ) or verdict_explanation
    value_block = None
    if value and not outcome_failed:
        rating = value.get("rating")
        profile_name = str(value.get("profile") or value_profile).replace("_", " ").title()
        value_block = {
            "profile": value.get("profile") or value_profile,
            "profile_label": profile_name,
            "rating": rating,
            "rating_text": f"{rating:.0f} / 100" if rating is not None else "",
            "score_delta": value.get("score_delta"),
            "drivers": value.get("drivers") or [],
            "guardrails": value.get("guardrails") or [],
        }

    score_delta = (value_block or {}).get("score_delta")
    if score_delta is None:
        score_delta = intel.get("score_delta")

    show_warnings = bool(warning_views) and density != PopupDensity.COMPACT
    show_value = (bool(value_block and value_block.get("rating") is not None) or bool(price_block)) and density != PopupDensity.COMPACT

    upgrade_path = result.get("upgrade_path") or {}
    potential = result.get("upgrade_potential") or {}
    offense_summary = _build_offense_summary(offense_coverage, compact_notes)
    if native_discovery.get("damage_scope") == "PARTIAL" and native_discovery.get("components"):
        compact_notes.append("Partial damage: separate PoB skills")
    current_edge = _build_current_edge(ranking_verdict, upgrade_path, potential)
    best_use = _build_best_use(multi_profile) if multi_profile_enabled else None
    build_fixes = _build_build_fix_lines(decision, resist, ranking_verdict)
    intel_fix_lines = [
        str(item.get("text") or item.get("detail") or "")
        for item in (intel.get("explanation") or {}).get("build_fixes") or []
    ]
    if intel_fix_lines:
        build_fixes = [line if line.startswith("✓") else f"✓ {line}" for line in intel_fix_lines if line][:3]
    risk_summary = derive_swap_risk(
        {**recommendation, "upgrade_potential": potential or {"repair_vector": upgrade_path.get("repair_steps") or []}},
        decision=decision,
        offense_coverage=offense_coverage,
    )

    why_not_upgrade = list(upgrade_path.get("why_not_upgrade") or [])
    if not why_not_upgrade and decision_enabled and decision:
        for item in decision.get("keep_current_reasons") or []:
            why_not_upgrade.append(
                {
                    "explanation": item.get("explanation"),
                    "severity": item.get("severity"),
                    "code": item.get("code"),
                }
            )
    if current_edge:
        why_not_upgrade = [
            item
            for item in why_not_upgrade
            if not str(item.get("code") or "").startswith("KEEP_CURRENT")
        ]

    warning_views, why_block, why_not_upgrade, compact_notes = apply_presentation_dedupe(
        rows=rows,
        warnings=warning_views,
        why_reasons=why_block,
        why_not_upgrade=why_not_upgrade,
        current_edge=current_edge,
        offense_summary=offense_summary,
        compact_notes=compact_notes,
        upgrade_path=upgrade_path,
    )
    warning_views = dedupe_warnings(warning_views, rows, why_block, why_not_upgrade)
    why_not_upgrade = dedupe_reason_blocks(why_not_upgrade, rows=rows, other_blocks=why_block)
    warning_groups = _group_warnings(warning_views)

    why_title = why_section_title(ranking_verdict, decision, upgrade_path)
    show_why_not = should_show_why_not_section(
        ranking_verdict,
        decision,
        upgrade_path,
        why_not_upgrade,
        current_edge=current_edge,
    )

    sections = [
        {"id": "header", "visible": True},
        {"id": "baseline", "visible": bool(baseline_line or value_profile)},
        {"id": "best_slot", "visible": bool(best_slot_headline)},
        {"id": "metrics", "visible": bool(rows or compact_notes)},
        {"id": "offense_summary", "visible": bool(offense_summary)},
        {"id": "current_edge", "visible": bool(current_edge)},
        {"id": "axes", "visible": bool(intel_axes)},
        {"id": "why", "visible": bool(why_block)},
        {"id": "best_use", "visible": bool(best_use)},
        {"id": "build_fixes", "visible": bool(build_fixes)},
        {"id": "tradeoffs", "visible": bool(intel_tradeoffs)},
        {"id": "important_mods", "visible": bool(intel_mods)},
        {"id": "multi_profile", "visible": bool(profile_row) and density != PopupDensity.COMPACT},
        {"id": "warnings", "visible": show_warnings},
        {"id": "verdict", "visible": True},
        {"id": "value", "visible": show_value or density == PopupDensity.COMPACT and bool(value_block)},
        {"id": "why_not_upgrade", "visible": show_why_not},
        {"id": "upgrade_path", "visible": bool(upgrade_path)},
        {"id": "risk_summary", "visible": bool(risk_summary)},
    ]

    return {
        "item_name": name,
        "base_type": base_type,
        "rarity": rarity,
        "baseline_line": baseline_line,
        "baseline_meta": baseline_meta,
        "pob_baseline_label": pob_baseline_label,
        "compared_against": compared_against,
        "baseline_item": baseline_item,
        "profile_indicator": value_profile,
        "context": context,
        "loadout_name": loadout_name,
        "build_name": build_name,
        "item_set_name": item_set_name,
        "rows": rows,
        "compact_notes": compact_notes,
        "warnings": warning_views,
        "warning_groups": warning_groups,
        "verdict": verdict,
        "verdict_label": verdict_label,
        "verdict_class": str(outcome.get("verdict_class") or ""),
        "verdict_reason": str(outcome.get("verdict_reason") or ""),
        "evaluation_outcome": outcome,
        "evaluation_quality": str(outcome.get("evaluation_quality") or ""),
        "quality_label": str(outcome.get("quality_label") or ""),
        "recommendation_tag": recommendation_tag,
        "verdict_explanation": verdict_explanation,
        "why_section_title": why_title or "",
        "verdict_emphasis": VERDICT_EMPHASIS.get(verdict, "medium"),
        "decision": decision,
        "why_reasons": why_block,
        "best_slot_headline": best_slot_headline,
        "multi_profile_row": profile_row,
        "popup_density": density.value,
        "value": value_block,
        "price": price_block,
        "flags": flags,
        "badges": badges,
        "sections": sections,
        "section_ids": [item["id"] for item in sections if item["visible"]],
        "max_rows": row_limit,
        "row_count": len(rows),
        "upgrade_path": upgrade_path,
        "why_not_upgrade": why_not_upgrade if show_why_not else [],
        "confidence": confidence,
        "confidence_reasons": list(decision.get("confidence_reasons") or []),
        "offense_coverage": offense_coverage,
        "offense_summary": offense_summary,
        "current_edge": current_edge,
        "best_use": best_use,
        "build_fixes": build_fixes,
        "risk_summary": risk_summary,
        "axis_rows": intel_axes,
        "important_mods": intel_mods[:4],
        "tradeoff_lines": intel_tradeoffs[:3],
        "hard_problems": intel_hard[:3],
        "slot_options": slot_options,
        "slot_alternate_line": slot_alternate_line,
        "replacement_choices": list(slot_options.get("options") or []),
        "intel_confidence": intel.get("confidence") or confidence,
        "decomposition_status": str(intel.get("decomposition_status") or ""),
        "profile_note": str((intel.get("explanation") or {}).get("profile_note") or ""),
        "product_verdict": intel.get("product_verdict") or "",
        "ranking_verdict": ranking_verdict,
        "score_delta": score_delta,
        "primary_metric": primary_metric,
        "native_damage_discovery": native_discovery,
        "damage_scope": native_discovery.get("damage_scope") or "",
    }


# --------------------------------------------------------------- surface policy
#
# `ui/overlay_aux_policy` binds to these by name. They are the passive overlay's
# product behaviour: what the primary tooltip says, and what the Companion card
# carries instead. See that module's docstring for why the seam exists.


def build_presentation_for_surface(
    result: dict[str, Any],
    *,
    surface: SurfaceMode | str = SurfaceMode.PASSIVE_COMPACT,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Presentation for one product surface, or None to let the caller fall back."""
    mode = surface.value if isinstance(surface, SurfaceMode) else str(surface or "")
    if mode != SurfaceMode.PASSIVE_COMPACT.value:
        return None
    kwargs.pop("popup_density", None)
    # STANDARD, not COMPACT: the compact tooltip picks its own 3-5 rows, and the
    # Companion wants the wider set of measured metrics behind them.
    model = build_presentation(result, popup_density=PopupDensity.STANDARD.value, **kwargs)
    model["surface_mode"] = SurfaceMode.PASSIVE_COMPACT.value
    apply_passive_aux_companion_policy(model)
    return model


def should_show_passive_aux_companion(presentation: dict[str, Any]) -> bool:
    """Legacy auto-companion is disabled; detail opens on demand in the tooltip drawer."""
    return False


def has_passive_detail_drawer(presentation: dict[str, Any]) -> bool:
    """Whether More info can offer the detailed analysis drawer."""
    if str(presentation.get("surface_mode") or "") != SurfaceMode.PASSIVE_COMPACT.value:
        return False
    more_info = presentation.get("more_info") or {}
    if more_info.get("sections"):
        return True
    companion = presentation.get("companion") or {}
    return bool(companion.get("sections"))


def sync_presentation_current_edge(presentation: dict[str, Any], result: dict[str, Any]) -> None:
    """Compress a presentation that arrived pre-built on the result payload.

    `build_presentation` may already have run upstream, in which case the passive
    overlay receives a full model rather than building one. It still has to reach the
    compact surface, and its Companion payload still has to be built.
    """
    if presentation.get("compact_surface"):
        return
    if presentation.get("score_delta") is None:
        intel = result.get("build_comparison") or (result.get("recommendation") or {}).get("build_comparison") or {}
        delta = (presentation.get("value") or {}).get("score_delta")
        if delta is None:
            delta = intel.get("score_delta")
        presentation["score_delta"] = delta
    apply_passive_aux_companion_policy(presentation)


def build_passive_aux_trace(
    presentation: dict[str, Any],
    result: dict[str, Any],
    *,
    overlay_generation: int,
    aux_visible: bool,
    aux_show_called: bool,
    aux_visible_after_show: bool,
) -> dict[str, Any]:
    companion = presentation.get("companion") or {}
    return {
        "aux_policy": "item_pro",
        "overlay_generation": overlay_generation,
        "aux_visible": aux_visible,
        "aux_show_called": aux_show_called,
        "aux_visible_after_show": aux_visible_after_show,
        "compact_surface": bool(presentation.get("compact_surface")),
        "companion_sections": list(companion.get("section_ids") or []),
        "impact_rows": [str(row.get("key")) for row in presentation.get("impact_rows") or []],
        "score": presentation.get("score_value"),
        "verdict": presentation.get("verdict"),
    }


_PROFILE_DISPLAY_LABELS = {
    "BALANCED": "Balanced",
    "MAPPING": "Mapping",
    "BOSSING": "Bossing",
    "DEFENSIVE": "Defensive",
}
_CLEAN_UPGRADE_VERDICTS = frozenset({"STRONG_UPGRADE", "CLEAR_UPGRADE", "OFFENSE_UPGRADE", "DEFENSE_UPGRADE"})
_BUILD_FIX_STATES = frozenset({"CAP_REACHED", "CAP_GAINED", "BELOW_CAP_IMPROVED"})


def _build_price_block(
    result: dict[str, Any],
    *,
    power: dict[str, Any] | None,
    value_profile: str,
) -> dict[str, Any] | None:
    market_ctx = result.get("market_context") or {}
    parsed = market_ctx.get("parsed_price") or {}
    parsed_price = parsed.get("price") if isinstance(parsed, dict) else None
    manual = result.get("manual_price") or (power or {}).get("price") or {}
    amount = None
    currency = None
    source = ""
    label_prefix = "Price"

    if market_ctx.get("active_session") and parsed_price:
        amount = parsed_price.get("amount")
        currency = parsed_price.get("currency")
        source = "market"
        label_prefix = "MARKET PRICE"
    elif parsed_price:
        amount = parsed_price.get("amount")
        currency = parsed_price.get("currency")
        source = "note"
        label_prefix = "PRICE NOTE"
    elif power and manual:
        amount = manual.get("amount")
        currency = manual.get("currency")
        source = "manual"

    if amount is None or not currency:
        return None

    block: dict[str, Any] = {
        "source": source,
        "label_prefix": label_prefix,
        "amount": amount,
        "currency": currency,
        "label": f"{amount:g} {currency}",
        "classification": (power or {}).get("classification"),
        "classification_label": str((power or {}).get("classification") or "").replace("_", " ").title(),
        "power_per_currency": (power or {}).get("power_per_currency"),
        "profile": value_profile,
    }
    if source == "market":
        block["session_rank"] = market_ctx.get("session_rank")
        block["session_total"] = market_ctx.get("session_total")
        block["is_best_value"] = bool(market_ctx.get("is_best_value"))
        block["is_new_best"] = bool(market_ctx.get("is_new_best"))
    return block


def _build_offense_summary(offense_coverage: dict[str, Any] | None, compact_notes: list[str]) -> str:
    coverage = offense_coverage or {}
    state = str(coverage.get("state") or "")
    if state in {
        OffenseCoverageState.LIMITED.value,
        OffenseCoverageState.UNAVAILABLE.value,
        OffenseCoverageState.INSENSITIVE.value,
        OffenseCoverageState.PARTIAL.value,
    }:
        return "Limited coverage"
    if any("Offense comparison limited" in note for note in compact_notes):
        return "Limited coverage"
    if state == OffenseCoverageState.FULL.value and coverage.get("offense_trustworthy"):
        return ""
    return ""


def _build_current_edge(verdict: str, upgrade_path: dict[str, Any], potential: dict[str, Any]) -> dict[str, Any] | None:
    if verdict in _CLEAN_UPGRADE_VERDICTS:
        return None
    repair_steps = list(upgrade_path.get("repair_steps") or [])
    if not repair_steps:
        repair_steps = build_repair_steps(list(potential.get("repair_vector") or []))
    lines = [str(item.get("line") or "") for item in repair_steps if item.get("line")]
    if not lines:
        return None
    return {"title": "WHY CURRENT WINS", "lines": lines[:3]}


def _build_best_use(multi_profile: dict[str, Any]) -> dict[str, Any] | None:
    profiles = multi_profile.get("profiles") or {}
    order = multi_profile.get("profile_order") or list(profiles.keys())
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for key in order:
        info = profiles.get(key) or {}
        rating = info.get("rating")
        if rating is None:
            continue
        ranked.append((float(rating), str(key), info))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    best_rating, best_key, _ = ranked[0]
    label = _PROFILE_DISPLAY_LABELS.get(best_key, best_key.replace("_", " ").title())
    result: dict[str, Any] = {
        "profile": best_key,
        "label": label,
        "rating": best_rating,
        "headline": f"{label} {best_rating:.0f}",
    }
    if len(ranked) > 1:
        runner_rating, runner_key, _ = ranked[1]
        if best_rating - runner_rating <= 6:
            runner_label = _PROFILE_DISPLAY_LABELS.get(runner_key, runner_key.replace("_", " ").title())
            result["runner_up"] = {"profile": runner_key, "label": runner_label, "rating": runner_rating}
    return result


def _build_build_fix_lines(decision: dict[str, Any], resist: dict[str, Any], verdict: str) -> list[str]:
    if verdict in {"DOWNGRADE", "STRONG_DOWNGRADE"} and not decision.get("build_repair"):
        return []
    fixes: list[str] = []
    seen: set[str] = set()
    for item in decision.get("why_reasons") or []:
        code = str(item.get("code") or "")
        direction = str(item.get("direction") or "")
        if direction != "up" and code not in {"RES_CAP_REACHED", "BELOW_CAP_IMPROVED", "RES_DEFICIT_IMPROVED"}:
            continue
        if code == "BUILD_REPAIR":
            continue
        explanation = str(item.get("explanation") or "").strip()
        if not explanation or explanation in seen:
            continue
        seen.add(explanation)
        fixes.append(explanation if explanation.startswith("✓") else f"✓ {explanation}")
    for element, info in (resist.get("elements") or {}).items():
        state = str((info or {}).get("state") or "")
        if state not in _BUILD_FIX_STATES:
            continue
        text = f"✓ {element.replace('_', ' ').title()} cap restored"
        if text not in seen:
            seen.add(text)
            fixes.append(text)
    return fixes[:3]


def _is_stable(abs_delta: float, pct: float | None) -> bool:
    if abs(abs_delta) > ZERO_ABS:
        return False
    if pct is not None and abs(float(pct)) > ZERO_PCT:
        return False
    return True


def _major_loss(abs_delta: float, pct: float | None) -> bool:
    if abs_delta >= 0:
        return False
    if pct is not None:
        return abs(float(pct)) >= MAJOR_DEFENSE_LOSS_PCT
    return abs(abs_delta) >= 1


def _row_emphasis(
    *,
    key: str,
    cap_state: str | None,
    abs_delta: float,
    pct: float | None,
    forced_critical: bool,
    warning: bool,
) -> str:
    if forced_critical or cap_state == "CAP_LOST":
        return "critical"
    if cap_state in CAP_STATE_EMPHASIS:
        return CAP_STATE_EMPHASIS[cap_state]
    if key in {"ehp", "worst_max_hit"} and _major_loss(abs_delta, pct):
        return "critical"
    if warning and abs_delta < 0:
        return "high"
    if key == "primary_offense" and not _is_stable(abs_delta, pct):
        return "high"
    if key in {"ehp", "worst_max_hit", "life", "energy_shield"}:
        return "medium"
    return "medium"


def _select_rows(candidates: list[dict[str, Any]], *, max_rows: int = MAX_NORMAL_ROWS) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda row: (
            EMPHASIS_RANK.get(str(row.get("emphasis")), 9),
            PRIORITY_INDEX.get(str(row.get("key")), 99),
        ),
    )
    selected: list[dict[str, Any]] = []
    for row in ordered:
        if len(selected) < max_rows:
            selected.append(row)
            continue
        if row.get("emphasis") == "critical":
            for index, existing in enumerate(selected):
                if existing.get("emphasis") != "critical":
                    selected[index] = row
                    break
    selected.sort(key=lambda row: PRIORITY_INDEX.get(str(row.get("key")), 99))
    return selected


def _warning_view(item: dict[str, Any]) -> dict[str, Any]:
    severity = item.get("severity") or "warning"
    return {
        "code": item.get("code"),
        "severity": severity,
        "text": _warning_text(item),
        "metric": item.get("metric"),
        "emphasis": "critical" if severity == "critical" or item.get("code") in CRITICAL_WARNING_CODES else "high",
    }


def _group_warnings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    critical = [item for item in items if item.get("severity") == "critical"]
    warning = [item for item in items if item.get("severity") != "critical"]
    if critical:
        groups.append({"severity": "critical", "title": "CRITICAL", "items": critical})
    if warning:
        groups.append({"severity": "warning", "title": "WARNING", "items": warning})
    return groups


def _warning_text(item: dict[str, Any]) -> str:
    code = item.get("code")
    metric = str(item.get("metric") or "")
    element = metric.replace("_res", "").replace("_", " ").title() if metric.endswith("_res") else ""
    mapping = {
        "RES_CAP_LOST": f"{element} cap lost" if element else "CAP LOST",
        "RES_DEFICIT_WORSENED": (
            f"{element} already below cap → worse"
            if element
            else "Already below cap → worse"
        )
        + (
            f"\n{item.get('before')} → {item.get('after')}"
            if item.get("before") is not None and item.get("after") is not None
            else ""
        ),
        "EHP_DOWN": "EHP decreased",
        "MAX_HIT_DOWN": "Max hit decreased",
        "LIFE_DOWN": "Life decreased",
        "ENERGY_SHIELD_DOWN": "Energy shield decreased",
        "CHAOS_RES_WORSE": "Chaos resistance worse",
        "MOVEMENT_LOSS": "Movement speed decreased",
        "RESOURCE_FAILURE": "Resource failure",
        "MAIN_SKILL_INVALID": "Main skill invalid",
        "BUILD_INVALID": "Build invalid",
    }
    if code == "RES_CAP_LOST":
        return mapping["RES_CAP_LOST"]
    if code == "RES_DEFICIT_WORSENED":
        return mapping["RES_DEFICIT_WORSENED"]
    return mapping.get(code, item.get("detail") or str(code))


def _axis_rows(intel: dict[str, Any]) -> list[dict[str, Any]]:
    axes = intel.get("axes") or {}
    rows: list[dict[str, Any]] = []
    for key, label in (
        ("OFFENSE", "Offense"),
        ("DEFENCE", "Defense"),
        ("RECOVERY", "Recovery"),
        ("RESOURCE", "Resource"),
        ("MOBILITY", "Mobility"),
    ):
        axis = axes.get(key) or {}
        kind = str(axis.get("delta_kind") or "MEASURED")
        pct = axis.get("percent_delta") if isinstance(axis, dict) else None
        if kind in {"UNMEASURED", "UNSUPPORTED"}:
            rows.append({"axis": key, "label": label, "text": f"{label:<12}unmeasured", "kind": kind})
            continue
        if kind == "ESTIMATED" and pct is not None:
            rows.append(
                {"axis": key, "label": label, "text": f"{label:<12}~{float(pct):+.1f}% (estimate)", "kind": kind}
            )
            continue
        if pct is None:
            continue
        rows.append(
            {
                "axis": key,
                "label": label,
                "text": f"{label:<12}{float(pct):+.1f}%",
                "percent_delta": float(pct),
                "kind": kind,
                "range_text": _axis_range(axis),
            }
        )
    return rows


def _axis_range(axis: dict[str, Any]) -> str:
    current = axis.get("current")
    candidate = axis.get("candidate")
    if current is None or candidate is None:
        return ""
    return f"{current} → {candidate}"


def _choice_from_outcome(
    slot: str,
    outcome: dict[str, Any],
    *,
    selected: bool,
    comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verdict = str(outcome.get("verdict") or "")
    score = outcome.get("final_score")
    empty = bool(outcome.get("replacing_empty_slot"))
    if comparison is not None:
        baseline_item = comparison.get("baseline_item") or {}
        empty = empty or bool(baseline_item.get("empty"))
    replacing_item = str(outcome.get("replacing_item") or "")
    if not replacing_item and comparison is not None:
        baseline_item = comparison.get("baseline_item") or {}
        replacing_item = str(baseline_item.get("display_name") or baseline_item.get("name") or "")
    return {
        "slot": slot,
        "verdict": verdict,
        "verdict_label": str(outcome.get("verdict_label") or _verdict_words(verdict)),
        "final_score": score,
        "rating_text": f"{float(score):.0f}" if score is not None else "",
        "selected": selected,
        "best": selected,
        "blocked": verdict in {"NOT_VIABLE", "NOT_EVALUATED", "UNSUPPORTED"},
        "empty": empty,
        "replacing_empty_slot": empty,
        "replacing_item": replacing_item,
        "evaluation_outcome": {
            **(dict(outcome) if outcome else {}),
            "replacement_slot": slot,
            "replacing_item": replacing_item,
            "replacing_empty_slot": empty,
        },
    }


def _slot_options(result: dict[str, Any], intel: dict[str, Any]) -> dict[str, Any]:
    comparisons = list(result.get("slot_comparisons") or [])
    if len(comparisons) < 2:
        notes = list(intel.get("slot_notes") or [])
        if len(notes) < 2:
            return {}
        options = []
        parts = []
        for note in notes:
            selected = bool(note.get("selected"))
            score = note.get("final_score")
            verdict = str(note.get("verdict") or note.get("product_verdict") or "")
            empty = bool(note.get("empty") or note.get("replacing_empty_slot"))
            options.append(
                {
                    "slot": note.get("pob_slot"),
                    "verdict": verdict,
                    "verdict_label": _verdict_words(verdict),
                    "final_score": score,
                    "rating_text": f"{float(score):.0f}" if score is not None else "",
                    "selected": selected,
                    "best": selected,
                    "blocked": bool(note.get("blocked")),
                    "empty": empty,
                    "replacing_empty_slot": empty,
                    "replacing_item": str(note.get("replacing_item") or ""),
                    "evaluation_outcome": dict(note.get("evaluation_outcome") or {}),
                }
            )
            marker = "→" if selected else " "
            label = "Equip to empty slot" if empty else _verdict_words(verdict)
            parts.append(f"{marker} {note.get('pob_slot')}: {label}")
        return {"title": "SLOT OPTIONS", "options": options, "compact_line": " · ".join(parts)}
    options = []
    parts = []
    selected_slot = str((result.get("recommendation") or {}).get("pob_slot") or "")
    for comparison in comparisons:
        slot = str(comparison.get("pob_slot") or "")
        outcome = dict(comparison.get("evaluation_outcome") or {})
        choice = _choice_from_outcome(slot, outcome, selected=slot == selected_slot, comparison=comparison)
        options.append(choice)
        label = "Equip to empty slot" if choice["empty"] else choice["verdict_label"]
        parts.append(f"{slot}: {label}")
    for failed in result.get("failed_slot_outcomes") or []:
        slot = str(failed.get("replacement_slot") or "")
        choice = _choice_from_outcome(slot, failed, selected=False)
        options.append(choice)
        parts.append(f"{slot}: {choice['verdict_label'] or _verdict_words(choice['verdict'])}")
    compact = " · ".join(parts)
    return {"title": "SLOT OPTIONS", "options": options, "compact_line": compact}


def _verdict_words(verdict: str) -> str:
    return str(verdict or "").replace("_", " ")
