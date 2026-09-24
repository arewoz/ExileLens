# Community Regression Matrix (CR-01)

Branch: `feat/weapon-set-component-contexts`. Consolidates existing real-build
regression coverage for community-reported primary-offense scenarios. No
production evaluation logic was changed for this matrix.

Status vocabulary (CR-01): `COVERED`, `PARTIAL`, `MISSING_FIXTURE`,
`MISSING_TEST`, `UNSUPPORTED`.

A scenario is `COVERED` only when an executed test (real-PoB or deterministic
worker-shaped) asserts the behavior below. Code inspection alone never counts.
"Correctly measured" (directional verdict), "correctly rejected" (explicit
refusal), and "correctly uncertain" (PARTIAL/UNCERTAIN) are kept separate: a
passing test is not proof that a whole mechanic is supported.

## Matrix

| # | Scenario | Fixture | Regression test | Expected | Actual (verified) | Status | Missing evidence / next step |
|---|----------|---------|-----------------|----------|-------------------|--------|------------------------------|
| 1 | Weapon-set switching and cross-context measurements | `core04_weapon_swap.xml` | `test_weapon_set_component_contexts.py` (8 tests: cross-set read/restore, repeated-switch determinism, sibling isolation, set-2/set-1 physical isolation, failure close/restore, corrupt-restore fail-closed, ordinary-check RPC silence) + `test_contextual_diagnostic_real_pob.py::test_both_weapon_set_catalogs_enumerate_with_restore` | Same reference reads under both sets with disjoint cache identities; deterministic per-set output; exact fingerprint/equipment/context restore | Verified on HEAD (PO-01 §8; CR-01 §Validation) | COVERED | None. Now tracked in the generated coverage report (13 `WSCTX`/`CTXDIAG` cases). |
| 2 | Incompatible weapon placement (cross-base disturbance) | `core04_weapon_swap.xml` | `test_contextual_incompatible_placement_real_pob.py` (3 tests) | Cross-base placement aborts to `UNAVAILABLE`/`NOT_VALID_IN_CONTEXT` naming `disturbed_slots`, exact restore, worker stays healthy; same-base placements still measure | Verified on HEAD (FIX-02 gate) | COVERED | None. Now tracked as 3 `XBASE` cases. |
| 3 | Near-zero primary DPS with other relevant offensive effects | None (deterministic worker-shaped values from the Combat Frenzy tester report: Bow Shot UNAVAILABLE, Herald of Ice IgniteDPS 1.3e-6, Snipe real loss) | `test_offense_fallback_truthfulness.py` (20 tests: significance gate, fallback selection incl. PoB-group-order tiebreak, truthfulness propagation, end-to-end pipeline) | Noise-sized component never selected, never manufactures ±100%; substituted fallback caps quality at PARTIAL / verdict at UNCERTAIN | Verified on HEAD (PO-01 §8) | COVERED | Real-build fixture with a naturally near-zero primary never checked in; deterministic values are the exact reported numbers, so no further testing required. |
| 4 | Incorrect primary skill or stat-set selection | All 9 public_corpus fixtures | Verdict tests asserting `pob_field`/`selected`/`semantic_quantity`/`ailment` (poison, mixed, skill-native-DoT, new stage-context ignite); corpus identity tests; stat-set keys asserted (`Poison Burst`, `FlameblastPlayer:sole-set`); per-fixture identity dump re-verified on HEAD (CR-01 §Validation) | Resolver picks the skill's own field; wrong-field selection would understate offense or fabricate it | Verified on HEAD | COVERED | None. |
| 5 | Multi-part skills (e.g. Vaal/Normal parts, `part_count > 1`) | None | None | Guarded comparison (`part_key` change → UNMEASURED) if ever encountered | Engine dump on HEAD: all 9 fixtures resolve to their skill's single whole part (`part_key = <Skill>:whole`, `part_count = 0`) | MISSING_FIXTURE | A real build whose main skill exposes multiple PoB parts. Do not synthesize one. |
| 6 | Multi-stage skills | `core04_stage_context.xml` (single-stage: `stage_count = 1`, `CHANNEL_RELEASE`) | Identity (`MINION-STAGE-IDENTITY-RETAINED`) + new `test_stage_context_channel_release_ignite_offense_is_measured_truthfully` (verdict depth) | Stage identity retained; ignite-dominant offense measured truthfully (PARTIAL/UNCERTAIN) | Verified on HEAD | PARTIAL | Explicit multi-stage (`stage_count > 1`) fixture: MISSING_FIXTURE. Single-stage channel-release is now fully covered. |
| 7 | Poison references (ailment-dominant) | `core04_poison_ailment.xml` | `test_poison_ailment_dominant_offense_is_selected_and_measured` (+ repeat-no-leak) | `PoisonDPS`/`AILMENT_DPS` selected; real +40%-class gain measured; PARTIAL/UNCERTAIN (truthful caution, never directional) | Verified on HEAD | COVERED | None. Correctly-uncertain, not correctly-measured -- kept separate by design. |
| 8 | Ignite references | `core04_stage_context.xml` (ignite-dominant) + `core04_mixed_hit_ailment.xml` (ignite-as-component) | New stage-context ignite verdict test + `test_mixed_hit_and_ailment_offense_selects_combined_dps` (CombinedDPS == TotalDPS + IgniteDPS exactly, FULL/MEANINGFUL_UPGRADE) | Ignite-dominant → measured + PARTIAL/UNCERTAIN; ignite-as-component → combined + FULL | Verified on HEAD | COVERED | Pure ignite-dominant coverage is new in CR-01 (was PARTIAL). Isolated `IgniteDPS`-only builds beyond Flameblast: no fixture, not required. |
| 9 | Sibling effect identities | `core04_weapon_swap.xml` (EscapeShot pair), `core04_melee_weapon.xml` (InfernalCry pair) | `test_effect_level_enumeration.py` (5 real-PoB tests) + `test_effect_level_identity.py` (7 unit tests) + `WSCTX-SIBLING-ISOLATION` | Siblings share one group, never share semantic/cache/context identity; reads never cross-contaminate; malformed rows fail closed | Verified on HEAD | COVERED | None. Now tracked as 5 `EFFENUM` cases. |
| 10 | Ambiguous offensive component selection | `core04_onehand_weapon.xml` (dual-slot mace), `core04_weapon_swap.xml` (wrong-set sentinel), deterministic fallback ordering | `test_onehand_weapon_candidate_is_ambiguous_and_resolved_safely` (NOT_VIABLE guardrail, best-slot never surfaces blocked slot), `test_weapon_swap_baseline_reflects_the_active_second_set` (sentinel), P0 group-order tiebreak unit test | Every legal slot evaluated under one policy; guardrail-blocked slots never win; fallback prefers group order, never biggest DPS | Verified on HEAD | COVERED | None. No highest-DPS auto-selection anywhere on this path. |
| 11 | Unsupported / partially supported mechanics | `core04_player_ring.xml` (two-hand vs offhand), poison/stage (ailment caution), jewel alternate-start socket | `test_offhand_candidate_against_two_hand_weapon_fails_truthfully` (`SlotResolutionFailed`), ailment PARTIAL/UNCERTAIN verdicts, jewel-socket exclusion + remediation suites | Explicit refusal or explicit uncertainty; never a confident verdict on unmodeled axes | Verified on HEAD | COVERED | None. |
| 12 | Reported Voltaic Barrier weapon-swap interaction (`pobb.in/1PuQGhYCY9Fv`) | None | None (`EXACT_COMMUNITY_FIXTURE_MISSING` in `test_contextual_diagnostic_real_pob.py`) | Unknown until the exact build is available | Not verifiable: repo-wide search finds only an unrelated equipped "Voltaic Staff" in `core04_player_ring.xml` and an unrelated "Virtuous Barrier" ascendancy gem in `core04_stage_context.xml` | MISSING_FIXTURE | The exact exported PoB build fixture. Do not substitute another build and do not download external builds in CR-01. The generic weapon-swap machinery covering this shape (scenarios 1-2) is COVERED. |

## Coverage distinction summary

- Correctly measured (directional verdicts): hit, mixed hit+ailment, skill-native DoT, melee/bow/ring replacements, same-base cross-set placements.
- Correctly rejected (explicit refusal): cross-base disturbed placements (`UNAVAILABLE`/`NOT_VALID_IN_CONTEXT`), offhand-vs-two-hand (`SlotResolutionFailed`), flask/jewel-alternate-start (unsupported).
- Correctly uncertain (`PARTIAL`/`UNCERTAIN`, never directional): poison-dominant, ignite-dominant, substituted fallback components, reduced-evidence comparisons.
- Without representative real-build tests: multi-part skills, multi-stage (`stage_count > 1`) skills, the exact Voltaic Barrier community build.

## Reporting changes (CR-01)

- `tests/corpus_coverage/registry.py`: new `SLICE_3_4D_REAL_POB_CASES` (18 cases: 8 `WSCTX`, 3 `XBASE`, 2 `CTXDIAG`, 5 `EFFENUM`) plus `STAGE-CHANNEL-RELEASE-IGNITE-VERDICT` in the strategic verdict suite. All point at existing or CR-01-added tests only.
- `scripts/generate_corpus_coverage_report.py`: `SUITES` extended with the four Slice 3-4D real-PoB files (same `real_pob` marker, no new framework).
- `tests/corpus_coverage/report.py`: one-word reporting fix (`4` → `9` build fixtures in the generated header; the manifest has held 9 fixtures since M1.1).
- Regenerated `docs/corpus_coverage/COVERAGE_REPORT.md` + `coverage_report.json`.
- `docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md`: unchanged (hand-maintained policy matrix; still accurate).
