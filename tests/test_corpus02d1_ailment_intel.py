"""CORPUS-02D1 — poison and ailment evidence rules (no PoB engine).

The real-PoB counterparts are in tests/integration/test_corpus02d1_poison_ailment.py.
"""

from __future__ import annotations

import pytest

from exilelens.items.ailment_intel import ailment_breakdown
from exilelens.items.evaluation_outcome import EvaluationQuality, assess_quality
from exilelens.items.offense_coverage import (
    OffenseCoverageState,
    _classify_from_probes,
    offense_secondary_mechanics_partial,
)
from exilelens.items.primary_metric import DamageQuantity, resolve_primary_metric

pytestmark = pytest.mark.itemcheck

# Real PoB 0.23.1 baseline of fixtures/builds/public_corpus/core04_poison_ailment.xml.
POISON_BASELINE = {
    "CombinedDPS": 895807.35715692, "TotalDPS": 101952.18517898, "TotalDot": 0.0,
    "TotalDotDPS": 793855.17197794, "PoisonDPS": 793727.17902357, "IgniteDPS": 127.99295436912,
    "PoisonDuration": 2.8125, "PoisonStackPotential": 0.94359375, "PoisonStacksMax": 4.0,
    "PoisonChancePerHit": 100.0, "PoisonMagnitudeEffect": 9.526, "PoisonRollAverage": 50.0,
    "PoisonDamage": 2232357.6910038, "Speed": 1.342,
}


def _identity(*, no_hit: bool) -> dict:
    return {
        "main_skill_identity": {
            "skill_name": "Poisonburst Arrow", "skill_id": "PoisonBurstArrowPlayer",
            "stat_set": "Poison Burst", "stat_set_no_hit_damage": no_hit, "damage_owner": "PLAYER",
        },
    }


def _probe(probe_id: str, pct: float, *, control: bool = False) -> dict:
    return {
        "probe_id": probe_id, "magnitude": 1.0, "status": "ok",
        "primary_offense_pct": pct, "primary_offense_abs": pct * 1000.0,
        "combined_dps_pct": pct, "responsive": abs(pct) > 0.05, "control": control,
    }


def _poison_selection():
    return resolve_primary_metric(_identity(no_hit=True), POISON_BASELINE)


# ------------------------------------------------------------------ resolver


def test_no_hit_stat_set_selects_the_ailment_even_when_the_fake_hit_is_larger() -> None:
    # A no-hit stat set whose fake hit exceeds its poison would otherwise fall through
    # to CombinedDPS, which adds PoB's fake hit to the poison.
    metrics = {**POISON_BASELINE, "TotalDPS": 900000.0, "CombinedDPS": 1693727.18}
    selection = resolve_primary_metric(_identity(no_hit=True), metrics)
    assert selection.pob_field == "PoisonDPS"
    assert selection.semantic_quantity == DamageQuantity.AILMENT_DPS
    assert selection.skill.no_hit_damage is True

    # Unchanged for a stat set that really hits.
    ordinary = resolve_primary_metric(_identity(no_hit=False), metrics)
    assert ordinary.pob_field == "CombinedDPS"
    assert ordinary.semantic_quantity == DamageQuantity.HIT_PLUS_AILMENT


# ------------------------------------------------------------------ coverage audit


def test_poison_with_pob_derived_stacks_and_clean_control_is_fully_measured() -> None:
    coverage = _classify_from_probes(
        _poison_selection(), POISON_BASELINE,
        [_probe("ATTACK_SPEED", 15.4), _probe("PROJECTILE_SKILL_LEVELS", 10.4),
         _probe("POISON_DURATION", 24.2), _probe("SPELL_DAMAGE", 0.0, control=True)],
        carrier_slot="Ring 1",
    )
    assert coverage.state == OffenseCoverageState.FULL.value
    assert coverage.offense_trustworthy is True
    assert coverage.scope_gap == ""
    assert offense_secondary_mechanics_partial(coverage) is False


def test_poison_stack_count_fixed_by_configuration_stays_partial_with_reason() -> None:
    # With PoB's "Multiplier:PoisonStacks" override, duration no longer changes PoisonDPS.
    coverage = _classify_from_probes(
        _poison_selection(), POISON_BASELINE,
        [_probe("ATTACK_SPEED", 0.0), _probe("PROJECTILE_SKILL_LEVELS", 10.4),
         _probe("POISON_DURATION", 0.0), _probe("SPELL_DAMAGE", 0.0, control=True)],
        carrier_slot="Ring 1",
    )
    assert coverage.state == OffenseCoverageState.PARTIAL.value
    assert coverage.offense_trustworthy is False
    assert coverage.scope_gap == "AILMENT_STACK_SCOPE_UNPROVEN"
    assert "stack count" in coverage.scope_gap_detail


def test_poison_responding_only_to_duration_is_not_fully_measured() -> None:
    coverage = _classify_from_probes(
        _poison_selection(), POISON_BASELINE,
        [_probe("ATTACK_SPEED", 0.0), _probe("PROJECTILE_SKILL_LEVELS", 0.0),
         _probe("POISON_DURATION", 20.0), _probe("SPELL_DAMAGE", 0.0, control=True)],
        carrier_slot="Ring 1",
    )
    assert coverage.state == OffenseCoverageState.PARTIAL.value
    assert coverage.scope_gap == "AILMENT_RESPONSE_UNVERIFIED"


def test_poison_with_leaking_control_is_limited() -> None:
    coverage = _classify_from_probes(
        _poison_selection(), POISON_BASELINE,
        [_probe("ATTACK_SPEED", 15.0), _probe("POISON_DURATION", 20.0),
         _probe("SPELL_DAMAGE", 5.0, control=True)],
        carrier_slot="Ring 1",
    )
    assert coverage.state == OffenseCoverageState.LIMITED.value
    assert coverage.offense_trustworthy is False


def test_ignite_keeps_its_partial_scope_with_a_specific_reason() -> None:
    identity = {"main_skill_identity": {"skill_name": "Flameblast", "skill_id": "FlameblastPlayer"}}
    selection = resolve_primary_metric(identity, {"TotalDPS": 10.0, "IgniteDPS": 1000.0, "CombinedDPS": 1010.0})
    assert selection.ailment == "IGNITE"
    coverage = _classify_from_probes(
        selection, {"IgniteDPS": 1000.0},
        [_probe("IGNITE_MAGNITUDE", 30.0), _probe("SPELL_DAMAGE", 10.0),
         _probe("POISON_MAGNITUDE", 0.0, control=True)],
        carrier_slot="Ring 1",
    )
    assert coverage.state == OffenseCoverageState.PARTIAL.value
    assert coverage.scope_gap == "AILMENT_SCOPE_UNVERIFIED"
    assert "ignite" in coverage.scope_gap_detail


# ------------------------------------------------------------------ breakdown


def _primary(no_hit: bool, metrics: dict) -> dict:
    return resolve_primary_metric(_identity(no_hit=no_hit), metrics).to_dict()


def test_breakdown_excludes_the_fake_hit_and_keeps_factors_out_of_the_sum() -> None:
    candidate = {**POISON_BASELINE, "PoisonDPS": 917485.46544572, "PoisonDuration": 3.375,
                 "PoisonStackPotential": 1.1323125, "PoisonRollAverage": 54.785911289958,
                 "TotalDotDPS": 917613.46, "CombinedDPS": 1019565.65}
    breakdown = ailment_breakdown(_primary(True, POISON_BASELINE), POISON_BASELINE, candidate)
    roles = {row["field"]: row["role"] for row in breakdown["components"]}
    assert roles == {"TotalDPS": "EXCLUDED_NO_HIT_DAMAGE", "PoisonDPS": "SCORED", "IgniteDPS": "ADDITIVE"}
    assert breakdown["combined_includes_fake_hit"] is True
    assert breakdown["hit_damage_real"] is False
    assert {row["role"] for row in breakdown["factors"]} == {"INCORPORATED"}
    duration = next(row for row in breakdown["factors"] if row["field"] == "PoisonDuration")
    assert duration["percent_delta"] == pytest.approx(20.0)
    assert breakdown["ailment_total_damage"]["role"] == "DERIVED"
    assert breakdown["composition"]["status"] == "EXPLAINED"
    assert breakdown["hit_ailment_conflict"] is False


def test_breakdown_reports_an_unexplained_combined_remainder() -> None:
    before = {**POISON_BASELINE, "CombinedDPS": POISON_BASELINE["CombinedDPS"] + 50000.0}
    breakdown = ailment_breakdown(_primary(True, POISON_BASELINE), before, before)
    assert breakdown["composition"]["status"] == "UNEXPLAINED"


def test_no_breakdown_without_a_damaging_ailment() -> None:
    metrics = {"CombinedDPS": 1000.0, "TotalDPS": 1000.0}
    primary = resolve_primary_metric({"main_skill_identity": {"skill_name": "Spark"}}, metrics).to_dict()
    assert ailment_breakdown(primary, metrics, metrics) is None


def _conflict_metrics(hit: float, poison: float) -> dict:
    return {"TotalDPS": hit, "PoisonDPS": poison, "TotalDotDPS": poison, "CombinedDPS": hit + poison}


def test_material_real_hit_scores_pobs_combined_hit_and_poison() -> None:
    # Real "Arrow" stat-set shape: hit ~19% of CombinedDPS, poison dominant.
    metrics = _conflict_metrics(101952.18517898, 428683.23019975)
    selection = resolve_primary_metric(_identity(no_hit=False), metrics)
    assert selection.pob_field == "CombinedDPS"
    assert selection.semantic_quantity == DamageQuantity.HIT_PLUS_AILMENT
    # The same numbers on the no-hit stat set score the poison only.
    assert resolve_primary_metric(_identity(no_hit=True), metrics).pob_field == "PoisonDPS"
    # An immaterial real hit keeps the established ailment-dominant field.
    small = _conflict_metrics(50000.0, 950000.0)
    assert resolve_primary_metric(_identity(no_hit=False), small).pob_field == "PoisonDPS"


def test_real_hit_moving_against_the_scored_poison_is_a_conflict() -> None:
    # The baseline hit is immaterial (10%), so PoisonDPS is scored; the candidate's
    # hit becomes material while poison falls.
    before = _conflict_metrics(100000.0, 900000.0)
    after = _conflict_metrics(300000.0, 850000.0)
    breakdown = ailment_breakdown(_primary(False, before), before, after)
    assert breakdown["scored_field"] == "PoisonDPS"
    assert breakdown["hit_ailment_conflict"] is True

    # The same numbers on a no-hit stat set are not a conflict: that hit is not damage.
    fake = ailment_breakdown(_primary(True, before), before, after)
    assert fake["hit_ailment_conflict"] is False


def test_immaterial_hit_never_blocks_a_poison_verdict() -> None:
    before = _conflict_metrics(50000.0, 950000.0)
    after = _conflict_metrics(70000.0, 900000.0)
    breakdown = ailment_breakdown(_primary(False, before), before, after)
    assert breakdown["hit_share"] < 0.15
    assert breakdown["hit_ailment_conflict"] is False


# ------------------------------------------------------------------ quality gate


def _quality(comparison_extra: dict) -> tuple[EvaluationQuality, list[dict[str, str]]]:
    comparison = {
        "pob_slot": "Weapon 2",
        "baseline": {"metrics": dict(POISON_BASELINE)},
        "candidate": {"metrics": dict(POISON_BASELINE), "item_present": True},
        "restore": {"pass": True},
        **comparison_extra,
    }
    profile = {
        "primary_offense": {"current": 600000.0, "candidate": 570000.0, "percent_delta": -5.0,
                            "delta_kind": "MEASURED", "pob_field": "PoisonDPS"},
        "ehp": {"current": 1.0, "candidate": 1.0},
        "worst_max_hit": {"current": 1.0, "candidate": 1.0},
    }
    return assess_quality(comparison, metric_profile=profile, resist={"elements": {}}, primary_field="PoisonDPS")


def test_hit_ailment_conflict_is_a_specific_partial_reason() -> None:
    quality, reasons = _quality({
        "ailment_breakdown": {"ailment": "POISON", "hit_ailment_conflict": True,
                              "ailment_percent_delta": -5.0, "hit_percent_delta": 40.0},
    })
    assert quality == EvaluationQuality.PARTIAL
    assert [reason["code"] for reason in reasons] == ["AILMENT_HIT_COMPONENTS_DISAGREE"]
    assert "-5.0%" in reasons[0]["detail"] and "+40.0%" in reasons[0]["detail"]


def test_audited_poison_is_full_and_a_scope_gap_names_its_reason() -> None:
    full, _ = _quality({"offense_coverage": {"state": "FULL", "offense_trustworthy": True}})
    assert full == EvaluationQuality.FULL

    partial, reasons = _quality({"offense_coverage": {
        "state": "PARTIAL", "offense_trustworthy": False, "scope_gap": "AILMENT_STACK_SCOPE_UNPROVEN",
        "scope_gap_detail": "Path of Building's active poison stack count did not respond",
    }})
    assert partial == EvaluationQuality.PARTIAL
    assert reasons[0]["code"] == "OFFENSE_MECHANICS_PARTIAL"
    assert reasons[0]["detail"].startswith("Path of Building's active poison stack count")


def test_absent_ailment_field_with_collapsed_combined_damage_is_main_skill_invalid() -> None:
    # Real PoB: a spear replacing Poisonburst Arrow's bow leaves no PoisonDPS at all
    # and CombinedDPS 0 (core04_weapon_swap.xml).
    from exilelens.items.build_intel.thresholds import assess_thresholds

    profile = {"primary_offense": {"current": 8931.3928096968, "candidate": None}}
    events = assess_thresholds(profile, {"elements": {}}, {"CombinedDPS": 21312.88}, {"CombinedDPS": 0.0})
    assert "MAIN_SKILL_INVALID" in {event.code for event in events}
    # Missing candidate output alone (no collapse evidence) is not a skill loss.
    events = assess_thresholds(profile, {"elements": {}}, {"CombinedDPS": 21312.88}, {})
    assert "MAIN_SKILL_INVALID" not in {event.code for event in events}
