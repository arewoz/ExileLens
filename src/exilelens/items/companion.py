"""Detailed analysis payload for the Companion card.

The primary tooltip answers "is this good, and why" in a couple of seconds. Everything
that explains the answer at length — the full axis breakdown, trade-offs, mod importance,
the whole current-item case, the upgrade path, the raw PoB before/after figures, coverage
limits and diagnostics — belongs here.

This module never re-derives semantics. It reads the finished presentation model and
arranges the analysis the evaluation already produced, so compressing the tooltip cannot
cost the product any analysis: it only moves where the analysis is read.
"""

from __future__ import annotations

from typing import Any

COMPANION_TITLE = "DETAILED ANALYSIS"

# Section ids, in the order the Companion renders them.
COMPANION_SECTION_ORDER = (
    "score",
    "axes",
    "tradeoffs",
    "important_mods",
    "current_case",
    "upgrade_path",
    "pob_values",
    "risk",
    "coverage",
    "diagnostics",
)


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("text", "detail", "explanation", "line", "label"):
            value = item.get(key)
            if value:
                return str(value).strip()
        return ""
    return str(item or "").strip()


def _lines_of(items: Any, *, limit: int | None = None, bullet: str = "") -> list[str]:
    lines: list[str] = []
    for item in list(items or []):
        text = _text_of(item)
        if not text or text in lines:
            continue
        lines.append(f"{bullet}{text}" if bullet else text)
        if limit is not None and len(lines) >= limit:
            break
    return lines


def _score_section(model: dict[str, Any]) -> dict[str, Any] | None:
    """Final score, evaluation quality and why — all read from the EvaluationOutcome."""
    outcome = model.get("evaluation_outcome") or {}
    if not outcome:
        return None
    lines: list[str] = []
    final = outcome.get("final_score")
    if final is not None:
        lines.append(f"Score {float(final):.0f} / 100")
    quality = str(outcome.get("quality_label") or "").strip()
    reasons = [str(item.get("detail") or "").strip() for item in outcome.get("evaluation_quality_reasons") or []]
    reasons = [reason for reason in reasons if reason]
    if quality:
        lines += [f"{quality}: {reason}" for reason in reasons] or [quality]
    elif outcome.get("verdict_reason"):
        lines.append(str(outcome["verdict_reason"]))
    if not lines:
        return None
    return {"id": "score", "title": "SCORE", "lines": lines}


def _axes_section(model: dict[str, Any]) -> dict[str, Any] | None:
    rows = list(model.get("axis_rows") or [])
    if not rows:
        return None
    lines: list[str] = []
    for row in rows:
        text = _text_of(row)
        if not text:
            continue
        range_text = str(row.get("range_text") or "").strip() if isinstance(row, dict) else ""
        lines.append(f"{text}   {range_text}".rstrip() if range_text else text)
    if not lines:
        return None
    return {"id": "axes", "title": "AXES", "lines": lines}


def _tradeoff_section(model: dict[str, Any]) -> dict[str, Any] | None:
    lines = _lines_of(model.get("tradeoff_lines"), bullet="• ")
    lines += [
        line
        for line in _lines_of(model.get("hard_problems"), bullet="• ")
        if line not in lines
    ]
    if not lines:
        return None
    return {"id": "tradeoffs", "title": "TRADE-OFFS", "lines": lines}


def _important_mods_section(model: dict[str, Any]) -> dict[str, Any] | None:
    rows = list(model.get("important_mods") or [])
    lines = []
    for row in rows:
        label = _text_of(row)
        if not label:
            continue
        stars = str(row.get("stars") or "").strip() if isinstance(row, dict) else ""
        lines.append(f"{stars}  {label}".strip())
    if not lines:
        return None
    return {"id": "important_mods", "title": "MOST IMPORTANT ON THIS ITEM", "lines": lines}


def _current_case_section(model: dict[str, Any]) -> dict[str, Any] | None:
    """The full case for keeping the current item — not just the three headline lines."""
    edge = model.get("current_edge") or {}
    lines = _lines_of(edge.get("lines"), bullet="• ")
    lines += [
        line
        for line in _lines_of(model.get("why_not_upgrade"), bullet="• ")
        if line not in lines
    ]
    lines += [
        line
        for line in _lines_of(model.get("why_reasons"), bullet="• ")
        if line not in lines
    ]
    if not lines:
        return None
    title = str(edge.get("title") or model.get("why_section_title") or "WHY CURRENT WINS")
    return {"id": "current_case", "title": title, "lines": lines}


def _upgrade_path_section(model: dict[str, Any]) -> dict[str, Any] | None:
    block = model.get("upgrade_path") or {}
    if not block:
        return None
    lines: list[str] = []
    summary = str(block.get("summary") or block.get("summary_compact") or "").strip()
    if summary:
        lines.append(summary)
    for step in list(block.get("repair_steps") or []):
        text = _text_of(step)
        if text and text not in lines:
            lines.append(f"• {text}")
    after = (block.get("after_repair") or {}).get("compact_line")
    if after:
        lines.append(f"After repair: {after}")
    note = str(block.get("hypothetical_note") or "").strip()
    if note:
        lines.append(note)
    fixes = _lines_of(model.get("build_fixes"))
    lines += [line for line in fixes if line not in lines]
    if not lines:
        return None
    return {"id": "upgrade_path", "title": str(block.get("title") or "UPGRADE PATH"), "lines": lines}


def _pob_values_section(model: dict[str, Any]) -> dict[str, Any] | None:
    """Raw PoB before → after for every measured metric, not only the displayed ones."""
    lines: list[str] = []
    for row in list(model.get("rows") or []):
        label = str(row.get("label") or row.get("key") or "").strip()
        range_text = str(row.get("range_text") or "").strip()
        delta_text = str(row.get("delta_text") or "").strip()
        if not label or not (range_text or delta_text):
            continue
        parts = [part for part in (range_text, delta_text) if part]
        lines.append(f"{label}: {'  '.join(parts)}")
    if not lines:
        return None
    return {"id": "pob_values", "title": "POB VALUES (BEFORE → AFTER)", "lines": lines}


def _risk_section(model: dict[str, Any]) -> dict[str, Any] | None:
    risk = model.get("risk_summary") or {}
    lines = [
        str(value).strip()
        for value in (risk.get("level"), risk.get("label"), risk.get("detail"))
        if str(value or "").strip()
    ]
    warnings = _lines_of(
        [item for group in (model.get("warning_groups") or []) for item in (group.get("items") or [])],
        bullet="• ",
    )
    lines += [line for line in warnings if line not in lines]
    if not lines:
        return None
    return {"id": "risk", "title": "RISK", "lines": lines}


def _coverage_section(model: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[str] = []
    summary = str(model.get("offense_summary") or "").strip()
    if summary:
        lines.append(f"Offense: {summary}")
    coverage = model.get("offense_coverage") or {}
    state = str(coverage.get("state") or "").strip()
    if state:
        lines.append(f"Offense coverage: {state}")
    for note in _lines_of(model.get("compact_notes")):
        if note not in lines:
            lines.append(note)
    for badge in list(model.get("badges") or []):
        label = str(badge.get("label") or "").strip()
        if label and label not in lines:
            lines.append(label)
    if not lines:
        return None
    return {"id": "coverage", "title": "COVERAGE LIMITS", "lines": lines}


def _diagnostics_section(model: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[str] = []
    confidence = str(model.get("confidence") or "").strip()
    if confidence:
        lines.append(f"Confidence: {confidence}")
    for reason in _lines_of(model.get("confidence_reasons")):
        lines.append(f"• {reason}")
    status = str(model.get("decomposition_status") or "").strip()
    if status:
        lines.append(f"Decomposition: {status}")
    profile_note = str(model.get("profile_note") or "").strip()
    if profile_note:
        lines.append(profile_note)
    best_slot = str(model.get("best_slot_headline") or "").strip()
    if best_slot:
        lines.append(best_slot)
    slot_line = str((model.get("slot_options") or {}).get("compact_line") or "").strip()
    if slot_line:
        lines.append(f"Slot options: {slot_line}")
    flags = [str(flag) for flag in (model.get("flags") or []) if flag]
    if flags:
        lines.append("Flags: " + ", ".join(flags))
    if not lines:
        return None
    return {"id": "diagnostics", "title": "DIAGNOSTICS", "lines": lines}


_SECTION_BUILDERS = {
    "score": _score_section,
    "axes": _axes_section,
    "tradeoffs": _tradeoff_section,
    "important_mods": _important_mods_section,
    "current_case": _current_case_section,
    "upgrade_path": _upgrade_path_section,
    "pob_values": _pob_values_section,
    "risk": _risk_section,
    "coverage": _coverage_section,
    "diagnostics": _diagnostics_section,
}


def build_companion_analysis(model: dict[str, Any]) -> dict[str, Any]:
    """Detailed analysis payload for the Companion card.

    Reads the *uncompressed* presentation model, so it must be called before the
    primary tooltip drops the sections it is moving here.
    """
    sections: list[dict[str, Any]] = []
    for section_id in COMPANION_SECTION_ORDER:
        section = _SECTION_BUILDERS[section_id](model)
        if section:
            sections.append(section)
    subtitle_parts = [
        str(model.get("item_name") or "").strip(),
        str(model.get("base_type") or "").strip(),
    ]
    return {
        "title": COMPANION_TITLE,
        "subtitle": " · ".join(part for part in subtitle_parts if part),
        "sections": sections,
        "section_ids": [section["id"] for section in sections],
    }


def _normalize(text: str) -> str:
    return str(text or "").lstrip("•✓⚠ ").strip().casefold()


def prune_companion_duplicates(companion: dict[str, Any], shown_texts: list[str]) -> None:
    """Drop Companion lines the primary tooltip already shows, in place.

    The Companion is the *expansion* surface. A line that repeats a headline reason or
    a critical note verbatim adds nothing, and a section left with nothing else to say
    is removed entirely.
    """
    shown = {_normalize(text) for text in shown_texts if str(text or "").strip()}
    sections: list[dict[str, Any]] = []
    for section in list(companion.get("sections") or []):
        kept: list[str] = []
        for line in section.get("lines") or []:
            normalized = _normalize(line)
            if not normalized or normalized in shown:
                continue
            # Within a section, a line wholly contained in one already kept is noise.
            if any(normalized in _normalize(existing) for existing in kept):
                continue
            kept = [existing for existing in kept if _normalize(existing) not in normalized]
            kept.append(str(line))
        if not kept:
            continue
        section["lines"] = kept
        sections.append(section)
    companion["sections"] = sections
    companion["section_ids"] = [section["id"] for section in sections]
