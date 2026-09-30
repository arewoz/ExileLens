"""Load replay fixtures and run them through the production verdict pipeline (no PoB, no policy copy)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from exilelens.items.item_impact import ImpactThresholds, interpret_item_impact
from exilelens.items.ranking import enrich_slot_comparison
from exilelens.items.value_profiles import ValueProfile

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def fixture_ids() -> list[str]:
    return sorted(path.stem for path in FIXTURE_DIR.glob("*.json"))


def load_fixture(fixture_id: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{fixture_id}.json").read_text(encoding="utf-8"))


def replay(fixture: dict[str, Any], *, profile: ValueProfile = ValueProfile.BALANCED) -> dict[str, Any]:
    """Enriched slot comparison (``evaluation_outcome`` included) for a stored fixture."""
    comparison = copy.deepcopy(fixture["comparison"])
    return enrich_slot_comparison(
        comparison,
        primary_field=str(fixture.get("primary_field") or "CombinedDPS"),
        primary_confidence=str(fixture.get("primary_confidence") or "high"),
        profile=profile,
        offense_coverage=copy.deepcopy(fixture.get("offense_coverage")) or None,
    )


def replay_id(fixture_id: str, **kwargs: Any) -> dict[str, Any]:
    return replay(load_fixture(fixture_id), **kwargs)


def impact_with(result: dict[str, Any], thresholds: ImpactThresholds):
    """Re-interpret an already-replayed result with different impact thresholds (production function)."""
    outcome = result["evaluation_outcome"]
    return interpret_item_impact(
        result["metric_profile"],
        result["resist_caps"],
        outcome["baseline_metrics"],
        outcome["candidate_metrics"],
        guardrails=outcome["guardrails_applied"],
        thresholds=thresholds,
    )


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    """The fields the flip report compares, tolerant of pre-conflict (old) outcomes."""
    outcome = result["evaluation_outcome"]
    impact = outcome.get("item_impact") or {}
    conflict = impact.get("conflict") or {}
    return {
        "verdict": outcome["verdict"],
        "quality": outcome["evaluation_quality"],
        "raw_score": outcome["raw_score"],
        "final_score": outcome["final_score"],
        "reason": outcome["verdict_reason"],
        "guardrails": sorted(g["code"] for g in outcome.get("guardrails_applied") or []),
        "pattern": impact.get("pattern"),
        "conflict_kind": conflict.get("kind"),
        "axes": {
            name: {"direction": axis.get("direction"), "significant": axis.get("significant"),
                   "material_positive": axis.get("material_positive"), "material_negative": axis.get("material_negative")}
            for name, axis in (impact.get("axes") or {}).items()
        },
        "negligible_opposition": [
            f"{item.get('axis')}:{item.get('metric')}" for item in conflict.get("negligible_opposition") or []
        ],
    }


def surface(fixture: dict[str, Any]) -> dict[str, Any]:
    """Replay, then run the production build-intel + presentation + More Info layers over the result.

    Mirrors how ``tests/test_complex_damage_truthfulness_guardrail.py`` assembles a result from an
    enriched comparison; nothing here decides a verdict.
    """
    from exilelens.items.build_intel.engine import compare_slot
    from exilelens.items.decision import build_decision_summary
    from exilelens.items.more_info import build_more_info
    from exilelens.items.presentation import build_presentation

    comparison = replay(fixture)
    intel = compare_slot(comparison).to_dict()
    result = {
        "recommendation": comparison,
        "slot_comparisons": [comparison],
        "decision": build_decision_summary(comparison).to_dict(),
        "build_comparison": intel,
        "primary_metric": {"pob_field": fixture.get("primary_field") or "CombinedDPS",
                           "confidence": fixture.get("primary_confidence") or "high"},
        "offense_coverage": comparison.get("offense_coverage"),
        "native_damage_discovery": comparison.get("native_damage_discovery"),
        "damage_claim": comparison.get("damage_claim"),
        "pob_parse": {"display_name": "Candidate", "item": {"type": "Item"}},
        "metadata": {"name": "Candidate", "base_type": "Item"},
        "value_profile": "BALANCED",
    }
    presentation = build_presentation(result)
    more_info = build_more_info(presentation, outcome=comparison["evaluation_outcome"])
    return {"comparison": comparison, "intel": intel, "presentation": presentation, "more_info": more_info}


def visible_text(surface_result: dict[str, Any]) -> list[str]:
    """Every user-facing explanation string the policy contributes to, for wording checks."""
    comparison = surface_result["comparison"]
    intel = surface_result["intel"]
    presentation = surface_result["presentation"]
    explanation = intel.get("explanation") or {}
    texts: list[str] = [
        str(comparison["evaluation_outcome"].get("verdict_reason") or ""),
        str(presentation.get("verdict_explanation") or ""),
        str(explanation.get("headline") or ""),
    ]
    for key in ("primary_reasons", "improvements", "tradeoffs"):
        for row in explanation.get(key) or []:
            texts.append(str(row.get("text") or row.get("detail") or ""))
    for line in presentation.get("tradeoff_lines") or []:
        texts.append(str(line.get("text") if isinstance(line, dict) else line))
    for section in (surface_result["more_info"].get("sections") or []):
        texts.append(str(section.get("title") or ""))
        texts.extend(str(line) for line in section.get("lines") or [])
    return [text for text in texts if text]
