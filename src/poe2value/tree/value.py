from __future__ import annotations

from typing import Any

from poe2value.analysis.probes import score_probe_metrics
from poe2value.items.value_profiles import ValueProfile
from poe2value.tree.models import EvalStatus


def detect_tree_breakpoints(
    resist: dict[str, Any],
    warnings: list[dict[str, Any]],
    baseline_raw: dict[str, Any],
    candidate_raw: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for element, info in (resist.get("elements") or {}).items():
        state = info.get("state")
        if state in {"CAP_REACHED", "CAP_GAINED"}:
            events.append(
                {
                    "code": "RES_CAP_REACHED",
                    "element": element,
                    "state": state,
                    "label": f"{str(element).upper()} CAP RESTORED",
                }
            )
        elif state == "CAP_LOST":
            events.append(
                {
                    "code": "RES_CAP_LOST",
                    "element": element,
                    "state": state,
                    "label": f"{str(element).upper()} CAP LOST",
                }
            )
    base_cost = float(baseline_raw.get("ManaPerSecondCost") or 0)
    base_regen = float(baseline_raw.get("ManaRegenRecovery") or 0)
    cand_cost = float(candidate_raw.get("ManaPerSecondCost") or 0)
    cand_regen = float(candidate_raw.get("ManaRegenRecovery") or 0)
    if base_cost > base_regen + 0.05 and cand_cost <= cand_regen + 0.05:
        events.append(
            {
                "code": "RESOURCE_PRESSURE_REMOVED",
                "metric": "mana",
                "label": "RESOURCE PRESSURE REMOVED",
            }
        )
    codes = {w.get("code") for w in warnings}
    if "MAIN_SKILL_INVALID" in codes:
        events.append({"code": "MAIN_SKILL_INVALID", "label": "MAIN SKILL INVALID"})
    return events


def score_tree_metrics(
    baseline_raw: dict[str, Any],
    candidate_raw: dict[str, Any],
    profile: ValueProfile,
    *,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
    cost: int = 1,
) -> dict[str, Any]:
    scored = score_probe_metrics(
        baseline_raw,
        candidate_raw,
        profile,
        primary_field=primary_field,
        primary_confidence=primary_confidence,
    )
    breakpoints = detect_tree_breakpoints(
        scored["resist_caps"],
        scored["warnings"],
        baseline_raw,
        candidate_raw,
    )
    score_delta = float(scored["value"]["score_delta"])
    point_cost = max(int(cost), 0)
    value_per_point = round(score_delta / point_cost, 4) if point_cost else None
    scored["breakpoints"] = breakpoints
    scored["build_value_delta"] = score_delta
    scored["value_per_point"] = value_per_point
    scored["cost"] = point_cost
    return scored


def evaluation_payload(
    *,
    status: EvalStatus | str,
    target: dict[str, Any],
    path: list[int],
    cost: int,
    scored: dict[str, Any] | None,
    restore: dict[str, Any],
    baseline: dict[str, Any],
    node_value: float | None,
    path_value: float | None,
    confidence: str,
) -> dict[str, Any]:
    status_value = status.value if isinstance(status, EvalStatus) else str(status)
    payload = {
        "status": status_value,
        "baseline": baseline,
        "target": target,
        "path": [int(n) for n in path],
        "cost": int(cost),
        "node_value": node_value,
        "path_value": path_value,
        "build_value_delta": path_value,
        "value_per_point": None if not cost else (None if path_value is None else round(path_value / cost, 4)),
        "breakpoints": [],
        "warnings": [],
        "confidence": confidence,
        "restore_verified": bool((restore or {}).get("pass")),
        "restore": restore,
        "heuristic": True,
    }
    if scored:
        payload.update(
            {
                "metrics": scored.get("metric_profile"),
                "resist_caps": scored.get("resist_caps"),
                "warnings": scored.get("warnings") or [],
                "value": scored.get("value"),
                "breakpoints": scored.get("breakpoints") or [],
                "build_value_delta": scored.get("build_value_delta"),
                "value_per_point": scored.get("value_per_point"),
                "path_value": scored.get("build_value_delta"),
            }
        )
        if cost == 1:
            payload["node_value"] = scored.get("build_value_delta")
    return payload
