"""R4: refusal and slot copy: a jewel with no evaluable socket is refused for the true reason, raw jewel node ids never reach player text, and the weapon-layout refusal says what it means."""

from __future__ import annotations

import pytest

from exilelens.errors import NoCompatibleSlot
from exilelens.items.evaluation import jewel_no_compatible_slot

pytestmark = pytest.mark.itemcheck


def test_no_allocated_socket_is_its_own_reason() -> None:
    error = jewel_no_compatible_slot(0, 0)
    assert isinstance(error, NoCompatibleSlot)
    assert error.code == "NO_COMPATIBLE_SLOT"
    assert "no allocated jewel sockets" in str(error)
    assert error.details == {"allocated_jewel_socket_count": 0, "excluded_connectivity_risky_socket_count": 0}


def test_plain_incompatibility_is_reported_when_every_socket_was_evaluable() -> None:
    error = jewel_no_compatible_slot(4, 0)
    assert "not compatible with any allocated jewel socket" in str(error)
    assert "safely" not in str(error)


@pytest.mark.parametrize("allocated, excluded", [(1, 1), (3, 3)])
def test_all_sockets_excluded_for_connectivity_is_not_called_incompatible(allocated: int, excluded: int) -> None:
    """The sockets exist and were never checked: saying the jewel is incompatible with them would be false."""
    error = jewel_no_compatible_slot(allocated, excluded)
    assert "not compatible" not in str(error)
    assert "cannot be evaluated safely" in str(error)
    assert error.details["excluded_connectivity_risky_socket_count"] == excluded


def test_partially_excluded_sockets_are_disclosed_in_the_refusal() -> None:
    error = jewel_no_compatible_slot(4, 1)
    assert "evaluated safely" in str(error)
    assert "1 socket(s) were skipped" in str(error)
    assert error.details == {"allocated_jewel_socket_count": 4, "excluded_connectivity_risky_socket_count": 1}


# ------------------------------------------------------------------ jewel copy: raw tree-node ids are never player copy


def _jewel_comparison(node_id: int, name: str, *, empty: bool = False, verdict: str = "SIDEGRADE") -> dict:
    return {
        "pob_slot": f"Jewel {node_id}",
        "baseline_item": {"name": "" if empty else name, "empty": empty},
        "evaluation_outcome": {"verdict": verdict, "final_score": 50.0},
    }


def test_best_slot_label_names_the_jewel_replaced_not_the_socket_node_id() -> None:
    from exilelens.items.best_slot import best_slot_label

    assert best_slot_label(_jewel_comparison(55190, "Megalomaniac, Diamond")) == "Replace Megalomaniac, Diamond"
    assert best_slot_label(_jewel_comparison(55190, "", empty=True)) == "Equip to empty jewel socket"
    assert best_slot_label({"pob_slot": "Jewel 55190", "baseline_item": {}}) == "Replace jewel"
    # Equipment slots are unchanged.
    assert best_slot_label({"pob_slot": "Ring 1", "baseline_item": {"name": "x"}}) == "Replace Ring 1"


def test_slot_options_line_reads_socket_ordinals_for_jewels_and_pob_names_for_equipment() -> None:
    from exilelens.items.presentation import _slot_options

    result = {
        "slot_comparisons": [_jewel_comparison(55190, "Megalomaniac, Diamond"), _jewel_comparison(2491, "Heart of the Well, Diamond", verdict="TRADEOFF")],
        "recommendation": {"pob_slot": "Jewel 55190"},
        "failed_slot_outcomes": [],
    }
    line = _slot_options(result, {})["compact_line"]
    assert line == "Socket 1: SIDEGRADE · Socket 2: TRADEOFF"
    ring = {
        "slot_comparisons": [{**_jewel_comparison(1, "x"), "pob_slot": "Ring 1"}, {**_jewel_comparison(1, "x"), "pob_slot": "Ring 2"}],
        "recommendation": {"pob_slot": "Ring 1"},
        "failed_slot_outcomes": [],
    }
    assert _slot_options(ring, {})["compact_line"] == "Ring 1: SIDEGRADE · Ring 2: SIDEGRADE"


def test_baseline_line_and_compared_against_never_carry_a_jewel_node_id() -> None:
    """`baseline_line` ("vs <item> · <slot>") used to end in "Jewel 55190" and an empty socket read "Empty Jewel 11184 Slot"."""
    from exilelens.items.presentation import build_presentation

    def result(comparison: dict) -> dict:
        outcome = {"verdict": "SIDEGRADE", "final_score": 50.0, "evaluation_quality": "FULL"}
        row = {**comparison, "evaluation_outcome": outcome, "product_slot": comparison["pob_slot"], "verdict": "SIDEGRADE"}
        return {"recommendation": row, "slot_comparisons": [row], "pob_parse": {"item": {}}, "raw_input": {}}

    occupied = build_presentation(result(_jewel_comparison(55190, "Megalomaniac, Diamond")))
    assert occupied["baseline_line"] == "vs Megalomaniac, Diamond"
    assert occupied["compared_against"]["slot"] == ""
    empty = build_presentation(result(_jewel_comparison(11184, "", empty=True)))
    assert empty["baseline_line"] == "vs Empty jewel socket"
    assert "11184" not in empty["baseline_line"] and "11184" not in empty["pob_baseline_label"]
    ring = build_presentation(result({"pob_slot": "Ring 1", "baseline_item": {"name": "Band, Ring", "empty": False}}))
    assert ring["baseline_line"] == "vs Band, Ring · Ring 1"


def test_layout_refusal_says_what_it_means_and_keeps_unknown_reasons_verbatim() -> None:
    from exilelens.items.evaluation import weapon_layout_refusal_message

    off_hand = weapon_layout_refusal_message("off-hand item is not compatible with the current weapon layout")
    assert "off-hand item can't be equipped with the main-hand weapon" in off_hand and "Change the weapon" in off_hand
    assert "current weapon layout" not in off_hand
    assert "two-handed weapon can't be equipped" in weapon_layout_refusal_message("two-hand weapon is not compatible with the current weapon layout")
    assert weapon_layout_refusal_message("something else") == "something else"
    assert weapon_layout_refusal_message(None) == "unsupported equipment layout"
