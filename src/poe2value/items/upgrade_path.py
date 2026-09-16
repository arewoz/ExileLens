"""ITEM-PRO-01A upgrade path presentation and eligibility (no PoB)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from poe2value.items.decision import RecommendationStyle
from poe2value.items.presentation_copy import dedupe_reason_blocks, should_show_why_not_section, why_section_title


class UpgradePathState(str, Enum):
    ALREADY_UPGRADE = "ALREADY_UPGRADE"
    BUILD_REPAIR = "BUILD_REPAIR"
    NEAR_MISS = "NEAR_MISS"
    TRADEOFF = "TRADEOFF"
    REPAIRABLE_DOWNGRADE = "REPAIRABLE_DOWNGRADE"
    NOT_CLOSE = "NOT_CLOSE"
    PENDING = "PENDING"


_CLEAN_UPGRADE_VERDICTS = frozenset({"STRONG_UPGRADE", "CLEAR_UPGRADE", "OFFENSE_UPGRADE", "DEFENSE_UPGRADE"})
_PROBE_VERDICTS = frozenset({"TRADEOFF", "SIDEGRADE", "DOWNGRADE", "UNRESOLVED", "NO_CHANGE"})
_EXTREME_DOWNGRADE_RATING = 28.0
_NEAR_MISS_RATING_LOW = 42.0
_NEAR_MISS_RATING_HIGH = 58.0
_CRITICAL_WARNING_CODES = frozenset({"RES_CAP_LOST", "RES_DEFICIT_WORSENED", "RESOURCE_FAILURE", "MAIN_SKILL_INVALID"})
_UPGRADE_VERDICTS = frozenset({"STRONG_UPGRADE", "CLEAR_UPGRADE", "OFFENSE_UPGRADE", "DEFENSE_UPGRADE"})
_LIMITED_COVERAGE_STATES = frozenset(
    {
        "LIMITED",
        "UNAVAILABLE",
        "INSENSITIVE",
        "PARTIAL",
    }
)
_UPGRADE_DISTANCE_LABELS = {
    UpgradePathState.ALREADY_UPGRADE.value: "ALREADY UPGRADE",
    UpgradePathState.BUILD_REPAIR.value: "BUILD FIX",
    UpgradePathState.NEAR_MISS.value: "NEAR MISS",
    UpgradePathState.TRADEOFF.value: "REPAIRABLE",
    UpgradePathState.REPAIRABLE_DOWNGRADE.value: "REPAIRABLE",
    UpgradePathState.NOT_CLOSE.value: "FAR",
    UpgradePathState.PENDING.value: "ANALYZING",
}


def normalize_upgrade_mode(value: str | None) -> str:
    raw = str(value or "").upper()
    if raw in {"OFF", "AUTO", "AUTO_DEEP"}:
        return raw
    if raw == "MANUAL":
        return "OFF"
    if raw in {"AUTO_NEAR_MISS", "AUTO_SMART"}:
        return "AUTO_DEEP"
    return "AUTO"


def classify_upgrade_path_state(result: dict[str, Any], *, style: str = RecommendationStyle.BALANCED.value) -> str:
    recommendation = result.get("recommendation") or {}
    decision = result.get("decision") or {}
    verdict = str(recommendation.get("verdict") or "UNRESOLVED")
    value = recommendation.get("value") or {}
    rating = float(value.get("rating") or 0.0)
    tag = str(decision.get("recommendation_tag") or "").upper()
    keep_tags = {"KEEP", "KEEP_CURRENT", "VENDOR", "SKIP"}

    if verdict in _CLEAN_UPGRADE_VERDICTS and tag not in keep_tags:
        return UpgradePathState.ALREADY_UPGRADE.value
    if decision.get("build_repair") and tag not in keep_tags:
        return UpgradePathState.BUILD_REPAIR.value

    warnings = recommendation.get("warnings") or []
    codes = {str(item.get("code")) for item in warnings}
    has_critical_repair = bool(codes & _CRITICAL_WARNING_CODES)
    if verdict in {"STRONG_DOWNGRADE", "DOWNGRADE"} and rating < _EXTREME_DOWNGRADE_RATING and not has_critical_repair:
        return UpgradePathState.NOT_CLOSE.value
    if verdict in _PROBE_VERDICTS or has_critical_repair:
        if rating < _EXTREME_DOWNGRADE_RATING and not has_critical_repair:
            return UpgradePathState.NOT_CLOSE.value
        if _NEAR_MISS_RATING_LOW <= rating < _NEAR_MISS_RATING_HIGH:
            return UpgradePathState.NEAR_MISS.value
        if verdict in {"TRADEOFF", "SIDEGRADE"}:
            return UpgradePathState.TRADEOFF.value
        return UpgradePathState.REPAIRABLE_DOWNGRADE.value
    return UpgradePathState.NOT_CLOSE.value


def build_why_not_upgrade(result: dict[str, Any]) -> list[dict[str, Any]]:
    decision = result.get("decision") or {}
    recommendation = result.get("recommendation") or {}
    blocks: list[dict[str, Any]] = []
    for item in decision.get("keep_current_reasons") or []:
        blocks.append(
            {
                "explanation": item.get("explanation"),
                "severity": item.get("severity") or "high",
                "code": item.get("code"),
            }
        )
    for item in decision.get("why_reasons") or []:
        if str(item.get("direction")) == "down" or str(item.get("severity")) in {"critical", "high"}:
            blocks.append(
                {
                    "explanation": item.get("explanation"),
                    "severity": item.get("severity") or "medium",
                    "code": item.get("code"),
                }
            )
    for warning in recommendation.get("warnings") or []:
        code = str(warning.get("code") or "")
        if code in _CRITICAL_WARNING_CODES:
            metric = str(warning.get("metric") or "")
            before = warning.get("before")
            after = warning.get("after")
            if before is not None and after is not None and metric.endswith("_res"):
                element = metric.replace("_res", "").replace("_", " ").title()
                blocks.append(
                    {
                        "explanation": f"{element} Res {before:g} → {after:g}",
                        "severity": "critical",
                        "code": code,
                    }
                )
            elif warning.get("detail"):
                blocks.append({"explanation": warning.get("detail"), "severity": "critical", "code": code})
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in blocks:
        key = str(item.get("explanation") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:4]


def _short_repair_label(label: str) -> str:
    text = str(label or "").strip().replace("_", " ")
    for suffix in (" Resistance", " Resist"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def format_repair_step_token(item: dict[str, Any]) -> str:
    label = _short_repair_label(str(item.get("label") or item.get("probe_id") or "stat"))
    magnitude = item.get("magnitude")
    unit = str(item.get("unit") or "")
    if magnitude is not None:
        if unit == "percent":
            return f"+{magnitude:g}% {label}"
        return f"+{magnitude:g} {label}"
    return label


def format_repair_passive_line(repair_steps: list[dict[str, Any]]) -> str:
    if not repair_steps:
        return ""
    parts: list[str] = []
    for step in repair_steps[:3]:
        token = str(step.get("passive_token") or format_repair_step_token(step))
        if step.get("blocker_reason"):
            parts.append(f"{token} · restore baseline")
        else:
            parts.append(token)
    return f"Repair: {', '.join(parts)}"


def format_after_repair_line(after_repair: dict[str, Any] | None) -> str:
    if not after_repair:
        return ""
    rating_text = str(after_repair.get("rating_text") or "").strip()
    if not rating_text:
        return ""
    verdict_text = str(after_repair.get("verdict_text") or "").strip()
    line = f"After repair: {rating_text}"
    if verdict_text:
        line += f" · {verdict_text}"
    return line


def _not_close_passive_line(block: dict[str, Any]) -> str:
    conclusion = str(block.get("compact_conclusion") or "").strip()
    if conclusion:
        return conclusion
    return "No tested improvement reached an upgrade"


def _pending_passive_line(block: dict[str, Any]) -> str:
    summary = str(block.get("summary") or "").strip()
    if summary and "..." not in summary:
        return summary
    return "Analyzing repair path"


def _passive_fallback_line(block: dict[str, Any]) -> str:
    product_state = str(block.get("product_state") or "")
    if product_state == UpgradePathState.PENDING.value:
        return _pending_passive_line(block)
    if product_state == UpgradePathState.NOT_CLOSE.value:
        return _not_close_passive_line(block)
    if product_state == UpgradePathState.ALREADY_UPGRADE.value:
        return "Already an upgrade"
    summary = str(block.get("summary") or "").strip()
    if summary and "..." not in summary:
        return summary
    return ""


def _format_path_line(path: dict[str, Any]) -> str:
    label = str(path.get("label") or path.get("probe_id") or "stat")
    magnitude = path.get("magnitude")
    unit = str(path.get("unit") or "")
    if magnitude is not None:
        if unit == "percent":
            return f"+{magnitude:g}% {label}"
        return f"+{magnitude:g} {label}"
    return label


def _format_verdict_short(verdict: str) -> str:
    mapping = {
        "STRONG_UPGRADE": "Strong Upgrade",
        "CLEAR_UPGRADE": "Upgrade",
        "OFFENSE_UPGRADE": "Offense Upgrade",
        "DEFENSE_UPGRADE": "Defense Upgrade",
        "TRADEOFF": "Tradeoff",
        "SIDEGRADE": "Sidegrade",
        "DOWNGRADE": "Downgrade",
        "STRONG_DOWNGRADE": "Strong Downgrade",
        "NO_CHANGE": "No Change",
        "UNRESOLVED": "Unresolved",
    }
    key = str(verdict or "UNRESOLVED").upper()
    return mapping.get(key, key.replace("_", " ").title())


def upgrade_distance_label(product_state: str, offense_coverage: dict[str, Any] | None = None) -> str:
    state = str((offense_coverage or {}).get("state") or "")
    if state in _LIMITED_COVERAGE_STATES and product_state in {
        UpgradePathState.NOT_CLOSE.value,
        UpgradePathState.PENDING.value,
    }:
        return "UNKNOWN · limited coverage"
    return _UPGRADE_DISTANCE_LABELS.get(product_state, str(product_state or "").replace("_", " "))


def build_repair_steps(repair_vector: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for item in repair_vector[:3]:
        blocker = item.get("blocker") if isinstance(item.get("blocker"), dict) else {}
        steps.append(
            {
                "line": _format_path_line(item),
                "passive_token": format_repair_step_token(item),
                "label": item.get("label"),
                "magnitude": item.get("magnitude"),
                "probe_id": item.get("probe_id"),
                "blocker_reason": item.get("blocker_reason") or blocker.get("reason") or blocker.get("blocker_reason"),
            }
        )
    return steps


def build_after_repair_preview(
    *,
    current_rating: float | None,
    current_verdict: str | None,
    repaired_rating: float | None,
    repaired_verdict: str | None,
) -> dict[str, Any] | None:
    if repaired_rating is None or not repaired_verdict:
        return None
    rating_text = ""
    if current_rating is not None:
        rating_text = f"{current_rating:g} → {repaired_rating:g}"
    else:
        rating_text = f"{repaired_rating:g}"
    current_v = str(current_verdict or "")
    repaired_v = str(repaired_verdict or "")
    if current_v and current_v == repaired_v:
        verdict_text = f"Still {_format_verdict_short(repaired_v)}"
    elif current_v:
        verdict_text = f"{_format_verdict_short(current_v)} → {_format_verdict_short(repaired_v)}"
    else:
        verdict_text = _format_verdict_short(repaired_v)
    compact_line = format_after_repair_line(
        {
            "rating_text": rating_text,
            "verdict_text": verdict_text,
        }
    )
    return {
        "current_rating": current_rating,
        "current_verdict": current_v or None,
        "repaired_rating": repaired_rating,
        "repaired_verdict": repaired_v,
        "rating_text": rating_text,
        "verdict_text": verdict_text,
        "compact_line": compact_line,
    }


def build_compact_conclusion(
    potential: dict[str, Any],
    *,
    offense_coverage: dict[str, Any] | None = None,
) -> str:
    product_state = str(potential.get("product_state") or "")
    if product_state != UpgradePathState.NOT_CLOSE.value:
        return ""
    offense_state = str((offense_coverage or {}).get("state") or "")
    reason = str(potential.get("not_close_reason") or potential.get("message") or "")
    secondary = [str(item) for item in (potential.get("secondary_attempted") or [])]
    cast_speed_claimed = any("cast speed" in item.lower() for item in secondary) or "Cast Speed" in reason
    if offense_state in _LIMITED_COVERAGE_STATES and cast_speed_claimed:
        return "Offensive paths not reliably measured."
    if offense_state in _LIMITED_COVERAGE_STATES and "No reasonable Cast Speed" in reason:
        return "Offensive paths not reliably measured."
    if reason and len(reason) <= 88 and "No reasonable Cast Speed" not in reason:
        return reason
    remaining = list(potential.get("remaining_losses") or [])
    if remaining:
        return f"Multiple defensive losses remain: {', '.join(remaining[:2])}"
    return ""


def compact_upgrade_summary(block: dict[str, Any]) -> str:
    """Passive overlay copy — up to two complete semantic lines, never truncated."""
    repair_steps = list(block.get("repair_steps") or [])
    after_repair = block.get("after_repair") or {}
    lines: list[str] = []

    repair_line = format_repair_passive_line(repair_steps)
    if repair_line:
        lines.append(repair_line)
        after_line = format_after_repair_line(after_repair)
        if after_line:
            lines.append(after_line)

    if not lines:
        fallback = _passive_fallback_line(block)
        if fallback:
            lines.append(fallback)

    return "\n".join(lines[:2])


def build_upgrade_path_block(
    result: dict[str, Any],
    *,
    potential: dict[str, Any] | None = None,
    pending: bool = False,
    style: str = RecommendationStyle.BALANCED.value,
) -> dict[str, Any]:
    recommendation = result.get("recommendation") or {}
    decision = result.get("decision") or {}
    potential = potential or result.get("upgrade_potential") or {}
    product_state = str(potential.get("product_state") or classify_upgrade_path_state(result, style=style))
    status = str(potential.get("status") or ("PENDING" if pending else "COMPLETE"))
    why_not = potential.get("why_not_upgrade") or build_why_not_upgrade(result)
    paths = list(potential.get("paths") or potential.get("thresholds") or [])
    compact_paths = [_format_path_line(item) for item in paths[:2]]
    target_label = _target_label(style)
    headline = "UPGRADE PATH"
    summary = ""
    detail_lines: list[str] = []

    if status == "PENDING" or pending:
        phase = str(potential.get("progress_phase") or "")
        if phase == "verify_repair":
            summary = "Testing resistance repair"
        elif phase == "secondary_search":
            summary = "Searching final improvement"
        elif phase == "identify_blockers":
            summary = "Analyzing main blocker"
        else:
            summary = potential.get("message") or "Analyzing main blocker"
    elif product_state == UpgradePathState.ALREADY_UPGRADE.value:
        summary = "Already an upgrade. No repair required."
    elif product_state == UpgradePathState.BUILD_REPAIR.value:
        repair_bits = [item.get("explanation") for item in (decision.get("why_reasons") or []) if item.get("category") == "BUILD_REPAIR"]
        fix = repair_bits[0] if repair_bits else "build constraint"
        summary = f"Already fixes: {fix}. No repair required for current recommendation."
    elif paths:
        repair_paths = [item for item in paths if item.get("kind") != "secondary"]
        secondary_paths = [item for item in paths if item.get("kind") == "secondary"]
        if repair_paths and secondary_paths:
            repair_text = " + ".join(_format_path_line(item) for item in repair_paths[:2])
            secondary_text = _format_path_line(secondary_paths[0])
            summary = f"{repair_text} then {secondary_text} → CLEAN UPGRADE"
        else:
            joined = " + ".join(_format_path_line(item) for item in paths[:2])
            summary = f"{joined} → CLEAN UPGRADE"
        for idx, path in enumerate(paths[:3], start=1):
            line = _format_path_line(path)
            consequence = path.get("consequence") or path.get("message") or ""
            rating = path.get("result_rating")
            detail = f"{idx}. {line}"
            if rating is not None and path.get("kind") != "secondary":
                detail += f" · Build Value {rating:g}"
            if consequence:
                detail += f" · {consequence}"
            detail_lines.append(detail)
    elif product_state == UpgradePathState.NOT_CLOSE.value:
        reason = str(potential.get("not_close_reason") or potential.get("message") or "").strip()
        repair_vector = list(potential.get("repair_vector") or [])
        if reason:
            summary = reason
        elif repair_vector:
            tested = ", ".join(_format_path_line(item) for item in repair_vector[:3])
            summary = f"Not close — tested {tested}"
        else:
            summary = "Not close within tested bounds."
        if repair_vector:
            detail_lines.append("Repairs tested: " + ", ".join(_format_path_line(item) for item in repair_vector[:3]))
        repaired_rating = potential.get("repaired_rating")
        repaired_verdict = potential.get("repaired_verdict")
        if repaired_rating is not None and repaired_verdict:
            detail_lines.append(
                f"Best repaired result: {str(repaired_verdict).replace('_', ' ').title()} · Build Value {repaired_rating:g}"
            )
    else:
        summary = potential.get("message") or "No reachable repair threshold found."

    offense_coverage = result.get("offense_coverage") or recommendation.get("offense_coverage") or {}
    repair_vector = list(potential.get("repair_vector") or [])
    if not repair_vector and paths:
        repair_vector = [item for item in paths if item.get("kind") != "secondary"][:3]
    current_value = recommendation.get("value") or {}
    current_rating = current_value.get("rating")
    current_verdict = str(recommendation.get("verdict") or "")
    repair_steps = build_repair_steps(repair_vector)
    after_repair = build_after_repair_preview(
        current_rating=float(current_rating) if current_rating is not None else None,
        current_verdict=current_verdict,
        repaired_rating=potential.get("repaired_rating"),
        repaired_verdict=str(potential.get("repaired_verdict") or "") or None,
    )
    upgrade_distance = upgrade_distance_label(product_state, offense_coverage)
    compact_conclusion = build_compact_conclusion(potential, offense_coverage=offense_coverage)

    compact_block = {
        "summary": summary,
        "product_state": product_state,
        "not_close_reason": str(potential.get("not_close_reason") or ""),
        "repair_steps": repair_steps,
        "after_repair": after_repair,
        "compact_conclusion": compact_conclusion,
        "pending": status == "PENDING" or pending,
    }

    return {
        "title": headline,
        "status": status,
        "product_state": product_state,
        "summary": summary,
        "summary_compact": compact_upgrade_summary(compact_block),
        "compact_paths": compact_paths,
        "paths": paths,
        "detail_lines": detail_lines,
        "why_not_upgrade": why_not,
        "target_label": target_label,
        "craft_legality_verified": bool(potential.get("craft_legality_verified")),
        "hypothetical_note": "Hypothetical stat change" if not potential.get("craft_legality_verified", False) else "",
        "probes_run": int(potential.get("probes_run") or 0),
        "paths_tested": int(potential.get("paths_tested") or 0),
        "solver_kind": str(potential.get("solver_kind") or ""),
        "not_close_reason": str(potential.get("not_close_reason") or ""),
        "pending": status == "PENDING" or pending,
        "repair_steps": repair_steps,
        "after_repair": after_repair,
        "upgrade_distance": upgrade_distance,
        "compact_conclusion": compact_conclusion,
    }


def attach_upgrade_path_presentation(
    result: dict[str, Any],
    *,
    pending: bool = False,
    style: str = RecommendationStyle.BALANCED.value,
) -> dict[str, Any]:
    block = build_upgrade_path_block(result, pending=pending, style=style)
    result = dict(result)
    presentation = dict(result.get("presentation") or {})
    presentation["upgrade_path"] = block
    why_not = list(block.get("why_not_upgrade") or [])
    verdict = str((result.get("recommendation") or {}).get("verdict") or "UNRESOLVED")
    decision = result.get("decision") or {}
    why_title = why_section_title(verdict, decision, block)
    why_not = dedupe_reason_blocks(
        why_not,
        rows=list(presentation.get("rows") or []),
        other_blocks=list(presentation.get("why_reasons") or []),
    )
    show_why_not = should_show_why_not_section(
        verdict,
        decision,
        block,
        why_not,
        current_edge=presentation.get("current_edge"),
    )
    presentation["why_not_upgrade"] = why_not if show_why_not else []
    presentation["why_section_title"] = why_title or ""
    from poe2value.items.presentation import sync_presentation_current_edge

    sync_presentation_current_edge(presentation, result)
    sections = list(presentation.get("sections") or [])
    if not any(item.get("id") == "upgrade_path" for item in sections):
        sections.append({"id": "upgrade_path", "visible": True})
    if not any(item.get("id") == "why_not_upgrade" for item in sections):
        sections.append({"id": "why_not_upgrade", "visible": show_why_not})
    presentation["sections"] = sections
    presentation["section_ids"] = [item["id"] for item in sections if item.get("visible")]
    result["presentation"] = presentation
    result["upgrade_path"] = block
    return result


def history_upgrade_path_hint(result: dict[str, Any]) -> str:
    block = result.get("upgrade_path") or build_upgrade_path_block(result)
    state = block.get("product_state")
    if state == UpgradePathState.ALREADY_UPGRADE.value:
        return "No repair needed"
    if block.get("pending"):
        return "Upgrade path: analyzing"
    if block.get("compact_paths"):
        return f"Upgrade path: {block['compact_paths'][0]}"
    if state == UpgradePathState.NOT_CLOSE.value:
        return "Not close"
    return str(block.get("summary") or "")


def _target_label(style: str) -> str:
    normalized = str(style or RecommendationStyle.BALANCED.value).upper()
    if normalized == RecommendationStyle.AGGRESSIVE.value:
        return "TO BECOME AN AGGRESSIVE UPGRADE"
    if normalized == RecommendationStyle.STRICT.value:
        return "TO BECOME A STRICT UPGRADE"
    return "TO BECOME A BALANCED UPGRADE"
