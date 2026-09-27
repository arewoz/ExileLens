"""CORPUS-02C: unit coverage for the item-base-transform (Way of the Stonefist) guard."""

from __future__ import annotations

import pytest

from exilelens.items.baseline_item import unmodeled_item_transform
from exilelens.items.evaluation_outcome import EvaluationQuality, assess_quality

pytestmark = pytest.mark.itemcheck

STONEFIST = [{"node": "Way of the Stonefist", "slot": "Gloves", "transformed_base": "Fists of Stone", "modeled": False}]


def _items(baseline_base: str, candidate_base: str, *, empty: bool = False) -> tuple[dict, dict]:
    return {"base_type": baseline_base, "empty": empty}, {"base_type": candidate_base, "pob_parsed": {}}


@pytest.mark.parametrize(
    ("transforms", "slot", "baseline", "candidate", "empty", "flagged"),
    [
        (STONEFIST, "Gloves", "Runeforged Fists of Stone", "Vaal Gloves", False, True),
        (STONEFIST, "Gloves", "Vaal Gloves", "Runeforged Fists of Stone", False, True),
        (STONEFIST, "Gloves", "Vaal Gloves", "Plate Gauntlets", False, True),
        (STONEFIST, "Gloves", "Runeforged Fists of Stone", "Fists of Stone", False, False),
        (STONEFIST, "Gloves", "", "Fists of Stone", True, False),
        (STONEFIST, "Ring 1", "Gold Ring", "Amethyst Ring", False, False),
        ([], "Gloves", "Vaal Gloves", "Plate Gauntlets", False, False),
        (None, "Gloves", "Vaal Gloves", "Plate Gauntlets", False, False),
    ],
)
def test_guard_flags_only_glove_comparisons_that_are_not_like_for_like(
    transforms, slot, baseline, candidate, empty, flagged,
) -> None:
    baseline_item, candidate_item = _items(baseline, candidate, empty=empty)
    result = unmodeled_item_transform(transforms, slot, baseline_item, candidate_item)
    assert (result is not None) is flagged
    if flagged:
        assert result["code"] == "ITEM_TRANSFORM_UNMODELED" and result["node"] == "Way of the Stonefist"


def test_guard_does_not_trust_a_pob_modelling_claim() -> None:
    """PR #2350-style modelling is unvalidated; the guard still applies and says so."""
    modeled = [{**STONEFIST[0], "modeled": True}]
    result = unmodeled_item_transform(modeled, "Gloves", *_items("Fists of Stone", "Vaal Gloves"))
    assert result is not None and result["pob_modeled"] is True


@pytest.mark.parametrize("pob_modeled", [False, True])
def test_flagged_comparison_is_unsupported_quality(pob_modeled: bool) -> None:
    comparison = {
        "pob_slot": "Gloves",
        "baseline": {"metrics": {"CombinedDPS": 100.0}},
        "candidate": {"metrics": {"CombinedDPS": 50.0}},
        "restore": {"pass": True},
        "unmodeled_item_transform": {
            "code": "ITEM_TRANSFORM_UNMODELED", "node": "Way of the Stonefist", "slot": "Gloves",
            "transformed_base": "Fists of Stone", "pob_modeled": pob_modeled,
        },
    }
    quality, reasons = assess_quality(comparison, metric_profile={}, resist={})
    assert quality == EvaluationQuality.UNSUPPORTED
    assert [reason["code"] for reason in reasons] == ["ITEM_TRANSFORM_UNMODELED"]
    assert "Way of the Stonefist" in reasons[0]["detail"]
    assert ("not validated" in reasons[0]["detail"]) is pob_modeled
