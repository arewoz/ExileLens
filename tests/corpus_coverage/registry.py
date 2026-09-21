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

from tests.corpus_coverage.taxonomy import Archetype, EvaluationDepth, ExpectedResult


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
        archetypes=(Archetype.SPELL, Archetype.CRIT, Archetype.LIFE_SCALING),
    ),
    CoverageCase(
        id="RING-TRADEOFF-BEST-SLOT",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_ring_tradeoff_and_best_slot_remain_semantic",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two-ring transaction, TRADEOFF impact pattern classified as SIDEGRADE, stable best-slot pick.",
        archetypes=(Archetype.SPELL,),
    ),
    CoverageCase(
        id="RING-EMPTY-SLOT",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_empty_ring_slot_is_explicitly_compared_not_inferred_as_missing",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Empty slot is compared explicitly, not inferred/guessed from a missing baseline.",
        archetypes=(Archetype.SPELL,),
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
    ),
    CoverageCase(
        id="ONE-BATCHED-TRANSACTION",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_one_item_check_uses_one_batched_candidate_evaluation",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="One Item Check issues exactly one batched PoB transaction across all compatible slots (perf invariant, not archetype-specific).",
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
    ),
    CoverageCase(
        id="POISON-AILMENT-OFFENSE-SELECTED-AND-MEASURED",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_poison_ailment_dominant_offense_is_selected_and_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNCERTAIN,
        description=(
            "A real poison-dominant build (PoisonDPS ~89% of CombinedDPS) correctly selects "
            "PoisonDPS/AILMENT_DPS/DOT_DPS as primary offense (not hit DPS or CombinedDPS), "
            "correctly measures a real +54%-class offense increase from a physical-damage "
            "candidate, and still reports PARTIAL quality / UNCERTAIN verdict -- a truthful, "
            "cautious classification is the correct, safe outcome for this ailment mechanic "
            "today, not a confident directional verdict."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
    ),
    CoverageCase(
        id="POISON-AILMENT-REPEATED-EVALUATION-NO-LEAK",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_poison_ailment_repeated_evaluation_does_not_leak_state",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Two consecutive Item Checks against the same poison-ailment candidate select the same PoB field and produce identical score/verdict, both restoring cleanly.",
        archetypes=(Archetype.AILMENT, Archetype.DOT),
        manifest_id="CORE04-POISON-AILMENT",
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
            "isolated-ailment-dominant case."
        ),
        archetypes=(Archetype.AILMENT, Archetype.DOT, Archetype.TRIGGER),
        manifest_id="CORE04-MIXED-HIT-AILMENT",
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
    ),
    CoverageCase(
        id="WEAPON-SWAP-BASELINE-REFLECTS-ACTIVE-SET",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_weapon_swap_baseline_reflects_the_active_second_set",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "A build whose active item set has useSecondWeaponSet=true correctly resolves "
            "active_item_set_id/loadout/skill identity, and its baseline offense is proven (via "
            "an explicit wrong-set sentinel: a massive damage buff on the INACTIVE primary "
            "weapon produces exactly zero measured change) to be computed from the active "
            "second weapon set, not the inactive primary set. NOTE: this covers only baseline "
            "correctness -- the separate, CONFIRMED defect in candidate substitution for this "
            "same build (candidates never reach the active slot at all) is deliberately NOT "
            "registered as a coverage case; see docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md risk "
            "register and the xfail(strict=True) regression "
            "test_weapon_swap_candidate_substitution_ignores_the_active_slot."
        ),
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
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
    ),
)

ALL_CASES: tuple[CoverageCase, ...] = BUILD_CORPUS_IDENTITY_CASES + REAL_POB_VERDICT_CASES + POLICY_UNIT_CASES
