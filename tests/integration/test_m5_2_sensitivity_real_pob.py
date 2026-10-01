"""M5.2 against real PoB: the profile mirrors what the existing probes measured, and adds no PoB work."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from exilelens.analysis.fingerprint import profile_independent
from exilelens.analysis.pipeline import analyze_build, rescore_analysis
from exilelens.analysis.sensitivity import build_sensitivity, profile_independent_sensitivity

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _analyze(engine, name: str) -> dict:
    return analyze_build(engine, build_path=str((CORPUS / name).resolve()), slot_filter="Amulet")


def test_acolyte_profile_matches_probes_and_survives_rescore(real_pob_engine) -> None:
    result = _analyze(real_pob_engine, "corpus02g_dex_int_acolyte_hand_of_wisdom.xml")
    sens = result["build_sensitivity"]
    assert sens["identity"]["baseline_fingerprint"] == result["build_fingerprint"]["identity"]["baseline_fingerprint"]
    assert sens["identity"]["generation"] == result["build_fingerprint"]["identity"]["generation"]
    measured = [s for s in sens["signals"] if s["status"] == "MEASURED"]
    assert measured and all(s["probe"]["magnitude"] for s in measured)
    for signal in measured:  # response mirrors the probe's own metric_profile
        probe = next(p for p in result["global_probes"] if p["probe_id"] == signal["probe_id"] and not p.get("breakpoint_exact") and not p.get("nonlinear_sample") and p.get("status") == "ok")
        assert signal["response"]["offense"]["percent"] == probe["metric_profile"]["primary_offense"]["percent_delta"]
    started = time.perf_counter()
    again = build_sensitivity(result)
    assert (time.perf_counter() - started) * 1000 < 50 and again == sens  # pure, no PoB involved
    rescored = rescore_analysis(result, "MAPPING")
    assert profile_independent_sensitivity(rescored["build_sensitivity"]) == profile_independent_sensitivity(sens)
    assert profile_independent(rescored["build_fingerprint"]) == profile_independent(result["build_fingerprint"])
    json.dumps(sens)


def test_minion_build_keeps_minion_ownership_without_fabricated_player_facts(real_pob_engine) -> None:
    result = _analyze(real_pob_engine, "core04_minion_actor.xml")
    sens = result["build_sensitivity"]
    assert sens["offense_context"]["owner"] == "MINION"
    assert result["build_fingerprint"]["offense"]["crit"]["present"]["evidence"] == "UNAVAILABLE"
    assert sens["signals"] and all(s["status"] in {"MEASURED", "NO_SIGNAL", "REJECTED", "UNSUPPORTED", "RESTORE_FAILED", "INVALID"} for s in sens["signals"])
    print({s["probe_id"]: s["status"] for s in sens["signals"]})
