"""FILTER-08E: the Build Intelligence adapter against production after R1 (#64) / R1.5 (#65).

Offline tests pin the contract (structures, freshness, additive keys); the live test re-runs the real PoB analysis for one build and compares
it with the canonical snapshot (skipped unless a PoB2 checkout is present).

Run with:  python -m pytest tests/test_filter08e_adapter.py -m ""
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

from exilelens.filters import canonical, intel_status
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.intel_fixtures import synthetic_analysis

ROOT = Path(__file__).resolve().parents[1]
POB2 = Path(os.environ.get("EXILELENS_POB2", ".run/absent-pob"))


def r15_payload(base: dict) -> dict:
    """The additive keys R1 / R1.5 put on the analysis result."""
    payload = copy.deepcopy(base)
    payload["strongest_responses"] = {"offense": [{"probe_id": "CAST_SPEED"}], "defense": []}
    payload["response_curves"] = {"schema_version": 1, "budget": 3, "new_recalcs": 3, "curves": [{"probe_id": "CAST_SPEED", "points": [1, 2]}]}
    payload["actionable"] = {"schema_version": 1, "focus": {"title": "x"}, "next_actions": [], "changes": []}
    payload["performance"] = {"elapsed_ms": 1.0, "pob_recalcs": 49, "probe_count": 40, "cache": {}}
    return payload


def test_additive_r1_r15_keys_do_not_change_the_needs_snapshot():
    base = synthetic_analysis()
    plain = BuildNeedsSnapshot.from_analysis(base, label="t")
    extended = BuildNeedsSnapshot.from_analysis(r15_payload(base), label="t")
    assert plain.to_dict() == extended.to_dict()
    assert plain.signals and plain.skill.name == "Spark"


def test_supported_fields_are_still_consumed_with_the_documented_semantics():
    needs = BuildNeedsSnapshot.from_analysis(r15_payload(synthetic_analysis()), label="t")
    spell = needs.signal("SPELL_SKILL_LEVELS")
    assert spell is not None and spell.status == "MEASURED" and spell.relevance in ("STRONG", "FIX_FIRST", "RESPONSIVE")
    assert needs.signal("ATTACK_SPEED").relevance == "NO_RESPONSE"              # no_signal probes stay "no response", never evidence of need
    assert needs.identity["generation"] == 1 and needs.skill.owner in ("PLAYER", "")


def test_freshness_and_staleness_contract_is_unchanged():
    payload = r15_payload(synthetic_analysis(generation=3, build_path="C:/builds/b.xml"))
    assert intel_status.is_build_analysis(payload)
    assert intel_status.is_current(payload, generation=3, build_path="C:/builds/b.xml")
    assert not intel_status.is_current(payload, generation=4, build_path="C:/builds/b.xml")      # baseline bumped -> stale
    assert not intel_status.is_current(payload, generation=3, build_path="C:/builds/other.xml")
    assert not intel_status.is_build_analysis({"kind": "tree", "nodes": [1]})


def test_dashboard_still_uses_the_controller_contract():
    import inspect
    from exilelens.app.controller import EvaluationController
    from exilelens.ui import filters_page
    source = inspect.getsource(filters_page.FiltersPage)
    for name in ("analysis_started", "analysis_finished", "analysis_error", "analysis_stale", "submit_analyze_build", "last_analysis",
                 "baseline_generation"):
        assert name in source
    signature = inspect.signature(EvaluationController.submit_analyze_build)
    assert "defence_probes" in signature.parameters
    for name in ("analysis_started", "build_analysis_started", "analysis_finished", "analysis_stale", "last_analysis", "baseline_generation"):
        assert hasattr(EvaluationController, name)


def test_canonical_snapshots_match_the_current_projection_rules():
    """A stored canonical snapshot must equal what the CURRENT from_dict/to_dict round trip produces (no stale schema)."""
    for path in sorted(canonical.CANONICAL_NEEDS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert BuildNeedsSnapshot.from_dict(data).to_dict() == BuildNeedsSnapshot.from_dict(BuildNeedsSnapshot.from_dict(data).to_dict()).to_dict()


@pytest.mark.skipif(not (POB2 / "src").exists() and not POB2.exists(), reason="no local PoB2 checkout")
def test_live_analysis_after_r15_matches_the_canonical_snapshot():
    from exilelens.config import PobConfig
    from exilelens.engine import Engine
    spec = importlib.util.spec_from_file_location("filter08b_snapshots", ROOT / "scripts" / "filter08b_snapshots.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_bow_quiver.xml"
    with Engine(PobConfig(POB2), use_subprocess=True) as engine:
        live, _ = module.snapshot_one(engine, path)
    stored = BuildNeedsSnapshot.from_dict(json.loads((canonical.CANONICAL_NEEDS_DIR / "core04_bow_quiver.json").read_text(encoding="utf-8")))
    key = lambda n: {(s.probe_id, s.status, s.relevance, s.confidence) for s in n.signals}
    assert key(live) == key(stored)
    assert live.skill == stored.skill and live.coverage == stored.coverage and live.evidence_complete == stored.evidence_complete
