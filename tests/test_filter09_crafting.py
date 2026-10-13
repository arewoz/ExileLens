"""FILTER-09: crafting bases and opportunity intelligence.

Run with:  python -m pytest tests/test_filter09_crafting.py -m ""
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from exilelens.filters import benchmark08b as bm
from exilelens.filters import crafting_intel as ci
from exilelens.filters import fuzz_harness as fh
from exilelens.filters import legal_corpus as lc
from exilelens.filters import natural_gameplay as ng
from exilelens.filters import opportunity_benchmark as ob
from exilelens.filters import opportunity_lanes as lanes
from exilelens.filters import rule_ir
from exilelens.filters.inspector import inspect as inspect_item, make_item, render
from exilelens.filters.intel_generate import generate
from exilelens.filters.opportunity import BuildOpportunityModel
from exilelens.filters.preview import preview_decision
from exilelens.filters.validation import validate_base_types
from exilelens.filters.verified_bases import load_base_properties, native_class

ROOT = Path(__file__).resolve().parents[1]
NEEDS = ROOT / "tests" / "fixtures" / "filter_needs" / "filter08e"
PROFILES = ("Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict")


@pytest.fixture(scope="module")
def snaps():
    if not NEEDS.exists():
        pytest.skip("canonical needs snapshots not present")
    return bm.load_snapshots(NEEDS)


@pytest.fixture(scope="module")
def blood(snaps):
    return snaps["spark_fixture"]


@pytest.fixture(scope="module")
def generated(blood):
    return {p: generate(blood, p, intel=True) for p in PROFILES}


# -- natural gameplay: the Utility Belt ----------------------------------------------------------------------------------------------------
def test_natural_corpus_is_labelled_and_complete():
    entries = ng.load()
    assert entries and all(e["label"] == "NATURAL GAMEPLAY EVIDENCE" for e in entries)
    belt = next(e for e in entries if e["item"]["base"] == "Utility Belt")
    assert belt["expected_user_assessment"] == "SHOULD SHOW"
    assert belt["matched_rule_before"] == "HideLowQualityNormals"       # the observation, as recorded in the game (FILTER-09)


def test_utility_belt_regression_per_profile_and_lane(blood):
    entry = next(e for e in ng.load() if e["item"]["base"] == "Utility Belt")
    expected = entry["profile_system_v2"]["per_profile"]           # the approved matrix, not the FILTER-09 per-profile policy
    for r in ng.replay(entry, blood):
        want = expected[r.profile][r.rarity] != "HIDE"
        assert r.after_visible == want, (r.profile, r.rarity, r.after_rule)
        if r.profile != "Relaxed":
            # without the CRAFT lane the belt falls to the generic jewellery rows: hidden from Recommended on
            assert not r.before_visible and r.before_rule.startswith("Generic_Jewellery_Low"), (r.profile, r.rarity, r.before_rule)
        if want:
            assert r.after_rule.startswith("Craft_RELEVANT_") and r.lane_cause == "CRAFT", (r.profile, r.rarity, r.after_rule)
        # the reason is always spelled out through independent lanes, never one scalar
        assert set(r.lane_levels) >= {"BUILD", "CRAFT", "TRADE"}
        assert r.lane_levels["CRAFT"] == "CRAFT_RELEVANT" and r.lane_levels["TRADE"] == "TRADE_POTENTIAL"


def test_no_base_is_hardcoded_in_the_lane_logic():
    """No string literal naming a belt (or any catalog base) may appear in the lane logic; prose in a docstring is fine."""
    import ast
    from exilelens.filters import rules
    catalog = set(load_base_properties())
    for module in (ci, lanes, rules):
        tree = ast.parse(inspect.getsource(module))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
                      and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings}
        classes = {r["class"] for r in load_base_properties().values()}      # 'Ring' is both a PoB class and a base name
        hardcoded = sorted(l for l in literals if l in catalog and l not in classes)
        assert not hardcoded, (module.__name__, hardcoded[:5])


def test_utility_belt_decision_is_policy_not_a_special_case(blood):
    """A rarity/item-level the policy does not list must stay hidden: the belt is shown by the lane's gate, not 'always'."""
    low = make_item("Utility Belt", rarity="Normal", item_level=60)
    for profile in ("Recommended", "Strict", "Very Strict", "Uber Strict"):
        assert preview_decision(generate(blood, profile, intel=True).rules, low).hidden
    rare = make_item("Utility Belt", rarity="Rare", item_level=82)
    assert not preview_decision(generate(blood, "Recommended", intel=True).rules, rare).hidden


# -- crafting intelligence --------------------------------------------------------------------------------------------------------------
def test_assessment_is_build_independent_and_deterministic():
    a, b = ci.assess("Utility Belt"), ci.assess("Utility Belt")
    assert a is b and a.level == ci.CraftLevel.RELEVANT
    assert a.breakpoints == {"meaningful": 50, "high": 70, "premium": 81}
    assert a.confidence == "VERIFIED"


def test_special_mechanic_bases_are_unknown_not_guessed():
    specials = [b for b in load_base_properties() if b.startswith(ci.SPECIAL_PREFIXES)]
    assert specials
    assert all(ci.assess(b).level == ci.CraftLevel.UNKNOWN for b in specials)
    assert all(ci.gate_for(ci.assess(b), "Relaxed") is None for b in specials)


def test_gates_are_on_the_ladder_and_never_below_required_level():
    for base in load_base_properties():
        a = ci.assess(base)
        for widened in (False, True):
            gate = ci.breakpoint_gate(a, widened=widened)
            if gate is not None:
                assert gate >= max(1, a.required_level)
                assert gate in ci.LADDER or gate == a.required_level
        for profile in PROFILES:
            placed = ci.gate_for(a, profile)
            if placed:
                assert placed[0] == ci.breakpoint_gate(a)


def test_profile_craft_policy_is_nested():
    """Every base a stricter profile shows (Relaxed > Recommended > Strict > Very Strict) is shown by the looser one at an item level
    no higher, for no narrower rarity set."""
    chain = ("Relaxed", "Recommended", "Strict", "Very Strict")
    for base in load_base_properties():
        a = ci.assess(base)
        for looser, stricter in zip(chain, chain[1:]):
            s = ci.gate_for(a, stricter)
            if s is None:
                continue
            l = ci.gate_for(a, looser)
            assert l is not None and l[0] <= s[0] and set(l[1]) >= set(s[1]), (base, looser, stricter)


# -- generator integration -------------------------------------------------------------------------------------------------------------
def test_craft_rules_are_exact_match_valid_and_above_the_generic_hides(generated):
    for profile, result in generated.items():
        assert result.valid, (profile, result.errors[:2])
        craft = [r for r in result.rules if r.category == "CRAFT_OPPORTUNITY"]
        assert craft, profile
        # profile system V2: rules are ordered by state (most visible first), so a visible craft rule can never sit below a Hide rule
        order = {id(r): i for i, r in enumerate(result.rules)}
        first_hide = min((order[id(r)] for r in result.rules if r.state == "HIDE"), default=len(result.rules))
        assert all(order[id(r)] < first_hide for r in craft if r.state not in ("HIDE",)), profile
        for rule in craft:
            assert any(line.strip().startswith("BaseType ==") for line in rule.lines)
            assert any(line.strip().startswith("Rarity") for line in rule.lines)
        assert validate_base_types(result.text).passed


def test_exact_match_keeps_special_variants_out_of_the_craft_rules(generated):
    shown = {b for r in generated["Relaxed"].rules if r.category == "CRAFT_OPPORTUNITY"
             and r.name.startswith(("Craft_PREMIUM", "Craft_RELEVANT")) for b in r.base_types}
    assert shown and not any(b.startswith(ci.SPECIAL_PREFIXES) for b in shown)
    plain = next(b for b in shown if native_class(b) == "Body Armours")
    variant = next((f"{p}{plain}" for p in ci.SPECIAL_PREFIXES if f"{p}{plain}" in load_base_properties()), None)
    if variant:
        item = make_item(variant, rarity="Normal", item_level=82)
        decision = preview_decision(generated["Relaxed"].rules, item)
        assert not decision.rule_name.startswith(("Craft_PREMIUM", "Craft_RELEVANT"))     # a special variant is UNKNOWN, never a substrate


def test_no_quality_gate_remains_for_classes_that_cannot_carry_quality(generated):
    for profile, result in generated.items():
        for rule in result.rules:
            if any("Quality >=" in line for line in rule.lines) and rule.base_types:
                dead = [b for b in rule.base_types if not ci.assess(b).quality_capable and ci.assess(b).native_class]
                assert not dead, (profile, rule.name, dead[:3])


def test_lane_reference_matches_generated_rules(blood):
    """decide() is the reference attribution; the generated filter realises it for the CRAFT lane (quality-0 items)."""
    model = BuildOpportunityModel(blood)
    bases = [b for b in load_base_properties() if native_class(b)]
    checked = 0
    for profile in ("Recommended", "Strict", "Uber Strict"):
        rules = generate(blood, profile, intel=True).rules
        by_name = {r.name: r for r in rules}
        for base in bases[::5]:
            for rarity, ilvl in (("Normal", 82), ("Magic", 70), ("Normal", 56), ("Rare", 82)):
                item = make_item(base, rarity=rarity, item_level=ilvl)
                actual = preview_decision(rules, item)
                rule = by_name.get(actual.rule_name)
                category = rule.category if rule else ""
                reference = lanes.decide(item, profile, model=model, build_shown=category.startswith("BUILD") and not actual.hidden)
                checked += 1
                craft_rule = category == "CRAFT_OPPORTUNITY" and actual.rule_name.startswith(("Craft_PREMIUM", "Craft_RELEVANT"))
                if reference.cause == lanes.Lane.CRAFT:
                    assert not actual.hidden, (profile, base, rarity, ilvl, actual.rule_name)     # a more visible row may style it
                if craft_rule and not actual.hidden:
                    assert reference.cause == lanes.Lane.CRAFT, (profile, base, rarity, ilvl)
                if category.startswith("BUILD"):
                    assert reference.cause == lanes.Lane.BUILD
                if reference.cause is None and rarity in ("Normal", "Magic") and reference.verdict(lanes.Lane.PROTECTED) is None:
                    assert not craft_rule and not category.startswith("BUILD"), (profile, base, rarity, ilvl, category)
    assert checked > 1000


def test_theme_and_build_do_not_change_the_craft_lane(snaps):
    reference = None
    for name, needs in list(snaps.items())[:4]:
        for theme in ("Void Gold", "Blood Sigil", "Wraeclast Ashes"):
            result = generate(needs, "Recommended", theme, intel=True)
            sig = sorted((r.name, tuple(r.base_types)) for r in result.rules if r.category == "CRAFT_OPPORTUNITY")
            reference = reference or sig
            assert sig == reference, (name, theme)


def test_missing_evidence_never_hides_a_craft_base(snaps):
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    unavailable = BuildNeedsSnapshot.unavailable("none", "no measurement")
    item = make_item("Utility Belt", rarity="Normal", item_level=82)
    for needs in (unavailable, snaps["spark_fixture"]):
        assert not preview_decision(generate(needs, "Recommended", intel=True).rules, item).hidden
    assert not preview_decision(generate(unavailable, "Recommended", intel=False).rules, item).hidden


def test_drift_widens_the_craft_lane_one_step(blood):
    from exilelens.filters.data_drift import DataState, DataStatus
    stale = DataStatus(DataState.STALE_SNAPSHOT, ("test",))
    normal = generate(blood, "Recommended", intel=True)
    widened = generate(blood, "Recommended", intel=True, data_status=stale)
    item = make_item("Utility Belt", rarity="Normal", item_level=55)       # between the 'meaningful' (50) and 'high' (70) breakpoints
    assert preview_decision(normal.rules, item).hidden
    assert not preview_decision(widened.rules, item).hidden


def test_optimiser_keeps_craft_lane_provenance(generated):
    for profile in ("Recommended", "Uber Strict"):
        rules = generated[profile].rules
        optimised, report = rule_ir.optimise(rules)
        before = {b for r in rules if r.category == "CRAFT_OPPORTUNITY" for b in r.base_types}
        after = {b for r in optimised if r.category == "CRAFT_OPPORTUNITY" for b in r.base_types}
        assert after <= before                        # the optimiser invents no craft base; one may leave a rule an earlier rule already covers
        assert all(r.class_reasons for r in optimised if r.category == "CRAFT_OPPORTUNITY")


def test_rule_ir_finds_no_defect_in_the_craft_lane(generated):
    for profile, result in generated.items():
        report = rule_ir.analyse(result.rules)
        bad = [f for f in report.defects() if f.rule.startswith("Craft_")]
        assert not bad, (profile, bad[:2])


# -- benchmark (author-annotated; see opportunity_benchmark.py for the honest label) -----------------------------------------------------
def test_benchmark_is_labelled_and_independent_of_the_lane_code():
    import ast
    imported = {n.module for n in ast.walk(ast.parse(inspect.getsource(ob))) if isinstance(n, ast.ImportFrom) and n.module}
    assert not [m for m in imported if m.endswith(("crafting_intel", "opportunity_lanes", "rules", "profiles"))], imported
    assert {c.source for c in ob.cases()} >= {"AUTHOR DOMAIN JUDGEMENT", "STRUCTURAL", "NATURAL GAMEPLAY"}
    assert {c.expectation for c in ob.cases()} == {ob.SHOULD_SHOW, ob.MAY_HIDE, ob.SHOULD_HIDE}


def test_generic_opportunity_miss_and_craft_clutter_per_profile(generated):
    measured = {}
    for profile, result in generated.items():
        without = [r for r in result.rules if r.category != "CRAFT_OPPORTUNITY"]
        before, after = ob.evaluate(without), ob.evaluate(result.rules)
        measured[profile] = (before, after)
        # the lane adds recall and never adds a SHOULD_HIDE base to the visible set
        assert after["generic_opportunity_miss"] <= before["generic_opportunity_miss"], profile
        assert after["clutter_rate"] <= before["clutter_rate"] + 1e-9, profile
    assert measured["Relaxed"][1]["generic_opportunity_miss"] == 0
    assert measured["Recommended"][1]["generic_opportunity_miss"] <= 0.05
    assert measured["Strict"][1]["generic_opportunity_miss"] <= 0.20
    # authored jewellery / belt judgements (the part that is NOT derived from drop level) are all shown by Recommended
    author = measured["Recommended"][1]["by_source"]["AUTHOR DOMAIN JUDGEMENT"]["SHOULD_SHOW"]
    assert author["visible"] == author["total"]
    # profile aggression is ordered: looser profiles never show fewer SHOULD_SHOW bases
    recall = [measured[p][1]["craft_recall"] for p in ("Relaxed", "Recommended", "Strict", "Very Strict")]
    assert recall == sorted(recall, reverse=True)


# -- fuzz invariants N / Q / R -----------------------------------------------------------------------------------------------------------
def test_fuzz_craft_invariants_hold_on_real_degraded_and_random_variants(snaps):
    cases = lc.sample(1500, seed=9)
    report, _, _ = fh.run(snaps, cases, seed=9, per_base=1, invariants=("N", "Q", "R"), variant_limit=14, sweep_items=1500)
    assert report.violations == [], report.violations[:3]
    assert {"N", "Q", "R"} <= set(report.invariants)


def test_invariant_n_can_fail(blood):
    """An invariant that cannot fail proves nothing: hide a PREMIUM substrate and N must object."""
    cases = [c for c in lc.sample(4000, seed=3)
             if c.item.rarity == "Normal" and c.item.base_type and ci.assess(c.item.base_type).level == ci.CraftLevel.PREMIUM
             and c.item.item_level >= 82 and not c.item.corrupted and not c.item.mirrored][:3]
    assert cases
    variant = fh.Variant("synthetic", blood, "real")
    ev = fh.Evaluator([c.item for c in cases])
    key = (ev.key(blood), "Recommended", True, "Void Gold", fh.CURRENT.state)
    ev._hidden[key] = tuple(True for _ in cases)
    assert fh.check_N(ev, variant, cases, profiles=("Recommended",))


# -- inspector --------------------------------------------------------------------------------------------------------------------------
def test_inspector_reports_every_lane_and_the_decision(blood):
    inspection = inspect_item(blood, make_item("Utility Belt", rarity="Normal", item_level=82))
    by_profile = {v.profile: v for v in inspection.verdicts}
    for verdict in by_profile.values():
        assert {row["lane"] for row in verdict.lanes} == {"BUILD", "CRAFT", "TRADE", "PROTECTED", "FALLBACK"}
        assert verdict.lane_decision
    assert by_profile["Recommended"].visible and by_profile["Recommended"].category == "CRAFT_OPPORTUNITY"
    assert "cause CRAFT" in by_profile["Recommended"].lane_decision
    assert not by_profile["Uber Strict"].visible and by_profile["Very Strict"].visible          # QUIET at Very Strict, HIDE at Uber Strict
    text = render(inspection)
    assert "LANE CRAFT" in text and "LANE DECISION" in text


def test_trade_premium_requires_market_evidence():
    class Signal:
        level, source, observed_at = "LIVE", "unit-test", "2026-01-01T00:00:00+00:00"
    heuristic = lanes.trade_lane("Utility Belt")
    assert heuristic.level == lanes.Opportunity.TRADE_POTENTIAL and heuristic.confidence == "HEURISTIC"
    assert lanes.trade_lane("Utility Belt", Signal()).level == lanes.Opportunity.TRADE_PREMIUM
    unknown = lanes.trade_lane("Not A Real Base")
    assert unknown.level == lanes.Opportunity.UNKNOWN


def test_protected_lane_wins_over_everything():
    from exilelens.filters.preview import PreviewItem
    item = PreviewItem("Exalted Orb", "Currency", "Stackable Currency")
    decision = lanes.decide(item, "Very Strict")
    assert decision.visible and decision.cause == lanes.Lane.PROTECTED


# -- patch resilience ----------------------------------------------------------------------------------------------------------------------
def test_snapshot_diff_exposes_craft_relevant_changes():
    from exilelens.filters import snapshot_tools as st
    from exilelens.filters.verified_bases import load_pob_base_properties
    props = load_pob_base_properties()           # the snapshot diff compares the whole PoB2 universe, not the ground-valid subset
    new = {"poe2_base_properties.json": {"bases": {k: dict(v) for k, v in props.items()}},
           "poe2_affix_pools.json": {"base_pool": {}, "pools": {}}, "poe2_skill_facts.json": {"skills": {}}}
    old_dir = Path(st.DATA_DIR)
    assert not st.breaking(st.diff(new, old_dir))
    new["poe2_base_properties.json"]["bases"]["Utility Belt"]["implicit"] = "(5-10)% increased Rarity of Items found"
    report = st.diff(new, old_dir)
    assert any(c["base"] == "Utility Belt" for c in report["CRAFT SUBSTRATE CHANGED"])
    assert st.breaking(report)
