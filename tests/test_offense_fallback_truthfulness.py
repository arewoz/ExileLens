"""P0 regression: near-zero native-component fallback must not manufacture a fake
-100% "primary offense" delta, and a substituted fallback component must not let
evaluation_quality report FULL / a confident verdict.

Reproduces a real tester report: primary skill "Combat Frenzy" had no usable
offensive PoB output at all. Native damage discovery correctly measured:

    Bow Shot:      before=32830.0755  status=UNAVAILABLE (identity/output changed)
    Herald of Ice: before=1.346366913e-06  after=0  (IgniteDPS -- PoB rounding noise)
    Snipe:         before=15039.8814  after=14167.0420  (a real, small loss)

and correctly flagged damage_scope=PARTIAL / overall_damage_verdict=UNCERTAIN. The
bug: evaluation nonetheless picked the noise-sized Herald of Ice delta as
"primary_offense" (a manufactured -100%), reported evaluation_quality=FULL, and
produced verdict=MEANINGFUL_DOWNGRADE.

These tests exercise the two independent fixes directly, at the same layers the
production pipeline uses (never a text/UI-level snapshot of the bug -- see
PRE-MERGE AUDIT-style tracing in the P0 fix commit message for the full trace).
"""

from __future__ import annotations

import pytest

from poe2value.items.evaluation_outcome import (
    SCORED_RAW_FIELDS,
    EvaluationQuality,
    PublicVerdict,
    assess_quality,
)
from poe2value.items.native_metric_discovery import (
    _is_significant_offense_value,
    promote_unresolved_primary_with_component,
)
from poe2value.items.ranking import enrich_slot_comparison
from poe2value.items.slots import pob_slot_to_product

pytestmark = pytest.mark.itemcheck


# --------------------------------------------------------------------------- #
# Shared fixtures matching the tester's real report
# --------------------------------------------------------------------------- #

_BOW_SHOT = {
    "name": "Bow Shot", "label": "Bow Shot", "index": 1, "owner": "PLAYER",
    "status": "UNAVAILABLE", "before": 32830.0755, "after": None,
    "field": "TotalDPS", "reason": "COMPONENT_IDENTITY_OR_OUTPUT_CHANGED",
}
_HERALD_OF_ICE_NOISE = {
    "name": "Herald of Ice", "label": "Herald of Ice", "index": 2, "owner": "PLAYER",
    "status": "MEASURED", "before": 1.346366913e-06, "after": 0.0,
    "field": "IgniteDPS", "reason": "",
}
_SNIPE_REAL_LOSS = {
    "name": "Snipe", "label": "Snipe", "index": 3, "owner": "PLAYER",
    "status": "MEASURED", "before": 15039.8814, "after": 14167.0420,
    "field": "TotalDPS", "reason": "",
}


def _components_comparison(components: list[dict]) -> dict:
    return {
        "baseline_primary_metric": {"semantic_quantity": "UNRESOLVED"},
        "native_damage_discovery": {
            "damage_scope": "PARTIAL",
            "overall_damage_verdict": "UNCERTAIN",
            "fallback_reason": "FULL_DPS_NOT_CONFIGURED",
            "components": components,
        },
    }


def _promote(components: list[dict], *, primary_confidence: str = "low"):
    metric_profile = {"primary_offense": {"pob_field": "CombinedDPS"}}
    comparison = _components_comparison(components)
    return promote_unresolved_primary_with_component(
        metric_profile, comparison, primary_confidence=primary_confidence,
    )


# --------------------------------------------------------------------------- #
# Phase 2 -- numerical significance
# --------------------------------------------------------------------------- #


class TestNumericalSignificance:
    def test_noise_sized_value_is_not_significant(self) -> None:
        assert _is_significant_offense_value(1.346366913e-06) is False

    def test_zero_is_not_significant(self) -> None:
        assert _is_significant_offense_value(0.0) is False

    def test_none_is_not_significant(self) -> None:
        assert _is_significant_offense_value(None) is False

    def test_exactly_at_epsilon_is_not_significant(self) -> None:
        # Boundary: the same "> eps" convention offense_coverage.py already uses
        # (RESPONSE_ABS_EPS = 0.5) treats the threshold itself as not-yet-significant.
        assert _is_significant_offense_value(0.5) is False

    def test_just_above_epsilon_is_significant(self) -> None:
        assert _is_significant_offense_value(0.51) is True

    def test_a_real_small_value_is_significant(self) -> None:
        # Requirement: a genuine small-but-nonzero offensive metric must not
        # disappear because of an excessively aggressive threshold.
        assert _is_significant_offense_value(5.0) is True

    def test_large_value_is_significant(self) -> None:
        assert _is_significant_offense_value(15039.8814) is True

    def test_nan_is_not_significant(self) -> None:
        # IEEE754: any comparison with NaN is False, so "> eps" already excludes it
        # with no extra guard needed.
        assert _is_significant_offense_value(float("nan")) is False

    def test_negative_value_is_not_significant(self) -> None:
        assert _is_significant_offense_value(-5.0) is False

    def test_infinite_value_passes_this_gate_alone(self) -> None:
        # Documented gap, not a bug in this function: `inf > eps` is True under
        # IEEE754. Safe end-to-end only because `evaluation_outcome._unavailable()`
        # independently requires a finite value before quality can be FULL -- see
        # TestTruthfulnessPropagation.test_non_finite_substituted_value_is_still_caught_as_partial.
        assert _is_significant_offense_value(float("inf")) is True


class TestFallbackPercentDeltaSignificance:
    def test_noise_sized_component_never_reaches_100_percent_delta(self) -> None:
        """The exact bug: 1.346e-6 -> 0 must not become a -100% delta at all --
        the component must not even be selected as the fallback (see
        TestFallbackComponentSelection), so `percent_delta` never gets computed."""
        profile, field, confidence = _promote([_BOW_SHOT, _HERALD_OF_ICE_NOISE])
        # No PLAYER MEASURED component clears the significance bar -- Bow Shot is
        # UNAVAILABLE and Herald of Ice's own baseline is noise-sized -- so no
        # substitution happens at all, and the placeholder offense is untouched.
        assert "substituted_component" not in profile["primary_offense"]
        assert field == "CombinedDPS"
        assert confidence == "low"

    def test_genuine_large_loss_still_produces_a_real_negative_100_percent(self) -> None:
        """10000 -> 0 on a component whose baseline IS significant remains a
        real, meaningful -100% loss -- the epsilon guard must never suppress an
        actual zeroing-out of real damage."""
        big_loss = {**_SNIPE_REAL_LOSS, "before": 10000.0, "after": 0.0}
        profile, field, confidence = _promote([big_loss])
        offense = profile["primary_offense"]
        assert offense["percent_delta"] == pytest.approx(-100.0)
        assert offense["absolute_delta"] == pytest.approx(-10000.0)
        assert offense["substituted_component"]["name"] == "Snipe"


# --------------------------------------------------------------------------- #
# Phase 3 -- component fallback eligibility / selection
# --------------------------------------------------------------------------- #


class TestFallbackComponentSelection:
    def test_noise_sized_component_never_outranks_a_meaningful_one(self) -> None:
        """The exact tester scenario: Bow Shot (UNAVAILABLE), Herald of Ice
        (noise), Snipe (real, small loss) -- Snipe must win, not Herald of Ice."""
        profile, field, confidence = _promote(
            [_BOW_SHOT, _HERALD_OF_ICE_NOISE, _SNIPE_REAL_LOSS]
        )
        offense = profile["primary_offense"]
        assert offense["substituted_component"]["name"] == "Snipe"
        assert offense["label"].startswith("Snipe")
        assert field == "TotalDPS"
        assert offense["percent_delta"] == pytest.approx(-5.8035, abs=0.01)
        assert offense["current"] == pytest.approx(15039.8814)
        assert offense["candidate"] == pytest.approx(14167.0420)

    def test_noise_sized_component_alone_is_not_promoted(self) -> None:
        profile, field, confidence = _promote([_HERALD_OF_ICE_NOISE])
        assert "substituted_component" not in profile["primary_offense"]

    def test_pob_group_order_is_still_the_tiebreak_among_eligible_components(self) -> None:
        """Preserves existing semantics: among components that ARE eligible,
        selection stays deterministic PoB-group-order, not "biggest DPS"."""
        first = {**_SNIPE_REAL_LOSS, "name": "Alpha", "label": "Alpha", "index": 1, "before": 20.0, "after": 20.0}
        second = {**_SNIPE_REAL_LOSS, "name": "Beta", "label": "Beta", "index": 2, "before": 999999.0, "after": 1.0}
        profile, _, _ = _promote([first, second])
        assert profile["primary_offense"]["substituted_component"]["name"] == "Alpha"

    def test_unavailable_component_is_never_chosen(self) -> None:
        profile, field, confidence = _promote([_BOW_SHOT])
        assert "substituted_component" not in profile["primary_offense"]
        assert field == "CombinedDPS"


# --------------------------------------------------------------------------- #
# Phase 4 -- truthfulness propagation (independent of the epsilon fix)
# --------------------------------------------------------------------------- #


def _quality_comparison() -> dict:
    return {
        "pob_slot": "Weapon 1",
        "product_slot": pob_slot_to_product("Weapon 1").value,
        "baseline": {"metrics": {"Life": 1000.0}},
        "candidate": {"metrics": {"Life": 1000.0}, "item_present": True},
        "restore": {"pass": True},
    }


class TestTruthfulnessPropagation:
    def test_substituted_fallback_component_caps_quality_at_partial(self) -> None:
        comparison = _quality_comparison()
        metric_profile = {
            "primary_offense": {
                "delta_kind": "MEASURED",
                "current": 15039.8814,
                "candidate": 14167.0420,
                "availability": "available",
                "substituted_component": {
                    "name": "Snipe", "index": 3, "owner": "PLAYER", "reason": "fallback",
                },
            },
            "ehp": {"current": 1000.0, "candidate": 1000.0, "availability": "available"},
            "worst_max_hit": {"current": 100.0, "candidate": 100.0, "availability": "available"},
        }
        quality, reasons = assess_quality(
            comparison, metric_profile=metric_profile, resist={},
            primary_field="CombinedDPS", primary_confidence="high",
        )
        assert quality == EvaluationQuality.PARTIAL
        assert any(reason["code"] == "OFFENSE_FALLBACK_COMPONENT" for reason in reasons)

    def test_a_normal_measured_delta_without_substitution_stays_full(self) -> None:
        """Non-regression: an ordinary, non-fallback MEASURED delta is unaffected."""
        comparison = _quality_comparison()
        metric_profile = {
            "primary_offense": {
                "delta_kind": "MEASURED",
                "current": 15039.8814,
                "candidate": 14167.0420,
                "availability": "available",
            },
            "ehp": {"current": 1000.0, "candidate": 1000.0, "availability": "available"},
            "worst_max_hit": {"current": 100.0, "candidate": 100.0, "availability": "available"},
        }
        quality, reasons = assess_quality(
            comparison, metric_profile=metric_profile, resist={},
            primary_field="CombinedDPS", primary_confidence="high",
        )
        assert quality == EvaluationQuality.FULL
        assert reasons == []

    def test_non_finite_substituted_value_is_still_caught_as_partial(self) -> None:
        """Pre-merge-audit finding, locked in as a regression: `_is_significant_offense_value`
        alone does not exclude +inf (`inf > RESPONSE_ABS_EPS` is True under IEEE754), so a
        corrupted/non-finite PoB output could in principle pass the significance gate. This
        is currently safe ONLY because `_unavailable()` below independently requires both
        sides of the offense delta to be finite (`math.isfinite`) before quality can be
        FULL. If that independent check is ever weakened or removed, this test must fail.
        """
        comparison = _quality_comparison()
        metric_profile = {
            "primary_offense": {
                "delta_kind": "MEASURED",
                "current": float("inf"),
                "candidate": 0.0,
                "availability": "available",
                "substituted_component": {
                    "name": "Corrupted", "index": 9, "owner": "PLAYER", "reason": "fallback",
                },
            },
            "ehp": {"current": 1000.0, "candidate": 1000.0, "availability": "available"},
            "worst_max_hit": {"current": 100.0, "candidate": 100.0, "availability": "available"},
        }
        quality, reasons = assess_quality(
            comparison, metric_profile=metric_profile, resist={},
            primary_field="CombinedDPS", primary_confidence="high",
        )
        assert quality == EvaluationQuality.PARTIAL
        codes = {reason["code"] for reason in reasons}
        assert codes & {"OFFENSE_UNAVAILABLE", "OFFENSE_FALLBACK_COMPONENT"}


# --------------------------------------------------------------------------- #
# End-to-end: the full tester scenario through the real pipeline
# --------------------------------------------------------------------------- #


def _raw(**overrides: float) -> dict[str, float]:
    values: dict[str, float] = {field: 100.0 for field in SCORED_RAW_FIELDS}
    values.update(
        {
            "CombinedDPS": 0.0,
            "TotalEHP": 1_000.0,
            "Life": 500.0,
            "EnergyShield": 100.0,
            "PhysicalMaximumHitTaken": 100.0,
            "FireMaximumHitTaken": 100.0,
            "ColdMaximumHitTaken": 100.0,
            "LightningMaximumHitTaken": 100.0,
            "ChaosMaximumHitTaken": 100.0,
            "MovementSpeedMod": 1.0,
            "FireResist": 75.0,
            "ColdResist": 75.0,
            "LightningResist": 75.0,
            "ChaosResist": 0.0,
            "FireResistMax": 75.0,
            "ColdResistMax": 75.0,
            "LightningResistMax": 75.0,
            "ChaosResistMax": 75.0,
        }
    )
    values.update(overrides)
    return values


def test_tester_scenario_end_to_end_is_no_longer_a_confident_downgrade() -> None:
    """The full reported bug, through the real ranking pipeline: a bow whose
    resolved primary skill (Combat Frenzy) has no usable offense output at all,
    with native discovery finding Bow Shot unavailable, Herald of Ice noise-sized,
    and Snipe a real small loss. Must land on a PARTIAL/UNCERTAIN outcome that
    reflects Snipe's real (small) loss -- never a manufactured MEANINGFUL_DOWNGRADE
    driven by Herald of Ice's noise-sized -100%.
    """
    slot = "Weapon 1"
    comparison = {
        "pob_slot": slot,
        "product_slot": pob_slot_to_product(slot).value,
        "baseline": {"metrics": _raw()},
        "candidate": {"metrics": _raw(), "item_present": True},
        "restore": {"pass": True},
        "baseline_primary_metric": {"semantic_quantity": "UNRESOLVED"},
        "native_damage_discovery": {
            "damage_scope": "PARTIAL",
            "overall_damage_verdict": "UNCERTAIN",
            "fallback_reason": "FULL_DPS_NOT_CONFIGURED",
            "components": [_BOW_SHOT, _HERALD_OF_ICE_NOISE, _SNIPE_REAL_LOSS],
        },
    }

    result = enrich_slot_comparison(
        comparison, primary_field="CombinedDPS", primary_confidence="low",
    )

    offense = result["metric_profile"]["primary_offense"]
    assert offense["label"].startswith("Snipe")
    assert offense["percent_delta"] == pytest.approx(-5.8035, abs=0.01)

    outcome = result["evaluation_outcome"]
    assert outcome["evaluation_quality"] == EvaluationQuality.PARTIAL.value
    assert outcome["verdict"] == PublicVerdict.UNCERTAIN.value
    assert outcome["verdict"] != PublicVerdict.MEANINGFUL_DOWNGRADE.value
