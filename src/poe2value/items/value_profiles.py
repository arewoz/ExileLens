from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from poe2value.items.guardrails import GUARDRAIL_RULES, apply_score_ceilings, evaluate_guardrails


class ValueProfile(str, Enum):
    BALANCED = "BALANCED"
    MAPPING = "MAPPING"
    BOSSING = "BOSSING"
    DEFENSIVE = "DEFENSIVE"


class ScoreBand(str, Enum):
    EXCEPTIONAL = "exceptional"
    STRONG = "strong"
    USEFUL = "useful"
    MARGINAL = "marginal"
    POOR = "poor"
    SEVERE = "severe"


@dataclass(frozen=True)
class ProfileWeights:
    primary_offense: float
    ehp: float
    max_hit: float
    res_cap: float
    movement: float
    chaos_res: float
    # Overcap flexibility (resistance buffer above cap). Deliberately small: it is
    # generic flexibility, never a second copy of the EHP/Max Hit defence gain.
    res_flex: float = 0.05


@dataclass(frozen=True)
class ScoreScale:
    """Candidate rating is 0–100 where 50 is equivalent to the current item.

    `useful` / `minor_upgrade` / `minor_downgrade` / `meaningful_downgrade` are the
    verdict band edges read by `evaluation_outcome.classify_score_verdict`; the other
    fields are the internal `ScoreBand` ids.
    """

    equivalent: float = 50.0
    useful: float = 60.0
    strong: float = 75.0
    exceptional: float = 90.0
    poor: float = 45.0
    severe: float = 25.0
    minor_upgrade: float = 53.0
    minor_downgrade: float = 47.0
    meaningful_downgrade: float = 40.0


SCORE_SCALE = ScoreScale()

# Contribution saturates at ±scale percent (or resistance points for chaos_res, or
# overcap utility units for res_flex — see resist_caps.overcap_utility).
CONTRIBUTION_SCALES = {
    "primary_offense": 12.0,
    "ehp": 10.0,
    "max_hit": 10.0,
    "movement": 8.0,
    "chaos_res": 25.0,
    "res_flex": 12.0,
}

CONTRIBUTION_LABELS = {
    "primary_offense": "primary offense",
    "ehp": "EHP",
    "max_hit": "max hit",
    "res_cap": "resistance cap",
    "res_flex": "resistance buffer",
    "movement": "movement",
    "chaos_res": "chaos resistance",
}

PROFILE_WEIGHTS: dict[ValueProfile, ProfileWeights] = {
    ValueProfile.BALANCED: ProfileWeights(
        primary_offense=0.35, ehp=0.25, max_hit=0.10, res_cap=0.20, movement=0.05, chaos_res=0.05
    ),
    ValueProfile.MAPPING: ProfileWeights(
        primary_offense=0.45, ehp=0.15, max_hit=0.05, res_cap=0.15, movement=0.15, chaos_res=0.05
    ),
    ValueProfile.BOSSING: ProfileWeights(
        primary_offense=0.30, ehp=0.20, max_hit=0.20, res_cap=0.25, movement=0.00, chaos_res=0.05
    ),
    ValueProfile.DEFENSIVE: ProfileWeights(
        primary_offense=0.15, ehp=0.30, max_hit=0.20, res_cap=0.30, movement=0.00, chaos_res=0.05
    ),
}

# Explicit guardrail ceilings — not hidden inside weights. Read-only view of the one
# table in `guardrails.GUARDRAIL_RULES`.
GUARDRAIL_RATING_CAPS = {code: rule.score_ceiling for code, rule in GUARDRAIL_RULES.items()}


def rating_band(rating: float) -> ScoreBand:
    if rating >= SCORE_SCALE.exceptional:
        return ScoreBand.EXCEPTIONAL
    if rating >= SCORE_SCALE.strong:
        return ScoreBand.STRONG
    if rating >= SCORE_SCALE.useful:
        return ScoreBand.USEFUL
    if rating >= SCORE_SCALE.poor:
        return ScoreBand.MARGINAL
    if rating >= SCORE_SCALE.severe:
        return ScoreBand.POOR
    return ScoreBand.SEVERE


def _signed_unit(value: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return max(-1.0, min(1.0, value / scale))


def _metric_pct(metric: dict[str, Any] | None) -> float:
    if not metric or metric.get("availability") == "missing":
        return 0.0
    pct = metric.get("percent_delta")
    if pct is not None:
        return float(pct)
    current = float(metric.get("current") or 0)
    candidate = float(metric.get("candidate") or 0)
    if current == 0:
        return 0.0
    return (candidate / current - 1.0) * 100.0


def _movement_pct(metric: dict[str, Any] | None) -> float:
    if not metric:
        return 0.0
    current = float(metric.get("current") or 0)
    candidate = float(metric.get("candidate") or 0)
    if 0 < current <= 8 and 0 < candidate <= 8:
        return (candidate - current) * 100.0
    return _metric_pct(metric)


# Mirrors offense_coverage.NON_AUTHORITATIVE_OFFENSE_KINDS (not imported: that module imports this one).
_NON_AUTHORITATIVE_OFFENSE = frozenset({"ESTIMATED", "MISSING", "UNSUPPORTED", "UNMEASURED"})


def score_profile(
    metrics: dict[str, Any],
    resist: dict[str, Any],
    warnings: list[dict[str, Any]],
    profile: ValueProfile,
) -> dict[str, Any]:
    weights = PROFILE_WEIGHTS[profile]
    offense_entry = metrics.get("primary_offense") or {}
    delta_kind = str(offense_entry.get("delta_kind") or "MEASURED")
    if delta_kind in _NON_AUTHORITATIVE_OFFENSE:
        offense = 0.0
    elif delta_kind == "MEASURED_ZERO":
        offense = 0.0
    else:
        offense = _metric_pct(offense_entry)
    ehp = _metric_pct(metrics.get("ehp"))
    max_hit = _metric_pct(metrics.get("worst_max_hit"))
    movement = _movement_pct(metrics.get("movement_speed"))
    chaos_abs = float((metrics.get("chaos_res") or {}).get("absolute_delta") or 0.0)

    cap_penalty = 0.0
    if resist.get("any_cap_lost"):
        cap_penalty = -1.0
    elif resist.get("elemental_deficit_worsened") or resist.get("deficit_worsened_elements"):
        worst_delta = 0.0
        worst_abs = 0.0
        for element, info in (resist.get("elements") or {}).items():
            if info.get("state") != "BELOW_CAP_WORSENED":
                continue
            worst_delta = max(worst_delta, abs(float(info.get("deficit_delta") or 0.0)))
            worst_abs = max(worst_abs, abs(float(info.get("candidate_deficit") or 0.0)))
        # Explainable: tiny 74→73 is mild; deep deficit like -33→-37 is heavier.
        unit = min(1.0, (worst_delta / 15.0) + min(1.0, worst_abs / 75.0) * 0.45)
        cap_penalty = -0.35 - 0.45 * unit
    elif resist.get("reached_elements"):
        cap_penalty = 0.85

    # Buffer-above-cap only (diminishing, saturating). Independent of EHP/Max Hit,
    # which keep every downstream effect of uncapped resistance at full weight.
    flex = float(resist.get("flexibility_delta") or 0.0)

    parts = {
        "primary_offense": weights.primary_offense * _signed_unit(offense, CONTRIBUTION_SCALES["primary_offense"]),
        "ehp": weights.ehp * _signed_unit(ehp, CONTRIBUTION_SCALES["ehp"]),
        "max_hit": weights.max_hit * _signed_unit(max_hit, CONTRIBUTION_SCALES["max_hit"]),
        "res_cap": weights.res_cap * cap_penalty,
        "res_flex": weights.res_flex * _signed_unit(flex, CONTRIBUTION_SCALES["res_flex"]),
        "movement": weights.movement * _signed_unit(movement, CONTRIBUTION_SCALES["movement"]),
        "chaos_res": weights.chaos_res * _signed_unit(chaos_abs, CONTRIBUTION_SCALES["chaos_res"]),
    }
    weighted = sum(parts.values())
    # Map combined unit-weighted signal onto ±50 around the 50 baseline.
    raw_delta = round(50.0 * max(-1.0, min(1.0, weighted * 1.35)), 1)
    raw_rating = round(SCORE_SCALE.equivalent + raw_delta, 1)

    guardrails = evaluate_guardrails(
        (warning["code"] for warning in warnings), resist, warnings=warnings, metrics=metrics
    )
    applied_guardrails = [guardrail.code for guardrail in guardrails]
    rating = apply_score_ceilings(raw_rating, guardrails)
    score_delta = round(rating - SCORE_SCALE.equivalent, 1)

    drivers: list[dict[str, Any]] = []
    labels = CONTRIBUTION_LABELS
    for key, contribution in sorted(parts.items(), key=lambda item: abs(item[1]), reverse=True):
        if abs(contribution) < 0.01 and key != "res_cap":
            continue
        if key == "primary_offense" and delta_kind in _NON_AUTHORITATIVE_OFFENSE:
            continue
        if contribution > 0:
            sign = "+"
        elif contribution < 0:
            sign = "-"
        else:
            continue
        drivers.append(
            {
                "sign": sign,
                "key": key,
                "label": labels[key],
                "contribution": round(contribution, 4),
            }
        )
        if len(drivers) >= 5:
            break
    for code in applied_guardrails:
        drivers.append({"sign": "!", "key": code, "label": code.replace("_", " ").lower(), "contribution": 0.0})

    return {
        "profile": profile.value,
        # Pre-guardrail number: diagnostics only, never shown as the item's score.
        "raw_rating": raw_rating,
        "rating": rating,
        "score_delta": score_delta,
        "band": rating_band(rating).value,
        "drivers": drivers,
        "guardrails": applied_guardrails,
        "contributions": {key: round(value, 4) for key, value in parts.items()},
        "heuristic": True,
    }
