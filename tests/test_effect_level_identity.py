from __future__ import annotations

import pytest

from poe2value.items.effect_components import ComponentReference, MAX_EFFECTS, normalize_effect_catalog
from poe2value.items.evaluation_identity import identity_from_state


pytestmark = pytest.mark.itemcheck


def _reference(effect_id: str, *, selector: int) -> dict:
    semantic_id = f"group|{effect_id}|gem|set|part||DIRECT||"
    return {
        "semantic_id": semantic_id,
        "group_id": "group",
        "effect_id": effect_id,
        "source_gem_id": "Metadata/Items/Gems/SkillGemExample",
        "source_gem_index": 1,
        "owner": "PLAYER",
        "stat_set_key": "set",
        "part_key": "part",
        "stage_count": None,
        "calculation_mode": "DIRECT",
        "output_table": "mainOutput",
        "group_selector": 3,
        "effect_selector": selector,
    }


def test_sibling_effects_have_distinct_semantic_and_cache_identity() -> None:
    first = ComponentReference.from_dict(_reference("EffectAPlayer", selector=1))
    second = ComponentReference.from_dict(_reference("EffectBPlayer", selector=2))

    assert first.semantic_id != second.semantic_id
    assert first.cache_identity != second.cache_identity


def test_selector_reordering_does_not_change_semantic_identity() -> None:
    before = ComponentReference.from_dict(_reference("EffectAPlayer", selector=1))
    reordered = ComponentReference.from_dict(_reference("EffectAPlayer", selector=7))

    assert before.semantic_id == reordered.semantic_id
    assert before.cache_identity == reordered.cache_identity


def test_catalog_reordering_preserves_references() -> None:
    rows = [
        {"status": "MEASURED", "reference": _reference("EffectAPlayer", selector=1)},
        {"status": "MEASURED", "reference": _reference("EffectBPlayer", selector=2)},
    ]
    forward = normalize_effect_catalog({"effects": rows, "total_effects": 2})
    reverse = normalize_effect_catalog({"effects": list(reversed(rows)), "total_effects": 2})

    assert {row["reference"]["semantic_id"] for row in forward["effects"]} == {
        row["reference"]["semantic_id"] for row in reverse["effects"]
    }


def test_malformed_and_duplicate_effect_rows_fail_closed() -> None:
    valid = {"status": "MEASURED", "reference": _reference("EffectAPlayer", selector=1)}
    payload = normalize_effect_catalog(
        {
            "effects": [valid, {"status": "MEASURED", "reference": {}}, valid],
            "total_effects": 3,
        }
    )

    assert len(payload["effects"]) == 1
    assert payload["malformed_count"] == 2


def test_effect_catalog_is_bounded() -> None:
    rows = [
        {"status": "MEASURED", "reference": _reference(f"Effect{index}Player", selector=index)}
        for index in range(1, MAX_EFFECTS + 4)
    ]
    payload = normalize_effect_catalog({"effects": rows, "total_effects": len(rows)})

    assert len(payload["effects"]) == MAX_EFFECTS
    assert payload["truncated"] is True


def test_component_reference_rejects_missing_or_invalid_identity() -> None:
    with pytest.raises(ValueError):
        ComponentReference.from_dict({"effect_id": "EffectAPlayer"})
    broken = _reference("EffectAPlayer", selector=1)
    broken["stage_count"] = "many"
    with pytest.raises(ValueError):
        ComponentReference.from_dict(broken)


def test_evaluation_context_fingerprint_separates_selected_effects() -> None:
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
    first = identity_from_state(
        **common,
        fingerprint_components={"main_effect_semantic_id": "group|EffectAPlayer"},
    )
    second = identity_from_state(
        **common,
        fingerprint_components={"main_effect_semantic_id": "group|EffectBPlayer"},
    )

    assert first.skill_context_fingerprint != second.skill_context_fingerprint
    assert first.token != second.token
