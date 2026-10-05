"""AMMO-01 — the whole crossbow ammo family, derived from PoB's own data (no skill-name list).

* the inventory comes from the bridge's read-only ``describe_gem_effects``;
* every discovered ammo gem is loaded into the tester's real build, once with the load action saved as the main effect and
  once with the fired effect saved, and the live resolver is checked against the data-derived mapping;
* weapon sensitivity uses PoB as the only oracle: ExileLens (load saved) must equal PoB with the fired effect selected, and
  must never turn a change PoB reports into a measured zero.

Fast structural cases (ambiguous / malformed pairings) are in tests/test_ammo01_pairing_contract.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from exilelens.items.evaluation import evaluate_item
from tests import gem_effect_audit as audit
from tests.integration.test_ammo01_permafrost_bolts_weapon import BUILD, CANDIDATE

pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


@pytest.fixture(scope="module")
def gems(real_pob_engine) -> list[dict]:
    return real_pob_engine._call("describe_gem_effects", {})["gems"]


@pytest.fixture(scope="module")
def ammo(gems) -> list[dict]:
    found = audit.ammo_gems(gems)
    assert found, "the PoB runtime exposes no CrossbowAmmoSkill gem: the inventory itself is broken"
    return found


def test_every_ammo_gem_has_one_deterministic_load_to_fired_mapping(ammo) -> None:
    mappings = [audit.ammo_mapping(g) for g in ammo]
    broken = [(m["name"], m["reasons"]) for m in mappings if m["status"] != "DETERMINISTIC"]
    assert broken == [], f"ammo gems that cannot be mapped deterministically: {broken}"
    for mapping in mappings:
        assert mapping["load_index"] != mapping["fired_index"], mapping["name"]
        # distinct effects, and the pair is unique across the family
    assert len({m["load_effect"] for m in mappings}) == len(mappings)
    assert len({m["fired_effect"] for m in mappings}) == len(mappings)


def test_every_ammo_load_effect_is_resolved_live_and_a_direct_fired_selection_is_untouched(
    real_pob_engine, ammo, tmp_path: Path
) -> None:
    base_text = BUILD.read_text(encoding="utf-8")
    problems: list[str] = []
    for index, gem in enumerate(ammo):
        mapping = audit.ammo_mapping(gem)
        for selector, saved in (("load", mapping["load_index"]), ("fired", mapping["fired_index"])):
            xml, main_group = audit.ammo_family_build(base_text, gem, selector=saved)
            path = tmp_path / f"family_{index}_{selector}.xml"
            path.write_text(xml, encoding="utf-8")
            loaded = real_pob_engine.load_build(path)
            identity = loaded["build"]["main_skill_identity"]
            label = f"{mapping['name']} (saved {selector})"
            if identity["index"] != main_group:
                problems.append(f"{label}: wrong main group {identity['index']}")
            if identity["skill_id"] != mapping["fired_effect"]:
                problems.append(f"{label}: measured {identity['skill_id']}, expected {mapping['fired_effect']}")
            if identity["ammo_load_effect"] or identity["damage_target"] is not True:
                problems.append(f"{label}: resolved identity still flagged as a non-target")
            redirect = identity.get("effect_redirect")
            if selector == "load":
                if not redirect or redirect["from_skill_id"] != mapping["load_effect"] \
                        or redirect["to_skill_id"] != mapping["fired_effect"] \
                        or redirect["reason"] != "AMMO_LOAD_DEALS_NO_DAMAGE":
                    problems.append(f"{label}: redirect missing or wrong: {redirect}")
            elif redirect is not None:
                problems.append(f"{label}: an unnecessary redirect was recorded: {redirect}")
            # The effect catalog keeps `calculable` and `damage_target` apart for both effects of the gem.
            rows = {
                row["reference"]["effect_id"]: row["reference"]
                for row in real_pob_engine.list_calculable_effects(indices=[main_group], max_effects=8)["effects"]
            }
            if rows[mapping["load_effect"]]["damage_target"] is not False:
                problems.append(f"{label}: catalog offers the load action as a damage target")
            if rows[mapping["fired_effect"]]["damage_target"] is not True:
                problems.append(f"{label}: catalog refuses the fired effect")
    assert problems == [], "\n".join(problems)


def test_resolution_is_scoped_to_the_same_gem_instance_even_inside_one_group(real_pob_engine, ammo, tmp_path: Path) -> None:
    """Two different ammo gems share ONE socket group: each load action resolves to its own fired effect only."""
    first, second = (audit.ammo_mapping(g) for g in ammo[:2])
    base_text = BUILD.read_text(encoding="utf-8")
    group = audit.gem_group_xml(ammo[0])
    second_gem = audit.gem_group_xml(ammo[1])
    # splice the second gem line into the first group so both gems live in one <Skill>
    second_line = second_gem[second_gem.index("<Gem "): second_gem.index("</Skill>")]
    merged = group.replace("</Skill>", second_line + "</Skill>")
    results = {}
    for selector in (1, 2, 3, 4):
        xml, existing = audit.inject_gem_groups(
            base_text, [merged.replace('mainActiveSkill="1"', f'mainActiveSkill="{selector}"')], replace=True
        )
        xml = re.sub(r'(<Build\b[^>]*\bmainSocketGroup=")\d+(")', rf"\g<1>{existing + 1}\2", xml, count=1)
        path = tmp_path / f"scoped_{selector}.xml"
        path.write_text(xml, encoding="utf-8")
        identity = real_pob_engine.load_build(path)["build"]["main_skill_identity"]
        results[selector] = (identity["skill_id"], (identity.get("effect_redirect") or {}).get("from_skill_id"))
    # display order inside the group: [first fired, first load, second fired, second load]
    assert results[1] == (first["fired_effect"], None)
    assert results[2] == (first["fired_effect"], first["load_effect"])
    assert results[3] == (second["fired_effect"], None)
    assert results[4] == (second["fired_effect"], second["load_effect"])


def test_weapon_sensitivity_matches_pob_for_every_ammo_gem_and_never_collapses_a_real_change(
    real_pob_engine, ammo, tmp_path: Path, record_property
) -> None:
    rows = audit.weapon_sensitivity_matrix(real_pob_engine, evaluate_item, ammo, BUILD, CANDIDATE, tmp_path)
    assert len(rows) == len(ammo)
    problems: list[str] = []
    responsive = {name: 0 for name, _, _ in audit.PERTURBATIONS}
    for row in rows:
        label = row["gem"]
        if row["primary_skill"] != row["fired"]:
            problems.append(f"{label}: measured {row['primary_skill']} instead of {row['fired']}")
        if not row["fields_equal"]:
            problems.append(f"{label}: ExileLens {row['exilelens_before']}->{row['exilelens_after']} differs from PoB")
        for name, pct in row["pob_delta_pct"].items():
            if name in responsive and pct is not None and abs(pct) > 1e-6:
                responsive[name] += 1
        combined = row["pob_delta_pct"]["all"]
        if combined is not None and abs(combined) > 1e-6:
            if row["delta_kind"] == "MEASURED_ZERO" or row["verdict"] in {"NO_CHANGE", "SIDEGRADE"}:
                problems.append(f"{label}: PoB reports {combined:.2f}% but ExileLens says {row['delta_kind']}/{row['verdict']}")
        elif row["delta_kind"] != "MEASURED_ZERO":
            problems.append(f"{label}: PoB reports no change but ExileLens says {row['delta_kind']}")
    for name, count in responsive.items():
        record_property(f"ammo_gems_responding_to_{name}", count)
    assert problems == [], "\n".join(problems)
    # A zero is valid, but a family where nothing responded to a deliberately strong change is not credible.
    assert all(count > 0 for count in responsive.values()), f"a perturbation moved no ammo skill at all: {responsive}"
