"""M1.3 Jewel Intelligence -- real-PoB evidence for the jewel Item Check path.

Uses the existing public corpus (fixtures/builds/public_corpus) rather than adding
new fixtures: core04_melee_weapon.xml carries five allocated, occupied jewel
sockets (a Timeless Jewel, two unique Diamonds, two rare Rubies).

P1.1b correctness fix, documented here because it changes what this file's own
fixtures were believed to prove: core04_skill_native_dot.xml was previously
(incorrectly) documented as "nineteen allocated sockets, most of them empty".
Ground truth -- `build.spec.allocNodes` queried directly against the passive
tree's Socket-type nodes, independent of `ItemsTab.slots`/`.inactive` -- is that
this build has only FOUR allocated jewel sockets (Jewel 7960 / 21984 / 26196 /
61419), and all four are occupied, none empty. The "nineteen" figure was every
Socket-type node PoB's `ItemsTab:Init` creates across the WHOLE passive tree
(`build.latestTree.nodes`, the same fixed ~19-node pool for every build sharing
this tree), never filtered by `spec.allocNodes` membership at all.

Root cause: `allocated_jewel_socket_slots()` (runtime/lua/bridge.lua) trusted
`slot.inactive` as that filter, and PoB's own `ItemsTabClass:UpdateSockets` is
indeed the function that correctly computes it (`spec.allocNodes[nodeId] == nil
-> slot.inactive = true`) -- but PoB only ever calls `UpdateSockets` from
`ItemsTab:Draw` (unreachable headless -- no render loop) and one narrow
`CalcSetup.lua` branch gated on a granted-passive-nodes change that does not
fire for an ordinary build. `ItemSlotControl` never initializes `.inactive` in
its constructor, so headless it stayed Lua-`nil` (falsy) for every socket-type
node no prior call happened to touch, and `not slot.inactive` silently admitted
all of them. Proven build-by-build: core04_melee_weapon.xml's `.inactive`
happened to be correctly computed for its run (5 active, matching ground truth
exactly -- its own test coverage was never wrong), while
core04_skill_native_dot.xml's was never computed at all (0 of 19 marked
inactive) -- an order/state-dependent bug, not a deterministic one. Fixed by
calling `it:UpdateSockets()` explicitly before reading `.inactive`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from exilelens.items.evaluation import evaluate_item

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
    exilelens.items.slots.is_jewel_socket_pob_slot."""
    from exilelens.items.slots import is_jewel_socket_pob_slot

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
        assert first_rows[slot]["evaluation_outcome"]["evaluation_quality"] == "FULL", slot
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
    # CORPUS-02F: Sunder is a per-use (showAverage) skill, so the scored metric is its per-second TotalDPS.
    # This jewel raises per-use damage but lowers attack speed (0.8064 -> 0.7812), leaving the rate
    # unchanged; only the defence gain remains. The per-use figure used before hid the speed loss.
    assert result["recommendation"]["verdict"] == "DEFENSE_UPGRADE"
    assert rows["Jewel 55190"]["evaluation_outcome"]["evaluation_quality"] == "FULL"


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
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    metric_profile = row["evaluation_outcome"]["item_impact"]["axes"]
    assert "OFFENSE" in metric_profile and "DEFENSE" in metric_profile


def test_unallocated_jewel_socket_nodes_are_excluded_from_discovery(real_pob_engine) -> None:
    """P1.1b correctness fix regression: discovery must return only the jewel
    sockets actually allocated in the loaded spec -- not every Socket-type node
    PoB's ItemsTab creates for the whole passive tree.

    core04_skill_native_dot.xml is the proof case: it has 19 Socket-type nodes
    in its tree (the same fixed pool core04_melee_weapon.xml also draws from --
    "Jewel 11184"/"Jewel 26196"/etc. are literal tree-node ids, not per-build),
    but ground truth (`spec.allocNodes` queried directly, independent of
    `ItemsTab.slots`/`.inactive`) says only 4 of them are allocated in THIS
    build: 7960, 21984, 26196, 61419. Before the fix, `parse_item` reported all
    19 as `compatible_slots`. This is also a genuinely "mixed" tree (allocated
    and unallocated Socket-type nodes both present), so it proves both
    "unallocated excluded" and "the mixed case returns exactly the expected
    legal set" in one real-engine assertion.
    """
    engine = real_pob_engine
    engine.ensure_build_ready(str(SKILL_NATIVE_DOT_BUILD), context="MAP")
    result = engine.parse_item(CANDIDATE_RUBY)
    assert set(result["compatible_slots"]) == {"Jewel 7960", "Jewel 21984", "Jewel 26196", "Jewel 61419"}
    assert result["allocated_jewel_socket_count"] == 4
    # Node ids that exist as Socket-type tree nodes (PoB creates an
    # ItemSlotControl for each one, occupied or not) but are NOT allocated in
    # this build's spec -- the exact set the pre-fix bug incorrectly admitted.
    known_unallocated = {"Jewel 2491", "Jewel 11184", "Jewel 17788", "Jewel 23960", "Jewel 26725", "Jewel 55190"}
    assert result["compatible_slots"] and known_unallocated.isdisjoint(result["compatible_slots"])


def test_unallocated_jewel_socket_ranking_only_sees_legal_candidates(real_pob_engine) -> None:
    """The fix must reach the full evaluate_item/ranking pipeline, not just
    parse_item's discovery response -- a slot never in `compatible_slots` must
    never appear in `slot_comparisons` or be selectable as the recommendation."""
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(SKILL_NATIVE_DOT_BUILD))
    assert result["ok"] is True
    rows = _rows(result)
    assert set(rows) == {"Jewel 7960", "Jewel 21984", "Jewel 26196", "Jewel 61419"}
    assert result["recommendation"]["product_slot"] in rows
    # All four are occupied in this build (see module docstring) -- each row's
    # baseline must reflect its OWN currently-equipped jewel, never a neighbor's.
    assert rows["Jewel 7960"]["baseline_item"]["empty"] is False
    assert rows["Jewel 21984"]["baseline_item"]["empty"] is False
    assert rows["Jewel 61419"]["baseline_item"]["empty"] is False


EMPTIED_SOCKET = 11184  # holds a plain rare Ruby ("Spirit Shard") in the unmodified fixture


def _with_socket_emptied(tmp_path: Path, node_id: int, mode: str) -> Path:
    """The public fixture with one allocated jewel unslotted, in both forms PoB writes a build with an empty socket:
    an explicit ``itemId="0"`` entry, or no entry at all."""
    text = MELEE_WEAPON_BUILD.read_text(encoding="utf-8")
    pattern = rf'<Socket itemId="\d+" nodeId="{node_id}"/>'
    if mode == "explicit_zero":
        text, count = re.subn(pattern, f'<Socket itemId="0" nodeId="{node_id}"/>', text)
    else:
        text, count = re.subn(r"[ \t]*" + pattern + r"\r?\n", "", text)
    assert count == 1, (mode, count)
    variant = tmp_path / f"core04_melee_weapon_empty_{mode}.xml"
    variant.write_text(text, encoding="utf-8")
    return variant


@pytest.mark.parametrize("mode", ["explicit_zero", "omitted"])
def test_empty_allocated_socket_is_compared_against_no_jewel(real_pob_engine, tmp_path: Path, mode: str) -> None:
    """Scenario 3: an allocated but EMPTY jewel socket is discovered and compared against no jewel, never inferred
    from a neighbouring socket, and nothing leaks into the next evaluation.

    R4 provenance note: no natural public-corpus build has an allocated-but-empty jewel socket (checked across the whole
    corpus), so this test derives one from the existing public fixture by unslotting a single jewel -- the same
    technique CORE-04's empty-ring test uses -- and measures it on the real engine. It is a variant of a real build, not
    a hand-made fixture; the earlier skip rested only on a code-path argument. Both representations PoB produces for an
    unslotted socket are covered."""
    original = _rows(evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(MELEE_WEAPON_BUILD)))
    assert original[f"Jewel {EMPTIED_SOCKET}"]["baseline_item"]["empty"] is False

    variant = _with_socket_emptied(tmp_path, EMPTIED_SOCKET, mode)
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(variant))

    assert result["ok"] is True
    rows = _rows(result)
    # The emptied socket is still allocated, so it is still discovered; none of the others is lost.
    assert set(rows) == set(original)
    empty = rows[f"Jewel {EMPTIED_SOCKET}"]
    assert empty["baseline_item"]["empty"] is True
    outcome = empty["evaluation_outcome"]
    assert outcome["replacing_empty_slot"] is True
    assert outcome["evaluation_quality"] == "FULL"
    assert empty["candidate"]["item_present"] is True
    assert empty["restore"]["pass"] is True
    # Compared against NO jewel: the unmodified socket was NO_CHANGE (same jewel family), the empty one is a real gain.
    assert original[f"Jewel {EMPTIED_SOCKET}"]["verdict"] == "NO_CHANGE"
    assert empty["verdict"] not in {"NO_CHANGE", "TRADEOFF"}
    assert result["recommendation"]["product_slot"] == f"Jewel {EMPTIED_SOCKET}"
    # Emptying one socket must not change what any other socket's own baseline measures.
    for slot, row in rows.items():
        if slot != f"Jewel {EMPTIED_SOCKET}":
            assert row["baseline_item"]["name"] == original[slot]["baseline_item"]["name"], slot
            assert row["verdict"] == original[slot]["verdict"], slot
        assert row["restore"]["pass"] is True, slot

    # No state leaked into the unmodified build.
    again = _rows(evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(MELEE_WEAPON_BUILD)))
    assert {slot: row["verdict"] for slot, row in again.items()} == {slot: row["verdict"] for slot, row in original.items()}
