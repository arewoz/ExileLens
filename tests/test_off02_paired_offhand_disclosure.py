"""OFF-02 regression: paired offhand removal is named on both item-check surfaces."""

from __future__ import annotations

import pytest

from poe2value.items.compact_tooltip import replacing_line
from poe2value.items.more_info import build_more_info

pytestmark = pytest.mark.itemcheck


def _paired_weapon_model() -> dict[str, object]:
    outcome = {
        "verdict_label": "SIDEGRADE",
        "replacement_slot": "Weapon 1",
        "replacing_item": "Ashen Staff",
    }
    return {
        "evaluation_outcome": outcome,
        "replacement_choices": [
            {
                "slot": "Weapon 1",
                "selected": True,
                "best": True,
                "replacing_item": "Ashen Staff",
            },
            {
                "slot": "Weapon 2",
                "replacing_item": "Dawn Guard",
            },
        ],
        "paired_offhand_cleared": True,
        "paired_offhand_slot": "Weapon 2",
        "primary_metric": {},
        "native_damage_discovery": {},
    }


def test_paired_offhand_name_is_disclosed_in_compact_tooltip_and_more_info() -> None:
    model = _paired_weapon_model()

    assert replacing_line(model) == "Best: Weapon 1 — Ashen Staff (also removes Dawn Guard)"

    more_info = build_more_info(model)
    verdict = next(section for section in more_info["sections"] if section["id"] == "verdict_header")
    assert "Replacing: Ashen Staff · Weapon 1 (also removes Dawn Guard)" in verdict["lines"]
