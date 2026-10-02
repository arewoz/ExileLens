"""R1.5 actionable Build Intelligence: ladders, response curves, action plan, focus, packages, health, coverage, diff."""

from __future__ import annotations

import copy
import json

import pytest

from exilelens.analysis import actionable as act
from exilelens.analysis import curves as cv
from exilelens.analysis.actionable import build_actionable, diff_actionable
from exilelens.analysis.catalog import ProbeCatalog
from exilelens.analysis.pipeline import analyze_build, rescore_analysis
from exilelens.analysis.priorities import build_priorities
from exilelens.analysis.strongest import strongest_responses
from tests.test_m5_3_build_priorities import BASELINE, PROBES, _probe, _result
from tests.test_m5_5_remediation import RING, FakeEngine

pytestmark = pytest.mark.itemcheck

CHAOS_NEED = {"code": "LOW_CHAOS_RES", "severity": "high", "metric": "chaos_res", "deficit": 33.0}
FIRE_NEED = {"code": "RES_CAP_MISSING", "severity": "critical", "metric": "fire_res", "deficit": 17.0}


def _leaf(value):
    return {"value": value, "evidence": "OBSERVED"}


def _res(current, cap=75.0):
    return {"current": _leaf(current), "cap": _leaf(cap), "missing": _leaf(max(0.0, cap - current)),
            "state": _leaf("BELOW_CAP" if current < cap else "CAPPED")}


def _fingerprint(*, fire=75.0, chaos=75.0, strength_short=0.0, pool=500.0, cost=40.0):
    return {
        "defense": {"resistances": {"fire": _res(fire), "cold": _res(75.0), "lightning": _res(75.0), "chaos": _res(chaos)}},
        "requirements": {"strength": {"value": _leaf(100.0 - strength_short), "highest_requirement": _leaf(100.0),
                                      "margin": _leaf(-strength_short), "state": _leaf("DEFICIT" if strength_short else "MET")}},
        "resources": {"mana": {"unreserved": _leaf(pool), "cost_per_use": _leaf(cost)}},
    }


def _analysis(probes=PROBES, *, needs=(), curves=(), slots=(), confidence="HIGH", baseline=None, **fp):
    result = _result(probes, needs=list(needs), confidence=confidence, fingerprint_extra=_fingerprint(**fp))
    if baseline:
        result["baseline"] = {**result["baseline"], **baseline}
        from exilelens.analysis.sensitivity import build_sensitivity

        result["build_sensitivity"] = build_sensitivity(result)
    result["build_priorities"] = build_priorities(result)
    result["strongest_responses"] = strongest_responses(result["build_priorities"])
    result["response_curves"] = {"curves": list(curves)}
    result["slots"] = list(slots)
    result["actionable"] = build_actionable(result)
    return result


def _act(*args, **kwargs):
    return _analysis(*args, **kwargs)["actionable"]


# -------------------------------------------------------------------------- ladder


def test_ladder_extends_the_priorities_lane_in_the_same_order_and_keeps_the_tested_change() -> None:
    extra = [_probe("INTELLIGENCE2", "Wisdom", "+20 to Wisdom", 20.0, offense=1.4), _probe("X", "Tiny", "+1 tiny", 1.0, offense=0.3)]
    result = _analysis([*PROBES, *extra])
    ladder = result["actionable"]["ladders"]["damage"]
    assert [row["label"] for row in ladder][:3] == [row["label"] for row in result["build_priorities"]["offense"]]
    assert [(row["position"], row["tested_change"], row["response_percent"]) for row in ladder] == [
        (1, "+1 to Level of all Spell Skills", 8.7), (2, "10% increased Cast Speed", 6.1), (3, "20% increased Spell Damage", 3.5),
        (4, "+20 to Intelligence", 2.1), (5, "+20 to Wisdom", 1.4)]
    assert len(ladder) <= act.MAX_LADDER_ROWS and "Tiny" not in [row["label"] for row in ladder]  # row 6 and weak rows are not "useful"
    assert all(row["tested_change"] for rows in result["actionable"]["ladders"].values() for row in rows)


def test_ladder_excludes_no_signal_rejected_and_resistance_and_keeps_catalog_order_on_ties() -> None:
    probes = [_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, offense=6.0),
              _probe("SPELL_DAMAGE", "Spell Damage", "20% increased Spell Damage", 20.0, offense=6.0),
              _probe("CRIT_CHANCE", "Crit Chance", "5% increased Critical Hit Chance", 5.0, status="NO_SIGNAL"),
              _probe("ATTACK_SPEED", "Attack Speed", "10% increased Attack Speed", 10.0, status="REJECTED"),
              _probe("FIRE_RES", "Fire Resistance", "+20% to Fire Resistance", 20.0, family="resistance", offense=9.0)]
    ladder = _act(probes)["ladders"]["damage"]
    assert [row["label"] for row in ladder] == ["Cast Speed", "Spell Damage"]
    assert [row["label"] for row in _act(list(reversed(probes[:2])) + probes[2:])["ladders"]["damage"]] == ["Spell Damage", "Cast Speed"]
    text = json.dumps(_act(probes)["ladders"])
    for forbidden in ("per_unit", "per_point", "score", "probe_id"):
        assert forbidden not in text


def test_low_confidence_damage_gives_no_damage_ladder_and_no_definitive_best_stat() -> None:
    actionable = _act(PROBES, confidence="LOW")
    assert actionable["ladders"]["damage"] == [] and actionable["ladders"]["ehp"]
    assert actionable["best_response"]["status"] == "COULD_NOT_ESTABLISH" and "Limited confidence" in actionable["best_response"]["reason"]
    assert all(action.get("axis") != "damage" for action in actionable["action_plan"])
    assert next(row for row in actionable["build_health"] if row["key"] == "damage")["state"] == act.LIMITED


# -------------------------------------------------------------------------- curves


class _Probes:
    pob_recalcs = 0


def _global(probe_id, name, line, magnitude, **axes):
    probe = _probe(probe_id, name, line, magnitude, **axes)
    return probe


def _second(responses):
    def run(probe_id, magnitude):
        _Probes.pob_recalcs += 1
        value = responses.get(probe_id)
        if value is None:
            return {"probe_id": probe_id, "status": "REJECTED", "magnitude": magnitude}
        key, percent = value
        return {"probe_id": probe_id, "status": "ok", "magnitude": magnitude, "line": f"x2 {probe_id}",
                "metric_profile": {key: {"availability": "available", "percent_delta": percent}}}
    return run


def test_second_step_is_the_increment_between_the_two_measurements_not_the_raw_doubled_response() -> None:
    result = _analysis()
    _Probes.pob_recalcs = 0
    curves = cv.measure_response_curves(
        _Probes, ProbeCatalog(), result["global_probes"], result["build_priorities"],
        run_probe=_second({"SPELL_SKILL_LEVELS": ("primary_offense", 16.5), "ENERGY_SHIELD": ("worst_max_hit", 4.0), "CAST_SPEED": ("primary_offense", 9.1)}),
    )
    by = {c["label"]: c for c in curves["curves"]}
    levels = by["Spell Skill Levels"]
    assert (levels["first_percent"], levels["total_percent"], levels["second_percent"]) == (8.7, 16.5, 7.8)
    assert levels["ratio"] == round(7.8 / 8.7, 3) and levels["state"] == cv.HOLDS and levels["step"] == 1.0
    assert (by["Energy Shield"]["axis"], by["Energy Shield"]["second_percent"], by["Energy Shield"]["state"]) == ("max_hit", 2.0, cv.HOLDS)
    assert by["Cast Speed"]["second_percent"] == 3.0 and by["Cast Speed"]["state"] == cv.DROPS
    assert curves["new_recalcs"] == 3 == cv.MAX_CURVES and len(curves["curves"]) == 3  # bounded budget


def test_curve_classification_boundaries() -> None:
    assert cv.classify(10.0, 11.5) == cv.HOLDS and cv.classify(10.0, 11.6) == cv.GROWS
    assert cv.classify(10.0, 8.5) == cv.HOLDS and cv.classify(10.0, 8.49) == cv.WEAKENS
    assert cv.classify(10.0, 5.0) == cv.WEAKENS and cv.classify(10.0, 4.99) == cv.DROPS
    assert cv.classify(10.0, 0.5) == cv.DROPS and cv.classify(10.0, 0.49) == cv.NO_FURTHER_VALUE
    assert cv.classify(10.0, -1.0) == cv.NO_FURTHER_VALUE and cv.classify(0.0, 3.0) == cv.COULD_NOT_ESTABLISH
    assert set(cv.STATE_LABELS) == {cv.GROWS, cv.HOLDS, cv.WEAKENS, cv.DROPS, cv.NO_FURTHER_VALUE, cv.COULD_NOT_ESTABLISH}


def test_curves_skip_weak_no_signal_resistance_and_low_confidence_targets_without_an_error() -> None:
    weak = [_probe("CAST_SPEED", "Cast Speed", "10% increased Cast Speed", 10.0, offense=0.4),
            _probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", status="NO_SIGNAL")]
    assert cv.curve_targets(_analysis(weak)["build_priorities"]) == []
    assert cv.curve_targets(_analysis(PROBES, confidence="LOW")["build_priorities"]) == [("Energy Shield", "max_hit")]
    targets = cv.curve_targets(_analysis()["build_priorities"])
    assert targets == [("Spell Skill Levels", "offense"), ("Energy Shield", "max_hit"), ("Cast Speed", "offense")]
    assert all("Resistance" not in label for label, _lane in targets)


def test_a_doubled_probe_that_cannot_be_measured_is_not_established_not_a_failure() -> None:
    result = _analysis()
    curves = cv.measure_response_curves(_Probes, ProbeCatalog(), result["global_probes"], result["build_priorities"], run_probe=_second({}))
    assert [c["status"] for c in curves["curves"]] == [cv.COULD_NOT_ESTABLISH] * 3
    assert act.curve_text(curves["curves"][0]) == "Could not establish"


def test_analyze_build_measures_curves_once_and_a_repeat_or_rescore_costs_nothing() -> None:
    from exilelens.analysis.cache import ProbeCache

    engine, cache = FakeEngine({"Ring 2": RING}), ProbeCache()
    first = analyze_build(engine, build_path="b.xml", slot_filter="__none__", cache=cache)
    assert "response_curves" in first and "actionable" in first and first["response_curves"]["budget"] == cv.MAX_CURVES
    assert first["response_curves"]["new_recalcs"] <= cv.MAX_CURVES
    calls = len(engine.evaluations)
    again = analyze_build(engine, build_path="b.xml", slot_filter="__none__", cache=cache)
    assert len(engine.evaluations) == calls and again["response_curves"]["new_recalcs"] == 0
    assert again["response_curves"]["curves"] == [{**c, "reused": True} for c in first["response_curves"]["curves"]] or again["actionable"]["ladders"] == first["actionable"]["ladders"]
    first["slots"] = []
    rescored = rescore_analysis(first, "MAPPING")
    assert len(engine.evaluations) == calls  # rescore never measures
    assert rescored["response_curves"] == first["response_curves"] and rescored["actionable"]["ladders"] == first["actionable"]["ladders"]


# --------------------------------------------------------------------- breakpoints


def test_explicit_breakpoints_state_the_actual_values_and_never_use_curve_language() -> None:
    actionable = _act(needs=[CHAOS_NEED], chaos=42.0)
    chaos = next(b for b in actionable["breakpoints"] if b["key"] == "chaos_res")
    assert (chaos["status"], chaos["current"], chaos["target"], chaos["needed"]) == ("BELOW_CAP", 42.0, 75.0, 33.0)
    assert chaos["text"] == "42% → 75% · 33% needed"
    fire = next(b for b in actionable["breakpoints"] if b["key"] == "fire_res")
    assert fire["status"] == "AT_CAP" and fire["text"] == "At cap — more of it does not improve this measured breakpoint."
    assert "diminish" not in json.dumps(actionable["breakpoints"]).lower()
    resource = next(b for b in actionable["breakpoints"] if b["kind"] == "RESOURCE")
    assert resource["status"] == "AFFORDABLE"


# ---------------------------------------------------------------- plan, focus, best


def test_hard_problems_outrank_optimisation_and_the_plan_is_capped_at_three() -> None:
    actionable = _act(needs=[CHAOS_NEED, FIRE_NEED], fire=58.0, chaos=42.0, strength_short=12.0)
    plan = actionable["action_plan"]
    assert [a["number"] for a in plan] == [1, 2, 3] and all(a["kind"] == "FIX" for a in plan)
    assert [a["title"] for a in plan] == ["Cap Fire Resistance", "Meet your Strength requirement", "Cap Chaos Resistance"]
    assert plan[0]["detail"] == "58% → 75% · 17% needed"
    focus = actionable["current_focus"]
    assert (focus["kind"], focus["title"], focus["headline"]) == (act.FOCUS_ISSUE, "BIGGEST CURRENT ISSUE", "Fire Resistance is below cap.")
    # The largest percentage does not override the breakpoint: it is reported separately.
    assert actionable["best_response"]["tested_change"] == "+1 to Level of all Spell Skills"


def test_one_issue_then_defensive_and_damage_directions_with_their_evidence() -> None:
    plan = _act(needs=[CHAOS_NEED], chaos=42.0)["action_plan"]
    assert [a["title"] for a in plan] == ["Cap Chaos Resistance", "Improve Max Hit", "Improve Damage"]
    assert plan[1]["detail"] == "Energy Shield gives the strongest measured Max Hit response (+50 to maximum Energy Shield → +2.0%)."
    assert plan[2]["detail"] == "Spell Skill Levels gives the strongest measured Damage response (+1 to Level of all Spell Skills → +8.7%)."
    text = json.dumps(plan).lower()
    for guide in ("passive", "unique", "gem", "ascendancy", "buy", "trade", "replace", "weak", "bad", "best build"):
        assert guide not in text


def test_optimisation_only_and_nothing_established_focus() -> None:
    clean = _act()
    assert clean["current_focus"]["kind"] == act.FOCUS_NO_CRITICAL and clean["current_focus"]["headline"] == "No critical issue detected."
    assert clean["current_focus"]["detail"].startswith("Energy Shield gives the strongest measured Max Hit response")
    assert [a["kind"] for a in clean["action_plan"]] == ["IMPROVE", "IMPROVE"]
    nothing = _act([_probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", status="REJECTED")])
    assert nothing["current_focus"]["kind"] == act.FOCUS_NOT_ESTABLISHED and nothing["action_plan"] == []
    assert "weak" not in json.dumps(clean["current_focus"]).lower()


def test_mana_pool_smaller_than_one_use_is_a_hard_action() -> None:
    actionable = _act(pool=30.0, cost=90.0)
    assert actionable["action_plan"][0]["title"] == "Make one use of your main skill affordable"
    assert actionable["action_plan"][0]["detail"] == "30 unreserved → 90 per use · 60 needed"
    assert next(r for r in actionable["build_health"] if r["key"] == "resources")["state"] == act.NEEDS_ATTENTION


# ------------------------------------------------------------------------ packages


def test_packages_show_component_evidence_and_never_a_summed_percentage() -> None:
    packages = {p["key"]: p for p in _act()["stat_packages"]}
    assert [s["label"] for s in packages["offense"]["stats"]] == ["Spell Skill Levels", "Cast Speed"]
    assert packages["offense"]["stats"][0]["evidence"] == "Damage +8.7%"
    assert [(s["label"], s["evidence"]) for s in packages["defence"]["stats"]] == [("Energy Shield", "Max Hit +2.0% · EHP +3.1%"), ("Life", "EHP +2.4%")]
    assert packages["hybrid"]["stats"] == [{"label": "Intelligence", "tested_change": "+20 to Intelligence", "evidence": "Damage +2.1% · ES +4.3% · Mana +3.0%"}]
    text = json.dumps(list(packages.values()))
    assert "+14.8" not in text and "total" not in text.lower() and "combined" not in text.lower()  # 8.7 + 6.1 is never claimed
    assert all("total" not in p and "percent" not in p for p in packages.values())


# -------------------------------------------------------------------------- health


def test_health_states_come_from_evidence_never_from_sensitivity_size() -> None:
    health = {r["key"]: r for r in _act(needs=[CHAOS_NEED], chaos=42.0)["build_health"]}
    assert (health["resistances"]["state"], health["resistances"]["reason"]) == (act.NEEDS_ATTENTION, "Chaos Resistance below cap.")
    assert health["max_hit"]["state"] == act.OPPORTUNITY and health["damage"]["state"] == act.OPPORTUNITY  # both are next actions
    assert health["ehp"]["state"] == act.NO_URGENT_ISSUE and health["movement"]["state"] == act.NO_URGENT_ISSUE
    assert health["resources"]["state"] == act.NO_URGENT_ISSUE
    # With three hard problems the plan has no room for an optimisation, so no axis is called an opportunity.
    busy = {r["key"]: r for r in _act(needs=[CHAOS_NEED, FIRE_NEED], fire=58.0, chaos=42.0, strength_short=12.0)["build_health"]}
    assert busy["damage"]["state"] == act.NO_URGENT_ISSUE and busy["requirements"]["state"] == act.NEEDS_ATTENTION
    only_life = {r["key"]: r for r in _act([_probe("LIFE", "Life", "+50 to maximum Life", 50.0, family="defense", ehp=2.4)])["build_health"]}
    assert only_life["damage"]["state"] == act.LIMITED and only_life["movement"]["state"] == act.LIMITED
    text = json.dumps(_act()["build_health"]).lower()
    assert "score" not in text and "strong build" not in text and "weak" not in text
    assert set(act.HEALTH_LABELS.values()) == {"Needs attention", "Opportunity", "No urgent issue detected", "Limited analysis"}


# ------------------------------------------------------------------------ coverage


def test_coverage_levels_and_that_it_is_not_measurement_confidence() -> None:
    high = _act([p for p in PROBES if p["status"] in {"ok", "NO_SIGNAL"}])["coverage"]
    assert (high["level"], high["label"], high["summary"]) == (act.COVERAGE_HIGH, "High", "8 / 8 relevant measurements established.")
    partial = _act(PROBES)["coverage"]  # one of nine tests unsupported: 8/9 = 0.89
    assert partial["level"] == act.COVERAGE_PARTIAL and partial["summary"] == "8 / 9 relevant measurements established."
    assert "1 test could not be applied to this build's items." in partial["notes"]
    rejected = [_probe(f"P{i}", f"S{i}", f"+{i} s", 1.0, status="REJECTED") for i in range(3)] + [PROBES[0]]
    assert _act(rejected)["coverage"]["level"] == act.COVERAGE_LIMITED
    assert _act([])["coverage"]["level"] == act.COVERAGE_LIMITED
    low_damage = _act([p for p in PROBES if p["status"] == "ok"], confidence="LOW")["coverage"]
    assert low_damage["level"] == act.COVERAGE_PARTIAL and "Damage could not be established reliably" in " ".join(low_damage["notes"])
    weapon = _act([p for p in PROBES if p["status"] == "ok"], slots=[{"analysis_limited": True}])["coverage"]
    assert weapon["level"] == act.COVERAGE_HIGH and "Weapon optimization remains limited." in weapon["notes"]  # a slot limit is not a build limit
    assert "confidence" not in json.dumps(high).lower()


# -------------------------------------------------------------------- what changed


def _next_state(**kwargs):
    return _act(baseline={"fingerprint": "hash2", "generation": 3}, **kwargs)


def test_resolved_issue_and_new_issue_are_reported_semantically() -> None:
    before = _act(needs=[CHAOS_NEED], chaos=42.0)
    after = _next_state()
    changes = diff_actionable(before, after)
    assert changes["comparable"] is True
    kinds = [item["kind"] for item in changes["items"]]
    assert kinds[0] == "RESOLVED" and changes["items"][0]["text"] == "✓ Chaos Resistance is no longer a priority."
    assert "FOCUS" in kinds and "UNCHANGED" in kinds
    assert changes["items"][-1]["text"] == "↔ Spell Skill Levels remains your strongest Damage response."
    added = diff_actionable(_act(), _next_state(needs=[FIRE_NEED], fire=58.0))
    assert added["items"][0]["kind"] == "ADDED" and "Fire Resistance is now a priority" in added["items"][0]["text"]


def test_top_response_change_rank_move_and_new_multi_impact() -> None:
    before = _act()
    boosted = [{**p, "metric_profile": {**p["metric_profile"], "primary_offense": {"availability": "available", "absolute_delta": 12.0, "percent_delta": 12.0}}}
               if p["probe_id"] == "SPELL_DAMAGE" else p for p in PROBES]
    strength = _probe("STRENGTH", "Strength", "+20 to Strength", 20.0, family="utility", offense=1.5, life=2.0)
    after = _next_state(probes=[*boosted, strength])
    texts = [item["text"] for item in diff_actionable(before, after)["items"]]
    assert "→ Spell Damage is now your strongest Damage response (was Spell Skill Levels)." in texts
    assert "↑ Spell Damage moved" not in " ".join(texts)  # the top change already says it
    assert "NEW: Strength is now a multi-impact response." in texts
    dropped = [{**p, "metric_profile": {**p["metric_profile"], "primary_offense": {"availability": "available", "absolute_delta": 1.2, "percent_delta": 1.2}}}
               if p["probe_id"] == "CAST_SPEED" else p for p in PROBES]
    moved = [item["text"] for item in diff_actionable(before, _next_state(probes=dropped))["items"]]
    assert "↓ Cast Speed moved from #2 to #4 for Damage." in moved


def test_noise_is_suppressed_and_the_same_state_reports_nothing() -> None:
    before = _act()
    nudged = [{**p, "metric_profile": {**p["metric_profile"], "primary_offense": {"availability": "available", "absolute_delta": 8.9, "percent_delta": 8.9}}}
              if p["probe_id"] == "SPELL_SKILL_LEVELS" else p for p in PROBES]
    assert diff_actionable(before, _next_state(probes=nudged)) == {"comparable": True, "items": []}  # +8.7% -> +8.9% is not news
    assert diff_actionable(before, _act()) == {"comparable": True, "items": []}  # same PoB state analysed twice
    grown = [{**p, "metric_profile": {**p["metric_profile"], "primary_offense": {"availability": "available", "absolute_delta": 12.0, "percent_delta": 12.0}}}
             if p["probe_id"] == "SPELL_SKILL_LEVELS" else p for p in PROBES]
    assert [i["text"] for i in diff_actionable(before, _next_state(probes=grown))["items"]] == ["↑ Spell Skill Levels: Damage response +8.7% → +12.0%."]
    assert len(diff_actionable(_act(needs=[CHAOS_NEED, FIRE_NEED], fire=58.0, chaos=42.0, strength_short=12.0), _next_state())["items"]) <= act.MAX_CHANGES


def test_incompatible_analyses_start_a_new_baseline_instead_of_a_misleading_diff() -> None:
    before = _act(needs=[CHAOS_NEED], chaos=42.0)
    for change in ({"build_path": "other.xml"}, {"loadout": "Boss"}, {"context": "BOSS"}):
        other = _act(baseline={"fingerprint": "hash2", "generation": 3, **change})
        assert diff_actionable(before, other) == {"comparable": False, "items": []}
    assert diff_actionable(None, before) == {"comparable": False, "items": []}
    gear_edit = _act(baseline={"fingerprint": "hash2", "generation": 3, "item_set": "2", "build_path": ".\\B.XML"})
    assert diff_actionable(before, gear_edit)["comparable"] is True  # same build, different gear: worth comparing
    assert act.comparable(before, gear_edit) and not act.comparable(before, {})


# -------------------------------------------------------------------- derived layer


def test_actionable_is_pure_profile_independent_and_leaves_m5_and_r1_outputs_untouched() -> None:
    result = _analysis(needs=[CHAOS_NEED], chaos=42.0)
    before = copy.deepcopy({k: v for k, v in result.items() if k != "actionable"})
    assert build_actionable(result) == result["actionable"]
    assert {k: v for k, v in result.items() if k != "actionable"} == before
    flipped = [{**p, "score_delta": 100.0 - i} if p["status"] == "ok" else p for i, p in enumerate(PROBES)]
    assert _act(flipped, needs=[CHAOS_NEED], chaos=42.0, baseline={"profile": "MAPPING"}) == result["actionable"]
    assert build_actionable({"slots": []}) == {}
    assert result["actionable"]["identity"] == {k if k != "fingerprint" else "baseline_fingerprint": v for k, v in BASELINE.items() if k != "profile"}
