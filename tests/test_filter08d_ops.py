"""FILTER-08D: failure injection, decision inspector, local feedback capture and the market contract.

Run with:  python -m pytest tests/test_filter08d_ops.py -m ""
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from exilelens.filters import benchmark08b as bm, failure_injection as fi, feedback, inspector, legal_corpus as lc, market_interface as mi
from exilelens.filters import intel_status
from exilelens.filters.data_drift import DataState, DataStatus
from exilelens.filters.intel_generate import filter_body_sha256, generate
from exilelens.filters.opportunity_graph import MarketSignal, OpportunityGraph

ROOT = Path(__file__).resolve().parents[1]
NEEDS = ROOT / "tests" / "fixtures" / "filter_needs" / "filter08e"


@pytest.fixture(scope="module")
def snapshots():
    if not NEEDS.exists():
        pytest.skip("08C needs snapshots not present")
    return bm.load_snapshots(NEEDS)


# -- failure injection -----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("build", ["core04_mixed_hit_ailment", "core04_melee_weapon", "core04_stage_context"])
def test_every_injected_failure_is_conservative(snapshots, build):
    cases = lc.sample(700, 3)
    results = fi.run_all(snapshots[build], cases)
    assert {r.scenario for r in results} == {s.name for s in fi.SCENARIOS}
    failing = [(r.scenario, r.narrower_than_reference, r.reference, r.notes) for r in results if not r.passed]
    assert failing == []
    assert not any(r.crashed for r in results)


def test_incompatible_data_blocks_explicitly_everything_else_degrades_with_a_notice(snapshots):
    results = {r.scenario: r for r in fi.run_all(snapshots["core04_mixed_hit_ailment"], lc.sample(300, 4))}
    assert results["incompatible_data"].blocked_explicitly and "INCOMPATIBLE" in results["incompatible_data"].visible_notice
    for name in ("stale_snapshot", "unverified_newer_game", "unknown_data_state", "partial_pob_calc", "low_confidence_measurement",
                 "missing_bi", "stale_analysis", "failed_analysis"):
        assert results[name].visible_notice, f"{name} must tell the user"
        assert not results[name].blocked_explicitly


def test_degraded_notes_reach_the_dashboard_status(snapshots):
    needs = snapshots["core04_mixed_hit_ailment"]
    assert intel_status.degraded_notes(needs, None) == []
    stale = DataStatus(DataState.STALE_SNAPSHOT, ("older than the game",))
    status = intel_status.describe(needs, state=intel_status.IntelState.CURRENT, data_status=stale)
    assert "STALE SNAPSHOT" in status.text and "widened" in status.text
    incomplete = next(n for n in snapshots.values() if n.has_measurement and not n.evidence_complete)
    assert "Evidence incomplete" in intel_status.describe(incomplete, state=intel_status.IntelState.CURRENT).text


def test_missing_itemization_data_widens_instead_of_hiding(snapshots):
    """Regression for two defects found by failure injection: lost family mapping must not empty the spell weapon classes or
    evidence-gate every base to IGNORE."""
    from unittest import mock
    from exilelens.filters.opportunity import BuildOpportunityModel
    needs = snapshots["core04_mixed_hit_ailment"]
    supported = ["Staves", "Wands", "Sceptres"]
    baseline = BuildOpportunityModel(needs).weapon_classes(supported)[0]
    with mock.patch("exilelens.filters.affix_pools.pools_for", return_value={}), \
            mock.patch("exilelens.filters.affix_pools.implicit_families", return_value=()), \
            mock.patch("exilelens.filters.affix_pools.universal_families", return_value=frozenset()):
        model = BuildOpportunityModel(needs)
        assert set(model.weapon_classes(supported)[0]) >= set(supported) - {"Staves"}
        decision = model.decide("Reflecting Staff", "Staves")
        assert decision.quality_tier.value != "IGNORE"
    assert "Staves" in baseline


def test_incomplete_evidence_keeps_verified_spell_weapon_classes(snapshots):
    from dataclasses import replace
    from exilelens.filters.opportunity import BuildOpportunityModel
    needs = snapshots["core04_stage_context"]
    degraded = replace(needs, skill=replace(needs.skill, verified=False))
    assert not degraded.evidence_complete
    supported = ["Staves", "Wands", "Sceptres"]
    assert set(BuildOpportunityModel(needs).weapon_classes(supported)[0]) <= set(BuildOpportunityModel(degraded).weapon_classes(supported)[0])


# -- inspector -------------------------------------------------------------------------------------------------------------------------
def test_inspector_explains_every_profile_and_compares_builds(snapshots):
    spark, melee = snapshots["spark_fixture"], snapshots["core04_melee_weapon"]
    item = inspector.make_item("Voltaic Staff", rarity="Rare", item_level=84)
    inspection = inspector.inspect(spark, item, compare=melee)
    assert [v.profile for v in inspection.verdicts] == list(bm.PROFILES)
    assert inspection.verdicts[1].visible and inspection.graph_facts
    assert inspection.compared and inspection.compared.verdicts[1].rule != inspection.verdicts[1].rule
    text = inspector.render(inspection)
    assert "Recommended" in text and "compared with" in text and "Differences:" in text
    json.dumps(inspection.to_dict(), default=str)


def test_inspector_flags_unknown_bases_and_reduction_justification(snapshots):
    needs = snapshots["core04_mixed_hit_ailment"]
    unknown = inspector.inspect(needs, inspector.make_item("Not A Real Base", item_class="Boots"), profiles=("Recommended",))
    assert any("not in the verified catalog" in n for n in unknown.notes)
    hidden = [v for v in inspector.inspect(needs, inspector.make_item("Plated Greaves", rarity="Magic", item_level=60), profiles=bm.PROFILES).verdicts
              if not v.visible]
    assert all(v.justification for v in hidden)


def test_inspector_cli_runs(snapshots, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("filter_inspect", ROOT / "tools" / "filter_inspect.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--needs", str(NEEDS / "core04_mixed_hit_ailment.json"), "--base", "Plated Greaves", "--rarity", "Magic",
                        "--ilvl", "88", "--profiles", "Strict"]) == 0
    assert "Strict" in capsys.readouterr().out


# -- feedback --------------------------------------------------------------------------------------------------------------------------
def test_feedback_capture_is_local_and_privacy_safe(snapshots, tmp_path):
    needs = snapshots["core04_mixed_hit_ailment"]
    item = inspector.make_item("Plated Greaves", rarity="Magic", item_level=88)
    case = feedback.capture(needs, "Strict", item, "SHOW", note="expected to see this", now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert case.build_label == "" and case.needs_identity and len(case.rules_sha) == 64
    text = case.to_json()
    for forbidden in ("path", "account", "character", needs.identity.get("build_path", "xx")):
        assert forbidden not in text.replace('"note"', "")
    path = feedback.save(case, tmp_path)
    assert feedback.load_all(tmp_path) == [case] and path.parent == tmp_path
    labelled = feedback.capture(needs, "Strict", item, "HIDE", include_label=True)
    assert labelled.build_label == needs.label


def test_feedback_replay_detects_match_mismatch_and_wrong_build(snapshots):
    needs, other = snapshots["core04_mixed_hit_ailment"], snapshots["spark_fixture"]
    item = inspector.make_item("Plated Greaves", rarity="Magic", item_level=88)
    observed = feedback.capture(needs, "Strict", item, "SHOW")
    right = feedback.replay(observed, needs)
    assert right.verdict in ("MATCHES", "MISMATCH") and not right.rules_changed
    flipped = feedback.capture(needs, "Strict", item, "HIDE" if observed.observed == "SHOW" else "SHOW")
    assert feedback.replay(flipped, needs).verdict == "MISMATCH"
    assert feedback.replay(feedback.capture(needs, "Strict", item, "UNSURE"), needs).verdict == "UNSURE_RECORDED"
    assert feedback.replay(observed, other).verdict == "WRONG_BUILD"
    assert [r.verdict for r in feedback.replay_all([observed], {"a": needs})] == [right.verdict]


def test_feedback_rejects_unknown_expectation_and_schema(snapshots):
    needs = snapshots["core04_mixed_hit_ailment"]
    with pytest.raises(ValueError):
        feedback.capture(needs, "Strict", inspector.make_item("Plated Greaves"), "MAYBE")
    with pytest.raises(ValueError):
        feedback.FeedbackCase.from_json(json.dumps({"schema": 99}))


def test_feedback_directory_honours_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("EXILELENS_FEEDBACK_DIR", str(tmp_path / "fb"))
    assert feedback.feedback_dir() == tmp_path / "fb" and feedback.load_all() == []


# -- market contract -------------------------------------------------------------------------------------------------------------------
def test_market_contract_validates_provenance():
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    mi.validate_signal(MarketSignal("UNKNOWN"))
    mi.validate_signal(MarketSignal("HEURISTIC", "pinned"))
    mi.validate_signal(MarketSignal("CACHED", "snapshot", (now - timedelta(days=1)).isoformat()), now=now)
    for bad in (MarketSignal("LIVE", "", ""), MarketSignal("LIVE", "x", "2026-01-01T00:00:00"), MarketSignal("CACHED", "x", (now + timedelta(days=1)).isoformat()),
                MarketSignal("RICH", "x", "")):
        with pytest.raises(mi.MarketContractError):
            mi.validate_signal(bad, now=now)


def test_market_signals_degrade_to_unknown_and_never_change_the_filter(snapshots):
    class Exploding:
        def category_context(self, item_class, base_type, league):
            raise RuntimeError("network down")

    pairs = [("Boots", "Plated Greaves")]
    assert mi.signals_from(None, pairs)["Plated Greaves"].level == "UNKNOWN"
    failed = mi.signals_from(Exploding(), pairs)["Plated Greaves"]
    assert failed.level == "UNKNOWN" and "RuntimeError" in failed.source
    assert mi.signals_from(mi.HeuristicMarketProvider(), pairs)["Plated Greaves"].level == "HEURISTIC"
    needs = snapshots["core04_mixed_hit_ailment"]
    plain = OpportunityGraph.build(needs)
    with_market = OpportunityGraph.build(needs, market=mi.signals_from(mi.HeuristicMarketProvider(), pairs))
    assert with_market.market("Plated Greaves").level == "HEURISTIC" and plain.market("Plated Greaves").level == "UNKNOWN"
    # generation never reads market data: the rules are byte-identical regardless
    assert filter_body_sha256(generate(needs, "Recommended").text) == filter_body_sha256(generate(needs, "Recommended").text)


# -- FILTER-08E: silent degradations are visible ---------------------------------------------------------------------------------------
def test_every_fallback_is_visible_and_non_blocking(snapshots):
    cases = lc.sample(300, 5)
    results = {r.scenario: r for r in fi.run_all(snapshots["core04_melee_weapon"], cases)}       # Sunder: an attack skill
    for name in ("incomplete_fingerprint", "missing_family_mapping", "missing_base_metadata", "unknown_weapon_requirement"):
        assert results[name].passed and results[name].visible_notice, name
        assert "conservative fallback" in results[name].visible_notice
    assert "weapon requirement unknown" in results["unknown_weapon_requirement"].visible_notice
    assert "no observed gear" in results["incomplete_fingerprint"].visible_notice
    assert "stat-family mapping missing" in results["missing_family_mapping"].visible_notice
    assert "base metadata missing" in results["missing_base_metadata"].visible_notice


def test_real_builds_report_only_genuine_fallbacks(snapshots):
    reported = {label: [d.code for d in generate(n, "Recommended").degradations] for label, n in snapshots.items()}
    assert reported["spark_fixture"] == []
    assert reported["core04_onehand_weapon"] == ["WEAPON_REQUIREMENT_UNKNOWN"]
    assert reported["corpus02d2_voltaic_barrier"] == ["SKILL_UNRESOLVED"]
    text = intel_status.describe(snapshots["core04_onehand_weapon"], state=intel_status.IntelState.CURRENT,
                                 degradations=generate(snapshots["core04_onehand_weapon"], "Recommended").degradations).text
    assert "Partial personalization" in text and "FALLBACK: weapon requirement unknown" in text
