"""AMMO-01 — tripwire over every multi-effect gem in the PoB runtime in use (real PoB, six build contexts).

The failure class: a saved ``mainActiveSkill`` points at an effect PoB declares as dealing no damage (a load action, a
transformation host, a totem placement ...) while PoB still reports a weapon-dependent figure for it. This test calculates
every selectable effect of every multi-effect gem in several real builds and requires that:

* no declared-non-damaging effect with PoB offense is left as a damage target (class C), and none is silently "measurable"
  (class E) without that being reviewed here;
* every phantom is either an ammo load the resolver pairs, or is refused by the damage-target guard;
* every ammo family is class A with a deterministic pairing.

A PoB update that introduces a new phantom therefore fails here instead of shipping as a confident wrong answer.
The full classified table is `docs/AMMO-01-GEM-EFFECT-AUDIT.md` (regenerate with `scripts/audit_gem_effects.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import gem_effect_audit as audit

pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def audited(real_pob_engine, tmp_path_factory):
    scratch = tmp_path_factory.mktemp("gem_audit")
    gems = real_pob_engine._call("describe_gem_effects", {})["gems"]
    rows = {name: audit.measure_gem_effects(real_pob_engine, ROOT / relative, gems, scratch) for name, relative in audit.AUDIT_CONTEXTS}
    return gems, rows, audit.classify_all(gems, rows)


def test_the_audit_actually_covers_the_multi_effect_gems_in_every_context(audited) -> None:
    gems, rows, table = audited
    assert len(gems) > len(audit.ammo_gems(gems)) > 0
    assert len(table) == len(gems)
    for name, context_rows in rows.items():
        assert context_rows, f"{name}: no effect could be calculated"
    # effects PoB makes selectable were really calculated (not just described)
    assert sum(1 for row in rows["crossbow"] if row["status"] == "MEASURED") > 100


def test_no_declared_non_damaging_effect_is_left_as_a_damage_target(audited) -> None:
    _, _, table = audited
    vulnerable = [(row["gem"], row["evidence"]) for row in table if row["class"] == "C"]
    assert vulnerable == [], f"class C families (phantom offense treated as a damage target): {vulnerable}"
    reviewed = [(row["gem"], row["evidence"]) for row in table if row["class"] == "E"]
    assert reviewed == [], f"class E families need a review before they may stay measurable: {reviewed}"


def test_every_phantom_is_refused_by_the_damage_target_guard(audited) -> None:
    gems, rows, _ = audited
    declared = {(g["gem_id"], e["id"]) for g in gems for e in g["effects"] if audit.declared_no_damage(e)}
    phantoms = 0
    leaked = []
    for context, context_rows in rows.items():
        for row in context_rows:
            if (row["gem_id"], row["effect_id"]) not in declared or audit.offense_of(row["output"]) <= audit.EPS:
                continue
            phantoms += 1
            if row["damage_target"] is not False:
                leaked.append((context, row["gem"], row["effect_id"], audit.offense_of(row["output"])))
    assert phantoms > 0, "the audit found no phantom at all: the oracle is not exercising weapon-dependent skills"
    assert leaked == [], f"declared-no-damage effects with PoB offense that are still damage targets: {leaked}"
    reasons = {row["damage_target_reason"] for context_rows in rows.values() for row in context_rows if row["damage_target"] is False}
    assert reasons <= {"AMMO_LOAD_DEALS_NO_DAMAGE", "DECLARES_NO_DAMAGE"}, reasons


def test_every_ammo_family_is_class_a_with_a_deterministic_pairing(audited) -> None:
    gems, _, table = audited
    by_gem = {row["gem_id"]: row for row in table}
    for gem in audit.ammo_gems(gems):
        mapping = audit.ammo_mapping(gem)
        assert mapping["status"] == "DETERMINISTIC", mapping
        assert by_gem[gem["gem_id"]]["class"] == "A", by_gem[gem["gem_id"]]
        assert by_gem[gem["gem_id"]]["ammo_family"] is True


def test_non_damaging_effects_beside_several_damage_capable_siblings_are_not_paired(audited) -> None:
    """Class D is evidence-based: more than one candidate means a redirect would be a guess, so none exists."""
    _, _, table = audited
    for row in (r for r in table if r["class"] == "D"):
        assert len(row["damaging_siblings"]) >= 2, row
        assert not row["ammo_family"], row
