"""TRUST-01 integration: the equipability blocker (A) outranks the freshness advisory (B)."""

from __future__ import annotations

import pytest

from exilelens.app.build_freshness import assess_build_freshness
from exilelens.app.build_revision import BuildFileRevision
from exilelens.items.compact_tooltip import MAX_NOTES, apply_compact_tooltip
from exilelens.items.guardrails import evaluate_guardrails

pytestmark = pytest.mark.itemcheck


def test_cant_equip_blocker_leads_and_freshness_never_takes_a_critical_slot() -> None:
    guard = evaluate_guardrails(
        ["EQUIP_REQUIREMENT_NOT_MET"],
        warnings=[{"code": "EQUIP_REQUIREMENT_NOT_MET", "detail": "Requires 155 Strength · Character has 132", "metric": "strength"}],
    )[0].to_dict()
    now = 1_800_000_000.0
    old = BuildFileRevision("b.xml", int((now - 9 * 86400) * 1e9), 1)
    freshness = assess_build_freshness(has_build=True, loaded_revision=old, current_revision=old, now=now)
    model = {
        "rows": [],
        "build_freshness": freshness,
        "evaluation_outcome": {
            "verdict": "NOT_VIABLE", "verdict_label": "NOT VIABLE", "final_score": 25.0, "evaluation_quality": "FULL",
            "all_deltas": [], "primary_deltas": [], "resistances": [], "guardrails_applied": [guard],
        },
    }
    apply_compact_tooltip(model)
    assert model["verdict_headline"] == "NOT VIABLE"
    assert model["impact_rows"][0]["key"] == "cannot_equip"
    assert model["impact_rows"][0]["delta_text"].startswith("Requires 155 Strength")
    assert len(model["critical_notes"]) <= MAX_NOTES
    assert model["evaluation_outcome"]["verdict"] == "NOT_VIABLE"
