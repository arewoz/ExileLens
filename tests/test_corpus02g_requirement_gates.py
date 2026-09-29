"""CORPUS-02G: attribute requirement gate against PoB's real output names (Str / ReqStr)."""

from __future__ import annotations

import pytest

from exilelens.items.requirement_gates import attribute_requirement_warnings

pytestmark = pytest.mark.itemcheck


def _codes(before: dict, after: dict) -> list[str]:
    return [warning["code"] for warning in attribute_requirement_warnings(before, after)]


def test_reads_pobs_req_field_names() -> None:
    before = {"Str": 200.0, "ReqStr": 157.0}
    assert _codes(before, {"Str": 100.0, "ReqStr": 157.0}) == ["ATTRIBUTE_REQUIREMENT_LOST"]
    assert _codes(before, {"Str": 300.0, "ReqStr": 157.0}) == []


def test_a_new_higher_requirement_is_a_loss() -> None:
    assert _codes({"Dex": 150.0, "ReqDex": 140.0}, {"Dex": 150.0, "ReqDex": 180.0}) == ["ATTRIBUTE_REQUIREMENT_LOST"]


def test_a_shortfall_the_build_already_had_is_not_caused_by_the_candidate() -> None:
    before = {"Int": 100.0, "ReqInt": 120.0}
    assert _codes(before, {"Int": 100.0, "ReqInt": 120.0}) == []
    assert _codes(before, {"Int": 90.0, "ReqInt": 120.0}) == ["ATTRIBUTE_REQUIREMENT_LOST"]
    assert _codes(before, {"Int": 130.0, "ReqInt": 120.0}) == ["ATTRIBUTE_REQUIREMENT_REACHED"]
