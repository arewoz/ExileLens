"""Slice 4D real-PoB gate: full diagnostic chain on the weapon-swap fixture.

Runs against the local supported PoB2 revision only (`-m real_pob`, with
`POB2_PATH` set). Exercises candidate -> measurements -> evidence ->
proof -> required scope -> eligibility through the read-only diagnostic
consumer on `core04_weapon_swap` (active set 2, bow/quiver vs
spear/shield) -- the strongest existing weapon-set fixture. No exact
community (Voltaic Barrier) build exists locally; see
EXACT_COMMUNITY_FIXTURE_MISSING below.

The expected truthful outcome is NOT forced: a bow mod moves bow skills
but not spear/shield skills, so a complete-scope assessment should
diverge (or surface unavailability). Whatever the engine truthfully
returns is asserted structurally, never as a fixed status string.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2value.items.contextual_diagnostics import run_contextual_diagnostic
from poe2value.items.contextual_evaluation import read_component_in_context
from poe2value.items.contextual_evidence import EvidenceObservation
from poe2value.items.effect_components import ContextualComponentReference
from poe2value.items.evaluation import evaluate_item
from poe2value.items.evaluation_identity import candidate_fingerprint
from poe2value.items.slots import ProductSlot

ROOT = Path(__file__).resolve().parents[2]
WEAPON_SWAP = ROOT / "fixtures" / "builds" / "public_corpus" / "core04_weapon_swap.xml"
RING_BUILD = ROOT / "fixtures" / "builds" / "core04_player_ring.xml"
ITEMS = ROOT / "fixtures" / "items"

# No exact recent-community (Voltaic Barrier cross-set) build is checked in
# locally. The only "Voltaic" text in-repo is an unrelated equipped staff
# in core04_player_ring.xml. The artifact needed later is an exported
# PoB/build fixture of the reported community case.
EXACT_COMMUNITY_FIXTURE_MISSING = True

pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _all_references(engine) -> list[dict]:
    loaded = engine.load_build(WEAPON_SWAP)
    count = int((loaded.get("build") or {}).get("skill_group_count") or 0)
    seen: dict[str, dict] = {}
    for index in range(1, count + 1):
        catalog = engine.list_calculable_effects(indices=[index])
        for row in catalog.get("effects") or []:
            reference = row.get("reference") or {}
            if reference.get("semantic_id"):
                seen[reference["semantic_id"]] = reference
    return list(seen.values())


def test_both_weapon_set_catalogs_enumerate_with_restore(real_pob_engine) -> None:
    real_pob_engine.load_build(WEAPON_SWAP)
    assert real_pob_engine.get_weapon_set_context()["weapon_set"] == 2
    before_fingerprint = real_pob_engine.get_metrics()["fingerprint_hash"]
    before_weapons = real_pob_engine.get_weapon_set_context()["physical_weapons"]

    with pytest.raises(ValueError):
        real_pob_engine.list_calculable_effects(weapon_set=3)

    plain = real_pob_engine.list_calculable_effects()
    assert "requested_weapon_set" not in plain

    catalog_set2 = real_pob_engine.list_calculable_effects(weapon_set=2)
    catalog_set1 = real_pob_engine.list_calculable_effects(weapon_set=1)

    assert catalog_set2["requested_weapon_set"] == 2
    assert catalog_set2["context"]["weapon_set"] == 2
    assert catalog_set2["frames"] == {"context_settle": 0, "restore_settle": 0}
    assert catalog_set1["requested_weapon_set"] == 1
    assert catalog_set1["context"]["weapon_set"] == 1
    assert catalog_set1["frames"] == {"context_settle": 1, "restore_settle": 1}
    for catalog in (catalog_set1, catalog_set2):
        assert isinstance(catalog.get("truncated"), bool)
        assert catalog.get("effects")
        for row in catalog["effects"]:
            assert row["reference"]["semantic_id"]

    # Same reference qualifies into two disjoint context identities.
    shared = next(
        row["reference"]
        for row in catalog_set2["effects"]
        if any(r["reference"]["semantic_id"] == row["reference"]["semantic_id"] for r in catalog_set1["effects"])
    )
    identities = {
        ContextualComponentReference.from_dict(
            {"component": shared, "context": {"weapon_set": weapon_set}}
        ).cache_identity
        for weapon_set in (1, 2)
    }
    assert len(identities) == 2

    # Original build state restored: same set, fingerprint, and weapons.
    assert real_pob_engine.get_weapon_set_context()["weapon_set"] == 2
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == before_fingerprint
    assert real_pob_engine.get_weapon_set_context()["physical_weapons"] == before_weapons


def test_full_diagnostic_chain_on_weapon_swap(real_pob_engine, monkeypatch) -> None:
    references = _all_references(real_pob_engine)
    assert len(references) > 8  # multi-effect build; per-call cap would hide rows
    physical = real_pob_engine.get_weapon_set_context()["physical_weapons"]
    assert real_pob_engine.get_weapon_set_context()["weapon_set"] == 2
    candidate = physical["Weapon 1 Swap"] + "\n500% increased Physical Damage\n"
    baseline_fingerprint = real_pob_engine.get_metrics()["fingerprint_hash"]
    baseline_weapons = dict(physical)

    observations = [
        EvidenceObservation(reference=reference, weapon_set=2, logical_product_slot=ProductSlot.WEAPON_1)
        for reference in references
    ]
    report = run_contextual_diagnostic(
        real_pob_engine, candidate_text=candidate, observations=observations
    )

    # Schema: every required diagnostic field present and JSON-plain.
    for key in (
        "candidate", "provenance", "source_identity", "source_revision", "build_generation",
        "requested_contexts", "observations", "unavailable", "physical_targets",
        "proof", "proof_scope", "proof_exact", "completeness", "assessment",
        "composition_eligibility", "eligibility_reason", "frames_total", "restore",
        "baseline_state", "final_state", "limitations", "warnings",
        "whole_build", "public_verdict_affected",
    ):
        assert key in report, key
    import json

    json.dumps(report)
    assert report["whole_build"] is False
    assert report["public_verdict_affected"] is False
    assert report["requested_contexts"] == [2]
    assert len(report["observations"]) == len(references)

    # Provenance is real and consistent with the engine state.
    assert report["candidate"] == {"fingerprint": candidate_fingerprint(candidate)}
    assert report["source_revision"] == real_pob_engine.loaded_revision.token
    assert report["build_generation"] == real_pob_engine.source_generation
    assert report["source_identity"] == real_pob_engine.loaded_source_ref.key
    for row in report["observations"]:
        assert row["physical_target"]["physical_pob_slot"] == "Weapon 1 Swap"
        assert row["qualified_reference"]["context"]["weapon_set"] == 2
        assert row["status"] in ("MEASURED", "UNAVAILABLE")
        if row["status"] == "UNAVAILABLE":
            assert row["baseline_output"] is None and row["candidate_output"] is None

    # Proof produced; completeness assessed against the enumerated catalog.
    assert report["proof"]["classification"] in (
        "COMMON_RESPONSE", "DIVERGENT_RESPONSE", "INSUFFICIENT_EVIDENCE", "NOT_COMPARABLE",
    )
    assert report["proof_exact"] is False
    completeness = report["completeness"]
    assert completeness["required_identities_count"] >= len(references)
    assert completeness["missing_catalog_sets"] == []
    assert completeness["catalog_status"]["2"]["enumerated"] is True

    # Eligibility is truthful, never forced: assert structure per outcome.
    eligibility = report["composition_eligibility"]
    reason = report["eligibility_reason"]
    assert eligibility in ("ELIGIBLE", "NOT_ELIGIBLE", "INSUFFICIENT_EVIDENCE")
    if eligibility == "ELIGIBLE":
        assert report["proof"]["classification"] == "COMMON_RESPONSE"
        assert completeness["missing_identities"] == []
        assert all(row.get("restore_pass") is True for row in report["observations"])
    elif eligibility == "NOT_ELIGIBLE":
        assert reason == "PROOF_DIVERGENT" or reason.startswith("PROOF_")
    else:
        assert reason  # exact structured reason recorded, not guessed

    # Restore: build/equipment state equals baseline after the diagnostic.
    assert report["restore"]["pass"] is True
    assert real_pob_engine.get_metrics()["fingerprint_hash"] == baseline_fingerprint
    assert real_pob_engine.get_weapon_set_context()["physical_weapons"] == baseline_weapons
    assert real_pob_engine.get_weapon_set_context()["weapon_set"] == 2

    # Weapon-set contexts remain distinct on real PoB (read-only, no candidate).
    first_reference = references[0]
    read_set2 = read_component_in_context(real_pob_engine, first_reference, 2)
    read_set1 = read_component_in_context(real_pob_engine, first_reference, 1)
    assert read_set2["context"]["weapon_set"] == 2
    assert read_set1["context"]["weapon_set"] == 1
    assert (
        read_set2["qualified_reference"]["cache_identity"]
        != read_set1["qualified_reference"]["cache_identity"]
    )

    # Normal Item Check remains unchanged with zero contextual RPCs.
    contextual_calls: list[str] = []
    original_candidate = real_pob_engine.evaluate_effect_candidate
    original_read = real_pob_engine.read_effect_metrics

    def counted_candidate(*args, **kwargs):
        contextual_calls.append("candidate")
        return original_candidate(*args, **kwargs)

    def counted_read(reference, **kwargs):
        if kwargs.get("weapon_set") is not None:
            contextual_calls.append("read")
        return original_read(reference, **kwargs)

    monkeypatch.setattr(real_pob_engine, "evaluate_effect_candidate", counted_candidate)
    monkeypatch.setattr(real_pob_engine, "read_effect_metrics", counted_read)
    item = (ITEMS / "core04_offense_ring.txt").read_text(encoding="utf-8")
    result = evaluate_item(item, real_pob_engine, build_path=str(RING_BUILD))
    row = next(entry for entry in result["slot_comparisons"] if entry["pob_slot"] == "Ring 1")
    assert contextual_calls == []
    assert row["evaluation_outcome"]["evaluation_quality"] == "FULL"
    assert row["evaluation_outcome"]["verdict"] == "MEANINGFUL_UPGRADE"
    assert row["restore"]["pass"] is True
