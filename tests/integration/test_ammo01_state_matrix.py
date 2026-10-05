"""AMMO-01 — state boundaries, socket-normalization independence and negative controls (real PoB).

The resolver (``settle_main_effect``) must run at every transition where the selected effect can change and must never
leak a redirect to another state, build or cache entry. Pairwise coverage only: load, loadout switch, item-set switch,
candidate replacement, calculation, restore; normalization OFF/ON against different rune counts on both sides.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from exilelens.items.evaluation import evaluate_item
from exilelens.items.primary_metric import OffenseKind, resolve_primary_metric
from tests.integration.test_ammo01_permafrost_bolts_weapon import BUILD, CANDIDATE, FIRED_EFFECT, LOAD_EFFECT

pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
LOAD_SAVED = 'mainActiveSkillCalcs="1" mainActiveSkill="2" label=""'
FIRED_SAVED = 'mainActiveSkillCalcs="1" mainActiveSkill="1" label=""'
ALT = "Alt {Alt}"


def _block(text: str, start: str, end: str) -> tuple[int, int]:
    first = text.index(start)
    return first, text.index(end, first) + len(end)


def _two_loadout_build(tmp_path: Path, *, default_saves: str, alt_saves: str, name: str) -> Path:
    """The tester's build with a second linked loadout ("Alt {Alt}": skill set, item set, config set, tree spec).

    The group-8 Permafrost gem saves ``default_saves`` in the default skill set and ``alt_saves`` in the alt one.
    """
    text = BUILD.read_text(encoding="utf-8")
    assert text.count(LOAD_SAVED) == 1
    text = text.replace(LOAD_SAVED, default_saves)
    s, e = _block(text, '<SkillSet id="1">', "</SkillSet>")
    first = text[s:e]
    second = first.replace('<SkillSet id="1">', f'<SkillSet id="2" title="{ALT}">').replace(default_saves, alt_saves)
    text = text[:s] + first.replace('<SkillSet id="1">', '<SkillSet id="1" title="Default">') + "\n\t\t" + second + text[e:]
    s, e = _block(text, '<ItemSet id="1"', "</ItemSet>")
    item_set = text[s:e]
    copy = item_set.replace('<ItemSet id="1" useSecondWeaponSet="false" title="Default">',
                            f'<ItemSet id="2" useSecondWeaponSet="false" title="{ALT}">')
    assert copy != item_set
    text = text[:e] + "\n\t\t" + copy + text[e:]
    s, e = _block(text, '<ConfigSet title="Default" id="1">', "</ConfigSet>")
    config = text[s:e]
    text = text[:e] + "\n\t\t" + config.replace('<ConfigSet title="Default" id="1">', f'<ConfigSet title="{ALT}" id="2">') + text[e:]
    s, e = _block(text, "<Spec ", "</Spec>")
    spec = text[s:e]
    text = text[:s] + spec.replace("<Spec ", '<Spec title="Default" ', 1) + "\n\t\t" + spec.replace("<Spec ", f'<Spec title="{ALT}" ', 1) + text[e:]
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _identity(engine) -> dict:
    return engine.get_build_info()["build"]["main_skill_identity"]


def _resolved(identity: dict, *, redirected: bool) -> None:
    assert identity["skill_id"] == FIRED_EFFECT and identity["stat_set"] == "Projectile"
    assert identity["ammo_load_effect"] is False and identity["damage_target"] is True
    assert bool(identity.get("effect_redirect")) is redirected
    if redirected:
        assert identity["effect_redirect"]["from_skill_id"] == LOAD_EFFECT


def _row(result: dict) -> dict:
    return next(r for r in result["slot_comparisons"] if r["pob_slot"] == "Weapon 1")


# ----------------------------------------------------------------------------------------------- state transitions


@pytest.mark.parametrize(
    ("default_saves", "alt_saves"),
    [(FIRED_SAVED, LOAD_SAVED), (LOAD_SAVED, FIRED_SAVED)],
    ids=["default-fired/alt-load", "default-load/alt-fired"],
)
def test_the_resolver_runs_at_every_transition_and_never_leaks_across_states(
    real_pob_engine, tmp_path: Path, default_saves: str, alt_saves: str
) -> None:
    path = _two_loadout_build(tmp_path, default_saves=default_saves, alt_saves=alt_saves, name="loadouts.xml")
    default_is_load = default_saves == LOAD_SAVED

    real_pob_engine.load_build(path)  # initial load
    _resolved(_identity(real_pob_engine), redirected=default_is_load)
    fingerprint = real_pob_engine.get_metrics()["fingerprint_hash"]

    real_pob_engine.set_active_loadout(ALT)  # loadout switch changes the skill set, hence the saved effect
    _resolved(_identity(real_pob_engine), redirected=not default_is_load)

    real_pob_engine.set_active_loadout("Default")  # back: no stale identity from the other state
    _resolved(_identity(real_pob_engine), redirected=default_is_load)
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == fingerprint

    real_pob_engine.set_active_item_set("2")  # an item-set switch alone cannot invent or drop a redirect
    _resolved(_identity(real_pob_engine), redirected=default_is_load)
    real_pob_engine.set_active_item_set("1")
    _resolved(_identity(real_pob_engine), redirected=default_is_load)
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == fingerprint


@pytest.mark.parametrize("loadout", ["Default", ALT])
def test_candidate_replacement_after_a_loadout_switch_measures_the_fired_effect_and_restores(
    real_pob_engine, tmp_path: Path, loadout: str
) -> None:
    path = _two_loadout_build(tmp_path, default_saves=FIRED_SAVED, alt_saves=LOAD_SAVED, name="loadouts_eval.xml")
    real_pob_engine.load_build(path)
    before_fingerprint = real_pob_engine.get_metrics()["fingerprint_hash"]

    result = evaluate_item(CANDIDATE, real_pob_engine, build_path=str(path), loadout=loadout)
    row = _row(result)
    for side in ("baseline", "candidate"):
        assert row[side]["primary_skill"]["skill_id"] == FIRED_EFFECT
        assert row[side]["semantic"]["loadout"] == loadout
    assert row["candidate"]["metrics"]["CombinedDPS"] > row["baseline"]["metrics"]["CombinedDPS"] > 0
    assert row["restore"]["pass"] is True
    assert result["state_integrity"]["recovery_used"] is False

    # Restore returns to the original selection and state: the engine still sits in the requested loadout with the
    # same redirect status it had before the candidate was measured.
    _resolved(_identity(real_pob_engine), redirected=loadout == ALT)
    real_pob_engine.set_active_loadout("Default")
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == before_fingerprint


def test_a_redirected_loadout_equals_the_same_loadout_with_the_fired_effect_saved(real_pob_engine, tmp_path: Path) -> None:
    """Same environment, two files: the Alt skill set saves the load action in one and the fired effect in the other.

    (Different loadouts of one file are not comparable: the synthesized Alt config/tree copy is its own environment.)"""
    load_saved = _two_loadout_build(tmp_path, default_saves=FIRED_SAVED, alt_saves=LOAD_SAVED, name="alt_load.xml")
    fired_saved = _two_loadout_build(tmp_path, default_saves=FIRED_SAVED, alt_saves=FIRED_SAVED, name="alt_fired.xml")
    redirected = _row(evaluate_item(CANDIDATE, real_pob_engine, build_path=str(load_saved), loadout=ALT))
    explicit = _row(evaluate_item(CANDIDATE, real_pob_engine, build_path=str(fired_saved), loadout=ALT))
    assert redirected["baseline"]["primary_skill"].get("effect_redirect")
    assert not explicit["baseline"]["primary_skill"].get("effect_redirect")
    for side in ("baseline", "candidate"):
        for field in ("CombinedDPS", "TotalDPS", "AverageDamage", "Speed"):
            assert redirected[side]["metrics"][field] == pytest.approx(explicit[side]["metrics"][field], rel=1e-9)


def test_a_redirect_never_leaks_across_builds_revisions_or_cached_reloads(real_pob_engine, tmp_path: Path) -> None:
    real_pob_engine.load_build(BUILD)
    _resolved(_identity(real_pob_engine), redirected=True)
    fingerprint = real_pob_engine.get_metrics()["fingerprint_hash"]

    other = real_pob_engine.load_build(CORPUS / "core04_melee_weapon.xml")["build"]["main_skill_identity"]
    assert not other.get("effect_redirect") and other["ammo_load_effect"] is False  # nothing carried over

    real_pob_engine.load_build(BUILD)  # a fresh parse of the same bytes: redirected again, same fingerprint
    _resolved(_identity(real_pob_engine), redirected=True)
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == fingerprint

    again = real_pob_engine.load_build(BUILD)  # same revision: PoB's cached build is reused, still settled
    assert again["build"]["main_skill_identity"]["effect_redirect"]["from_skill_id"] == LOAD_EFFECT
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == fingerprint

    fired = tmp_path / "fired_saved.xml"  # different bytes (the fired effect saved): a new revision, no redirect
    fired.write_text(BUILD.read_text(encoding="utf-8").replace(LOAD_SAVED, FIRED_SAVED), encoding="utf-8")
    real_pob_engine.load_build(fired)
    _resolved(_identity(real_pob_engine), redirected=False)


# ------------------------------------------------------------------------------- socket normalization independence


def _without_rune_lines(text: str) -> str:
    lines = [line for line in text.split("\n") if not line.rstrip().endswith("(rune)")]
    return "\n".join(lines)


def _one_rune(text: str) -> str:
    kept, seen = [], False
    for line in text.split("\n"):
        if line.rstrip().endswith("(rune)"):
            if seen:
                continue
            seen = True
        kept.append(line)
    return "\n".join(kept)


@pytest.mark.parametrize("normalize", [False, True], ids=["normalization-off", "normalization-on"])
@pytest.mark.parametrize("variant", ["3-runes", "1-rune", "0-runes"])
def test_effect_resolution_and_socket_normalization_are_independent(real_pob_engine, normalize: bool, variant: str) -> None:
    candidate = {"3-runes": CANDIDATE, "1-rune": _one_rune(CANDIDATE), "0-runes": _without_rune_lines(CANDIDATE)}[variant]
    runes = {"3-runes": 3, "1-rune": 1, "0-runes": 0}[variant]
    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD), item_check_pro={"ignore_socketed_mods": normalize})
    row = _row(result)
    normalization = result["socket_normalization"]
    assert normalization["enabled"] is normalize
    assert normalization["candidate_normalized"] is (normalize and runes > 0)
    assert normalization["candidate_removed_count"] == (runes if normalize else 0)
    assert normalization["baseline_normalized_slots"] == (["Weapon 1"] if normalize else [])
    # the candidate really replaced the equipped crossbow, whatever the normalization did to either side
    assert "Blight Core" in row["baseline"]["equipment"]["Weapon 1"]
    assert "Spirit Core" in row["candidate"]["equipment"]["Weapon 1"]
    assert row["baseline"]["equipment"]["Weapon 1"] != row["candidate"]["equipment"]["Weapon 1"]
    # the right effect is measured and the build restores
    for side in ("baseline", "candidate"):
        assert row[side]["primary_skill"]["skill_id"] == FIRED_EFFECT
    assert row["metric_profile"]["primary_offense"]["delta_kind"] == "MEASURED"
    assert row["restore"]["pass"] is True


def test_normalization_does_not_change_which_numbers_a_rune_free_candidate_produces(real_pob_engine) -> None:
    """With normalization ON every rune line is stripped, so 3 runes and 0 runes must calculate identically."""
    runs = {}
    for variant, candidate in (("3", CANDIDATE), ("0", _without_rune_lines(CANDIDATE))):
        row = _row(evaluate_item(candidate, real_pob_engine, build_path=str(BUILD), item_check_pro={"ignore_socketed_mods": True}))
        runs[variant] = (row["baseline"]["metrics"]["CombinedDPS"], row["candidate"]["metrics"]["CombinedDPS"])
    assert runs["3"] == pytest.approx(runs["0"], rel=1e-9)


# --------------------------------------------------------------------------------------------- negative controls


def _identity_of(engine, path: Path) -> dict:
    return engine.load_build(path)["build"]["main_skill_identity"]


def _select_ballista(tmp_path: Path, selector: int) -> Path:
    """CORPUS-02F's Boba build with the Siege Ballista group main and ``selector`` saved (the file is otherwise unchanged)."""
    text = (CORPUS / "corpus02f_ballista_warbringer.xml").read_text(encoding="utf-8")
    text = text.replace('mainSocketGroup="7"', 'mainSocketGroup="9"', 1)
    groups = list(re.finditer(r"<Skill [^>]*>", text))
    assert "Siege Ballista" in text[groups[8].end(): groups[9].start()]
    tag = re.sub(r'mainActiveSkill="[^"]*"', f'mainActiveSkill="{selector}"', groups[8].group(0))
    tag = re.sub(r'mainActiveSkillCalcs="[^"]*"', f'mainActiveSkillCalcs="{selector}"', tag)
    path = tmp_path / f"ballista_{selector}.xml"
    path.write_text(text[: groups[8].start()] + tag + text[groups[8].end():], encoding="utf-8")
    return path


def test_negative_control_siege_ballista_is_never_redirected_and_keeps_its_measurable_effect(real_pob_engine, tmp_path: Path) -> None:
    projectile = _identity_of(real_pob_engine, _select_ballista(tmp_path, 2))  # the effect CORPUS-02F measures
    assert projectile["skill_id"] == "SiegeBallistaProjectilePlayer" and projectile["damage_target"] is True
    assert not projectile.get("effect_redirect") and projectile["ammo_load_effect"] is False
    assert real_pob_engine.get_metrics()["raw"]["CombinedDPS"] > 0

    placement = _identity_of(real_pob_engine, _select_ballista(tmp_path, 1))  # the totem-placement effect: declared no-damage
    assert placement["skill_id"] == "SiegeBallistaPlayer"
    assert not placement.get("effect_redirect")  # the resolver is ammo-only: it never guesses a sibling for a totem
    assert placement["ammo_load_effect"] is False
    assert placement["damage_target"] is False and placement["damage_target_reason"] == "DECLARES_NO_DAMAGE"
    raw = real_pob_engine.get_metrics()["raw"]
    selection = resolve_primary_metric({"main_skill_identity": placement}, raw)
    assert selection.selected == OffenseKind.UNRESOLVED  # PoB reports no offense for it: refused, not mismeasured


@pytest.mark.parametrize(
    ("fixture", "skill"),
    [
        ("core04_melee_weapon.xml", "Sunder"),  # a normal single-effect attack
        ("core04_mixed_hit_ailment.xml", "Comet"),  # a normal single-effect spell (with hit + ailment output)
        ("core04_poison_ailment.xml", "Poisonburst Arrow"),  # a stat set that declares no hit damage but IS measured
    ],
)
def test_negative_control_ordinary_skills_are_untouched(real_pob_engine, fixture: str, skill: str) -> None:
    identity = _identity_of(real_pob_engine, CORPUS / fixture)
    assert identity["skill_name"] == skill
    assert not identity.get("effect_redirect")
    assert identity["ammo_load_effect"] is False and identity["damage_target"] is True and not identity["damage_target_reason"]
    selection = resolve_primary_metric({"main_skill_identity": identity}, real_pob_engine.get_metrics()["raw"])
    assert selection.selected != OffenseKind.UNRESOLVED


def test_negative_control_multi_effect_gem_already_on_its_damaging_effect(real_pob_engine, tmp_path: Path) -> None:
    fired = tmp_path / "fired_saved.xml"
    fired.write_text(BUILD.read_text(encoding="utf-8").replace(LOAD_SAVED, FIRED_SAVED), encoding="utf-8")
    _resolved(_identity_of(real_pob_engine, fired), redirected=False)
