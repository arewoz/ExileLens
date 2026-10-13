"""FILTER-08E: upstream sync, evidence completion, coverage completion, degradation visibility, stability and traceability.

Run with:  python -m pytest tests/test_filter08e.py -m ""
"""
from __future__ import annotations

from pathlib import Path

import pytest

from exilelens.filters import benchmark08b as bm, canonical, coverage_audit as audit, inspector
from exilelens.filters.intel_generate import generate
from exilelens.filters.preview import preview_decision
from exilelens.filters.verified_bases import load_base_properties, native_class

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def snapshots():
    if not canonical.CANONICAL_NEEDS_DIR.exists():
        pytest.skip("canonical needs not present")
    return bm.load_snapshots(canonical.CANONICAL_NEEDS_DIR)


# -- canonical vs historical -----------------------------------------------------------------------------------------------------------

# -- the 39 unclassified bases ---------------------------------------------------------------------------------------------------------
def test_no_base_is_unexplained():
    unclassified = {r["class"] for b, r in load_base_properties().items() if native_class(b) is None}
    assert unclassified <= set(audit.UNCLASSIFIED_DISPOSITION), unclassified
    for cls in unclassified:
        disposition, reason = audit.UNCLASSIFIED_DISPOSITION[cls]
        assert disposition and "PoE2DB" in reason


def test_charms_and_traps_have_verified_native_classes():
    classes = {native_class(b) for b, r in load_base_properties().items() if r["class"] in ("Charm", "TrapTool")}
    assert classes == {"Charms", "Traps"}


# -- belts (PARTIAL PERSONALIZATION via the verified implicit) -------------------------------------------------------------------------
def test_belt_implicit_rule_is_evidence_backed_and_additive(snapshots):
    needs = snapshots["spark_fixture"]
    result = generate(needs, "Recommended")
    rule = next(r for r in result.rules if r.name == "Belt_Implicit")
    assert rule.lines[1] == '\tClass "Belts"' and "Invoking Belt" in rule.base_types
    magic = inspector.make_item("Invoking Belt", rarity="Magic", item_level=60)
    assert not preview_decision(result.rules, magic).hidden
    assert preview_decision(generate(needs, "Recommended", intel=False).rules, magic).hidden          # legacy hid it
    # a belt whose implicit the build does not need stays under the generic rule
    assert preview_decision(result.rules, inspector.make_item("Linen Belt", rarity="Magic", item_level=60)).hidden


def test_belt_rule_needs_a_measurement_and_an_unlocking_profile_and_survives_widening(snapshots):
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    from exilelens.filters.data_drift import DataState, DataStatus
    needs = snapshots["spark_fixture"]
    has = lambda result: any(r.name == "Belt_Implicit" for r in result.rules)
    assert has(generate(needs, "Recommended"))
    assert not has(generate(needs, "Very Strict"))                                       # profiles that do not unlock opportunities
    assert not has(generate(BuildNeedsSnapshot.unavailable("x", "none", skill_name="Spark"), "Recommended"))   # no measurement, no claim
    # additive rules survive widening: fuzz invariant M found it when the rule was first dropped under drift
    stale = DataStatus(DataState.STALE_SNAPSHOT, ("test",))
    assert has(generate(needs, "Recommended", data_status=stale))
    incomplete = next(n for n in snapshots.values() if n.has_measurement and not n.evidence_complete)
    assert has(generate(incomplete, "Recommended")) == has(generate(incomplete, "Recommended", data_status=stale))


# -- natural-drop logging preparation --------------------------------------------------------------------------------------------------
def test_annotations_record_the_observation_and_drive_replay(snapshots, tmp_path):
    from exilelens.filters import feedback
    needs = snapshots["spark_fixture"]
    shown = inspector.make_item("Voltaic Staff", rarity="Rare", item_level=84)
    hidden = inspector.make_item("Plated Greaves", rarity="Magic", item_level=60)
    assert set(feedback.ANNOTATIONS) == {"SHOULD SHOW", "SHOULD HIDE", "UNSURE", "VALUABLE MISS", "NOISE"}
    miss = feedback.capture(needs, "Recommended", hidden, "VALUABLE MISS", note="should have shown")
    noise = feedback.capture(needs, "Recommended", shown, "NOISE")
    assert miss.expected == "SHOW" and miss.annotation == "VALUABLE MISS" and miss.observed == "HIDE"
    assert noise.expected == "HIDE" and noise.observed == "SHOW"
    for case in (miss, noise):
        assert case.provenance and len(case.needs_sha256) == 64 and case.rules_sha and case.observed_rule and case.data_state == "CURRENT"
        assert case.build_label == ""                                   # no build name unless asked
        assert feedback.replay(case, needs).verdict == "MISMATCH"       # both are exactly the observed misbehaviour
    feedback.save(miss, tmp_path)
    assert feedback.load_all(tmp_path) == [miss]
    rows = feedback.natural_drop_corpus([miss, noise, feedback.capture(needs, "Recommended", shown, "UNSURE")])
    assert [r["annotation"] for r in rows] == ["VALUABLE MISS", "NOISE"]
    assert "build_label" not in rows[0] and "note" not in rows[0]


def test_schema_1_cases_still_load():
    from exilelens.filters import feedback
    old = {"id": "x", "schema": 1, "captured_at": "t", "profile": "Strict", "needs_identity": "h", "item": {"name": "a"}, "expected": "SHOW",
           "observed": "HIDE", "observed_rule": "r", "rules_sha": "s"}
    import json
    assert feedback.FeedbackCase.from_json(json.dumps(old)).annotation == ""


# -- Build Priority traceability ---------------------------------------------------------------------------------------------------------
def test_traceability_classifies_every_measured_need(snapshots):
    from exilelens.filters import traceability as tr
    needs = snapshots["spark_fixture"]
    from dataclasses import replace
    from exilelens.filters.build_needs import Relevance
    needs = replace(needs, signals=tuple(replace(s, status="UNSUPPORTED", responses={},
                                                relevance=Relevance.NOT_ESTABLISHED.value)
                                        if s.probe_id == "FIRE_RES" else s for s in needs.signals))
    traces = {t.probe: t for t in tr.trace(needs, {"Recommended": generate(needs, "Recommended").rules})}
    assert traces["SPELL_SKILL_LEVELS"].classification == "A" and traces["SPELL_SKILL_LEVELS"].eligible_bases > 50
    assert traces["SPELL_SKILL_LEVELS"].rules["Recommended"] and "Class" in traces["SPELL_SKILL_LEVELS"].native_proxy
    assert traces["ATTACK_SPEED"].classification == "D"                    # measured no response
    assert traces["FIRE_RES"].classification == "C"                        # never established (unsupported probe)
    chaos = traces["CHAOS_RES"]
    assert chaos.relevance == "FIX_FIRST" and "cannot claim any item contains the fix" in chaos.why
    assert tr.LIMIT in chaos.limitation and "=>" in chaos.chain()
    assert set(tr.summarise(list(traces.values()))) == {"A", "B", "C", "D"}


# -- rule-warning decomposition ----------------------------------------------------------------------------------------------------------
def test_every_rule_warning_has_a_structural_cause(snapshots):
    import importlib.util
    spec = importlib.util.spec_from_file_location("filter08e_rule_warnings", ROOT / "scripts" / "filter08e_rule_warnings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from exilelens.filters import rule_ir as ri
    result = generate(snapshots["core04_bow_quiver"], "Recommended")
    by_name = {r.name: r for r in result.rules}
    causes = {module.cause(f, by_name) for f in ri.analyse(result.rules).findings if f.kind in ("SHADOWED", "DUPLICATE", "REDUNDANT")}
    assert causes and "UNEXPLAINED" not in causes


# -- optimizer ---------------------------------------------------------------------------------------------------------------------------
def test_optimizer_is_equivalent_on_canonical_builds(snapshots):
    from exilelens.filters import rule_ir as ri
    for label in ("spark_fixture", "core04_minion_actor"):
        for profile in ("Recommended", "Endgame"):
            plain, fast = generate(snapshots[label], profile), generate(snapshots[label], profile, optimize=True)
            assert fast.valid and len(fast.rules) < len(plain.rules)
            assert ri.compare(plain.rules, fast.rules).equivalent(strict=True)


# -- stability benchmark helpers ---------------------------------------------------------------------------------------------------------

# -- acceptance artifact ---------------------------------------------------------------------------------------------------------------
