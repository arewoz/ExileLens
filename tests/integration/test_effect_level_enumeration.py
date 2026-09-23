from __future__ import annotations

from pathlib import Path

import pytest

from poe2value.items.evaluation import evaluate_item


ROOT = Path(__file__).resolve().parents[2]
BUILDS = ROOT / "fixtures" / "builds"
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


def test_additional_granted_effects_are_distinct_cache_backed_components(real_pob_engine) -> None:
    weapon_swap = BUILDS / "public_corpus" / "core04_weapon_swap.xml"
    melee = BUILDS / "public_corpus" / "core04_melee_weapon.xml"

    escape = _find_group(
        _catalogs(real_pob_engine, weapon_swap),
        {"EscapeShotPlayer", "EscapeShotIceFragmentPlayer"},
    )
    infernal = _find_group(
        _catalogs(real_pob_engine, melee),
        {"InfernalCryPlayer", "InfernalCryCorpseExplosionPlayer"},
    )

    for catalog, effect_ids in (
        (escape, ("EscapeShotPlayer", "EscapeShotIceFragmentPlayer")),
        (infernal, ("InfernalCryPlayer", "InfernalCryCorpseExplosionPlayer")),
    ):
        rows = [_row(catalog, effect_id) for effect_id in effect_ids]
        assert len({row["reference"]["group_id"] for row in rows}) == 1
        assert len({row["reference"]["semantic_id"] for row in rows}) == 2
        assert len({row["reference"]["cache_identity"] for row in rows}) == 2
        assert all(row["cache_status"] == "HIT" for row in rows)
        assert all(row["status"] == "MEASURED" for row in rows)


def test_exact_effect_reads_do_not_cross_contaminate_and_are_deterministic(real_pob_engine) -> None:
    build = BUILDS / "public_corpus" / "core04_melee_weapon.xml"
    catalog = _find_group(
        _catalogs(real_pob_engine, build),
        {"InfernalCryPlayer", "InfernalCryCorpseExplosionPlayer"},
    )
    first_catalog = real_pob_engine.list_calculable_effects(
        indices=[_row(catalog, "InfernalCryPlayer")["reference"]["group_selector"]]
    )
    second_catalog = real_pob_engine.list_calculable_effects(
        indices=[_row(catalog, "InfernalCryPlayer")["reference"]["group_selector"]]
    )
    assert first_catalog == second_catalog

    reads = [
        real_pob_engine.read_effect_metrics(_row(catalog, effect_id)["reference"])
        for effect_id in ("InfernalCryPlayer", "InfernalCryCorpseExplosionPlayer")
    ]
    assert [read["reference"]["effect_id"] for read in reads] == [
        "InfernalCryPlayer", "InfernalCryCorpseExplosionPlayer"
    ]
    assert len({read["reference"]["semantic_id"] for read in reads}) == 2
    assert all(read["source"] == "GLOBAL_CACHE" for read in reads)
    assert all(read["restore"]["status"] == "NOT_REQUIRED" for read in reads)


def test_cache_miss_fallback_restores_selected_effect_and_calc_state(real_pob_engine) -> None:
    build = BUILDS / "public_corpus" / "core04_melee_weapon.xml"
    loaded = real_pob_engine.load_build(build)
    before_identity = (loaded["build"] or {})["main_skill_identity"]
    before_metrics = real_pob_engine.get_metrics()
    catalog = _find_group(
        _catalogs(real_pob_engine, build),
        {"InfernalCryPlayer", "InfernalCryCorpseExplosionPlayer"},
    )
    reference = _row(catalog, "InfernalCryCorpseExplosionPlayer")["reference"]

    measured = real_pob_engine.read_effect_metrics(reference, force_cache_miss=True)
    after = real_pob_engine.get_build_info()
    after_metrics = real_pob_engine.get_metrics()

    assert measured["status"] == "MEASURED"
    assert measured["source"] == "TRANSACTIONAL_RECALC"
    assert measured["reference"]["semantic_id"] == reference["semantic_id"]
    assert measured["restore"]["pass"] is True
    assert (after["build"] or {})["main_skill_identity"] == before_identity
    assert after_metrics["fingerprint_hash"] == before_metrics["fingerprint_hash"]
    for key in ("stat_set_key", "part_key", "stage_count", "calculation_mode"):
        assert measured["restore"].get(key) == before_identity.get(key)


def test_malformed_effect_results_fail_closed_and_restore(real_pob_engine) -> None:
    build = BUILDS / "public_corpus" / "core04_melee_weapon.xml"
    catalog = _find_group(
        _catalogs(real_pob_engine, build),
        {"InfernalCryPlayer", "InfernalCryCorpseExplosionPlayer"},
    )
    reference = _row(catalog, "InfernalCryCorpseExplosionPlayer")["reference"]
    before = real_pob_engine.get_metrics()["fingerprint_hash"]

    malformed_cache = real_pob_engine.read_effect_metrics(reference, malformed_cache=True)
    malformed_fallback = real_pob_engine.read_effect_metrics(
        reference, force_cache_miss=True, malformed_fallback=True
    )

    assert malformed_cache["status"] == "UNAVAILABLE"
    assert malformed_cache["reason"] == "MALFORMED_EFFECT_CACHE"
    assert "output" not in malformed_cache
    assert malformed_fallback["status"] == "UNAVAILABLE"
    assert malformed_fallback["reason"] == "MALFORMED_EFFECT_RESULT"
    assert malformed_fallback["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == before


def test_effect_bound_and_ordinary_item_check_behavior(real_pob_engine) -> None:
    ordinary = BUILDS / "core04_player_ring.xml"
    loaded = real_pob_engine.load_build(ordinary)
    catalog = real_pob_engine.list_calculable_effects(max_effects=8)
    assert len(catalog["effects"]) <= 8
    assert catalog["max_effects"] == 8
    assert catalog["truncated"] is (catalog["total_effects"] > 8)
    assert (loaded["build"] or {})["effect_catalog"]["max_effects"] == 8

    item = (ITEMS / "core04_offense_ring.txt").read_text(encoding="utf-8")
    result = evaluate_item(item, real_pob_engine, build_path=str(ordinary))
    row = next(entry for entry in result["slot_comparisons"] if entry["pob_slot"] == "Ring 1")
    assert result["effect_catalog"]
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["evaluation_outcome"]["verdict"] == "MEANINGFUL_UPGRADE"
    assert row["restore"]["pass"] is True
