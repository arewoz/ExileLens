"""CORPUS-02D1 — poison and damaging-ailment breakdown from PoB's own outputs.

PoB remains the only calculator. This module classifies the numbers PoB already
reports for the selected player skill so that Item Check can show them without
double counting:

* **Damage streams** are additive in PoB's CombinedDPS (CalcOffence, "Calculate
  combined DPS estimate"): hit ``TotalDPS`` (or ``AverageDamage`` for showAverage
  skills) + ``ImpaleDPS`` + mirage damage + ``TotalDotDPS``, where ``TotalDotDPS``
  sums the skill's own ``TotalDot``, each damaging ailment's DPS and the caustic /
  burning ground they create. That sum is then multiplied by the cull and
  reservation DPS multipliers.
* **Incorporated factors** (ailment duration, chance per hit, stack potential,
  maximum stacks, magnitude effect, roll average, enemy mitigation, hit rate) are
  inputs PoB has already multiplied into ``<Ailment>DPS``
  (calcDamagingAilmentOutputs). They explain a change; they are never added to it.
* ``<Ailment>Damage`` is ``<Ailment>DPS`` x duration: the damage of the whole active
  ailment set, a different quantity from a rate, never added to DPS either.

A stat set that deals no hit damage in game (PoB data stat
``display_statset_no_hit_damage``) still has a PoB ``TotalDPS``: the fake hit PoB
uses to size the ailment. That hit is reported as excluded, not as damage.
"""

from __future__ import annotations

import math
from typing import Any

AILMENT_BREAKDOWN_VERSION = 1

# Absolute and relative tolerance for "CombinedDPS equals the sum of its streams".
_COMPOSITION_ABS_TOL = 1.0
_COMPOSITION_REL_TOL = 1e-4
# A real hit is a material part of the damage when it is at least this share of
# CombinedDPS; below it a disagreement cannot change the total's direction by much.
# The resolver scores CombinedDPS when the baseline hit is material, so a conflict
# is only possible when the candidate crosses this share.
MATERIAL_HIT_SHARE = 0.15
# Component changes smaller than this (percent) are not a direction.
_DIRECTION_PCT = 1.0

_AILMENTS = ("Poison", "Ignite", "Bleed")

# Additive damage streams of CombinedDPS (before cull/reservation multipliers).
_STREAMS: tuple[tuple[str, str], ...] = (
    ("TotalDPS", "Hit DPS"),
    ("PoisonDPS", "Poison DPS"),
    ("IgniteDPS", "Ignite DPS"),
    ("BleedDPS", "Bleed DPS"),
    ("TotalDot", "Skill damage over time"),
    ("CausticGroundDPS", "Caustic ground DPS"),
    ("BurningGroundDPS", "Burning ground DPS"),
    ("ImpaleDPS", "Impale DPS"),
)

_FACTOR_LABELS: dict[str, str] = {
    "Duration": "duration (s)",
    "ChancePerHit": "chance per hit (%)",
    "StackPotential": "stack potential",
    "StacksMax": "maximum stacks",
    "MagnitudeEffect": "magnitude effect",
    "RollAverage": "average roll (%)",
    "EffMult": "enemy mitigation multiplier",
}


def _num(metrics: dict[str, Any] | None, key: str) -> float | None:
    if not metrics:
        return None
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _pct(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or abs(before) <= 0.5:
        return None
    return (after / before - 1.0) * 100.0


def _row(field: str, label: str, role: str, before: float | None, after: float | None) -> dict[str, Any]:
    return {
        "field": field,
        "label": label,
        "role": role,
        "before": before,
        "after": after,
        "absolute_delta": None if before is None or after is None else after - before,
        "percent_delta": _pct(before, after),
    }


def _composition(metrics: dict[str, Any]) -> tuple[str, float | None]:
    """Whether PoB's CombinedDPS equals the sum of the streams this module reads."""
    combined = _num(metrics, "CombinedDPS")
    if combined is None:
        return "UNAVAILABLE", None
    if (_num(metrics, "MirageDPS") or 0.0) > 0.5:
        # Mirage damage is added from a separate actor with its own replacement
        # rules; this module does not reconstruct it.
        return "NOT_ASSESSED", None
    hit = _num(metrics, "TotalDPS") or 0.0
    dot_total = _num(metrics, "TotalDotDPS")
    if dot_total is None:
        dot_total = sum(_num(metrics, field) or 0.0 for field, _label in _STREAMS[1:7])
    base = hit + (_num(metrics, "ImpaleDPS") or 0.0) + dot_total
    multiplier = (_num(metrics, "CullMultiplier") or 1.0) * (_num(metrics, "ReservationDpsMultiplier") or 1.0)
    residual = combined - base * multiplier
    tolerance = max(_COMPOSITION_ABS_TOL, abs(combined) * _COMPOSITION_REL_TOL)
    return ("EXPLAINED" if abs(residual) <= tolerance else "UNEXPLAINED"), residual


def _dot_rate(metrics: dict[str, Any]) -> float:
    """PoB's per-second damage-over-time total (skill DoT plus every damaging ailment)."""
    total = _num(metrics, "TotalDotDPS")
    if total is not None:
        return total
    return sum(_num(metrics, f"{name}DPS") or 0.0 for name in _AILMENTS)


def _per_use_hit_omits_dot(
    primary_metric: dict[str, Any],
    before_metrics: dict[str, Any],
    after_metrics: dict[str, Any],
    hit_pct: float | None,
) -> bool:
    """A per-use (showAverage) skill is scored on its hit rate, which leaves out its DoT.

    PoB's CombinedDPS is the per-use average damage for such skills and cannot be compared
    as a rate, so the hit ``TotalDPS`` is scored. The ailment/DoT rate is a separate PoB
    output that this leaves out; when it moves and the hit rate does not show the same
    direction, the scored number does not establish the total change. Nothing is added to
    the score; PoB's own additive rate (hit + DoT) is only used to check the direction.
    """
    if not str(primary_metric.get("reason") or "").startswith("showAverage"):
        return False
    if str(primary_metric.get("pob_field") or "") != "TotalDPS":
        return False
    hit_before = _num(before_metrics, "TotalDPS") or 0.0
    hit_after = _num(after_metrics, "TotalDPS") or 0.0
    total_before = hit_before + _dot_rate(before_metrics)
    total_after = hit_after + _dot_rate(after_metrics)
    total_pct = _pct(total_before, total_after)
    if total_pct is None or abs(total_pct) < _DIRECTION_PCT:
        return False
    return hit_pct is None or abs(hit_pct) < _DIRECTION_PCT or (hit_pct > 0) != (total_pct > 0)


def ailment_breakdown(
    primary_metric: dict[str, Any] | None,
    baseline_metrics: dict[str, Any] | None,
    candidate_metrics: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Classify PoB's ailment outputs for one baseline/candidate comparison.

    Returns ``None`` when the selected player skill reports no damaging ailment.
    """
    primary_metric = primary_metric or {}
    if str(primary_metric.get("metric_source") or "PLAYER") != "PLAYER":
        return None
    before_metrics = baseline_metrics or {}
    after_metrics = candidate_metrics or {}
    present = [
        name for name in _AILMENTS
        if (_num(before_metrics, f"{name}DPS") or 0.0) > 0.5 or (_num(after_metrics, f"{name}DPS") or 0.0) > 0.5
    ]
    if not present:
        return None

    skill = primary_metric.get("primary_skill") or {}
    no_hit_damage = bool(skill.get("no_hit_damage"))
    selected_ailment = str(primary_metric.get("ailment") or "")
    dominant = selected_ailment.title() if selected_ailment else max(
        present, key=lambda name: _num(before_metrics, f"{name}DPS") or 0.0,
    )
    scored_field = str(primary_metric.get("pob_field") or "")

    components: list[dict[str, Any]] = []
    for field, label in _STREAMS:
        before = _num(before_metrics, field)
        after = _num(after_metrics, field)
        if before is None and after is None:
            continue
        if not (abs(before or 0.0) > 0.5 or abs(after or 0.0) > 0.5):
            continue
        if field == "TotalDPS" and no_hit_damage:
            role = "EXCLUDED_NO_HIT_DAMAGE"
        elif field == scored_field:
            role = "SCORED"
        else:
            role = "ADDITIVE"
        components.append(_row(field, label, role, before, after))

    factors: list[dict[str, Any]] = []
    for suffix, label in _FACTOR_LABELS.items():
        field = f"{dominant}{suffix}"
        before = _num(before_metrics, field)
        after = _num(after_metrics, field)
        if before is None and after is None:
            continue
        factors.append(_row(field, f"{dominant} {label}", "INCORPORATED", before, after))
    for field, label in (("HitSpeed", "hit rate"), ("Speed", "skill speed")):
        before = _num(before_metrics, field)
        after = _num(after_metrics, field)
        if before is not None or after is not None:
            factors.append(_row(field, label, "INCORPORATED", before, after))
            break

    total_damage = None
    before = _num(before_metrics, f"{dominant}Damage")
    after = _num(after_metrics, f"{dominant}Damage")
    if before is not None or after is not None:
        total_damage = _row(f"{dominant}Damage", f"{dominant} damage of all active stacks (DPS x duration)",
                            "DERIVED", before, after)

    status_before, residual_before = _composition(before_metrics)
    status_after, residual_after = _composition(after_metrics)
    if "UNAVAILABLE" in {status_before, status_after}:
        composition = "UNAVAILABLE"
    elif "NOT_ASSESSED" in {status_before, status_after}:
        composition = "NOT_ASSESSED"
    elif "UNEXPLAINED" in {status_before, status_after}:
        composition = "UNEXPLAINED"
    else:
        composition = "EXPLAINED"

    hit_before = _num(before_metrics, "TotalDPS") or 0.0
    hit_after = _num(after_metrics, "TotalDPS") or 0.0
    combined_before = _num(before_metrics, "CombinedDPS") or 0.0
    combined_after = _num(after_metrics, "CombinedDPS") or 0.0
    hit_share = max(
        hit_before / combined_before if combined_before > 0.5 else 0.0,
        hit_after / combined_after if combined_after > 0.5 else 0.0,
    )
    hit_pct = _pct(hit_before, hit_after)
    ailment_pct = _pct(_num(before_metrics, f"{dominant}DPS"), _num(after_metrics, f"{dominant}DPS"))
    conflict = bool(
        str(primary_metric.get("semantic_quantity") or "") == "AILMENT_DPS"
        and not no_hit_damage
        and hit_share >= MATERIAL_HIT_SHARE
        and hit_pct is not None and ailment_pct is not None
        and abs(hit_pct) >= _DIRECTION_PCT and abs(ailment_pct) >= _DIRECTION_PCT
        and (hit_pct > 0) != (ailment_pct > 0)
    )

    dot_omitted = _per_use_hit_omits_dot(primary_metric, before_metrics, after_metrics, hit_pct)

    return {
        "version": AILMENT_BREAKDOWN_VERSION,
        "ailment": dominant.upper(),
        "scored_field": scored_field,
        "hit_damage_real": not no_hit_damage,
        "combined_includes_fake_hit": bool(no_hit_damage and max(hit_before, hit_after) > 0.5),
        "components": components,
        "factors": factors,
        "ailment_total_damage": total_damage,
        "composition": {
            "status": composition,
            "baseline_residual": residual_before,
            "candidate_residual": residual_after,
        },
        "hit_share": hit_share,
        "hit_percent_delta": hit_pct,
        "ailment_percent_delta": ailment_pct,
        "hit_ailment_conflict": conflict,
        "per_use_hit_omits_dot": dot_omitted,
    }
