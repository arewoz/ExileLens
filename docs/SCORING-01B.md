# SCORING-01b - calibration and regression completion

SCORING-01b continues the policy merged in SCORING-01a at
`552d09b8d24660b884b09dcbed7b86dd1fa3b719` (PR #56). It fixes the downgrade transition,
handles measured recovery from zero, corrects the Resource percentage sign, and makes the
public explanation follow the measured result. PoB calculation, score weights, quality precedence,
resource guardrails, movement weights, and release metadata are unchanged.

## Final material-conflict policy

Direction, materiality, conflict, and verdict remain separate. A `MATERIAL` conflict requires
both a material gain and a material loss. Descriptive `pattern == TRADEOFF` alone is insufficient;
`NONE` uses the ordinary score. Measured negligible opposition stays visible but cannot force SIDEGRADE.

Quality and feasibility keep precedence: FAILED, UNSUPPORTED, not-viable guardrails, PARTIAL,
applied score ceilings, then material-conflict resolution.

| FULL, no applied guardrail | Resolution |
| --- | --- |
| Conflict NONE | `final_score = raw_score`; ordinary score verdict |
| MATERIAL, raw <= 47 | Ordinary downgrade, same score; named trade-off appended |
| MATERIAL, 47 < raw < 60 | SIDEGRADE at 50.0; meaningful trade-off explained |
| MATERIAL, raw >= 60 | MINOR_UPGRADE capped at 59.0; material loss explained |

The downgrade edge now uses `SCORE_SCALE.minor_downgrade` (47), replacing the meaningful-downgrade
edge (40). This preserves the adjacent sequence MEANINGFUL_DOWNGRADE -> MINOR_DOWNGRADE -> SIDEGRADE
-> MINOR_UPGRADE as scores improve. A material conflict may hold an upgrade back, but never softens
an ordinary downgrade. Deterministic sweeps of synthetic inputs and real replay measurements check
monotonicity and adjacency as opposing effects worsen.

## Recovery calibration and zero baseline

`recovery_pool_pct` remains **0.5% of baseline max Life per second, provisional**. It was not tuned
to Cases A or B. A nonzero baseline also needs the existing 3% relative recovery change.
A baseline of exactly zero has no relative percentage: the signed absolute change and its measured
Life-pool fraction decide materiality, with no fake percentage, infinity, or NaN. Missing Life or
Life <= 1 cannot establish material recovery. The from-zero boundary, both directions, no change,
missing/CI pools, conflicts, and finite JSON serialization have focused tests.

The recovered initial corpus survey contains 2,612 outcome records from 137 tests and 661 distinct
outcomes under its deduplication key; the final survey contains 2,622 records from 147 tests and 665
distinct outcomes. Multiple profiles, repeated evaluations, and best-slot comparisons appear in these
counts; they are not fixture counts or coverage-case counts.

Observed distinct nonzero recovery changes were 0.039, 0.044, 0.055, 0.059, 0.112, 0.114, 0.212,
0.228, 0.312, 0.367, 0.638, and 0.740% of baseline max Life per second. Case B adds 0.122% from
sanitized diagnostics replay. Thus the default sits in the observed gap between 0.367 and 0.638%,
without cutting an observed value. This is evidence supporting retention, not broad calibration.

The authentic CORPUS-02D2 Voltaic Barrier build supplies a positive recovery control:
170.1 -> 188.2 life/s, +18.1/s, 0.638% of its 2,839 baseline Life, with Life/EHP up and offense unchanged.
The new data-only replay fixture was captured from that real PoB comparison and produces FULL /
MEANINGFUL_UPGRADE 73.6 in Balanced. No tester identity, item text, private path, or raw diagnostics
bundle is included. No real 0 -> positive recovery case appeared in the surveyed corpus; that path
has deterministic policy tests, not a claimed real-PoB regression.

## Presentation and legacy consumers

The Resource explanation uses `(candidate - baseline) / abs(baseline) * 100` for nonzero sustain.
For Case B, -30.54 -> -29.74 is +2.6%, correctly listed as an improvement. A worsening remains
negative; a positive baseline and a zero baseline retain their established behavior. This change
normalizes the explanation sign; it does not alter resource feasibility or scoring.

A downgrade's compact explanation starts with its losses; an upgrade starts with its gains.
Case A says: "Recovery +6.8 life/s (0.37% of max Life per second) is too small to offset the larger
offense and defense losses." Case B names the corresponding small loss and larger gains.
Verdict reason, compact presentation, More Info, and Build Intelligence agree. Measured losses
under conflict NONE use the heading WHAT GETS WORSE; material conflicts retain TRADE-OFF.
History persists the authoritative public verdict used by its dashboard entries; pinned detail reuses
the common presentation builder. The inactive legacy dashboard-detail formatter is not used as evidence
of an active surface. MAIN-SKILL-01 presentation and its precedence are preserved.

Legacy Build Intelligence `pareto_status` has no user-facing consumer in the source search and its
algorithm remains unchanged. Public `result["pareto"]` reads the authoritative outcome: a SIDEGRADE
with conflict NONE is NEITHER_DOMINATES; a material SIDEGRADE is TRADEOFF. Legacy payloads without
conflict information keep their prior compatibility reading. Movement/UTILITY are not redesigned.

## Complete pre-01a -> 01a -> 01b replay table

These 44 rows replay all 11 data-only fixtures under all four value profiles through the production
pipeline. Pre-01a source is read from `c2c3974`; 01a source from merged `552d09b`; 01b is the final
working tree. These are offline policy replays of the same captured measurements, not fresh PoB runs.
Scores beside verdicts are final scores; the Raw column is the unchanged ordinary score.

| Fixture / profile | Raw | Pre-01a | 01a | 01b | Conflict / constraint |
| --- | ---: | --- | --- | --- | --- |
| Case B boots / BALANCED | 79.3 | SIDEGRADE 50.0 | MEANINGFUL_UPGRADE 79.3 | MEANINGFUL_UPGRADE 79.3 | NONE |
| Case B boots / MAPPING | 75.9 | SIDEGRADE 50.0 | MEANINGFUL_UPGRADE 75.9 | MEANINGFUL_UPGRADE 75.9 | NONE |
| Case B boots / BOSSING | 79.3 | SIDEGRADE 50.0 | MEANINGFUL_UPGRADE 79.3 | MEANINGFUL_UPGRADE 79.3 | NONE |
| Case B boots / DEFENSIVE | 86.0 | SIDEGRADE 50.0 | MEANINGFUL_UPGRADE 86.0 | MEANINGFUL_UPGRADE 86.0 | NONE |
| CORE-04 Ring 1 / BALANCED | 62.5 | SIDEGRADE 50.0 | MINOR_UPGRADE 59.0 | MINOR_UPGRADE 59.0 | MATERIAL |
| CORE-04 Ring 1 / MAPPING | 73.6 | SIDEGRADE 50.0 | MINOR_UPGRADE 59.0 | MINOR_UPGRADE 59.0 | MATERIAL |
| CORE-04 Ring 1 / BOSSING | 57.7 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | MATERIAL |
| CORE-04 Ring 1 / DEFENSIVE | 44.7 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | MINOR_DOWNGRADE 44.7 | MATERIAL |
| CORPUS-02B Ring 1 / BALANCED | 43.5 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | MINOR_DOWNGRADE 43.5 | MATERIAL |
| CORPUS-02B Ring 1 / MAPPING | 32.3 | SIDEGRADE 50.0 | MEANINGFUL_DOWNGRADE 32.3 | MEANINGFUL_DOWNGRADE 32.3 | MATERIAL |
| CORPUS-02B Ring 1 / BOSSING | 48.2 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | MATERIAL |
| CORPUS-02B Ring 1 / DEFENSIVE | 60.7 | SIDEGRADE 50.0 | MINOR_UPGRADE 59.0 | MINOR_UPGRADE 59.0 | MATERIAL |
| 02D1 attack-speed loss control / BALANCED | 27.4 | MEANINGFUL_DOWNGRADE 27.4 | MEANINGFUL_DOWNGRADE 27.4 | MEANINGFUL_DOWNGRADE 27.4 | NONE |
| 02D1 attack-speed loss control / MAPPING | 21.0 | MEANINGFUL_DOWNGRADE 21.0 | MEANINGFUL_DOWNGRADE 21.0 | MEANINGFUL_DOWNGRADE 21.0 | NONE |
| 02D1 attack-speed loss control / BOSSING | 30.6 | MEANINGFUL_DOWNGRADE 30.6 | MEANINGFUL_DOWNGRADE 30.6 | MEANINGFUL_DOWNGRADE 30.6 | NONE |
| 02D1 attack-speed loss control / DEFENSIVE | 40.3 | MINOR_DOWNGRADE 40.3 | MINOR_DOWNGRADE 40.3 | MINOR_DOWNGRADE 40.3 | NONE |
| 02D1 trade-off gloves / BALANCED | 47.9 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | MATERIAL |
| 02D1 trade-off gloves / MAPPING | 64.2 | SIDEGRADE 50.0 | MINOR_UPGRADE 59.0 | MINOR_UPGRADE 59.0 | MATERIAL |
| 02D1 trade-off gloves / BOSSING | 41.5 | SIDEGRADE 50.0 | SIDEGRADE 50.0 | MINOR_DOWNGRADE 41.5 | MATERIAL |
| 02D1 trade-off gloves / DEFENSIVE | 25.5 | SIDEGRADE 50.0 | MEANINGFUL_DOWNGRADE 25.5 | MEANINGFUL_DOWNGRADE 25.5 | MATERIAL |
| 02D1 poison gain control / BALANCED | 68.2 | MEANINGFUL_UPGRADE 68.2 | MEANINGFUL_UPGRADE 68.2 | MEANINGFUL_UPGRADE 68.2 | NONE |
| 02D1 poison gain control / MAPPING | 73.4 | MEANINGFUL_UPGRADE 73.4 | MEANINGFUL_UPGRADE 73.4 | MEANINGFUL_UPGRADE 73.4 | NONE |
| 02D1 poison gain control / BOSSING | 65.6 | MEANINGFUL_UPGRADE 65.6 | MEANINGFUL_UPGRADE 65.6 | MEANINGFUL_UPGRADE 65.6 | NONE |
| 02D1 poison gain control / DEFENSIVE | 57.8 | MINOR_UPGRADE 57.8 | MINOR_UPGRADE 57.8 | MINOR_UPGRADE 57.8 | NONE |
| 02D2 recovery gain amulet / BALANCED | 73.6 | MEANINGFUL_UPGRADE 73.6 | MEANINGFUL_UPGRADE 73.6 | MEANINGFUL_UPGRADE 73.6 | NONE |
| 02D2 recovery gain amulet / MAPPING | 63.5 | MEANINGFUL_UPGRADE 63.5 | MEANINGFUL_UPGRADE 63.5 | MEANINGFUL_UPGRADE 63.5 | NONE |
| 02D2 recovery gain amulet / BOSSING | 77.0 | MEANINGFUL_UPGRADE 77.0 | MEANINGFUL_UPGRADE 77.0 | MEANINGFUL_UPGRADE 77.0 | NONE |
| 02D2 recovery gain amulet / DEFENSIVE | 83.8 | MEANINGFUL_UPGRADE 83.8 | MEANINGFUL_UPGRADE 83.8 | MEANINGFUL_UPGRADE 83.8 | NONE |
| 02F ignite-only PARTIAL / BALANCED | 50.0 | UNCERTAIN 50.0 | UNCERTAIN 50.0 | UNCERTAIN 50.0 | NONE |
| 02F ignite-only PARTIAL / MAPPING | 50.0 | UNCERTAIN 50.0 | UNCERTAIN 50.0 | UNCERTAIN 50.0 | NONE |
| 02F ignite-only PARTIAL / BOSSING | 50.0 | UNCERTAIN 50.0 | UNCERTAIN 50.0 | UNCERTAIN 50.0 | NONE |
| 02F ignite-only PARTIAL / DEFENSIVE | 50.0 | UNCERTAIN 50.0 | UNCERTAIN 50.0 | UNCERTAIN 50.0 | NONE |
| 02G requirement-loss amulet / BALANCED | 2.8 | NOT_VIABLE 2.8 | NOT_VIABLE 2.8 | NOT_VIABLE 2.8 | ATTRIBUTE_REQUIREMENT_LOST |
| 02G requirement-loss amulet / MAPPING | 6.1 | NOT_VIABLE 6.1 | NOT_VIABLE 6.1 | NOT_VIABLE 6.1 | ATTRIBUTE_REQUIREMENT_LOST |
| 02G requirement-loss amulet / BOSSING | 2.8 | NOT_VIABLE 2.8 | NOT_VIABLE 2.8 | NOT_VIABLE 2.8 | ATTRIBUTE_REQUIREMENT_LOST |
| 02G requirement-loss amulet / DEFENSIVE | 6.1 | NOT_VIABLE 6.1 | NOT_VIABLE 6.1 | NOT_VIABLE 6.1 | ATTRIBUTE_REQUIREMENT_LOST |
| 02H chaos-cap-loss helmet / BALANCED | 73.7 | MINOR_DOWNGRADE 47.0 | MINOR_DOWNGRADE 47.0 | MINOR_DOWNGRADE 47.0 | RES_CAP_LOST |
| 02H chaos-cap-loss helmet / MAPPING | 76.2 | MINOR_DOWNGRADE 47.0 | MINOR_DOWNGRADE 47.0 | MINOR_DOWNGRADE 47.0 | RES_CAP_LOST |
| 02H chaos-cap-loss helmet / BOSSING | 71.6 | MINOR_DOWNGRADE 47.0 | MINOR_DOWNGRADE 47.0 | MINOR_DOWNGRADE 47.0 | RES_CAP_LOST |
| 02H chaos-cap-loss helmet / DEFENSIVE | 62.4 | MINOR_DOWNGRADE 47.0 | MINOR_DOWNGRADE 47.0 | MINOR_DOWNGRADE 47.0 | RES_CAP_LOST |
| Case A helmet / BALANCED | 6.9 | SIDEGRADE 50.0 | MEANINGFUL_DOWNGRADE 6.9 | MEANINGFUL_DOWNGRADE 6.9 | NONE |
| Case A helmet / MAPPING | 8.5 | SIDEGRADE 50.0 | MEANINGFUL_DOWNGRADE 8.5 | MEANINGFUL_DOWNGRADE 8.5 | NONE |
| Case A helmet / BOSSING | 7.5 | SIDEGRADE 50.0 | MEANINGFUL_DOWNGRADE 7.5 | MEANINGFUL_DOWNGRADE 7.5 | NONE |
| Case A helmet / DEFENSIVE | 12.0 | SIDEGRADE 50.0 | MEANINGFUL_DOWNGRADE 12.0 | MEANINGFUL_DOWNGRADE 12.0 | NONE |

There are **three verdict changes from 01a to 01b**: CORE-04 / Defensive (raw 44.7),
CORPUS-02B / Balanced (43.5), and CORPUS-02D1 gloves / Bossing (41.5). All three are MATERIAL,
have no applied guardrail, and lie in (40, 47]; preserving the ordinary MINOR_DOWNGRADE explains each.
Balanced CORE-04 remains MINOR_UPGRADE 59.0; Balanced 02D1 gloves remain SIDEGRADE 50.0.
All profiles for these three conflict fixtures have explicit regression assertions.

The final real-PoB survey has **13 distinct changed verdict/score configurations versus pre-01a**:
three CORE-04 profiles, three 02B profiles, three 02D1 glove profiles, and all four Case A profiles.
Case B contributes four more profile changes in diagnostics replay, outside the real-PoB survey.
The table includes every one of these 17 changes and the unchanged controls.

The matched initial/final survey has 1,104 distinct test/measurement keys and exactly the same three
01b verdict changes. Four Ballista Ring 2 profile records have different raw scores between the runs
(24.3/32.1/28.9/18.8 -> 25.3/33.1/29.9/19.8); all retain MEANINGFUL_DOWNGRADE and RES_CAP_LOST.
The summary-only survey does not store enough inputs to attribute that numeric variation, so these
records are not evidence of identical raw measurements. Ten additional final records come from
malformed-output and critical-constraint unit cases, all failing closed as expected. No unexplained
verdict flip was found; no constant was tuned in response to this audit.

## Guardrails, Stonefist, and best slots

The final survey includes 910 RES_CAP_LOST records across 55 tests, 67 attribute-requirement-loss
records across 10 tests, and 380 PARTIAL records across 27 tests. None changes verdict versus the
pre-01a rule. Unsupported comparisons remain unsupported; otherwise requirement loss stays NOT_VIABLE.
PARTIAL stays UNCERTAIN unless a feasibility guardrail takes precedence.

Stonefist: 672 records across 24 tests, no verdict flips. Its transform support, unsupported unique
cases, uncertainty, restore behavior, and repeated-evaluation contracts are retained.
CORE-04's real best-slot integration remains passing. Its Ring 1 Balanced result is the capped
MINOR_UPGRADE; alternative-slot quality/guardrails still determine eligibility before score.
The 02B player-defense ring's Ring 2 remains NOT_VIABLE for attribute requirement loss.

## Validation and coverage

Expensive evidence was recovered from the previous agent and **reused**, because continuation made
no production change after those runs:

- Real-PoB corpus generator: **173/173 registered cases supported**; captured generator output confirms it.
- Extra integration files outside the generator (socket normalization, jewel real-PoB, jewel remediation):
  **19 passed, 1 skipped**, as recorded in the handoff; not rerun in this continuation.
- Earlier calibration/policy modules: **86 passed**; the handoff also records five expected failures when
  the old raw-40 transition was temporarily restored, followed by source restoration. That mutation
  experiment was not rerun.

Continuation validation:

- Calibration, policy-core, and report unit modules: **109 passed** before the 12 all-profile assertions
  were added; report tests comprise 23 of those checks.
- Directly affected adversarial, complex-damage, tooltip, Build Intelligence role, MAIN-SKILL-01, and
  ailment-intelligence unit modules: **112 passed**.
- Final calibration module, including the 12 profile assertions: **42 passed**.
- Ruff configured lint, startup static checker, touched-source compile checks, and `git diff --check` pass.
- Ruff formatter check reports existing style differences in all 12 previously tracked Python files,
  also present in the unchanged 01a sources. The branch preserves that style rather than reformatting
  unrelated lines. The new test module follows the existing policy-test style.
- Required PR gates are `smoke` and `Native Windows P0 validation`; final results are recorded on the PR.

The generated coverage report derives its **19 build fixtures** from `manifest.json`, not a literal.
Supported cases: **173/173 (100%)**, comprising 146 PASS, 19 EXPECTED_UNCERTAIN, and 8 UNSUPPORTED.
Functional coverage remains **45/54 (83%)** fully measured, with 64 executed verdict-level cases still
unclassified. Correct refusal counts as supported behavior, not functional measurement or population coverage.

## Remaining limitations

- The 0.5% recovery floor is provisional; one authentic recovery-heavy build supports a material-gain control,
  but broad calibration and a real zero-baseline recovery fixture remain absent.
- Recovery is explanatory/conflict evidence, not an independently weighted score component.
- Recovery normalization uses baseline Life; missing or CI-sized pools cannot establish material Life recovery.
- Community boots are REPRODUCED / COVERED via sanitized diagnostics replay, with no tester PoB export.
- Candidate level requirements remain unevaluated; measured attribute requirements have their existing gate.
- Legacy internal pareto and payloads without conflict data retain compatibility behavior.
- Existing partial/unsupported mechanics and incomplete functional classifications remain as reported by the corpus.
