"""M5.2 Build Sensitivity Profile: pure normalisation of existing probe results."""

from __future__ import annotations

import time

import pytest

from exilelens.analysis.identity import AnalysisBaseline
from exilelens.analysis.sensitivity import (
    SCHEMA_VERSION,
    build_sensitivity,
    is_sensitivity_stale,
    profile_independent_sensitivity,
)

pytestmark = pytest.mark.itemcheck

BASELINE = {
    "build_path": "b.xml", "build_name": "T", "loadout": "L", "item_set": "1", "context": "MAP",
    "profile": "BALANCED", "generation": 2, "fingerprint": "hash1",
}


def _entry(key, absolute, percent=None, available=True):
    if not available:
        return {"key": key, "availability": "missing", "absolute_delta": None, "percent_delta": None}
    return {"key": key, "availability": "available", "absolute_delta": absolute, "percent_delta": percent}


def _probe(probe_id="CAST_SPEED", status="ok", magnitude=10.0, score=4.2, **extra):
    base = {
        "probe_id": probe_id, "status": status, "family": "offense", "display_name": probe_id.title(),
        "magnitude": magnitude, "unit": "percent", "line": f"+{magnitude}", "confidence": "HIGH",
    }
    if status == "ok":
        base.update(
            offense_percent=7.8, ehp_percent=0.0, score_delta=score, marginal_value_per_unit=round(score / magnitude, 4),
            metric_profile={
                "primary_offense": _entry("primary_offense", 780.0, 7.8),
                "ehp": _entry("ehp", 0.0, 0.0),
                "energy_shield": _entry("energy_shield", None, available=False),
                "fire_res": _entry("fire_res", 0.0),
            },
            warnings=[], breakpoints=[],
        )
    base.update(extra)
    return base


def _result(probes, *, offense_confidence="HIGH", profile="BALANCED"):
    return {
        "baseline": {**BASELINE, "profile": profile},
        "audit": {"primary_field": "CombinedDPS", "primary_confidence": offense_confidence.lower()},
        "build_fingerprint": {"offense": {
            "owner": "PLAYER", "metric": "CombinedDPS", "scope": "PRIMARY_SKILL",
            "provenance": "POB_PRIMARY_SKILL", "confidence": offense_confidence,
        }},
        "global_probes": probes,
    }


def _signal(profile, probe_id):
    return next(s for s in profile["signals"] if s["probe_id"] == probe_id)


def test_measured_offense_signal_keeps_magnitude_response_and_separates_score() -> None:
    sens = build_sensitivity(_result([_probe()]))
    sig = _signal(sens, "CAST_SPEED")
    assert sens["schema_version"] == SCHEMA_VERSION == 1
    assert sig["status"] == "MEASURED" and sig["probe"]["magnitude"] == 10.0 and sig["family"] == "offense"
    assert sig["response"]["offense"] == {"absolute": 780.0, "evidence": "MEASURED", "percent": 7.8, "confidence": "HIGH"}
    assert "energy_shield" not in sig["response"]  # unavailable axes are omitted, never a fake 0
    assert sig["response_per_unit"] == {"evidence": "DERIVED", "offense_percent_per_unit": 0.78, "ehp_percent_per_unit": 0.0}
    assert sig["profile_dependent"]["score_delta"] == 4.2
    assert "score_delta" not in sig["response"]["offense"] and "score_delta" not in sig


def test_defensive_and_attribute_probes_record_the_actual_multi_axis_response() -> None:
    es = _probe("ENERGY_SHIELD", magnitude=50.0, family="defense",
                metric_profile={"energy_shield": _entry("energy_shield", 50.0, 1.9), "ehp": _entry("ehp", 400.0, 1.9),
                                "worst_max_hit": _entry("worst_max_hit", 90.0, 1.1)})
    intel = _probe("INTELLIGENCE", magnitude=20.0, family="utility",
                   metric_profile={"primary_offense": _entry("primary_offense", 10.0, 2.3),
                                   "energy_shield": _entry("energy_shield", 300.0, 3.4), "mana": _entry("mana", 20.0, 2.0)})
    sens = build_sensitivity(_result([es, intel]))
    assert {"energy_shield", "ehp", "max_hit"} <= set(_signal(sens, "ENERGY_SHIELD")["response"])
    attr = _signal(sens, "INTELLIGENCE")
    assert attr["family"] == "utility"  # the intervention family, not a verdict on what it affects
    assert {"offense", "energy_shield", "mana"} <= set(attr["response"])


def test_failure_statuses_stay_distinct_and_carry_no_response() -> None:
    probes = [_probe("A", "NO_SIGNAL"), _probe("B", "UNSUPPORTED_PROBE"), _probe("C", "REJECTED"),
              _probe("D", "RESTORE_FAILED"), _probe("E", "INVALID_PROBE")]
    sens = build_sensitivity(_result(probes))
    assert {s["probe_id"]: s["status"] for s in sens["signals"]} == {
        "A": "NO_SIGNAL", "B": "UNSUPPORTED", "C": "REJECTED", "D": "RESTORE_FAILED", "E": "INVALID"}
    assert all("response" not in s and s["confidence"] == "UNSUPPORTED" for s in sens["signals"])
    counts = sens["coverage"]["counts"]
    assert counts["NO_SIGNAL"] == counts["UNSUPPORTED"] == counts["REJECTED"] == counts["RESTORE_FAILED"] == counts["INVALID"] == 1
    assert counts["MEASURED"] == 0 and sorted(sens["coverage"]["not_measured"]) == ["A", "B", "C", "D", "E"]


def test_breakpoints_are_kept_separately_from_marginal_response() -> None:
    default = _probe("FIRE_RES", magnitude=20.0, family="defense", breakpoints=[{"code": "CAP_REACHED", "element": "fire"}])
    exact = _probe("FIRE_RES", magnitude=13.0, family="defense", breakpoint_exact=True, CAP_REACHED_AT=13)
    sig = _signal(build_sensitivity(_result([default, exact])), "FIRE_RES")
    kinds = [(b["kind"], b.get("event"), b.get("required_increment")) for b in sig["breakpoints"]]
    assert ("RESISTANCE_CAP", "CAP_REACHED", None) in kinds and ("RESISTANCE_CAP", None, 13.0) in kinds
    assert sig["probe"]["magnitude"] == 20.0  # the exact probe did not replace the standard increment


def test_existing_nonlinear_samples_are_preserved_not_extended() -> None:
    probes = [
        _probe(magnitude=10.0),
        {**_probe(magnitude=5.0, score=2.0), "nonlinear_sample": True},
        {**_probe(magnitude=20.0, score=9.0), "nonlinear_sample": True},
        {"probe_id": "CAST_SPEED", "status": "curve", "linearity": "NON_LINEAR", "samples": []},
    ]
    sig = _signal(build_sensitivity(_result(probes)), "CAST_SPEED")
    assert [s["magnitude"] for s in sig["samples"]] == [5.0, 10.0, 20.0]
    assert sig["profile_dependent"]["linearity"] == "NON_LINEAR"  # existing, score-based classification
    assert _signal(build_sensitivity(_result([_probe()])), "CAST_SPEED")["profile_dependent"]["linearity"] == "UNKNOWN"


def test_low_confidence_offense_is_not_upgraded() -> None:
    sig = _signal(build_sensitivity(_result([_probe()], offense_confidence="LOW")), "CAST_SPEED")
    assert sig["response"]["offense"]["confidence"] == "LOW"  # M5.5: axis-aware; the signal keeps the probe confidence
    assert _signal(build_sensitivity(_result([_probe()])), "CAST_SPEED")["confidence"] == "HIGH"


def test_profile_change_alters_only_profile_dependent_fields() -> None:
    balanced = build_sensitivity(_result([_probe(score=4.2)]))
    mapping = build_sensitivity(_result([_probe(score=9.9)], profile="MAPPING"))
    assert _signal(mapping, "CAST_SPEED")["profile_dependent"]["score_delta"] == 9.9
    assert balanced != mapping
    assert profile_independent_sensitivity(balanced) == profile_independent_sensitivity(mapping)
    assert not is_sensitivity_stale(balanced, AnalysisBaseline(**{**BASELINE, "profile": "MAPPING"}))


def test_baseline_identity_invalidation() -> None:
    sens = build_sensitivity(_result([_probe()]))
    assert sens["identity"]["baseline_fingerprint"] == "hash1"
    for change in ({"fingerprint": "x"}, {"generation": 3}, {"loadout": "L2"}, {"item_set": "2"}, {"context": "BOSS"}, {"build_path": "o.xml"}):
        assert is_sensitivity_stale(sens, AnalysisBaseline(**{**BASELINE, **change}))
    assert not is_sensitivity_stale(sens, AnalysisBaseline(**BASELINE))


def test_no_universal_cross_family_scalar_and_construction_is_cheap_and_pure() -> None:
    probes = [_probe(), _probe("LIFE", magnitude=50.0, family="defense")]
    result = _result(probes)
    started = time.perf_counter()
    sens = build_sensitivity(result)
    assert (time.perf_counter() - started) * 1000 < 50
    assert not any(key in sens for key in ("score", "sensitivity_score", "rank", "ranking", "priority"))
    assert not any(k in s for s in sens["signals"] for k in ("score", "rank", "importance", "priority"))
    assert all("profile_dependent" in s for s in sens["signals"])
    assert result["global_probes"] == probes  # input untouched; no engine is even available to call
