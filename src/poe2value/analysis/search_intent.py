from __future__ import annotations

from typing import Any

from poe2value.analysis.audit import BuildNeed
from poe2value.analysis.identity import AnalysisBaseline
from poe2value.items.value_profiles import ValueProfile

SEARCH_INTENT_VERSION = 1
TIERS = ("REQUIRED", "HIGH_VALUE", "USEFUL", "LOW_VALUE", "AVOID")

RES_TO_PROBE = {
    "fire_res": "FIRE_RES",
    "cold_res": "COLD_RES",
    "lightning_res": "LIGHTNING_RES",
    "chaos_res": "CHAOS_RES",
}


def _tier_from_delta(score_delta: float, breakpoints: list, profile: ValueProfile) -> str:
    if any(event.get("code") == "CAP_REACHED" for event in breakpoints):
        return "REQUIRED"
    mapping_boost = profile == ValueProfile.MAPPING
    if mapping_boost and score_delta >= 5:
        return "HIGH_VALUE"
    if score_delta >= 8:
        return "HIGH_VALUE"
    if score_delta >= 3:
        return "USEFUL"
    if score_delta <= -4:
        return "AVOID"
    return "LOW_VALUE"


def build_search_intent(
    *,
    baseline: AnalysisBaseline,
    product_slot: str,
    pob_slot: str,
    needs: list[BuildNeed],
    probes: list[dict[str, Any]],
    opportunity: dict[str, Any],
    profile: ValueProfile,
    slot_compat: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required: list[dict[str, Any]] = []
    high_value: list[dict[str, Any]] = []
    useful: list[dict[str, Any]] = []
    low_value: list[dict[str, Any]] = []
    avoid: list[dict[str, Any]] = []

    used_required: set[str] = set()
    for need in needs:
        if need.code not in {"RES_CAP_MISSING", "LOW_CHAOS_RES", "ATTRIBUTE_REQUIREMENT"}:
            continue
        probe_id = RES_TO_PROBE.get(need.metric)
        if not probe_id:
            continue
        compat = slot_compat.get(probe_id) or {}
        if not compat.get("compatible"):
            continue
        used_required.add(probe_id)
        required.append(
            {
                "stat": need.metric,
                "probe_id": probe_id,
                "minimum": need.deficit,
                "reason": "RESTORE_CAP" if need.breakpoint == "RESISTANCE_CAP" else need.code,
                "confidence": need.confidence,
                "tier": "REQUIRED",
            }
        )

    by_id: dict[str, dict[str, Any]] = {}
    for probe in probes:
        if probe.get("status") not in {"ok", "NO_SIGNAL"}:
            continue
        if not probe.get("slot_compatible"):
            continue
        by_id[str(probe["probe_id"])] = probe

    for probe_id, probe in by_id.items():
        if probe_id in used_required:
            continue
        breakpoints = probe.get("breakpoints") or []
        delta = float(probe.get("score_delta") or 0.0)
        tier = _tier_from_delta(delta, breakpoints, profile)
        entry = {
            "stat": probe_id.lower(),
            "probe_id": probe_id,
            "display_name": probe.get("display_name"),
            "marginal_value": probe.get("marginal_value_per_unit"),
            "score_delta": delta,
            "magnitude": probe.get("magnitude"),
            "confidence": str(probe.get("confidence") or "MEDIUM").lower(),
            "label": "MARGINAL VALUE",
            "tier": tier,
            "breakpoints": breakpoints,
        }
        if tier == "REQUIRED":
            required.append(entry)
        elif tier == "HIGH_VALUE":
            high_value.append(entry)
        elif tier == "USEFUL":
            useful.append(entry)
        elif tier == "AVOID":
            avoid.append(entry)
        else:
            low_value.append(entry)

    def _rank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda row: abs(float(row.get("score_delta") or row.get("minimum") or 0)), reverse=True)

    intent = {
        "contract_version": SEARCH_INTENT_VERSION,
        "kind": "SearchIntent",
        "baseline": baseline.to_dict(),
        "slot": product_slot,
        "pob_slot": pob_slot,
        "profile": profile.value,
        "required": _rank(required),
        "high_value": _rank(high_value),
        "useful": _rank(useful),
        "low_value": _rank(low_value),
        "avoid": _rank(avoid),
        "constraints": {
            "slot": product_slot,
            "context": baseline.context,
            "offline": True,
            "market": False,
        },
        "opportunity_score": opportunity.get("score"),
        "opportunity_band": opportunity.get("band"),
        "SLOT_COMPATIBILITY_CONFIDENCE": "high",
        "price": None,
        "trade_query": None,
        "network": False,
    }
    return intent
