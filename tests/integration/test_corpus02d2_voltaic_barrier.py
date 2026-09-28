"""CORPUS-02D2: the community-reported Voltaic Barrier build (pobb.in/1PuQGhYCY9Fv).

Fixture: ``fixtures/builds/public_corpus/corpus02d2_voltaic_barrier.xml`` -- a
Mercenary/Gemling Legionnaire retrieved from the reported pobb.in link's raw export
endpoint (base64 + zlib, decoded once during acquisition; see docs/CORPUS-02D2.md),
sanitized per docs/BUILD_CORPUS_SOURCES.md (``Unique ID:`` lines, the cached
``<PlayerStat>`` block, and the identifying ``<Import lastCharacterHash=...>`` removed;
nothing else changed -- verified against a fresh engine load producing identical
metrics before and after sanitization).

Two things are covered here, both real, both verified against the real PoB engine:

* **As exported** (``mainSocketGroup="3"``): PoB's own saved main skill is
  "Virtuous Barrier", a pure reservation/buff skill with zero calculated offense
  (no ``SkillType.Attack``/``Damage`` -- a barrier that accumulates protective
  "Motes", nothing else). Every weapon-related Item Check on this exact save state
  is truthfully PARTIAL/UNCERTAIN or a clearly-labeled substituted secondary
  component -- never a false confident verdict. This is the most direct, literal
  reproduction of "everything is uncertain" available from the retrieved export: a
  genuine PoB build-state characteristic (the player's last main-skill selection),
  not an ExileLens defect.
* **Voltaic Barrier selected as main** (``mainSocketGroup="9"``, an edited copy of
  the same authentic build -- same pattern CORPUS-02D1 used for its "Arrow" stat-set
  variant): Voltaic Barrier is a real weapon-scaling attack skill (100% of its
  physical damage converted to lightning, PoB data ``other.lua``
  ``skills["VoltaicBarrierPlayer"]``). With it selected, Item Check produces FULL,
  correctly measured, verdict-level results for weapon and defensive candidates,
  verified against independent fresh PoB reloads of edited builds, deterministic
  across repeated evaluations, and restores exactly -- including this build's 47
  weapon-set-conditional passive tree allocations (``weapon_set_alloc``), more than
  the existing ``core04_weapon_swap.xml`` fixture exercises.

No ExileLens defect specific to Voltaic Barrier or weapon-set interaction was
confirmed; see docs/CORPUS-02D2.md for the full investigation and what was ruled
out (mace-into-active-slot candidate substitution is truthful, restore is exact,
the PoB-calculated number matches an independent reload).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from exilelens.items.evaluation import evaluate_item

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "corpus02d2_voltaic_barrier.xml"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _equipped_item(build: Path, slot: str) -> str:
    root = ElementTree.parse(build).getroot()
    items = root.find("Items")
    assert items is not None
    raw = {item.get("id"): (item.text or "").strip() for item in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(entry for entry in items.findall("ItemSet") if entry.get("id") == active)
    item_id = next(entry.get("itemId") for entry in item_set.findall("Slot") if entry.get("name") == slot)
    assert item_id and item_id != "0"
    return raw[item_id]


def _edit(raw: str, *, remove: tuple[str, ...] = (), add: tuple[str, ...] = ()) -> str:
    lines = raw.splitlines()
    for pattern in remove:
        kept = [line for line in lines if not re.search(pattern, line)]
        assert len(kept) == len(lines) - 1, pattern
        lines = kept
    return "\n".join([*lines, *add]) + "\n"


def _variant(tmp_path: Path, name: str, *, main_socket_group: int | None = None,
             slots: dict[str, str] | None = None) -> Path:
    """Write an edited copy of the authentic build: main-skill selection and/or slot items."""
    text = BUILD.read_text(encoding="utf-8")
    if main_socket_group is not None:
        text, count = re.subn(r'mainSocketGroup="\d+"', f'mainSocketGroup="{main_socket_group}"', text, count=1)
        assert count == 1
    new_items = []
    for index, (slot, raw) in enumerate((slots or {}).items()):
        item_id = str(900 + index)
        new_items.append(f'\t\t<Item id="{item_id}">\n{raw.strip()}\n\t\t</Item>\n')
        text, count = re.subn(
            rf'(<Slot name="{re.escape(slot)}" itemPbURL="" itemId=")\d+("/>)', rf"\g<1>{item_id}\g<2>", text,
        )
        assert count == 1, slot
    if new_items:
        anchor = '\t\t<ItemSet title="Default" id="1"'
        assert text.count(anchor) == 1
        text = text.replace(anchor, "".join(new_items) + anchor, 1)
    path = tmp_path / f"{name}.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _fresh_metrics(engine, tmp_path: Path, name: str, **kwargs) -> dict:
    engine.load_build(_variant(tmp_path, name, **kwargs))
    return engine.get_metrics()["raw"]


def _close(actual: float, expected: float) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def _row(result: dict, slot: str) -> dict:
    return next(r for r in result["slot_comparisons"] if r["pob_slot"] == slot)


CROSSBOW = _equipped_item(BUILD, "Weapon 1")
RING_1 = _equipped_item(BUILD, "Ring 1")
AMULET = _equipped_item(BUILD, "Amulet")
CROSSBOW_UPGRADE = _edit(CROSSBOW, add=("200% increased Physical Damage",))
CROSSBOW_DOWNGRADE = _edit(CROSSBOW, remove=("49% increased Physical Damage",))
AMULET_LIFE_UPGRADE = _edit(AMULET, add=("+300 to maximum Life",))


def test_as_exported_main_skill_has_no_offense_and_item_checks_are_truthfully_uncertain(real_pob_engine) -> None:
    """Reproduces the retrieved export exactly: PoB's own saved main skill is a
    zero-damage reservation buff, so weapon Item Checks correctly refuse to claim
    confident offense -- never a false verdict."""
    loaded = real_pob_engine.load_build(BUILD)
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Virtuous Barrier"
    assert identity["skill_id"] == "VirtuousBarrierPlayer"
    metrics = loaded["metrics"]
    assert metrics["CombinedDPS"] == 0
    assert metrics["TotalDPS"] == 0

    result = evaluate_item(CROSSBOW_UPGRADE, real_pob_engine, build_path=str(BUILD))
    row = _row(result, "Weapon 1")
    outcome = row["evaluation_outcome"]
    assert row["baseline"]["primary_skill"]["skill_name"] == "Virtuous Barrier"
    # A truthful outcome: either an explicit substituted secondary component
    # (labelled, never presented as the main skill's own damage) or unmeasured --
    # both PARTIAL/UNCERTAIN, never a confident directional verdict manufactured
    # from a skill that deals no damage.
    assert outcome["evaluation_quality"] in {"PARTIAL", "FAILED"}
    assert outcome["verdict"] in {"UNCERTAIN", "NOT_EVALUATED"}
    assert outcome["verdict"] != "MEANINGFUL_UPGRADE"
    assert outcome["verdict"] != "MEANINGFUL_DOWNGRADE"
    assert row["restore"]["pass"] is True


def test_as_exported_defensive_candidate_measures_defense_even_without_offense(real_pob_engine) -> None:
    """A life-focused ring still gets a truthful, measured DEFENSE verdict on the
    as-exported (zero-offense main skill) build -- PARTIAL quality overall, but not
    every axis is thrown away."""
    ring_candidate = _edit(RING_1, add=("+300 to maximum Life",))
    result = evaluate_item(ring_candidate, real_pob_engine, build_path=str(BUILD))
    row = _row(result, "Ring 1")
    outcome = row["evaluation_outcome"]
    defense = outcome["item_impact"]["axes"]["DEFENSE"]
    assert defense["support"] == "MEASURED"
    assert defense["direction"] == "POSITIVE"
    assert outcome["evaluation_quality"] == "PARTIAL"
    assert row["restore"]["pass"] is True


def test_voltaic_barrier_as_main_measures_a_real_weapon_upgrade(real_pob_engine, tmp_path) -> None:
    """With PoB's main skill re-pinned to Voltaic Barrier (the skill the report
    names -- a real weapon-scaling attack skill), a crossbow upgrade is FULL /
    measured, verified against an independent fresh PoB reload of the edited build."""
    build = _variant(tmp_path, "vb_main", main_socket_group=9)
    loaded = real_pob_engine.load_build(build)
    identity = loaded["build"]["main_skill_identity"]
    assert identity["skill_name"] == "Voltaic Barrier"
    assert loaded["metrics"]["CombinedDPS"] > 0

    result = evaluate_item(CROSSBOW_UPGRADE, real_pob_engine, build_path=str(build))
    row = _row(result, "Weapon 1")
    outcome = row["evaluation_outcome"]
    assert row["baseline_primary_metric"]["pob_field"] == "CombinedDPS"
    assert row["baseline_item"]["name"] == "Rampart Raptor, Runemastered Tense Crossbow"
    assert outcome["evaluation_quality"] == "FULL"
    assert outcome["verdict"] == "MEANINGFUL_UPGRADE"
    offense = outcome["item_impact"]["axes"]["OFFENSE"]
    assert offense["support"] == "MEASURED"
    assert offense["direction"] == "POSITIVE"
    assert row["restore"]["pass"] is True

    fresh = _fresh_metrics(real_pob_engine, tmp_path, "vb_main_fresh_candidate",
                           main_socket_group=9, slots={"Weapon 1": CROSSBOW_UPGRADE})
    for field in ("CombinedDPS", "TotalDPS", "TotalEHP"):
        assert _close(row["candidate"]["metrics"][field], fresh[field]), field


def test_voltaic_barrier_downgrade_and_amulet_upgrade(real_pob_engine, tmp_path) -> None:
    """A weapon downgrade and an unrelated defensive amulet upgrade are both FULL /
    correctly directional, each verified against a fresh reload."""
    build = _variant(tmp_path, "vb_main2", main_socket_group=9)

    down_row = _row(evaluate_item(CROSSBOW_DOWNGRADE, real_pob_engine, build_path=str(build)), "Weapon 1")
    assert down_row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert down_row["evaluation_outcome"]["verdict"] == "MEANINGFUL_DOWNGRADE"
    assert down_row["restore"]["pass"] is True

    life_row = _row(evaluate_item(AMULET_LIFE_UPGRADE, real_pob_engine, build_path=str(build)), "Amulet")
    life_outcome = life_row["evaluation_outcome"]
    assert life_outcome["evaluation_quality"] == "FULL"
    assert life_outcome["item_impact"]["axes"]["DEFENSE"]["direction"] == "POSITIVE"
    assert life_outcome["item_impact"]["axes"]["OFFENSE"]["support"] == "MEASURED"
    assert life_outcome["item_impact"]["axes"]["OFFENSE"]["direction"] == "NEUTRAL"
    assert life_row["restore"]["pass"] is True

    for name, raw, row in (("down", CROSSBOW_DOWNGRADE, down_row), ("life", AMULET_LIFE_UPGRADE, life_row)):
        slot = "Weapon 1" if name == "down" else "Amulet"
        fresh = _fresh_metrics(real_pob_engine, tmp_path, f"vb_{name}_fresh", main_socket_group=9,
                               slots={slot: raw})
        for field in ("CombinedDPS", "TotalEHP"):
            assert _close(row["candidate"]["metrics"][field], fresh[field]), (name, field)


def test_repeated_evaluation_and_restore_with_weapon_set_conditional_passives(real_pob_engine, tmp_path) -> None:
    """This build allocates 47 weapon-set-conditional passive nodes (``alloc_mode``
    1/2 in ``weapon_set_alloc``) -- more than the existing weapon-swap fixture.
    Two consecutive evaluations must be identical, and the restored build must
    equal an independent fresh reload exactly, including every conditional node's
    contribution to the tree-derived stats."""
    build = _variant(tmp_path, "vb_restore", main_socket_group=9)
    baseline = real_pob_engine.load_build(build)["metrics"]

    first = evaluate_item(CROSSBOW_UPGRADE, real_pob_engine, build_path=str(build))
    second = evaluate_item(CROSSBOW_UPGRADE, real_pob_engine, build_path=str(build))
    first_row, second_row = _row(first, "Weapon 1"), _row(second, "Weapon 1")
    assert first_row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert second_row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert first_row["evaluation_outcome"]["final_score"] == second_row["evaluation_outcome"]["final_score"]
    assert first_row["evaluation_outcome"]["verdict"] == second_row["evaluation_outcome"]["verdict"]
    assert first_row["candidate"]["metrics"]["CombinedDPS"] == second_row["candidate"]["metrics"]["CombinedDPS"]
    assert first_row["restore"]["pass"] is True and second_row["restore"]["pass"] is True

    restored = real_pob_engine.get_metrics()["raw"]
    fresh = real_pob_engine.load_build(build)["metrics"]
    for key in sorted(set(restored) | set(fresh)):
        rv, fv = restored.get(key), fresh.get(key)
        if isinstance(rv, (int, float)) and isinstance(fv, (int, float)):
            assert math.isclose(rv, fv, rel_tol=1e-6, abs_tol=0.5), key
        else:
            assert rv == fv, key
    assert restored["TotalEHP"] == baseline["TotalEHP"]
    assert restored["CombinedDPS"] == baseline["CombinedDPS"]


def test_candidate_only_targets_the_active_weapon_slot_and_is_labelled_truthfully(real_pob_engine, tmp_path) -> None:
    """The build's inactive swap slot ("Weapon 1 Swap") holds a two-handed mace
    (Marohi Erqi). Submitting that exact item text as a candidate resolves only
    against the ACTIVE physical slot ("Weapon 1") -- ordinary Item Check never
    offers or silently writes into the inactive swap slot -- and the result
    truthfully names the crossbow it would actually replace, never the mace
    already equipped there. This is the current, documented scope of ordinary
    Item Check for a weapon-swap build (see docs/CORPUS-02D2.md); it is not a
    truthfulness violation, since nothing about which item is being compared is
    misrepresented."""
    build = _variant(tmp_path, "vb_slot_scope", main_socket_group=9)
    mace = _equipped_item(BUILD, "Weapon 1 Swap")
    result = evaluate_item(mace, real_pob_engine, build_path=str(build))

    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Weapon 1"}
    row = _row(result, "Weapon 1")
    assert row["baseline_item"]["name"] == "Rampart Raptor, Runemastered Tense Crossbow"
    # A real weapon swap, correctly and fully measured -- the scope limitation is
    # which slot gets offered, never the truthfulness of the resulting verdict.
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["restore"]["pass"] is True

    reloaded = real_pob_engine.load_build(build)
    inactive_mace_raw = _equipped_item(build, "Weapon 1 Swap")
    assert "Marohi Erqi" in inactive_mace_raw
    assert reloaded["build"]["use_second_weapon_set"] is False
