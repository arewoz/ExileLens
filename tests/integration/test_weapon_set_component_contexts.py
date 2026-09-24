"""Slice 3 real-PoB gate: weapon-set-qualified component contexts.

Runs against the local supported PoB2 revision only (`-m real_pob`, with
`POB2_PATH` set). No production verdict logic is exercised here: every
assertion is about context identity, physical isolation, truthful
availability, and exact restore. No skill or item is named for its game
mechanics; references come from the live effect catalog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2value.errors import RestoreFailed
from poe2value.items.contextual_evaluation import (
    evaluate_physical_candidate,
    list_component_contexts,
    read_component_in_context,
)
from poe2value.items.effect_components import ContextualComponentReference
from poe2value.items.evaluation import evaluate_item
from poe2value.items.slots import ProductSlot

ROOT = Path(__file__).resolve().parents[2]
BUILDS = ROOT / "fixtures" / "builds"
PUBLIC_CORPUS = BUILDS / "public_corpus"
WEAPON_SWAP = PUBLIC_CORPUS / "core04_weapon_swap.xml"
MELEE = PUBLIC_CORPUS / "core04_melee_weapon.xml"
RING_BUILD = BUILDS / "core04_player_ring.xml"
ITEMS = ROOT / "fixtures" / "items"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _catalogs(engine, build: Path) -> list[dict]:
    loaded = engine.load_build(build)
    count = int((loaded.get("build") or {}).get("skill_group_count") or 0)
    return [engine.list_calculable_effects(indices=[index]) for index in range(1, count + 1)]


def _find_group(catalogs: list[dict], expected: set[str]) -> dict:
    for catalog in catalogs:
        ids = {row["reference"]["effect_id"] for row in catalog["effects"]}
        if expected <= ids:
            return catalog
    raise AssertionError(f"no effect group contained {sorted(expected)}")


def _row(catalog: dict, effect_id: str) -> dict:
    return next(row for row in catalog["effects"] if row["reference"]["effect_id"] == effect_id)


def _physical_raws(engine) -> dict[str, str]:
    return dict(engine.get_weapon_set_context()["physical_weapons"])


def test_same_reference_reads_under_both_sets_with_exact_restore(real_pob_engine) -> None:
    catalog = _find_group(
        _catalogs(real_pob_engine, WEAPON_SWAP),
        {"EscapeShotPlayer", "EscapeShotIceFragmentPlayer"},
    )
    reference = _row(catalog, "EscapeShotPlayer")["reference"]
    before = real_pob_engine.get_metrics()
    assert real_pob_engine.get_weapon_set_context()["weapon_set"] == 2

    first_set2 = read_component_in_context(real_pob_engine, reference, 2)
    first_set1 = read_component_in_context(real_pob_engine, reference, 1)

    for observed, expected_set in ((first_set2, 2), (first_set1, 1)):
        assert observed["requested_weapon_set"] == expected_set
        assert observed["context"]["weapon_set"] == expected_set
        assert observed["status"] in ("MEASURED", "UNAVAILABLE")
        if observed["status"] == "UNAVAILABLE":
            # Unavailable in a context is explicit, never a synthetic zero.
            assert observed["reason"] in (
                "NOT_VALID_IN_CONTEXT",
                "EFFECT_NOT_FOUND",
                "CACHE_MISS",
                "CACHE_IDENTITY_MISMATCH",
                "MALFORMED_EFFECT_CACHE",
            )
            assert "output" not in observed
        else:
            assert isinstance(observed.get("output"), dict)
        assert "qualified_reference" in observed

    # Same semantic effect, two disjoint cache observations.
    qualified = [
        ContextualComponentReference.from_dict(
            {"component": reference, "context": {"weapon_set": weapon_set}}
        )
        for weapon_set in (1, 2)
    ]
    assert qualified[0].component.cache_identity == qualified[1].component.cache_identity
    assert qualified[0].cache_identity != qualified[1].cache_identity

    # Exact restoration: still on set 2, same fingerprint and equipment.
    after = real_pob_engine.get_metrics()
    assert real_pob_engine.get_weapon_set_context()["weapon_set"] == 2
    assert after["fingerprint_hash"] == before["fingerprint_hash"]


def test_repeated_set_switching_is_deterministic(real_pob_engine) -> None:
    catalog = _find_group(
        _catalogs(real_pob_engine, WEAPON_SWAP),
        {"EscapeShotPlayer", "EscapeShotIceFragmentPlayer"},
    )
    reference = _row(catalog, "EscapeShotPlayer")["reference"]
    reads = [
        read_component_in_context(real_pob_engine, reference, weapon_set)
        for weapon_set in (2, 1, 2, 1, 2)
    ]
    set2 = [read for read, weapon_set in zip(reads, (2, 1, 2, 1, 2)) if weapon_set == 2]
    set1 = [read for read, weapon_set in zip(reads, (2, 1, 2, 1, 2)) if weapon_set == 1]
    assert all(read["status"] == set2[0]["status"] for read in set2)
    assert all(read["status"] == set1[0]["status"] for read in set1)
    if set2[0]["status"] == "MEASURED":
        assert all(read["output"] == set2[0]["output"] for read in set2)
    if set1[0]["status"] == "MEASURED":
        assert all(read["output"] == set1[0]["output"] for read in set1)


def test_sibling_effects_share_no_context_observation(real_pob_engine) -> None:
    catalog = _find_group(
        _catalogs(real_pob_engine, WEAPON_SWAP),
        {"EscapeShotPlayer", "EscapeShotIceFragmentPlayer"},
    )
    matrix = list_component_contexts(
        real_pob_engine,
        [_row(catalog, effect_id)["reference"] for effect_id in ("EscapeShotPlayer", "EscapeShotIceFragmentPlayer")],
    )
    assert matrix["max_weapon_contexts"] == 2
    assert matrix["truncated"] is False
    assert len(matrix["contexts"]) == 4
    identities = {
        ContextualComponentReference.from_dict(
            {"component": row["reference"], "context": row["context"]}
        ).cache_identity
        for row in matrix["contexts"]
    }
    assert len(identities) == 4


def test_physical_set2_candidate_is_isolated_and_restored(real_pob_engine) -> None:
    catalog = _find_group(
        _catalogs(real_pob_engine, WEAPON_SWAP),
        {"EscapeShotPlayer", "EscapeShotIceFragmentPlayer"},
    )
    reference = _row(catalog, "EscapeShotPlayer")["reference"]
    physical_before = _physical_raws(real_pob_engine)
    assert physical_before["Weapon 1 Swap"].strip()
    fingerprint_before = real_pob_engine.get_metrics()["fingerprint_hash"]

    candidate_raw = physical_before["Weapon 1 Swap"] + "\n500% increased Physical Damage\n"
    result = evaluate_physical_candidate(
        real_pob_engine, reference, ProductSlot.WEAPON_1, 2, candidate_raw
    )

    assert result["requested_weapon_set"] == 2
    assert result["physical_target"] == {
        "logical_product_slot": "WEAPON_1",
        "physical_pob_slot": "Weapon 1 Swap",
        "weapon_set": 2,
    }
    assert result["restore"]["pass"] is True
    assert result["restore"]["weapon_set"] == 2
    # The opposite set is byte-identical: set 1 was never touched.
    assert result["physical_target"]["physical_pob_slot"] == "Weapon 1 Swap"
    assert _physical_raws(real_pob_engine)["Weapon 1"] == physical_before["Weapon 1"]
    assert _physical_raws(real_pob_engine)["Weapon 2"] == physical_before["Weapon 2"]
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == fingerprint_before

    if result["status"] == "MEASURED":
        assert result["baseline"]["status"] == "MEASURED"
        assert result["candidate"]["status"] == "MEASURED"
        assert isinstance(result["delta"], dict) and result["delta"]
        changed = [
            field
            for field, entry in result["delta"].items()
            if isinstance(entry, dict) and entry.get("absolute") not in (0, 0.0, None)
        ]
        # A wrong-slot placement measures exactly zero (the M1.1 P0 precedent);
        # a non-empty delta proves the exact physical slot was hit.
        assert changed
        assert all(result["delta"][field]["relative_pct"] is not None or result["delta"][field]["before"] is not None for field in changed)
    else:
        assert result["status"] == "UNAVAILABLE"
        assert "output" not in (result.get("candidate") or {})


def test_physical_set1_candidate_leaves_set2_identical(real_pob_engine) -> None:
    catalog = _find_group(
        _catalogs(real_pob_engine, WEAPON_SWAP),
        {"EscapeShotPlayer", "EscapeShotIceFragmentPlayer"},
    )
    reference = _row(catalog, "EscapeShotPlayer")["reference"]
    physical_before = _physical_raws(real_pob_engine)
    assert physical_before["Weapon 1"].strip()
    fingerprint_before = real_pob_engine.get_metrics()["fingerprint_hash"]

    candidate_raw = physical_before["Weapon 1"] + "\n500% increased Physical Damage\n"
    result = evaluate_physical_candidate(
        real_pob_engine, reference, ProductSlot.WEAPON_1, 1, candidate_raw
    )

    assert result["requested_weapon_set"] == 1
    assert result["physical_target"]["physical_pob_slot"] == "Weapon 1"
    assert result["restore"]["pass"] is True
    # Set 2 is byte-identical: the set-1 placement never touched it.
    physical_after = _physical_raws(real_pob_engine)
    assert physical_after["Weapon 1 Swap"] == physical_before["Weapon 1 Swap"]
    assert physical_after["Weapon 2 Swap"] == physical_before["Weapon 2 Swap"]
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == fingerprint_before


def test_context_failures_close_and_restore(real_pob_engine) -> None:
    real_pob_engine.load_build(WEAPON_SWAP)
    with pytest.raises(ValueError):
        real_pob_engine.read_effect_metrics({"semantic_id": "x", "group_id": "g", "effect_id": "e"}, weapon_set=3)
    catalog = _find_group(
        _catalogs(real_pob_engine, WEAPON_SWAP),
        {"EscapeShotPlayer", "EscapeShotIceFragmentPlayer"},
    )
    reference = _row(catalog, "EscapeShotPlayer")["reference"]
    before = real_pob_engine.get_metrics()["fingerprint_hash"]
    # Physical slot from the other set is refused before anything mutates.
    with pytest.raises(Exception):
        real_pob_engine.evaluate_effect_candidate(
            reference, weapon_set=2, physical_slot="Weapon 1", item_raw="Rarity: Rare\nTest\n"
        )
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == before
    # A failed candidate calculation still restores the original context.
    with pytest.raises(Exception):
        real_pob_engine.evaluate_effect_candidate(
            reference, weapon_set=2, physical_slot="Weapon 1 Swap", item_raw="this is not an item"
        )
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == before
    assert real_pob_engine.get_weapon_set_context()["weapon_set"] == 2


def test_corrupt_contextual_restore_fails_closed(real_pob_engine) -> None:
    catalog = _find_group(
        _catalogs(real_pob_engine, WEAPON_SWAP),
        {"EscapeShotPlayer", "EscapeShotIceFragmentPlayer"},
    )
    reference = _row(catalog, "EscapeShotPlayer")["reference"]
    physical = _physical_raws(real_pob_engine)
    with pytest.raises(RestoreFailed):
        real_pob_engine.evaluate_effect_candidate(
            reference,
            weapon_set=2,
            physical_slot="Weapon 1 Swap",
            item_raw=physical["Weapon 1 Swap"],
            test_fault="corrupt_restore",
        )
    # Recovery mirrors the ordinary path: the next load re-parses a known-good baseline.
    reloaded = real_pob_engine.load_build(WEAPON_SWAP)
    assert reloaded.get("reloaded") is True
    assert real_pob_engine.last_load_reloaded is True


def test_ordinary_item_check_uses_no_context_path_and_is_unchanged(real_pob_engine, monkeypatch) -> None:
    contextual_calls: list[dict] = []
    original_read = real_pob_engine.read_effect_metrics
    original_candidate = real_pob_engine.evaluate_effect_candidate

    def counted_read(reference, **kwargs):
        if kwargs.get("weapon_set") is not None:
            contextual_calls.append({"read": kwargs.get("weapon_set")})
        return original_read(reference, **kwargs)

    def counted_candidate(*args, **kwargs):
        contextual_calls.append({"candidate": True})
        return original_candidate(*args, **kwargs)

    monkeypatch.setattr(real_pob_engine, "read_effect_metrics", counted_read)
    monkeypatch.setattr(real_pob_engine, "evaluate_effect_candidate", counted_candidate)

    item = (ITEMS / "core04_offense_ring.txt").read_text(encoding="utf-8")
    result = evaluate_item(item, real_pob_engine, build_path=str(RING_BUILD))
    row = next(entry for entry in result["slot_comparisons"] if entry["pob_slot"] == "Ring 1")

    assert contextual_calls == []
    assert result["effect_catalog"]
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["evaluation_outcome"]["verdict"] == "MEANINGFUL_UPGRADE"
    assert row["restore"]["pass"] is True
