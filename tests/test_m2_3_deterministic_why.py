"""M2.3 -- deterministic "Why?" explanation: semantic kind/metric checks on synthetic outcomes.

Presentation-only: no PoB worker, no scoring. Exact copy is asserted only where the
wording is the contract (truthfulness boundary); otherwise kind/metric are checked.
"""

from __future__ import annotations

import pytest

from exilelens.items.compact_tooltip import MAX_NOTES, MAX_REASONS, apply_compact_tooltip
from exilelens.items.more_info import build_more_info
from exilelens.items.why_explanation import MAX_WHY_REASONS, build_why_explanation

pytestmark = pytest.mark.itemcheck


def _delta(key: str, pct: float, **extra: object) -> dict[str, object]:
    return {
        "key": key,
        "label": key,
        "current": 100.0,
        "candidate": 100.0 + pct,
        "percent_delta": pct,
        "absolute_delta": pct,
        "direction": "positive" if pct > 0 else "negative",
        **extra,
    }


def _recovery(key: str, before: float, after: float, pool: float) -> dict[str, object]:
    change = after - before
    return {
        "key": key,
        "current": before,
        "candidate": after,
        "percent_delta": None if before == 0 else (after / before - 1) * 100,
        "absolute_delta": change,
        "support": "MEASURED",
        "pool_pct": abs(change) * 100 / pool,
        "from_zero": before == 0,
    }


def _outcome(verdict, deltas=(), *, recovery=(), resistances=(), guardrails=(), quality="FULL", reasons=()):
    return {
        "verdict": verdict,
        "verdict_label": verdict.replace("_", " "),
        "verdict_class": "neutral",
        "verdict_reason": "Net score +9.0 against the current item.",
        "final_score": 58.0,
        "evaluation_quality": quality,
        "evaluation_quality_reasons": [{"code": "X", "detail": detail} for detail in reasons],
        "quality_label": "" if quality == "FULL" else "Partial evaluation",
        "all_deltas": list(deltas),
        "primary_deltas": list(deltas),
        "resistances": list(resistances),
        "guardrails_applied": list(guardrails),
        "critical_tradeoffs": [],
        "item_impact": {
            "axes": {"RECOVERY": {"metrics": list(recovery)}, "DEFENSE": {"support": "MEASURED"}},
            "conflict": {},
        },
    }


def _kinds(why: dict) -> list[str]:
    return [block["kind"] for block in why["reasons"]]


def _texts(why: dict) -> list[str]:
    return [block["text"] for block in why["reasons"]]


# ------------------------------------------------------------------ verdict behaviour


def test_clean_damage_upgrade_names_the_gain_and_adds_no_filler() -> None:
    why = build_why_explanation(_outcome("MEANINGFUL_UPGRADE", [_delta("primary_offense", 11.2)]))
    assert _kinds(why) == ["gain"] and why["reasons"][0]["metric"] == "primary_offense"
    assert "11.2%" in why["reasons"][0]["text"] and why["title"] == "WHY IT'S AN UPGRADE"


def test_upgrade_with_defensive_loss_states_the_loss_second() -> None:
    why = build_why_explanation(
        _outcome("MINOR_UPGRADE", [_delta("primary_offense", 11.2), _delta("ehp", -4.1), _delta("movement_speed", 1.0)])
    )
    assert _kinds(why) == ["gain", "loss"]
    assert [b["metric"] for b in why["reasons"]] == ["primary_offense", "ehp"]
    assert why["reasons"][1]["text"] == "You give up 4.1% EHP."


def test_sidegrade_tradeoff_keeps_both_directions() -> None:
    why = build_why_explanation(_outcome("SIDEGRADE", [_delta("primary_offense", 8.4), _delta("ehp", -9.7)]))
    first = why["reasons"][0]
    assert first["kind"] == "tradeoff" and first["metric"] == "primary_offense" and first["counter_metric"] == "ehp"
    assert "8.4%" in first["text"] and "9.7%" in first["text"]
    assert why["reasons"][1]["text"] == "That trade-off keeps this a sidegrade."


def test_downgrade_leads_with_loss_then_insufficient_gain() -> None:
    why = build_why_explanation(_outcome("MINOR_DOWNGRADE", [_delta("primary_offense", -7.6), _delta("ehp", 3.5)]))
    assert _kinds(why) == ["loss", "gain"]
    assert why["reasons"][0]["text"] == "Damage falls 7.6%."
    assert why["reasons"][1]["text"].endswith("but not enough to offset it.")


def test_cap_loss_outranks_a_larger_harmless_gain() -> None:
    why = build_why_explanation(
        _outcome(
            "MINOR_DOWNGRADE",
            [_delta("primary_offense", 14.0)],
            resistances=[{"element": "fire", "state": "CAP_LOST", "current": 75, "candidate": 62}],
        )
    )
    assert why["reasons"][0]["kind"] == "loss" and why["reasons"][0]["metric"] == "fire_res"
    assert why["reasons"][0]["text"] == "You lose the Fire Resistance cap."


def test_not_viable_leads_with_the_exact_guardrail_and_ignores_damage() -> None:
    guard = {"code": "ATTRIBUTE_REQUIREMENT_LOST", "not_viable": True, "reason": "Strength requirement not met (90/120).", "metric": ""}
    why = build_why_explanation(_outcome("NOT_VIABLE", [_delta("primary_offense", 30.0)], guardrails=[guard]))
    assert _kinds(why) == ["blocker"]
    assert why["reasons"][0]["text"] == "Strength requirement not met (90/120)."
    assert why["title"] == "WHY IT'S NOT VIABLE"


def test_uncertain_leads_with_the_real_reason_and_names_the_measured_axis() -> None:
    why = build_why_explanation(
        _outcome(
            "UNCERTAIN",
            [_delta("primary_offense", 50.0, delta_kind="UNMEASURED"), _delta("ehp", 6.0)],
            quality="PARTIAL",
            reasons=["the main skill's damage change could not be measured"],
        )
    )
    assert _kinds(why) == ["uncertainty", "uncertainty"]
    assert why["reasons"][0]["text"] == "The main skill's damage change could not be measured."
    assert why["reasons"][1]["text"] == "Defensive changes are still measured."
    assert not any("50" in text for text in _texts(why)), "an unverified damage number is never stated"


def test_no_change_says_threshold_not_identical() -> None:
    why = build_why_explanation(_outcome("SIDEGRADE", [_delta("primary_offense", 1.0), _delta("ehp", -0.9)]))
    assert _texts(why) == ["The measured changes are below the meaningful-change threshold."]
    identical = build_why_explanation(_outcome("SIDEGRADE", [_delta("primary_offense", 0.0)]))
    assert _texts(identical) == ["The measured values are unchanged."]


# --------------------------------------------------------------------- recovery


def test_life_regeneration_tradeoff_keeps_life_identity() -> None:
    why = build_why_explanation(
        _outcome(
            "SIDEGRADE",
            [_delta("primary_offense", 6.0)],
            recovery=[_recovery("LifeRegenRecovery", 40.0, 10.0, 1000.0)],
        )
    )
    first = why["reasons"][0]
    assert first["counter_metric"] == "life_regeneration"
    assert "Life Regeneration falls by 30/s" in first["text"] and "Energy Shield" not in first["text"]


def test_energy_shield_regeneration_gain_keeps_es_identity() -> None:
    why = build_why_explanation(
        _outcome("MINOR_UPGRADE", recovery=[_recovery("EnergyShieldRegenRecovery", 7.0, 100.0, 3000.0)])
    )
    assert why["reasons"][0]["metric"] == "energy_shield_regeneration"
    assert why["reasons"][0]["text"] == "Energy Shield Regeneration increases by 93/s."


def test_hybrid_life_down_es_up_preserves_both_channels_unsummed() -> None:
    why = build_why_explanation(
        _outcome(
            "SIDEGRADE",
            recovery=[
                _recovery("LifeRegenRecovery", 40.0, 10.0, 1000.0),
                _recovery("EnergyShieldRegenRecovery", 7.0, 100.0, 3000.0),
            ],
        )
    )
    first = why["reasons"][0]
    assert (first["metric"], first["counter_metric"]) == ("energy_shield_regeneration", "life_regeneration")
    assert "Energy Shield Regeneration increases by 93/s" in first["text"]
    assert "Life Regeneration falls by 30/s" in first["text"]


def test_immaterial_recovery_is_not_explained() -> None:
    why = build_why_explanation(
        _outcome("MINOR_UPGRADE", [_delta("primary_offense", 5.0)], recovery=[_recovery("LifeRegenRecovery", 40.0, 38.0, 100000.0)])
    )
    assert _kinds(why) == ["gain"]


# ------------------------------------------------------------------ truthfulness


def test_player_copy_has_no_causality_score_or_internal_vocabulary() -> None:
    outcome = _outcome(
        "SIDEGRADE",
        [_delta("primary_offense", 8.4), _delta("ehp", -9.7)],
        resistances=[{"element": "fire", "state": "CAP_LOST", "current": 75, "candidate": 62}],
    )
    text = " ".join(_texts(build_why_explanation(outcome))).lower()
    for banned in ("because", "thanks to", "caused", "net score", "build value", "_", "cap_lost"):
        assert banned not in text, banned


def test_reasons_never_exceed_the_cap_and_priority_is_ordered() -> None:
    why = build_why_explanation(
        _outcome(
            "SIDEGRADE",
            [_delta("primary_offense", 8.0), _delta("ehp", -9.0), _delta("worst_max_hit", -6.0), _delta("movement_speed", 12.0)],
            resistances=[{"element": "cold", "state": "CAP_REACHED", "current": 60, "candidate": 75}],
        )
    )
    assert len(why["reasons"]) <= MAX_WHY_REASONS
    assert [b["priority"] for b in why["reasons"]] == list(range(len(why["reasons"])))


def test_no_structured_evidence_yields_no_reasons() -> None:
    assert build_why_explanation(_outcome("MEANINGFUL_UPGRADE"))["reasons"] == []
    assert build_why_explanation({})["reasons"] == []


# --------------------------------------------------------- compact / More Info wiring


def _model(outcome: dict) -> dict:
    return {"item_name": "Test Item", "evaluation_outcome": outcome, "rows": []}


def _why_section(model: dict) -> dict:
    return next(section for section in model["more_info"]["sections"] if section["id"] == "why_verdict")


def test_compact_and_more_info_share_the_same_reasons() -> None:
    outcome = _outcome("SIDEGRADE", [_delta("primary_offense", 8.4), _delta("ehp", -9.7)])
    model = _model(outcome)
    apply_compact_tooltip(model)
    canonical = _texts(build_why_explanation(outcome))
    assert [line["text"] for line in model["primary_reasons"]] == canonical[:MAX_REASONS]
    assert _why_section(model)["lines"] == canonical
    assert "Net score" not in " ".join(_why_section(model)["lines"])


def test_compact_does_not_repeat_the_quality_note() -> None:
    outcome = _outcome(
        "UNCERTAIN", [_delta("ehp", 6.0)], quality="PARTIAL",
        reasons=["the main skill's damage change could not be measured"],
    )
    model = _model(outcome)
    apply_compact_tooltip(model)
    assert model["critical_notes"][0].startswith("◐")
    assert [line["text"] for line in model["primary_reasons"]] == ["Defensive changes are still measured."]


def test_compact_does_not_repeat_a_blocker_row_but_more_info_keeps_it() -> None:
    guard = {"code": "ATTRIBUTE_REQUIREMENT_LOST", "not_viable": True, "reason": "Strength requirement not met.", "metric": ""}
    model = _model(_outcome("NOT_VIABLE", guardrails=[guard]))
    apply_compact_tooltip(model)
    assert any(row["key"] == "cannot_equip" for row in model["impact_rows"])
    assert model["primary_reasons"] == []
    assert _why_section(model)["lines"] == ["Strength requirement not met."]


def test_compact_budgets_unchanged() -> None:
    assert (MAX_REASONS, MAX_NOTES) == (3, 2)


def test_more_info_falls_back_to_verdict_reason_without_evidence() -> None:
    info = build_more_info({}, outcome={"verdict": "MEANINGFUL_UPGRADE", "verdict_reason": "Net score +9.0 against the current item."})
    why = next(section for section in info["sections"] if section["id"] == "why_verdict")
    assert why["lines"] == ["Net score +9.0 against the current item."]
