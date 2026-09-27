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
    ),
    CoverageCase(
        id="OFFHAND-CANDIDATE-AGAINST-TWO-HAND-WEAPON-FAILS-TRUTHFULLY",
        test_file="tests/integration/test_public_real_pob.py",
        node_name="test_offhand_candidate_against_two_hand_weapon_fails_truthfully",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description=(
            "M1.2 offhand slice, invalid-combination case: a real Focus candidate against a "
            "build whose active weapon is a two-handed staff (empty offhand) resolves zero "
            "compatible slots via PoB's own IsItemValidForSlot and is correctly refused with "
            "SlotResolutionFailed/UNSUPPORTED_EQUIPMENT_LAYOUT -- never a confident, silently "
            "wrong-slot comparison. A clean, unrelated evaluation immediately afterward proves "
            "the failed resolution left no residual build-state mutation."
        ),
        archetypes=(Archetype.SPELL,),
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
            "isolated-ailment-dominant case. M1.2 offhand-support note: the candidate itself is "
            "this build's own equipped Focus (item.type == 'Focus', logical/physical Weapon 2) "
            "-- this is the corpus's real-PoB evidence for Focus offhand support, promoted from "
            "already-proven behavior rather than re-implemented or re-fixtured."
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
            "active_item_set_id/loadout/skill identity, and its baseline equipment/offense are "
            "proven (via an explicit wrong-set sentinel) to be computed from the active second "
            "weapon set, not the inactive primary set. The sentinel candidate replaces logical "
            "Weapon 1 with the INACTIVE primary weapon and is correctly, truthfully refused as "
            "NOT_VIABLE (an arrow skill without a bow), not silently no-op'd."
        ),
        archetypes=(Archetype.WEAPON_SWAP,),
        manifest_id="CORE04-WEAPON-SWAP",
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
            "classification, never a confident directional verdict."
        ),
        archetypes=(Archetype.SPELL, Archetype.AILMENT, Archetype.DOT, Archetype.UNUSUAL_SKILL_PART),
        manifest_id="CORE04-STAGE-CONTEXT",
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
    ),
    CoverageCase(
        id="EFFENUM-SIBLING-COMPONENTS",
        test_file="tests/integration/test_effect_level_enumeration.py",
        node_name="test_additional_granted_effects_are_distinct_cache_backed_components",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Sibling granted effects (EscapeShot/IceFragment, InfernalCry/CorpseExplosion) share one group but carry distinct semantic and cache identities, all GlobalCache-backed and measured.",
        archetypes=(Archetype.WEAPON_SWAP, Archetype.MELEE),
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
    ),
    CoverageCase(
        id="EFFENUM-BOUND-AND-ORDINARY-CHECK",
        test_file="tests/integration/test_effect_level_enumeration.py",
        node_name="test_effect_bound_and_ordinary_item_check_behavior",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Cross-cutting bound: the effect catalog is capped at 8 with explicit truncation, and ordinary ring Item Check keeps its FULL/MEANINGFUL_UPGRADE result.",
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
        archetypes=(Archetype.MELEE, Archetype.UNIQUE_INTERACTION),
        manifest_id="CORPUS02-GIANTS-BLOOD-SHIELD",
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
    ),
    CoverageCase(
        id="STONEFIST-ROLL-DEPENDENT-DETERMINISTIC-RESTORE",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_roll_dependent_evaluation_is_deterministic_and_restores",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="Repeated roll-dependent evaluations are identical and fingerprint/equipment return to baseline.",
        manifest_id="CORPUS02C-STONEFIST",
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
    ),
    CoverageCase(
        id="STONEFIST-CHARACTER-LEVEL",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_transformed_defences_follow_the_character_level",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="At character level 70 the transformed per-level defences match a level-70 reference load.",
        manifest_id="CORPUS02C-STONEFIST",
    ),
    CoverageCase(
        id="STONEFIST-UNRESOLVABLE-GLOVES-UNSUPPORTED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_unresolvable_gloves_stay_unsupported_with_the_precise_reason",
        node_name_is_prefix=True,
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.UNSUPPORTED,
        description=(
            "Remaining gaps, not coverage: unique gloves (game HandWrapsUnique* mods are absent from PoB's "
            "data) and gloves whose lines match no glove-modifier combination stay UNSUPPORTED with the reason."
        ),
        manifest_id="CORPUS02C-STONEFIST",
    ),
    CoverageCase(
        id="STONEFIST-NON-GLOVE-CANDIDATES-STAY-MEASURED",
        test_file="tests/integration/test_corpus02c_stonefist.py",
        node_name="test_non_glove_candidates_on_a_stonefist_build_stay_measured",
        depth=EvaluationDepth.VERDICT,
        expected=ExpectedResult.CONFIDENT,
        description="The transformation is scoped to gloves: an amulet candidate stays FULL and matches PoB.",
        manifest_id="CORPUS02C-STONEFIST",
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
    ),
    CoverageCase(
        id="STONEFIST-NON-MONOTONE-REFUSED",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_non_monotone_pob_results_are_refused_even_when_verdicts_match",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C: matching verdicts are not proof when PoB outputs are not ordered across the rolls.",
    ),
    CoverageCase(
        id="STONEFIST-ALTERNATIVES-MUST-AGREE",
        test_file="tests/test_stonefist_transform.py",
        node_name="test_every_decomposition_alternative_must_agree",
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C: when displayed lines fit several modifier combinations, all resulting items must share one verdict.",
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
    ),
    CoverageCase(
        id="ITEM-TRANSFORM-FLAGGED-IS-UNSUPPORTED",
        test_file="tests/test_item_transform_guard.py",
        node_name="test_flagged_comparison_is_unsupported_quality",
        node_name_is_prefix=True,
        depth=EvaluationDepth.POLICY_UNIT,
        expected=ExpectedResult.UNSUPPORTED,
        description="CORPUS-02C: a flagged comparison is EvaluationQuality.UNSUPPORTED with reason ITEM_TRANSFORM_UNMODELED.",
    ),
)

ALL_CASES: tuple[CoverageCase, ...] = (
    BUILD_CORPUS_IDENTITY_CASES
    + REAL_POB_VERDICT_CASES
    + SLICE_3_4D_REAL_POB_CASES
    + CORPUS_02A_REAL_POB_CASES
    + CORPUS_02B_REAL_POB_CASES
    + CORPUS_02C_REAL_POB_CASES
    + POLICY_UNIT_CASES
)
