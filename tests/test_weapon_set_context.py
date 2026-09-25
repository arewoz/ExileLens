"""Slice 3 unit gate: context identity, physical targets, cache safety (no PoB)."""

from __future__ import annotations

import pathlib

import pytest

from exilelens.items import contextual_evaluation as contextual
from exilelens.items.effect_components import (
    MAX_EFFECTS,
    CalculationContext,
    ComponentReference,
    ContextualComponentReference,
    normalize_context_catalog,
)
from exilelens.items.evaluation_identity import identity_from_state
from exilelens.items.slots import (
    PHYSICAL_WEAPON_SLOTS,
    ProductSlot,
    opposite_physical_slot,
)

pytestmark = pytest.mark.itemcheck


def _reference() -> dict:
    return {
        "semantic_id": "group|EffectAPlayer|gem|set|part||DIRECT||",
        "group_id": "group",
        "effect_id": "EffectAPlayer",
        "source_gem_id": "Metadata/Items/Gems/SkillGemExample",
        "source_gem_index": 1,
        "owner": "PLAYER",
        "stat_set_key": "set",
        "part_key": "part",
        "stage_count": None,
        "calculation_mode": "DIRECT",
        "output_table": "mainOutput",
        "group_selector": 3,
        "effect_selector": 1,
    }


def test_weapon_set_is_binary_and_validated() -> None:
    assert CalculationContext(weapon_set=1).weapon_set == 1
    assert CalculationContext(weapon_set=2).weapon_set == 2
    with pytest.raises(ValueError):
        CalculationContext(weapon_set=0)
    with pytest.raises(ValueError):
        CalculationContext(weapon_set=3)
    with pytest.raises(ValueError):
        CalculationContext.from_dict({"weapon_set": 3})
    with pytest.raises(ValueError):
        CalculationContext.from_dict({"weapon_set": "many"})


def test_context_token_covers_weapon_set_and_skill_set() -> None:
    set1 = CalculationContext(weapon_set=1)
    set2 = CalculationContext(weapon_set=2)
    assert set1.token != set2.token
    assert CalculationContext(weapon_set=1, active_skill_set_id="5").token != CalculationContext(
        weapon_set=1, active_skill_set_id="7"
    ).token


def test_same_effect_in_two_sets_is_same_semantic_but_distinct_observation() -> None:
    component = ComponentReference.from_dict(_reference())
    first = ContextualComponentReference(component=component, context=CalculationContext(weapon_set=1))
    second = ContextualComponentReference(component=component, context=CalculationContext(weapon_set=2))
    # Effect semantic identity itself is context-independent ...
    assert first.component.semantic_id == second.component.semantic_id
    assert first.component.cache_identity == second.component.cache_identity
    # ... but the contextual cache observation must never be reusable across sets.
    assert first.cache_identity != second.cache_identity


def test_physical_targets_cover_primary_and_swap_pairs() -> None:
    assert contextual.resolve_physical_target(ProductSlot.WEAPON_1, 1).physical_pob_slot == "Weapon 1"
    assert contextual.resolve_physical_target(ProductSlot.WEAPON_1, 2).physical_pob_slot == "Weapon 1 Swap"
    assert contextual.resolve_physical_target(ProductSlot.WEAPON_2, 1).physical_pob_slot == "Weapon 2"
    assert contextual.resolve_physical_target(ProductSlot.WEAPON_2, 2).physical_pob_slot == "Weapon 2 Swap"
    assert contextual.resolve_physical_target(ProductSlot.OFFHAND_1, 1).physical_pob_slot == "Weapon 2"
    assert contextual.resolve_physical_target(ProductSlot.OFFHAND_1, 2).physical_pob_slot == "Weapon 2 Swap"
    assert set(PHYSICAL_WEAPON_SLOTS) == {"Weapon 1", "Weapon 2", "Weapon 1 Swap", "Weapon 2 Swap"}


def test_physical_targets_reject_non_weapon_slots_and_bad_sets() -> None:
    with pytest.raises(ValueError):
        contextual.resolve_physical_target(ProductSlot.HELMET, 1)
    with pytest.raises(ValueError):
        contextual.resolve_physical_target(ProductSlot.WEAPON_1, 3)
    with pytest.raises(ValueError):
        opposite_physical_slot("Helmet")
    assert opposite_physical_slot("Weapon 1") == "Weapon 1 Swap"
    assert opposite_physical_slot("Weapon 1 Swap") == "Weapon 1"
    assert opposite_physical_slot("Weapon 2") == "Weapon 2 Swap"
    assert opposite_physical_slot("Weapon 2 Swap") == "Weapon 2"


def test_offhand_2_is_not_a_contextual_target() -> None:
    from exilelens.items import slots as slot_module

    mapping = slot_module._PHYSICAL_WEAPON_TARGET
    assert not any(logical == ProductSlot.OFFHAND_2.value for logical, _ in mapping)
    with pytest.raises(ValueError):
        contextual.resolve_physical_target(ProductSlot.OFFHAND_2, 1)


def test_evaluation_identity_separates_weapon_and_skill_sets() -> None:
    common = {
        "source_identity": "build",
        "source_revision": "revision",
        "build_generation": 1,
        "baseline_fingerprint": "baseline",
        "equipment_fingerprint": "equipment",
        "tree_fingerprint": "tree",
        "loadout": "default",
        "item_set": "1",
        "calculation_context": "MAP",
        "worker_generation": 1,
    }
    set1 = identity_from_state(**common, fingerprint_components={"weapon_set": 1})
    set2 = identity_from_state(**common, fingerprint_components={"weapon_set": 2})
    assert set1.token != set2.token
    assert set1.weapon_set == 1 and set2.weapon_set == 2
    skill_a = identity_from_state(**common, fingerprint_components={"active_skill_set_id": 5})
    skill_b = identity_from_state(**common, fingerprint_components={"active_skill_set_id": 7})
    assert skill_a.token != skill_b.token


def test_context_catalog_is_bounded_with_truncation_metadata() -> None:
    rows = [
        {
            "reference": _reference(),
            "context": {"weapon_set": 1 if index % 2 == 0 else 2},
            "status": "MEASURED",
        }
        for index in range(MAX_EFFECTS * 2 + 4)
    ]
    payload = normalize_context_catalog({"contexts": rows, "total_contexts": len(rows)})
    assert len(payload["contexts"]) <= MAX_EFFECTS * 2
    assert payload["max_weapon_contexts"] == 2
    assert payload["truncated"] is True


def test_ordinary_evaluation_path_does_not_import_contextual_flow() -> None:
    import exilelens.items.evaluation as evaluation_module

    source = pathlib.Path(evaluation_module.__file__).read_text(encoding="utf-8")
    assert "contextual_evaluation" not in source
    assert "weapon_set" in source  # cache-key qualification only


def test_no_voltaic_specific_logic_in_production_code() -> None:
    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    hits = [
        path
        for path in root.rglob("*.py")
        if "voltaic" in path.read_text(encoding="utf-8").lower()
    ]
    assert hits == []
    bridge = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "lua" / "bridge.lua"
    assert "voltaic" not in bridge.read_text(encoding="utf-8").lower()
