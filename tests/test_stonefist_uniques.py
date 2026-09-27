"""CORPUS-02C follow-up: Way of the Stonefist on unique gloves (fake engine).

Real-item and real-PoB coverage: tests/integration/test_corpus02c_stonefist.py ("unique gloves").
"""

from __future__ import annotations

from typing import Any

import pytest

from exilelens.items import stonefist_uniques
from exilelens.items.stonefist import ModPair, StonefistTransformer, worse_when_larger
from exilelens.items.stonefist_rolls import BEST_ROLLS, WORST_ROLLS, rule_for

pytestmark = pytest.mark.itemcheck

EVIDENCE = {"Test Grasp": {"mods": ("UniqueA1", "UniqueKept1", "UniqueGone1", "UniqueFixed1", "UniqueSkill1"),
                           "untransformed": 1, "transformed": 1}}
MOD_LINES = {
    "UniqueA1": {"lines": ["(40-60)% increased Armour"]},
    "UniqueKept1": {"lines": ["+0.3 metres to Melee Strike Range while Unarmed"]},
    "UniqueGone1": {"lines": ["(30-50)% increased Stun Buildup"]},
    "UniqueFixed1": {"lines": ["-(20-10)% to Cold Resistance"]},
    "UniqueOther1": {"lines": ["+(20-30) to Intelligence"]},
    "UniqueMutatedVaalLife": {"lines": ["(8-12)% increased maximum Life"]},
}
PAIRS = [
    {"source_id": "UniqueA1", "target_id": "HandWrapsUniqueA1", "source_table": "Exclusive", "target_table": "Exclusive",
     "source_lines": ["(40-60)% increased Armour"], "target_lines": ["(10-15)% more Global Evasion Rating and Energy Shield"]},
    {"source_id": "UniqueFixed1", "target_id": "HandWrapsUniqueFixed1", "source_table": "Exclusive", "target_table": "Exclusive",
     "source_lines": ["-(20-10)% to Cold Resistance"], "target_lines": ["(30-50)% increased Chill Duration on you"]},
    {"source_id": "UniqueMutatedVaalLife", "target_id": "HandWrapsUniqueMutatedVaalLife", "source_table": "Exclusive",
     "target_table": "Item", "source_lines": ["(8-12)% increased maximum Life"], "target_lines": ["+(36-42) to maximum Mana"]},
    # A rare modifier: never used for a unique, and unique modifiers never for a rare.
    {"source_id": "IncreasedLife6", "target_id": "HandWrapsIncreasedLife6", "source_table": "Item", "target_table": "Item",
     "source_lines": ["+(70-84) to maximum Life"], "target_lines": ["10% less damage taken while on Low Life"]},
]
GAME_ONLY = {"removed": frozenset({"HandWrapsUniqueGone1"}), "unavailable": frozenset({"HandWrapsUniqueOther1"})}


def _rows(*lines: str, mutated: bool = False) -> list[dict[str, Any]]:
    return [{"line": line, "fractured": False, "desecrated": False, "crafted": False, "mutated": mutated} for line in lines]


class _Engine:
    def __init__(self, explicit: list[dict[str, Any]], name: str = "Test Grasp") -> None:
        self.described = {"type": "Gloves", "base_name": "Moulded Mitts", "rarity": "UNIQUE", "name": name,
                          "implicit": [], "explicit": explicit}

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "describe_item":
            return self.described
        if method == "get_mod_lines":
            if params.get("prefix"):
                return {"mods": {k: v for k, v in MOD_LINES.items() if k.startswith(params["prefix"])}}
            return {"mods": {k: MOD_LINES[k] for k in params["ids"] if k in MOD_LINES}}
        if method == "get_base_implicits":
            return {"lines": ["Has +3 to Evasion Rating per player level"]}
        if method == "rebuild_item":
            return {"item_raw": "rebuilt", "base_name": params["base_name"], "type": "Gloves"}
        raise AssertionError(method)


@pytest.fixture(autouse=True)
def _evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stonefist_uniques, "UNIQUE_GLOVE_MODS", EVIDENCE)
    monkeypatch.setattr(stonefist_uniques, "GAME_ONLY_TARGETS", GAME_ONLY)


def _transform(engine: _Engine, rule=WORST_ROLLS):
    return StonefistTransformer(PAIRS, rule).transform(engine, "raw")


def test_each_modifier_is_transformed_kept_or_removed_as_the_game_does() -> None:
    engine = _Engine(_rows("52% increased Armour", "+0.3 metres to Melee Strike Range while Unarmed",
                           "41% increased Stun Buildup", "-15% to Cold Resistance"))
    worst, best = _transform(engine), _transform(engine, BEST_ROLLS)
    assert worst.ok and worst.base_name == "Fists of Stone" and worst.bounded
    fates = {m["source_id"]: m["target_id"] for m in worst.mapped}
    assert fates == {"UniqueA1": "HandWrapsUniqueA1", "UniqueKept1": "UniqueKept1",
                     "UniqueGone1": "HandWrapsUniqueGone1", "UniqueFixed1": "HandWrapsUniqueFixed1"}
    assert [row["line"] for row in worst.explicit] == [
        "10% more Global Evasion Rating and Energy Shield",
        "+0.3 metres to Melee Strike Range while Unarmed",  # kept verbatim
        # the Stun Buildup line is gone: its transformed modifier has no displayed stat
        "50% increased Chill Duration on you",  # a longer chill on you is the worst end
    ]
    best_lines = [row["line"] for row in best.explicit]
    assert best_lines[0] == "15% more Global Evasion Rating and Energy Shield"
    assert best_lines[2] == "30% increased Chill Duration on you"
    assert worst.ranged_lines == ["#% more Global Evasion Rating and Energy Shield", "#% increased Chill Duration on you"]


def test_a_line_that_is_not_one_of_the_uniques_modifiers_is_refused() -> None:
    result = _transform(_Engine(_rows("52% increased Armour", "+25 to Intelligence")))
    assert not result.ok
    assert result.unresolved == ['Test Grasp: the line "+25 to Intelligence" is not one of the verified Test Grasp modifiers']


def test_a_modifier_whose_transformation_pob_lacks_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stonefist_uniques, "UNIQUE_GLOVE_MODS", {"Test Grasp": {"mods": ("UniqueOther1",)}})
    result = _transform(_Engine(_rows("+25 to Intelligence")))
    assert not result.ok and "Path of Building's data does not have" in result.unresolved[0]


def test_a_value_outside_pobs_older_range_is_identified_only_when_unambiguous() -> None:
    # 70% lies outside PoB's (40-60): accepted, and reported, because the template is unique.
    result = _transform(_Engine(_rows("70% increased Armour")))
    assert result.ok and result.source_values_outside_pob_data == ["70% increased Armour"]
    # Two candidate lines share the template: neither can be identified by text alone.
    assert not _transform(_Engine(_rows("70% increased Armour", "75% increased Armour"))).ok


def test_a_mutated_line_is_matched_against_pobs_mutated_modifiers() -> None:
    result = _transform(_Engine(_rows("52% increased Armour") + _rows("10% increased maximum Life", mutated=True)))
    assert result.ok
    assert {m["target_id"] for m in result.mapped} == {"HandWrapsUniqueA1", "HandWrapsUniqueMutatedVaalLife"}
    assert "+36 to maximum Mana" in [row["line"] for row in result.explicit]


def test_a_granted_skill_the_game_keeps_is_kept_verbatim() -> None:
    result = _transform(_Engine(_rows("Grants Skill: Level 20 Herald of the Royal Queen", "52% increased Armour")))
    assert result.ok and "Grants Skill: Level 20 Herald of the Royal Queen" in [row["line"] for row in result.explicit]


def test_rare_and_unique_modifiers_are_kept_apart() -> None:
    transformer = StonefistTransformer(PAIRS, WORST_ROLLS)
    assert {pair.source_id for pair in transformer.pairs} == {"IncreasedLife6"}
    assert set(transformer.unique_pairs) == {"UniqueA1", "UniqueFixed1", "UniqueMutatedVaalLife"}


@pytest.mark.parametrize(("line", "pattern", "fits"), [
    ("-15% to Cold Resistance", "-(20-10)% to Cold Resistance", True),
    ("-25% to Cold Resistance", "-(20-10)% to Cold Resistance", False),
    ("-9 to Maximum Rage", "+(-10-10) to Maximum Rage", True),
    ("+9 to Maximum Rage", "+(-10-10) to Maximum Rage", True),
    ("52% increased Armour", "(40-60)% increased Armour", True),
    ("52% increased Evasion", "(40-60)% increased Armour", False),
])
def test_signed_ranges_are_read_as_displayed(line: str, pattern: str, fits: bool) -> None:
    assert stonefist_uniques._fits(line, pattern) is fits


@pytest.mark.parametrize(("line", "worse"), [
    ("(15-25)% reduced Attack Speed", True),
    ("(30-50)% increased Chill Duration on you", True),
    ("Leech Life (15-25)% slower", True),
    ("(15-40)% reduced Mana Cost of Attacks", False),
    ("(7-9)% less damage taken while on Low Life", False),
])
def test_roll_orientation(line: str, worse: bool) -> None:
    assert worse_when_larger(line) is worse


def test_flip_rule_sets_one_line_best_and_the_rest_worst() -> None:
    pair = ModPair("S", "T", ("x",), ("(10-15)% more Global Evasion Rating and Energy Shield",
                                      "(30-50)% increased Chill Duration on you"), "", "g")
    assert rule_for("flip:#% more Global Evasion Rating and Energy Shield")(pair, []) == [15.0, 50.0]
    assert rule_for("flip:#% increased Chill Duration on you")(pair, []) == [10.0, 30.0]
