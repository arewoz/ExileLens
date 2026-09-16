from __future__ import annotations

from typing import Any

from poe2value.analysis.audit import BuildNeed
from poe2value.items.slots import ProductSlot

WEAPON_PRODUCT_SLOTS = {
    ProductSlot.WEAPON_1.value,
    ProductSlot.WEAPON_2.value,
    ProductSlot.OFFHAND_2.value,
}

SAFE_CONTRIBUTION_SLOTS = {
    ProductSlot.HELMET.value,
    ProductSlot.BODY_ARMOUR.value,
    ProductSlot.GLOVES.value,
    ProductSlot.BOOTS.value,
    ProductSlot.BELT.value,
    ProductSlot.AMULET.value,
    ProductSlot.RING_1.value,
    ProductSlot.RING_2.value,
    ProductSlot.OFFHAND_1.value,
}

BANDS = (
    (80, "VERY HIGH"),
    (60, "HIGH"),
    (40, "MEDIUM"),
    (0, "LOW"),
)

RES_PROBE = {
    "fire_res": "FIRE_RES",
    "cold_res": "COLD_RES",
    "lightning_res": "LIGHTNING_RES",
    "chaos_res": "CHAOS_RES",
}


def opportunity_band(score: int) -> str:
    for threshold, label in BANDS:
        if score >= threshold:
            return label
    return "LOW"


def _need_addressable(need: BuildNeed, slot: str, compat: dict[str, set[str]]) -> bool:
    probe_id = RES_PROBE.get(need.metric)
    if probe_id:
        return slot in compat.get(probe_id, set())
    if need.code == "MOVEMENT_OPPORTUNITY":
        return slot in compat.get("MOVEMENT_SPEED", set())
    if need.code == "RESOURCE_PRESSURE":
        return slot in compat.get("MANA", set())
    return False


def score_slot_opportunity(
    *,
    product_slot: str,
    needs: list[BuildNeed],
    slot_probes: list[dict[str, Any]],
    contribution: dict[str, Any] | None,
    compat: dict[str, set[str]],
    analysis_limited: bool = False,
) -> dict[str, Any]:
    if analysis_limited or product_slot in WEAPON_PRODUCT_SLOTS:
        return {
            "product_slot": product_slot,
            "score": None,
            "band": "ANALYSIS LIMITED",
            "drivers": [{"text": "Weapon / offhand probing is not trustworthy in Phase 5A.", "kind": "limit"}],
            "confidence": "LOW",
            "analysis_limited": True,
        }

    drivers: list[dict[str, Any]] = []
    score = 0

    # Breakpoint / critical needs are explicit. Do not also add Phase 4 res_cap
    # score_delta from the matching resistance probe (avoids triple-counting cap,
    # EHP, and max-hit as extra arbitrary bonuses on top of the breakpoint).
    cap_need_metrics: set[str] = set()
    for need in needs:
        if need.severity != "critical":
            continue
        if not _need_addressable(need, product_slot, compat):
            continue
        cap_need_metrics.add(need.metric)
        bump = 40 if need.code == "RES_CAP_MISSING" else 28
        score += bump
        extra = f" +{need.deficit:g} to cap" if need.deficit is not None else ""
        drivers.append({"text": f"can repair missing {need.metric.replace('_', ' ')}{extra}", "kind": "critical", "code": need.code})

    for need in needs:
        if need.severity != "high":
            continue
        if not _need_addressable(need, product_slot, compat):
            continue
        score += 16
        drivers.append({"text": f"addresses {need.code}", "kind": "high", "code": need.code})

    cap_probe_ids = {RES_PROBE[m] for m in cap_need_metrics if m in RES_PROBE}
    smooth = 0.0
    high_value_count = 0
    for probe in slot_probes:
        if probe.get("status") not in {"ok", "NO_SIGNAL"}:
            continue
        if probe.get("probe_id") in cap_probe_ids:
            continue
        if not probe.get("slot_compatible"):
            continue
        delta = float(probe.get("score_delta") or 0.0)
        if delta >= 8:
            high_value_count += 1
        if probe.get("breakpoints"):
            drivers.append({"text": f"{probe.get('display_name')} crosses a breakpoint", "kind": "breakpoint"})
        smooth = max(smooth, delta)
        if delta >= 6:
            drivers.append(
                {
                    "text": f"{probe.get('display_name')} has high marginal value",
                    "kind": "marginal",
                    "probe_id": probe.get("probe_id"),
                    "score_delta": delta,
                }
            )

    score += int(max(0.0, min(30.0, smooth)))
    score += min(10, high_value_count * 3)

    if contribution and contribution.get("status") == "ok":
        offense_loss = float(contribution.get("offense_percent") or 0.0)
        # Neutralized item vs current: negative offense_percent means current item contributes offense.
        if offense_loss > -1.0:
            score += 12
            drivers.append({"text": "current item contributes little offense", "kind": "contribution"})
        elif offense_loss > -4.0:
            score += 6
            drivers.append({"text": "current item is offensively modest", "kind": "contribution"})

    score = int(max(0, min(100, score)))
    if not drivers:
        drivers.append({"text": "current slot already performs efficiently", "kind": "note"})
    return {
        "product_slot": product_slot,
        "score": score,
        "band": opportunity_band(score),
        "drivers": drivers,
        "confidence": "HIGH" if score >= 40 or cap_need_metrics else "MEDIUM",
        "analysis_limited": False,
        "market": False,
    }
