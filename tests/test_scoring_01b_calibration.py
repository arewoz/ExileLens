"""SCORING-01b: calibration, real-evidence regression and presentation finishing.

Builds on ``tests/test_scoring_01a_policy_core.py`` (same replay fixtures, same production pipeline; no PoB).

Sections
  1. zero-baseline recovery      - a regeneration change from exactly 0 is judged by the pool fraction, no invented percentage
  2. recovery_pool_pct evidence  - the value sits in the empty gap of the real observed pool fractions
  3. real material recovery      - an authentic regeneration-heavy build recognises a real gain
  4. resource sign               - an improvement of a negative sustain baseline is an improvement
  5. pareto consumers            - a SIDEGRADE is a trade-off only with a material conflict
  6. conflict transitions        - deterministic sweeps on real measurements: worse never improves, no skipped band
  7. presentation                - material trade-off vs dominant result with a small opposing change
"""

from __future__ import annotations

import copy
import json

import pytest

from exilelens.items.build_intel.axes import build_axes
from exilelens.items.evaluation_outcome import PublicVerdict, classify_score_verdict
from exilelens.items.item_impact import ImpactThresholds, interpret_item_impact
from exilelens.items.ranking import _pareto_summary, enrich_slot_comparison
from exilelens.items.value_profiles import ValueProfile
from exilelens.items.slots import pob_slot_to_product
from exilelens.metrics import build_metric_profile
from tests.policy_replay.replay import load_fixture, replay, replay_id, surface, visible_text
from tests.test_scoring_01a_policy_core import (
    CASE_A,
    CASE_B,
    CORE04_RING,
    GLOVES_TRADEOFF,
    MINION_RING,
    _conflict,
    _raw,
    _synthetic,
)

pytestmark = pytest.mark.itemcheck

REGEN_GAIN = "corpus02d2_amulet_life_and_regen_gain"
_LADDER = [
    PublicVerdict.MEANINGFUL_UPGRADE, PublicVerdict.MINOR_UPGRADE, PublicVerdict.SIDEGRADE,
    PublicVerdict.MINOR_DOWNGRADE, PublicVerdict.MEANINGFUL_DOWNGRADE,
]


def _rank(verdict: str) -> int:
    return _LADDER.index(PublicVerdict(verdict))


# =========================================================================== 1. zero-baseline recovery


def _zero(delta: float, *, life: float | None = 1_000.0, pool_pct: float = 0.5):
    before, after = _raw(LifeRegenRecovery=0.0), _raw(LifeRegenRecovery=delta)
    for raw in (before, after):
        if life is None:
            del raw["Life"]
        else:
            raw["Life"] = life
    return interpret_item_impact(
        build_metric_profile(before, after), {"elements": {}}, before, after,
        thresholds=ImpactThresholds(recovery_pool_pct=pool_pct),
    )


def test_a_zero_baseline_is_judged_by_the_pool_fraction_alone() -> None:
    material = _zero(5.0).axes["RECOVERY"]  # exactly 0.5% of 1000 Life per second
    below = _zero(4.9).axes["RECOVERY"]
    assert (material.direction, material.significant, material.material_positive) == ("POSITIVE", True, True)
    assert (below.direction, below.significant, below.material_positive) == ("POSITIVE", False, False)


def test_a_zero_baseline_never_gets_an_invented_percentage() -> None:
    impact = _zero(12.0)
    axis = impact.axes["RECOVERY"]
    (metric,) = [m for m in axis.metrics if m.key == "LifeRegenRecovery"]
    assert metric.percent_delta is None and metric.from_zero is True and axis.magnitude_pct is None
    assert metric.pool_pct == pytest.approx(1.2)
    json.dumps(impact.to_dict(), allow_nan=False)  # nothing infinite or NaN sneaks into the payload


def test_a_zero_baseline_can_be_a_loss_in_the_same_way() -> None:
    axis = _zero(-6.0).axes["RECOVERY"]
    assert (axis.direction, axis.material_negative, axis.material_positive) == ("NEGATIVE", True, False)


@pytest.mark.parametrize("life", [1.0, 0.0, None])
def test_a_zero_baseline_with_no_usable_life_pool_is_not_invented(life: float | None) -> None:
    axis = _zero(50.0, life=life).axes["RECOVERY"]
    assert (axis.direction, axis.significant, axis.material_positive, axis.material_negative) == ("NEUTRAL", False, False, False)


def test_no_change_from_zero_is_no_change() -> None:
    axis = _zero(0.0).axes["RECOVERY"]
    assert (axis.direction, axis.material_positive, axis.material_negative) == ("NEUTRAL", False, False)


def test_a_material_zero_baseline_gain_counts_in_a_conflict_and_a_small_one_is_only_disclosed() -> None:
    for regen, expected_kind in ((12.0, "MATERIAL"), (4.0, "NONE")):  # 0.6% vs 0.2% of 2000 Life per second
        before, after = _raw(Life=2_000.0, LifeRegenRecovery=0.0), _raw(CombinedDPS=90.0, Life=2_000.0, LifeRegenRecovery=regen)
        outcome = _synthetic(before, after)
        assert _conflict(outcome)["kind"] == expected_kind, regen
        assert outcome["verdict"] == "MEANINGFUL_DOWNGRADE"  # the raw score is decisive either way
        if expected_kind == "NONE":
            (record,) = _conflict(outcome)["negligible_opposition"]
            assert record["percent_delta"] is None and record["why"] == "BELOW_POOL_FLOOR"
            assert record["direction"] == "POSITIVE" and record["absolute_delta"] == pytest.approx(4.0)
            # Never a relative "trade-off" to begin with (no percentage exists), so no trade-off wording either.
            assert "trade" not in outcome["verdict_reason"].lower()


# =========================================================================== 2. recovery_pool_pct evidence

# Pool fractions (|change in life regeneration per second| / baseline max Life, in %) of every distinct regeneration
# change found when the whole real-PoB corpus (137 tests, 661 distinct evaluations, 7 authentic builds) was surveyed
# at SCORING-01b, plus the two community reports. See docs/SCORING-01B.md.
OBSERVED_SMALL = (0.039, 0.044, 0.055, 0.059, 0.112, 0.114, 0.122, 0.212, 0.228, 0.312, 0.367)
OBSERVED_LARGE = (0.638, 0.740)


def test_recovery_pool_pct_sits_in_the_empty_gap_between_the_small_and_large_observed_changes() -> None:
    """Evidence guard, not a fitted value: the threshold separates the observed changes and cuts none of them.

    If this fails, someone changed ``recovery_pool_pct`` (or new authentic data moved the gap): re-read
    docs/SCORING-01B.md before editing the numbers above."""
    assert max(OBSERVED_SMALL) < ImpactThresholds().recovery_pool_pct < min(OBSERVED_LARGE)


# =========================================================================== 3. real material recovery


def test_a_real_regeneration_heavy_build_recognises_a_material_recovery_gain() -> None:
    outcome = replay_id(REGEN_GAIN)["evaluation_outcome"]
    axes = outcome["item_impact"]["axes"]
    assert outcome["evaluation_quality"] == "FULL" and not outcome["guardrails_applied"]
    assert axes["RECOVERY"]["material_positive"] is True and axes["RECOVERY"]["direction"] == "POSITIVE"
    (metric,) = [m for m in axes["RECOVERY"]["metrics"] if m["key"] == "LifeRegenRecovery"]
    assert metric["pool_pct"] == pytest.approx(0.638, abs=0.001)
    assert _conflict(outcome)["kind"] == "NONE" and not _conflict(outcome)["negligible_opposition"]
    assert PublicVerdict(outcome["verdict"]) is classify_score_verdict(outcome["raw_score"])
    assert outcome["final_score"] == outcome["raw_score"]


# =========================================================================== 4. resource sign


def _resource(cost_before: float, regen_before: float, cost_after: float, regen_after: float):
    before = _raw(ManaPerSecondCost=cost_before, ManaRegenRecovery=regen_before)
    after = _raw(ManaPerSecondCost=cost_after, ManaRegenRecovery=regen_after)
    return build_axes(build_metric_profile(before, after), raw_current=before, raw_candidate=after)["RESOURCE"]


def test_an_improvement_of_a_negative_sustain_baseline_is_a_positive_change() -> None:
    axis = _resource(90.54045, 60.0, 90.54045, 60.8)  # sustain -30.54 -> -29.74 (Case B's numbers)
    assert axis.absolute_delta == pytest.approx(0.8) and axis.percent_delta == pytest.approx(2.62, abs=0.01)


def test_a_worsening_of_a_negative_sustain_baseline_is_a_negative_change() -> None:
    axis = _resource(90.0, 60.0, 91.0, 60.0)  # -30 -> -31
    assert axis.absolute_delta < 0 and axis.percent_delta == pytest.approx(-100.0 / 30.0)


def test_the_sign_of_the_change_is_the_sign_of_the_absolute_change_for_any_baseline() -> None:
    for cost, regen in ((90.0, 60.0), (10.0, 60.0), (60.0, 60.5)):
        for delta in (-3.0, 3.0):
            axis = _resource(cost, regen, cost, regen + delta)
            assert (axis.percent_delta > 0) == (axis.absolute_delta > 0), (cost, regen, delta)


def test_positive_and_zero_sustain_baselines_are_unchanged() -> None:
    assert _resource(10.0, 60.0, 10.0, 70.0).percent_delta == pytest.approx(20.0)  # 50 -> 60
    assert _resource(60.0, 60.0, 50.0, 60.0).percent_delta is None  # baseline 0: still no percentage


def test_an_improved_negative_sustain_is_listed_as_an_improvement_not_a_trade_off_line() -> None:
    """Case B's real numbers: its Resource row used to read '-2.6%' under the loss panel."""
    shown = surface(load_fixture(CASE_B))
    explanation = shown["intel"]["explanation"]
    assert [row["metric"] for row in explanation["tradeoffs"]] == []
    assert any(row["metric"] == "resource" and row["percent_delta"] > 0 for row in explanation["improvements"])
    assert shown["presentation"]["tradeoff_lines"] == []


# =========================================================================== 5. pareto consumers


def _row(fixture_id: str) -> dict:
    return replay_id(fixture_id)


def test_a_sidegrade_is_a_pareto_trade_off_only_with_a_material_conflict() -> None:
    assert _pareto_summary([_row(GLOVES_TRADEOFF)])["status"] == "TRADEOFF"  # SIDEGRADE, material conflict
    zero = enrich_slot_comparison({
        "pob_slot": "Ring 1", "product_slot": pob_slot_to_product("Ring 1").value,
        "baseline": {"metrics": _raw()}, "candidate": {"metrics": _raw(), "item_present": True}, "restore": {"pass": True},
    })
    assert zero["evaluation_outcome"]["verdict"] == "SIDEGRADE" and _conflict(zero["evaluation_outcome"])["kind"] == "NONE"
    assert _pareto_summary([zero])["status"] == "NEITHER_DOMINATES"


def test_pareto_without_conflict_information_keeps_the_old_reading() -> None:
    legacy = {"product_slot": "RING_1", "evaluation_outcome": {"verdict": "SIDEGRADE"}}
    assert _pareto_summary([legacy])["status"] == "TRADEOFF"


def test_other_pareto_readings_are_unchanged() -> None:
    assert _pareto_summary([_row(REGEN_GAIN)])["status"] == "DOMINATES"
    assert _pareto_summary([_row(CASE_A)])["status"] == "NEITHER_DOMINATES"


# =========================================================================== 6. conflict transitions (real measurements)


def _scaled(fixture_id: str, **factors: float) -> dict:
    """Replay a real fixture with named candidate metrics scaled: a deterministic what-if on measured values."""
    fixture = copy.deepcopy(load_fixture(fixture_id))
    metrics = fixture["comparison"]["candidate"]["metrics"]
    for name, factor in factors.items():
        metrics[fixture["primary_field"] if name == "offense" else name] *= factor
    return replay(fixture)["evaluation_outcome"]


def test_a_growing_offense_gain_against_a_real_defense_loss_climbs_through_every_band() -> None:
    """02D1 gloves (EHP -10.8%): sweep the offense change from -30% to +40% around the measured +11%.

    01a jumped MEANINGFUL DOWNGRADE -> SIDEGRADE across raw 40 (skipping MINOR DOWNGRADE); 01b does not."""
    ranks, verdicts = [], []
    for step in range(0, 71):
        outcome = _scaled(GLOVES_TRADEOFF, offense=0.70 + step * 0.01)
        ranks.append(_rank(outcome["verdict"]))
        verdicts.append(outcome["verdict"])
        assert outcome["evaluation_quality"] == "FULL"
    assert ranks == sorted(ranks, reverse=True), ranks  # a bigger gain never worsens the verdict
    assert all(a - b <= 1 for a, b in zip(ranks, ranks[1:])), ranks  # and never skips a band
    assert [v for i, v in enumerate(verdicts) if i == 0 or v != verdicts[i - 1]] == [
        "MEANINGFUL_DOWNGRADE", "MINOR_DOWNGRADE", "SIDEGRADE"]


def test_a_deepening_defense_loss_against_a_real_offense_gain_never_improves_the_verdict() -> None:
    """CORE-04 ring (offense +21.7%): sweep the EHP change from +5% to -40% around the measured -4.3%."""
    ranks = []
    for step in range(0, 91):
        outcome = _scaled(CORE04_RING, TotalEHP=1.05 - step * 0.005)
        ranks.append(_rank(outcome["verdict"]))
    assert ranks == sorted(ranks), ranks
    assert all(b - a <= 1 for a, b in zip(ranks, ranks[1:])), ranks


def test_every_edge_of_a_material_conflict_is_an_adjacent_band_on_a_real_build() -> None:
    """Fine sweep of the minion ring's offense loss (raw crosses 60, 47 and 40): the band ladder has no gap."""
    seen = []
    for step in range(0, 101):
        outcome = _scaled(MINION_RING, offense=0.80 + step * 0.006)
        seen.append(_rank(outcome["verdict"]))
        if _conflict(outcome)["kind"] == "MATERIAL":
            assert outcome["final_score"] in (outcome["raw_score"], 50.0, 59.0)
    assert seen == sorted(seen, reverse=True) and all(a - b <= 1 for a, b in zip(seen, seen[1:])), seen


def test_a_conflict_never_softens_a_downgrade_the_score_already_reads() -> None:
    for step in range(0, 71):
        outcome = _scaled(GLOVES_TRADEOFF, offense=0.70 + step * 0.01)
        if outcome["raw_score"] <= 47.0:
            assert outcome["final_score"] == outcome["raw_score"], outcome["raw_score"]
            assert outcome["verdict"] in {"MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE"}


@pytest.mark.parametrize("fixture_id, profile, verdict, final_score", [
    (CORE04_RING, ValueProfile.BALANCED, "MINOR_UPGRADE", 59.0),
    (CORE04_RING, ValueProfile.MAPPING, "MINOR_UPGRADE", 59.0),
    (CORE04_RING, ValueProfile.BOSSING, "SIDEGRADE", 50.0),
    (CORE04_RING, ValueProfile.DEFENSIVE, "MINOR_DOWNGRADE", 44.7),
    (MINION_RING, ValueProfile.BALANCED, "MINOR_DOWNGRADE", 43.5),
    (MINION_RING, ValueProfile.MAPPING, "MEANINGFUL_DOWNGRADE", 32.3),
    (MINION_RING, ValueProfile.BOSSING, "SIDEGRADE", 50.0),
    (MINION_RING, ValueProfile.DEFENSIVE, "MINOR_UPGRADE", 59.0),
    (GLOVES_TRADEOFF, ValueProfile.BALANCED, "SIDEGRADE", 50.0),
    (GLOVES_TRADEOFF, ValueProfile.MAPPING, "MINOR_UPGRADE", 59.0),
    (GLOVES_TRADEOFF, ValueProfile.BOSSING, "MINOR_DOWNGRADE", 41.5),
    (GLOVES_TRADEOFF, ValueProfile.DEFENSIVE, "MEANINGFUL_DOWNGRADE", 25.5),
])
def test_reviewed_material_conflict_results_for_every_profile(
    fixture_id: str, profile: ValueProfile, verdict: str, final_score: float,
) -> None:
    """The full survey found three 01b flips, including two outside Balanced; preserve all profile decisions."""
    outcome = replay(load_fixture(fixture_id), profile=profile)["evaluation_outcome"]
    assert _conflict(outcome)["kind"] == "MATERIAL"
    assert outcome["verdict"] == verdict and outcome["final_score"] == final_score
    if verdict.endswith("DOWNGRADE"):
        assert outcome["final_score"] == outcome["raw_score"]
        assert "Trade-off: " in outcome["verdict_reason"]


# =========================================================================== 7. presentation


def test_a_material_trade_off_and_a_dominant_result_read_differently() -> None:
    material = surface(load_fixture(GLOVES_TRADEOFF))
    dominant = surface(load_fixture(CASE_B))
    assert material["comparison"]["evaluation_outcome"]["verdict_reason"] == (
        "Meaningful trade-off: offense +11.0%; defense -10.9%.")
    assert material["presentation"]["tradeoff_title"] == "TRADE-OFF"
    assert dominant["comparison"]["evaluation_outcome"]["verdict_reason"].endswith(
        "Recovery -1.5 life/s (0.12% of max Life per second) is too small to offset the larger defense and utility gains.")
    assert dominant["presentation"]["tradeoff_title"] == "WHAT GETS WORSE"


def test_more_info_states_the_negligible_opposition_in_its_verdict_section() -> None:
    dominant = surface(load_fixture(CASE_B))
    why = next(section for section in dominant["more_info"]["sections"] if section["id"] == "why_verdict")
    assert any("too small to offset the larger defense and utility gains" in line for line in why["lines"])


def test_a_downgrade_is_explained_by_its_losses() -> None:
    shown = surface(load_fixture(CASE_A))
    explanation = shown["presentation"]["verdict_explanation"]
    assert shown["comparison"]["evaluation_outcome"]["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert explanation.startswith("-17.9% Offense") and "+" not in explanation.split("·")[0]
    assert "is too small to offset the larger offense and defense losses" in explanation
    assert shown["presentation"]["tradeoff_title"] == "WHAT GETS WORSE"


def test_companion_section_title_follows_the_conflict() -> None:
    from exilelens.items.companion import _tradeoff_section

    material, dominant = surface(load_fixture(GLOVES_TRADEOFF)), surface(load_fixture(CASE_A))
    assert _tradeoff_section(material["presentation"])["title"] == "TRADE-OFFS"
    assert _tradeoff_section(dominant["presentation"])["title"] == "WHAT GETS WORSE"


def test_an_upgrade_is_still_explained_by_its_gains() -> None:
    shown = surface(load_fixture(CASE_B))
    assert shown["presentation"]["verdict_explanation"].startswith("+32.9% Defence")


@pytest.mark.parametrize("fixture_id", [CASE_A, CASE_B, REGEN_GAIN])
def test_no_visible_text_says_trade_off_without_a_material_conflict(fixture_id: str) -> None:
    shown = surface(load_fixture(fixture_id))
    assert _conflict(shown["comparison"]["evaluation_outcome"])["kind"] == "NONE"
    assert [t for t in visible_text(shown) if "trade" in t.lower()] == []
    assert shown["presentation"]["tradeoff_title"] == "WHAT GETS WORSE"
