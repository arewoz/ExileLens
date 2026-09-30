"""Build a sanitized replay fixture from a real ``evaluate_item`` result (needs a PoB run to produce the input).

Only measured numbers and the small set of evidence blocks the policy reads are kept. Item text, item names,
equipment, fingerprints, paths and the build identity are dropped.
"""

from __future__ import annotations

import copy
from typing import Any

# Slot-row keys the verdict policy reads (see ranking.enrich_slot_comparison / evaluation_outcome.assess_quality).
_ROW_KEYS = (
    "pob_slot", "product_slot", "restore", "baseline_primary_metric", "native_damage_discovery",
    "main_skill_diagnostic", "unmodeled_item_transform", "stonefist_baseline_note", "ailment_breakdown",
)


def capture_fixture(
    result: dict[str, Any], row: dict[str, Any], *, fixture_id: str, description: str, source: str,
) -> dict[str, Any]:
    outcome = row["evaluation_outcome"]
    comparison: dict[str, Any] = {key: copy.deepcopy(row[key]) for key in _ROW_KEYS if row.get(key) is not None}
    comparison["baseline"] = {"metrics": copy.deepcopy(row["baseline"]["metrics"])}
    comparison["candidate"] = {
        "metrics": copy.deepcopy(row["candidate"]["metrics"]),
        "item_present": (row.get("candidate") or {}).get("item_present", True),
    }
    comparison["baseline_item"] = {"empty": bool((row.get("baseline_item") or {}).get("empty"))}
    primary = result.get("primary_metric") or {}
    impact = outcome.get("item_impact") or {}
    return {
        "id": fixture_id,
        "description": description,
        "source": source,
        "primary_field": primary.get("pob_field") or "CombinedDPS",
        "primary_confidence": primary.get("confidence") or "high",
        "offense_coverage": copy.deepcopy(result.get("offense_coverage")),
        "comparison": comparison,
        "recorded": {
            "verdict": outcome["verdict"],
            "evaluation_quality": outcome["evaluation_quality"],
            "raw_score": outcome["raw_score"],
            "final_score": outcome["final_score"],
            "verdict_reason": outcome["verdict_reason"],
            "guardrails": sorted(g["code"] for g in outcome.get("guardrails_applied") or []),
            "pattern": impact.get("pattern"),
        },
    }
