"""Real-PoB regression coverage for "Ignore socketed modifiers in Item Check".

Uses the public corpus build ``core04_bow_quiver.xml``, whose ``Weapon 1`` is
already equipped with a real 3-rune two-hand bow ("Pandemonium Breeze") -- the
same shape of fixture the product brief's own worked example is drawn from
(``fixtures/builds/public_corpus/core04_bow_quiver.xml``, item id 11/19).
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from exilelens.errors import EngineError
from exilelens.items.evaluation import evaluate_item
from exilelens.items.socket_normalize import strip_socketed_modifiers

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_bow_quiver.xml"
RING_BUILD = ROOT / "fixtures" / "builds" / "core04_player_ring.xml"
SLOT = "Weapon 1"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _equipped_raw(path: Path, slot_name: str) -> str:
    root = ElementTree.parse(path).getroot()
    items = root.find("Items")
    assert items is not None
    raw = {item.get("id"): (item.text or "").strip() for item in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(entry for entry in items.findall("ItemSet") if entry.get("id") == active)
    item_id = next(entry.get("itemId") for entry in item_set.findall("Slot") if entry.get("name") == slot_name)
    assert item_id and item_id != "0"
    return raw[item_id]


# The real "Pandemonium Breeze" equipped in Weapon 1: three runes, all four of
# whose granted lines are counted inside "Implicits: 4".
_BASELINE_RUNE_BOW = _equipped_raw(BUILD, SLOT)

# Same base item and every non-rune mod line unchanged; only the socketed runes
# (and the lines they grant) differ -- the exact scenario the brief describes:
# "The equipped item may have a completely different rune ... its socketed
# modifier must also be removed for the same comparison."
_CANDIDATE_DIFFERENT_RUNE_BOW = """Rarity: RARE
Pandemonium Breeze
Warmonger Bow
Unique ID: 0000000000000000000000000000000000000000000000000000000000000013
Item Level: 82
Quality: 30
Sockets: S S S
Rune: Perfect Storm Rune
Rune: Perfect Storm Rune
Rune: Perfect Storm Rune
LevelReq: 77
Implicits: 4
{enchant}{rune}Gain 12% of Damage as Extra Lightning Damage
{enchant}{rune}70% increased Spell Damage
{enchant}{rune}Bonded: Break Armour on Critical Hit with Spells equal to 24% of Physical Damage dealt
{enchant}{rune}Bonded: 30% increased Magnitude of Shock you inflict
{fractured}+5% to Critical Hit Chance
255% increased Physical Damage
+176 to Accuracy Rating
+25% to Critical Damage Bonus
+4 to Level of all Projectile Skills
+198% Surpassing chance to fire an additional Arrow
{desecrated}Adds 37 to 65 Physical Damage"""

# The same candidate with no sockets/runes at all.
_CANDIDATE_NO_RUNE_BOW = """Rarity: RARE
Pandemonium Breeze
Warmonger Bow
Unique ID: 0000000000000000000000000000000000000000000000000000000000000013
Item Level: 82
Quality: 30
LevelReq: 77
Implicits: 0
{fractured}+5% to Critical Hit Chance
255% increased Physical Damage
+176 to Accuracy Rating
+25% to Critical Damage Bonus
+4 to Level of all Projectile Skills
+198% Surpassing chance to fire an additional Arrow
{desecrated}Adds 37 to 65 Physical Damage"""


def _weapon1_comparison(result: dict) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == SLOT)


def _stripped_build(tmp_path: Path) -> Path:
    """A copy of BUILD whose equipped Weapon 1 has had rune/bonded lines removed.

    An independent (non-Lua, non-override) path to the "manually unsocketed"
    baseline: plain XML text substitution plus the default (no override)
    evaluation pipeline, exactly like every other build fixture in this suite.
    """
    original_text = BUILD.read_text(encoding="utf-8")
    # Extracted from the raw XML source directly (not via ElementTree, whose text
    # decodes entities like ``&apos;`` -- the stripper's output is substituted back
    # into this same raw source, so the search key must match it byte-for-byte).
    match = re.search(r'(?<=<Item id="19">\n)(.*?)(?=\n\t{3}<ModRange)', original_text, re.S)
    assert match, "fixture layout changed: item id=19 (Weapon 1) not found as expected"
    item_19_raw = match.group(1)
    stripped = strip_socketed_modifiers(item_19_raw)
    assert stripped.changed is True
    new_text = original_text[: match.start()] + stripped.text + original_text[match.end() :]
    out = tmp_path / "core04_bow_quiver_unsocketed_weapon1.xml"
    out.write_text(new_text, encoding="utf-8")
    return out


def test_setting_off_matches_unmodified_behavior(real_pob_engine) -> None:
    """Requirement 1: OFF (the default) leaves Item Check byte-for-byte the same."""
    default = evaluate_item(_CANDIDATE_DIFFERENT_RUNE_BOW, real_pob_engine, build_path=str(BUILD))
    explicit_off = evaluate_item(
        _CANDIDATE_DIFFERENT_RUNE_BOW,
        real_pob_engine,
        build_path=str(BUILD),
        item_check_pro={"ignore_socketed_mods": False},
    )
    row_default = _weapon1_comparison(default)
    row_off = _weapon1_comparison(explicit_off)
    assert row_default["baseline"]["metrics"] == row_off["baseline"]["metrics"]
    assert row_default["candidate"]["metrics"] == row_off["candidate"]["metrics"]
    assert row_default["delta"] == row_off["delta"]
    assert row_off["restore"]["pass"] is True
    # The real equipped item keeps its own rune contribution when the setting is off.
    assert default["socket_normalization"]["enabled"] is False


def test_setting_on_normalizes_both_sides_like_manually_unsocketed_items(real_pob_engine, tmp_path) -> None:
    """Requirements 2 & 3: ON strips both sides, matching hand-unsocketed items."""
    on = evaluate_item(
        _CANDIDATE_DIFFERENT_RUNE_BOW,
        real_pob_engine,
        build_path=str(BUILD),
        item_check_pro={"ignore_socketed_mods": True},
    )
    row_on = _weapon1_comparison(on)
    assert on["socket_normalization"]["enabled"] is True
    assert on["socket_normalization"]["candidate_normalized"] is True
    assert on["socket_normalization"]["baseline_normalized_slots"] == [SLOT]
    assert row_on["restore"]["pass"] is True

    # Independent gold standard: a build whose Weapon 1 was hand-unsocketed via
    # plain XML text substitution (no override machinery at all), checked against
    # a hand-unsocketed candidate, with the setting left at its OFF default.
    stripped_build = _stripped_build(tmp_path)
    candidate_stripped = strip_socketed_modifiers(_CANDIDATE_DIFFERENT_RUNE_BOW)
    assert candidate_stripped.changed is True
    gold = evaluate_item(candidate_stripped.text, real_pob_engine, build_path=str(stripped_build))
    row_gold = _weapon1_comparison(gold)

    for field in ("CombinedDPS", "TotalEHP", "Life"):
        if field in row_on["baseline"]["metrics"] and field in row_gold["baseline"]["metrics"]:
            assert row_on["baseline"]["metrics"][field] == pytest.approx(
                row_gold["baseline"]["metrics"][field], rel=1e-6, abs=1e-6,
            )
            assert row_on["candidate"]["metrics"][field] == pytest.approx(
                row_gold["candidate"]["metrics"][field], rel=1e-6, abs=1e-6,
            )


def test_rune_on_only_one_side_is_ignored_correctly(real_pob_engine) -> None:
    """Requirement 4: a rune on only the equipped side is stripped just the same."""
    on = evaluate_item(
        _CANDIDATE_NO_RUNE_BOW,
        real_pob_engine,
        build_path=str(BUILD),
        item_check_pro={"ignore_socketed_mods": True},
    )
    row_on = _weapon1_comparison(on)
    assert on["socket_normalization"]["baseline_normalized_slots"] == [SLOT]
    # The candidate itself has nothing to strip -- normalization must not claim it did.
    assert on["socket_normalization"]["candidate_normalized"] is False
    assert row_on["restore"]["pass"] is True

    off = evaluate_item(
        _CANDIDATE_NO_RUNE_BOW,
        real_pob_engine,
        build_path=str(BUILD),
        item_check_pro={"ignore_socketed_mods": False},
    )
    row_off = _weapon1_comparison(off)
    # With the real (rune-bearing) baseline measured as-is, the baseline metrics
    # must differ from the normalized run -- the rune's own contribution is being
    # measured in one case and not the other.
    assert row_off["baseline"]["metrics"] != row_on["baseline"]["metrics"]


def test_build_state_is_fully_restored_after_a_normalized_evaluation(real_pob_engine) -> None:
    """Requirement 8: the true equipped item (with its real rune) survives intact."""
    before = real_pob_engine.get_equipment()
    before_weapon1 = next(e for e in before["equipment"] if e.get("slot") == SLOT)

    result = evaluate_item(
        _CANDIDATE_DIFFERENT_RUNE_BOW,
        real_pob_engine,
        build_path=str(BUILD),
        item_check_pro={"ignore_socketed_mods": True},
    )
    row = _weapon1_comparison(result)
    assert row["restore"]["pass"] is True
    assert row["restore"]["equipment_match"] is True
    assert row["restore"]["fingerprint_match"] is True

    after = real_pob_engine.get_equipment()
    after_weapon1 = next(e for e in after["equipment"] if e.get("slot") == SLOT)
    assert after_weapon1["raw"] == before_weapon1["raw"]
    assert "Rune: Countess Seske" in after_weapon1["raw"]

    # A subsequent, unrelated evaluation on the same engine still works cleanly.
    follow_up = evaluate_item(_CANDIDATE_NO_RUNE_BOW, real_pob_engine, build_path=str(BUILD))
    assert _weapon1_comparison(follow_up)["restore"]["pass"] is True


def test_a_failed_baseline_override_never_leaves_a_partial_mutation_equipped(real_pob_engine) -> None:
    """PRE-MERGE AUDIT regression: a mid-batch baseline_overrides failure must roll back.

    ``tx_begin`` mutates the build to apply baseline overrides for every compatible
    slot in ONE transaction (e.g. two rings, or dual-wielded weapons, each needing
    their own override) -- a real, easily reached shape whenever a candidate is
    legal in more than one currently-socketed slot. Unlike ``tx_measure``'s
    candidate changes, this mutation used to have no rollback if a LATER slot's
    override failed to parse after an EARLIER one had already been applied and
    equipped. This directly engages that path: the first override (Ring 1) is
    valid, the second (Ring 2) is deliberately unparseable.
    """
    real_pob_engine.load_build(RING_BUILD)
    before = real_pob_engine.get_equipment()
    before_by_slot = {e.get("slot"): e for e in before["equipment"]}

    ring_one_raw = before_by_slot["Ring 1"]["raw"]
    assert ring_one_raw
    # Deliberately DIFFERENT from the true equipped text (not merely a copy of it),
    # so that if this override's mutation ever leaks past a failed transaction, the
    # raw-text comparison below can actually detect it instead of trivially
    # matching a byte-identical re-application of the same item.
    ring_one_valid_override = ring_one_raw + "\n200% increased Rarity of Items found\n"

    with pytest.raises(EngineError):
        real_pob_engine.evaluate_item_slots(
            ["Ring 1", "Ring 2"],
            ring_one_raw,
            baseline_overrides={
                "Ring 1": ring_one_valid_override,
                "Ring 2": "this is not a parseable item at all",
            },
        )

    after = real_pob_engine.get_equipment()
    after_by_slot = {e.get("slot"): e for e in after["equipment"]}
    assert after_by_slot["Ring 1"]["raw"] == before_by_slot["Ring 1"]["raw"]
    assert after_by_slot["Ring 2"]["raw"] == before_by_slot["Ring 2"]["raw"]

    # The worker must still be healthy: a normal evaluation right after must succeed.
    recovered = evaluate_item(ring_one_raw, real_pob_engine, build_path=str(RING_BUILD))
    row = next(r for r in recovered["slot_comparisons"] if r["pob_slot"] == "Ring 1")
    assert row["restore"]["pass"] is True
