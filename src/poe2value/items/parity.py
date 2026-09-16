from __future__ import annotations

from typing import Any

from poe2value.metrics import RAW_METRIC_FIELDS

PARITY_FIELDS = (
    "CombinedDPS",
    "TotalEHP",
    "Life",
    "EnergyShield",
    "Mana",
    "FireResist",
    "ColdResist",
    "LightningResist",
    "ChaosResist",
    "PhysicalMaximumHitTaken",
    "FireMaximumHitTaken",
    "ColdMaximumHitTaken",
    "LightningMaximumHitTaken",
    "ChaosMaximumHitTaken",
)


def _num(raw: dict[str, Any], field: str) -> float | None:
    if field not in raw or raw.get(field) is None:
        return None
    return float(raw[field])


def metrics_match(left: dict[str, Any], right: dict[str, Any], *, tolerance: float = 0.5) -> dict[str, Any]:
    diffs: list[dict[str, Any]] = []
    fields = [field for field in PARITY_FIELDS if field in RAW_METRIC_FIELDS or True]
    for field in fields:
        a = _num(left, field)
        b = _num(right, field)
        if a is None and b is None:
            continue
        if a is None or b is None:
            diffs.append({"field": field, "left": a, "right": b, "delta": None})
            continue
        if abs(a - b) > tolerance:
            diffs.append({"field": field, "left": a, "right": b, "delta": a - b})
    return {"match": not diffs, "diffs": diffs, "tolerance": tolerance}


def explicit_equip_metrics(engine, *, slot: str, item_raw: str, context: str = "MAP") -> dict[str, Any]:
    """Canonical PoB equip path: apply_live_equipment + recalc. Caller must reload baseline after."""
    applied = engine.apply_live_equipment([{"slot": slot, "item_raw": item_raw}])
    metrics = engine.get_metrics(context=context)
    raw = metrics.get("raw") or applied.get("metrics") or {}
    return {
        "metrics": raw,
        "fingerprint_hash": metrics.get("fingerprint_hash") or applied.get("fingerprint_hash"),
        "equipment": applied.get("equipment"),
    }


def baseline_metrics_snapshot(engine, *, context: str = "MAP") -> dict[str, Any]:
    metrics = engine.get_metrics(context=context)
    raw = metrics.get("raw") or {}
    return {
        "metrics": raw,
        "fingerprint_hash": metrics.get("fingerprint_hash"),
    }
