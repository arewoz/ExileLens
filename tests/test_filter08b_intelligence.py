"""FILTER-08B: build-aware loot intelligence. Offline; runs from stored Build Intelligence measurements.

Run with:  python -m pytest tests/test_filter08b_intelligence.py -m ""   (FILTER tests are outside the default marker selection)
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from exilelens.filters import affix_pools, benchmark08b as bm, benchmark08b_fn as fn, skill_facts
from exilelens.filters.benchmark_corpus import LOOT_CASES
from exilelens.filters.build_needs import BuildNeedsSnapshot, Coverage, NeedSignal, Relevance
from exilelens.filters.intel_fixtures import synthetic_analysis
from exilelens.filters.intel_generate import generate
from exilelens.filters.opportunity import BuildOpportunityModel, EvidenceKind
from exilelens.filters.preview import PreviewItem, preview_decision
from exilelens.filters.profile_oracle import matrix_hides
from exilelens.filters.priorities import SLOT_EQUIPMENT_CLASSES
from exilelens.filters.profiles import FilterProfileName, FilterThemeName, ProductSlot

NEEDS_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "filter_needs" / "filter08b"
# FILTER-08D: narrowing needs COMPLETE evidence (the standard probe set incl. ARMOUR/EVASION). The original 08B measurements predate those
# probes, so they are incomplete and only widen; the 08B behaviour contract is exercised on the standard-complete 08C measurements.
COMPLETE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "filter_needs" / "filter08c"
SPARK = "spark_fixture"
BOW = "core04_bow_quiver"
MELEE = "core04_melee_weapon"


@pytest.fixture(scope="module")
def snapshots() -> dict[str, BuildNeedsSnapshot]:
    loaded = bm.load_snapshots(COMPLETE_DIR)
    assert SPARK in loaded and BOW in loaded and MELEE in loaded, "stored measurements are part of the checkpoint"
    return loaded


# --- the production adapter ---------------------------------------------------------------------------------------------------
def test_adapter_projects_production_priorities_without_a_universal_score():
    needs = BuildNeedsSnapshot.from_analysis(synthetic_analysis(), label="synthetic")
    by = {s.probe_id: s for s in needs.signals}
    assert by["SPELL_SKILL_LEVELS"].relevance == Relevance.STRONG.value and "offense" in by["SPELL_SKILL_LEVELS"].lanes
    # a lane with a single candidate orders nothing: measured and responsive, never STRONG
    assert by["MOVEMENT_SPEED"].relevance == Relevance.RESPONSIVE.value
    assert by["ATTACK_SPEED"].relevance == Relevance.NO_RESPONSE.value
    # unlike interventions keep their own increment and axis; nothing is summed or normalised
    assert by["SPELL_SKILL_LEVELS"].tested_change == "+1 to Level of all Spell Skills"
    assert by["ENERGY_SHIELD"].tested_change == "+50 to maximum Energy Shield"
    assert "score" not in needs.to_json().lower().replace("score_delta", "")
    assert needs.skill.mode == "SPELL" and needs.skill.elements == ("Lightning",)
    assert BuildNeedsSnapshot.from_json(needs.to_json()) == needs


def test_synthetic_spark_fixture_exercises_incomplete_measurement_fallback():
    needs = bm.load_snapshots(NEEDS_DIR)[SPARK]
    assert needs.skill.name == "Spark" and needs.skill.mode == "SPELL"
    assert needs.coverage == Coverage.PARTIAL
    assert any("defence direction not measured" in reason for reason in needs.coverage_reasons)
    assert needs.signal("ATTACK_SPEED").relevance == Relevance.NO_RESPONSE.value


# --- verified itemization data -----------------------------------------------------------------------------------------------------
def test_affix_pools_distinguish_bases_by_verified_tags():
    assert affix_pools.eligible_pool("Voltaic Staff", "SPELL_SKILL_LEVELS@Lightning", 82)
    assert affix_pools.eligible_pool("Ashen Staff", "SPELL_SKILL_LEVELS@Lightning", 82) is None
    assert affix_pools.eligible_pool("Ashen Staff", "SPELL_SKILL_LEVELS@Fire", 82)
    pool = affix_pools.eligible_pool("Voltaic Staff", "SPELL_SKILL_LEVELS", 82)
    assert pool and pool.first_level <= 10 and pool.top_level >= 75 and pool.tiers_at(40) < pool.tiers_at(82)
    assert affix_pools.snapshot_info()["pob_commit"]


def test_skill_facts_replace_curated_guesses_with_verified_weapon_requirements():
    assert skill_facts.lookup(name="Ice Shot").weapon_classes == ("Bows",)
    assert set(skill_facts.lookup(name="Sunder").weapon_classes) == {"One Hand Maces", "Two Hand Maces"}
    assert skill_facts.lookup(name="Spark").weapon_classes is None and skill_facts.lookup(name="Spark").is_spell
    assert skill_facts.lookup(name="Split Arrow") is None  # a PoE1 name the curated map still carries


def test_pools_agree_with_production_slot_compat():
    """The base-level pools extend (never contradict) the production slot-level compatibility table."""
    pob = Path(os.environ.get("POB2_PATH") or ".run/absent-pob")
    if not (pob / "src" / "Data" / "ModItem.lua").exists():
        pytest.skip("PoB2 checkout not available")
    from exilelens.analysis.slot_compat import load_slot_compat
    table = load_slot_compat(str(pob))
    classes = {"RING_1": "Ring", "AMULET": "Amulet", "BELT": "Belt", "HELMET": "Helmet", "BODY_ARMOUR": "Body Armour",
               "GLOVES": "Gloves", "BOOTS": "Boots"}
    for probe_id in ("LIFE", "ENERGY_SHIELD", "FIRE_RES", "CHAOS_RES", "MOVEMENT_SPEED", "SPELL_SKILL_LEVELS", "CAST_SPEED"):
        families = [f for f, d in affix_pools.family_definitions().items() if d["probe_id"] == probe_id and d["relation"] == "DIRECT"]
        for slot in table[probe_id]["slots"]:
            if slot in classes:
                assert set(families) & affix_pools.class_families(classes[slot]), (probe_id, slot)


# --- decision table -------------------------------------------------------------------------------------------------------------------
def test_measured_promotion_is_base_specific_and_explained(snapshots):
    model = BuildOpportunityModel(snapshots[SPARK])
    voltaic, ashen = model.decide("Voltaic Staff", "Staves"), model.decide("Ashen Staff", "Staves")
    assert voltaic.shift == 1 and voltaic.relevance == Relevance.STRONG
    assert ashen.shift == 0  # cannot roll Lightning spell levels, so no base-specific advantage
    kinds = {r.kind for r in voltaic.reasons}
    assert EvidenceKind.MEASURED_BUILD_RESPONSE in kinds and EvidenceKind.AFFIX_POOL_OPPORTUNITY in kinds
    amethyst = model.decide("Amethyst Ring", "Rings")  # verified chaos-res implicit; chaos cap is a Fix First deficit
    assert amethyst.shift == 1 and any(h.source == "IMPLICIT" for h in amethyst.hits)
    coat = model.decide("Corsair Coat", "Body Armours")  # movement-speed implicit: responsive, not a ranked priority
    assert coat.shift == 0


def test_demotion_needs_confident_measured_no_response_and_never_follows_low_offense_confidence(snapshots):
    needs = snapshots[BOW]
    model = BuildOpportunityModel(needs)
    # ES responds strongly for this build's EHP lane; an armour base with no ES carries no ES evidence either way
    plate = model.decide(next(b for b, r in __import__("exilelens.filters.verified_bases", fromlist=["x"]).load_base_properties().items()
                              if r["class"] == "Body Armour" and r["armour"] and not r["energy_shield"] and not r["evasion"]), "Body Armours")
    assert plate.shift >= 0  # absence of evidence never demotes
    # a measured NO_RESPONSE on a probe with LOW confidence must not demote
    weak = replace(needs, signals=tuple(
        replace(s, relevance=Relevance.NO_RESPONSE.value, confidence="LOW") if s.probe_id == "ENERGY_SHIELD" else s
        for s in needs.signals))
    weak_model = BuildOpportunityModel(weak)
    robe = weak_model.decide(next(b for b, r in __import__("exilelens.filters.verified_bases", fromlist=["x"]).load_base_properties().items()
                                  if r["class"] == "Body Armour" and r["energy_shield"] and not r["armour"] and not r["evasion"]), "Body Armours")
    assert robe.shift >= 0
    confident = replace(needs, signals=tuple(
        replace(s, relevance=Relevance.NO_RESPONSE.value, confidence="HIGH") if s.probe_id == "ENERGY_SHIELD" else s
        for s in needs.signals))
    pure_es = next(b for b, r in __import__("exilelens.filters.verified_bases", fromlist=["x"]).load_base_properties().items()
                   if r["class"] == "Body Armour" and r["energy_shield"] and not r["armour"] and not r["evasion"])
    assert BuildOpportunityModel(confident).decide(pure_es, "Body Armours").shift == -1


def test_weapon_classes_follow_the_evidence_precedence(snapshots):
    supported = SLOT_EQUIPMENT_CLASSES[ProductSlot.WEAPON_1]
    bow_classes, bow_reasons, bow_cov = BuildOpportunityModel(snapshots[BOW]).weapon_classes(supported)
    assert bow_classes[0] == "Bows" and bow_reasons[0].kind == EvidenceKind.VERIFIED_BASE_FACT and bow_cov == Coverage.MEASURED
    mace_classes, _, _ = BuildOpportunityModel(snapshots[MELEE]).weapon_classes(supported)
    assert {"One Hand Maces", "Two Hand Maces"} <= set(mace_classes) and "Bows" not in mace_classes
    spell_classes, spell_reasons, _ = BuildOpportunityModel(snapshots[SPARK]).weapon_classes(supported)
    assert {"Wands", "Staves"} <= set(spell_classes)
    assert spell_reasons[0].kind == EvidenceKind.MEASURED_BUILD_RESPONSE
    fallback = BuildNeedsSnapshot.unavailable("x", "no measurement")
    broad, reasons, state = BuildOpportunityModel(fallback).weapon_classes(supported)
    assert "Bows" in broad and "Wands" in broad and reasons[0].kind == EvidenceKind.CONSERVATIVE_FALLBACK
    assert state == Coverage.UNSUPPORTED  # unknown skill is never reported as personalised


def test_unsupported_builds_widen_conservatively_and_stay_valid():
    for needs in (BuildNeedsSnapshot.unavailable("u1", "no measurement", skill_name="Spark"),
                  BuildNeedsSnapshot.unavailable("u2", "no measurement")):
        for profile in FilterProfileName:
            generated = generate(needs, profile)
            assert generated.valid, generated.errors
            decisions = bm.evaluate(generated, [case.item for case in LOOT_CASES])
            assert not any(d.hidden and not matrix_hides(case.item, str(profile.value)) for case, d in zip(LOOT_CASES, decisions)
                           if case.expectation == "protect")
            assert not any(d.personalised for d in decisions), "a fallback must never be labelled personalised"


# --- safety: nothing the legacy filter showed may disappear -------------------------------------------------------------------------------------
def test_intelligence_never_hides_what_the_legacy_generator_showed(snapshots):
    items = bm.systematic_items()[::5]
    for label in (SPARK, BOW, MELEE):
        for profile in bm.PROFILES:
            new = bm.evaluate(generate(snapshots[label], profile), items)
            old = bm.evaluate(generate(snapshots[label], profile, intel=False), items)
            result = generate(snapshots[label], profile)
            lost = [i.name for i, a, b in zip(items, old, new) if not a.hidden and b.hidden
                    and bm.reduction_justification(i, snapshots[label], result, matched_rule=b.rule) == bm.UNEXPLAINED]
            assert not lost, (label, profile, lost[:5])


def test_protected_cases_stay_visible_for_every_measured_build_and_profile(snapshots):
    protected = [case for case in LOOT_CASES if case.expectation == "protect"]
    for label in (SPARK, BOW, MELEE):
        for profile in bm.PROFILES:
            decisions = bm.evaluate(generate(snapshots[label], profile), [case.item for case in protected])
            assert not [c.id for c, d in zip(protected, decisions) if d.hidden and not matrix_hides(c.item, profile)], (label, profile)


def test_extended_false_negative_corpus_has_no_confirmed_errors(snapshots):
    for label in (SPARK, BOW, MELEE):
        report = fn.evaluate_corpus(snapshots[label])
        for profile, result in report["profiles"].items():
            assert result["valid"]
            assert result["counts"].get("CONFIRMED ERROR", 0) == 0, (label, profile)
        # the default profile must not miss an annotated build opportunity
        assert report["profiles"]["Recommended"]["counts"].get("POTENTIAL MISS", 0) == 0, label


# --- differential personalisation ---------------------------------------------------------------------------------------------------------
def test_builds_with_different_measured_needs_get_different_decisions_for_stated_reasons(snapshots):
    items = bm.systematic_items()[::3]
    # Profile system V2: at Recommended a build changes EMPHASIS (generic rows already keep top bases visible); at Strict it also decides what
    # stays visible, because the generic Normal / Magic rows are HIDE there and the build lane ADDS its own bases back.
    rec_spark = bm.evaluate(generate(snapshots[SPARK], "Recommended"), items)
    rec_bow = bm.evaluate(generate(snapshots[BOW], "Recommended"), items)
    assert bm.differential(rec_spark, rec_bow, items)["genuinely_personalised"] > 0
    spark = bm.evaluate(generate(snapshots[SPARK], "Strict"), items)
    bow = bm.evaluate(generate(snapshots[BOW], "Strict"), items)
    diff = bm.differential(spark, bow, items)
    assert diff["visibility_changed"] > 0 and diff["genuinely_personalised"] > 0
    changed = [(items[i], a, b) for i, a, b in diff["_rows"] if a.hidden != b.hidden]
    wand = next(((item, a, b) for item, a, b in changed if item.item_class in ("Wands", "Staves")), None)
    bows = next(((item, a, b) for item, a, b in changed if item.item_class in ("Bows", "Quivers")), None)
    assert wand or bows
    if wand:
        item, a, b = wand
        assert not a.hidden and b.hidden and a.personalised  # spell build keeps the staff/wand, bow build does not
    reasons = bm.material_needs_difference(snapshots[SPARK], snapshots[BOW])
    assert any("damage mode" in r for r in reasons) and any("weapon requirement" in r for r in reasons)


def test_every_changed_decision_carries_confidence_and_evidence(snapshots):
    items = bm.systematic_items()[::7]
    left = bm.evaluate(generate(snapshots[SPARK], "Strict"), items)
    right = bm.evaluate(generate(snapshots[MELEE], "Strict"), items)
    for _, a, b in bm.differential(left, right, items)["_rows"]:
        for d in (a, b):
            if d.rule not in ("game default",) and not d.hidden and d.rule.startswith(("Weapon", "Defense", "Jewellery", "Offhand", "Opportunity")):
                assert d.coverage and d.kinds and d.native_rule


# --- profiles, themes, explanations, offline --------------------------------------------------------------------------------------------------
def test_build_opportunity_rules_run_at_every_level_and_only_add(snapshots):
    """Profile system V2: the Endgame-only opportunity rules are part of every level; a measured build can only ADD with them."""
    needs = snapshots[SPARK]
    for profile in bm.PROFILES:
        generated = generate(needs, profile)
        assert any(r.name.startswith("Opportunity_") for r in generated.rules), profile
        assert all(r.row == "build_relevant_base" and r.state != "HIDE" for r in generated.rules if r.name.startswith("Opportunity_"))


def test_themes_never_change_visibility(snapshots):
    items = bm.systematic_items()[::9]
    signatures = set()
    for theme in FilterThemeName:
        generated = generate(snapshots[SPARK], "Recommended", theme)
        assert generated.valid
        signatures.add(tuple(d.hidden for d in bm.evaluate(generated, items)))
    assert len(signatures) == 1


def test_explanations_state_what_is_measured_and_what_is_not(snapshots):
    generated = generate(snapshots[SPARK], "Recommended")
    promoted = next(r for r in generated.rules if r.name.endswith("_up") and r.category == "BUILD_WEAPON")
    sections = dict(promoted.evidence.sections())
    assert "stat family your build responds to" in sections["BUILD"]
    assert "MEASURED PERSONALIZATION" in sections["CONFIDENCE"] and "unidentified" in sections["CONFIDENCE"]
    assert "not observable" in " ".join(promoted.evidence.details) or "unidentified" in " ".join(promoted.evidence.details)
    assert sections["MARKET"].startswith("HEURISTIC")  # no live/cached price is ever claimed by this layer
    assert set(sections) == {"BUILD", "ITEMIZATION", "CRAFT", "MARKET", "CONFIDENCE"}
    # an unmeasured build never claims personalization: the unmapped-skill weapon fallback lane is retired, so there is no BUILD rule at all
    fallback = generate(BuildNeedsSnapshot.unavailable("u", "none", skill_name="Spark"), "Recommended")
    assert not [r for r in fallback.rules if r.category.startswith("BUILD")]


def test_generation_is_deterministic_and_offline(snapshots):
    a, b = generate(snapshots[SPARK], "Recommended"), generate(snapshots[SPARK], "Recommended")
    assert a.text == b.text
    code = ("import exilelens.filters.intel_generate, sys; "
            "assert not {'exilelens.engine', 'socket', 'requests', 'urllib.request'} & set(sys.modules), sorted(sys.modules)")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr[-400:]
