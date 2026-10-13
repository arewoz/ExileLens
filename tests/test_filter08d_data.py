"""FILTER-08D: versioned data, drift guard, snapshot tooling, item-family audit and the Item Opportunity Graph. Offline.

Run with:  python -m pytest tests/test_filter08d_data.py -m ""
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from exilelens.filters import affix_pools, benchmark08b as bm, coverage_audit as audit, data_drift as drift, snapshot_tools as st
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.intel_generate import generate
from exilelens.filters.opportunity import ROLE_BY_CLASS, BuildOpportunityModel
from exilelens.filters.opportunity_graph import EdgeKind, MarketSignal, OpportunityGraph, Provenance
from exilelens.filters.verified_bases import FILTER_TO_POB_CLASS, load_base_properties, native_class

NEEDS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "filter_needs" / "filter08e"
POB = Path(os.environ.get("POB2_PATH") or ".run/absent-pob")


@pytest.fixture(scope="module")
def snaps():
    return bm.load_snapshots(NEEDS)


# --- drift states ----------------------------------------------------------------------------------------------------------------------
def _data_copy(directory: Path) -> Path:
    directory.mkdir()
    for name in (*st.FILES, st.MANIFEST):
        shutil.copy(st.DATA_DIR / name, directory / name)
    return directory


def test_checked_in_data_is_current_and_consistent():
    status = drift.check()
    assert status.state == drift.DataState.CURRENT and not status.reasons
    assert status.versions["pob_commit"] == status.versions["supported_pob_head"] and status.versions["game_version_hint"]
    assert not status.widen and not status.blocks


def test_drift_states_and_their_safe_behaviour(tmp_path):
    base = _data_copy(tmp_path / "d")
    assert drift.check(base).state == drift.DataState.CURRENT
    assert drift.check(base, client_version="0.9.1").state == drift.DataState.UNVERIFIED_NEWER_GAME      # client newer than the data
    assert drift.check(base, client_version="0.4.0").state == drift.DataState.CURRENT
    assert drift.check(base, supported_pob_head="deadbeef").state == drift.DataState.STALE_SNAPSHOT
    target = base / "poe2_base_properties.json"
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert drift.check(base).state == drift.DataState.INCOMPATIBLE_DATA                                  # bytes differ from the manifest
    (base / st.MANIFEST).unlink()
    assert drift.check(base).state == drift.DataState.UNKNOWN
    for state, widen, blocks in ((drift.DataState.STALE_SNAPSHOT, True, False), (drift.DataState.UNVERIFIED_NEWER_GAME, True, False),
                                 (drift.DataState.UNKNOWN, True, False), (drift.DataState.INCOMPATIBLE_DATA, False, True),
                                 (drift.DataState.CURRENT, False, False)):
        status = drift.DataStatus(state, ())
        assert (status.widen, status.blocks) == (widen, blocks)


def test_generation_blocks_on_incompatible_data_and_widens_on_stale_data(snaps):
    needs = snaps["spark_fixture"]
    with pytest.raises(drift.DataIncompatible):
        generate(needs, "Recommended", data_status=drift.DataStatus(drift.DataState.INCOMPATIBLE_DATA, ("test",)))
    normal = generate(needs, "Strict", data_status=drift.DataStatus(drift.DataState.CURRENT, ()))
    stale = generate(needs, "Strict", data_status=drift.DataStatus(drift.DataState.STALE_SNAPSHOT, ("test",)))
    assert "# Data: STALE SNAPSHOT" in stale.text and "# Data: CURRENT" in normal.text
    items = bm.systematic_items()[::4]
    shown_normal = sum(not d.hidden for d in bm.evaluate(normal, items))
    shown_stale = sum(not d.hidden for d in bm.evaluate(stale, items))
    assert shown_stale >= shown_normal and stale.valid                                                    # drift may only widen


# --- snapshot regeneration -----------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def built():
    if not (POB / "src" / "Data" / "Bases").exists():
        pytest.skip("PoB2 checkout not available")
    return st.build(POB)


def test_regeneration_reproduces_the_checked_in_data_with_no_changes(built):
    assert built[st.MANIFEST]["validation"]["passed"], built[st.MANIFEST]["validation"]["problems"][:3]
    report = st.diff(built)
    assert {k: len(v) for k, v in report.items()} == {k: 0 for k in report}
    assert not st.breaking(report)


def test_snapshot_diff_classifies_every_kind_of_change(built):
    changed = copy.deepcopy(built)
    props = changed["poe2_base_properties.json"]["bases"]
    pool = changed["poe2_affix_pools.json"]
    props["Ashen Staff Mk2"] = dict(props.pop("Gelid Staff"))                                            # RENAMED
    props["Brand New Wand"] = dict(props["Ashen Staff"], **{"class": "Wand", "required_level": 99, "implicit": "x"})   # ADDED
    del props["Bone Wand"]                                                                               # REMOVED
    props["Voltaic Staff"]["class"] = "Wand"                                                             # CLASS CHANGED
    props["Permafrost Staff"]["required_level"] += 5                                                     # REQUIREMENT CHANGED
    sig = pool["base_pool"]["Galvanic Wand"]
    pool["pools"][sig] = {**pool["pools"][sig], "families": {k: v for k, v in pool["pools"][sig]["families"].items() if k != "CAST_SPEED"}}
    report = st.diff(changed)
    assert any(r["to"] == "Ashen Staff Mk2" for r in report["RENAMED"])
    assert "Brand New Wand" in report["ADDED"] and "Bone Wand" in report["REMOVED"]
    assert any(c["base"] == "Voltaic Staff" for c in report["CLASS CHANGED"]) and any(c["base"] == "Permafrost Staff" for c in report["REQUIREMENT CHANGED"])
    assert any("CAST_SPEED" in c["families_changed"] for c in report["MOD POOL CHANGED"])
    assert st.breaking(report)


def test_validation_catches_broken_relationships(built):
    broken = copy.deepcopy(built)
    broken["poe2_affix_pools.json"]["families"]["SPELL_DAMAGE"]["probe_id"] = "NOT_A_PROBE"
    del broken["poe2_base_properties.json"]["bases"]["Bone Wand"]
    problems = st.validate(broken)
    assert any("not in the production probe catalog" in p for p in problems) and any("base name sets differ" in p for p in problems)


def test_writing_a_candidate_never_touches_the_checked_in_data(built, tmp_path):
    before = (st.DATA_DIR / "poe2_bases.json").read_bytes()
    st.write(built, tmp_path / "cand")
    assert (tmp_path / "cand" / "poe2_item_catalog.json").exists() and (st.DATA_DIR / "poe2_bases.json").read_bytes() == before
    assert json.loads((tmp_path / "cand" / st.MANIFEST).read_text(encoding="utf-8"))["files"]["poe2_item_catalog.json"]["sha256"]


# --- item family audit ---------------------------------------------------------------------------------------------------------------------
def test_family_matrix_reports_gaps_instead_of_hiding_them():
    matrix = audit.family_matrix()
    detections, coverage = matrix["detections"], matrix["coverage"]
    # FILTER-08E: Charms and Traps got verified native classes; what remains is explicit, sourced and ambiguous in the pinned data.
    assert detections["unclassified_bases (no native class)"]["count"] == 13
    assert set(detections["valid_pob_classes_without_filter_native_class"]) == {"Fishing Rod", "Transcendent Limb"}
    assert set(detections["valid_pob_classes_without_filter_native_class"]) <= set(audit.UNCLASSIFIED_DISPOSITION)
    assert detections["bases_in_multiple_incompatible_classes"] == []
    assert detections["dead_skill_map_entries"] == [] and detections["curated_tier_entries_in_wrong_native_class (active)"] == []
    assert coverage["of_equipment_bases"]["verified_classification_pct"] == 100.0
    assert coverage["verified_classification_pct"] < 100 and coverage["fallback_only_pct (no build or global-tier handling)"] > 0           # honest, not 100 %
    for family in ("Flail", "Claw", "Dagger", "One Hand Axe", "Two Hand Sword", "Talisman", "Crossbow", "Focus", "Quarterstaff", "Quiver"):
        row = matrix["classes"][family]
        assert row["native_classes"] and row["filter_handling"][row["native_classes"][0]]["build_rules"]


def test_every_native_class_is_known_and_slots_have_one_explicit_gap():
    records = audit.catalog()
    for name in records:
        native = native_class(name)
        assert native is None or native in FILTER_TO_POB_CLASS
    assert {r["class"] for r in records.values() if audit.slot_of(r) is None} == {"Transcendent Limb"}


def test_modifier_family_registry_is_complete_and_language_safe():
    registry = audit.family_registry()["families"]
    assert set(registry) == set(affix_pools.family_definitions())
    for family, row in registry.items():
        assert row["modifier_observable_on_unidentified_item"] is False and "never said to HAVE" in row["language"]
    lightning = registry["SPELL_SKILL_LEVELS@Lightning"]["classes"]["Staves"]
    assert lightning["bases_able"] < lightning["bases_in_class"] and "no_lightning_spell_mods" in lightning["excluded_by_tags"]
    assert registry["ARMOUR"]["production_runs_probe_globally"] is False and registry["LIFE"]["production_runs_probe_globally"] is True


# --- opportunity graph ----------------------------------------------------------------------------------------------------------------------
def test_graph_edges_always_carry_provenance_and_no_scores(snaps):
    graph = OpportunityGraph.build(snaps["spark_fixture"])
    assert all(isinstance(e.provenance, Provenance) for e in graph.edges)
    assert {e.kind for e in graph.edges} >= {EdgeKind.NEED_TO_FAMILY, EdgeKind.FAMILY_TO_BASE, EdgeKind.BASE_PROXY, EdgeKind.SKILL_CLASS}
    assert "score" not in graph.to_json().lower() and graph.summary()["data"]["state"] == "CURRENT"
    need = next(e for e in graph.edges if e.kind == EdgeKind.NEED_TO_FAMILY)
    assert need.provenance == Provenance.BI_MEASUREMENT and need.get("tested_change")
    assert all(e.get("modifier_observable") is False for e in graph.edges if e.kind == EdgeKind.BASE_PROXY)


def test_graph_answers_the_four_questions(snaps):
    graph = OpportunityGraph.build(snaps["spark_fixture"])
    opportunities = {o.base: o for o in graph.opportunities(decision_policy=True)}
    assert "Voltaic Staff" in opportunities and "Ashen Staff" not in opportunities                       # which bases?
    why = " ".join(graph.why("Voltaic Staff"))
    assert "SPELL_SKILL_LEVELS@Lightning" in why and "NOT observable" in why and "production Build Intelligence measurement" in why
    first, top = graph.unlock_levels("Voltaic Staff")["SPELL_SKILL_LEVELS@Lightning"]                     # which item level?
    assert first <= 5 and top >= 75 and opportunities["Voltaic Staff"].unlock_level("SPELL_SKILL_LEVELS@Lightning") == top
    assert graph.is_measured("Voltaic Staff") is True                                                     # measured or fallback?
    silent = next(b for b in load_base_properties() if not affix_pools.pools_for(b) and not affix_pools.implicit_families(b))
    assert graph.is_measured(silent) is False and "no evidence either way" in " ".join(graph.why(silent))
    assert "not in the verified base catalog" in graph.why("No Such Base")[0]


def test_graph_reproduces_the_decision_model_on_every_measured_build(snaps):
    for label, needs in snaps.items():
        model = BuildOpportunityModel(needs)
        promoted = {b for b in load_base_properties() if native_class(b) in ROLE_BY_CLASS and model.decide(b, native_class(b)).shift > 0}
        graph = {o.base for o in OpportunityGraph.build(needs).opportunities(decision_policy=True) if o.native_class in ROLE_BY_CLASS}
        assert promoted == graph, label


def test_graph_skill_edges_separate_verified_requirements_from_curated_fallbacks(snaps):
    bow = OpportunityGraph.build(snaps["core04_bow_quiver"])
    assert {e.provenance for e in bow.edges if e.kind == EdgeKind.SKILL_CLASS} == {Provenance.COMPATIBILITY_REQUIREMENT}
    fallback = OpportunityGraph.build(BuildNeedsSnapshot.unavailable("u", "none", skill_name="Leap Slam"))
    assert {e.provenance for e in fallback.edges if e.kind == EdgeKind.SKILL_CLASS} <= {Provenance.CURATED_FALLBACK, Provenance.COMPATIBILITY_REQUIREMENT}
    assert not fallback.need_edges(0)                                                                     # no measurement: no need edges invented


def test_graph_market_contract_is_optional_and_never_a_price(snaps):
    needs = snaps["spark_fixture"]
    assert OpportunityGraph.build(needs).market("Voltaic Staff") == MarketSignal()                         # UNKNOWN by default
    signal = MarketSignal("CACHED", "test provider", "2026-10-01T00:00:00+00:00")
    graph = OpportunityGraph.build(needs, market={"Voltaic Staff": signal})
    assert graph.market("Voltaic Staff") == signal
    assert not any("price" in k for e in graph.edges for k, _ in e.attrs)
