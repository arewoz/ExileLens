"""Lazy baseline item contribution — remove slot item, recalc, restore."""

from __future__ import annotations

import time
from typing import Any

from exilelens.metrics import build_metric_profile


def analyze_baseline_item_contribution(
    engine: Any,
    slot: str,
    *,
    build_path: str = "",
    context: str = "MAP",
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
) -> dict[str, Any]:
    """Remove the equipped item in slot, measure metrics, restore. Lazy/deep only."""
    started = time.perf_counter()
    if build_path:
        engine.ensure_build_ready(build_path, context=context)
    evaluation = engine.evaluate_slot_cleared(slot, context=context)
    restore = evaluation.get("restore") or {}
    if not restore.get("pass"):
        return {
            "ok": False,
            "slot": slot,
            "status": "RESTORE_FAILED",
            "restore": restore,
            "elapsed_ms": (time.perf_counter() - started) * 1000,
        }
    baseline_raw = (evaluation.get("baseline") or {}).get("metrics") or {}
    cleared_raw = (evaluation.get("cleared") or {}).get("metrics") or {}
    profile = build_metric_profile(
        baseline_raw,
        cleared_raw,
        primary_field=primary_field,
        confidence=primary_confidence,
    )
    return {
        "ok": True,
        "slot": slot,
        "status": "COMPLETE",
        "metric_profile": profile,
        "baseline_metrics": baseline_raw,
        "without_item_metrics": cleared_raw,
        "restore": restore,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
