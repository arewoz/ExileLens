from __future__ import annotations

from typing import Any


def next_passive_recommendation(row: dict[str, Any]) -> dict[str, Any]:
    """Stable product-facing next-passive row. No Lua internals."""
    return {
        "rank": row.get("rank"),
        "node": {
            "id": row.get("node_id"),
            "name": row.get("name"),
            "type": row.get("type"),
        },
        "cost": row.get("cost"),
        "total_build_value": row.get("build_value_delta"),
        "value_per_point": row.get("value_per_point"),
        "top_metric_drivers": row.get("top_metric_drivers") or [],
        "breakpoints": row.get("breakpoints") or [],
        "warnings": row.get("warnings") or [],
        "confidence": row.get("confidence"),
    }


def tree_heatmap_data(evaluation: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Contract for Phase 5A.6 heatmap renderer. Not rendered in 5A.5."""
    return {
        "node_id": node.get("id") or node.get("node_id"),
        "x": node.get("x"),
        "y": node.get("y"),
        "allocated": node.get("allocated"),
        "reachable": evaluation.get("status") == "VALID",
        "cost": evaluation.get("cost"),
        "build_value": evaluation.get("path_value") if evaluation.get("path_value") is not None else evaluation.get("build_value_delta"),
        "value_per_point": evaluation.get("value_per_point"),
        "profile_scores": evaluation.get("profile_scores"),
        "breakpoints": evaluation.get("breakpoints") or [],
        "confidence": evaluation.get("confidence"),
        "evaluation_status": evaluation.get("status"),
        "path": evaluation.get("path") or [],
        "heatmap_source": "MY_BUILD_VALUE",
    }
