# CORPUS-02A — Real-world regression and build coverage

Branch `test/corpus-02a-real-build-regression`, based on `origin/main` at `bf413d6`
(v0.5.0b1 plus the Patreon docs commit). No production code was changed.

## 1. Original problem

A Reddit tester reported that ExileLens failed while processing their public poe.ninja
PoE2 character, with an error involving `get_tree_snapshot`. The maintainer supplied a
sanitized PoB2 XML export of that character. This investigation used only that export.
The character's current online state and the league slug in its URL were not used.

The build is a Mercenary / Gemling Legionnaire (level 92). Its main skill is Supercharged
Slam (socket group 10, PLAYER-owned, `CHANNEL_RELEASE`, `stage_count = 1`, 2 stat sets,
"Impact" selected). The mechanics that matter for Item Check are:

- The **Giant's Blood** keystone. The active set holds a two-hand mace (Tawhoan Greatclub)
  in Weapon 1 **and** a tower shield in Weapon 2.
- The shield is **Chernobog's Pillar**: "Gain 1% of damage as Fire damage per 1% Chance
  to Block". At 50% block this fire is also what lets the build ignite. PoB reports
  CombinedDPS 284,292 = TotalDPS 278,487 + IgniteDPS 5,805.
- There is an inactive swap set with a talisman (Hysseg's Claw) and an empty Weapon 2
  Swap. `useSecondWeaponSet` is false.
- Three tree jewels are socketed (Megalomaniac, Heart of the Well, a rare Ruby).
- Other elements are present but not the primary skill: minion skills (Pounce, Cackling
  Companions), warcries, and Thorns.

## 2. Reproduction

| Environment | Result |
| --- | --- |
| Current HEAD, default engine path (`load_build` → `get_tree_snapshot`) | OK: 4,544 nodes, 126 allocated |
| Current HEAD, controller `run_baseline_reload` → Item Check, worker child forced to cp1251 | OK |
| **v0.3.0b1** (`4977309`), same controller helper `load_tree_snapshot`, worker child in cp1251 | **FAILS**: `WorkerUnhealthy: PoB worker process ended unexpectedly during 'get_tree_snapshot'`, stderr `'charmap' codec can't encode character '\xf3' in position 534346` |
| Pre-fix worker emulation, cp932 | FAILS the same way (`'cp932' codec can't encode character '\xf3'`) |
| Pre-fix worker emulation, cp1252 / cp1250 | No crash, but the parent decodes the name as `The M�rrigan's Guidance` (silent corruption) |

## 3. Confirmed root cause (already fixed)

`get_tree_snapshot` returns the whole passive tree. Its response is the first one in the
load sequence that carries non-ASCII text: the tree 0_5 passive "The Mórrigan's Guidance"
(node 27773, valid UTF-8 in PoB's `TreeData/0_5/tree.lua`). Before v0.4.0b1 the worker
subprocess wrote protocol responses to `sys.stdout` in the Windows ANSI code page. On a
locale whose code page cannot encode `ó` (Cyrillic cp1251, Japanese cp932, and others)
`sys.stdout.write` raised `UnicodeEncodeError` outside the request try-block, so the worker
died mid-response. `load_build` had already succeeded, so the failure always surfaced at
`get_tree_snapshot`.

The tree-snapshot code itself (`collect_tree_snapshot` and its helpers in
`runtime/lua/bridge.lua`) is byte-identical from v0.2.0b2 to HEAD and is not at fault.

The fix is already on `main`. It shipped in v0.4.0b1 as "Fix PoB worker Unicode stdio
encoding" (`369478b`, PR #27): `-X utf8` / `PYTHONUTF8=1` for the child, plus
`_configure_std_streams_utf8()`. That second part matters because `PYTHONIOENCODING`
overrides UTF-8 mode. The existing unit test `tests/test_worker_unicode_stdio.py` covers
the stream mechanism but not the real-PoB path. **No new fix was made.**

## 4. Tests added

`tests/integration/test_corpus02_giants_blood_shield.py` (markers `integration`, `real_pob`,
`itemcheck`) adds 6 tests. Numeric expectations are checked against an **independent cold
PoB load** of an edited copy of the build (`_fresh_metrics`). They never come from
ExileLens scoring output.

| Test | What it proves | Expected / result |
| --- | --- | --- |
| `test_tree_snapshot_survives_non_utf8_worker_code_page` | **Regression for the report.** Runs the real `_EvaluationWorker` baseline reload with the child in cp1251. The tree graph returns with node 27773 byte-exact, no U+FFFD, and Giant's Blood allocated. A following Item Check completes, its deferred restore is finalized, and the fingerprint is back at baseline. With `_configure_std_streams_utf8()` disabled locally, it fails with the exact reported error. | CONFIDENT / PASS |
| `test_giants_blood_baseline_identity_and_active_weapon_set` | Class, ascendancy, skill, `PLAYER`, `CHANNEL_RELEASE`. Weapon 1 is the two-hand mace and Weapon 2 the shield, both on the physical primary set, with the swap talisman inactive. CombinedDPS = TotalDPS + IgniteDPS. | identity-only / PASS |
| `test_giants_blood_two_hand_candidate_keeps_shield_and_matches_pob` | A two-hand mace candidate goes to Weapon 1 and the **shield is kept** (`paired_offhand_cleared` false). Result is FULL, offense POSITIVE, defense NEUTRAL, directional upgrade, and candidate CombinedDPS equals the cold PoB load. PoB's alternative off-hand placement of the same mace removes the shield and the ignite, and stays PARTIAL/UNCERTAIN. The recommendation is Weapon 1. | CONFIDENT / PASS |
| `test_chernobog_shield_loss_is_measured_by_pob_but_stays_uncertain` | A plain tower shield replaces Chernobog's Pillar. PoB shows a −25.1% loss, IgniteDPS drops to 0, armour goes up and fire resistance goes down. The primary quantity changes from `HIT_PLUS_AILMENT` to `HIT_DPS`, so offense is `UNMEASURED` (`SEMANTIC_METRIC_CHANGED`). Result: PARTIAL, defense MIXED, public verdict UNCERTAIN. | UNCERTAIN / EXPECTED_UNCERTAIN |
| `test_ineligible_two_hander_clears_shield_and_is_not_viable` | A talisman (not covered by Giant's Blood) is placed. PoB clears the shield, and the removal is disclosed in the result and the presentation. The main mace skill becomes unusable (cold PoB CombinedDPS 0), giving `MAIN_SKILL_INVALID` → NOT_VIABLE. | CONFIDENT / PASS |
| `test_giants_blood_repeated_evaluation_is_deterministic_and_restores` | Weapon, shield, talisman and weapon candidates run interleaved. The repeated check gives an identical verdict, score and DPS, and the fingerprint and equipment return to baseline. | CONFIDENT / PASS |

Corpus integration:

- The fixture `fixtures/builds/public_corpus/corpus02_giants_blood_shield.xml` is
  byte-identical to the supplied export (SHA-256 `664f7d7d…ef1b9`). It was re-screened: no
  `Unique ID`, no `<PlayerStat>`, no account or character identifiers, and it passes the
  public safety scan.
- Manifest id `CORPUS02-GIANTS-BLOOD-SHIELD`; the manifest now has 10 entries.
- Registry: 1 identity case and a new `CORPUS_02A_REAL_POB_CASES` group (6 cases).
- Archetypes: `melee` everywhere, plus `unique_interaction` only on the Chernobog case,
  where the unique's mechanic decides the outcome. `ascendancy` was **not** claimed:
  Gemling Legionnaire is present, but no test isolates an ascendancy effect.
- Identity-only and verdict cases stay separate: 3 are identity-only (manifest identity,
  regression, baseline) and 4 are verdict-level.

## 5. Fixes implemented

None. The reported failure was already fixed in v0.4.0b1, and nothing else reproduced as a
defect.

## 6. Remaining limitations and observations

- **The Chernobog shield case is conservative.** PoB's `CombinedDPS` is available on both
  sides, but the guard (`apply_primary_skill_guard`) treats the hit+ailment → hit-only
  switch as a semantic change, so the answer is UNCERTAIN rather than a measured
  downgrade. That is truthful, and changing it would be a scoring-policy decision, so it
  was left alone.
- **Legacy `recommendation.verdict` diverges from the public verdict.** For the shield
  case it still reads `STRONG_DOWNGRADE` ("Severe damage loss…"), while the authoritative
  `evaluation_outcome.verdict` and `presentation.verdict` are UNCERTAIN. Consumers
  (`history.py`, presentation) prefer the outcome, as enforced by #25. The tests assert the
  public verdict. Tracked separately as follow-up FU-1 (section 10).
- **Misleading worker stderr label.** `run_worker_entrypoint` labels any exception escaping
  the request loop "ExileLens PoB worker could not start", even mid-session. This is a
  diagnostics wording issue only and was not changed.
- **Not covered by this build:** explicit multi-stage (`stage_count` is 1), multi-part
  (`part_count` 0), ascendancy-specific Item Check effects, minion primary offense, and
  jewel candidates for its Megalomaniac / Heart of the Well sockets.
- **Not independently reproduced:** the tester's own OS locale is unknown. The cp1251 cause
  is the only code path found that yields the reported symptom for this build, and it was
  reproduced exactly on the released v0.3.0b1 code.

## 7. Validation (all executed locally)

Environment: Windows 11, Python 3.14.3, pytest 9.1.1. PoB2 was auto-detected at
`%APPDATA%\Path of Building Community (PoE2)` (installed layout, v0.23.1, accepted by
`validate_pob_path`). Nothing was skipped.

| Command | Result |
| --- | --- |
| `pytest tests/integration/test_corpus02_giants_blood_shield.py -m real_pob` | 6 passed |
| Regression test with the UTF-8 stdio fix temporarily disabled | 1 failed with the reported error (fix restored afterwards, `worker.py` unchanged) |
| `pytest tests/integration/test_public_build_corpus.py -m build_corpus` | 36 passed |
| `pytest tests/test_corpus_coverage_report.py tests/test_worker_unicode_stdio.py` | 22 passed |
| `pytest tests/test_socket_normalize.py public_tests/test_m4_4_diagnostics.py` | 15 passed |
| `python scripts/generate_corpus_coverage_report.py` (build_corpus 36, test_public_real_pob 26, weapon-set contexts 8, incompatible placement 3, contextual diagnostic 2, effect enumeration 5, CORPUS-02A 6, adversarial itemcheck 51) | all passed; **73/73** supported (66 PASS, 7 EXPECTED_UNCERTAIN), up from 66/66; `unique_interaction` no longer NO COVERAGE (4/18 categories remain empty) |

The full test suite was not run. Only tests and docs changed.

## 8. Reuse for future CORPUS-02 tasks

- **Independent PoB reference.** Use `_fresh_metrics` in the new module (edit a slot in a
  copy of the XML and cold-load it) to validate a candidate's numbers without trusting
  ExileLens scoring.
- **Controller path.** Drive `_EvaluationWorker.run_baseline_reload` / `run_evaluation`
  with a real `Engine` and connect to `finished_baseline` / `finished_eval`. Restore is
  deferred (PERF-02), so assert on the emitted error and the post-state fingerprint, not
  on `row["restore"]["pass"]`.
- **Already covered; do not duplicate:**
  - Active second weapon set and cross-set contexts: `core04_weapon_swap.xml` (18 cases).
  - OFF-02 two-hand-candidate shield disclosure for a normal one-hand + shield build:
    `test_public_real_pob.py::test_off02_*`.
  - Ambiguous one-hand slot: `core04_onehand_weapon.xml`.
  - Channel-release stage identity plus ignite-dominant uncertainty: `core04_stage_context.xml`.
  - Poison, mixed hit+ignite, and skill-native DoT selection.
  - Sibling effect identities: `test_effect_level_enumeration.py`.
  - Jewel placement and restore: `test_jewel_real_pob.py`, `test_jewel_restore_remediation.py`.
  - Unicode worker stdio mechanism: `tests/test_worker_unicode_stdio.py`.
- **Offhand refusal is PoB-layout-dependent.** The "offhand vs two-hand" refusal in
  `core04_player_ring.xml` follows PoB's slot validity. With Giant's Blood, PoB accepts the
  layout and Item Check measures it (this fixture). New cases should rely on PoB's decision
  instead of assuming either behavior.

## 9. Fixture sanitization cleanup (separate commit)

While screening the new fixture, I found that the older public corpus contradicted
`docs/BUILD_CORPUS_SOURCES.md`. The doc said per-item `Unique ID: <hash>` lines had been
removed, but all nine `fixtures/builds/public_corpus/core04_*.xml` files still contained
them. That is 220 lines in total: bow_quiver 25, melee_weapon 25, minion_actor 23,
mixed_hit_ailment 28, onehand_weapon 24, poison_ailment 25, skill_native_dot 20,
stage_context 27, weapon_swap 23. These are GGG-generated identifiers of a real player's
item drops. `core04_player_ring.xml` and the CORPUS-02A fixture had none.

- **Change.** Only lines matching `^Unique ID: [0-9a-f]+$` were deleted, working on raw
  bytes. The diff is exactly 220 removed lines and nothing else. The CORPUS-02A fixture
  is untouched and still byte-identical to the supplied export.
- **Behavior check (real PoB, original vs. sanitized).** For all nine fixtures these are
  identical: every raw PoB metric (59–69 fields each), main-skill identity, class and
  ascendancy, allocated passives, jewels, and equipped items, whose raw text is equal
  once the removed line is excluded. The only difference is ExileLens's fingerprint hash,
  which covers raw item text; no test pins one. No code reads `Unique ID`. The synthetic
  all-zero `Unique ID` lines inside candidate clipboard text in the socket-normalization
  tests are deliberate: they model real clipboard items, are not fixtures, and were left
  alone.
- **Guard.** `test_selected_fixture_contains_no_private_path_or_identity_markers` now also
  rejects `(?im)^\s*Unique ID:` and names the offending markers. Run against the
  pre-cleanup fixtures, it rejects all 9.
- **Docs.** `BUILD_CORPUS_SOURCES.md` now records the correction, and states accurately
  that `<PlayerStat>` was stripped only from poe.ninja-sourced fixtures. The four fixtures
  inherited from the earlier local corpus (player_ring, bow_quiver, minion_actor,
  stage_context) keep PoB's own save-time `<PlayerStat>` cache. PoB writes it but never
  reads it back, and it contains no identifiers, so it was deliberately not rewritten.
- **Validation.**
  - Privacy / manifest / well-formedness tests: 26 passed.
  - Socket-normalization and jewel real-PoB suites plus the socket unit test: 26 passed,
    1 pre-existing designed skip. The skipped test is `test_jewel_real_pob.py:234`, which
    needs an allocated-but-empty jewel socket that no corpus fixture has.
  - Coverage generator, all 8 suites: 36 / 26 / 8 / 3 / 2 / 5 / 6 / 51 passed. The
    regenerated report is byte-identical, still 73/73.

## 10. Follow-ups (not done here; no verdict or scoring policy changed)

- **FU-1: legacy row verdict contradicts the public verdict.** In the Chernobog's Pillar
  replacement case, `slot_comparisons[i]["verdict"]` and therefore
  `recommendation["verdict"]` read `STRONG_DOWNGRADE`, with the explanation "Severe damage
  loss. Defenses improve substantially. Fire resistance cap lost." Meanwhile
  `evaluation_outcome.verdict` and `presentation.verdict` are `UNCERTAIN` (quality
  PARTIAL, offense `UNMEASURED` / `SEMANTIC_METRIC_CHANGED`).
  - Source: `src/exilelens/items/ranking.py` sets `comparison["verdict"]` and
    `verdict_explanation` from the legacy classifier (around line 306).
  - Its "Severe damage loss." branch (around line 133) is evaluated from the raw percent
    *before* the `UNMEASURED` check.
  - `sync_value_with_outcome` re-syncs only the `value` block.
  - Current user-facing surfaces use the outcome (#25), so this is a latent consistency
    risk for any consumer reading the legacy fields, not a known visible defect.
  - Suggested direction for a separate task: make the legacy row verdict and explanation
    mirror, or defer to, the authoritative outcome whenever offense is not measured. Add
    a regression using `test_chernobog_shield_loss_is_measured_by_pob_but_stays_uncertain`.
  - This is a verdict-surface decision, so it was intentionally not changed in CORPUS-02A.
- **FU-2: worker crash stderr label.** `run_worker_entrypoint` reports "could not start"
  for mid-session crashes (section 6). This is a diagnostics wording issue only.
