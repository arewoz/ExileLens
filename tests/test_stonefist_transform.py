"""CORPUS-02C: unit coverage for the Way of the Stonefist transformation adapter.

Uses a small hand-written mod table in the bridge's ``get_item_transform_mods``
shape (source tier -> game ``HandWraps<Id>`` tier) and a fake engine; real-PoB
behaviour is covered by tests/integration/test_corpus02c_stonefist.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from exilelens.items import evaluation as evaluation_module
from exilelens.items.stonefist import StonefistTransformer, no_ranged_rule
from exilelens.items.stonefist_rolls import BEST_ROLLS, MIDDLE_ROLLS, WORST_ROLLS

pytestmark = pytest.mark.itemcheck


def _mod(source_id: str, source: list[str], target: list[str], kind: str = "Prefix", group: str = "") -> dict[str, Any]:
    return {
        "source_id": source_id, "target_id": "HandWraps" + source_id, "source_lines": source,
        "target_lines": target, "source_type": kind, "source_group": group or source_id.rstrip("0123456789"),
    }


MODS = [
    _mod("IncreasedLife4", ["+(40-59) to maximum Life"], ["8% less damage taken while on Low Life"]),
    _mod("IncreasedLife6", ["+(70-84) to maximum Life"], ["10% less damage taken while on Low Life"]),
    _mod("LocalIncreasedEnergyShieldPercent7", ["(92-100)% increased Energy Shield"],
         ["(19-20)% more Global Evasion Rating and Energy Shield"], group="LocalEnergyShieldPercent"),
    _mod("LocalIncreasedEnergyShieldAndLife5", ["(33-38)% increased Energy Shield", "+(34-41) to maximum Life"],
         ["3% of Damage Taken Recouped as Life, Mana and Energy Shield"], group="LocalIncreasedEnergyShieldAndLife"),
    _mod("CriticalMultiplier4", ["(25-29)% increased Critical Damage Bonus"], ["+(2.1-2.5)% to Critical Hit Chance"], "Suffix"),
    _mod("ColdResist3", ["+(16-20)% to Cold Resistance"], ["+1% to Maximum Cold Resistance", "+(21-25)% to Cold Resistance"], "Suffix"),
    _mod("AddedPhysicalDamage6", ["Adds (6-10) to (12-17) Physical Damage to Attacks"],
         ["Attacks Gain (15-16)% of Damage as Extra Physical Damage"], group="PhysicalDamage"),
    _mod("AddedPhysicalDamage7", ["Adds (7-11) to (14-20) Physical Damage to Attacks"],
         ["Attacks Gain (17-18)% of Damage as Extra Physical Damage"], group="PhysicalDamage"),
    _mod("LifeLeech3", ["Leech (6-6.9)% of Physical Attack Damage as Life"],
         ["Leech (9-9.9)% of Physical Attack Damage as Life", "Leech Life (20-25)% slower"], "Suffix"),
]


def _lines(*texts: str) -> list[dict[str, Any]]:
    return [{"line": text, "fractured": False, "desecrated": False, "crafted": False} for text in texts]


def _lines_of(explicit: list[dict[str, Any]]) -> list[str]:
    return sorted(row["line"] for row in explicit)


def test_fixed_targets_are_exact_even_without_a_roll_rule() -> None:
    explicit, mapped, problems = StonefistTransformer(MODS, no_ranged_rule).transform_lines(
        _lines("+82 to maximum Life"),
    )
    assert not problems
    assert _lines_of(explicit) == ["10% less damage taken while on Low Life"]
    assert mapped[0]["target_id"] == "HandWrapsIncreasedLife6" and mapped[0]["ranged"] is False


def test_ranged_targets_need_a_bound_rule() -> None:
    _, _, problems = StonefistTransformer(MODS, no_ranged_rule).transform_lines(
        _lines("27% increased Critical Damage Bonus"),
    )
    assert problems and "no validated roll rule" in problems[0]


def test_independent_ranged_modifiers_take_their_own_bounds() -> None:
    lines = _lines("27% increased Critical Damage Bonus", "+18% to Cold Resistance", "Leech 6.5% of Physical Attack Damage as Life")
    expected = {
        WORST_ROLLS: ["+1% to Maximum Cold Resistance", "+2.1% to Critical Hit Chance", "+21% to Cold Resistance",
                      "Leech 9.0% of Physical Attack Damage as Life", "Leech Life 25% slower"],
        MIDDLE_ROLLS: ["+1% to Maximum Cold Resistance", "+2.3% to Critical Hit Chance", "+23% to Cold Resistance",
                       "Leech 9.5% of Physical Attack Damage as Life", "Leech Life 23% slower"],
        BEST_ROLLS: ["+1% to Maximum Cold Resistance", "+2.5% to Critical Hit Chance", "+25% to Cold Resistance",
                     "Leech 9.9% of Physical Attack Damage as Life", "Leech Life 20% slower"],
    }
    for rule, lines_expected in expected.items():
        explicit, mapped, problems = StonefistTransformer(MODS, rule).transform_lines(lines)
        assert not problems, rule.__name__
        # "slower" is worse when larger, so the worst roll is its largest value.
        assert _lines_of(explicit) == sorted(lines_expected), rule.__name__
        assert all(m["ranged"] for m in mapped)


def test_merged_same_stat_line_is_decomposed_into_both_modifiers() -> None:
    # 95% ES = 92-100 %ES prefix alone OR 33-38 hybrid + ... ; +37 life needs the hybrid.
    transformer = StonefistTransformer(MODS, WORST_ROLLS)
    solutions, problems = transformer.decompose(_lines("130% increased Energy Shield", "+37 to maximum Life"))
    assert not problems
    ids = [sorted(p.source_id for p in pairs) for pairs, _ in solutions]
    assert ids == [["LocalIncreasedEnergyShieldAndLife5", "LocalIncreasedEnergyShieldPercent7"]]
    explicit, _, problems = transformer.transform_lines(_lines("130% increased Energy Shield", "+37 to maximum Life"))
    assert not problems
    assert _lines_of(explicit) == [
        "19% more Global Evasion Rating and Energy Shield",
        "3% of Damage Taken Recouped as Life, Mana and Energy Shield",
    ]


def test_merged_line_blocks_a_source_dependent_rule_only() -> None:
    def derived(pair, values):  # a hypothetical rule that needs the source roll
        return [2.3]

    derived.__name__ = "derived"
    lines = _lines("130% increased Energy Shield", "+37 to maximum Life")
    _, _, problems = StonefistTransformer(MODS, derived).transform_lines(lines)
    assert problems and "merged into a shared line" in problems[0]


def test_separate_same_stat_lines_are_assigned_one_modifier_each() -> None:
    solutions, problems = StonefistTransformer(MODS, WORST_ROLLS).decompose(
        _lines("95% increased Energy Shield", "35% increased Energy Shield", "+37 to maximum Life"),
    )
    assert not problems
    assert {tuple(sorted(p.source_id for p in pairs)) for pairs, _ in solutions} == {
        ("LocalIncreasedEnergyShieldAndLife5", "LocalIncreasedEnergyShieldPercent7"),
    }
    _, own = solutions[0]
    assert own[("LocalIncreasedEnergyShieldPercent7", "#% increased Energy Shield")] == [95.0]


def test_overlapping_tiers_widen_the_bounds_only() -> None:
    lines = _lines("Adds 8 to 16 Physical Damage to Attacks")
    solutions, _ = StonefistTransformer(MODS, WORST_ROLLS).decompose(lines)
    assert len(solutions) == 2  # AddedPhysicalDamage6 and 7 both fit
    worst, _, _ = StonefistTransformer(MODS, WORST_ROLLS).transform_lines(lines)
    middle, _, _ = StonefistTransformer(MODS, MIDDLE_ROLLS).transform_lines(lines)
    best, _, _ = StonefistTransformer(MODS, BEST_ROLLS).transform_lines(lines)
    assert _lines_of(worst) == ["Attacks Gain 15% of Damage as Extra Physical Damage"]
    assert _lines_of(middle) == ["Attacks Gain 17% of Damage as Extra Physical Damage"]
    assert _lines_of(best) == ["Attacks Gain 18% of Damage as Extra Physical Damage"]
    _, _, problems = StonefistTransformer(MODS, no_ranged_rule).transform_lines(lines)
    assert problems


def test_impossible_items_are_refused() -> None:
    transformer = StonefistTransformer(MODS, WORST_ROLLS)
    assert transformer.transform_lines(_lines("+500 to maximum Life"))[2]  # no tier fits
    assert transformer.transform_lines(_lines("Some unrelated modifier"))[2]  # no mapping
    # Four prefixes cannot exist on one item.
    four = _lines("+82 to maximum Life", "95% increased Energy Shield", "Adds 8 to 16 Physical Damage to Attacks",
                  "35% increased Energy Shield", "+37 to maximum Life")
    assert transformer.transform_lines(four)[2]


class _FakeEngine:
    def __init__(self, described: dict[str, Any]) -> None:
        self.described = described
        self.calls: list[str] = []

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(method)
        if method == "describe_item":
            return self.described
        if method == "get_base_implicits":
            return {"lines": ["Has +3 to Evasion Rating per player level"]}
        if method == "rebuild_item":
            return {"item_raw": "rebuilt:" + params["base_name"], "base_name": params["base_name"], "type": "Gloves"}
        raise AssertionError(method)


def test_already_transformed_items_pass_through_untouched() -> None:
    engine = _FakeEngine({"type": "Gloves", "base_name": "Runeforged Fists of Stone", "rarity": "RARE", "explicit": []})
    result = StonefistTransformer(MODS, WORST_ROLLS).transform(engine, "raw text")
    assert result.ok and result.already_transformed and result.item_raw == "raw text"
    assert "rebuild_item" not in engine.calls


def test_unique_gloves_without_evidence_are_not_guessed() -> None:
    engine = _FakeEngine({"type": "Gloves", "base_name": "Vaal Gloves", "rarity": "UNIQUE", "name": "Not A Real Unique",
                          "explicit": _lines("+82 to maximum Life")})
    result = StonefistTransformer(MODS, WORST_ROLLS).transform(engine, "raw")
    assert not result.ok
    assert result.unresolved == ["the unique gloves Not A Real Unique have no verified Way of the Stonefist transformation"]


def test_runic_bases_become_runeforged_fists_of_stone() -> None:
    engine = _FakeEngine({"type": "Gloves", "base_name": "Runeforged Massive Mitts", "rarity": "RARE", "runic": True,
                          "explicit": _lines("+82 to maximum Life")})
    result = StonefistTransformer(MODS, WORST_ROLLS).transform(engine, "raw")
    assert result.ok and result.base_name == "Runeforged Fists of Stone" and not result.bounded


# --------------------------------------------------------------------------- verdict-spanning wrapper


def _fake_result(verdict: str, metrics: dict[str, float], bounded: bool = True, alternatives: int = 1, pattern: str = "SINGLE_AXIS") -> dict[str, Any]:
    row = {
        "pob_slot": "Gloves",
        "primary_metric_field": "CombinedDPS",
        "item_transform": {"candidate": {"ok": True, "bounded": bounded, "alternatives": alternatives}},
        "metric_profile": {"primary_offense": {"percent_delta": metrics["CombinedDPS"] - 100}},
        "candidate": {"metrics": metrics},
        "evaluation_outcome": {"verdict": verdict, "item_impact": {"pattern": pattern, "axes": {}}, "all_deltas": [
            {"key": "primary_offense", "label": "Damage", "percent_delta": metrics["CombinedDPS"] - 100, "candidate": metrics["CombinedDPS"]},
        ], "unsupported_or_unmodeled": []},
    }
    return {"slot_comparisons": [row], "presentation": {"evaluation_outcome": {"unsupported_or_unmodeled": []}},
            "recommendation": {"pob_slot": "Gloves"}}


class _BatchEngine:
    """Records how the wrapper asked PoB to measure its configurations."""

    def __init__(self) -> None:
        self.singles: list[str] = []
        self.batches: list[list[str]] = []

    def evaluate_item_slots(self, slots, item_raw, **kwargs):
        self.singles.append(item_raw)
        return {"measured": item_raw}

    def evaluate_item_variants(self, slots, item_raws, **kwargs):
        self.batches.append(list(item_raws))
        return [{"measured": raw} for raw in item_raws]


def _stub(monkeypatch: pytest.MonkeyPatch, by_bound: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Stand-in for the item evaluation: suspends at its measurement like the real one."""
    calls: list[dict[str, Any]] = []

    def steps(raw_text, engine, **kwargs):
        calls.append(kwargs)
        key = f'{kwargs["stonefist_bound"]}:{kwargs.get("stonefist_alternative") or 0}'
        if kwargs.get("stonefist_unresolved"):
            result, transform, key = {"unresolved": kwargs["stonefist_unresolved"]}, None, "unresolved"
        else:
            result = by_bound.get(key) or by_bound[kwargs["stonefist_bound"]]
            transform = result["slot_comparisons"][0]["item_transform"]["candidate"]
        measured = yield evaluation_module._MeasurementRequest(
            slots=("Gloves",), item_raw=key, context="MAP", component_keys=None, baseline_overrides=None,
            defer_restore=bool(kwargs.get("defer_restore")), stonefist=transform,
        )
        assert measured == {"measured": key}, "each configuration must receive its own measurement"
        return result

    monkeypatch.setattr(evaluation_module, "_evaluate_item_steps", steps)
    return calls


def test_verdict_changing_across_the_roll_range_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(monkeypatch, {
        "worst": _fake_result("SIDEGRADE", {"CombinedDPS": 99, "TotalEHP": 10}),
        "middle": _fake_result("SIDEGRADE", {"CombinedDPS": 101, "TotalEHP": 10}),
        "best": _fake_result("MINOR_UPGRADE", {"CombinedDPS": 104, "TotalEHP": 10}),
    })
    result = evaluation_module.evaluate_item("raw", _BatchEngine())
    assert "the verdict changes (SIDEGRADE and MINOR_UPGRADE)" in result["unresolved"]
    assert [c.get("stonefist_bound") for c in calls] == ["worst", "middle", "best", "worst"]


def test_matching_ends_with_a_different_middle_verdict_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst": _fake_result("SIDEGRADE", {"CombinedDPS": 99, "TotalEHP": 10}),
        "middle": _fake_result("MINOR_DOWNGRADE", {"CombinedDPS": 100, "TotalEHP": 10}),
        "best": _fake_result("SIDEGRADE", {"CombinedDPS": 101, "TotalEHP": 10}),
    })
    assert "verdict changes" in evaluation_module.evaluate_item("raw", _BatchEngine())["unresolved"]


def test_non_monotone_pob_results_are_refused_even_when_verdicts_match(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst": _fake_result("SIDEGRADE", {"CombinedDPS": 99, "TotalEHP": 12}),
        "middle": _fake_result("SIDEGRADE", {"CombinedDPS": 100, "TotalEHP": 10}),
        "best": _fake_result("SIDEGRADE", {"CombinedDPS": 101, "TotalEHP": 11}),
    })
    reason = evaluation_module.evaluate_item("raw", _BatchEngine())["unresolved"]
    assert "not ordered across the roll range (TotalEHP)" in reason


def test_consistent_ordered_range_reports_a_guaranteed_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 110, "TotalEHP": 10}),
        "middle": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 115, "TotalEHP": 10}),
        "best": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 120, "TotalEHP": 10}),
    })
    result = evaluation_module.evaluate_item("raw", _BatchEngine())
    bounds = result["slot_comparisons"][0]["stonefist_roll_bounds"]
    assert bounds["guarantee"] == "an upgrade at each measured roll"
    assert bounds["ranges"]["primary_offense"]["worst_pct"] == 10 and bounds["ranges"]["primary_offense"]["best_pct"] == 20
    assert result["presentation"]["roll_dependent"] is True
    assert "+10.0% to +20.0%" in result["presentation"]["verdict_explanation"]
    assert "[measured +10.0% to +20.0%]" in result["slot_comparisons"][0]["evaluation_outcome"]["all_deltas"][0]["label"]


def test_exact_candidates_are_evaluated_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(monkeypatch, {"worst": _fake_result("SIDEGRADE", {"CombinedDPS": 100, "TotalEHP": 10}, bounded=False)})
    evaluation_module.evaluate_item("raw", _BatchEngine())
    assert len(calls) == 1


def test_every_decomposition_alternative_must_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    common = {
        "worst:0": _fake_result("MINOR_DOWNGRADE", {"CombinedDPS": 90, "TotalEHP": 10}, bounded=False, alternatives=2),
        "worst:1": _fake_result("SIDEGRADE", {"CombinedDPS": 97, "TotalEHP": 10}, bounded=False, alternatives=2),
    }
    calls = _stub(monkeypatch, dict(common))
    reason = evaluation_module.evaluate_item("raw", _BatchEngine())["unresolved"]
    assert "fit several glove modifier combinations" in reason and "MINOR_DOWNGRADE and SIDEGRADE" in reason
    assert [(c.get("stonefist_bound"), c.get("stonefist_alternative")) for c in calls] == [
        ("worst", 0), ("worst", 1), ("worst", 0),
    ]


def test_agreeing_alternatives_report_the_union_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst:0": _fake_result("MINOR_DOWNGRADE", {"CombinedDPS": 95, "TotalEHP": 10}, bounded=False, alternatives=2),
        "worst:1": _fake_result("MINOR_DOWNGRADE", {"CombinedDPS": 92, "TotalEHP": 10}, bounded=False, alternatives=2),
    })
    result = evaluation_module.evaluate_item("raw", _BatchEngine())
    bounds = result["slot_comparisons"][0]["stonefist_roll_bounds"]
    assert bounds["alternatives"] == 2 and bounds["verified_configurations"] == 2
    assert bounds["ranges"]["primary_offense"]["worst_pct"] == -8 and bounds["ranges"]["primary_offense"]["best_pct"] == -5
    # The shown numbers are the lowest-damage configuration, labelled with the full range.
    assert result["slot_comparisons"][0]["candidate"]["metrics"]["CombinedDPS"] == 92
    assert "one of 2 possible items" in bounds["summary"]


def test_same_verdict_reached_through_different_patterns_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review counterexample: TRADEOFF forces SIDEGRADE at the worst roll while the score band
    gives SIDEGRADE at the best roll; an intermediate roll can leave the TRADEOFF pattern with a
    downgrade-band score. Matching verdicts are not enough -- the verdict structure must match."""
    _stub(monkeypatch, {
        "worst": _fake_result("SIDEGRADE", {"CombinedDPS": 95, "TotalEHP": 10}, pattern="TRADEOFF"),
        "middle": _fake_result("SIDEGRADE", {"CombinedDPS": 99, "TotalEHP": 10}, pattern="TRADEOFF"),
        "best": _fake_result("SIDEGRADE", {"CombinedDPS": 101, "TotalEHP": 10}, pattern="SINGLE_AXIS"),
    })
    reason = evaluation_module.evaluate_item("raw", _BatchEngine())["unresolved"]
    assert "changes character" in reason


# --------------------------------------------------------------------------- batched configuration measurement


def test_roll_configurations_are_measured_in_one_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 110, "TotalEHP": 10}),
        "middle": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 115, "TotalEHP": 10}),
        "best": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 120, "TotalEHP": 10}),
    })
    engine = _BatchEngine()
    evaluation_module.evaluate_item("raw", engine, defer_restore=True)
    assert engine.batches == [["worst:0", "middle:0", "best:0"]] and engine.singles == []


def test_every_alternative_and_roll_shares_the_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst:0": _fake_result("MINOR_DOWNGRADE", {"CombinedDPS": 95, "TotalEHP": 10}, alternatives=2),
        "middle:0": _fake_result("MINOR_DOWNGRADE", {"CombinedDPS": 96, "TotalEHP": 10}, alternatives=2),
        "best:0": _fake_result("MINOR_DOWNGRADE", {"CombinedDPS": 97, "TotalEHP": 10}, alternatives=2),
        "worst:1": _fake_result("MINOR_DOWNGRADE", {"CombinedDPS": 92, "TotalEHP": 10}, bounded=False, alternatives=2),
    })
    engine = _BatchEngine()
    result = evaluation_module.evaluate_item("raw", engine)
    assert engine.batches == [["worst:0", "middle:0", "best:0", "worst:1"]] and engine.singles == []
    assert result["slot_comparisons"][0]["stonefist_roll_bounds"]["verified_configurations"] == 4


def test_exact_candidates_keep_their_single_deferred_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(monkeypatch, {"worst": _fake_result("SIDEGRADE", {"CombinedDPS": 100, "TotalEHP": 10}, bounded=False)})
    engine = _BatchEngine()
    evaluation_module.evaluate_item("raw", engine, defer_restore=True)
    assert engine.singles == ["worst:0"] and engine.batches == []
    assert calls[0]["defer_restore"] is True


def test_a_refusal_after_the_batch_is_measured_on_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst": _fake_result("SIDEGRADE", {"CombinedDPS": 99, "TotalEHP": 10}),
        "middle": _fake_result("SIDEGRADE", {"CombinedDPS": 101, "TotalEHP": 10}),
        "best": _fake_result("MINOR_UPGRADE", {"CombinedDPS": 104, "TotalEHP": 10}),
    })
    engine = _BatchEngine()
    assert "verdict changes" in evaluation_module.evaluate_item("raw", engine)["unresolved"]
    assert engine.batches == [["worst:0", "middle:0", "best:0"]] and engine.singles == ["unresolved"]


def test_engines_without_variant_batches_measure_each_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 110, "TotalEHP": 10}),
        "middle": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 115, "TotalEHP": 10}),
        "best": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 120, "TotalEHP": 10}),
    })
    requests: list[Any] = []

    class SingleEngine:
        def evaluate_item_slots(self, slots, item_raw, **kwargs):
            requests.append((item_raw, kwargs["defer_restore"]))
            return {"measured": item_raw}

    result = evaluation_module.evaluate_item("raw", SingleEngine(), defer_restore=True)
    assert "stonefist_roll_bounds" in result
    # Measured one after another, so none of them may leave its restore deferred.
    assert requests == [("worst:0", False), ("middle:0", False), ("best:0", False)]


def test_a_failed_batch_fails_the_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 110, "TotalEHP": 10}),
        "middle": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 115, "TotalEHP": 10}),
        "best": _fake_result("MEANINGFUL_UPGRADE", {"CombinedDPS": 120, "TotalEHP": 10}),
    })

    class FailingEngine(_BatchEngine):
        def evaluate_item_variants(self, slots, item_raws, **kwargs):
            raise RuntimeError("restore failed")

    with pytest.raises(RuntimeError, match="restore failed"):
        evaluation_module.evaluate_item("raw", FailingEngine())


# --------------------------------------------------------------------------- one-at-a-time roll probes

_TWO_ROLLS = ["Attacks Gain #% of Damage as Extra Cold Damage", "+#% to Cold Resistance"]


def _rolled(verdict: str, metrics: dict[str, float], ranged: list[str] | None = None, alternatives: int = 1) -> dict[str, Any]:
    result = _fake_result(verdict, metrics, alternatives=alternatives)
    result["slot_comparisons"][0]["item_transform"]["candidate"]["ranged_lines"] = list(ranged or _TWO_ROLLS)
    return result


def test_each_ranged_line_is_probed_alone_in_the_same_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {
        "worst": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 110, "TotalEHP": 10}),
        "middle": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 115, "TotalEHP": 11}),
        "best": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 120, "TotalEHP": 12}),
        f"flip:{_TWO_ROLLS[0]}": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 118, "TotalEHP": 10}),
        f"flip:{_TWO_ROLLS[1]}": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 110, "TotalEHP": 12}),
    })
    engine = _BatchEngine()
    result = evaluation_module.evaluate_item("raw", engine)
    assert engine.batches == [["worst:0", "middle:0", "best:0", f"flip:{_TWO_ROLLS[0]}:0", f"flip:{_TWO_ROLLS[1]}:0"]]
    bounds = result["slot_comparisons"][0]["stonefist_roll_bounds"]
    assert bounds["verified_configurations"] == 5 and bounds["single_roll_probes"] == 2
    assert "each ranged modifier alone at its highest roll" in bounds["summary"]


def test_a_roll_that_lowers_an_output_on_its_own_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The diagonal worst <= middle <= best holds, but one roll alone costs EHP: a trade-off
    between rolls that the diagonal cannot see, so no verdict is guaranteed."""
    _stub(monkeypatch, {
        "worst": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 110, "TotalEHP": 10}),
        "middle": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 115, "TotalEHP": 11}),
        "best": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 120, "TotalEHP": 12}),
        f"flip:{_TWO_ROLLS[0]}": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 118, "TotalEHP": 9}),
        f"flip:{_TWO_ROLLS[1]}": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 112, "TotalEHP": 12}),
    })
    reason = evaluation_module.evaluate_item("raw", _BatchEngine())["unresolved"]
    assert f'not ordered when only "{_TWO_ROLLS[0]}" changes (TotalEHP)' in reason


def test_a_probe_with_a_different_verdict_structure_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _fake_result("SIDEGRADE", {"CombinedDPS": 100, "TotalEHP": 10}, pattern="TRADEOFF")
    _stub(monkeypatch, {
        "worst": _rolled("SIDEGRADE", {"CombinedDPS": 99, "TotalEHP": 10}),
        "middle": _rolled("SIDEGRADE", {"CombinedDPS": 100, "TotalEHP": 10}),
        "best": _rolled("SIDEGRADE", {"CombinedDPS": 101, "TotalEHP": 10}),
        f"flip:{_TWO_ROLLS[0]}": _rolled("SIDEGRADE", {"CombinedDPS": 100, "TotalEHP": 10}),
        f"flip:{_TWO_ROLLS[1]}": probe,
    })
    assert "changes character" in evaluation_module.evaluate_item("raw", _BatchEngine())["unresolved"]


@pytest.mark.parametrize(("ranged", "probes"), [
    (_TWO_ROLLS[:1], 0), (_TWO_ROLLS, 2), ([f"{c} #" for c in "abcde"], 5), ([f"{c} #" for c in "abcdef"], 0),
])
def test_probes_are_measured_only_within_the_configuration_budget(monkeypatch: pytest.MonkeyPatch, ranged, probes) -> None:
    common = {bound: _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 110 + i, "TotalEHP": 10}, ranged)
              for i, bound in enumerate(("worst", "middle", "best"))}
    flips = {f"flip:{t}": _rolled("MEANINGFUL_UPGRADE", {"CombinedDPS": 111, "TotalEHP": 10}, ranged) for t in ranged}
    _stub(monkeypatch, {**common, **flips})
    engine = _BatchEngine()
    evaluation_module.evaluate_item("raw", engine)
    assert len(engine.batches[0]) == 3 + probes


def test_probes_are_skipped_when_they_would_exceed_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    ranged = ["a #", "b #", "c #", "d #"]
    table = {}
    for alternative in range(4):
        for i, bound in enumerate(("worst", "middle", "best")):
            table[f"{bound}:{alternative}"] = _rolled("MINOR_DOWNGRADE", {"CombinedDPS": 90 + i, "TotalEHP": 10}, ranged, alternatives=4)
        for t in ranged:
            table[f"flip:{t}:{alternative}"] = _rolled("MINOR_DOWNGRADE", {"CombinedDPS": 91, "TotalEHP": 10}, ranged, alternatives=4)
    _stub(monkeypatch, table)
    engine = _BatchEngine()
    result = evaluation_module.evaluate_item("raw", engine)
    # 12 bound configurations already exceed the budget of 8: no probes.
    assert len(engine.batches[0]) == 12
    assert result["slot_comparisons"][0]["stonefist_roll_bounds"]["single_roll_probes"] == 0
