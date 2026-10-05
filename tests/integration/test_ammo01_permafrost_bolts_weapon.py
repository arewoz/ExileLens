"""AMMO-01: a crossbow ammo "Load" effect must not be the measured offense.

A tester's Witchhunter build saved PoB's *second* effect of the Permafrost Bolts gem as its main skill. Because of the
gem's display order that effect is "Load Permafrost Bolts" (``PermafrostBoltsAmmoPlayer``, stat set "Ammunition"), the
reload action whose own stat set is ``base_deal_no_damage``. PoB still reports a number for it (the damage the supports
add to the load action itself, ~332 CombinedDPS, speed 1.25 = 1 / 0.8 s cast time) and that number does not read the
weapon at all. A materially stronger crossbow therefore compared as exactly ``332.589`` -> ``332.589`` and surfaced as a
confident MEASURED_ZERO sidegrade, while PoB's real damage skill, "Permafrost Bolts" (``PermafrostBoltsPlayer``, stat
set "Projectile"), moved by tens of percent.

The fix lives where PoB itself draws the line: the load effect is the parameter carrier for its fired sibling
(``calcCrossbowAmmoStats``), so the bridge resolves the gem's damage-bearing effect as the main effect and discloses the
redirect. See ``docs/AMMO-01.md``.

The build is the tester's public Maxroll export (``maxroll.gg/poe2/pob/t77rg80g``) with the standard corpus
sanitization (per-item ``Unique ID`` lines, the PoB display cache and the import character hash removed). Its saved main
effect is left exactly as the tester had it. Every figure below is recomputed by the local PoB runtime; nothing is pinned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "ammo01_permafrost_bolts_witchhunter.xml"
SLOT = "Weapon 1"
LOAD_EFFECT = "PermafrostBoltsAmmoPlayer"
FIRED_EFFECT = "PermafrostBoltsPlayer"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

# The tester's newly crafted crossbow, exactly as the game copies it (three socketed runes are tagged "(rune)").
CANDIDATE = """Item Class: Crossbows
Rarity: Rare
Spirit Core
Stout Crossbow
--------
Quality: +20% (augmented)
Physical Damage: 42-169 (augmented)
Elemental Damage: 67-88 (fire), 65-99 (cold), 1-202 (lightning)
Critical Hit Chance: 5.00%
Attacks per Second: 1.63 (augmented)
Reload Time: 0.71 (augmented)
--------
Requires: Level 67, 74 Str, 74 Dex
--------
Sockets: S S S
--------
Item Level: 76
--------
18% increased Physical Damage (rune)
Adds 9 to 15 Cold Damage (rune)
Gain 5% of Damage as Extra Damage of all Elements (rune)
--------
Adds 1 to 202 Lightning Damage
Adds 56 to 84 Cold Damage
Adds 67 to 88 Fire Damage
+4 to Level of all Projectile Skills
Attacks Chain an additional time
5% increased Attack Speed
--------
Corrupted
"""


def _row(result: dict) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == SLOT)


def test_ammo_load_effect_is_resolved_to_the_fired_effect_and_disclosed(real_pob_engine) -> None:
    loaded = real_pob_engine.load_build(BUILD)
    identity = loaded["build"]["main_skill_identity"]
    # The file as saved selects effect 2 of the gem, the load action.
    assert 'mainActiveSkill="2"' in BUILD.read_text(encoding="utf-8")
    assert identity["skill_id"] == FIRED_EFFECT
    assert identity["skill_name"] == "Permafrost Bolts"
    assert identity["stat_set"] == "Projectile"
    assert identity["ammo_load_effect"] is False
    redirect = identity["effect_redirect"]
    assert redirect["reason"] == "AMMO_LOAD_DEALS_NO_DAMAGE"
    assert redirect["from_skill_id"] == LOAD_EFFECT
    assert redirect["from_stat_set"] == "Ammunition"
    assert redirect["to_skill_id"] == FIRED_EFFECT


@pytest.mark.parametrize("ignore_socketed_mods", [True, False], ids=["sockets-ignored", "sockets-counted"])
def test_stronger_crossbow_is_measured_on_the_fired_skill_not_a_false_measured_zero(
    real_pob_engine, ignore_socketed_mods: bool
) -> None:
    result = evaluate_item(
        CANDIDATE,
        real_pob_engine,
        build_path=str(BUILD),
        item_check_pro={"ignore_socketed_mods": ignore_socketed_mods},
    )
    row = _row(result)

    # State: the equipped crossbow is the previously equipped one, and the candidate really is Weapon 1 in the calc.
    assert row["baseline_item"]["name"] == "Blight Core, Bleak Crossbow"
    assert row["candidate_item"]["name"] == "Spirit Core"
    assert "Blight Core" in row["baseline"]["equipment"][SLOT]
    assert "Spirit Core" in row["candidate"]["equipment"][SLOT]
    assert row["restore"]["pass"] is True
    assert result["socket_normalization"]["enabled"] is ignore_socketed_mods

    # Semantics: both frames measure the fired skill, never the load action.
    for side in ("baseline", "candidate"):
        primary = row[side]["primary_skill"]
        assert primary["skill_id"] == FIRED_EFFECT
        assert primary["stat_set"] == "Projectile"
        assert row[side]["semantic"]["main_skill"] == "Permafrost Bolts"
    assert result["primary_metric"]["primary_skill"]["skill_id"] == FIRED_EFFECT

    # The weapon is read: PoB's own numbers move, and the old collapse to identical figures is gone.
    baseline, candidate = row["baseline"]["metrics"], row["candidate"]["metrics"]
    assert candidate["CombinedDPS"] > baseline["CombinedDPS"] > 0
    assert candidate["Speed"] != baseline["Speed"]
    assert (candidate["CombinedDPS"], candidate["AverageDamage"]) != (baseline["CombinedDPS"], baseline["AverageDamage"])
    offense = row["metric_profile"]["primary_offense"]
    assert offense["delta_kind"] == "MEASURED"
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["verdict"] == "OFFENSE_UPGRADE"


def test_resolved_effect_matches_what_a_player_gets_selecting_it_in_pob(real_pob_engine, tmp_path) -> None:
    """Independent gold standard: the same build with the fired effect selected in the file itself (no redirect)."""
    text = BUILD.read_text(encoding="utf-8")
    needle = 'mainActiveSkillCalcs="1" mainActiveSkill="2"'
    assert text.count(needle) == 1
    selected = tmp_path / "ammo01_fired_effect_selected.xml"
    selected.write_text(text.replace(needle, 'mainActiveSkillCalcs="1" mainActiveSkill="1"'), encoding="utf-8")

    redirected = _row(evaluate_item(CANDIDATE, real_pob_engine, build_path=str(BUILD)))
    gold = _row(evaluate_item(CANDIDATE, real_pob_engine, build_path=str(selected)))
    assert gold["baseline"]["primary_skill"].get("effect_redirect") is None
    for side in ("baseline", "candidate"):
        for field in ("CombinedDPS", "TotalDPS", "AverageDamage", "Speed"):
            assert redirected[side]["metrics"][field] == pytest.approx(gold[side]["metrics"][field], rel=1e-9)


def test_the_load_effect_is_restored_to_the_build_after_an_evaluation(real_pob_engine) -> None:
    real_pob_engine.load_build(BUILD)
    before = real_pob_engine.get_metrics()
    result = evaluate_item(CANDIDATE, real_pob_engine, build_path=str(BUILD))
    assert _row(result)["restore"]["pass"] is True
    after = real_pob_engine.get_metrics()
    assert after["fingerprint_hash"] == before["fingerprint_hash"]
    assert after["raw"]["CombinedDPS"] == before["raw"]["CombinedDPS"]
