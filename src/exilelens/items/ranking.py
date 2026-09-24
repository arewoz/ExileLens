from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from exilelens.items.consequences import build_warnings
from exilelens.items.display_thresholds import DEFAULT_DISPLAY_THRESHOLDS
from exilelens.items.evaluation_outcome import (
    authoritative_public_verdict,
    build_evaluation_outcome,
    sync_value_with_outcome,
)
from exilelens.items.native_metric_discovery import promote_unresolved_primary_with_component
from exilelens.items.offense_coverage import (
    apply_offense_coverage_to_profile,
    apply_primary_skill_guard,
    clamp_primary_offense_noise,
    promote_pob_measured_offense_delta,
)
from exilelens.items.price import ManualPrice, compute_power_per_currency
from exilelens.items.resist_caps import analyze_resistances
from exilelens.items.value_profiles import ValueProfile, score_profile
from exilelens.metrics import build_metric_profile

def _rank_guardrail_first(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from exilelens.items.best_slot import rank_comparisons_guardrail_first

    return rank_comparisons_guardrail_first(ranked)


class Verdict(str, Enum):
    STRONG_UPGRADE = "STRONG_UPGRADE"
    CLEAR_UPGRADE = "CLEAR_UPGRADE"
    OFFENSE_UPGRADE = "OFFENSE_UPGRADE"
    DEFENSE_UPGRADE = "DEFENSE_UPGRADE"
    TRADEOFF = "TRADEOFF"
    SIDEGRADE = "SIDEGRADE"
    DOWNGRADE = "DOWNGRADE"
    STRONG_DOWNGRADE = "STRONG_DOWNGRADE"
    UNRESOLVED = "UNRESOLVED"
    NO_CHANGE = "NO_CHANGE"


@dataclass(frozen=True)
class RankingThresholds:
    offense_percent: float = 1.0
    defense_percent: float = 1.0
    sidegrade_percent: float = 0.25
    strong_offense_percent: float = 8.0
    strong_defense_percent: float = 8.0
    clear_offense_percent: float = 3.0
    major_defense_loss_percent: float = 6.0


DEFAULT_THRESHOLDS = RankingThresholds()

_VERDICT_ORDER = {
    Verdict.STRONG_UPGRADE.value: 0,
    Verdict.CLEAR_UPGRADE.value: 1,
    Verdict.OFFENSE_UPGRADE.value: 2,
    Verdict.DEFENSE_UPGRADE.value: 3,
    Verdict.SIDEGRADE.value: 4,
    Verdict.NO_CHANGE.value: 5,
    Verdict.TRADEOFF.value: 6,
    Verdict.UNRESOLVED.value: 7,
    Verdict.DOWNGRADE.value: 8,
    Verdict.STRONG_DOWNGRADE.value: 9,
}


def _metric_delta(profile: dict[str, Any], key: str) -> tuple[float, float | None]:
    metric = profile.get(key, {})
    abs_delta = metric.get("absolute_delta")
    if abs_delta is None:
        abs_delta = 0.0
    return float(abs_delta), metric.get("percent_delta")


def _material_up(abs_delta: float, pct: float | None, threshold: float) -> bool:
    if abs_delta <= 0:
        return False
    if pct is None:
        return True
    return pct >= threshold


def _material_down(abs_delta: float, pct: float | None, threshold: float) -> bool:
    if abs_delta >= 0:
        return False
    if pct is None:
        return True
    return pct <= -threshold


def classify_verdict_v2(
    profile: dict[str, Any],
    warnings: list[dict[str, Any]] | None = None,
    *,
    thresholds: RankingThresholds = DEFAULT_THRESHOLDS,
) -> tuple[Verdict, list[str], str]:
    warnings = warnings or []
    codes = {item.get("code") for item in warnings}
    offense_abs, offense_pct = _metric_delta(profile, "primary_offense")
    ehp_abs, ehp_pct = _metric_delta(profile, "ehp")
    life_abs, _ = _metric_delta(profile, "life")
    es_abs, _ = _metric_delta(profile, "energy_shield")

    offense_up = _material_up(offense_abs, offense_pct, thresholds.offense_percent)
    offense_down = _material_down(offense_abs, offense_pct, thresholds.offense_percent)
    offense_strong_up = _material_up(offense_abs, offense_pct, thresholds.strong_offense_percent)
    offense_strong_down = _material_down(offense_abs, offense_pct, thresholds.strong_offense_percent)
    defense_up = (ehp_abs > 0 or life_abs > 0 or es_abs > 0) and (
        ehp_pct is None or ehp_pct >= thresholds.defense_percent or ehp_abs > 0
    )
    defense_down = (ehp_abs < 0 or life_abs < 0 or es_abs < 0) and (
        ehp_pct is None or ehp_pct <= -thresholds.defense_percent or ehp_abs < 0
    )
    defense_strong_up = _material_up(ehp_abs, ehp_pct, thresholds.strong_defense_percent)
    defense_strong_down = _material_down(ehp_abs, ehp_pct, thresholds.strong_defense_percent) or (
        ehp_pct is not None and ehp_pct <= -thresholds.major_defense_loss_percent
    )
    cap_lost = "RES_CAP_LOST" in codes
    deficit_worsened = "RES_DEFICIT_WORSENED" in codes
    skill_invalid = "MAIN_SKILL_INVALID" in codes or "BUILD_INVALID" in codes

    reasons: list[str] = []
    if offense_strong_up:
        reasons.append("Strong damage gain.")
    elif offense_up:
        reasons.append("Damage improves.")
    elif offense_strong_down:
        reasons.append("Severe damage loss.")
    elif offense_down:
        reasons.append("Damage decreases.")
    elif (profile.get("primary_offense") or {}).get("availability") == "missing" or (
        (profile.get("primary_offense") or {}).get("delta_kind") in {"MISSING", "UNMEASURED", "UNSUPPORTED", "ESTIMATED"}
    ):
        reasons.append("Damage could not be measured.")
    else:
        reasons.append("Damage is stable.")

    if defense_strong_up:
        reasons.append("Defenses improve substantially.")
    elif defense_up:
        reasons.append("Defenses improve.")
    elif defense_strong_down:
        reasons.append("Major defensive loss.")
    elif defense_down:
        reasons.append("Defenses drop.")
    else:
        reasons.append("Defenses stable.")

    if cap_lost:
        lost = next((item for item in warnings if item.get("code") == "RES_CAP_LOST"), None)
        metric = (lost or {}).get("metric", "resistance")
        label = str(metric).replace("_res", " resistance").replace("_", " ")
        reasons.append(f"{label[:1].upper() + label[1:]} cap lost.")
    elif deficit_worsened:
        worse = next((item for item in warnings if item.get("code") == "RES_DEFICIT_WORSENED"), None)
        metric = (worse or {}).get("metric", "resistance")
        label = str(metric).replace("_res", " resistance").replace("_", " ")
        reasons.append(f"EHP and max hit improve, but an already uncapped {label} gets worse." if ehp_abs > 0 else f"{label[:1].upper() + label[1:]} already below cap gets worse.")

    explanation = " ".join(reasons)

    if skill_invalid:
        return Verdict.STRONG_DOWNGRADE, reasons, explanation

    all_small = all(abs(value) <= thresholds.sidegrade_percent for value in (offense_abs, ehp_abs, life_abs, es_abs))
    if all_small and not cap_lost and not deficit_worsened:
        verdict = Verdict.NO_CHANGE if offense_abs == 0 and ehp_abs == 0 and life_abs == 0 and es_abs == 0 else Verdict.SIDEGRADE
        return verdict, reasons, explanation

    if cap_lost:
        if offense_up and not defense_strong_down:
            return Verdict.TRADEOFF, reasons, explanation
        if defense_down or not offense_up:
            return Verdict.DOWNGRADE if not offense_strong_down else Verdict.STRONG_DOWNGRADE, reasons, explanation
        return Verdict.TRADEOFF, reasons, explanation

    if offense_strong_up and defense_strong_up:
        verdict = Verdict.STRONG_UPGRADE
    elif offense_up and defense_up:
        verdict = Verdict.CLEAR_UPGRADE
    elif offense_up and not defense_down:
        verdict = Verdict.OFFENSE_UPGRADE
    elif defense_up and not offense_down:
        verdict = Verdict.DEFENSE_UPGRADE
    elif offense_strong_down and defense_strong_down:
        verdict = Verdict.STRONG_DOWNGRADE
    elif offense_down and defense_down:
        verdict = Verdict.DOWNGRADE
    elif (offense_up and defense_down) or (offense_down and defense_up):
        verdict = Verdict.TRADEOFF
    elif offense_up:
        verdict = Verdict.OFFENSE_UPGRADE
    elif defense_up:
        verdict = Verdict.DEFENSE_UPGRADE
    elif offense_down or defense_down:
        verdict = Verdict.DOWNGRADE
    else:
        verdict = Verdict.UNRESOLVED

    if deficit_worsened and verdict in {
        Verdict.STRONG_UPGRADE,
        Verdict.CLEAR_UPGRADE,
        Verdict.DEFENSE_UPGRADE,
        Verdict.OFFENSE_UPGRADE,
    }:
        verdict = Verdict.TRADEOFF
    return verdict, reasons, explanation


def classify_slot_comparison(
    profile: dict[str, Any],
    *,
    thresholds: RankingThresholds = DEFAULT_THRESHOLDS,
    warnings: list[dict[str, Any]] | None = None,
) -> Verdict:
    verdict, _, _ = classify_verdict_v2(profile, warnings, thresholds=thresholds)
    return verdict


def enrich_slot_comparison(
    comparison: dict[str, Any],
    *,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
    profile: ValueProfile = ValueProfile.BALANCED,
    price: ManualPrice | None = None,
    thresholds: RankingThresholds = DEFAULT_THRESHOLDS,
    offense_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if offense_coverage:
        comparison["offense_coverage"] = offense_coverage
    current_raw = comparison["baseline"]["metrics"]
    candidate_raw = comparison["candidate"]["metrics"]
    metric_profile = build_metric_profile(
        current_raw,
        candidate_raw,
        primary_field=primary_field,
        confidence=primary_confidence,
    )
    metric_profile = apply_offense_coverage_to_profile(metric_profile, offense_coverage, comparison=comparison)
    metric_profile = apply_primary_skill_guard(metric_profile, comparison)
    metric_profile = promote_pob_measured_offense_delta(
        metric_profile,
        comparison,
        offense_coverage,
        primary_field=primary_field,
        primary_confidence=primary_confidence,
    )
    primary_reference = comparison.get("baseline_primary_metric") or {}
    provenance = primary_reference.get("provenance")
    if provenance:
        label = (metric_profile.get("primary_offense") or {}).get("label") or "Damage"
        if provenance == "POB_FULL_BUILD":
            label = "PoB-configured Full DPS"
        elif provenance == "POB_PRIMARY_SKILL":
            skill_name = str(primary_reference.get("skill_name") or "").strip()
            label = f"{skill_name} (PoB primary)" if skill_name else "Selected PoB skill"
        metric_profile = dict(metric_profile)
        metric_profile["primary_offense"] = {
            **(metric_profile.get("primary_offense") or {}),
            "provenance": provenance,
            "label": label,
        }
    metric_profile, effective_primary_field, effective_primary_confidence = promote_unresolved_primary_with_component(
        metric_profile, comparison, primary_confidence=primary_confidence,
    )
    metric_profile = clamp_primary_offense_noise(metric_profile)
    resist = analyze_resistances(current_raw, candidate_raw)
    # A deferred restore (PERF-02) reports `pass: None` -- pending, not failed. Only an
    # explicit `False`, from a restore that actually ran and disagreed, is a real failure.
    restore_failed = (comparison.get("restore") or {}).get("pass") is False
    warnings = build_warnings(
        metric_profile,
        resist,
        current_raw,
        candidate_raw,
        thresholds=DEFAULT_DISPLAY_THRESHOLDS,
        restore_failed=restore_failed,
    )
    value = score_profile(metric_profile, resist, warnings, profile)
    # Internal / regression verdict. The player-facing verdict is the outcome's.
    verdict, reasons, explanation = classify_verdict_v2(metric_profile, warnings, thresholds=thresholds)
    outcome = build_evaluation_outcome(
        comparison,
        value=value,
        metric_profile=metric_profile,
        resist=resist,
        warnings=warnings,
        primary_field=effective_primary_field,
        primary_confidence=effective_primary_confidence,
    )
    value = sync_value_with_outcome(value, outcome)
    power = compute_power_per_currency(float(value["score_delta"]), price)
    comparison["evaluation_outcome"] = outcome.to_dict()
    comparison["damage_claim"] = dict(outcome.damage_claim)
    comparison["metric_profile"] = metric_profile
    comparison["normalized_metrics"] = metric_profile
    comparison["resist_caps"] = resist
    comparison["warnings"] = warnings
    comparison["value"] = value
    comparison["verdict"] = verdict.value
    comparison["verdict_reasons"] = reasons
    comparison["verdict_explanation"] = explanation
    comparison["power_per_currency"] = power
    comparison["primary_metric_field"] = effective_primary_field
    if offense_coverage:
        comparison["offense_coverage"] = offense_coverage
    return comparison


def rank_slot_comparisons(
    comparisons: list[dict[str, Any]],
    *,
    thresholds: RankingThresholds = DEFAULT_THRESHOLDS,
    profile: ValueProfile = ValueProfile.BALANCED,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
    price: ManualPrice | None = None,
    skip_enrich: bool = False,
    offense_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ranked = []
    for comparison in comparisons:
        if skip_enrich and comparison.get("metric_profile") and comparison.get("verdict"):
            ranked.append(comparison)
            continue
        ranked.append(
            enrich_slot_comparison(
                dict(comparison),
                primary_field=comparison.get("primary_metric_field") or primary_field,
                primary_confidence=primary_confidence,
                profile=profile,
                price=price,
                thresholds=thresholds,
                offense_coverage=offense_coverage or comparison.get("offense_coverage"),
            )
        )

    def sort_key(entry: dict[str, Any]) -> tuple:
        profile_metrics = entry["metric_profile"]
        offense = profile_metrics.get("primary_offense", {}).get("absolute_delta") or 0.0
        ehp = profile_metrics.get("ehp", {}).get("absolute_delta") or 0.0
        rating = ((entry.get("value") or {}).get("rating")) or 50.0
        return (_VERDICT_ORDER.get(entry["verdict"], 99), -rating, -(offense + ehp * 0.001))

    ranked.sort(key=sort_key)
    ranked = _rank_guardrail_first(ranked)
    recommendation = ranked[0] if ranked else None
    return {
        "slot_comparisons": ranked,
        "recommendation": recommendation,
        "pareto": _pareto_summary(ranked),
    }


def _pareto_summary(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    if not ranked:
        return {"status": "UNRESOLVED", "reason": "no slot comparisons"}
    best = ranked[0]
    verdict = authoritative_public_verdict(best)
    if verdict in {
        "MEANINGFUL_UPGRADE",
        "MINOR_UPGRADE",
        Verdict.STRONG_UPGRADE.value,
        Verdict.CLEAR_UPGRADE.value,
        Verdict.OFFENSE_UPGRADE.value,
        Verdict.DEFENSE_UPGRADE.value,
    }:
        return {"status": "DOMINATES", "verdict": verdict, "slot": best.get("product_slot")}
    if verdict in {"SIDEGRADE", Verdict.TRADEOFF.value}:
        return {"status": "TRADEOFF", "verdict": verdict, "slot": best.get("product_slot")}
    return {"status": "NEITHER_DOMINATES", "verdict": verdict, "slot": best.get("product_slot")}
