"""SCORING-01a: verdict policy core (direction -> materiality -> conflict -> verdict).

Real measured inputs are replayed from ``tests/policy_replay/fixtures`` through the production pipeline
(no PoB runtime). Synthetic worker-shaped cases (clearly labelled) exercise the policy at its boundaries;
they are policy tests, not evidence about any real build.

Sections
  1. replay fidelity                - the fixtures reproduce the recorded raw score, quality and guardrails
  2. characterization               - behaviour that must be identical before and after SCORING-01a
  3. Case A / Case B                - the two real reports (target: fail before SCORING-01a)
  4. synthetic policy               - materiality, conflict kind and resolution
  5. recovery_pool_pct              - boundary and robustness
  6. monotonicity sweep             - no improvement when the opposition gets worse
  7. user-facing consistency        - no "trade-off" wording without a material conflict
  8. declared flips                 - every replay verdict change is listed and reviewed
"""

from __future__ import annotations

import pytest

from exilelens.items.evaluation_outcome import (
    EvaluationQuality,
    PublicVerdict,
    SCORED_RAW_FIELDS,
    classify_score_verdict,
    decide_verdict,
)
from exilelens.items.guardrails import MINOR_UPGRADE_CEILING
from exilelens.items.item_impact import ImpactThresholds, interpret_item_impact
from exilelens.items.ranking import enrich_slot_comparison
from exilelens.items.slots import pob_slot_to_product
from exilelens.items.value_profiles import SCORE_SCALE
from exilelens.metrics import build_metric_profile
from tests.policy_replay.flip_report import flip_rows
from tests.policy_replay.replay import (
    fixture_ids,
    impact_with,
    load_fixture,
    replay,
    replay_id,
    surface,
    visible_text,
)

pytestmark = pytest.mark.itemcheck

CASE_A = "corpus02h_life_for_es_helmet_loses_damage_and_ehp"
CASE_B = "boots_life_ms_res_vs_regen_loss"
GLOVES_TRADEOFF = "corpus02d1_gloves_offense_gain_defense_loss"
CORE04_RING = "core04_ring_offense_defense_tradeoff"
MINION_RING = "corpus02b_minion_defense_ring"
CAP_LOST = "corpus02h_helmet_chaos_res_cap_lost"
REQUIREMENT = "corpus02g_amulet_attribute_requirement_lost"
PARTIAL = "corpus02f_ring_ignite_only_change_partial"
CONTROL_DOWN = "corpus02d1_gloves_attack_speed_loss"
CONTROL_UP = "corpus02d1_quiver_poison_magnitude"


def _outcome(fixture_id: str) -> dict:
    return replay_id(fixture_id)["evaluation_outcome"]


def _conflict(outcome: dict) -> dict:
    return (outcome.get("item_impact") or {}).get("conflict") or {}


# --------------------------------------------------------------------------- synthetic worker-shaped inputs


def _raw(**overrides: float | str | None) -> dict[str, float | str | None]:
    values: dict[str, float | str | None] = {field: 100.0 for field in SCORED_RAW_FIELDS}
    values.update(
        {
            "CombinedDPS": 100.0, "TotalEHP": 1_000.0, "Life": 2_000.0, "EnergyShield": 100.0,
            "LifeRegenRecovery": 40.0, "MovementSpeedMod": 1.0,
            "PhysicalMaximumHitTaken": 100.0, "FireMaximumHitTaken": 100.0, "ColdMaximumHitTaken": 100.0,
            "LightningMaximumHitTaken": 100.0, "ChaosMaximumHitTaken": 100.0,
            "FireResist": 75.0, "ColdResist": 75.0, "LightningResist": 75.0, "ChaosResist": 0.0,
            "FireResistMax": 75.0, "ColdResistMax": 75.0, "LightningResistMax": 75.0, "ChaosResistMax": 75.0,
        }
    )
    values.update(overrides)
    return values


def _synthetic(before: dict, after: dict, *, primary_confidence: str = "high") -> dict:
    comparison = {
        "pob_slot": "Ring 1",
        "product_slot": pob_slot_to_product("Ring 1").value,
        "baseline": {"metrics": before},
        "candidate": {"metrics": after, "item_present": True},
        "restore": {"pass": True},
    }
    return enrich_slot_comparison(comparison, primary_confidence=primary_confidence)["evaluation_outcome"]


def _pair(*, dps: float = 100.0, ehp: float = 1_000.0, regen: float = 40.0, life: float = 2_000.0,
          phys_hit: float = 100.0, movement: float = 1.0) -> tuple[dict, dict]:
    return (
        _raw(Life=life),
        _raw(CombinedDPS=dps, TotalEHP=ehp, LifeRegenRecovery=regen, Life=life,
             PhysicalMaximumHitTaken=phys_hit, MovementSpeedMod=movement),
    )


# =========================================================================== 1. replay fidelity


@pytest.mark.parametrize("fixture_id", fixture_ids())
def test_replay_reproduces_the_recorded_score_quality_and_guardrails(fixture_id: str) -> None:
    """The replay measures nothing and rescoring is untouched by SCORING-01a: only the verdict policy may differ."""
    fixture = load_fixture(fixture_id)
    recorded = fixture["recorded"]
    outcome = replay(fixture)["evaluation_outcome"]
    assert outcome["raw_score"] == pytest.approx(recorded["raw_score"])
    assert outcome["evaluation_quality"] == recorded["evaluation_quality"]
    assert sorted(g["code"] for g in outcome["guardrails_applied"]) == recorded["guardrails"]
    assert outcome["item_impact"]["pattern"] == recorded["pattern"]


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {key for value in node.values() for key in _keys(value)}
    if isinstance(node, list):
        return {key for value in node for key in _keys(value)}
    return set()


def test_fixtures_are_data_only_and_carry_no_item_text() -> None:
    """Measured numbers only: no item text/names, equipment, fingerprints or build identity."""
    forbidden_keys = {"raw_text", "raw_input", "raw", "equipment", "display_name", "fingerprint",
                      "fingerprint_hash", "content_hash", "build_path", "source_identity"}
    forbidden_words = ("item class:", "rarity:", "requires: level", "item level:", "sockets:")  # pasted item text
    for fixture_id in fixture_ids():
        fixture = load_fixture(fixture_id)
        assert not (_keys(fixture) & forbidden_keys), (fixture_id, _keys(fixture) & forbidden_keys)
        assert not [w for w in forbidden_words if w in str(fixture).lower()], fixture_id
        assert set(fixture["comparison"]["baseline_item"]) == {"empty"}


# =========================================================================== 2. characterization (before == after)


def test_genuine_balanced_trade_off_remains_sidegrade() -> None:
    """+11.0% offense against -10.9% defense: a real two-sided conflict with a middling score."""
    outcome = _outcome(GLOVES_TRADEOFF)
    assert outcome["evaluation_quality"] == "FULL" and not outcome["guardrails_applied"]
    assert outcome["verdict"] == "SIDEGRADE" and outcome["final_score"] == SCORE_SCALE.equivalent
    assert outcome["verdict_reason"].startswith("Meaningful trade-off")
    assert SCORE_SCALE.meaningful_downgrade < outcome["raw_score"] < SCORE_SCALE.useful


def test_minion_offense_loss_against_a_smaller_defense_gain_is_a_minor_downgrade() -> None:
    """SCORING-01b: -10.6% minion offense for +5.3% EHP is a real trade-off with a net score of -6.5. A conflict
    holds an upgrade back but never softens a downgrade the score already reads, so it is a MINOR DOWNGRADE that
    still names the trade-off. (01a forced it to SIDEGRADE.)"""
    outcome = _outcome(MINION_RING)
    assert _conflict(outcome)["kind"] == "MATERIAL"
    assert outcome["verdict"] == "MINOR_DOWNGRADE" and outcome["final_score"] == outcome["raw_score"]
    assert "Trade-off: " in outcome["verdict_reason"] and not outcome["verdict_reason"].startswith("Meaningful trade-off")


def test_resistance_cap_loss_keeps_its_ceiling_and_never_becomes_a_forced_sidegrade() -> None:
    outcome = _outcome(CAP_LOST)
    assert [g["code"] for g in outcome["guardrails_applied"]] == ["RES_CAP_LOST"]
    assert outcome["raw_score"] > 70  # a strong raw score that only the cap holds down
    assert outcome["final_score"] == SCORE_SCALE.minor_downgrade == 47.0
    assert outcome["verdict"] == "MINOR_DOWNGRADE"


def test_attribute_requirement_loss_remains_not_viable() -> None:
    outcome = _outcome(REQUIREMENT)
    assert outcome["verdict"] == "NOT_VIABLE"
    assert "ATTRIBUTE_REQUIREMENT_LOST" in {g["code"] for g in outcome["guardrails_applied"]}


def test_partial_evaluation_remains_uncertain() -> None:
    outcome = _outcome(PARTIAL)
    assert outcome["evaluation_quality"] == "PARTIAL" and outcome["verdict"] == "UNCERTAIN"


def test_clear_one_sided_results_are_untouched() -> None:
    down, up = _outcome(CONTROL_DOWN), _outcome(CONTROL_UP)
    assert (down["verdict"], down["final_score"]) == ("MEANINGFUL_DOWNGRADE", down["raw_score"])
    assert (up["verdict"], up["final_score"]) == ("MEANINGFUL_UPGRADE", up["raw_score"])


def test_main_skill_loss_and_resource_failure_remain_not_viable_despite_gains() -> None:
    """Synthetic: an attractive defence gain cannot rescue an invalid main skill or a broken resource."""
    before, after = _pair(dps=0.0, ehp=1_500.0)
    outcome = _synthetic(before, after)
    assert outcome["verdict"] == "NOT_VIABLE"
    assert "MAIN_SKILL_INVALID" in {g["code"] for g in outcome["guardrails_applied"]}

    before = _raw(ManaPerSecondCost=10.0, ManaRegenRecovery=20.0)
    after = _raw(CombinedDPS=200.0, TotalEHP=1_400.0, ManaPerSecondCost=20.0, ManaRegenRecovery=10.0)
    outcome = _synthetic(before, after)
    assert outcome["verdict"] == "NOT_VIABLE"
    assert "RESOURCE_FAILURE" in {g["code"] for g in outcome["guardrails_applied"]}


def test_partial_wins_over_any_conflict() -> None:
    """Synthetic: a material two-sided conflict on a low-confidence damage metric is still UNCERTAIN."""
    before, after = _pair(dps=125.0, ehp=900.0)
    outcome = _synthetic(before, after, primary_confidence="low")
    assert outcome["evaluation_quality"] == "PARTIAL" and outcome["verdict"] == "UNCERTAIN"


# =========================================================================== 3. Case A and Case B (real reports)


def test_case_a_small_recovery_gain_cannot_neutralize_large_offense_and_defence_losses() -> None:
    outcome = _outcome(CASE_A)
    axes = outcome["item_impact"]["axes"]
    assert outcome["evaluation_quality"] == "FULL" and not outcome["guardrails_applied"]
    assert axes["OFFENSE"]["direction"] == "NEGATIVE" and axes["DEFENSE"]["direction"] == "NEGATIVE"
    assert axes["RECOVERY"]["direction"] == "POSITIVE"
    assert _conflict(outcome)["kind"] == "NONE"
    assert [f"{o['axis']}:{o['metric']}" for o in _conflict(outcome)["negligible_opposition"]] == ["RECOVERY:LifeRegenRecovery"]
    assert outcome["verdict"] != "SIDEGRADE"
    assert outcome["final_score"] == outcome["raw_score"]
    assert PublicVerdict(outcome["verdict"]) is classify_score_verdict(outcome["raw_score"])
    assert outcome["verdict"] == "MEANINGFUL_DOWNGRADE"


def test_case_b_small_recovery_loss_cannot_neutralize_a_large_defence_and_movement_gain() -> None:
    outcome = _outcome(CASE_B)
    axes = outcome["item_impact"]["axes"]
    assert outcome["evaluation_quality"] == "FULL" and not outcome["guardrails_applied"]
    assert axes["DEFENSE"]["direction"] == "POSITIVE" and axes["UTILITY"]["direction"] == "POSITIVE"
    assert axes["RECOVERY"]["direction"] == "NEGATIVE"
    conflict = _conflict(outcome)
    assert conflict["kind"] == "NONE"
    assert [f"{o['axis']}:{o['metric']}" for o in conflict["negligible_opposition"]] == ["RECOVERY:LifeRegenRecovery"]
    assert outcome["verdict"] != "SIDEGRADE"
    assert outcome["final_score"] == outcome["raw_score"]
    # The verdict is whatever the ordinary score classification says; it is not pinned to a band here.
    assert PublicVerdict(outcome["verdict"]) is classify_score_verdict(outcome["raw_score"])


def test_case_b_normal_scoring_treats_it_as_a_clear_upgrade() -> None:
    """Product sanity check. If this fails, the score model (not the conflict policy) has a second problem."""
    outcome = _outcome(CASE_B)
    assert outcome["raw_score"] >= SCORE_SCALE.useful
    assert classify_score_verdict(outcome["raw_score"]) is PublicVerdict.MEANINGFUL_UPGRADE


# =========================================================================== 4. synthetic policy


def test_tiny_recovery_gain_cannot_neutralize_large_losses() -> None:
    before, after = _pair(dps=70.0, ehp=800.0, regen=48.0)  # +20% recovery, but +8/s on 2000 Life = 0.4%/s
    outcome = _synthetic(before, after)
    assert _conflict(outcome)["kind"] == "NONE"
    assert outcome["verdict"] == "MEANINGFUL_DOWNGRADE" and outcome["final_score"] == outcome["raw_score"]


def test_tiny_recovery_loss_cannot_neutralize_large_gains() -> None:
    before, after = _pair(dps=130.0, ehp=1_200.0, regen=0.0)  # -100% recovery, but -40/s on 20,000 Life = 0.2%/s
    before["Life"] = after["Life"] = 20_000.0
    outcome = _synthetic(before, after)
    assert _conflict(outcome)["kind"] == "NONE"
    assert outcome["verdict"] == "MEANINGFUL_UPGRADE" and outcome["final_score"] == outcome["raw_score"]


def test_a_mixed_defence_axis_needs_material_opposition_on_both_sides() -> None:
    """EHP +9% with a -0.3% sibling (worst max hit) is a clear defence gain, not a trade-off."""
    before, after = _pair(ehp=1_090.0, phys_hit=99.7)
    outcome = _synthetic(before, after)
    defense = outcome["item_impact"]["axes"]["DEFENSE"]
    assert defense["direction"] == "MIXED" and defense["significant"] is True  # labels preserved
    assert defense["material_positive"] is True and defense["material_negative"] is False
    assert _conflict(outcome)["kind"] == "NONE"
    assert outcome["verdict"] != "SIDEGRADE" and outcome["final_score"] == outcome["raw_score"]


def test_a_mixed_axis_with_both_directions_material_is_a_conflict() -> None:
    before, after = _pair(ehp=1_090.0, phys_hit=95.0)  # EHP +9%, worst max hit -5%
    outcome = _synthetic(before, after)
    defense = outcome["item_impact"]["axes"]["DEFENSE"]
    assert defense["material_positive"] is True and defense["material_negative"] is True
    assert _conflict(outcome)["kind"] == "MATERIAL"


def test_trivial_opposing_movement_does_not_create_a_conflict() -> None:
    """A capped-resistance style utility gain with a -0.3 point movement change is not a trade-off."""
    before = _raw(FireResist=60.0, TotalEHP=1_000.0)
    after = _raw(FireResist=75.0, TotalEHP=1_050.0, MovementSpeedMod=0.997)
    outcome = _synthetic(before, after)
    utility = outcome["item_impact"]["axes"]["UTILITY"]
    assert utility["direction"] == "MIXED"
    assert utility["material_positive"] is True and utility["material_negative"] is False
    assert _conflict(outcome)["kind"] == "NONE"
    assert outcome["verdict"] != "SIDEGRADE"


def test_material_two_sided_conflict_with_a_middling_score_is_the_canonical_sidegrade() -> None:
    before, after = _pair(dps=111.0, ehp=910.0)  # +11% offense, -9% EHP
    outcome = _synthetic(before, after)
    assert _conflict(outcome)["kind"] == "MATERIAL"
    assert SCORE_SCALE.minor_downgrade < outcome["raw_score"] < SCORE_SCALE.useful
    assert outcome["verdict"] == "SIDEGRADE" and outcome["final_score"] == SCORE_SCALE.equivalent
    assert outcome["verdict_reason"].startswith("Meaningful trade-off")


def test_material_conflict_with_a_strongly_negative_score_is_a_normal_downgrade() -> None:
    before, after = _pair(dps=75.0, ehp=1_050.0)  # -25% offense, +5% EHP
    outcome = _synthetic(before, after)
    assert _conflict(outcome)["kind"] == "MATERIAL"
    assert outcome["raw_score"] <= SCORE_SCALE.meaningful_downgrade
    assert outcome["verdict"] == "MEANINGFUL_DOWNGRADE" and outcome["final_score"] == outcome["raw_score"]
    assert "Trade-off: " in outcome["verdict_reason"]


def test_material_conflict_with_a_strongly_positive_score_is_capped_at_minor_upgrade() -> None:
    before, after = _pair(dps=125.0, ehp=960.0)  # +25% offense, -4% EHP
    outcome = _synthetic(before, after)
    assert _conflict(outcome)["kind"] == "MATERIAL"
    assert outcome["raw_score"] >= SCORE_SCALE.useful
    assert outcome["final_score"] == MINOR_UPGRADE_CEILING < SCORE_SCALE.useful
    assert outcome["verdict"] == "MINOR_UPGRADE"
    assert "MINOR UPGRADE" in outcome["verdict_reason"]


def test_negligible_opposition_is_disclosed_but_cannot_force_a_sidegrade() -> None:
    before, after = _pair(dps=130.0, ehp=1_200.0, regen=0.0)
    before["Life"] = after["Life"] = 20_000.0
    conflict = _conflict(_synthetic(before, after))
    assert conflict["kind"] == "NONE"
    (record,) = conflict["negligible_opposition"]
    assert (record["axis"], record["metric"], record["direction"]) == ("RECOVERY", "LifeRegenRecovery", "NEGATIVE")
    assert record["absolute_delta"] == pytest.approx(-40.0) and record["pool_pct"] == pytest.approx(0.2)


def test_near_zero_life_pools_never_invent_recovery_materiality() -> None:
    """Chaos Inoculation builds report Life 1; a missing Life field is unavailable evidence, not zero."""
    for life in (1.0, None):
        before, after = _pair(regen=0.5, life=1.0)
        before["Life"] = after["Life"] = life
        before["LifeRegenRecovery"], after["LifeRegenRecovery"] = 0.5, 2.5
        if life is None:
            del before["Life"], after["Life"]
        impact = interpret_item_impact(build_metric_profile(before, after), {"elements": {}}, before, after)
        recovery = impact.axes["RECOVERY"]
        assert recovery.material_positive is False and recovery.material_negative is False


# =========================================================================== 5. recovery_pool_pct


def _recovery_impact(delta: float, *, base: float = 40.0, life: float = 1_000.0, pool_pct: float = 0.5):
    before = _raw(Life=life, LifeRegenRecovery=base)
    after = _raw(Life=life, LifeRegenRecovery=base + delta)
    return interpret_item_impact(
        build_metric_profile(before, after), {"elements": {}}, before, after,
        thresholds=ImpactThresholds(recovery_pool_pct=pool_pct),
    ).axes["RECOVERY"]


def test_default_recovery_pool_threshold_is_a_documented_conservative_value() -> None:
    assert 0.25 <= ImpactThresholds().recovery_pool_pct <= 1.0


@pytest.mark.parametrize("sign", [1, -1])
def test_recovery_pool_boundary_holds_on_both_sides_for_gains_and_losses(sign: int) -> None:
    below = _recovery_impact(sign * 4.9)  # 0.49% of 1000 Life per second, +12% relative
    at = _recovery_impact(sign * 5.0)  # exactly the threshold
    above = _recovery_impact(sign * 5.5)
    key = "material_positive" if sign > 0 else "material_negative"
    assert below.significant is True and getattr(below, key) is False  # relatively significant, pool-negligible
    assert getattr(at, key) is True and getattr(above, key) is True
    assert not getattr(above, "material_negative" if sign > 0 else "material_positive")


def test_recovery_needs_both_the_relative_and_the_pool_gate() -> None:
    small_relative = _recovery_impact(40.0, base=2_000.0)  # +2% relative, but 4% of Life per second
    assert small_relative.significant is False and small_relative.material_positive is False


@pytest.mark.parametrize("pool_pct", [0.25, 0.5, 1.0, 2.0])
def test_case_b_is_robust_for_any_threshold_above_its_pool_fraction(pool_pct: float) -> None:
    result = replay_id(CASE_B)
    impact = impact_with(result, ImpactThresholds(recovery_pool_pct=pool_pct))
    outcome = result["evaluation_outcome"]
    assert impact.conflict.kind == "NONE"
    decision = decide_verdict(outcome["raw_score"], [], EvaluationQuality.FULL, item_impact=impact)
    assert decision.verdict is classify_score_verdict(outcome["raw_score"]) and decision.final_score == outcome["raw_score"]


def test_case_b_becomes_a_conflict_only_when_the_threshold_is_below_its_actual_pool_fraction() -> None:
    result = replay_id(CASE_B)
    assert impact_with(result, ImpactThresholds(recovery_pool_pct=0.05)).conflict.kind == "MATERIAL"


@pytest.mark.parametrize("pool_pct", [0.1, 0.25, 0.5, 1.0, 2.0])
def test_case_a_is_a_downgrade_whether_or_not_its_recovery_counts_as_material(pool_pct: float) -> None:
    result = replay_id(CASE_A)
    outcome = result["evaluation_outcome"]
    impact = impact_with(result, ImpactThresholds(recovery_pool_pct=pool_pct))
    assert impact.conflict.kind == ("MATERIAL" if pool_pct < 0.36 else "NONE")  # 6.8 / 1854 = 0.37% per second
    decision = decide_verdict(outcome["raw_score"], [], EvaluationQuality.FULL, item_impact=impact)
    assert decision.verdict is PublicVerdict.MEANINGFUL_DOWNGRADE


# =========================================================================== 6. monotonicity sweep

_LADDER = [
    PublicVerdict.MEANINGFUL_UPGRADE, PublicVerdict.MINOR_UPGRADE, PublicVerdict.SIDEGRADE,
    PublicVerdict.MINOR_DOWNGRADE, PublicVerdict.MEANINGFUL_DOWNGRADE,
]


def _rank(outcome: dict) -> int:
    return _LADDER.index(PublicVerdict(outcome["verdict"]))


def test_a_growing_defence_loss_never_improves_the_verdict_and_never_skips_a_band() -> None:
    """+20% offense against an EHP loss that grows from nothing to -20%."""
    ranks = []
    for ehp_change in (0.0, -0.5, -1.0, -2.0, -2.9, -3.0, -4.0, -6.0, -8.0, -10.0, -15.0, -20.0):
        before, after = _pair(dps=120.0, ehp=1_000.0 * (1 + ehp_change / 100.0))
        ranks.append(_rank(_synthetic(before, after)))
    assert ranks == sorted(ranks), ranks
    assert all(b - a <= 1 for a, b in zip(ranks, ranks[1:])), ranks


def test_a_growing_defence_gain_against_an_offense_loss_never_worsens_the_verdict() -> None:
    """-20% offense against an EHP gain that grows from nothing to +20%.

    SCORING-01b: the decisive-downgrade edge is the minor-downgrade edge, so every step is to an adjacent band
    (01a used the meaningful-downgrade edge, which skipped MINOR DOWNGRADE).
    """
    ranks = []
    for ehp_change in (0.0, 1.0, 2.9, 3.0, 5.0, 7.0, 8.0, 9.0, 10.0, 15.0, 20.0):
        before, after = _pair(dps=80.0, ehp=1_000.0 * (1 + ehp_change / 100.0))
        ranks.append(_rank(_synthetic(before, after)))
    assert ranks == sorted(ranks, reverse=True), ranks
    assert all(a - b <= 1 for a, b in zip(ranks, ranks[1:])), ranks


# =========================================================================== 7. user-facing consistency


def _mentions_tradeoff(texts: list[str]) -> list[str]:
    return [text for text in texts if "trade-off" in text.lower() or "tradeoff" in text.lower()]


@pytest.mark.parametrize("fixture_id", [CASE_A, CASE_B])
def test_no_visible_text_calls_a_non_conflict_a_trade_off(fixture_id: str) -> None:
    shown = surface(load_fixture(fixture_id))
    assert _conflict(shown["comparison"]["evaluation_outcome"])["kind"] == "NONE"
    assert _mentions_tradeoff(visible_text(shown)) == []
    assert shown["intel"]["product_verdict"] != "TRADEOFF"


@pytest.mark.parametrize("fixture_id", [CASE_A, CASE_B])
def test_the_negligible_axis_is_neither_a_reason_nor_a_trade_off_line(fixture_id: str) -> None:
    shown = surface(load_fixture(fixture_id))
    explanation = shown["intel"]["explanation"]
    reasons = explanation["improvements"] + explanation["tradeoffs"] + explanation["primary_reasons"]
    assert not [row for row in reasons if row.get("metric") == "recovery"]
    # R4: RECOVERY-02A (#58) made the legacy recovery axis a COMPOSITE of Life and Energy Shield regeneration, so it no longer
    # yields a legacy row for `negligible_opposition` to move (this assertion had failed on main since then). What the player
    # reads is unchanged and is asserted here: the negligible recovery change is disclosed, not presented as a reason or a trade-off.
    assert "recovery" not in [row["metric"] for row in explanation["tradeoffs"]]
    text = " ".join(visible_text(shown)).lower()
    assert "too small to offset" in text and "recovery" in text


def test_the_visible_reason_for_case_a_is_the_measured_loss_not_the_recovery_gain() -> None:
    shown = surface(load_fixture(CASE_A))
    assert shown["comparison"]["evaluation_outcome"]["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert "18.3% Recovery" not in shown["presentation"]["verdict_explanation"]
    assert "Offense" in shown["presentation"]["verdict_explanation"]


def test_a_material_conflict_keeps_the_trade_off_wording() -> None:
    shown = surface(load_fixture(GLOVES_TRADEOFF))
    assert _conflict(shown["comparison"]["evaluation_outcome"])["kind"] == "MATERIAL"
    assert shown["comparison"]["evaluation_outcome"]["verdict_reason"].startswith("Meaningful trade-off")
    assert shown["intel"]["product_verdict"] == "TRADEOFF"


# =========================================================================== 8. declared flips

# Every replay verdict/score change from the pre-SCORING-01a recording, reviewed by hand.
DECLARED_FLIPS = {
    # Case A: forced 50.0 discarded a raw 6.9 because +6.8 life/s (0.37% of Life per second) counted as a conflict.
    CASE_A: ("SIDEGRADE", "MEANINGFUL_DOWNGRADE"),
    # Case B: forced 50.0 discarded a raw 79.3 because -1.5 life/s (0.12% of Life per second) counted as a conflict.
    CASE_B: ("SIDEGRADE", "MEANINGFUL_UPGRADE"),
    # +21.7% offense against -4.3% EHP, raw 62.5: a material but lopsided conflict. It is no longer forced to
    # SIDEGRADE; the score decides, and a real named loss caps it at MINOR UPGRADE (SCORING-01a section 4).
    CORE04_RING: ("SIDEGRADE", "MINOR_UPGRADE"),
    # SCORING-01b: -10.6% minion offense against +5.3% EHP, raw 43.5. The conflict no longer softens a downgrade
    # the score already reads (net -6.5), so it is a MINOR DOWNGRADE that names the trade-off.
    MINION_RING: ("SIDEGRADE", "MINOR_DOWNGRADE"),
}


def test_every_replay_flip_is_declared_and_reviewed() -> None:
    changed = {row["fixture"]: (row["old_verdict"], row["new_verdict"]) for row in flip_rows() if row["changed"]}
    assert changed == DECLARED_FLIPS
