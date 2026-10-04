"""CORPUS-02F: Mortar Cannon and Ballista coverage on authentic public builds.

``corpus02f_mortar_cannon_warbringer.xml`` (Warrior / Warbringer, level 100): the saved main
group is Mortar Cannon + Cluster Grenade and the selected effect is Cluster Grenade, a
per-use ("show average") skill limited by its cooldown. ``corpus02f_ballista_warbringer.xml``
(Warrior / Warbringer, level 97): the saved main skill is another grenade; the Siege Ballista
group is calculated with its second effect, Artillery, selected by the test only. See
docs/CORPUS-02F.md.

Every numeric expectation is checked against an independent fresh PoB load of the same build
with the candidate equipped in its slot, never against ExileLens's own scoring. Candidates are
hand-written rares in the equipped item's shape.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
MORTAR = CORPUS / "corpus02f_mortar_cannon_warbringer.xml"
BALLISTA_SAVED = CORPUS / "corpus02f_ballista_warbringer.xml"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

FIELDS = ("TotalDPS", "CombinedDPS", "Speed", "Life", "TotalEHP", "IgniteDPS", "GroupTotemLimit")

# --------------------------------------------------------------------------- Mortar candidates (Ring 1)

_RING = """Rarity: RARE
Loath Whorl
Prismatic Ring
Item Level: 82
LevelReq: 60
Implicits: 1
+10% to all Elemental Resistances
{mods}"""
_PHYS = "Adds 22 to 37 Physical Damage to Attacks"
_FIRE = "Adds 33 to 58 Fire damage to Attacks"
_LIFE = "+70 to maximum Life"
_RES = "+9% to all Elemental Resistances\n+27% to Fire Resistance"
_FILLER = "18% increased Rarity of Items found"


def _ring(phys: str = _PHYS, fire: str = _FIRE, life: str = _LIFE, res: str = _RES, extra: str = _FILLER) -> str:
    return _RING.format(mods="\n".join(line for line in (phys, fire, life, res, extra) if line))


RINGS = {
    "fire_up": _ring(fire="Adds 90 to 140 Fire damage to Attacks"),
    "fire_down": _ring(fire="Adds 8 to 14 Fire damage to Attacks"),
    "cooldown": _ring(extra="20% increased Cooldown Recovery Rate"),
    "ignite": _ring(extra="30% chance to Ignite"),
    "totems": _ring(extra="+1 to maximum number of Summoned Totems"),
    "life": _ring(life="+170 to maximum Life"),
    "tradeoff": _ring(fire="Adds 90 to 140 Fire damage to Attacks", res="+9% to all Elemental Resistances"),
}

# --------------------------------------------------------------------------- Ballista candidates (Weapon 1)

_CROSSBOW = """Rarity: RARE
Pandemonium Core
Siege Crossbow
Item Level: 82
Quality: 20
Sockets: S S
Rune: Saqawal's Rune of the Sky
Rune: Thane Myrk's Rune of Summer
LevelReq: 79
Implicits: 5
{{enchant}}{{rune}}Bonded: +2% to Maximum Fire Resistance
{{enchant}}{{rune}}Adds 23 to 34 Fire Damage to Attacks against Ignited Enemies
{{enchant}}{{rune}}Bonded: 8% chance to gain an additional random Charge when you gain a Charge
{{enchant}}{{rune}}Gain 5% of Damage as Extra Damage of all Elements
Grenade Skills Fire an additional Projectile
154% increased Physical Damage
Adds 145 to 213 Fire Damage
122% increased Elemental Damage with Attacks
Gain 35 Mana per enemy killed
{totems}
{speed}"""


def _crossbow(totems: str = "+2 to maximum number of Summoned Ballista Totems", speed: str = "9% increased Attack Speed") -> str:
    return _CROSSBOW.format(totems=totems, speed=speed)


CROSSBOWS = {
    "attack_speed": _crossbow(speed="25% increased Attack Speed"),
    "slower": _crossbow(speed="1% increased Attack Speed"),
    "fewer_totems": _crossbow(totems="+0 to maximum number of Summoned Ballista Totems"),
    "more_totems": _crossbow(totems="+4 to maximum number of Summoned Ballista Totems"),
}
BALLISTA_RING = """Rarity: RARE
Loath Gyre
Breach Ring
Item Level: 82
LevelReq: 60
Implicits: 1
+20% to Maximum Quality
+93 to maximum Mana
Adds 35 to 63 Fire damage to Attacks
40% increased Fire Damage
+18% to all Elemental Resistances
+33% to Lightning Resistance
{tail}"""
BALLISTA_RINGS = {
    "life": BALLISTA_RING.format(tail="+22% to Fire and Chaos Resistances\n+120 to maximum Life"),
}


# --------------------------------------------------------------------------- helpers


def _variant(base: Path, tmp_path: Path, name: str, slot: str, raw: str) -> Path:
    """The build as the player would save it with ``raw`` equipped in ``slot``."""
    text = base.read_text(encoding="utf-8")
    text = text.replace("\t\t<ItemSet ", f'\t\t<Item id="900">\n{escape(raw)}\n\t\t</Item>\n\t\t<ItemSet ', 1)
    text, count = re.subn(rf'(<Slot itemId=")\d+(" itemPbURL="" name="{re.escape(slot)}"/>)', r"\g<1>900\g<2>", text)
    assert count == 1, slot
    path = tmp_path / f"{name}.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _select_ballista(tmp_path: Path) -> Path:
    """The saved Boba-style build with its Siege Ballista group's Artillery effect selected.

    Test-only change: ``mainSocketGroup`` 7 -> 9, and that group's ``mainActiveSkill`` /
    ``mainActiveSkillCalcs`` 1 -> 2 (Siege Ballista -> Artillery). Nothing else differs.
    """
    text = BALLISTA_SAVED.read_text(encoding="utf-8")
    assert 'mainSocketGroup="7"' in text
    text = text.replace('mainSocketGroup="7"', 'mainSocketGroup="9"', 1)
    groups = list(re.finditer(r"<Skill [^>]*>", text))
    tag = groups[8].group(0)
    assert "Siege Ballista" in text[groups[8].end() : groups[9].start()]
    edited = re.sub(r'mainActiveSkill="[^"]*"', 'mainActiveSkill="2"', tag)
    edited = re.sub(r'mainActiveSkillCalcs="[^"]*"', 'mainActiveSkillCalcs="2"', edited)
    text = text[: groups[8].start()] + edited + text[groups[8].end() :]
    path = tmp_path / "ballista_selected.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _fresh(engine, path: Path) -> dict:
    engine.load_build(path)
    return engine.get_metrics()["raw"]


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _close(actual, expected) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def _assert_matches_fresh(engine, base: Path, tmp_path: Path, name: str, slot: str, raw: str, row: dict) -> dict:
    reference = _fresh(engine, _variant(base, tmp_path, name, slot, raw))
    for field in FIELDS:
        measured = row["candidate"]["metrics"].get(field)
        if field in reference or measured is not None:
            assert _close(measured, reference[field]), (name, field, measured, reference.get(field))
    return reference


def _codes(outcome: dict) -> set[str]:
    return {reason["code"] for reason in (outcome.get("evaluation_quality_reasons") or [])}


@pytest.fixture(scope="module")
def ballista(tmp_path_factory) -> Path:
    return _select_ballista(tmp_path_factory.mktemp("ballista"))


# --------------------------------------------------------------------------- Mortar: identity and PoB semantics


def test_mortar_selected_effect_is_the_per_use_cluster_grenade(real_pob_engine) -> None:
    loaded = real_pob_engine.load_build(MORTAR)
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Cluster Grenade" and identity["damage_owner"] == "PLAYER"
    assert identity["gems"][0] == "Mortar Cannon" and identity["calculation_mode"] == "DIRECT"
    assert identity["show_average"] is True  # PoB: CombinedDPS is the per-use AverageDamage
    effects = {e["name"]: e for e in loaded["build"]["effect_catalog"]["effects"]}
    assert effects["Cluster Grenade"]["selected"] is True
    assert effects["Mortar Cannon"]["output"]["TotalDPS"] == 0  # the totem-summoning effect deals no damage

    metrics = real_pob_engine.get_metrics()["raw"]
    # PoB (CalcOffence): a showAverage skill's CombinedDPS is AverageDamage per use, not a rate.
    assert _close(metrics["CombinedDPS"], metrics["AverageDamage"])
    # TotalDPS is the per-second rate: per-use damage x uses per second (the cooldown limits it to
    # well under one use per second) x PoB's own skill DPS multiplier. Both authentic builds show
    # the same multiplier.
    assert metrics["Speed"] < 1.0 and metrics["TotalDPS"] < metrics["CombinedDPS"]
    assert _close(metrics["TotalDPS"] / (metrics["AverageDamage"] * metrics["Speed"]), 1.65)
    # PoB reports damage for one totem; the totem limit is a separate output of the summoning skill.
    assert metrics["GroupTotemLimit"] == 4
    invariants = effects["Cluster Grenade"]["invariants"]
    assert invariants["Cooldown"] == pytest.approx(1 / metrics["Speed"])


def test_mortar_scores_the_per_second_hit_rate_not_the_per_use_average(real_pob_engine) -> None:
    result = evaluate_item(RINGS["fire_up"], real_pob_engine, build_path=str(MORTAR))
    metric = result["primary_metric"]
    assert metric["pob_field"] == "TotalDPS" and metric["semantic_quantity"] == "HIT_DPS"
    assert metric["reason"].startswith("showAverage")
    assert _row(result, "Ring 1")["evaluation_outcome"]["evaluation_quality"] == "FULL"


# --------------------------------------------------------------------------- Mortar: FULL verdicts against fresh loads


def test_mortar_offense_upgrade_and_downgrade_match_fresh_loads(real_pob_engine, tmp_path: Path) -> None:
    up = evaluate_item(RINGS["fire_up"], real_pob_engine, build_path=str(MORTAR))
    row = _row(up, "Ring 1")
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_UPGRADE"
    reference = _assert_matches_fresh(real_pob_engine, MORTAR, tmp_path, "fire_up", "Ring 1", RINGS["fire_up"], row)
    assert reference["TotalDPS"] > row["baseline"]["metrics"]["TotalDPS"] * 1.05
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "POSITIVE"

    down = evaluate_item(RINGS["fire_down"], real_pob_engine, build_path=str(MORTAR))
    row = _row(down, "Ring 1")
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] in {"MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE"}
    reference = _assert_matches_fresh(real_pob_engine, MORTAR, tmp_path, "fire_down", "Ring 1", RINGS["fire_down"], row)
    assert reference["TotalDPS"] < row["baseline"]["metrics"]["TotalDPS"]
    assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "NEGATIVE"


def test_cooldown_recovery_reaches_the_rate_that_the_per_use_average_cannot_show(real_pob_engine, tmp_path: Path) -> None:
    """Regression: PoB's CombinedDPS is per use, so it never moves for a cooldown-only change."""
    result = evaluate_item(RINGS["cooldown"], real_pob_engine, build_path=str(MORTAR))
    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    reference = _assert_matches_fresh(real_pob_engine, MORTAR, tmp_path, "cooldown", "Ring 1", RINGS["cooldown"], row)
    baseline = row["baseline"]["metrics"]
    assert reference["Speed"] > baseline["Speed"]
    assert _close(reference["CombinedDPS"], baseline["CombinedDPS"])  # the old metric was blind to it
    assert reference["TotalDPS"] > baseline["TotalDPS"] * 1.05
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] == "MEANINGFUL_UPGRADE"


def test_defence_only_ring_leaves_the_mortar_damage_untouched(real_pob_engine, tmp_path: Path) -> None:
    result = evaluate_item(RINGS["life"], real_pob_engine, build_path=str(MORTAR))
    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    reference = _assert_matches_fresh(real_pob_engine, MORTAR, tmp_path, "life", "Ring 1", RINGS["life"], row)
    baseline = row["baseline"]["metrics"]
    assert _close(reference["TotalDPS"], baseline["TotalDPS"]) and reference["Life"] > baseline["Life"]
    assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] in {"MINOR_UPGRADE", "MEANINGFUL_UPGRADE"}
    axes = outcome["item_impact"]["axes"]
    assert axes["DEFENSE"]["direction"] == "POSITIVE" and axes["OFFENSE"]["direction"] != "POSITIVE"


def test_offense_gain_with_a_lost_resistance_cap_is_a_flagged_tradeoff(real_pob_engine, tmp_path: Path) -> None:
    result = evaluate_item(RINGS["tradeoff"], real_pob_engine, build_path=str(MORTAR))
    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    reference = _assert_matches_fresh(real_pob_engine, MORTAR, tmp_path, "tradeoff", "Ring 1", RINGS["tradeoff"], row)
    assert reference["TotalDPS"] > row["baseline"]["metrics"]["TotalDPS"] * 1.05
    assert outcome["evaluation_quality"] == "FULL" and outcome["item_impact"]["pattern"] == "TRADEOFF"
    assert {g["code"] for g in outcome["guardrails_applied"]} == {"RES_CAP_LOST"}
    assert outcome["verdict"] == "MINOR_DOWNGRADE"


# --------------------------------------------------------------------------- Mortar: unmeasured mechanics are not FULL


def test_ignite_only_change_is_not_claimed_as_measured(real_pob_engine, tmp_path: Path) -> None:
    """The scored hit rate leaves out this skill's ignite; PoB moved ignite, so the result is PARTIAL."""
    result = evaluate_item(RINGS["ignite"], real_pob_engine, build_path=str(MORTAR))
    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    reference = _assert_matches_fresh(real_pob_engine, MORTAR, tmp_path, "ignite", "Ring 1", RINGS["ignite"], row)
    baseline = row["baseline"]["metrics"]
    assert _close(reference["TotalDPS"], baseline["TotalDPS"]) and reference["IgniteDPS"] > baseline["IgniteDPS"] * 1.5
    assert outcome["evaluation_quality"] == "PARTIAL" and outcome["verdict"] == "UNCERTAIN"
    assert "PER_USE_DOT_NOT_MEASURED" in _codes(outcome)


def test_a_changed_totem_count_is_not_claimed_as_measured(real_pob_engine, tmp_path: Path) -> None:
    result = evaluate_item(RINGS["totems"], real_pob_engine, build_path=str(MORTAR))
    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    reference = _assert_matches_fresh(real_pob_engine, MORTAR, tmp_path, "totems", "Ring 1", RINGS["totems"], row)
    assert row["baseline"]["metrics"]["GroupTotemLimit"] == 4 and reference["GroupTotemLimit"] == 5
    assert outcome["evaluation_quality"] == "PARTIAL" and outcome["verdict"] == "UNCERTAIN"
    assert "TOTEM_LIMIT_CHANGED" in _codes(outcome)


# --------------------------------------------------------------------------- Ballista


def test_ballista_group_is_calculated_through_its_artillery_effect(real_pob_engine, ballista: Path) -> None:
    saved = real_pob_engine.load_build(BALLISTA_SAVED)
    assert saved["build"]["main_skill_identity"]["skill_name"] == "Explosive Grenade"  # the saved main skill

    loaded = real_pob_engine.load_build(ballista)
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Artillery" and identity["damage_owner"] == "PLAYER"
    assert identity["gems"][0] == "Siege Ballista" and identity["index"] == 9
    effects = {e["name"]: e for e in loaded["build"]["effect_catalog"]["effects"]}
    assert effects["Siege Ballista"]["output"]["TotalDPS"] == 0  # the summoning effect deals no damage
    assert effects["Siege Ballista"]["invariants"]["ActiveTotemLimit"] == 4

    metrics = real_pob_engine.get_metrics()["raw"]
    # A plain per-second skill: TotalDPS is one ballista's damage, CombinedDPS equals it.
    assert _close(metrics["TotalDPS"], metrics["AverageDamage"] * metrics["Speed"])
    assert _close(metrics["CombinedDPS"], metrics["TotalDPS"])
    assert metrics["GroupTotemLimit"] == 4  # the summoning effect's limit, not the fired skill's 1


def test_ballista_weapon_offense_verdicts_match_fresh_loads(real_pob_engine, ballista: Path, tmp_path: Path) -> None:
    for name, expected, direction in (
        ("attack_speed", {"MEANINGFUL_UPGRADE"}, "POSITIVE"),
        ("slower", {"MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE"}, "NEGATIVE"),
    ):
        result = evaluate_item(CROSSBOWS[name], real_pob_engine, build_path=str(ballista))
        assert result["primary_metric"]["pob_field"] == "TotalDPS"
        row = _row(result, "Weapon 1")
        outcome = row["evaluation_outcome"]
        reference = _assert_matches_fresh(real_pob_engine, ballista, tmp_path, name, "Weapon 1", CROSSBOWS[name], row)
        baseline = row["baseline"]["metrics"]
        assert (reference["TotalDPS"] > baseline["TotalDPS"]) == (direction == "POSITIVE"), name
        assert outcome["evaluation_quality"] == "FULL" and outcome["verdict"] in expected, name
        assert outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == direction


@pytest.mark.parametrize("name", ["fewer_totems", "more_totems"])
def test_ballista_totem_count_change_is_not_claimed_as_measured(real_pob_engine, ballista: Path, tmp_path: Path, name: str) -> None:
    """PoB's Artillery damage is one ballista's; the item changes how many may exist."""
    result = evaluate_item(CROSSBOWS[name], real_pob_engine, build_path=str(ballista))
    row = _row(result, "Weapon 1")
    outcome = row["evaluation_outcome"]
    reference = _assert_matches_fresh(real_pob_engine, ballista, tmp_path, name, "Weapon 1", CROSSBOWS[name], row)
    baseline = row["baseline"]["metrics"]
    assert baseline["GroupTotemLimit"] == 4 and reference["GroupTotemLimit"] != 4
    assert _close(reference["TotalDPS"], baseline["TotalDPS"])  # PoB's damage figure does not move
    assert outcome["evaluation_quality"] == "PARTIAL" and outcome["verdict"] == "UNCERTAIN"
    assert "TOTEM_LIMIT_CHANGED" in _codes(outcome)


def test_ballista_defence_ring_is_measured_without_inventing_offense(real_pob_engine, ballista: Path, tmp_path: Path) -> None:
    result = evaluate_item(BALLISTA_RINGS["life"], real_pob_engine, build_path=str(ballista))
    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    reference = _assert_matches_fresh(real_pob_engine, ballista, tmp_path, "ring_life", "Ring 1", BALLISTA_RINGS["life"], row)
    baseline = row["baseline"]["metrics"]
    assert _close(reference["TotalDPS"], baseline["TotalDPS"]) and reference["Life"] > baseline["Life"]
    assert outcome["evaluation_quality"] == "FULL"


# --------------------------------------------------------------------------- restore


def test_repeated_evaluations_are_identical_and_restore_the_build(real_pob_engine) -> None:
    real_pob_engine.load_build(MORTAR)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    original_equipment = real_pob_engine.get_equipment()

    first = evaluate_item(RINGS["cooldown"], real_pob_engine, build_path=str(MORTAR))
    evaluate_item(RINGS["ignite"], real_pob_engine, build_path=str(MORTAR))
    second = evaluate_item(RINGS["cooldown"], real_pob_engine, build_path=str(MORTAR))

    a, b = _row(first, "Ring 1"), _row(second, "Ring 1")
    assert a["evaluation_outcome"]["evaluation_quality"] == b["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert a["evaluation_outcome"]["verdict"] == b["evaluation_outcome"]["verdict"]
    assert a["evaluation_outcome"]["final_score"] == b["evaluation_outcome"]["final_score"]
    assert a["candidate"]["metrics"]["TotalDPS"] == b["candidate"]["metrics"]["TotalDPS"]
    assert a["restore"]["pass"] is True and b["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash
    assert real_pob_engine.get_equipment() == original_equipment
