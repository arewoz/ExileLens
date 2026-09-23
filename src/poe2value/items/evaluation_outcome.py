"""EvaluationOutcome — the one contract every item surface consumes.

One outcome per legal replacement slot. It carries exactly one player-facing verdict,
and that verdict is classified from the same `final_score` it publishes:

    raw_score (score_profile, pre-guardrail)
      → guardrail ceilings            (guardrails.GUARDRAIL_RULES, the one table)
      → final_score
      → verdict = band(final_score)   (NOT VIABLE if a not-viable guardrail fired;
                                        UNCERTAIN if evidence is PARTIAL;
                                        UNSUPPORTED if PoB cannot model the selected
                                        semantic axis; COULDN'T EVALUATE if quality
                                        is FAILED)

Ranking V2 (`ranking.Verdict`) and the build-intel product verdict
(`build_intel.models.BuildVerdict`) stay internal/regression signals. Neither is an
input to the public verdict; hard constraints reach it only as guardrail codes.

Evaluation quality is built from detectable evidence only (see `assess_quality`).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

from poe2value.items.guardrails import AppliedGuardrail, apply_score_ceilings, evaluate_guardrails
from poe2value.items.item_impact import ItemImpact, interpret_item_impact
from poe2value.items.value_profiles import CONTRIBUTION_LABELS, SCORE_SCALE, rating_band
from poe2value.metrics import RAW_METRIC_FIELDS


class EvaluationQuality(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


class PublicVerdict(str, Enum):
    MEANINGFUL_UPGRADE = "MEANINGFUL_UPGRADE"
    MINOR_UPGRADE = "MINOR_UPGRADE"
    SIDEGRADE = "SIDEGRADE"
    MINOR_DOWNGRADE = "MINOR_DOWNGRADE"
    MEANINGFUL_DOWNGRADE = "MEANINGFUL_DOWNGRADE"
    NOT_VIABLE = "NOT_VIABLE"
    # Retained only to deserialize persisted pre-CORE-01 payloads. The truthfulness
    # gate below no longer emits directional potential verdicts.
    POTENTIAL_UPGRADE = "POTENTIAL_UPGRADE"
    POTENTIAL_DOWNGRADE = "POTENTIAL_DOWNGRADE"
    # The primary decision axis (main-skill damage) is unavailable and nothing else
    # moved the score: a neutral score here is missing evidence, not a sidegrade.
    UNCERTAIN = "UNCERTAIN"
    # PoB explicitly cannot model the semantic axis required for this comparison.
    # This is distinct from a transient failure and from incomplete evidence.
    UNSUPPORTED = "UNSUPPORTED"
    NOT_EVALUATED = "NOT_EVALUATED"


VERDICT_LABELS: dict[PublicVerdict, str] = {
    PublicVerdict.MEANINGFUL_UPGRADE: "MEANINGFUL UPGRADE",
    PublicVerdict.MINOR_UPGRADE: "MINOR UPGRADE",
    PublicVerdict.SIDEGRADE: "SIDEGRADE",
    PublicVerdict.MINOR_DOWNGRADE: "MINOR DOWNGRADE",
    PublicVerdict.MEANINGFUL_DOWNGRADE: "MEANINGFUL DOWNGRADE",
    PublicVerdict.NOT_VIABLE: "NOT VIABLE",
    PublicVerdict.POTENTIAL_UPGRADE: "POTENTIAL UPGRADE",
    PublicVerdict.POTENTIAL_DOWNGRADE: "POTENTIAL DOWNGRADE",
    PublicVerdict.UNCERTAIN: "UNCERTAIN",
    PublicVerdict.UNSUPPORTED: "UNSUPPORTED",
    PublicVerdict.NOT_EVALUATED: "COULDN'T EVALUATE",
}

# `upgrade` / `neutral` / `downgrade` / `tradeoff` — keys into `ui.styles.VERDICT_COLOR`.
VERDICT_CLASSES: dict[PublicVerdict, str] = {
    PublicVerdict.MEANINGFUL_UPGRADE: "upgrade",
    PublicVerdict.MINOR_UPGRADE: "upgrade",
    PublicVerdict.SIDEGRADE: "neutral",
    PublicVerdict.MINOR_DOWNGRADE: "downgrade",
    PublicVerdict.MEANINGFUL_DOWNGRADE: "downgrade",
    PublicVerdict.NOT_VIABLE: "downgrade",
    PublicVerdict.POTENTIAL_UPGRADE: "tradeoff",
    PublicVerdict.POTENTIAL_DOWNGRADE: "tradeoff",
    PublicVerdict.UNCERTAIN: "tradeoff",
    PublicVerdict.UNSUPPORTED: "tradeoff",
    PublicVerdict.NOT_EVALUATED: "neutral",
}

# Best first. Used to pick the best legal slot outcome.
VERDICT_ORDER: dict[str, int] = {
    verdict.value: index
    for index, verdict in enumerate(
        (
            PublicVerdict.MEANINGFUL_UPGRADE,
            PublicVerdict.MINOR_UPGRADE,
            PublicVerdict.POTENTIAL_UPGRADE,
            PublicVerdict.SIDEGRADE,
            PublicVerdict.UNCERTAIN,
            PublicVerdict.POTENTIAL_DOWNGRADE,
            PublicVerdict.MINOR_DOWNGRADE,
            PublicVerdict.MEANINGFUL_DOWNGRADE,
            PublicVerdict.NOT_VIABLE,
            # An explicitly unsupported comparison must never displace an
            # evidence-backed result in replacement-slot selection.
            PublicVerdict.UNSUPPORTED,
            PublicVerdict.NOT_EVALUATED,
        )
    )
}

QUALITY_LABELS = {
    EvaluationQuality.FULL: "",
    EvaluationQuality.PARTIAL: "Partial evaluation",
    EvaluationQuality.UNSUPPORTED: "Unsupported evaluation",
    EvaluationQuality.FAILED: "Evaluation failed",
}

# A primary loss this large is a critical trade-off even when the net score is fine.
LARGE_LOSS_PCT = 10.0

# Raw PoB fields the score reads. A non-finite value in any of them fails the outcome.
SCORED_RAW_FIELDS = (
    "TotalEHP",
    "Life",
    "EnergyShield",
    "FireResist",
    "ColdResist",
    "LightningResist",
    "ChaosResist",
    "PhysicalMaximumHitTaken",
    "FireMaximumHitTaken",
    "ColdMaximumHitTaken",
    "LightningMaximumHitTaken",
    "ChaosMaximumHitTaken",
    "MovementSpeedMod",
)

# Offense kinds that are not an authoritative damage measurement (never scored, never
# a "large damage loss"). ESTIMATED still carries PoB's numbers for display as an estimate.
_UNMEASURED_OFFENSE = frozenset({"MISSING", "UNSUPPORTED", "UNMEASURED", "ESTIMATED"})
_OFFENSE_QUALITY_DETAIL = {
    "ESTIMATED": "the main skill's damage change is an estimate that could not be verified for this build",
}
_OFFENSE_MECHANICS_PARTIAL_DETAIL = "some build mechanics are not fully measured"
_PRIMARY_DELTA_KEYS = ("primary_offense", "ehp", "worst_max_hit", "movement_speed", "chaos_res")
_LARGE_LOSS_KEYS = ("primary_offense", "ehp", "worst_max_hit", "movement_speed")
# Movement is a small score weight but a first-class loss for the player.
LARGE_MOVEMENT_LOSS_PCT = 8.0


@dataclass
class EvaluationOutcome:
    evaluation_quality: str
    evaluation_quality_reasons: list[dict[str, str]]
    final_score: float | None
    # Pre-guardrail number. Internal + diagnostics only; never the item's score.
    raw_score: float | None
    verdict: str
    verdict_reason: str
    damage_claim: dict[str, Any] = field(default_factory=dict)
    guardrails_applied: list[dict[str, Any]] = field(default_factory=list)
    item_impact: dict[str, Any] = field(default_factory=dict)
    primary_deltas: list[dict[str, Any]] = field(default_factory=list)
    all_deltas: list[dict[str, Any]] = field(default_factory=list)
    critical_tradeoffs: list[dict[str, Any]] = field(default_factory=list)
    unsupported_or_unmodeled: list[dict[str, str]] = field(default_factory=list)
    resistances: list[dict[str, Any]] = field(default_factory=list)
    source_slot: str = ""
    replacement_slot: str = ""
    replacing_item: str = ""
    replacing_empty_slot: bool = False
    baseline_metrics: dict[str, Any] = field(default_factory=dict)
    candidate_metrics: dict[str, Any] = field(default_factory=dict)
    score_contributors: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, Any] = field(default_factory=dict)
    profile: str = ""

    @property
    def pre_guardrail_score(self) -> float | None:
        return self.raw_score

    @property
    def verdict_label(self) -> str:
        return VERDICT_LABELS[PublicVerdict(self.verdict)]

    @property
    def verdict_class(self) -> str:
        return VERDICT_CLASSES[PublicVerdict(self.verdict)]

    @property
    def quality_label(self) -> str:
        return QUALITY_LABELS[EvaluationQuality(self.evaluation_quality)]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pre_guardrail_score"] = self.raw_score
        payload["verdict_label"] = self.verdict_label
        payload["verdict_class"] = self.verdict_class
        payload["quality_label"] = self.quality_label
        return payload


# ------------------------------------------------------------------ verdict policy


def classify_score_verdict(final_score: float) -> PublicVerdict:
    """The only score → verdict mapping. Edges live on `SCORE_SCALE`."""
    score = float(final_score)
    if score >= SCORE_SCALE.useful:
        return PublicVerdict.MEANINGFUL_UPGRADE
    if score >= SCORE_SCALE.minor_upgrade:
        return PublicVerdict.MINOR_UPGRADE
    if score > SCORE_SCALE.minor_downgrade:
        return PublicVerdict.SIDEGRADE
    if score > SCORE_SCALE.meaningful_downgrade:
        return PublicVerdict.MINOR_DOWNGRADE
    return PublicVerdict.MEANINGFUL_DOWNGRADE


@dataclass(frozen=True)
class VerdictDecision:
    final_score: float | None
    verdict: PublicVerdict
    reason: str
    guardrails: list[dict[str, Any]]


def decide_verdict(
    raw_score: float | None,
    guardrails: Iterable[AppliedGuardrail],
    quality: EvaluationQuality,
    quality_reasons: list[dict[str, str]] | None = None,
    item_impact: ItemImpact | None = None,
) -> VerdictDecision:
    """The single score/verdict policy. `final_score` and `verdict` always agree."""
    applied = list(guardrails)
    reasons = list(quality_reasons or [])
    if quality == EvaluationQuality.FAILED or raw_score is None or not math.isfinite(float(raw_score)):
        detail = reasons[0]["detail"] if reasons else "the evaluation did not produce usable results"
        return VerdictDecision(None, PublicVerdict.NOT_EVALUATED, f"Couldn't evaluate: {detail}.", [])

    raw = float(raw_score)
    final = apply_score_ceilings(raw, applied)
    guardrail_rows = [
        {**item.to_dict(), "binding": raw > item.score_ceiling}
        for item in applied
    ]
    if quality == EvaluationQuality.UNSUPPORTED:
        detail = reasons[0]["detail"] if reasons else "the selected build mechanic is not supported"
        return VerdictDecision(
            final,
            PublicVerdict.UNSUPPORTED,
            f"Unsupported comparison: {detail}.",
            guardrail_rows,
        )

    # Hard feasibility checks are facts about the evaluated candidate rather than a
    # score-derived recommendation. They remain visible even when another axis is
    # incomplete, but only after a successful, supported evaluation.
    not_viable = [item for item in applied if item.not_viable]
    if not_viable:
        return VerdictDecision(final, PublicVerdict.NOT_VIABLE, not_viable[0].reason, guardrail_rows)

    band = classify_score_verdict(final)
    binding = [item for item in applied if raw > item.score_ceiling]
    if quality == EvaluationQuality.PARTIAL:
        detail = reasons[0]["detail"] if reasons else "some build effects were not measured"
        return VerdictDecision(
            final,
            PublicVerdict.UNCERTAIN,
            f"Partial comparison: {detail}.",
            guardrail_rows,
        )
    # Keep the CORE-01 score/verdict agreement: a supported major cross-axis
    # conflict has the canonical sidegrade score, while raw_score retains the
    # weighted aggregate for diagnostics. Binding feasibility ceilings win.
    if item_impact is not None and item_impact.pattern == "TRADEOFF" and not applied:
        detail = "; ".join(item_impact.reasons) or "important build dimensions disagree"
        return VerdictDecision(
            50.0,
            PublicVerdict.SIDEGRADE,
            f"Meaningful trade-off: {detail}.",
            guardrail_rows,
        )
    if binding:
        return VerdictDecision(
            final,
            band,
            f"{binding[0].reason} Limited to {VERDICT_LABELS[band]}.",
            guardrail_rows,
        )
    return VerdictDecision(
        final,
        band,
        f"Net score {final - SCORE_SCALE.equivalent:+.1f} against the current item.",
        guardrail_rows,
    )


# ------------------------------------------------------------------ quality


def _reason(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _finite(value: Any) -> bool:
    # Absent fields are handled as unavailable evidence. A value that is present
    # but not a finite number is malformed worker output and must fail closed.
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _unavailable(metric: dict[str, Any] | None) -> bool:
    """Whether PoB omitted an axis, distinct from a known numeric zero."""
    if not metric or metric.get("availability") == "missing":
        return True
    try:
        current = float(metric.get("current"))
        candidate = float(metric.get("candidate"))
    except (TypeError, ValueError):
        return True
    return not math.isfinite(current) or not math.isfinite(candidate)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def build_damage_claim(
    comparison: dict[str, Any],
    metric_profile: dict[str, Any],
) -> dict[str, Any]:
    """Describe the offense evidence without deciding quality or verdict.

    This is deliberately provenance-only.  ``assess_quality`` remains the sole
    truthfulness gate and ``decide_verdict`` remains the sole public verdict policy.
    """
    offense = metric_profile.get("primary_offense") or {}
    discovery = comparison.get("native_damage_discovery") or {}
    coverage = comparison.get("offense_coverage") or {}
    kind = str(offense.get("delta_kind") or "MEASURED")
    before = _finite_number(offense.get("current"))
    after = _finite_number(offense.get("candidate"))
    percent_delta = _finite_number(offense.get("percent_delta"))
    measured = kind in {"MEASURED", "MEASURED_ZERO"} and before is not None and after is not None

    native_scope = str(discovery.get("damage_scope") or "")
    composition_status = str(discovery.get("composition_status") or "")
    overall = str(discovery.get("overall_damage_verdict") or "")
    substituted = bool(offense.get("substituted_component"))
    offense_provenance = str(offense.get("provenance") or "")
    # `damage_scope=PARTIAL` alone means that discovery produced a partial
    # component report; the presence of other groups does not establish their
    # materiality. Explicit composition/overall uncertainty is authoritative for
    # every measured scope, including an exact selected-primary quantity.
    component_claim = substituted or offense_provenance == "POB_COMPONENT"
    native_partial = (
        composition_status == "PARTIAL"
        or overall == PublicVerdict.UNCERTAIN.value
        or component_claim and native_scope == "PARTIAL"
    )

    audited_partial = False
    if measured and not coverage.get("audit_skipped"):
        from poe2value.items.offense_coverage import offense_secondary_mechanics_partial

        audited_partial = offense_secondary_mechanics_partial(coverage)

    reasons: list[str] = []
    if native_partial:
        reasons.append("PRACTICAL_COMPOSITION_UNAVAILABLE")
    if audited_partial:
        reasons.append("OFFENSE_MECHANICS_PARTIAL")
    if substituted:
        reasons.append("OFFENSE_FALLBACK_COMPONENT")

    provenance = str(offense_provenance or discovery.get("provenance") or "")
    if substituted or offense_provenance == "POB_COMPONENT":
        scope = "POB_COMPONENT"
    elif provenance in {
        "POB_FULL_BUILD", "POB_PRIMARY_SKILL", "POB_COMPONENT", "UNAVAILABLE",
    }:
        scope = provenance
    else:
        scope = "UNAVAILABLE" if not measured else "POB_PRIMARY_SKILL"

    if native_partial or audited_partial or substituted:
        whole_build_status = "PARTIAL"
    elif composition_status == "COMPLETE" or native_scope == "FULL" or scope == "POB_FULL_BUILD":
        whole_build_status = "COMPLETE"
    elif not measured:
        whole_build_status = "UNAVAILABLE"
    else:
        # Absence of an explicit composition audit is not evidence of partiality.
        # Ordinary same-skill PoB comparisons retain their established behaviour.
        whole_build_status = "NOT_ASSESSED"

    return {
        "scope": scope,
        "absolute_status": "EXACT" if measured else "UNAVAILABLE",
        "relative_status": "EXACT" if measured else "UNAVAILABLE",
        "whole_build_status": whole_build_status,
        "before": before,
        "after": after,
        "percent_delta": percent_delta,
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def authoritative_public_verdict(comparison: dict[str, Any], default: str = "UNRESOLVED") -> str:
    """Return EvaluationOutcome's verdict, with legacy-payload fallback only."""
    if "evaluation_outcome" in comparison:
        outcome = comparison.get("evaluation_outcome") or {}
        return str(outcome.get("verdict") or default)
    return str(comparison.get("verdict") or default)


def authoritative_verdict_reason(comparison: dict[str, Any]) -> str:
    """Return EvaluationOutcome's reason, with legacy-payload fallback only."""
    if "evaluation_outcome" in comparison:
        outcome = comparison.get("evaluation_outcome") or {}
        return str(outcome.get("verdict_reason") or "")
    return str(comparison.get("verdict_explanation") or "")


def assess_quality(
    comparison: dict[str, Any],
    *,
    metric_profile: dict[str, Any],
    resist: dict[str, Any],
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
    damage_claim: dict[str, Any] | None = None,
) -> tuple[EvaluationQuality, list[dict[str, str]]]:
    """FULL / PARTIAL / UNSUPPORTED / FAILED from detectable evidence only.

    FAILED: no slot, no metrics, non-finite scored metrics, failed baseline restore.
    UNSUPPORTED: PoB explicitly marks the selected primary semantic comparison as
                 unsupported.
    PARTIAL: unmeasured/unavailable offense, incomplete mechanics coverage,
             low-confidence primary damage metric, unavailable EHP / Max Hit, or
             resistance fields PoB did not report.
    Unparsed modifiers and PoB calc warnings are *not* reported by the bridge today,
    so they are never claimed.
    """
    failed: list[dict[str, str]] = []
    if not str(comparison.get("pob_slot") or comparison.get("product_slot") or ""):
        failed.append(_reason("UNRESOLVED_SLOT", "the replacement slot could not be resolved"))
    if (comparison.get("candidate") or {}).get("item_present") is False:
        failed.append(_reason("REPLACEMENT_NOT_APPLIED", "Path of Building did not equip the candidate in the selected slot"))
    raw_current = (comparison.get("baseline") or {}).get("metrics")
    raw_candidate = (comparison.get("candidate") or {}).get("metrics")
    if not isinstance(raw_current, dict) or not raw_current or not isinstance(raw_candidate, dict) or not raw_candidate:
        failed.append(_reason("NO_METRICS", "Path of Building returned no metrics"))
    else:
        # A malformed non-score value (for example mana sustain) can reach a
        # guardrail before scoring. Validate every documented worker metric that
        # is actually present, while still allowing PoB to omit unsupported fields.
        fields = (*RAW_METRIC_FIELDS, primary_field)
        bad = sorted(
            {
                name
                for raw in (raw_current, raw_candidate)
                for name in fields
                if name in raw and not _finite(raw.get(name))
            }
        )
        if bad:
            failed.append(_reason("INVALID_METRICS", "Path of Building returned invalid values for " + ", ".join(bad)))
    # PERF-02 defers the restore: `pass` is explicitly `None` (never absent) while it is
    # still pending, and `False` only once verification has actually run and disagreed
    # with the baseline. `.get("pass", True)` returns the stored `None` here, not the
    # default -- treating "not yet verified" as "verified failed" would fail every
    # deferred comparison. Only an explicit `False` is a real, checked restore failure.
    if (comparison.get("restore") or {}).get("pass") is False:
        failed.append(_reason("RESTORE_FAILED", "the build could not be restored after the comparison"))
    if failed:
        return EvaluationQuality.FAILED, failed

    partial: list[dict[str, str]] = []
    offense = metric_profile.get("primary_offense") or {}
    claim = damage_claim or build_damage_claim(comparison, metric_profile)
    kind = str(offense.get("delta_kind") or "MEASURED")
    if kind == "UNSUPPORTED":
        return EvaluationQuality.UNSUPPORTED, [
            _reason("OFFENSE_UNSUPPORTED", "Path of Building does not support the selected main-skill comparison")
        ]
    if kind in _UNMEASURED_OFFENSE:
        partial.append(
            _reason(
                f"OFFENSE_{kind}",
                _OFFENSE_QUALITY_DETAIL.get(kind, "damage change could not be measured for this build"),
            )
        )
    elif _unavailable(offense):
        partial.append(_reason("OFFENSE_UNAVAILABLE", "Path of Building reported no damage for the main skill"))
    if offense.get("substituted_component"):
        # CORE-01: native discovery only ever substitutes a component here when it has
        # already established damage_scope=PARTIAL / overall_damage_verdict=UNCERTAIN
        # for the true primary skill (see native_metric_discovery.
        # promote_unresolved_primary_with_component) -- the substitute's own field may
        # be confidently identified and its number genuinely measured, but it is still
        # one secondary skill standing in for a primary that produced nothing to
        # measure at all, never full coverage of the build's real damage change. That
        # must downgrade quality regardless of which delta_kind the substitute carries
        # or how confidently the substitute skill itself was resolved.
        partial.append(
            _reason(
                "OFFENSE_FALLBACK_COMPONENT",
                "the main skill produced no usable damage output; a secondary measured "
                "component stands in for it",
            )
        )
    if kind in {"MEASURED", "MEASURED_ZERO"} and claim.get("whole_build_status") == "PARTIAL":
        claim_codes = set(claim.get("reason_codes") or [])
        if offense.get("substituted_component"):
            # The established fallback reason above is more specific.
            pass
        elif "OFFENSE_MECHANICS_PARTIAL" in claim_codes:
            partial.append(_reason("OFFENSE_MECHANICS_PARTIAL", _OFFENSE_MECHANICS_PARTIAL_DETAIL))
        else:
            partial.append(
                _reason(
                    "OFFENSE_COMPOSITION_PARTIAL",
                    "the measured damage component does not establish complete build damage",
                )
            )
    if str(primary_confidence or "").lower() == "low":
        partial.append(_reason("PRIMARY_METRIC_LOW_CONFIDENCE", "the main damage metric could not be identified with confidence"))
    if _unavailable(metric_profile.get("ehp")):
        partial.append(_reason("EHP_UNAVAILABLE", "effective hit pool was not reported"))
    if _unavailable(metric_profile.get("worst_max_hit")):
        partial.append(_reason("MAX_HIT_UNAVAILABLE", "maximum hit taken was not reported"))
    missing_res = [
        element
        for element, info in (resist.get("elements") or {}).items()
        if str((info or {}).get("state") or "") == "UNKNOWN"
    ]
    if missing_res:
        partial.append(
            _reason("RESISTANCE_UNAVAILABLE", "resistance values were not reported for " + ", ".join(sorted(missing_res)))
        )
    if partial:
        return EvaluationQuality.PARTIAL, partial
    return EvaluationQuality.FULL, []


# ------------------------------------------------------------------ builders


def _hard_constraint_codes(
    metric_profile: dict[str, Any],
    resist: dict[str, Any],
    raw_current: dict[str, Any],
    raw_candidate: dict[str, Any],
    *,
    restore_failed: bool,
) -> list[str]:
    # Lazy: build_intel's package init imports ranking, which imports this module.
    from poe2value.items.build_intel.constraints import constraints_from_thresholds
    from poe2value.items.build_intel.thresholds import assess_thresholds

    events = assess_thresholds(metric_profile, resist, raw_current, raw_candidate, restore_failed=restore_failed)
    return [item.code for item in constraints_from_thresholds(events)]


def _delta_row(key: str, metric: dict[str, Any]) -> dict[str, Any]:
    row = {
        "key": key,
        "label": metric.get("label") or key,
        "current": metric.get("current"),
        "candidate": metric.get("candidate"),
        "absolute_delta": metric.get("absolute_delta"),
        "percent_delta": metric.get("percent_delta"),
        "direction": metric.get("direction"),
    }
    if key == "primary_offense":
        row["delta_kind"] = metric.get("delta_kind") or "MEASURED"
        if metric.get("provenance"):
            row["provenance"] = metric["provenance"]
    return row


def _resistance_rows(resist: dict[str, Any], guardrails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    critical_metrics = {
        metric
        for item in guardrails
        if str(item.get("code") or "").startswith("RES_")
        for metric in str(item.get("metric") or "").split(",")
        if metric
    }
    rows = []
    for element, info in (resist.get("elements") or {}).items():
        info = info or {}
        rows.append(
            {
                "element": element,
                "state": info.get("state"),
                "cap_current": info.get("cap_current"),
                "cap_candidate": info.get("cap_candidate"),
                "current": info.get("current"),
                "candidate": info.get("candidate"),
                "uncapped_current": info.get("uncapped_current"),
                "uncapped_candidate": info.get("uncapped_candidate"),
                "buffer_current": info.get("buffer_current"),
                "buffer_candidate": info.get("buffer_candidate"),
                "buffer_delta": info.get("buffer_delta"),
                "deficit_current": info.get("baseline_deficit"),
                "deficit_candidate": info.get("candidate_deficit"),
                "flexibility_delta": info.get("flexibility_delta"),
                "critical": f"{element}_res" in critical_metrics,
            }
        )
    return rows


def _unsupported_or_unmodeled(
    quality_reasons: list[dict[str, str]],
    metric_profile: dict[str, Any],
    comparison: dict[str, Any],
) -> list[dict[str, str]]:
    rows = [item for item in quality_reasons if item["code"].startswith(("OFFENSE_", "PRIMARY_"))]
    seen_codes = {item["code"] for item in rows}
    offense = metric_profile.get("primary_offense") or {}
    kind = str(offense.get("delta_kind") or "MEASURED")
    if kind in {"MEASURED", "MEASURED_ZERO"} and "OFFENSE_MECHANICS_PARTIAL" not in seen_codes:
        from poe2value.items.offense_coverage import offense_secondary_mechanics_partial

        coverage = comparison.get("offense_coverage") or {}
        if not coverage.get("audit_skipped") and offense_secondary_mechanics_partial(coverage):
            rows.append(_reason("OFFENSE_MECHANICS_PARTIAL", _OFFENSE_MECHANICS_PARTIAL_DETAIL))
    return rows


def _critical_tradeoffs(metric_profile: dict[str, Any], guardrails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {"marker": "!", "code": item["code"], "metric": item.get("metric") or "", "text": item["reason"]}
        for item in guardrails
    ]
    for key in _LARGE_LOSS_KEYS:
        metric = metric_profile.get(key) or {}
        pct = metric.get("percent_delta")
        if key == "primary_offense" and str(metric.get("delta_kind") or "MEASURED") in _UNMEASURED_OFFENSE:
            continue
        threshold = LARGE_MOVEMENT_LOSS_PCT if key == "movement_speed" else LARGE_LOSS_PCT
        if pct is None or float(pct) > -threshold:
            continue
        rows.append(
            {
                "marker": "▼",
                "code": "LARGE_LOSS",
                "metric": key,
                "text": f"{metric.get('label') or key} {float(pct):+.1f}%",
            }
        )
    return rows


def _score_contributors(value: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, contribution in (value.get("contributions") or {}).items():
        amount = float(contribution or 0.0)
        if abs(amount) < 0.0001:
            continue
        rows.append(
            {
                "key": key,
                "label": CONTRIBUTION_LABELS.get(key, key),
                "sign": "+" if amount > 0 else "-",
                "contribution": round(amount, 4),
            }
        )
    rows.sort(key=lambda row: abs(row["contribution"]), reverse=True)
    return rows


def _replacing(comparison: dict[str, Any]) -> tuple[str, bool]:
    baseline_item = comparison.get("baseline_item") or {}
    if baseline_item.get("empty"):
        return "", True
    return str(baseline_item.get("display_name") or baseline_item.get("name") or ""), False


def build_evaluation_outcome(
    comparison: dict[str, Any],
    *,
    value: dict[str, Any],
    metric_profile: dict[str, Any],
    resist: dict[str, Any],
    warnings: list[dict[str, Any]],
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
) -> EvaluationOutcome:
    raw_current = dict((comparison.get("baseline") or {}).get("metrics") or {})
    raw_candidate = dict((comparison.get("candidate") or {}).get("metrics") or {})
    # See assess_quality: a deferred restore's `pass` is `None`, not failed.
    restore_failed = (comparison.get("restore") or {}).get("pass") is False
    damage_claim = build_damage_claim(comparison, metric_profile)
    quality, quality_reasons = assess_quality(
        comparison,
        metric_profile=metric_profile,
        resist=resist,
        primary_field=primary_field,
        primary_confidence=primary_confidence,
        damage_claim=damage_claim,
    )

    guardrails: list[AppliedGuardrail] = []
    if quality != EvaluationQuality.FAILED:
        codes = {str(item.get("code") or "") for item in warnings}
        codes.update(
            _hard_constraint_codes(metric_profile, resist, raw_current, raw_candidate, restore_failed=restore_failed)
        )
        guardrails = evaluate_guardrails(codes, resist, warnings=warnings, metrics=metric_profile)

    raw_score = value.get("raw_rating", value.get("rating"))
    item_impact = interpret_item_impact(
        metric_profile, resist, raw_current, raw_candidate,
        guardrails=[item.to_dict() for item in guardrails],
    )
    decision = decide_verdict(raw_score, guardrails, quality, quality_reasons, item_impact=item_impact)
    replacing_item, replacing_empty = _replacing(comparison)
    eval_ms = comparison.get("eval_ms")

    return EvaluationOutcome(
        evaluation_quality=quality.value,
        evaluation_quality_reasons=quality_reasons,
        final_score=decision.final_score,
        raw_score=float(raw_score) if raw_score is not None and _finite(raw_score) else None,
        verdict=decision.verdict.value,
        verdict_reason=decision.reason,
        damage_claim=damage_claim,
        guardrails_applied=decision.guardrails,
        item_impact=item_impact.to_dict(),
        primary_deltas=[
            _delta_row(key, metric_profile[key])
            for key in _PRIMARY_DELTA_KEYS
            if key in metric_profile and not _unavailable(metric_profile[key])
        ],
        all_deltas=[
            _delta_row(key, metric)
            for key, metric in metric_profile.items()
            if isinstance(metric, dict) and metric.get("availability") != "missing"
        ],
        critical_tradeoffs=_critical_tradeoffs(metric_profile, decision.guardrails),
        unsupported_or_unmodeled=_unsupported_or_unmodeled(quality_reasons, metric_profile, comparison),
        resistances=_resistance_rows(resist, decision.guardrails),
        source_slot=str(comparison.get("product_slot") or ""),
        replacement_slot=str(comparison.get("pob_slot") or ""),
        replacing_item=replacing_item,
        replacing_empty_slot=replacing_empty,
        baseline_metrics=raw_current,
        candidate_metrics=raw_candidate,
        score_contributors=_score_contributors(value),
        timings={"slot_eval_ms": float(eval_ms)} if eval_ms is not None else {},
        profile=str(value.get("profile") or ""),
    )


def failed_outcome(
    code: str,
    detail: str,
    *,
    source_slot: str = "",
    replacement_slot: str = "",
) -> EvaluationOutcome:
    """Outcome for a slot (or whole item) whose evaluation raised before producing metrics."""
    reasons = [_reason(code, detail)]
    decision = decide_verdict(None, [], EvaluationQuality.FAILED, reasons)
    return EvaluationOutcome(
        evaluation_quality=EvaluationQuality.FAILED.value,
        evaluation_quality_reasons=reasons,
        final_score=None,
        raw_score=None,
        verdict=decision.verdict.value,
        verdict_reason=decision.reason,
        source_slot=source_slot,
        replacement_slot=replacement_slot,
    )


def sync_value_with_outcome(value: dict[str, Any], outcome: EvaluationOutcome) -> dict[str, Any]:
    """Compatibility adapter: the legacy `value` block mirrors the outcome's final score.

    Legacy readers (`value.rating`, `value.score_delta`, pinned SWAP SCORE, multi-profile)
    therefore show the same number the verdict was classified from. A FAILED outcome
    keeps the legacy numbers for internal callers but is marked, and surfaces must
    read the outcome (final_score None) instead.
    """
    synced = dict(value)
    synced["verdict"] = outcome.verdict
    synced["evaluation_quality"] = outcome.evaluation_quality
    if outcome.final_score is None:
        return synced
    synced["raw_rating"] = outcome.raw_score
    synced["rating"] = outcome.final_score
    synced["score_delta"] = round(outcome.final_score - SCORE_SCALE.equivalent, 1)
    synced["band"] = rating_band(outcome.final_score).value
    synced["guardrails"] = [item["code"] for item in outcome.guardrails_applied]
    return synced
