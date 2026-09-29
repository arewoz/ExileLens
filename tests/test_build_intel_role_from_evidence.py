"""Regression coverage for ``_role_from_evidence`` classification.

Threshold events (build fixes, hard breaks) are decided inside the events loop and
return immediately; the function's final fall-through carries no threshold relation.
An earlier revision kept an unreachable ``if threshold_relation:`` branch after
``del reasons`` (a latent NameError, never reachable because ``threshold_relation``
was never assigned). These tests pin the established classifications.
"""

from __future__ import annotations

import pytest

from exilelens.items.build_intel.models import AxisDelta, ThresholdEvent
from exilelens.items.build_intel.relevance import _role_from_evidence

pytestmark = pytest.mark.itemcheck


def _classify(family="life", kind="DAMAGE", axes=None, thresholds=None):
    return _role_from_evidence(
        family=family, kind=kind, axes=axes or {}, thresholds=thresholds or [], resist={}, offense_zero=False,
    )


def _event(**kwargs) -> ThresholdEvent:
    base = dict(code="RES_CAP_REACHED", metric="fire_res", before=60, after=75, threshold=75,
                direction="UP", severity="HIGH")
    return ThresholdEvent(**{**base, **kwargs})


def test_a_matching_build_fix_event_is_core_with_full_strength() -> None:
    role, reasons, relation, strength = _classify(family="fire_res", thresholds=[_event(is_build_fix=True)])
    assert (role, reasons, relation, strength) == ("CORE", ["RES_CAP_REACHED"], "RES_CAP_REACHED", 1.0)


def test_a_matching_hard_break_event_is_harmful() -> None:
    role, reasons, relation, strength = _classify(
        family="fire_res", thresholds=[_event(code="RES_CAP_LOST", is_hard_break=True)],
    )
    assert (role, reasons, relation, strength) == ("HARMFUL", ["RES_CAP_LOST"], "RES_CAP_LOST", -1.0)


def test_an_event_for_another_family_does_not_classify_the_contribution() -> None:
    result = _classify(family="life", thresholds=[_event(is_build_fix=True)])
    assert result == ("NEUTRAL", ["NO_MEASURED_IMPACT"], "", 0.0)


@pytest.mark.parametrize("kind", ["DAMAGE", "DEFENCE", "RESOURCE", "RECOVERY", "ENABLER", "UTILITY"])
def test_no_measured_impact_falls_through_to_neutral(kind: str) -> None:
    axes = {"OFFENSE": AxisDelta(axis="OFFENSE", percent_delta=0.2, absolute_delta=0.0)}
    assert _classify(kind=kind, axes=axes) == ("NEUTRAL", ["NO_MEASURED_IMPACT"], "", 0.0)


def test_a_measured_damage_gain_keeps_its_classification() -> None:
    axes = {"OFFENSE": AxisDelta(axis="OFFENSE", percent_delta=9.0)}
    role, reasons, relation, strength = _classify(kind="DAMAGE", axes=axes)
    assert (role, reasons, relation) == ("CORE", ["OFFENSE_GAIN"], "DAMAGE") and strength == 0.75
