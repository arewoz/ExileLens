"""CORPUS-02A: real-build regression and Item Check coverage for a Giant's Blood build.

Fixture: ``fixtures/builds/public_corpus/corpus02_giants_blood_shield.xml`` -- a
Mercenary/Gemling Legionnaire using Supercharged Slam with a *two-handed* mace and
a tower shield at the same time (the Giant's Blood keystone), where the shield is
the unique Chernobog's Pillar ("Gain 1% of damage as Fire damage per 1% Chance to
Block"). See docs/CORPUS-02A.md for provenance and the investigation.

Two things are covered here:

* The community report that ExileLens failed on this character with an error
  involving ``get_tree_snapshot``. Reproduced against v0.3.0b1: the tree snapshot
  is the first worker response carrying non-ASCII text (passive "The Mórrigan's
  Guidance"), and a worker writing protocol output in a non-UTF-8 Windows code
  page (cp1251, cp932, ...) died with UnicodeEncodeError, surfacing as "PoB
  worker process ended unexpectedly during 'get_tree_snapshot'". Fixed since
  v0.4.0b1 (worker stdio forced to UTF-8); the regression test below drives the
  real controller baseline-reload path with the child forced to cp1251.
* Item Check behavior this corpus did not cover: two-hand candidates that PoB
  lets coexist with a shield, a two-hander PoB does not allow beside a shield,
  and a unique-shield interaction whose loss PoB measures but whose damage
  semantics change (hit+ignite -> hit only), which must stay UNCERTAIN.

Every numeric expectation is checked against an independent cold PoB load of an
edited copy of the build, never against ExileLens's own scoring output.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import pytest

from exilelens.items.evaluation import evaluate_item


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "corpus02_giants_blood_shield.xml"
ONEHAND_BUILD = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_onehand_weapon.xml"
CHERNOBOG = "Chernobog's Pillar, Blacksteel Tower Shield"
MACE = "Fate Ram, Tawhoan Greatclub"
TALISMAN = "Hysseg's Claw, Familial Talisman"
NON_ASCII_NODE_ID = 27773
NON_ASCII_NODE_NAME = "The M\u00f3rrigan's Guidance"
REPLACEMENT_CHARACTER = chr(0xFFFD)
DIRECTIONAL_UPGRADES = {"MINOR_UPGRADE", "MEANINGFUL_UPGRADE", "MAJOR_UPGRADE"}
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _equipped_item(path: Path, slot: str) -> str:
    root = ElementTree.parse(path).getroot()
    items = root.find("Items")
    assert items is not None
    raw = {item.get("id"): (item.text or "").strip() for item in items.findall("Item")}
    active = items.get("activeItemSet")
    item_set = next(entry for entry in items.findall("ItemSet") if entry.get("id") == active)
    item_id = next(entry.get("itemId") for entry in item_set.findall("Slot") if entry.get("name") == slot)
    assert item_id and item_id != "0"
    return raw[item_id]


def _two_hand_upgrade() -> str:
    return _equipped_item(BUILD, "Weapon 1") + "\n40% increased Physical Damage\n"


def _plain_tower_shield() -> str:
    return _equipped_item(ONEHAND_BUILD, "Weapon 2")


def _talisman() -> str:
    return _equipped_item(BUILD, "Weapon 1 Swap")


def _fresh_metrics(engine, tmp_path: Path, name: str, slots: dict[str, str | None]) -> dict:
    """Cold-load an edited copy of the build and return PoB's own raw metrics.

    ``slots`` maps a slot name to the raw item text to equip there, or ``None``
    to leave the slot empty. This is the independent PoB reference for Item
    Check's in-place candidate transaction.
    """
    text = BUILD.read_text(encoding="utf-8")
    new_items = []
    for index, (slot, raw) in enumerate(slots.items()):
        item_id = "0"
        if raw is not None:
            item_id = str(900 + index)
            new_items.append(f'\t\t<Item id="{item_id}">\n{escape(raw)}\n\t\t</Item>\n')
        text, count = re.subn(
            rf'(<Slot itemId=")\d+(" itemPbURL="" name="{re.escape(slot)}"/>)',
            rf"\g<1>{item_id}\g<2>",
            text,
        )
        assert count == 1, slot
    text = text.replace('\t\t<ItemSet id="1"', "".join(new_items) + '\t\t<ItemSet id="1"', 1)
    variant = tmp_path / f"{name}.xml"
    variant.write_text(text, encoding="utf-8")
    engine.load_build(variant)
    return engine.get_metrics()["raw"]


def _row(result: dict, slot: str) -> dict:
    return next(row for row in result["slot_comparisons"] if row["pob_slot"] == slot)


def _axes(row: dict) -> dict[str, str]:
    axes = row["evaluation_outcome"]["item_impact"]["axes"]
    return {name: axis["direction"] for name, axis in axes.items()}


def _close(actual: float, expected: float) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-6)


def test_tree_snapshot_survives_non_utf8_worker_code_page(pob_config, monkeypatch) -> None:
    """Regression for the community `get_tree_snapshot` failure (see module docstring).

    The child worker inherits PYTHONIOENCODING=cp1251, which overrides Python's
    UTF-8 mode. Before v0.4.0b1 this exact configuration killed the worker while
    writing the tree snapshot. The test drives the real controller path
    (baseline reload -> Item Check) and checks the non-ASCII node name arrives
    intact, which also guards the silent U+FFFD corruption seen under cp1252.
    """
    from exilelens.app.controller import BaselineReloadRequest, EvaluationRequest, _EvaluationWorker
    from exilelens.engine import Engine

    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    with Engine(pob_config, use_subprocess=True) as engine:
        worker = _EvaluationWorker()
        worker.configure(engine, str(BUILD), "MAP")
        baselines: list[tuple[int, object, object]] = []
        evaluations: list[tuple[int, object, object]] = []
        worker.finished_baseline.connect(lambda rid, payload, error: baselines.append((rid, payload, error)))
        worker.finished_eval.connect(lambda rid, payload, error: evaluations.append((rid, payload, error)))

        worker.run_baseline_reload(BaselineReloadRequest(request_id=1, path=str(BUILD)))

        assert len(baselines) == 1
        request_id, payload, error = baselines[0]
        assert error is None, repr(error)
        assert request_id == 1 and payload["ok"] is True
        assert payload["item_set_valid"] is True and payload["active_loadout"] == "Default"
        assert payload["tree_set"]["tree_version"] == "0_5"
        graph = payload["graph"]
        assert graph["class"] == "Mercenary" and graph["ascendancy"] == "Gemling Legionnaire"
        nodes = {node["id"]: node for node in graph["nodes"]}
        assert nodes[NON_ASCII_NODE_ID]["name"] == NON_ASCII_NODE_NAME
        assert not any(REPLACEMENT_CHARACTER in str(node.get("name") or "") for node in graph["nodes"])
        assert any(node["allocated"] and node["name"] == "Giant's Blood" for node in graph["nodes"])

        worker.run_evaluation(EvaluationRequest(
            request_id=2,
            raw_text=_two_hand_upgrade(),
            content_hash="corpus02-two-hand",
            clipboard_received_ms=1.0,
            copy_timestamp=2.0,
            baseline_generation=0,
            presentation_generation=0,
            context_identity="",
            candidate_fingerprint="corpus02-two-hand",
        ))

        assert len(evaluations) == 1
        request_id, eval_payload, error = evaluations[0]
        assert error is None, repr(error)
        result, _timing = eval_payload
        assert request_id == 2
        assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Weapon 1", "Weapon 2"}
        # The controller defers the restore (PERF-02) and verifies it in
        # _finalize_deferred_restore before emitting; a failed restore would have
        # been emitted as the error above. Confirm the build is back to baseline.
        assert engine.get_metrics()["fingerprint_hash"] == payload["fingerprint"]


def test_giants_blood_baseline_identity_and_active_weapon_set(real_pob_engine) -> None:
    loaded = real_pob_engine.load_build(BUILD)
    build = loaded["build"]
    identity = build["main_skill_identity"]
    assert (build["class"], build["ascendancy"]) == ("Mercenary", "Gemling Legionnaire")
    assert identity["skill_name"] == "Supercharged Slam"
    assert identity["damage_owner"] == "PLAYER"
    assert identity["calculation_mode"] == "CHANNEL_RELEASE"

    raw = real_pob_engine.get_metrics()["raw"]
    # PoB's primary output is hit plus a small, real ignite component (fire from
    # Chernobog's Pillar), so CombinedDPS -- not TotalDPS -- is the primary field.
    assert raw["IgniteDPS"] > 0
    assert _close(raw["CombinedDPS"], raw["TotalDPS"] + raw["IgniteDPS"])
    assert raw["BlockChance"] == 50

    equipment = {
        entry["slot"]: entry
        for entry in real_pob_engine.get_equipment()["equipment"]
        if isinstance(entry, dict)
    }
    assert equipment["Weapon 1"]["name"] == MACE
    assert equipment["Weapon 1"]["type"] == "Two Hand Mace"
    assert equipment["Weapon 1"]["physical_slot"] == "Weapon 1"
    assert equipment["Weapon 2"]["name"] == CHERNOBOG
    assert equipment["Weapon 2"]["type"] == "Shield"
    assert equipment["Weapon 2"]["physical_slot"] == "Weapon 2"
    # The talisman sits in the inactive swap set and must not be read as active.
    assert equipment["Weapon 1 Swap"]["name"] == TALISMAN

    snapshot = real_pob_engine.get_tree_snapshot()
    allocated = {node["name"] for node in snapshot["nodes"] if node["allocated"]}
    assert "Giant's Blood" in allocated
    assert snapshot["stats"]["allocated_count"] == len([n for n in snapshot["nodes"] if n["allocated"]])


def test_giants_blood_two_hand_candidate_keeps_shield_and_matches_pob(real_pob_engine, tmp_path: Path) -> None:
    """A two-hand mace PoB allows beside the shield replaces Weapon 1 and keeps the shield."""
    candidate = _two_hand_upgrade()
    shield = _equipped_item(BUILD, "Weapon 2")
    expected = _fresh_metrics(real_pob_engine, tmp_path, "two_hand", {"Weapon 1": candidate})
    baseline = _fresh_metrics(real_pob_engine, tmp_path, "baseline", {})

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    assert result["pob_parse"]["item"]["type"] == "Two Hand Mace"
    assert result["paired_offhand_cleared"] is False
    assert {row["pob_slot"] for row in result["slot_comparisons"]} == {"Weapon 1", "Weapon 2"}

    main = _row(result, "Weapon 1")
    assert main["candidate"]["equipment"]["Weapon 2"] == main["baseline"]["equipment"]["Weapon 2"]
    assert CHERNOBOG.split(",")[0] in main["candidate"]["equipment"]["Weapon 2"]
    assert shield.splitlines()[1] in main["candidate"]["equipment"]["Weapon 2"]
    assert _close(main["baseline"]["metrics"]["CombinedDPS"], baseline["CombinedDPS"])
    assert _close(main["candidate"]["metrics"]["CombinedDPS"], expected["CombinedDPS"])
    assert expected["CombinedDPS"] > baseline["CombinedDPS"]
    assert expected["BlockChance"] == baseline["BlockChance"]
    outcome = main["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL"
    assert _axes(main)["OFFENSE"] == "POSITIVE"
    assert _axes(main)["DEFENSE"] == "NEUTRAL"
    assert outcome["verdict"] in DIRECTIONAL_UPGRADES
    assert main["candidate"]["primary_skill"]["skill_name"] == "Supercharged Slam"
    assert main["restore"]["pass"] is True

    # PoB also accepts a Giant's Blood two-hander in the off hand. That placement
    # drops the shield and with it the ignite component, so it must stay non-directional.
    offhand = _row(result, "Weapon 2")
    offhand_expected = _fresh_metrics(real_pob_engine, tmp_path, "two_hand_offhand", {"Weapon 2": candidate})
    assert offhand_expected.get("IgniteDPS", 0) == 0 and baseline["IgniteDPS"] > 0
    assert _close(offhand["candidate"]["metrics"]["CombinedDPS"], offhand_expected["CombinedDPS"])
    assert offhand["evaluation_outcome"]["evaluation_quality"] == "PARTIAL"
    assert offhand["evaluation_outcome"]["verdict"] == "UNCERTAIN"
    assert _axes(offhand)["OFFENSE"] == "UNKNOWN"
    assert offhand["restore"]["pass"] is True

    assert result["recommendation"]["pob_slot"] == "Weapon 1"
    assert result["presentation"]["verdict"] == outcome["verdict"]


def test_chernobog_shield_loss_is_measured_by_pob_but_stays_uncertain(real_pob_engine, tmp_path: Path) -> None:
    """Replacing the unique shield: PoB shows a large loss, the damage semantics change.

    Chernobog's Pillar converts block chance into extra fire damage, which is also
    what lets the build ignite. A plain tower shield removes both, so baseline
    CombinedDPS (hit + ignite) and candidate CombinedDPS (hit only) no longer denote
    the same quantity. The truthful public answer is PARTIAL/UNCERTAIN.
    """
    candidate = _plain_tower_shield()
    baseline = _fresh_metrics(real_pob_engine, tmp_path, "baseline", {})
    expected = _fresh_metrics(real_pob_engine, tmp_path, "plain_shield", {"Weapon 2": candidate})
    assert baseline["IgniteDPS"] > 0 and expected.get("IgniteDPS", 0) == 0
    assert expected["CombinedDPS"] < 0.8 * baseline["CombinedDPS"]
    assert expected["Armour"] > baseline["Armour"]
    assert expected["FireResist"] < baseline["FireResist"]

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    assert result["pob_parse"]["item"]["type"] == "Shield"
    assert result["paired_offhand_cleared"] is False
    assert [row["pob_slot"] for row in result["slot_comparisons"]] == ["Weapon 2"]
    row = _row(result, "Weapon 2")
    assert row["candidate"]["equipment"]["Weapon 1"] == row["baseline"]["equipment"]["Weapon 1"]
    assert MACE.split(",")[0] in row["candidate"]["equipment"]["Weapon 1"]
    assert _close(row["baseline"]["metrics"]["CombinedDPS"], baseline["CombinedDPS"])
    assert _close(row["candidate"]["metrics"]["CombinedDPS"], expected["CombinedDPS"])

    outcome = row["evaluation_outcome"]
    offense = row["metric_profile"]["primary_offense"]
    assert offense["delta_kind"] == "UNMEASURED"
    assert offense["coverage_state"] == "SEMANTIC_METRIC_CHANGED"
    assert row["baseline_primary_metric"]["semantic_quantity"] == "HIT_PLUS_AILMENT"
    assert row["candidate_primary_metric"]["semantic_quantity"] == "HIT_DPS"
    assert outcome["evaluation_quality"] == "PARTIAL"
    assert "OFFENSE_UNMEASURED" in {reason["code"] for reason in outcome["evaluation_quality_reasons"]}
    assert _axes(row)["OFFENSE"] == "UNKNOWN"
    assert _axes(row)["DEFENSE"] == "MIXED"
    assert outcome["verdict"] == "UNCERTAIN"
    assert result["presentation"]["verdict"] == "UNCERTAIN"
    assert row["restore"]["pass"] is True


def test_ineligible_two_hander_clears_shield_and_is_not_viable(real_pob_engine, tmp_path: Path) -> None:
    """Giant's Blood does not cover talismans: PoB drops the shield and the mace skill."""
    candidate = _talisman()
    expected = _fresh_metrics(
        real_pob_engine, tmp_path, "talisman", {"Weapon 1": candidate, "Weapon 2": None},
    )
    assert expected["CombinedDPS"] == 0

    result = evaluate_item(candidate, real_pob_engine, build_path=str(BUILD))

    assert result["pob_parse"]["item"]["type"] == "Talisman"
    assert [row["pob_slot"] for row in result["slot_comparisons"]] == ["Weapon 1"]
    row = _row(result, "Weapon 1")
    assert row["candidate"]["equipment"]["Weapon 2"] == ""
    assert result["paired_offhand_cleared"] is True
    assert result["paired_offhand_slot"] == "Weapon 2"
    assert result["paired_offhand_name"] == CHERNOBOG
    assert result["presentation"]["paired_offhand_name"] == CHERNOBOG
    assert _close(row["candidate"]["metrics"]["CombinedDPS"], expected["CombinedDPS"])

    outcome = row["evaluation_outcome"]
    assert outcome["verdict"] == "NOT_VIABLE"
    # Offense of a build whose main skill cannot be used is intentionally not scored: PARTIAL quality, decisive verdict.
    assert outcome["evaluation_quality"] == "PARTIAL"
    assert "MAIN_SKILL_INVALID" in {guard["code"] for guard in outcome["guardrails_applied"]}
    assert result["presentation"]["verdict"] == "NOT_VIABLE"
    assert row["restore"]["pass"] is True


def test_giants_blood_repeated_evaluation_is_deterministic_and_restores(real_pob_engine) -> None:
    real_pob_engine.load_build(BUILD)
    original_hash = real_pob_engine.get_metrics()["fingerprint_hash"]
    original_equipment = real_pob_engine.get_equipment()

    first = evaluate_item(_two_hand_upgrade(), real_pob_engine, build_path=str(BUILD))
    evaluate_item(_plain_tower_shield(), real_pob_engine, build_path=str(BUILD))
    evaluate_item(_talisman(), real_pob_engine, build_path=str(BUILD))
    second = evaluate_item(_two_hand_upgrade(), real_pob_engine, build_path=str(BUILD))

    for slot in ("Weapon 1", "Weapon 2"):
        before, after = _row(first, slot), _row(second, slot)
        assert before["evaluation_outcome"]["verdict"] == after["evaluation_outcome"]["verdict"]
        assert before["evaluation_outcome"]["final_score"] == after["evaluation_outcome"]["final_score"]
        assert before["candidate"]["metrics"]["CombinedDPS"] == after["candidate"]["metrics"]["CombinedDPS"]
        assert after["restore"]["pass"] is True
    for result in (first, second):
        assert _row(result, "Weapon 1")["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == original_hash
    assert real_pob_engine.get_equipment() == original_equipment


def test_block_chance_stacking_is_measured_through_the_damage_conversion(real_pob_engine, tmp_path: Path) -> None:
    """R4 stat-stacker evidence: Chernobog's Pillar turns Chance to Block into Fire damage ("Gain 1% of damage as Fire
    damage per 1% Chance to Block"), so this build stacks a stat that is neither an attribute nor a resource pool.

    A candidate that lowers Block lowers BOTH effective HP and damage (the conversion), PoB measures it, and Item Check
    reports a FULL downgrade on both axes that equals an independent cold PoB load. A candidate that adds Block changes
    nothing because the stat is already at its cap -- PoB says so, and Item Check agrees (a SIDEGRADE, not an invented
    gain). Scope: one stat-stacker flavour on one build; other stacked stats (Armour, Evasion, Rage, charges) have no
    corpus build, and Item Check adds no stat-specific formula for any of them (PoB computes them).
    """
    own = _equipped_item(BUILD, "Weapon 2")
    reduced = own + "\n20% reduced Block chance\n"
    more = own + "\n20% increased Block chance\n"
    baseline = _fresh_metrics(real_pob_engine, tmp_path, "block_baseline", {})
    lower = _fresh_metrics(real_pob_engine, tmp_path, "block_reduced", {"Weapon 2": reduced})
    higher = _fresh_metrics(real_pob_engine, tmp_path, "block_more", {"Weapon 2": more})
    assert lower["BlockChance"] < baseline["BlockChance"]
    assert lower["CombinedDPS"] < baseline["CombinedDPS"] and lower["TotalEHP"] < baseline["TotalEHP"]
    assert higher["BlockChance"] == baseline["BlockChance"]  # already capped
    assert _close(higher["CombinedDPS"], baseline["CombinedDPS"])

    down = evaluate_item(reduced, real_pob_engine, build_path=str(BUILD))
    row = _row(down, "Weapon 2")
    assert _close(row["baseline"]["metrics"]["CombinedDPS"], baseline["CombinedDPS"])
    assert _close(row["candidate"]["metrics"]["CombinedDPS"], lower["CombinedDPS"])
    outcome = row["evaluation_outcome"]
    assert outcome["evaluation_quality"] == "FULL"
    assert _axes(row)["OFFENSE"] == "NEGATIVE" and _axes(row)["DEFENSE"] == "NEGATIVE"
    assert outcome["verdict"] in {"MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE", "MAJOR_DOWNGRADE"}
    assert row["restore"]["pass"] is True

    flat = _row(evaluate_item(more, real_pob_engine, build_path=str(BUILD)), "Weapon 2")
    assert flat["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert flat["evaluation_outcome"]["verdict"] == "SIDEGRADE"
    assert _close(flat["candidate"]["metrics"]["CombinedDPS"], higher["CombinedDPS"])
    assert flat["restore"]["pass"] is True
