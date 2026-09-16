"""Dashboard full-detail formatter (Phase F — DASHBOARD_FULL surface)."""

from __future__ import annotations

from typing import Any

from poe2value.items.presentation import SurfaceMode, build_presentation_for_surface
from poe2value.items.upgrade_path import history_upgrade_path_hint


def _line_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("line") or item.get("explanation") or "")
    return str(item)


def format_dashboard_item_detail(result: dict[str, Any]) -> str:
    meta = result.get("request_meta") or {}
    presentation = build_presentation_for_surface(
        result,
        surface=SurfaceMode.DASHBOARD_FULL,
        build_name=str(meta.get("build_name") or ""),
        loadout_name=str(meta.get("loadout_name") or ""),
        item_set_name=str(meta.get("item_set_name") or ""),
        context=str(result.get("context") or "MAP"),
        value_profile=str(result.get("value_profile") or "BALANCED"),
    )
    pob = result.get("pob_parse") or {}
    rec = result.get("recommendation") or {}
    baseline_item = (result.get("baseline_item") or {}).get("name") or pob.get("baseline_item_name") or "—"
    lines = [
        f"Item: {pob.get('display_name') or presentation.get('item_name') or '—'}",
        # TODO Phase G UI: "POB BASELINE · Saved build · Fast Mapper" header from build/loadout meta.
        f"Best slot: {(result.get('best_slot') or {}).get('label') or rec.get('pob_slot') or '—'}",
        f"PoB baseline item: {baseline_item}",
        f"Verdict: {presentation.get('verdict_label') or rec.get('verdict') or '—'}",
        f"Decision: {(result.get('decision') or {}).get('headline') or '—'}",
        f"Build Value: {((rec.get('value') or {}).get('rating')) or '—'}",
    ]

    slot_options = presentation.get("slot_options") or {}
    if slot_options.get("options"):
        lines.extend(["", str(slot_options.get("title") or "SLOT OPTIONS")])
        for option in slot_options.get("options") or []:
            marker = "→" if option.get("selected") else " "
            verdict_text = str(option.get("verdict") or "").replace("_", " ").title()
            line = f"  {marker} {option.get('slot')}: {option.get('rating_text')} · {verdict_text}"
            if option.get("blocked"):
                line += " · blocked"
            lines.append(line)

    profile_row = presentation.get("multi_profile_row") or []
    if profile_row:
        lines.extend(["", "PROFILE ROW"])
        for row in profile_row:
            lines.append(f"  · {row.get('label')}: {row.get('rating_text')} ({row.get('verdict') or '—'})")

    best_use = presentation.get("best_use") or {}
    if best_use.get("headline_detailed") or best_use.get("headline"):
        lines.extend(["", "BEST PROFILE"])
        lines.append(str(best_use.get("headline_detailed") or best_use.get("headline")))
        runner = best_use.get("runner_up") or {}
        if runner.get("label"):
            rating = runner.get("rating")
            rating_text = f" {rating:.0f}" if rating is not None else ""
            lines.append(f"  Runner-up: {runner.get('label')}{rating_text}")

    current_edge = presentation.get("current_edge") or {}
    edge_lines = list(current_edge.get("lines") or [])
    if edge_lines:
        lines.extend(["", str(current_edge.get("title") or "WHY CURRENT WINS")])
        for item in edge_lines[:3]:
            text = _line_text(item)
            if text:
                lines.append(f"  · {text}")

    risk = presentation.get("risk_summary") or {}
    if risk.get("label") or risk.get("detail"):
        lines.extend(["", "RISK"])
        if risk.get("level"):
            lines.append(f"  Level: {risk.get('level')}")
        if risk.get("label"):
            lines.append(f"  {risk.get('label')}")
        if risk.get("detail"):
            lines.append(f"  {risk.get('detail')}")

    lines.extend(["", "UPGRADE PATH"])
    upgrade = result.get("upgrade_path") or presentation.get("upgrade_path") or {}
    if upgrade:
        lines.append(str(upgrade.get("summary") or "—"))
        after_repair = upgrade.get("after_repair") or {}
        if after_repair.get("compact_line"):
            lines.append(f"  After repair: {after_repair.get('compact_line')}")
        elif after_repair.get("rating_text") or after_repair.get("verdict_text"):
            lines.append(
                f"  After repair: {after_repair.get('rating_text') or '—'} · {after_repair.get('verdict_text') or '—'}"
            )
        repair_steps = list(upgrade.get("repair_steps") or [])
        if repair_steps:
            lines.append("  Repair steps:")
            for step in repair_steps[:6]:
                line = _line_text(step)
                reason = str(step.get("blocker_reason") or "").strip()
                if line and reason:
                    lines.append(f"    · {line} — {reason}")
                elif line:
                    lines.append(f"    · {line}")
        for detail in upgrade.get("detail_lines") or []:
            lines.append(f"  {detail}")
        if upgrade.get("hypothetical_note"):
            lines.append(str(upgrade.get("hypothetical_note")))
        probes = upgrade.get("probes_run")
        if probes:
            lines.append(f"Probes run: {probes}")
    else:
        lines.append(history_upgrade_path_hint(result) or "—")

    potential = result.get("upgrade_potential") or {}
    if potential:
        lines.extend(["", "SOLVER TRACE"])
        state = potential.get("product_state") or potential.get("status")
        if state:
            lines.append(f"State: {state}")
        repair_vector = list(potential.get("repair_vector") or [])
        if repair_vector:
            lines.append("Repair vector:")
            for item in repair_vector[:6]:
                label = item.get("label") or item.get("probe_id") or "repair"
                magnitude = item.get("magnitude")
                unit = item.get("unit") or ""
                reason = str(item.get("blocker_reason") or "").strip()
                if magnitude is not None:
                    line = f"  · {label} +{magnitude:g}{'%' if unit == 'percent' else ''}"
                else:
                    line = f"  · {label}"
                if reason:
                    line += f" — {reason}"
                lines.append(line)
        blockers = list(potential.get("blockers") or [])
        if blockers:
            lines.append("Blockers:")
            for blocker in blockers[:6]:
                lines.append(f"  · {blocker.get('label') or blocker.get('code') or blocker}")
        eligibility = list(potential.get("dimension_eligibility") or [])
        if eligibility:
            lines.append("Dimension eligibility:")
            for row in eligibility[:6]:
                dim = row.get("dimension") or row.get("probe_id") or "dimension"
                eligible = row.get("eligible")
                reason = row.get("reason") or row.get("state")
                suffix = f" ({reason})" if reason else ""
                lines.append(f"  · {dim}: {'yes' if eligible else 'no'}{suffix}")
        probes = potential.get("probes_run")
        if probes is not None:
            lines.append(f"PoB probes run: {probes}")
        repaired_rating = potential.get("repaired_rating")
        repaired_verdict = potential.get("repaired_verdict")
        if repaired_rating is not None or repaired_verdict:
            lines.append(
                f"After repair preview: {repaired_rating if repaired_rating is not None else '—'} · "
                f"{repaired_verdict or '—'}"
            )

    offense = result.get("offense_coverage") or rec.get("offense_coverage") or {}
    offense_entry = (
        (rec.get("metric_profile") or rec.get("normalized_metrics") or {}).get("primary_offense") or {}
    )
    delta_kind = str(offense_entry.get("delta_kind") or "MEASURED")
    score_eligible = offense_entry.get("score_eligible")
    if score_eligible is None:
        score_eligible = delta_kind not in {"MISSING", "UNSUPPORTED", "UNMEASURED"}
    if offense.get("state"):
        lines.extend(["", "OFFENSE COVERAGE"])
        lines.append(f"  State: {offense.get('state')}")
        if offense_entry:
            lines.append(f"  Damage delta_kind: {delta_kind}")
            if offense_entry.get("percent_delta") is not None:
                lines.append(f"  Damage delta: {offense_entry.get('percent_delta'):.1f}%")
            lines.append(f"  Score eligible: {'yes' if score_eligible else 'no'}")
        dimension_evidence = offense.get("dimension_evidence") or {}
        if dimension_evidence:
            lines.append("  Dimensions:")
            for probe_id, evidence in dimension_evidence.items():
                lines.append(f"    · {probe_id}: {evidence}")

    confidence = (result.get("decision") or {}).get("confidence")
    reasons = (result.get("decision") or {}).get("confidence_reasons") or []
    if confidence:
        lines.extend(["", f"Confidence: {confidence}"])
        for reason in reasons[:3]:
            lines.append(f"  · {reason}")

    return "\n".join(lines)
