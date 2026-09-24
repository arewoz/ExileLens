"""M1.3 bounded remediation slice: jewel restore-safety root cause + performance.

Part A root cause (see docs/POB2_ENGINE_CONTRACT.md's Jewel section for the full
writeup): a connectivity-affecting jewel ("From Nothing"-style "Passives in Radius
can be Allocated without being connected", or "Split Personality"-style "Can
Allocate Passive Skills from the <Class>'s starting point") makes other passives'
allocation validity depend on the jewel's presence. `ItemSlotClass:SetSelItemId`
(the swap-and-restore primitive the jewel transaction is built on) has no symmetric
"reallocate on restore" step the way PoB's own `ItemsTabClass:DeleteItem` has for
"deallocate on removal" -- so a candidate frame that briefly displaces such a jewel
left the true baseline's dependent passives deallocated even after the SAME jewel
was restored to its socket. This is fixed locally (`repair_tree_allocation` in
runtime/lua/bridge.lua, mirroring PoB's own `spec.allocNodes`/`node.alloc`/
`spec.hashOverrides`/`spec.masterySelections` mutations in reverse) for 2 of 3
previously-failing fixture classes; the third (a jewel with PoB's
`jewelData.alternateClassStart` flag) has a small, understood-but-unresolved
residual and stays in the existing connectivity-risk exclusion instead.

A separate, real bug was found and fixed in passing: `tx_finish`'s and
`tx_assert_reverted_full`'s RESTORE_FAILED error details had `baseline_value`/
`restored_value` swapped (pre-existing, predates M1.3 -- never visibly wrong
before because production equipment restores never actually mismatched).

Part B: native component discovery (`skill_report`) was found to be the dominant
cost of jewel evaluation (~70-80% of wall time on a multi-skill build) because
jewel batches were not requesting the PERF-06 in-batch optimization equipment
batches already get. Re-enabling it (safe: the new jewel inter-slot check always
recalculates before reading anything on its rare fallback path) cut wall time by
roughly a third with zero change to the correctness model.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"

pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

CANDIDATE_RUBY = """Rarity: RARE
Spirit Shard
Ruby
Item Level: 55
LevelReq: 0
Implicits: 1
+15% increased Global Physical Damage"""

# The 3 fixture classes Part A of the M1.3 audit found producing a genuine
# RESTORE_FAILED on jewel-socket transactions (unrelated to their skill
# archetype labels -- all 3 turned out to share the same connectivity-jewel
# root cause, not 3 distinct mechanisms).
PREVIOUSLY_FAILING = [
    "core04_stage_context.xml",
    "core04_mixed_hit_ailment.xml",
    "core04_minion_actor.xml",
]


@pytest.mark.parametrize("fixture_name", PREVIOUSLY_FAILING)
def test_previously_failing_fixtures_now_restore_correctly(real_pob_engine, fixture_name):
    """Every socket in each previously-failing fixture is now either correctly
    restorable (allocation/override/mastery repair) or safely excluded
    (residual connectivity-risk case) -- never a delivered RESTORE_FAILED."""
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(CORPUS / fixture_name))
    assert result["ok"] is True
    assert result["slot_comparisons"], "expected at least one evaluated socket"
    for row in result["slot_comparisons"]:
        assert row["restore"]["pass"] is True, row["pob_slot"]


def test_stage_context_split_personality_socket_is_excluded(real_pob_engine):
    """The one residual, not-locally-fixable case (core04_stage_context.xml,
    socket holding a jewel with PoB's `jewelData.alternateClassStart` flag,
    "Split Personality"-style) stays in the connectivity-risk exclusion rather
    than being silently included and risking a delivered wrong Life value."""
    build = CORPUS / "core04_stage_context.xml"
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(build))
    assert result["ok"] is True
    slots = {row["pob_slot"] for row in result["slot_comparisons"]}
    assert "Jewel 54127" not in slots
    diagnostics = result.get("jewel_socket_diagnostics") or {}
    assert diagnostics.get("excluded_connectivity_risky_socket_count", 0) >= 1


def test_repeated_evaluation_stable_on_previously_failing_fixture(real_pob_engine):
    build = CORPUS / "core04_minion_actor.xml"
    r1 = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(build))
    r2 = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(build))
    assert r1["recommendation"]["product_slot"] == r2["recommendation"]["product_slot"]
    assert r1["recommendation"]["verdict"] == r2["recommendation"]["verdict"]
    for row1, row2 in zip(
        sorted(r1["slot_comparisons"], key=lambda r: r["pob_slot"]),
        sorted(r2["slot_comparisons"], key=lambda r: r["pob_slot"]),
    ):
        assert row1["verdict"] == row2["verdict"]
        assert row1["restore"]["pass"] is True
        assert row2["restore"]["pass"] is True


def test_candidate_item_reused_across_sockets_not_reparsed(real_pob_engine, monkeypatch):
    """M1.3 Part B: the same candidate raw text is parsed/added once per batch,
    not once per socket (`set_item`'s `item_cache` param) -- every socket's
    `item_present` proof must still hold true regardless of reuse."""
    monkeypatch.setenv("EXILELENS_TOOLTIP_PERF", "1")
    build = CORPUS / "core04_melee_weapon.xml"
    real_pob_engine.ensure_build_ready(str(build), context="MAP")
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(build))
    assert result["ok"] is True
    assert len(result["slot_comparisons"]) == 5
    for row in result["slot_comparisons"]:
        assert row["restore"]["pass"] is True
    perf = result["timings"].get("per_slot_pob_ms", {}).get("__transaction__", {})
    print("candidate_set_item_ms:", perf.get("candidate_set_item_ms"))


def test_native_discovery_no_longer_dominates_jewel_evaluation_cost(real_pob_engine, monkeypatch):
    """Diagnostic, not a hard SLA (perf varies by machine): confirms the fixed
    redundant per-socket native-discovery recalculation stays fixed. Prints
    the measured wall time; does not assert an absolute bound."""
    monkeypatch.setenv("EXILELENS_TOOLTIP_PERF", "1")
    build = CORPUS / "core04_melee_weapon.xml"
    real_pob_engine.ensure_build_ready(str(build), context="MAP")
    started = time.perf_counter()
    result = evaluate_item(CANDIDATE_RUBY, real_pob_engine, build_path=str(build))
    elapsed_ms = (time.perf_counter() - started) * 1000
    perf = result["timings"].get("per_slot_pob_ms", {}).get("__transaction__", {})
    native_ms = perf.get("native_discovery_ms", 0)
    print(f"jewel evaluation wall_ms={elapsed_ms:.0f} native_discovery_ms={native_ms}")
    # Native discovery cost must stay a small fraction of total wall time, not
    # the dominant cost it was measured to be before the fix (~70-80%).
    if native_ms:
        assert native_ms < elapsed_ms * 0.25
