"""SURFACE-01 presentation copy helpers — headings, dedupe, verdict display."""

from __future__ import annotations

from typing import Any

_CLEAN_UPGRADE_VERDICTS = frozenset(
    {"STRONG_UPGRADE", "CLEAR_UPGRADE", "OFFENSE_UPGRADE", "DEFENSE_UPGRADE"}
)
_DOWNGRADE_VERDICTS = frozenset({"DOWNGRADE", "STRONG_DOWNGRADE"})

_GENERIC_TAGS = frozenset(
    {
        "good fit",
        "weigh tradeoffs",
        "build repair",
        "skip",
        "take it",
        "worth the risk",
        "probably skip",
        "do not take",
        "avoid unless desperate",
        "take only if clean",
        "repair only if needed",
        "fix the build",
    }
)

OFFENSE_LIMITED_FACT = "OFFENSE_LIMITED_COVERAGE"
_REPAIR_FACT_PREFIX = "REPAIR_"


def verdict_headline(verdict: str, decision: dict[str, Any] | None = None) -> str:
    decision = decision or {}
    headline = str(decision.get("headline") or "").strip()
    if verdict == "NO_CHANGE":
        return "NO MEANINGFUL CHANGE"
    if decision.get("build_repair") and verdict not in _DOWNGRADE_VERDICTS:
        return "BUILD REPAIR"
    if headline and verdict != "NO_CHANGE":
        return headline
    mapping = {
        "STRONG_UPGRADE": "STRONG UPGRADE",
        "CLEAR_UPGRADE": "CLEAR UPGRADE",
        "OFFENSE_UPGRADE": "OFFENSE UPGRADE",
        "DEFENSE_UPGRADE": "DEFENSE UPGRADE",
        "TRADEOFF": "TRADEOFF",
        "SIDEGRADE": "SIDEGRADE",
        "DOWNGRADE": "DOWNGRADE",
        "STRONG_DOWNGRADE": "STRONG DOWNGRADE",
        "UNRESOLVED": "UNRESOLVED",
        "NO_CHANGE": "NO MEANINGFUL CHANGE",
    }
    return mapping.get(verdict, verdict.replace("_", " "))


def verdict_subtitle(
    verdict: str,
    decision: dict[str, Any] | None,
    recommendation: dict[str, Any] | None,
) -> str:
    decision = decision or {}
    recommendation = recommendation or {}
    if decision.get("build_repair"):
        for item in decision.get("why_reasons") or []:
            if str(item.get("category")) != "BUILD_REPAIR" and item.get("explanation"):
                return str(item["explanation"])
        for item in decision.get("why_reasons") or []:
            if item.get("explanation"):
                return str(item["explanation"])
    if verdict == "NO_CHANGE":
        return "No meaningful change to score or guardrails."
    return str(recommendation.get("verdict_explanation") or "")


def recommendation_tag_display(headline: str, tag: str) -> str:
    cleaned = str(tag or "").strip()
    if not cleaned:
        return ""
    if cleaned.lower() == headline.lower():
        return ""
    if cleaned.lower() in _GENERIC_TAGS:
        return ""
    return cleaned


def effective_presentation_state(
    decision: dict[str, Any] | None,
    upgrade_path: dict[str, Any] | None,
) -> str:
    """Canonical state for presentation-only heading and visibility policy."""
    state = str((upgrade_path or {}).get("product_state") or "")
    if state:
        return state
    return "BUILD_REPAIR" if (decision or {}).get("build_repair") else ""


def why_section_title(
    verdict: str,
    decision: dict[str, Any] | None,
    upgrade_path: dict[str, Any] | None,
) -> str | None:
    decision = decision or {}
    upgrade_path = upgrade_path or {}
    state = effective_presentation_state(decision, upgrade_path)
    if state == "ALREADY_UPGRADE":
        return None
    if state == "BUILD_REPAIR":
        return "WHY THIS HELPS"
    if verdict in _CLEAN_UPGRADE_VERDICTS and not decision.get("build_repair"):
        return "WHY IT'S AN UPGRADE"
    if decision.get("build_repair"):
        return "WHY THIS HELPS"
    if verdict == "TRADEOFF":
        return "WHY NOT A CLEAN UPGRADE?"
    if verdict in _DOWNGRADE_VERDICTS:
        return "WHY KEEP CURRENT?"
    if verdict == "NO_CHANGE":
        return "WHY IT DOESN'T IMPROVE THE BUILD"
    if verdict in _CLEAN_UPGRADE_VERDICTS:
        return "WHY IT'S AN UPGRADE"
    return "WHY NOT UPGRADE?"


def should_show_why_not_section(
    verdict: str,
    decision: dict[str, Any] | None,
    upgrade_path: dict[str, Any] | None,
    why_not_upgrade: list[dict[str, Any]],
    *,
    current_edge: dict[str, Any] | None = None,
) -> bool:
    if not why_not_upgrade:
        return False
    if current_edge:
        return False
    decision = decision or {}
    upgrade_path = upgrade_path or {}
    state = effective_presentation_state(decision, upgrade_path)
    if state in {"ALREADY_UPGRADE", "BUILD_REPAIR"}:
        return False
    if verdict in _CLEAN_UPGRADE_VERDICTS and not decision.get("build_repair"):
        return False
    if decision.get("build_repair"):
        return False
    return why_section_title(verdict, decision, upgrade_path) is not None


def _normalize_semantic(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def fact_id_for_metric_row(row: dict[str, Any]) -> str | None:
    key = str(row.get("key") or "")
    cap_state = str(row.get("cap_state") or "")
    if not key.endswith("_res"):
        return None
    element = key.replace("_res", "").upper()
    if cap_state in {"BELOW_CAP_WORSENED", "FURTHER_BELOW_CAP"}:
        return f"RES_{element}_BELOW_CAP_WORSENED"
    if cap_state == "CAP_LOST":
        return f"RES_{element}_CAP_LOST"
    if cap_state in {"BELOW_CAP_IMPROVED", "CAP_REACHED", "CAP_GAINED"}:
        return f"RES_{element}_DEFICIT_IMPROVED"
    return None


def fact_id_for_warning(warning: dict[str, Any]) -> str | None:
    code = str(warning.get("code") or "")
    metric = str(warning.get("metric") or "")
    if metric.endswith("_res"):
        element = metric.replace("_res", "").upper()
        if code == "RES_CAP_LOST":
            return f"RES_{element}_CAP_LOST"
        if code in {"RES_DEFICIT_WORSENED", "BELOW_CAP_WORSENED"}:
            return f"RES_{element}_BELOW_CAP_WORSENED"
    return None


def fact_id_for_reason(reason: dict[str, Any]) -> str | None:
    code = str(reason.get("code") or "")
    metric = str(reason.get("metric") or "")
    if code == OFFENSE_LIMITED_FACT:
        return OFFENSE_LIMITED_FACT
    if metric.endswith("_res"):
        element = metric.replace("_res", "").upper()
        if code in {"RES_CAP_LOST", "RES_CAP_LOST"}:
            return f"RES_{element}_CAP_LOST"
        if code in {"RES_DEFICIT_WORSENED", "BELOW_CAP_WORSENED", "BELOW_CAP_WORSENED"}:
            return f"RES_{element}_BELOW_CAP_WORSENED"
    if code.startswith(_REPAIR_FACT_PREFIX):
        return code
    return None


def fact_id_for_repair_step(step: dict[str, Any]) -> str | None:
    probe_id = str(step.get("probe_id") or "")
    if probe_id == "MANA":
        return "REPAIR_MANA_REGRESSION"
    if probe_id.endswith("_RES"):
        element = probe_id.replace("_RES", "").upper()
        return f"REPAIR_{element}_RESTORE"
    return None


def assign_presentation_fact_ids(
    *,
    rows: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    why_reasons: list[dict[str, Any]],
    why_not_upgrade: list[dict[str, Any]],
    upgrade_path: dict[str, Any] | None,
    current_edge: dict[str, Any] | None,
) -> None:
    for row in rows:
        fact_id = fact_id_for_metric_row(row)
        if fact_id:
            row["fact_id"] = fact_id
    for warning in warnings:
        fact_id = fact_id_for_warning(warning)
        if fact_id:
            warning["fact_id"] = fact_id
    for block in (*why_reasons, *why_not_upgrade):
        fact_id = fact_id_for_reason(block)
        if fact_id:
            block["fact_id"] = fact_id
    repair_steps = list((upgrade_path or {}).get("repair_steps") or [])
    for step in repair_steps:
        fact_id = fact_id_for_repair_step(step)
        if fact_id:
            step["fact_id"] = fact_id
    if current_edge and repair_steps:
        edge_lines: list[dict[str, Any]] = []
        for step in repair_steps[:3]:
            line = str(step.get("line") or "")
            if not line:
                continue
            edge_lines.append({"text": line, "fact_id": step.get("fact_id")})
        if edge_lines:
            current_edge["lines"] = edge_lines


def apply_presentation_dedupe(
    *,
    rows: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    why_reasons: list[dict[str, Any]],
    why_not_upgrade: list[dict[str, Any]],
    current_edge: dict[str, Any] | None = None,
    offense_summary: str = "",
    compact_notes: list[str] | None = None,
    upgrade_path: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    assign_presentation_fact_ids(
        rows=rows,
        warnings=warnings,
        why_reasons=why_reasons,
        why_not_upgrade=why_not_upgrade,
        upgrade_path=upgrade_path,
        current_edge=current_edge,
    )

    claimed: set[str] = set()
    for row in rows:
        fact_id = str(row.get("fact_id") or "")
        if fact_id:
            claimed.add(fact_id)

    repair_facts: set[str] = set()
    for step in (upgrade_path or {}).get("repair_steps") or []:
        fact_id = str(step.get("fact_id") or "")
        if fact_id:
            repair_facts.add(fact_id)
            claimed.add(fact_id)

    filtered_warnings: list[dict[str, Any]] = []
    for warning in warnings:
        fact_id = str(warning.get("fact_id") or "")
        if fact_id and fact_id in claimed:
            continue
        if fact_id:
            claimed.add(fact_id)
        filtered_warnings.append(warning)

    filtered_why: list[dict[str, Any]] = []
    for reason in why_reasons:
        fact_id = str(reason.get("fact_id") or "")
        code = str(reason.get("code") or "")
        if fact_id and fact_id in claimed:
            continue
        if code.startswith(_REPAIR_FACT_PREFIX):
            continue
        filtered_why.append(reason)

    filtered_why_not: list[dict[str, Any]] = []
    for reason in why_not_upgrade:
        fact_id = str(reason.get("fact_id") or "")
        code = str(reason.get("code") or "")
        if fact_id and (fact_id in claimed or fact_id in repair_facts):
            continue
        if code.startswith(_REPAIR_FACT_PREFIX) or code.startswith("KEEP_CURRENT"):
            continue
        filtered_why_not.append(reason)

    notes = list(compact_notes or [])
    if offense_summary:
        notes = [note for note in notes if "Offense comparison limited" not in note]

    return filtered_warnings, filtered_why, filtered_why_not, notes


def dedupe_reason_blocks(
    reasons: list[dict[str, Any]],
    *,
    rows: list[dict[str, Any]] | None = None,
    other_blocks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    covered: set[str] = set()
    for row in rows or []:
        cap = str(row.get("cap_label") or "")
        label = str(row.get("label") or "")
        if cap:
            covered.add(_normalize_semantic(cap))
        if label:
            covered.add(_normalize_semantic(label))
    for block in other_blocks or []:
        explanation = _normalize_semantic(str(block.get("explanation") or ""))
        if explanation:
            covered.add(explanation)

    filtered: list[dict[str, Any]] = []
    for reason in reasons:
        explanation = _normalize_semantic(str(reason.get("explanation") or ""))
        if not explanation:
            continue
        if any(explanation in existing or existing in explanation for existing in covered if len(existing) > 8):
            continue
        filtered.append(reason)
        covered.add(explanation)
    return filtered


def dedupe_warnings(
    warnings: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    why_reasons: list[dict[str, Any]],
    why_not_upgrade: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    covered: set[str] = set()
    for row in rows:
        cap = str(row.get("cap_label") or "")
        label = str(row.get("label") or "")
        if cap:
            covered.add(_normalize_semantic(cap))
        if label:
            covered.add(_normalize_semantic(label))
    for block in (*why_reasons, *why_not_upgrade):
        explanation = _normalize_semantic(str(block.get("explanation") or ""))
        if explanation:
            covered.add(explanation)
        code = str(block.get("code") or "").lower()
        if code:
            covered.add(code)

    filtered: list[dict[str, Any]] = []
    for warning in warnings:
        text = _normalize_semantic(str(warning.get("text") or ""))
        code = str(warning.get("code") or "").lower()
        if text and any(text in existing or existing in text for existing in covered if len(existing) > 8):
            continue
        if code and code in covered:
            continue
        filtered.append(warning)
        if text:
            covered.add(text)
    return filtered


def apply_passive_aux_companion_policy(model: dict[str, Any]) -> None:
    """Split a passive-overlay model into primary tooltip + Companion analysis.

    This is the copy policy for the passive surface: the tooltip keeps the decision
    (score, a handful of deltas, the strongest reasons, critical warnings, the verdict)
    and the Companion receives every section that would otherwise explain the same
    conclusion a second time further down the tooltip.
    """
    from exilelens.items.compact_tooltip import apply_compact_tooltip

    apply_compact_tooltip(model)
