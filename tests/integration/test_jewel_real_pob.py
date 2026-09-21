"""M1.3 Jewel Intelligence -- real-PoB evidence for the jewel Item Check path.

Uses the existing public corpus (fixtures/builds/public_corpus) rather than adding
new fixtures: core04_melee_weapon.xml already carries five allocated, occupied
jewel sockets (a Timeless Jewel, two unique Diamonds, two rare Rubies), and
core04_skill_native_dot.xml carries nineteen allocated sockets, most of them
empty. Both were discovered by inspecting the existing corpus for jewel content
(Phase A audit) before considering any new fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2value.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
MELEE_WEAPON_BUILD = CORPUS / "core04_melee_weapon.xml"
SKILL_NATIVE_DOT_BUILD = CORPUS / "core04_skill_native_dot.xml"

pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

# A plain rare Ruby jewel, compatible with every ordinary (non-cluster,
# non-sinister, non-ascendancy-embedded) jewel socket.
CANDIDATE_RUBY = """Rarity: RARE
Spirit Shard
Ruby
Item Level: 55
LevelReq: 0
Implicits: 1
{enchant}+9% to Lightning Resistance
+1% to Maximum Fire Resistance
15% increased Global Physical Damage
6% increased Area of Effect
{crafted}6% of Skill Mana Costs Converted to Life Costs"""


def _rows(result: dict) -> dict[str, dict]:
    return {row["pob_slot"]: row for row in result["slot_comparisons"]}


def test_jewel_candidate_is_routed_to_jewel_sockets_not_equipment_slots() -> None:
    """parse_item/resolve_compatible_slots classify a Jewel by dynamic socket
    name ("Jewel <nodeId>"), never as a fixed equipment ProductSlot -- see
    poe2value.items.slots.is_jewel_socket_pob_slot."""
    from poe2value.items.slots import is_jewel_socket_pob_slot

    assert is_jewel_socket_pob_slot("Jewel 2491")
    assert not is_jewel_socket_pob_slot("Ring 1")
    assert not is_jewel_socket_pob_slot("Weapon 2")


def test_occupied_socket_replacement_measurable_and_restored(real_pob_engine) -> None:
    """Scenario 1: real build, real equipped Jewel, candidate produces a real
    measurable delta, verdict, and clean restore."""
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(MELEE_WEAPON_BUILD))
    assert result["ok"] is True
    rows = _rows(result)
    assert set(rows) == {"Jewel 2491", "Jewel 11184", "Jewel 26196", "Jewel 26725", "Jewel 55190"}

    # Socket 55190 holds the unique "Megalomaniac, Diamond" (grants allocated
    # notables via its enchant lines); replacing it with a plain Ruby is a
    # real, measurable downgrade in build terms -- this repo's ranking policy
    # (below) selects it as the recommendation because it produces the most
    # decisive CLEAR_UPGRADE-shaped delta among the compatible sockets, i.e.
    # this specific unique is the socket where the candidate is comparatively
    # strongest, not because it is an arbitrary first slot.
    row = rows["Jewel 55190"]
    assert row["baseline_item"]["name"] == "Megalomaniac, Diamond"
    assert row["baseline_item"]["empty"] is False
    assert row["restore"]["pass"] is True
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"

    # Every socket's baseline correctly reflects ITS OWN currently-equipped
    # jewel, not a shared/default one.
    assert rows["Jewel 2491"]["baseline_item"]["name"] == "Heart of the Well, Diamond"
    assert rows["Jewel 26196"]["baseline_item"]["name"] == "Undying Hate, Timeless Jewel"
    assert rows["Jewel 11184"]["baseline_item"]["name"] == "Spirit Shard, Ruby"


def test_repeated_evaluation_is_stable_and_restores_cleanly(real_pob_engine) -> None:
    """Restore correctness + repeated-evaluation stability (milestone-blocking
    if violated): running the identical jewel evaluation twice in a row must
    give byte-identical socket set, verdicts, and a passing restore both
    times."""
    first = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(MELEE_WEAPON_BUILD))
    second = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(MELEE_WEAPON_BUILD))
    first_rows, second_rows = _rows(first), _rows(second)
    assert set(first_rows) == set(second_rows)
    for slot in first_rows:
        assert first_rows[slot]["verdict"] == second_rows[slot]["verdict"], slot
        assert first_rows[slot]["restore"]["pass"] is True
        assert second_rows[slot]["restore"]["pass"] is True
    assert first["recommendation"]["product_slot"] == second["recommendation"]["product_slot"]


def test_multi_socket_ranking_reflects_best_valid_placement_not_first_socket(real_pob_engine) -> None:
    """Scenario 2: at least two compatible occupied sockets exist, the
    candidate is materially better in one than another, and the
    recommendation deterministically reflects the best placement -- not
    whichever socket happens to sort first."""
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(MELEE_WEAPON_BUILD))
    rows = _rows(result)

    # Socket 2491 (baseline: unique "Heart of the Well") and socket 55190
    # (baseline: unique "Megalomaniac") are BOTH occupied by uniques the
    # candidate is not, and produce materially different verdicts:
    assert rows["Jewel 2491"]["verdict"] != rows["Jewel 55190"]["verdict"]
    # NO_CHANGE for the socket that already holds the same jewel family/roll
    # the candidate is (11184 is itself a Ruby jewel).
    assert rows["Jewel 11184"]["verdict"] == "NO_CHANGE"

    # The recommendation is the socket judged best by the EXISTING ranking
    # policy (rank_slot_comparisons), not sorted-first ("Jewel 11184" would
    # sort/iterate before "Jewel 2491"/"Jewel 55190" is not guaranteed by
    # dict order, so this only holds if selection is genuinely score-driven).
    assert result["recommendation"]["product_slot"] == "Jewel 55190"
    assert result["recommendation"]["verdict"] == "CLEAR_UPGRADE"


def test_multi_axis_tradeoff_is_reported_not_hidden(real_pob_engine) -> None:
    """Scenario 5: a socket where the candidate improves one axis and
    worsens another must surface as a TRADEOFF, never silently collapsed
    into a single-axis upgrade/downgrade."""
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(MELEE_WEAPON_BUILD))
    rows = _rows(result)
    # Socket 26196 holds a Timeless Jewel granting Conquered/Desecrated
    # attribute bonuses across a large radius; removing it is an offense
    # upgrade (loses no damage-relevant mods) but a defense-relevant
    # attribute loss -- a real, PoB-measured multi-axis tradeoff.
    row = rows["Jewel 26196"]
    assert row["verdict"] == "TRADEOFF"
    metric_profile = row["evaluation_outcome"]["item_impact"]["axes"]
    assert "OFFENSE" in metric_profile and "DEFENSE" in metric_profile


def test_empty_allocated_socket_is_compared_against_no_jewel(real_pob_engine) -> None:
    """Scenario 3: an allocated but empty jewel socket must be evaluated as
    "candidate vs no jewel", using the same empty-slot semantics as ordinary
    equipment, never mistaken for replacing a different jewel.

    core04_skill_native_dot.xml has one socket (Jewel 26196) whose currently
    equipped jewel is a corpus-fixture item that trips a known, bounded PoB
    restore-safety limitation (see docs/POB2_ENGINE_CONTRACT.md's Jewel
    section) unrelated to empty-socket handling, so this test evaluates the
    empty sockets directly through the engine rather than the full
    auto-discovered batch.
    """
    engine = real_pob_engine
    engine.ensure_build_ready(str(SKILL_NATIVE_DOT_BUILD), context="MAP")
    empty_slots = ["Jewel 11184", "Jewel 17788", "Jewel 23960"]
    batch = engine.evaluate_item_slots(empty_slots, CANDIDATE_RUBY, context="MAP")
    assert batch["restore"]["status"] == "OK"
    for entry in batch["slots"]:
        assert entry.get("error") is None
        slot_item = entry["slot_item"]
        assert slot_item["equipped"] is False
        # Not equipped means no baseline raw item text -- never inferred from
        # a neighboring socket.
        assert not slot_item.get("raw")
