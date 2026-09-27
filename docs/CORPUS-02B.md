# CORPUS-02B — Minion and Djinn real-world coverage

Branch `test/corpus-02b-minion-djinn`, based on `origin/main` at `cb3aafd` (CORPUS-02A, PR #42).

## 1. Existing coverage (inspected, reused, not rebuilt)

- **Minion offense selection already existed and works.** `primary_metric.resolve_primary_metric`
  reads a minion-owned main skill from `mainOutput.Minion` (`Minion.CombinedDPS`,
  `ACTOR_COMBINED_DPS`). `offense_coverage` has minion-specific probes, and
  `apply_primary_skill_guard` marks offense `UNMEASURED` if the damage owner, output table,
  actor or actor skill changes between baseline and candidate.
- **The Infernal Hound fixture (`core04_minion_actor.xml`) had identity-only coverage.**
  The manifest identity case and `MINION-STAGE-IDENTITY-RETAINED` confirmed the MINION owner
  and skill id. No Item Check verdict was asserted on any minion build.
- **Djinn references in the repository: none.** The only record of the community report is
  an earlier audit note (`.planning/…-community-regression-compatibility-audit`). It says a
  Reddit tester (thread `1wniams`) reported almost every item as UNCERTAIN and "Varasta
  Djinns" missing from advanced details. No build was attached.

## 2. The community Djinn report: what could and could not be established

- **The original report was not obtainable.** Reddit is blocked from this environment,
  through both the fetch tool and the in-app browser. No local session, attachment, or
  planning file holds the tester's PoB export. **The exact build is missing evidence.**
- **The related evidence used is a different build.** The predecessor development
  repository's Build Corpus V1 has a real Disciple of Varashta ladder character (C08,
  poe.ninja Runes of Aldur, level 100, 2026-09-12). It carries all three Djinns, with Navira
  as the main skill. It was re-sanitized and added as
  `fixtures/builds/public_corpus/corpus02b_varashta_djinn.xml`. **It is not the tester's
  build and is not presented as a reproduction.**

What this build shows:

| Configuration | Current `main` | v0.3.0b1 |
| --- | --- | --- |
| Navira (Water Djinn) main, as exported | FULL, directional verdicts, `Minion.CombinedDPS` 467,530 | FULL, same verdicts |
| Ruzhan (Fire Djinn) main, edited selection | FULL | – |
| Kelari (Sand Djinn) main, edited selection | FULL | – |
| Navira's player-cast **Command** effect selected as the main skill | PoB calculates **no** offensive output, so **every item is PARTIAL / UNCERTAIN** (`OFFENSE_MISSING`, `PRIMARY_METRIC_LOW_CONFIDENCE`) | – |

- **"UNCERTAIN for nearly every item" did not reproduce** for any Djinn-summon main-skill
  configuration, in either version.
- **The Command-as-main configuration produces exactly that symptom.** There the UNCERTAIN
  is correct: PoB provides nothing to compare. It is a plausible explanation, but it is
  unconfirmed without the tester's export.
- **Missing Djinn information in the advanced view reproduced on this build** (see section 3).

## 3. Diagnosis and the one fix

| Gap category | Finding |
| --- | --- |
| Incorrect skill/actor selection | None found. Navira resolves to actor `WaterDjinn` / `mainOutput.Minion`, and the Infernal Hound to `SummonedHellhound`. |
| Missing PoB-calculated metrics | Only when PoB's main skill is the Djinn Command, a PoB configuration choice. PoB itself outputs nothing. |
| Unsupported mechanics | Djinn Command damage is not calculated by PoB in this configuration, so ExileLens cannot measure it. |
| Evaluation-quality classification | Correct in every case tested: FULL where PoB measures the owner's damage, PARTIAL/UNCERTAIN where it does not. |
| **Presentation omission** | **Reproduced and fixed.** Ruzhan and Kelari were absent from "POB DAMAGE COMPONENTS" in the advanced view. |
| Expected UNCERTAIN | The Command-as-main variant. |

**Root cause of the omission.** For multi-skill builds, Item Check requests PoB's per-group
report only for groups whose static PoB stat-set flags say `hit`, `dot` or `minion`
(`native_damage_candidate` in `runtime/lua/bridge.lua`). The flags differ by Djinn:

- Water Djinn: `baseFlags = { minion = true }`.
- Fire and Sand Djinn: `baseFlags = {}` in PoB's data, although PoB calculates their minions.

Their groups (1, 3, 16) were therefore never reported. With a full report they pass every
component gate:

- Ruzhan: 61,472 `Minion.CombinedDPS`.
- Kelari: 61,799 `Minion.CombinedDPS`.

**The fix (4 lines).** A group whose gem selects a minion actor (`skillMinion` /
`skillMinionCalcs`) is also a discovery hint. It is only a hint: a displayed component still
needs a directly calculated, significant, high-confidence PoB output, so truthfulness gates
are unchanged. Verdicts on the Djinn build are identical before and after. The regression
test fails without the fix.

## 4. New verdict-level coverage

`tests/integration/test_corpus02b_minion_djinn.py` adds 7 real-PoB tests. Every number is
compared with a cold PoB load of an edited copy of the fixture.

| Test | Fixture | Result (PoB-verified) | Expected |
| --- | --- | --- | --- |
| `test_minion_damage_ring_is_measured_on_the_minion_actor` | Hound | Ring 1 with +30% minion damage: 67,034 → 69,750 (+4.1%). Player CombinedDPS is 0. FULL, offense-only upgrade | CONFIDENT |
| `test_losing_minion_skill_levels_is_a_measured_minion_downgrade` | Hound | Amulet without +4 minion skill levels: −36.3%, same actor and skill. FULL / MEANINGFUL_DOWNGRADE | CONFIDENT |
| `test_player_defense_ring_is_a_minion_offense_versus_defense_tradeoff` | Hound | Player-defense ring: minion −10.6% (Ring 1), defense up. FULL / SIDEGRADE in both ring slots | CONFIDENT |
| `test_minion_repeated_evaluation_is_deterministic_and_restores` | Hound | Identical repeat; fingerprint and equipment restored | CONFIDENT |
| `test_djinn_minion_levels_are_measured_and_every_djinn_component_is_reported` | Djinn | Amulet without +5 minion levels: Navira −43.5%, Ruzhan −41.6%, Kelari −41.7%, each matching PoB with that Djinn selected. FULL / MEANINGFUL_DOWNGRADE. All three Djinns shown in More Info. No whole-build total claimed | CONFIDENT |
| `test_djinn_minion_damage_ring_is_a_measured_upgrade_and_restores` | Djinn | Ring with +30% minion damage: +5.2%, FULL directional, identical on repeat, fingerprint restored | CONFIDENT |
| `test_djinn_command_as_main_skill_is_truthfully_uncertain` | Djinn (Command variant) | PoB has no offense output, so PARTIAL / UNCERTAIN (`OFFENSE_MISSING`) | UNCERTAIN |

- **Public verdicts asserted:** all assertions use `evaluation_outcome.verdict` and
  `presentation.verdict`, never the legacy `recommendation.verdict`.
- **Registry:** 1 identity case plus `CORPUS_02B_REAL_POB_CASES` (7 verdict cases).
- **Archetypes:** `minion` on all cases, and `ascendancy` only on the two Djinn cases, whose
  primary damage is the ascendancy-granted Water Djinn.
- **Methodology note:** `CORPUS_COVERAGE_METHODOLOGY.md` now states that rule. The
  `ascendancy` category no longer has zero coverage.

**Not added (evidence did not support it):**

- **A sceptre "presence damage" case.** Removing that rune-granted line gives 0.0% in both
  ExileLens and a cold PoB load, so it proves nothing new.
- **More identity-only tests.**

## 5. Remaining unsupported mechanics and missing evidence

- **The tester's exact Varashta export is missing.** Its main-skill configuration, items
  and ExileLens version are unknown.
- **Djinn Command damage.** When a Command effect is PoB's main skill, PoB calculates no
  offense, so Item Check is truthfully UNCERTAIN. A clearer user-facing hint (for example
  "select the Djinn summon in PoB") would be a product decision and is not implemented.
- **FU-3: Ruzhan-main metric label, unverified semantics.** With the Fire Djinn as the main
  skill:
  - PoB's `Minion.CombinedDPS` equals `Minion.AverageDamage` (61,472).
  - `Minion.TotalDPS` = 61,472 × 2.6/s = 159,828.
  - ExileLens labels the field `PER_SECOND` because the show-average flag it reads is the
    player group's (false), not the minion skill's.
  - Deltas remain like-for-like (the same field on both sides), but the absolute "DPS"
    label may be a per-use average.
  - Not changed: no reported case, and it would alter metric semantics.
- **Legacy verdict fields.** FU-1 from CORPUS-02A, where the legacy verdict can contradict
  the public verdict, still applies. It is tracked separately and untouched here.
- **Still empty archetypes:** `proxy_totem`, `stat_stacker` and `es_scaling`. Spectres,
  companions and multi-minion full-build aggregation (`FullDPS` not configured in either
  fixture) have no verdict coverage.

## 6. Validation (executed locally)

Environment: Windows 11, Python 3.14.3, PoB2 0.23.1 (auto-detected).

| Command | Result |
| --- | --- |
| `pytest tests/integration/test_corpus02b_minion_djinn.py -m real_pob` | 7 passed |
| Djinn component test with the bridge fix reverted | 1 failed (`{1, 2, 3}` not in the discovery hints); fix restored |
| `pytest tests/test_corpus_coverage_report.py` | 20 passed |
| `python scripts/generate_corpus_coverage_report.py`, the real-PoB corpus gate run once. Suites: build_corpus 39, test_public_real_pob 26, weapon-set 8, placement 3, diagnostic 2, effect enumeration 5, CORPUS-02A 6, CORPUS-02B 7, adversarial 51 | all passed; **81/81** supported (up from 73/73) |
| Socket-normalization and jewel real-PoB suites (they also exercise the changed discovery path) | 19 passed, 1 pre-existing designed skip |

The full test suite was not run. The experimental independent engine was not touched.
