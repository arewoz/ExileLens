"""The coverage-case registry: what corpus/regression coverage actually exists today.

Every entry here must reference a real fixture and a real, currently-passing (or
currently-failing) pytest node — nothing is invented to fill the taxonomy. A category
in `taxonomy.Archetype` with no entries below is a genuine, reportable gap; see
`docs/corpus_coverage/COVERAGE_REPORT.md` for the generated view of that gap.

To add a coverage case when new corpus fixtures or regression tests land:
  1. Add/extend the fixture or test as normal (see docs/BUILD_CORPUS_SOURCES.md).
  2. Add one `CoverageCase` below pointing at the new pytest node(s).
  3. Re-run `python scripts/generate_corpus_coverage_report.py`.
Do not add a `CoverageCase` for a fixture/test that does not exist yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from tests.corpus_coverage.taxonomy import (
    Archetype,
    CaseRole,
    EvaluationDepth,
    ExpectedResult,
    FunctionalMeasurement,
    UncertaintyAudit,
)


@dataclass(frozen=True)
class CoverageCase:
    id: str
    test_file: str
    node_name: str  # exact JUnit `name`, or a prefix when `node_name_is_prefix` is set
    depth: EvaluationDepth
    expected: ExpectedResult
    description: str
    archetypes: tuple[Archetype, ...] = ()
    manifest_id: str | None = None
    node_name_is_prefix: bool = False
    # CORPUS-02D1: what the case's own assertions establish about the mechanic. Left
    # unset for identity, restore/repeatability and policy cases, and for verdict
    # cases not yet classified; `tests/test_corpus_coverage_report.py` checks each
    # declared value against the quality the test body asserts.
    functional: FunctionalMeasurement | None = None
    # R4: a VERDICT case is either a MECHANIC case (declares `functional`) or a STATE_INTEGRITY case (loadout/restore/
    # enumeration plumbing that asserts no measurement quality). `tests/test_corpus_coverage_report.py` fails a
    # VERDICT case that is neither, so "not yet classified" can no longer accumulate silently.
    role: CaseRole = CaseRole.MECHANIC
    # R4: every case whose correct answer is a refusal (expected UNCERTAIN/UNSUPPORTED, or PARTIALLY_MEASURED)
    # carries the audited reason and a one-line note; `blocks_1_0` marks an unresolved release blocker.
    audit: UncertaintyAudit | None = None
    audit_note: str = ""
    blocks_1_0: bool = False


# ---------------------------------------------------------------------------
# Build Corpus (fixtures/builds/public_corpus/manifest.json) — identity-level.
#
# These confirm PoB loads each manifested build and attributes class, ascendancy,
# primary skill, and damage owner correctly. They do not assert an Item Check
# verdict; see the VERDICT-depth cases below for that.
# ---------------------------------------------------------------------------
BUILD_CORPUS_IDENTITY_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="CORE04-BOW-QUIVER-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-BOW-QUIVER]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description="Ranger/Deadeye, Ice Shot (bow projectile attack), PLAYER actor.",
        archetypes=(Archetype.RANGED_ATTACK,),
        manifest_id="CORE04-BOW-QUIVER",
    ),
    CoverageCase(
        id="CORE04-MINION-ACTOR-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-MINION-ACTOR]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description="Witch/Infernalist, Summon Infernal Hound, MINION-owned primary offense.",
        archetypes=(Archetype.MINION,),
        manifest_id="CORE04-MINION-ACTOR",
    ),
    CoverageCase(
        id="CORE04-STAGE-CONTEXT-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-STAGE-CONTEXT]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Mercenary/Gemling Legionnaire, Flameblast: channel-release stage context "
            "(stage_count-bearing skill part), an unusual skill-part configuration."
        ),
        archetypes=(Archetype.SPELL, Archetype.UNUSUAL_SKILL_PART),
        manifest_id="CORE04-STAGE-CONTEXT",
    ),
    CoverageCase(
        id="CORE04-MELEE-WEAPON-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-MELEE-WEAPON]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Warrior/Warbringer, Sunder (two-handed mace melee attack), PLAYER actor. "
            "Sourced from a real, currently-played public poe.ninja Runes of Aldur build."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-MELEE-WEAPON",
    ),
    CoverageCase(
        id="CORE04-ONEHAND-WEAPON-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-ONEHAND-WEAPON]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Warrior/Titan, Shield Wall (one-hand mace + tower shield melee build), PLAYER actor. "
            "Sourced from a real, currently-played public poe.ninja Runes of Aldur build."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-ONEHAND-WEAPON",
    ),
    CoverageCase(
        id="CORE04-POISON-AILMENT-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-POISON-AILMENT]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Huntress/Ritualist, Poisonburst Arrow (poison-dominant offense: real PoB PoisonDPS "
            "is ~89% of CombinedDPS), PLAYER actor. Sourced from a real, currently-played public "
            "poe.ninja Runes of Aldur build."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
    ),
    CoverageCase(
        id="CORE04-MIXED-HIT-AILMENT-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-MIXED-HIT-AILMENT]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Witch/Infernalist, Comet (triggered by Cast on Elemental Ailment): real PoB hit "
            "TotalDPS and IgniteDPS are both meaningful (~59%/41% split), neither negligible nor "
            "dominant. PLAYER actor. Sourced from a real, currently-played public poe.ninja Runes "
            "of Aldur build with no active weapon-swap set."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT, Archetype.TRIGGER),
        manifest_id="CORE04-MIXED-HIT-AILMENT",
    ),
    CoverageCase(
        id="CORE04-WEAPON-SWAP-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-WEAPON-SWAP]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Huntress/Ritualist, Poisonburst Arrow, PLAYER actor. Active item set has "
            "useSecondWeaponSet=true: the primary Weapon 1/2 slots hold an unrelated spear+shield "
            "loadout that is not actually equipped. Sourced from a real, currently-played public "
            "poe.ninja Runes of Aldur build."
        ),
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
    ),
    CoverageCase(
        id="CORE04-SKILL-NATIVE-DOT-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORE04-SKILL-NATIVE-DOT]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Monk/Acolyte of Chayula, Profane Ritual (triggered by Cast on Minion Death): zero hit "
            "DPS, zero named-ailment DPS, CombinedDPS is entirely PoB's own TotalDot. PLAYER actor. "
            "Sourced from a real, currently-played public poe.ninja Runes of Aldur build."
        ),
        archetypes=(Archetype.DOT,),
        manifest_id="CORE04-SKILL-NATIVE-DOT",
    ),
    CoverageCase(
        id="CORPUS02-GIANTS-BLOOD-SHIELD-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORPUS02-GIANTS-BLOOD-SHIELD]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Mercenary/Gemling Legionnaire, Supercharged Slam with a two-hand mace plus a tower "
            "shield (Giant's Blood), PLAYER actor. Supplied by a community tester (CORPUS-02A)."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
    ),
    CoverageCase(
        id="CORPUS02B-VARASHTA-DJINN-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORPUS02B-VARASHTA-DJINN]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Sorceress/Disciple of Varashta, Navira, the Last Mirage (ascendancy-granted Water "
            "Djinn), MINION actor. Public ladder build; not the community Djinn report's build."
        ),
        archetypes=(Archetype.MINION,),
        manifest_id="CORPUS02B-VARASHTA-DJINN",
    ),
    CoverageCase(
        id="CORPUS02C-STONEFIST-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORPUS02C-STONEFIST]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Monk/Martial Artist, Twister, PLAYER actor, Way of the Stonefist allocated with "
            "already-transformed Runeforged Fists of Stone gloves. Public ladder build."
        ),
        manifest_id="CORPUS02C-STONEFIST",
    ),
    CoverageCase(
        id="CORPUS02D2-VOLTAIC-BARRIER-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORPUS02D2-VOLTAIC-BARRIER]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Mercenary/Gemling Legionnaire, the community-reported build "
            "(pobb.in/1PuQGhYCY9Fv). PoB's own saved main skill is Virtuous Barrier, "
            "PLAYER actor."
        ),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
    ),
    CoverageCase(
        id="CORPUS02E-SPELL-TOTEM-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[CORPUS02E-SPELL-TOTEM]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Warrior/Titan, a public poe.ninja ladder character whose selected group is the Spell Totem "
            "meta skill casting Grim Pillars; PLAYER actor (PoB calculates the totem on the player's output)."
        ),
        archetypes=(Archetype.PROXY_TOTEM,),
        manifest_id="CORPUS02E-SPELL-TOTEM",
    ),
)

# ---------------------------------------------------------------------------
# Strategic real-PoB suite (tests/integration/test_public_real_pob.py) —
# verdict-level. These call `evaluate_item` and assert an actual
# EvaluationOutcome/PublicVerdict/quality, using the ring build
# (fixtures/builds/core04_player_ring.xml: Sorceress/Stormweaver, Spark, with the
# "Pinpoint Critical" support gem equipped) plus the three public_corpus builds.
# ---------------------------------------------------------------------------
REAL_POB_VERDICT_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="RING-OFFENSE-DEFENSE-MEASURED",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_supported_offense_and_defense_comparisons_are_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Sorceress/Stormweaver, Spark (crit-support gem equipped): FULL quality, "
            "directional OFFENSE/DEFENSE axis improvement, clean restore."
        ),
        archetypes=(Archetype.SPELL, Archetype.CRIT),
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="LIFE01-BLOOD-MAGE-GORE-SPIKE",
        test_file="tests/integration/test_life01_blood_mage.py",
        node_name="test_life01_gore_spike_life_increases_authoritative_player_offense",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Authentic Witch/Blood Mage Ember Fusillade build (pobb.in/duLtV2Cf4TfL): "
            "a Life-only Original Sin candidate increases current unreserved Life, Gore Spike "
            "critical damage, selected player DPS, and EHP with verified transaction restore."
        ),
        archetypes=(Archetype.SPELL, Archetype.CRIT, Archetype.LIFE_SCALING, Archetype.ASCENDANCY),
        manifest_id="LIFE01-BLOOD-MAGE-GORE-SPIKE",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="RING-TRADEOFF-BEST-SLOT",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_ring_tradeoff_and_best_slot_remain_semantic",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two-ring transaction, TRADEOFF impact pattern with a material conflict capped at MINOR_UPGRADE (SCORING-01a), stable best-slot pick.",
        archetypes=(Archetype.SPELL,),
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="RING-EMPTY-SLOT",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_empty_ring_slot_is_explicitly_compared_not_inferred_as_missing",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Empty slot is compared explicitly, not inferred/guessed from a missing baseline.",
        archetypes=(Archetype.SPELL,),
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="BOW-QUIVER-REPLACEMENT",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_bow_quiver_preserves_player_skill_and_restore",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Quiver replacement on a bow build preserves the Ice Shot player-skill identity and restores cleanly.",
        archetypes=(Archetype.RANGED_ATTACK,),
        manifest_id="CORE04-BOW-QUIVER",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MINION-STAGE-IDENTITY-RETAINED",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_minion_actor_and_stage_context_are_retained",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description="Minion damage-owner identity and channel-release stage/stage-count identity both survive engine load.",
        archetypes=(Archetype.MINION, Archetype.UNUSUAL_SKILL_PART),
        manifest_id="CORE04-MINION-ACTOR",
    ),
    CoverageCase(
        id="CORRUPT-RESTORE-RECOVERY",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_failed_candidate_restore_is_followed_by_a_clean_valid_evaluation",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="A corrupted candidate restore is followed by a forced reload and a clean, valid subsequent evaluation.",
        archetypes=(Archetype.SPELL,),
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="ONE-BATCHED-TRANSACTION",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_one_item_check_uses_one_batched_candidate_evaluation",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="One Item Check issues exactly one batched PoB transaction across all compatible slots (perf invariant, not archetype-specific).",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="MELEE-TWO-HAND-WEAPON-UPGRADE",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_melee_two_hand_weapon_upgrade_is_measured_and_restored",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Real two-handed mace replacement on a Warrior/Warbringer Sunder build: single-slot "
            "resolution, FULL quality, measured offense-only gain, MEANINGFUL_UPGRADE, clean restore."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-MELEE-WEAPON",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MELEE-WEAPON-REPEATED-EVALUATION-NO-LEAK",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_melee_weapon_repeated_evaluation_does_not_leak_state",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two consecutive Item Checks against the same melee weapon candidate produce identical score/verdict and both restore cleanly.",
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-MELEE-WEAPON",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="ONEHAND-WEAPON-AMBIGUOUS-SLOT-RESOLVED-SAFELY",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_onehand_weapon_candidate_is_ambiguous_and_resolved_safely",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A one-hand mace candidate legal in both Weapon 1 and Weapon 2 (dual-wield-capable "
            "layout, tower shield in Weapon 2) is evaluated in both slots: FULL/MEANINGFUL_UPGRADE "
            "for the correct replacement, guardrail-forced NOT_VIABLE (never a confident verdict) "
            "for the slot that would remove the shield the main skill needs. Best-slot ranking "
            "never surfaces the guardrail-blocked slot."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-ONEHAND-WEAPON",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="SHIELD-REPLACEMENT-MEASURED-AND-RESTORED",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_shield_replacement_is_measured_and_restored",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "M1.2 offhand slice: a real Shield-into-Shield candidate on the Shield Wall build "
            "(same tower shield plus one added life mod) resolves to exactly one legal slot "
            "(Weapon 2, via PoB's own IsItemValidForSlot), preserves the Shield-Wall-requires-a-"
            "shield skill identity, and shows a real, non-fabricated defense-only gain (+8.75% "
            "EHP) with a correctly NEUTRAL offense axis -- FULL quality, MEANINGFUL_UPGRADE, "
            "clean restore, stable repeated evaluation."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-ONEHAND-WEAPON",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="OFFHAND-CANDIDATE-AGAINST-TWO-HAND-WEAPON-FAILS-TRUTHFULLY",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_offhand_candidate_against_two_hand_weapon_fails_truthfully",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNSUPPORTED,
        description=(
            "M1.2 offhand slice, invalid-combination case: a real Focus candidate against a "
            "build whose active weapon is a two-handed staff (empty offhand) resolves zero "
            "compatible slots via PoB's own IsItemValidForSlot and is correctly refused with "
            "SlotResolutionFailed/UNSUPPORTED_EQUIPMENT_LAYOUT -- never a confident, silently "
            "wrong-slot comparison. A clean, unrelated evaluation immediately afterward proves "
            "the failed resolution left no residual build-state mutation."
        ),
        archetypes=(Archetype.SPELL,),
        functional=FunctionalMeasurement.UNSUPPORTED_MECHANIC,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note="A Focus/shield/quiver cannot legally be worn with an equipped two-handed weapon: PoB's own IsItemValidForSlot returns no slot. Item Check refuses (SLOT_RESOLUTION_FAILED / UNSUPPORTED_EQUIPMENT_LAYOUT) and does not evaluate the two-step change (swap the weapon too).",
    ),
    CoverageCase(
        id="ONEHAND-WEAPON-REPEATED-EVALUATION-NO-LEAK",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_onehand_weapon_repeated_evaluation_does_not_leak_state",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two consecutive ambiguous-slot Item Checks produce identical per-slot score/verdict and both slots restore cleanly both times.",
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-ONEHAND-WEAPON",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="POISON-AILMENT-OFFENSE-SELECTED-AND-MEASURED",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_poison_ailment_dominant_offense_is_selected_and_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A real poison-dominant build (PoisonDPS ~89% of CombinedDPS) correctly selects "
            "PoisonDPS/AILMENT_DPS/DOT_DPS as primary offense (not hit DPS or CombinedDPS), "
            "and measures a real +54%-class offense increase from a physical-damage candidate. "
            "CORPUS-02D1: formerly PARTIAL / UNCERTAIN (every ailment audit was capped at "
            "'stack scope unproven'); the poison audit now proves PoB-derived stacks, so the "
            "evaluation is FULL / MEANINGFUL_UPGRADE."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="POISON-AILMENT-REPEATED-EVALUATION-NO-LEAK",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_poison_ailment_repeated_evaluation_does_not_leak_state",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two consecutive Item Checks against the same poison-ailment candidate select the same PoB field and produce identical FULL-quality score/verdict, both restoring cleanly.",
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MIXED-HIT-AILMENT-OFFENSE-SELECTS-COMBINED-DPS",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_mixed_hit_and_ailment_offense_selects_combined_dps",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A real build with meaningful hit AND meaningful ignite (~59%/41% split, neither "
            "negligible nor dominant) correctly selects CombinedDPS/HIT_PLUS_AILMENT rather than "
            "hit-only or ailment-only, correctly measures a +9.7%-class offense increase across "
            "TotalDPS, IgniteDPS, and CombinedDPS together (no double counting: CombinedDPS == "
            "TotalDPS + IgniteDPS exactly in both baseline and candidate), and reaches FULL "
            "quality / MEANINGFUL_UPGRADE -- a confident verdict is correct here, unlike the "
            "isolated-ailment-dominant case. M1.2 offhand-support note: the candidate itself is "
            "this build's own equipped Focus (item.type == 'Focus', logical/physical Weapon 2) "
            "-- this is the corpus's real-PoB evidence for Focus offhand support, promoted from "
            "already-proven behavior rather than re-implemented or re-fixtured."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT, Archetype.TRIGGER),
        manifest_id="CORE04-MIXED-HIT-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MIXED-HIT-AILMENT-REPEATED-EVALUATION-NO-LEAK",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_mixed_hit_and_ailment_repeated_evaluation_does_not_leak_state",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two consecutive Item Checks against the same mixed hit+ailment candidate select the same PoB field (CombinedDPS) and produce identical score/verdict, both restoring cleanly.",
        archetypes=(Archetype.AILMENT, Archetype.DOT, Archetype.TRIGGER),
        manifest_id="CORE04-MIXED-HIT-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="WEAPON-SWAP-BASELINE-REFLECTS-ACTIVE-SET",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_weapon_swap_baseline_reflects_the_active_second_set",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A build whose active item set has useSecondWeaponSet=true correctly resolves "
            "active_item_set_id/loadout/skill identity, and its baseline equipment/offense are "
            "proven (via an explicit wrong-set sentinel) to be computed from the active second "
            "weapon set, not the inactive primary set. The sentinel candidate replaces logical "
            "Weapon 1 with the INACTIVE primary weapon and is correctly, truthfully refused as "
            "NOT_VIABLE (an arrow skill without a bow), not silently no-op'd."
        ),
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="WEAPON-SWAP-CANDIDATE-SUBSTITUTION-RESOLVES-ACTIVE-SLOT",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_weapon_swap_candidate_substitution_resolves_the_active_slot",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "M1.1 P0 fix regression: a candidate cloned from the build's TRUE active bow "
            "(Weapon 1 Swap) and evaluated against logical Weapon 1 now correctly resolves "
            "against the active slot -- baseline_item is the active bow (not the inactive "
            "spear), the measured offense delta is real and material (+148%-class, matching a "
            "real PoB run), quality/verdict are a genuine FULL/MEANINGFUL_UPGRADE, the inactive "
            "primary set is never mutated, restore is exact (including active-item-set "
            "selection and skill identity), and repeated evaluation is stable. Fixed in "
            "runtime/lua/bridge.lua via `active_weapon_slot` -- see "
            "docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md risk register for before/after."
        ),
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="WEAPON-SWAP-OFFHAND-CANDIDATE-SUBSTITUTION-RESOLVES-ACTIVE-SLOT",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_weapon_swap_offhand_candidate_substitution_resolves_the_active_slot",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "M1.2 offhand slice, companion to WEAPON-SWAP-CANDIDATE-SUBSTITUTION-RESOLVES-"
            "ACTIVE-SLOT: a Quiver candidate cloned from the build's TRUE active quiver "
            "(physically Weapon 2 Swap) plus an attack-speed mod resolves against logical "
            "Weapon 2 correctly targeting the ACTIVE offhand -- baseline_item is the active "
            "quiver (not the inactive shield), a real +26.9%-class offense-only gain is "
            "measured, FULL/MEANINGFUL_UPGRADE, the inactive primary set (spear+shield) is "
            "never mutated, restore is exact, and repeated evaluation is stable. Confirms the "
            "M1.1 active_weapon_slot bridge translation already covers the offhand case with "
            "no separate offhand-swap mapper required."
        ),
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="SKILL-NATIVE-DOT-OFFENSE-SELECTED-AND-MEASURED",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_skill_native_dot_offense_is_selected_and_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A real build with zero hit DPS and zero named-ailment DPS -- offense is entirely "
            "PoB's own skill-native TotalDot -- correctly selects TotalDot/SKILL_DOT/DOT_DPS "
            "rather than falling back to TotalDPS (0, would silently report no offense) or "
            "substituting a named ailment field (none exists). A +100% increased Damage over "
            "Time candidate moves TotalDot by +81.97%, with CombinedDPS staying exactly equal to "
            "TotalDot throughout (no double counting) and FullDotDPS staying 0 (the AGGREGATE "
            "alternative correctly not involved). Reaches genuine FULL quality / "
            "MEANINGFUL_UPGRADE, matching the real measured delta."
        ),
        archetypes=(Archetype.DOT,),
        manifest_id="CORE04-SKILL-NATIVE-DOT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="SKILL-NATIVE-DOT-REPEATED-EVALUATION-NO-LEAK",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_skill_native_dot_repeated_evaluation_does_not_leak_state",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two consecutive Item Checks against the same skill-native-DoT candidate select the same PoB field (TotalDot) and produce identical score/verdict, both restoring cleanly.",
        archetypes=(Archetype.DOT,),
        manifest_id="CORE04-SKILL-NATIVE-DOT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STAGE-CHANNEL-RELEASE-IGNITE-VERDICT",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_stage_context_channel_release_ignite_offense_is_measured_truthfully",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "The corpus's first ignite-dominant verdict-level evidence (the mixed "
            "hit+ailment fixture covers ignite only as a CombinedDPS component): the "
            "channel-release Flameblast build resolves IgniteDPS/AILMENT_DPS/DOT_DPS, "
            "retains stage_count 1 / CHANNEL_RELEASE / sole stat set on both sides, "
            "measures a real ignite loss with MEASURED support, and still reports "
            "PARTIAL quality / UNCERTAIN verdict -- the truthful ailment-dominant "
            "classification, never a confident directional verdict. CORPUS-02D1: counted as "
            "partially measured -- PoB measures the ignite change, but ExileLens has no "
            "verified ignite stack/stage scope check (AILMENT_SCOPE_UNVERIFIED)."
        ),
        archetypes=(Archetype.SPELL, Archetype.AILMENT, Archetype.DOT, Archetype.UNUSUAL_SKILL_PART),
        manifest_id="CORE04-STAGE-CONTEXT",
        functional=FunctionalMeasurement.PARTIALLY_MEASURED,
        audit=UncertaintyAudit.FIXABLE_MEASUREMENT_GAP,
        audit_note='Only POISON has a PoB stack/stage scope proof (AILMENT_STACK_SCOPE_PROBES); ignite- and bleed-dominant primary outputs stay PARTIAL on every Item Check although PoB measures the ailment. Medium effort (per-ailment proof plus ignite and bleed corpus builds). Population unmeasured (1 of 21 corpus builds). Documented limitation, not a blocker.',
    ),
)

# ---------------------------------------------------------------------------
# Slice 3-4D real-PoB gates (CR-01 consolidation) — verdict-level in the
# "drives the real PoB worker" sense. These assert truthful component
# evidence (context identity, physical isolation, availability, exact
# restore), never a public EvaluationOutcome/PublicVerdict; see
# docs/COMMUNITY_REGRESSION_MATRIX.md for the per-scenario mapping. Each
# entry below points at an existing, currently-passing test -- nothing here
# invents coverage.
# ---------------------------------------------------------------------------
SLICE_3_4D_REAL_POB_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="WSCTX-CROSS-SET-READ-RESTORE",
        test_file="tests/integration/test_weapon_set_component_contexts.py",
        node_name="test_same_reference_reads_under_both_sets_with_exact_restore",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="The same ComponentReference reads under set 1 and set 2 as two disjoint cache observations (shared component identity, distinct context identity) with exact fingerprint/equipment restore.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="WSCTX-REPEATED-SWITCH-DETERMINISTIC",
        test_file="tests/integration/test_weapon_set_component_contexts.py",
        node_name="test_repeated_set_switching_is_deterministic",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Repeated set2->set1->set2 component reads are deterministic per set (same status, same output when measured).",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="WSCTX-SIBLING-ISOLATION",
        test_file="tests/integration/test_weapon_set_component_contexts.py",
        node_name="test_sibling_effects_share_no_context_observation",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two sibling effects under two weapon sets yield four disjoint context cache identities -- no observation is ever shared.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="WSCTX-PHYSICAL-SET2-ISOLATED",
        test_file="tests/integration/test_weapon_set_component_contexts.py",
        node_name="test_physical_set2_candidate_is_isolated_and_restored",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="A candidate placed in the exact physical Weapon 1 Swap slot measures a real component delta with the opposite set byte-identical and the fingerprint restored.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="WSCTX-PHYSICAL-SET1-LEAVES-SET2",
        test_file="tests/integration/test_weapon_set_component_contexts.py",
        node_name="test_physical_set1_candidate_leaves_set2_identical",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="A set-1 physical placement never touches set 2 (both swap slots byte-identical) and restores exactly.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="WSCTX-FAILURES-CLOSE-AND-RESTORE",
        test_file="tests/integration/test_weapon_set_component_contexts.py",
        node_name="test_context_failures_close_and_restore",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Invalid weapon set, cross-set physical slot, and failed candidate calculation all fail closed with the baseline fingerprint and context restored.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="WSCTX-CORRUPT-RESTORE-FAILS-CLOSED",
        test_file="tests/integration/test_weapon_set_component_contexts.py",
        node_name="test_corrupt_contextual_restore_fails_closed",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="A corrupted contextual restore raises RestoreFailed and the next load re-parses a known-good baseline (mirrors the ordinary-path recovery contract).",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="WSCTX-ORDINARY-CHECK-NO-CONTEXT-RPCS",
        test_file="tests/integration/test_weapon_set_component_contexts.py",
        node_name="test_ordinary_item_check_uses_no_context_path_and_is_unchanged",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Ordinary ring Item Check invokes zero contextual RPCs and keeps its FULL/MEANINGFUL_UPGRADE result -- the contextual path is explicit-only.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="XBASE-SAME-BASE-MEASURES",
        test_file="tests/integration/test_contextual_incompatible_placement_real_pob.py",
        node_name="test_compatible_same_base_replacements_still_measure",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Same-base replacements in both weapon sets still measure normally with clean restore (the FIX-02 guard never over-fires on compatible placements).",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="XBASE-CROSS-OFFHAND-UNAVAILABLE",
        test_file="tests/integration/test_contextual_incompatible_placement_real_pob.py",
        node_name="test_cross_base_offhand_disturbance_is_unavailable_not_corrupt",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="A cross-base placement that would disturb the paired offhand aborts to UNAVAILABLE/NOT_VALID_IN_CONTEXT naming the disturbed slot, restores exactly, and leaves the worker healthy for the next transaction.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="XBASE-CROSS-PRIMARY-UNAVAILABLE",
        test_file="tests/integration/test_contextual_incompatible_placement_real_pob.py",
        node_name="test_cross_base_primary_disturbance_is_unavailable_not_corrupt",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="A cross-base placement disturbing the primary pairing aborts to UNAVAILABLE/NOT_VALID_IN_CONTEXT with exact restore and the original weapon set retained.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="CTXDIAG-CATALOGS-ENUMERATE-RESTORE",
        test_file="tests/integration/test_contextual_diagnostic_real_pob.py",
        node_name="test_both_weapon_set_catalogs_enumerate_with_restore",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Both weapon-set effect catalogs enumerate (set-2 read costs zero settle frames) with disjoint context identities and exact set/fingerprint/weapon restore.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="CTXDIAG-FULL-CHAIN-WEAPON-SWAP",
        test_file="tests/integration/test_contextual_diagnostic_real_pob.py",
        node_name="test_full_diagnostic_chain_on_weapon_swap",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Full read-only diagnostic chain (candidate -> measurements -> evidence -> proof -> scope -> eligibility) on the weapon-swap fixture: schema-complete, provenance-bound, restore-exact, and ordinary Item Check still uses zero contextual RPCs.",
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="EFFENUM-SIBLING-COMPONENTS",
        test_file="tests/integration/test_effect_level_enumeration.py",
        node_name="test_additional_granted_effects_are_distinct_cache_backed_components",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Sibling granted effects (EscapeShot/IceFragment, InfernalCry/CorpseExplosion) share one group but carry distinct semantic and cache identities, all GlobalCache-backed and measured.",
        archetypes=(Archetype.WEAPON_SWAP, Archetype.MELEE),
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="EFFENUM-READS-DETERMINISTIC",
        test_file="tests/integration/test_effect_level_enumeration.py",
        node_name="test_exact_effect_reads_do_not_cross_contaminate_and_are_deterministic",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Repeated catalog listings are identical and exact sibling reads return their own identities from GLOBAL_CACHE without cross-contamination and without a restore transaction.",
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-MELEE-WEAPON",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="EFFENUM-CACHE-MISS-FALLBACK",
        test_file="tests/integration/test_effect_level_enumeration.py",
        node_name="test_cache_miss_fallback_restores_selected_effect_and_calc_state",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="A forced cache miss falls back to a transactional recalc that measures the exact requested semantic identity and restores main-skill identity, fingerprint, stat set, part, stage, and calculation mode.",
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-MELEE-WEAPON",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="EFFENUM-MALFORMED-FAIL-CLOSED",
        test_file="tests/integration/test_effect_level_enumeration.py",
        node_name="test_malformed_effect_results_fail_closed_and_restore",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Malformed cache entries and malformed fallback results surface as UNAVAILABLE with the precise reason, never a synthetic output, with the fingerprint restored.",
        archetypes=(Archetype.MELEE,),
        manifest_id="CORE04-MELEE-WEAPON",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="EFFENUM-BOUND-AND-ORDINARY-CHECK",
        test_file="tests/integration/test_effect_level_enumeration.py",
        node_name="test_effect_bound_and_ordinary_item_check_behavior",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Cross-cutting bound: the effect catalog is capped at 8 with explicit truncation, and ordinary ring Item Check keeps its FULL/MEANINGFUL_UPGRADE result.",
        role=CaseRole.STATE_INTEGRITY,
    ),
)

# ---------------------------------------------------------------------------
# CORPUS-02A real-build regression (tests/integration/test_corpus02_giants_blood_shield.py)
# — the community `get_tree_snapshot` report plus Item Check behavior of a Giant's
# Blood two-hand-mace-plus-shield build. Numeric expectations are checked against
# independent cold PoB loads of edited copies of the build. See docs/CORPUS-02A.md.
# ---------------------------------------------------------------------------
CORPUS_02A_REAL_POB_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="TREE-SNAPSHOT-NON-UTF8-CODE-PAGE-REGRESSION",
        test_file="tests/integration/test_corpus02_giants_blood_shield.py",
        node_name="test_tree_snapshot_survives_non_utf8_worker_code_page",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Regression for the community 'get_tree_snapshot' failure: with the worker child "
            "forced to cp1251, the real controller baseline reload returns the passive tree "
            "with its non-ASCII node name intact and a following Item Check completes and "
            "restores. Fails on pre-0.4.0b1 worker stdio exactly as reported."
        ),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
    ),
    CoverageCase(
        id="GIANTS-BLOOD-BASELINE-ACTIVE-WEAPON-SET",
        test_file="tests/integration/test_corpus02_giants_blood_shield.py",
        node_name="test_giants_blood_baseline_identity_and_active_weapon_set",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Two-hand mace in Weapon 1 and Chernobog's Pillar in Weapon 2 both resolve as the "
            "active set (inactive swap talisman ignored); primary is CombinedDPS = hit + ignite."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
    ),
    CoverageCase(
        id="GIANTS-BLOOD-TWO-HAND-CANDIDATE-KEEPS-SHIELD",
        test_file="tests/integration/test_corpus02_giants_blood_shield.py",
        node_name="test_giants_blood_two_hand_candidate_keeps_shield_and_matches_pob",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A two-hand mace candidate replaces Weapon 1 without clearing the shield "
            "(paired_offhand_cleared false), FULL with a positive offense verdict matching a "
            "cold PoB load; PoB's alternative off-hand placement stays PARTIAL/UNCERTAIN."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="CHERNOBOG-SHIELD-LOSS-SEMANTICS-CHANGE-UNCERTAIN",
        test_file="tests/integration/test_corpus02_giants_blood_shield.py",
        node_name="test_chernobog_shield_loss_is_measured_by_pob_but_stays_uncertain",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "Replacing Chernobog's Pillar (fire damage per block chance) with a plain tower "
            "shield: PoB shows a >20% loss and the ignite component disappears, so the "
            "primary metric changes from hit+ailment to hit only. Reported PARTIAL/UNCERTAIN "
            "with offense UNMEASURED, never a confident directional verdict."
        ),
        archetypes=(Archetype.MELEE, Archetype.UNIQUE_INTERACTION, Archetype.STAT_STACKER),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
        functional=FunctionalMeasurement.PARTIALLY_MEASURED,
        audit=UncertaintyAudit.FIXABLE_MEASUREMENT_GAP,
        audit_note="PoB's CombinedDPS exists on both sides; the primary-skill guard refuses because the quantity changes from hit+ailment to hit only (documented scoring-policy decision, CORPUS-02A section 6). Affects candidates that add or remove an ailment component. Owner decision, small-medium effort; refusal is truthful, not a 1.0 blocker.",
    ),
    CoverageCase(
        id="GIANTS-BLOOD-INELIGIBLE-TWO-HANDER-CLEARS-SHIELD",
        test_file="tests/integration/test_corpus02_giants_blood_shield.py",
        node_name="test_ineligible_two_hander_clears_shield_and_is_not_viable",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A talisman (not covered by Giant's Blood) clears the shield in PoB's own "
            "transaction; the removed shield is disclosed and the main mace skill becomes "
            "unusable (PoB CombinedDPS 0), so the verdict is NOT_VIABLE."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
        functional=FunctionalMeasurement.PARTIALLY_MEASURED,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note="Decisive NOT_VIABLE (MAIN_SKILL_INVALID): the main skill needs the shield PoB drops, PoB's own output is zero, and the paired-offhand removal is disclosed. Quality is PARTIAL because offense of a build that cannot use its skill is intentionally not scored.",
    ),
    CoverageCase(
        id="GIANTS-BLOOD-REPEATED-EVALUATION-NO-LEAK",
        test_file="tests/integration/test_corpus02_giants_blood_shield.py",
        node_name="test_giants_blood_repeated_evaluation_is_deterministic_and_restores",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Weapon, shield and talisman candidates interleaved: the repeated weapon check is "
            "identical and the build's fingerprint and equipment return to baseline."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
)

# ---------------------------------------------------------------------------
# CORPUS-02B minion and Djinn verdicts (tests/integration/test_corpus02b_minion_djinn.py)
# — minion-owned Item Check verdicts on the Infernal Hound and Varashta Djinn
# fixtures, each numeric expectation checked against an independent cold PoB load.
# The Varashta fixture is a public ladder build, not the community report's build.
# See docs/CORPUS-02B.md.
# ---------------------------------------------------------------------------
CORPUS_02B_REAL_POB_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="MINION-DAMAGE-RING-MEASURED",
        test_file="tests/integration/test_corpus02b_minion_djinn.py",
        node_name="test_minion_damage_ring_is_measured_on_the_minion_actor",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A +30% minion damage ring is measured on the hound (Minion.CombinedDPS, MINION actor "
            "SummonedHellhound; player CombinedDPS is 0): FULL, offense-only upgrade, matching PoB."
        ),
        archetypes=(Archetype.MINION,),
        manifest_id="CORE04-MINION-ACTOR",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MINION-SKILL-LEVEL-LOSS-MEASURED",
        test_file="tests/integration/test_corpus02b_minion_djinn.py",
        node_name="test_losing_minion_skill_levels_is_a_measured_minion_downgrade",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Removing +4 to Level of all Minion Skills from the amulet: same minion actor and skill, "
            "a PoB-verified >30% minion DPS loss, FULL / MEANINGFUL_DOWNGRADE."
        ),
        archetypes=(Archetype.MINION,),
        manifest_id="CORE04-MINION-ACTOR",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MINION-PLAYER-DEFENSE-RING-TRADEOFF",
        test_file="tests/integration/test_corpus02b_minion_djinn.py",
        node_name="test_player_defense_ring_is_a_minion_offense_versus_defense_tradeoff",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A player-defense ring replacing a minion ring: minion offense down, player defense up, "
            "FULL / SIDEGRADE in both ring slots."
        ),
        archetypes=(Archetype.MINION,),
        manifest_id="CORE04-MINION-ACTOR",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MINION-REPEATED-EVALUATION-NO-LEAK",
        test_file="tests/integration/test_corpus02b_minion_djinn.py",
        node_name="test_minion_repeated_evaluation_is_deterministic_and_restores",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Interleaved minion candidates: the repeated check is identical and fingerprint/equipment "
            "return to baseline."
        ),
        archetypes=(Archetype.MINION,),
        manifest_id="CORE04-MINION-ACTOR",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="DJINN-MINION-LEVELS-AND-ALL-DJINN-COMPONENTS",
        test_file="tests/integration/test_corpus02b_minion_djinn.py",
        node_name="test_djinn_minion_levels_are_measured_and_every_djinn_component_is_reported",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Ascendancy-granted Water Djinn primary: losing +5 minion levels is FULL / "
            "MEANINGFUL_DOWNGRADE, and Ruzhan and Kelari (Fire/Sand Djinn) now appear as measured PoB "
            "damage components matching cold PoB loads (previously omitted: empty PoB baseFlags)."
        ),
        archetypes=(Archetype.MINION, Archetype.ASCENDANCY),
        manifest_id="CORPUS02B-VARASHTA-DJINN",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="DJINN-MINION-DAMAGE-RING-UPGRADE",
        test_file="tests/integration/test_corpus02b_minion_djinn.py",
        node_name="test_djinn_minion_damage_ring_is_a_measured_upgrade_and_restores",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A +30% minion damage ring on the Djinn build: FULL directional upgrade on Navira's "
            "Minion.CombinedDPS matching PoB, identical on repeat, fingerprint restored."
        ),
        archetypes=(Archetype.MINION, Archetype.ASCENDANCY),
        manifest_id="CORPUS02B-VARASHTA-DJINN",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="DJINN-COMMAND-MAIN-SKILL-UNCERTAIN",
        test_file="tests/integration/test_corpus02b_minion_djinn.py",
        node_name="test_djinn_command_as_main_skill_is_truthfully_uncertain",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "Configuration variant with the player-cast Djinn Command selected in PoB: PoB calculates "
            "no offense, so Item Check is PARTIAL / UNCERTAIN (OFFENSE_MISSING), never directional."
        ),
        archetypes=(Archetype.MINION,),
        manifest_id="CORPUS02B-VARASHTA-DJINN",
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='PoB calculates no offense at all when the player-cast Command effect is the main skill; nothing exists to measure. Item Check names the cause and the group sibling that would be measurable (MAIN-SKILL-01).',
    ),
)

# ---------------------------------------------------------------------------
# CORPUS-02C Way of the Stonefist (tests/integration/test_corpus02c_stonefist.py) — ordinary
# gloves are transformed in memory into the Fists of Stone item the character
# equips and PoB measures it; ranged transformed rolls are verified across their
# range. Numeric expectations are checked against hand-transformed reference
# items in cold PoB loads. See docs/CORPUS-02C.md.
# ---------------------------------------------------------------------------
CORPUS_02C_REAL_POB_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="STONEFIST-DETECTED-AND-UNMODELED-BY-SUPPORTED-POB",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_stonefist_is_detected_and_the_supported_pob_does_not_model_it",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "The bridge reports Way of the Stonefist (Gloves -> Fists of Stone) with PoB's own "
            "modeled=False; a PoB revision that parses it trips this test and must be re-validated."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
    ),
    CoverageCase(
        id="STONEFIST-TRANSFORMED-GLOVES-MEASURED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_transformed_glove_comparison_is_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Fists of Stone vs Fists of Stone (exported gloves minus their crit line): FULL, matching a cold PoB load.",
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-FIXED-VALUE-GLOVE-EXACT",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_fixed_value_ordinary_glove_is_transformed_exactly",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "An ordinary glove whose modifiers all transform to fixed values is evaluated as the exact "
            "Fists of Stone item (HandWraps ids asserted), matching a hand-transformed reference in PoB."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-NO-DOUBLE-TRANSFORMATION",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_already_transformed_gloves_are_never_transformed_twice",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Exported (already transformed) gloves are never transformed again, as candidate or baseline; metrics equal the export.",
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-ROLL-BOUNDS-MATCH-REFERENCES",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_ranged_rolls_are_bounded_by_independent_reference_items",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Real Massive Mitts with ranged transformed modifiers: worst/best PoB runs equal hand-transformed "
            "worst/best reference items; worst/middle/best verdicts agree and a verified range is reported."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-ORDINARY-REAL-GLOVES-VERIFIED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_ordinary_real_gloves_receive_verified_verdicts",
        node_name_is_prefix=True,
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Seven real ordinary gloves (runeforged, corrupted, separate same-stat lines, overlapping tiers) "
            "receive FULL verdicts on the transformed item, verified across their roll range, with exact restore."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-GUARANTEED-UPGRADE-COMMUNICATED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_guaranteed_upgrade_across_every_roll_is_communicated",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Hand-built baseline with weak ordinary gloves: a better ordinary glove is an upgrade at every "
            "transformed roll; the reported range matches hand-transformed worst/best references."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-ROLL-DEPENDENT-DETERMINISTIC-RESTORE",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_roll_dependent_evaluation_is_deterministic_and_restores",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Repeated roll-dependent evaluations are identical and fingerprint/equipment return to baseline.",
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-HAND-BUILT-BASELINE-TRANSFORMED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_ordinary_equipped_gloves_are_transformed_for_the_baseline",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A hand-built PoB with ordinary equipped gloves: an amulet check is measured on the in-memory "
            "transformed baseline (matching a reference load) and the user's build is restored untouched."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-CHARACTER-LEVEL",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_transformed_defences_follow_the_character_level",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="At character level 70 the transformed per-level defences match a level-70 reference load.",
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-INEXACT-BASELINE-DISCLOSED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_inexact_equipped_gloves_are_disclosed_on_other_slots",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "Hand-built PoB with ordinary ranged gloves: other slots are measured but PARTIAL/UNCERTAIN "
            "(STONEFIST_BASELINE_UNTRANSFORMED), never a confident recommendation on an untransformed baseline."
        ),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note="A hand-built PoB with ordinary ranged gloves cannot give an exact transformed baseline; every other slot's effect can depend on the unknown gloves, so a confident verdict would be invented. Disclosed (STONEFIST_BASELINE_UNTRANSFORMED). Way of the Stonefist only.",
    ),
    CoverageCase(
        id="STONEFIST-UNRESOLVABLE-GLOVES-UNSUPPORTED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_unresolvable_gloves_stay_unsupported_with_the_precise_reason",
        node_name_is_prefix=True,
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNSUPPORTED,
        description=(
            "Remaining gaps, not coverage: unique gloves without real-item evidence of their modifiers, and "
            "gloves whose lines match no glove-modifier combination, stay UNSUPPORTED with the reason."
        ),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.UNSUPPORTED_MECHANIC,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='Unique gloves without real-item evidence of their modifiers, and gloves whose lines match no glove-modifier combination, are refused with the precise reason. Way of the Stonefist gloves only; adding evidence is per-unique data work.',
    ),
    CoverageCase(
        id="STONEFIST-UNIQUE-GLOVES-VERIFIED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_corpus_unique_gloves_receive_a_verified_verdict",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Real unique gloves (Aurseize from the CORE-04 weapon-swap build) transform exactly like the game's "
            "transformed Aurseize (poe.ninja); FULL verdict across the roll range and single-roll probes, exact restore."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-UNIQUE-UNORDERED-RESULTS-UNSUPPORTED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_a_unique_whose_pob_results_are_not_ordered_stays_unsupported",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNSUPPORTED,
        description=(
            "Candlemaker: PoB's DPS falls as one transformed roll grows, so no verdict holds for every roll; "
            "UNSUPPORTED with the reason."
        ),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.UNSUPPORTED_MECHANIC,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note="Candlemaker: PoB's DPS falls as one transformed roll grows (a resistance-reduction line), so no verdict holds for every roll. PoB output is non-monotone; a verdict would be unsound.",
    ),
    CoverageCase(
        id="STONEFIST-SINGLE-ROLL-PROBES",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_each_ranged_line_is_probed_alone_for_a_real_glove",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Assumption (A) check: each ranged transformed line is also measured alone at its best roll, in the "
            "same PoB transaction; every probe is ordered between worst and best and agrees on the verdict."
        ),
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STONEFIST-NON-GLOVE-CANDIDATES-STAY-MEASURED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_non_glove_candidates_on_a_stonefist_build_stay_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="The transformation is scoped to gloves: an amulet candidate stays FULL and matches PoB.",
        manifest_id="CORPUS02C-STONEFIST",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
)


# ---------------------------------------------------------------------------
# CORE-04 adversarial policy suite (tests/test_core_04_adversarial_item_check.py)
# — deterministic, worker-shaped unit tests of outcome policy. No real PoB, no
# build fixture: these are the safety net around the verdict/quality contract
# itself, not build-archetype coverage. Reported separately from the archetype
# matrix (see docs/corpus_coverage/COVERAGE_REPORT.md, "Policy safety-net" section).
#
# `node_name_is_prefix=True` cases are grouped: many pytest.mark.parametrize
# variants roll up into one coverage case, graded PASS only if every variant passes.
# ---------------------------------------------------------------------------
POLICY_UNIT_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="SLOT-MAPPING-SEMANTIC",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_supported_slot_mapping_is_semantic_not_position_only",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="PoB slot -> product slot mapping is item-type aware (bow/quiver/shield/focus/wand), not position-only.",
    ),
    CoverageCase(
        id="SLOT-SELECTION-PREFERS-FULL",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_ring_slot_selection_prefers_full_evidence_over_partial_and_unsupported",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="A high-scoring UNSUPPORTED slot never outranks a lower-scoring FULL-evidence slot.",
    ),
    CoverageCase(
        id="SLOT-SELECTION-FULL-OVER-UNSUPPORTED-DOWNGRADE",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_ring_slot_selection_preserves_valid_full_downgrade_over_unsupported",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="A FULL-evidence downgrade still outranks an UNSUPPORTED slot with a higher raw rating.",
    ),
    CoverageCase(
        id="SLOT-TIEBREAK-STABLE",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_ring_slot_equal_outcomes_have_a_stable_slot_tiebreaker",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="Equal-outcome ring slots resolve to a stable, order-independent tiebreak.",
    ),
    CoverageCase(
        id="REDUCED-EVIDENCE-NEVER-DIRECTIONAL",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_reducing_evidence_never_emits_a_directional_verdict",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNCERTAIN,
        description="PARTIAL/UNSUPPORTED/FAILED quality can never produce a directional up/downgrade verdict.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='Fail-closed invariant: reduced evidence can never emit a directional verdict.',
    ),
    CoverageCase(
        id="KNOWN-ZERO-VS-MISSING",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_known_zero_is_available_but_missing_is_not",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="A legitimate zero metric stays available/scored; a missing metric is excluded from scoring, never coerced to zero.",
    ),
    CoverageCase(
        id="MALFORMED-METRICS-FAIL-CLOSED",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_malformed_worker_output_fails_closed",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNCERTAIN,
        description="Non-numeric/NaN/infinity/bool worker metrics produce FAILED quality + NOT_EVALUATED, never a thrown exception or a silent numeric coercion.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='Fail-closed invariant: malformed worker output is FAILED/NOT_EVALUATED, never coerced.',
    ),
    CoverageCase(
        id="RESISTANCE-CAP-STATE-BOUNDARIES",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_resistance_state_boundaries",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="Below-cap improvement, cap-reached, stays-capped, overcap-buffer-loss-but-still-capped, and cap-lost are each classified distinctly.",
    ),
    CoverageCase(
        id="MISSING-RESISTANCE-UNKNOWN",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_missing_resistance_is_unknown_not_zero_deficit",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNCERTAIN,
        description="A missing resistance reads as UNKNOWN state, never silently treated as a zero deficit.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='Fail-closed invariant: a missing resistance is UNKNOWN, never a zero deficit.',
    ),
    CoverageCase(
        id="SCORE-BAND-BOUNDARIES",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_public_verdict_threshold_boundaries",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="Score-band boundaries (60/53/47/40) classify to the exact adjacent PublicVerdict on both sides.",
    ),
    CoverageCase(
        id="CROSS-AXIS-TRADEOFF-NOT-FLATTENED",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_meaningful_cross_axis_tradeoff_is_not_flattened_by_aggregate_score",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="A large offense gain with a large defense loss is classified TRADEOFF, not averaged away by an aggregate score.",
    ),
    CoverageCase(
        id="GUARDRAILS-OVERRIDE-ATTRACTIVE-SCORE",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_critical_constraints_remain_separate_from_an_attractive_score",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="An attribute-requirement loss or a resource (mana sustain) failure forces NOT_VIABLE regardless of an attractive raw score.",
        archetypes=(Archetype.ATTRIBUTE_STACKER, Archetype.MANA_SCALING),
    ),
    CoverageCase(
        id="EMPTY-VS-UNKNOWN-SLOT",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_empty_slot_is_distinct_from_an_unknown_baseline_slot",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="An explicitly empty slot and an unknown/absent baseline slot are never conflated.",
    ),
    CoverageCase(
        id="CANDIDATE-FINGERPRINT-NORMALIZATION",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_candidate_fingerprint_normalizes_formatting_but_not_semantics",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="Candidate fingerprint is stable across CRLF/whitespace formatting but changes on any semantic modifier change.",
    ),
    CoverageCase(
        id="CONTEXT-IDENTITY-CHANGES",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_context_identity_changes_for_material_evaluation_context",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="Loadout, item set, worker generation, source revision, and calculation-context changes each change the evaluation-context identity token.",
    ),
    CoverageCase(
        id="EXPLICIT-RESTORE-FAILURE-FAILS-CLOSED",
        test_file="tests/test_core_04_adversarial_item_check.py",
        node_name="test_assess_quality_marks_explicit_restore_failure_as_failed",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNCERTAIN,
        description="An explicit restore failure is graded FAILED quality, never silently treated as a successful comparison.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='Fail-closed invariant: a restore failure is never presented as a valid comparison.',
    ),
    CoverageCase(
        id="STONEFIST-DECOMPOSITION-POLICY",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_merged_same_stat_line_is_decomposed_into_both_modifiers",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="CORPUS-02C: a merged same-stat line decomposes into its unique source modifiers.",
    ),
    CoverageCase(
        id="STONEFIST-OVERLAPPING-TIERS-POLICY",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_overlapping_tiers_widen_the_bounds_only",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="CORPUS-02C: overlapping source tiers widen worst/middle/best bounds and stay unresolved without bounds.",
    ),
    CoverageCase(
        id="STONEFIST-INDEPENDENT-RANGED-MODIFIERS",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_independent_ranged_modifiers_take_their_own_bounds",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="CORPUS-02C: each ranged modifier takes its own worst/middle/best value; 'slower' lines invert.",
    ),
    CoverageCase(
        id="STONEFIST-VERDICT-SPANNING-REFUSED",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_verdict_changing_across_the_roll_range_is_refused",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C: a verdict that changes across the roll range is refused (stubbed PoB results).",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='A verdict that changes across the unknown roll range cannot be stated; refused.',
    ),
    CoverageCase(
        id="STONEFIST-NON-MONOTONE-REFUSED",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_non_monotone_pob_results_are_refused_even_when_verdicts_match",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C: matching verdicts are not proof when PoB outputs are not ordered across the rolls.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note="Equal verdicts are not proof when PoB's outputs are not ordered across the rolls; refused.",
    ),
    CoverageCase(
        id="STONEFIST-ALTERNATIVES-MUST-AGREE",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_every_decomposition_alternative_must_agree",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C: when displayed lines fit several modifier combinations, all resulting items must share one verdict.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='When displayed lines fit several modifier combinations every alternative must agree, otherwise refused.',
    ),
    CoverageCase(
        id="STONEFIST-VERDICT-STRUCTURE-MUST-MATCH",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_same_verdict_reached_through_different_patterns_is_refused",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C review: a verdict reached through different impact patterns across the roll range is refused.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='A verdict reached through different impact patterns across the range is refused.',
    ),
    CoverageCase(
        id="STONEFIST-GUARANTEED-RANGE-REPORTED",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_consistent_ordered_range_reports_a_guaranteed_verdict",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="CORPUS-02C: an ordered, agreeing range is reported as a verified range with an explicit guarantee.",
    ),
    CoverageCase(
        id="ITEM-TRANSFORM-GUARD-SCOPE",
        test_file="tests/test_item_transform_guard.py",
        node_name="test_guard_flags_only_glove_comparisons_that_are_not_like_for_like",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="CORPUS-02C: only transformed-slot comparisons that are not Fists of Stone on both sides are flagged.",
    ),
    CoverageCase(
        id="ITEM-TRANSFORM-POB-CLAIM-NOT-TRUSTED",
        test_file="tests/test_item_transform_guard.py",
        node_name="test_guard_does_not_trust_a_pob_modelling_claim",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C: a PoB revision that parses Way of the Stonefist (e.g. PR #2350) does not lift the guard unvalidated.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='A PoB revision that claims to model Way of the Stonefist does not lift the guard unvalidated.',
    ),
    CoverageCase(
        id="ITEM-TRANSFORM-FLAGGED-IS-UNSUPPORTED",
        test_file="tests/test_item_transform_guard.py",
        node_name="test_flagged_comparison_is_unsupported_quality",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C: a flagged comparison is EvaluationQuality.UNSUPPORTED with reason ITEM_TRANSFORM_UNMODELED.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='A flagged item-transform comparison is UNSUPPORTED (ITEM_TRANSFORM_UNMODELED), never scored.',
    ),
)

# ---------------------------------------------------------------------------
# CORPUS-02D1 poison and damaging-ailment Item Check (docs/CORPUS-02D1.md).
# Reuses the CORE04 poison and weapon-swap fixtures; edited copies cover the
# really-hitting "Arrow" stat set and a configured poison-stack count. Every
# number is checked against an independent cold PoB load of the edited build.
# ---------------------------------------------------------------------------
_D1_FILE = "tests/integration/test_corpus02d1_poison_ailment.py"
_D1_UNIT = "tests/test_corpus02d1_ailment_intel.py"
CORPUS_02D1_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="POISON-MAGNITUDE-UPGRADE-FRESH-LOAD",
        test_file=_D1_FILE,
        node_name="test_poison_magnitude_upgrade_is_fully_measured_and_matches_a_fresh_load",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Quiver + 40% increased Magnitude of Poison: FULL / MEANINGFUL_UPGRADE, PoisonDPS "
            "+9.24% (PoisonMagnitudeEffect +9.24%), equal to a fresh load of the edited build."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="POISON-DURATION-STACK-CAP-INTERACTION",
        test_file=_D1_FILE,
        node_name="test_duration_and_stack_cap_interaction_follows_pob",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Duration +20% gives PoisonDPS +15.59% (stacks capped at 4); +1 poison stack alone "
            "is a measured zero (SIDEGRADE); both together +20.00%. All FULL, fresh-load checked."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="POISON-DOWNGRADE-AND-OFFENSE-DEFENSE-TRADEOFF",
        test_file=_D1_FILE,
        node_name="test_attack_speed_downgrade_and_offense_defense_tradeoff",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Gloves without attack speed: FULL / MEANINGFUL_DOWNGRADE -11.48% (fewer active "
            "poisons). Gloves trading ES for attack speed: FULL / SIDEGRADE meaningful trade-off "
            "(offense +10.95%, defense down). Fresh-load checked."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="POISON-FAKE-HIT-EXCLUDED-REPEATED-RESTORE",
        test_file=_D1_FILE,
        node_name="test_fake_hit_is_excluded_and_repeated_evaluations_restore_exactly",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "The no-hit Poison Burst stat set's PoB TotalDPS is reported as an excluded fake "
            "hit, ailment factors as incorporated; two FULL evaluations are identical and the "
            "restored build equals the baseline exactly."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="POISON-REAL-HIT-STAT-SET-COMBINED",
        test_file=_D1_FILE,
        node_name="test_real_hit_stat_set_scores_pobs_combined_hit_and_poison",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Edited copy on the 'Arrow' stat set (real hit ~19%): poison -42% with hit +12% is "
            "scored on PoB's CombinedDPS (-31.54%), FULL / MEANINGFUL_DOWNGRADE, fresh-load checked."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT, Archetype.RANGED_ATTACK),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="POISON-CONFIGURED-STACKS-UNCERTAIN",
        test_file=_D1_FILE,
        node_name="test_configured_poison_stack_count_keeps_a_specific_uncertainty",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "Edited copy with '# of Poisons on enemy' configured: PoB fixes the stacks, poison "
            "duration no longer moves PoisonDPS, and the comparison is PARTIAL / UNCERTAIN with "
            "the specific AILMENT_STACK_SCOPE_UNPROVEN reason."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note="The build's configuration fixes the poison stack count, so duration/application changes cannot move PoisonDPS; claiming a measured poison comparison would be invented.",
    ),
    CoverageCase(
        id="POISON-INERT-PROBE-CARRIER-SKIPPED",
        test_file=_D1_FILE,
        node_name="test_inert_probe_carrier_is_skipped",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Weapon-swap build: Ring 1 is Kalandra's Touch, whose added lines PoB ignores; the "
            "poison audit skips it, probes Ring 2 and the quiver check is FULL."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT, Archetype.WEAPON_SWAP, Archetype.UNIQUE_INTERACTION),
        manifest_id="CORE04-WEAPON-SWAP",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="AILMENT-STACK-SCOPE-UNPROVEN-POLICY",
        test_file=_D1_UNIT,
        node_name="test_poison_stack_count_fixed_by_configuration_stays_partial_with_reason",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNCERTAIN,
        description="A poison audit whose duration probe is insensitive stays PARTIAL with AILMENT_STACK_SCOPE_UNPROVEN.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='Unit proof of the refusal asserted for real PoB by POISON-CONFIGURED-STACKS-UNCERTAIN.',
    ),
    CoverageCase(
        id="AILMENT-HIT-CONFLICT-POLICY",
        test_file=_D1_UNIT,
        node_name="test_hit_ailment_conflict_is_a_specific_partial_reason",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNCERTAIN,
        description="A scored ailment moving against a material real hit is PARTIAL with AILMENT_HIT_COMPONENTS_DISAGREE.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='A scored ailment moving against a material real hit means the components disagree; refusing is the safe answer.',
    ),
)


# ---------------------------------------------------------------------------
# CORPUS-02D2: the community-reported Voltaic Barrier build (docs/CORPUS-02D2.md).
# The as-exported build (PoB's own saved main skill, "Virtuous Barrier", has zero
# offense) is correctly, truthfully UNCERTAIN. An edited copy re-pinning PoB's main
# skill to "Voltaic Barrier" (the skill the report names, a real weapon-scaling
# attack skill) is FULL. Every number is checked against an independent cold PoB
# load of the edited build.
# ---------------------------------------------------------------------------
_D2_FILE = "tests/integration/test_corpus02d2_voltaic_barrier.py"
CORPUS_02D2_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="VOLTAIC-BARRIER-AS-EXPORTED-UNCERTAIN",
        test_file=_D2_FILE,
        node_name="test_as_exported_main_skill_has_no_offense_and_item_checks_are_truthfully_uncertain",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "As retrieved from pobb.in: PoB's saved main skill (Virtuous Barrier) is a pure "
            "reservation/buff skill with zero calculated offense. A weapon Item Check correctly "
            "stays PARTIAL/UNCERTAIN -- never a confident verdict manufactured from a skill that "
            "deals no damage. This is the most direct reproduction available of the reported "
            "symptom, and it is a genuine PoB build-state characteristic, not a defect."
        ),
        archetypes=(Archetype.ASCENDANCY, Archetype.WEAPON_SWAP),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note="The saved main skill (Virtuous Barrier) deals no damage; Item Check never manufactures a verdict from it. The most common 'UNCERTAIN for everything' cause; the actionable diagnostic is asserted by MAINSKILL-VOLTAIC-ACTIONABLE-DIAGNOSTIC.",
    ),
    CoverageCase(
        id="VOLTAIC-BARRIER-AS-EXPORTED-DEFENSE-MEASURED",
        test_file=_D2_FILE,
        node_name="test_as_exported_defensive_candidate_measures_defense_even_without_offense",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "On the same zero-offense as-exported build, a life-focused ring still gets a "
            "truthful, measured DEFENSE verdict -- PARTIAL overall (offense unmeasured), but not "
            "every axis is discarded."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='Offense is genuinely unmeasurable on the as-exported build; defense is still measured and reported, not discarded.',
    ),
    CoverageCase(
        id="VOLTAIC-BARRIER-MAIN-WEAPON-UPGRADE-FRESH-LOAD",
        test_file=_D2_FILE,
        node_name="test_voltaic_barrier_as_main_measures_a_real_weapon_upgrade",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "With PoB's main skill re-pinned to Voltaic Barrier (the skill the report names -- a "
            "real weapon-scaling attack skill, 100% physical-to-lightning conversion), a crossbow "
            "upgrade is FULL / MEANINGFUL_UPGRADE, matching an independent fresh PoB reload of the "
            "edited build."
        ),
        archetypes=(Archetype.ASCENDANCY, Archetype.WEAPON_SWAP),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="VOLTAIC-BARRIER-DOWNGRADE-AND-AMULET-UPGRADE",
        test_file=_D2_FILE,
        node_name="test_voltaic_barrier_downgrade_and_amulet_upgrade",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A weapon downgrade (FULL / MEANINGFUL_DOWNGRADE) and an unrelated defensive amulet "
            "upgrade (FULL, DEFENSE positive, OFFENSE measured-neutral) on the Voltaic-Barrier-main "
            "build, both fresh-load checked."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="VOLTAIC-BARRIER-REPEATED-EVALUATION-WEAPON-SET-PASSIVES",
        test_file=_D2_FILE,
        node_name="test_repeated_evaluation_and_restore_with_weapon_set_conditional_passives",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "This build allocates 47 weapon-set-conditional passive nodes, more than the existing "
            "weapon-swap fixture. Two consecutive evaluations are identical and the restored build "
            "equals an independent fresh reload exactly, including every conditional node's "
            "contribution."
        ),
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="VOLTAIC-BARRIER-CANDIDATE-ACTIVE-SLOT-SCOPE",
        test_file=_D2_FILE,
        node_name="test_candidate_only_targets_the_active_weapon_slot_and_is_labelled_truthfully",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Submitting the build's own inactive swap-set mace as a candidate resolves only "
            "against the ACTIVE physical slot and truthfully names the crossbow it would actually "
            "replace -- ordinary Item Check never silently writes into the inactive weapon-swap "
            "slot, and never misrepresents which item is being compared."
        ),
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
)

# ---------------------------------------------------------------------------
# MAIN-SKILL-01: actionable diagnostics when the selected main skill has no
# calculated offense (docs/MAIN-SKILL-01.md). Two builds whose symptom looks alike
# but whose causes differ: the Voltaic Barrier build (PoB's saved main skill is a
# zero-damage buff in its own socket group) and the Djinn Command variant (Command
# shares a socket group with the calculated Navira summon).
# ---------------------------------------------------------------------------
_MS_FILE = "tests/integration/test_main_skill_01_real_pob.py"
_MS_UNIT = "tests/test_main_skill_diagnostics.py"
MAIN_SKILL_01_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="MAINSKILL-VOLTAIC-ACTIONABLE-DIAGNOSTIC",
        test_file=_MS_FILE,
        node_name="test_as_exported_voltaic_build_gets_an_actionable_diagnostic",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "As exported, PoB's main skill is Virtuous Barrier (zero offense). Both ring slots are "
            "PARTIAL/UNCERTAIN with the main-skill reason first, the selected skill named by its PoB "
            "identity, the five PoB-calculated alternatives (Voltaic Barrier among them) in group "
            "order, the recovery path, measured DEFENSE preserved, and no automatic skill switch."
        ),
        archetypes=(Archetype.ASCENDANCY,),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.COPY_OR_DIAGNOSTIC,
        audit_note='Refusal is correct; the user-facing remedy (selected skill named by its PoB identity, the PoB-calculated alternatives, how to select in PoB and reload, no automatic switch) shipped in MAIN-SKILL-01 and is what this case asserts. Copy issue resolved.',
    ),
    CoverageCase(
        id="MAINSKILL-SELECT-IN-POB-AND-RELOAD-FULL",
        test_file=_MS_FILE,
        node_name="test_selecting_the_skill_in_pob_and_reloading_gives_full_evaluations",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "The recovery path on one build file: evaluate (UNCERTAIN with diagnostic), save Voltaic "
            "Barrier as PoB's main skill, evaluate again -- ExileLens reloads the changed file and the "
            "weapon upgrade is FULL / MEANINGFUL_UPGRADE with no diagnostic."
        ),
        archetypes=(Archetype.ASCENDANCY, Archetype.WEAPON_SWAP),
        manifest_id="CORPUS02D2-VOLTAIC-BARRIER",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MAINSKILL-DJINN-COMMAND-DIFFERENT-CAUSE",
        test_file=_MS_FILE,
        node_name="test_djinn_command_has_a_different_cause_and_the_group_sibling_is_offered",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "Djinn Command selected: no fallback component is substituted (OFFENSE_MISSING), and the "
            "selected group's own Navira summon (same socket group) is offered alongside the other "
            "calculated minions; selecting Navira and reloading is FULL. Classified as expected "
            "uncertainty: the case's primary claim is the correct diagnostic refusal."
        ),
        archetypes=(Archetype.MINION, Archetype.ASCENDANCY),
        manifest_id="CORPUS02B-VARASHTA-DJINN",
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note="Different cause from Voltaic Barrier: the Command effect has no offense; the diagnostic offers the selected group's own Navira summon.",
    ),
    CoverageCase(
        id="MAINSKILL-MEASURABLE-BUILDS-UNAFFECTED",
        test_file=_MS_FILE,
        node_name="test_builds_with_a_measurable_main_skill_are_unaffected",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Builds whose selected skill PoB measures (poison, Djinn Navira) get no diagnostic, no "
            "MAIN_SKILL_NO_OFFENSE reason and no More Info section; the poison check stays FULL."
        ),
        archetypes=(Archetype.AILMENT, Archetype.MINION),
        manifest_id="CORE04-POISON-AILMENT",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MAINSKILL-ALTERNATIVES-POLICY",
        test_file=_MS_UNIT,
        node_name="test_alternatives_are_only_calculated_skills_in_pob_group_order",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.CONFIDENT,
        description="Alternatives are limited to enabled, PoB-calculated skills, in PoB group order, never ranked by damage.",
    ),
    CoverageCase(
        id="MAINSKILL-REASON-LEADS-POLICY",
        test_file=_MS_UNIT,
        node_name="test_main_skill_reason_leads_the_quality_reasons_and_stays_partial",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNCERTAIN,
        description="MAIN_SKILL_NO_OFFENSE is the first quality reason and the evaluation stays PARTIAL.",
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note='The main-skill reason leads the PARTIAL reasons so the user sees the cause first (copy contract of MAIN-SKILL-01).',
    ),
)

# ---------------------------------------------------------------------------
# CORPUS-02E — authentic Spell Totem (proxy/totem) build. Every measured case is
# checked against an independent fresh PoB load with the candidate equipped.
# ---------------------------------------------------------------------------
_E_FILE = "tests/integration/test_corpus02e_spell_totem.py"
CORPUS_02E_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="SPELL-TOTEM-IDENTITY-AND-DPS-SEMANTICS",
        test_file=_E_FILE,
        node_name="test_spell_totem_group_is_the_selected_player_calculation",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "The Spell Totem group's selected effect is Grim Pillars on the PLAYER output; the meta skill "
            "and the second linked spell deal no damage of their own. PoB's TotalDPS is per-cast damage x "
            "the totem's cast rate (CombinedDPS is the per-cast damage), so TotalDPS is the scored field."
        ),
        archetypes=(Archetype.PROXY_TOTEM, Archetype.SPELL),
        manifest_id="CORPUS02E-SPELL-TOTEM",
    ),
    CoverageCase(
        id="SPELL-TOTEM-OFFENSE-UPGRADE",
        test_file=_E_FILE,
        node_name="test_genuine_offense_upgrade_is_a_full_verdict",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="+2 spell skill levels on the amulet: FULL / MEANINGFUL_UPGRADE, matching a fresh PoB reload.",
        archetypes=(Archetype.PROXY_TOTEM, Archetype.SPELL),
        manifest_id="CORPUS02E-SPELL-TOTEM",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="SPELL-TOTEM-OFFENSE-DOWNGRADE",
        test_file=_E_FILE,
        node_name="test_genuine_offense_downgrade_is_a_full_verdict",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="-2 spell skill levels: FULL / MEANINGFUL_DOWNGRADE, OFFENSE negative, matching a fresh PoB reload.",
        archetypes=(Archetype.PROXY_TOTEM, Archetype.SPELL),
        manifest_id="CORPUS02E-SPELL-TOTEM",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="SPELL-TOTEM-DEFENSE-ONLY-NO-INVENTED-OFFENSE",
        test_file=_E_FILE,
        node_name="test_defense_only_item_improves_the_player_without_inventing_offense",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "More Energy Shield on the amulet: FULL upgrade with DEFENSE positive; the totem's damage and "
            "cast rate are exactly unchanged, so no offensive gain is reported."
        ),
        archetypes=(Archetype.PROXY_TOTEM,),
        manifest_id="CORPUS02E-SPELL-TOTEM",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="SPELL-TOTEM-CAST-SPEED-REACHES-TOTEM",
        test_file=_E_FILE,
        node_name="test_player_cast_speed_reaches_the_totems_cast_rate_as_pob_calculates_it",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Player cast speed raises the totem's PoB cast rate; per-cast damage is unchanged so DPS follows "
            "Speed exactly (FULL / MEANINGFUL_UPGRADE, fresh-load checked)."
        ),
        archetypes=(Archetype.PROXY_TOTEM, Archetype.SPELL),
        manifest_id="CORPUS02E-SPELL-TOTEM",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="SPELL-TOTEM-OFFENSE-DEFENSE-TRADEOFF",
        test_file=_E_FILE,
        node_name="test_offense_gain_with_a_lost_resistance_cap_is_a_flagged_tradeoff",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "+15% totem DPS but Cold Resistance falls below the cap and EHP drops: FULL, TRADEOFF pattern, "
            "RES_CAP_LOST guardrail, never an upgrade; numbers match a fresh PoB reload."
        ),
        archetypes=(Archetype.PROXY_TOTEM,),
        manifest_id="CORPUS02E-SPELL-TOTEM",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="SPELL-TOTEM-REPEATED-EVALUATION-RESTORE",
        test_file=_E_FILE,
        node_name="test_repeated_evaluations_are_identical_and_restore_the_build",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Interleaved evaluations are identical and the fingerprint and equipment return to baseline.",
        archetypes=(Archetype.PROXY_TOTEM,),
        manifest_id="CORPUS02E-SPELL-TOTEM",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
)

# ---------------------------------------------------------------------------
# CORPUS-02F — authentic Mortar Cannon and Siege Ballista builds. Every measured case is
# checked against an independent fresh PoB load with the candidate equipped.
# ---------------------------------------------------------------------------
_F_FILE = "tests/integration/test_corpus02f_mortar_ballista.py"
_F_MORTAR = "CORPUS02F-MORTAR-CANNON"
_F_BALLISTA = "CORPUS02F-BALLISTA"
_F_TAGS = (Archetype.PROXY_TOTEM, Archetype.RANGED_ATTACK)
CORPUS_02F_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="MORTAR-IDENTITY-AND-DPS-SEMANTICS",
        test_file=_F_FILE,
        node_name="test_mortar_selected_effect_is_the_per_use_cluster_grenade",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "The Mortar Cannon group's selected effect is Cluster Grenade on the PLAYER output. PoB's "
            "CombinedDPS is the per-use AverageDamage; TotalDPS is the per-second rate (uses per second, "
            "limited by the cooldown, x PoB's DPS multiplier) for one totem; the totem limit is separate."
        ),
        archetypes=_F_TAGS,
        manifest_id=_F_MORTAR,
    ),
    CoverageCase(
        id="MORTAR-SCORES-THE-PER-SECOND-RATE",
        test_file=_F_FILE,
        node_name="test_mortar_scores_the_per_second_hit_rate_not_the_per_use_average",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="The resolver scores TotalDPS (HIT_DPS, showAverage reason), not the per-use CombinedDPS.",
        archetypes=_F_TAGS,
        manifest_id=_F_MORTAR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MORTAR-OFFENSE-UPGRADE-AND-DOWNGRADE",
        test_file=_F_FILE,
        node_name="test_mortar_offense_upgrade_and_downgrade_match_fresh_loads",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="More/less flat fire damage to attacks on the ring: FULL upgrade / downgrade, fresh-load checked.",
        archetypes=_F_TAGS,
        manifest_id=_F_MORTAR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MORTAR-COOLDOWN-RECOVERY-REACHES-THE-RATE",
        test_file=_F_FILE,
        node_name="test_cooldown_recovery_reaches_the_rate_that_the_per_use_average_cannot_show",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Cooldown recovery leaves PoB's per-use CombinedDPS exactly unchanged but raises the rate: FULL / "
            "MEANINGFUL_UPGRADE. Before the fix the cooldown-limited skill was scored on the per-use figure."
        ),
        archetypes=_F_TAGS,
        manifest_id=_F_MORTAR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MORTAR-DEFENCE-ONLY-NO-INVENTED-OFFENSE",
        test_file=_F_FILE,
        node_name="test_defence_only_ring_leaves_the_mortar_damage_untouched",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="More life on the ring: FULL upgrade, DEFENSE positive, the damage rate exactly unchanged.",
        archetypes=_F_TAGS,
        manifest_id=_F_MORTAR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MORTAR-OFFENSE-DEFENSE-TRADEOFF",
        test_file=_F_FILE,
        node_name="test_offense_gain_with_a_lost_resistance_cap_is_a_flagged_tradeoff",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="More damage but the Fire Resistance cap is lost: FULL, TRADEOFF, RES_CAP_LOST, never an upgrade.",
        archetypes=_F_TAGS,
        manifest_id=_F_MORTAR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MORTAR-IGNITE-ONLY-CHANGE-IS-PARTIAL",
        test_file=_F_FILE,
        node_name="test_ignite_only_change_is_not_claimed_as_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "Ignite chance doubles PoB's IgniteDPS while the scored hit rate is unchanged: PARTIAL / UNCERTAIN "
            "(PER_USE_DOT_NOT_MEASURED). PoB measures the ignite; ExileLens does not yet score a per-use skill's "
            "ignite as a rate."
        ),
        archetypes=(Archetype.PROXY_TOTEM, Archetype.AILMENT),
        manifest_id=_F_MORTAR,
        functional=FunctionalMeasurement.PARTIALLY_MEASURED,
        audit=UncertaintyAudit.FIXABLE_MEASUREMENT_GAP,
        audit_note="PoB measures IgniteDPS; ExileLens scores a per-use skill's hit rate only (PER_USE_DOT_NOT_MEASURED). Small-medium effort, niche (ignite on per-use cooldown skills); truthful refusal, not a blocker.",
    ),
    CoverageCase(
        id="MORTAR-TOTEM-COUNT-CHANGE-IS-PARTIAL",
        test_file=_F_FILE,
        node_name="test_a_changed_totem_count_is_not_claimed_as_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "+1 maximum totems (limit 4 -> 5): PoB's damage is for one totem, so the change in total damage is "
            "not measured; PARTIAL / UNCERTAIN (TOTEM_LIMIT_CHANGED)."
        ),
        archetypes=(Archetype.PROXY_TOTEM,),
        manifest_id=_F_MORTAR,
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.FIXABLE_MEASUREMENT_GAP,
        audit_note="PoB's damage is for one totem; ActiveTotemLimit/TotemsSummoned exist in PoB's output but ExileLens does not compose a total (no formula is invented, POB_NATIVE_DAMAGE_POLICY). +maximum totems is a plausible affix on totem builds. Whether PoB's FullDPS composes the count correctly is unverified. Medium effort; truthful refusal (TOTEM_LIMIT_CHANGED), not a blocker.",
    ),
    CoverageCase(
        id="BALLISTA-IDENTITY-AND-DPS-SEMANTICS",
        test_file=_F_FILE,
        node_name="test_ballista_group_is_calculated_through_its_artillery_effect",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "The saved main skill is another grenade; the Siege Ballista group's Artillery effect (selected by "
            "the test only) is a plain per-second skill for one ballista; the summoning effect deals no damage "
            "and carries the totem limit."
        ),
        archetypes=_F_TAGS,
        manifest_id=_F_BALLISTA,
    ),
    CoverageCase(
        id="BALLISTA-WEAPON-OFFENSE-VERDICTS",
        test_file=_F_FILE,
        node_name="test_ballista_weapon_offense_verdicts_match_fresh_loads",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Faster / slower crossbow: FULL upgrade / downgrade of the ballista's rate, fresh-load checked.",
        archetypes=_F_TAGS,
        manifest_id=_F_BALLISTA,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="BALLISTA-TOTEM-COUNT-CHANGE-IS-PARTIAL",
        test_file=_F_FILE,
        node_name="test_ballista_totem_count_change_is_not_claimed_as_measured",
        node_name_is_prefix=True,
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "A weapon that changes the maximum number of Ballista totems (4 -> 2 / 4 -> 6): PoB's Artillery "
            "damage does not move, so the change in total damage is not measured; PARTIAL / UNCERTAIN."
        ),
        archetypes=(Archetype.PROXY_TOTEM,),
        manifest_id=_F_BALLISTA,
        functional=FunctionalMeasurement.EXPECTED_UNCERTAINTY,
        audit=UncertaintyAudit.FIXABLE_MEASUREMENT_GAP,
        audit_note="Same as MORTAR-TOTEM-COUNT-CHANGE-IS-PARTIAL for Siege Ballista (PoB's Artillery damage does not move with the totem count).",
    ),
    CoverageCase(
        id="BALLISTA-DEFENCE-RING-MEASURED",
        test_file=_F_FILE,
        node_name="test_ballista_defence_ring_is_measured_without_inventing_offense",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="More life on the ring: FULL, the ballista's damage rate exactly unchanged.",
        archetypes=(Archetype.PROXY_TOTEM,),
        manifest_id=_F_BALLISTA,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="MORTAR-REPEATED-EVALUATION-RESTORE",
        test_file=_F_FILE,
        node_name="test_repeated_evaluations_are_identical_and_restore_the_build",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Interleaved evaluations are identical and the fingerprint and equipment return to baseline.",
        archetypes=(Archetype.PROXY_TOTEM,),
        manifest_id=_F_MORTAR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
)

# ---------------------------------------------------------------------------
# CORPUS-02G — authentic attribute-stacking builds (Strength; Dexterity/Intelligence). Every
# measured case is checked against an independent fresh PoB load with the candidate equipped.
# ---------------------------------------------------------------------------
_G_FILE = "tests/integration/test_corpus02g_attribute_stacking.py"
_G_STR = "CORPUS02G-STRENGTH-BRUTUS"
_G_DI = "CORPUS02G-DEX-INT-HAND-OF-WISDOM"
CORPUS_02G_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="STRENGTH-IDENTITY-AND-ATTRIBUTE-STACK",
        test_file=_G_FILE,
        node_name="test_strength_build_stacks_strength_through_the_weapons_and_uses_combined_dps",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Oracle with dual Brutus' Lead Sprinkler (Added Attack Fire Damage per 25 Strength) and about 1,900 Strength; PoB's Str and ReqStr outputs are visible; the scored field is CombinedDPS."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_STR,
    ),
    CoverageCase(
        id="STRENGTH-MORE-AND-LESS-STRENGTH",
        test_file=_G_FILE,
        node_name="test_more_and_less_strength_move_offense_and_defence_together",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "+40 / -40 flat Strength on the amulet: FULL upgrade / downgrade, offense and Energy Shield move together, fresh-load checked."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_STR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STRENGTH-THRESHOLD-STEP",
        test_file=_G_FILE,
        node_name="test_strength_scaling_has_thresholds_and_is_not_a_fixed_rate",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Three more Strength across a per-25 boundary is worth several times the neighbouring three; Item Check reports PoB's number on both sides (FULL)."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_STR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STRENGTH-PERCENT-INCREASED-BEATS-LARGER-FLAT",
        test_file=_G_FILE,
        node_name="test_percent_increased_strength_beats_a_larger_flat_bonus",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "An amulet with no flat Strength change but 70% increased Strength outscores one with +106 more flat Strength: FULL, fresh-load checked."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_STR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STRENGTH-DEFENCE-ONLY",
        test_file=_G_FILE,
        node_name="test_defence_only_amulet_leaves_the_strength_stack_untouched",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "More Energy Shield only: FULL upgrade, DEFENSE positive, Strength and damage exactly unchanged."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_STR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STRENGTH-OFFENSE-DEFENSE-TRADEOFF",
        test_file=_G_FILE,
        node_name="test_strength_gain_with_a_lost_resistance_cap_is_a_flagged_tradeoff",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "More Strength but the Cold Resistance cap is lost: FULL, TRADEOFF, RES_CAP_LOST, never an upgrade."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_STR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STRENGTH-REQUIREMENT-LOST",
        test_file=_G_FILE,
        node_name="test_dropping_below_an_equipped_requirement_is_not_viable",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Strength below the equipped items' requirement (PoB's ReqStr): NOT_VIABLE with ATTRIBUTE_REQUIREMENT_LOST. PoB still applies the unmet item, so only the guardrail catches it."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_STR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="STRENGTH-REPEATED-EVALUATION-RESTORE",
        test_file=_G_FILE,
        node_name="test_strength_build_repeated_evaluations_restore_the_build",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Interleaved evaluations are identical and the fingerprint and equipment return to baseline (FULL)."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_STR,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="DEX-INT-IDENTITY-AND-ATTRIBUTE-SCALING",
        test_file=_G_FILE,
        node_name="test_dex_int_build_scales_speed_and_added_damage_from_attributes",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Acolyte of Chayula with Astramentis and Hand of Wisdom and Action: attack speed per 20 Dexterity and added lightning damage per 20 Intelligence; PoB's attributes and requirements are visible."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_DI,
    ),
    CoverageCase(
        id="DEX-INT-MORE-AND-FEWER-ATTRIBUTES",
        test_file=_G_FILE,
        node_name="test_more_and_fewer_attributes_change_speed_and_damage",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "+60 / -120 all attributes on Astramentis: Speed and damage follow; FULL upgrade / downgrade, fresh-load checked."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_DI,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="DEX-INT-ES-DOES-NOT-PAY-FOR-LOST-ATTRIBUTES",
        test_file=_G_FILE,
        node_name="test_extra_energy_shield_does_not_pay_for_lost_attributes",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Fewer attributes but +150 Energy Shield: offense and effective HP both fall, FULL MEANINGFUL_DOWNGRADE, fresh-load checked."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_DI,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="DEX-INT-DEFENCE-ONLY",
        test_file=_G_FILE,
        node_name="test_dex_int_defence_only_amulet_leaves_offense_unchanged",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "More Energy Shield only: FULL, offense exactly unchanged."
        ),
        archetypes=(Archetype.ATTRIBUTE_STACKER,),
        manifest_id=_G_DI,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
)

# ---------------------------------------------------------------------------
# CORPUS-02H - authentic Eldritch Battery build: Energy Shield is converted to Mana, and Mana scales
# the main skill. Every measured case is checked against an independent fresh PoB load.
# ---------------------------------------------------------------------------
_H_FILE = "tests/integration/test_corpus02h_energy_shield_mana.py"
_H_ID = "CORPUS02H-ELDRITCH-BATTERY"
CORPUS_02H_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="ES-MANA-IDENTITY-AND-CONVERSION",
        test_file=_H_FILE,
        node_name="test_energy_shield_is_converted_to_mana_and_mana_scales_the_main_skill",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Eldritch Battery converts all Energy Shield to maximum Mana (PoB Energy Shield 0, Mana above 10,000) and Rathpith Globe scales Spark with maximum Mana; the scored field is TotalDPS."
        ),
        archetypes=(Archetype.ES_SCALING, Archetype.MANA_SCALING),
        manifest_id=_H_ID,
    ),
    CoverageCase(
        id="ES-MANA-MORE-ES-RAISES-MANA-DAMAGE-EHP",
        test_file=_H_FILE,
        node_name="test_more_energy_shield_raises_mana_damage_and_effective_hp",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "+200 flat Energy Shield on the helmet: Mana, damage and effective HP rise while the Energy Shield output stays 0; FULL MEANINGFUL_UPGRADE, fresh-load checked."
        ),
        archetypes=(Archetype.ES_SCALING, Archetype.MANA_SCALING),
        manifest_id=_H_ID,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="ES-MANA-LESS-ES-LOWERS-MANA-DAMAGE-EHP",
        test_file=_H_FILE,
        node_name="test_less_energy_shield_lowers_mana_damage_and_effective_hp",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "-70 flat Energy Shield: Mana, damage and effective HP fall; FULL MEANINGFUL_DOWNGRADE, fresh-load checked."
        ),
        archetypes=(Archetype.ES_SCALING, Archetype.MANA_SCALING),
        manifest_id=_H_ID,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="ES-MANA-PERCENT-INCREASED-ES",
        test_file=_H_FILE,
        node_name="test_percent_increased_energy_shield_on_the_armour_reaches_the_mana_pool",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "100% more increased Energy Shield on the helmet raises Mana and damage: FULL upgrade, fresh-load checked."
        ),
        archetypes=(Archetype.ES_SCALING, Archetype.MANA_SCALING),
        manifest_id=_H_ID,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="ES-MANA-SLOT-DEPENDENT-VALUE",
        test_file=_H_FILE,
        node_name="test_the_same_flat_energy_shield_is_worth_more_on_the_helmet_than_the_amulet",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "The same +200 flat Energy Shield adds over three times as much Mana on the helmet (enchant and increased Energy Shield) as on the amulet; both FULL, the helmet scores higher."
        ),
        archetypes=(Archetype.ES_SCALING, Archetype.MANA_SCALING),
        manifest_id=_H_ID,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="ES-MANA-DIRECT-MANA-INDEPENDENT-EFFECT",
        test_file=_H_FILE,
        node_name="test_direct_mana_and_converted_energy_shield_are_measured_alike",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Flat maximum Mana (no conversion) is measured like converted Energy Shield: Energy Shield stays 0, Mana and damage rise; FULL upgrade."
        ),
        archetypes=(Archetype.ES_SCALING, Archetype.MANA_SCALING),
        manifest_id=_H_ID,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="ES-MANA-ES-GAIN-WITH-LOST-RESISTANCE-CAP",
        test_file=_H_FILE,
        node_name="test_energy_shield_gain_that_costs_a_resistance_cap_is_a_flagged_tradeoff",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "More Energy Shield but the Chaos Resistance cap is lost: FULL, RES_CAP_LOST, never an upgrade."
        ),
        archetypes=(Archetype.ES_SCALING,),
        manifest_id=_H_ID,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="ES-MANA-ES-SWAPPED-FOR-LIFE",
        test_file=_H_FILE,
        node_name="test_swapping_energy_shield_for_life_costs_damage_and_effective_hp",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Life instead of increased Energy Shield: measured damage and effective HP both fall (FULL), verdict is not an upgrade."
        ),
        archetypes=(Archetype.ES_SCALING,),
        manifest_id=_H_ID,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="ES-MANA-REPEATED-EVALUATION-RESTORE",
        test_file=_H_FILE,
        node_name="test_repeated_evaluations_are_identical_and_restore_the_build",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Interleaved evaluations are identical and the fingerprint and equipment return to baseline (FULL)."
        ),
        archetypes=(Archetype.ES_SCALING,),
        manifest_id=_H_ID,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
)

# ---------------------------------------------------------------------------
# R4 1.0 reliability gate: evidence the audit found missing or never wired into the report.
#   * identity cases for the two fixtures added by LIFE-01 / RECOVERY-02A (RECOVERY-02A was not even in the manifest);
#   * the recovery verdict case, the jewel evidence (test_jewel_*.py was never part of the report), the all-slots sweep and
#     the stat-stacker case. Each points at exactly one test; nothing here duplicates an existing layer.
# ---------------------------------------------------------------------------
_R4_FILE = "tests/integration/test_r4_reliability_gate.py"
_JEWEL_FILE = "tests/integration/test_jewel_real_pob.py"
_JEWEL_RESTORE_FILE = "tests/integration/test_jewel_restore_remediation.py"
_JEWEL_FIXTURE = "CORE04-MELEE-WEAPON"

R4_CASES: tuple[CoverageCase, ...] = (
    CoverageCase(
        id="LIFE01-BLOOD-MAGE-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[LIFE01-BLOOD-MAGE-GORE-SPIKE]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description="Witch/Blood Mage, Ember Fusillade, PLAYER actor (authentic pobb.in export).",
        archetypes=(Archetype.SPELL, Archetype.LIFE_SCALING),
        manifest_id="LIFE01-BLOOD-MAGE-GORE-SPIKE",
    ),
    CoverageCase(
        id="RECOVERY02A-ES-REGEN-INVOKER-IDENTITY",
        test_file="tests/integration/test_public_build_corpus.py",
        node_name="test_public_corpus_loads_with_expected_primary_actor[RECOVERY02A-ES-REGEN-INVOKER]",
        depth=EvaluationDepth.IDENTITY_ONLY,
        expected=ExpectedResult.CONFIDENT,
        description="Monk/Invoker, Spark, PLAYER actor (authentic pobb.in export); Energy Shield recovery build.",
        archetypes=(Archetype.SPELL, Archetype.ES_SCALING),
        manifest_id="RECOVERY02A-ES-REGEN-INVOKER",
    ),
    CoverageCase(
        id="RECOVERY02A-ES-REGEN-BOOTS-MEASURED",
        test_file="tests/integration/test_recovery02a_es_regen.py",
        node_name="test_authentic_invoker_boots_gain_real_es_regeneration_and_restore",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Boots gaining Energy Shield regeneration on an ES build: PoB's EnergyShieldRegenRecovery moves from zero, the "
            "RECOVERY axis reports it against the ES pool as a distinct channel from Life regeneration (FULL), and the build restores."
        ),
        archetypes=(Archetype.ES_SCALING,),
        manifest_id="RECOVERY02A-ES-REGEN-INVOKER",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="GEAR-SLOTS-MEASURED-IN-OWN-SLOT-AND-RESTORED",
        test_file=_R4_FILE,
        node_name="test_every_gear_slot_is_measured_in_its_own_slot_and_restored",
        node_name_is_prefix=True,
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Helmet, Body Armour, Gloves, Boots, Belt, Amulet and both Rings on one real build: each candidate resolves to its "
            "own slot, is applied, is measured FULL with a defence gain, and restores. Belt had no real-PoB verdict test before R4."
        ),
        archetypes=(Archetype.MELEE,),
        manifest_id=_JEWEL_FIXTURE,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="JEWEL-OCCUPIED-SOCKET-REPLACEMENT",
        test_file=_JEWEL_FILE,
        node_name="test_occupied_socket_replacement_measurable_and_restored",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A rare Ruby against a build with five allocated, occupied sockets (Timeless Jewel, two unique Diamonds, two rare "
            "Rubies): every socket is evaluated against its own equipped jewel, FULL, and restores."
        ),
        manifest_id=_JEWEL_FIXTURE,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="JEWEL-MULTI-SOCKET-RANKING-SELECTS-BEST-PLACEMENT",
        test_file=_JEWEL_FILE,
        node_name="test_multi_socket_ranking_reflects_best_valid_placement_not_first_socket",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Deterministic target-socket selection: with materially different verdicts across sockets the recommendation is the "
            "score-driven best placement, not the first socket (FULL)."
        ),
        manifest_id=_JEWEL_FIXTURE,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="JEWEL-MULTI-AXIS-TRADEOFF-REPORTED",
        test_file=_JEWEL_FILE,
        node_name="test_multi_axis_tradeoff_is_reported_not_hidden",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Replacing a Timeless Jewel is a PoB-measured offense/defense TRADEOFF, reported as such (FULL).",
        manifest_id=_JEWEL_FIXTURE,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="JEWEL-REPEATED-EVALUATION-RESTORE",
        test_file=_JEWEL_FILE,
        node_name="test_repeated_evaluation_is_stable_and_restores_cleanly",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two identical jewel evaluations give identical socket sets and verdicts, FULL, with a passing restore each time.",
        manifest_id=_JEWEL_FIXTURE,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="JEWEL-EMPTY-ALLOCATED-SOCKET-COMPARED-AGAINST-NO-JEWEL",
        test_file=_JEWEL_FILE,
        node_name="test_empty_allocated_socket_is_compared_against_no_jewel",
        node_name_is_prefix=True,
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "An allocated but empty jewel socket (derived from the public fixture by unslotting one jewel, in both forms PoB "
            "writes it) is discovered, compared against no jewel (FULL, replacing_empty_slot), leaves every other socket's "
            "baseline untouched, and leaks nothing. Replaces the old skip, which rested on a code-path argument."
        ),
        manifest_id=_JEWEL_FIXTURE,
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
    CoverageCase(
        id="JEWEL-UNALLOCATED-SOCKETS-NEVER-EVALUATED",
        test_file=_JEWEL_FILE,
        node_name="test_unallocated_jewel_socket_ranking_only_sees_legal_candidates",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Wrong-socket safety: a build whose passive tree contains 19 socket nodes but allocates 4 is evaluated on exactly the "
            "4, each against its own equipped jewel; an unallocated socket can never be selected."
        ),
        manifest_id="CORE04-SKILL-NATIVE-DOT",
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="JEWEL-CONNECTIVITY-JEWEL-RESTORE",
        test_file=_JEWEL_RESTORE_FILE,
        node_name="test_previously_failing_fixtures_now_restore_correctly",
        node_name_is_prefix=True,
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Three builds carrying a connectivity-affecting jewel (From Nothing / Split Personality class) evaluate every "
            "evaluable socket with a passing restore; none delivers RESTORE_FAILED."
        ),
        role=CaseRole.STATE_INTEGRITY,
    ),
    CoverageCase(
        id="JEWEL-ALTERNATE-START-SOCKET-EXCLUDED",
        test_file=_JEWEL_RESTORE_FILE,
        node_name="test_stage_context_split_personality_socket_is_excluded",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNSUPPORTED,
        description=(
            "A socket holding a Split Personality-class jewel (alternateClassStart) is left out of the evaluation and counted in "
            "the diagnostics instead of risking a wrong delivered Life value."
        ),
        manifest_id="CORE04-STAGE-CONTEXT",
        role=CaseRole.STATE_INTEGRITY,
        audit=UncertaintyAudit.CORRECT_UNCERTAINTY,
        audit_note=(
            "Restoring that socket leaves a ~2.5% secondary-metric (Life) discrepancy that was not explained, so the socket is excluded "
            "rather than risk a wrong delivered value. Rare (jewel-specific); the socket count is reported in the diagnostics, the "
            "user-facing copy does not yet name skipped sockets (P2)."
        ),
    ),
    CoverageCase(
        id="STAT-STACKER-BLOCK-CHANCE-DAMAGE-CONVERSION",
        test_file="tests/integration/test_corpus02_giants_blood_shield.py",
        node_name="test_block_chance_stacking_is_measured_through_the_damage_conversion",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "Chernobog's Pillar converts Chance to Block into Fire damage, so the build stacks a stat that is neither an attribute nor a "
            "pool. Less Block lowers damage and EHP (FULL downgrade on both axes, equal to an independent PoB load); more Block at the cap "
            "is a SIDEGRADE. One stacker flavour on one build; no Armour/Evasion/Rage/charge stacker is in the corpus."
        ),
        archetypes=(Archetype.STAT_STACKER, Archetype.MELEE),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
        functional=FunctionalMeasurement.FULLY_MEASURED,
    ),
)

ALL_CASES: tuple[CoverageCase, ...] = (
    BUILD_CORPUS_IDENTITY_CASES
    + REAL_POB_VERDICT_CASES
    + SLICE_3_4D_REAL_POB_CASES
    + CORPUS_02A_REAL_POB_CASES
    + CORPUS_02B_REAL_POB_CASES
    + CORPUS_02C_REAL_POB_CASES
    + CORPUS_02D1_CASES
    + CORPUS_02D2_CASES
    + MAIN_SKILL_01_CASES
    + CORPUS_02E_CASES
    + CORPUS_02F_CASES
    + CORPUS_02G_CASES
    + CORPUS_02H_CASES
    + R4_CASES
    + POLICY_UNIT_CASES
)
