# SCORING-01a - verdict policy core

Scope: how already-measured PoB effects are combined into the public verdict. No PoB measurement, quality
(FULL / PARTIAL / UNSUPPORTED / FAILED) or scoring-weight logic changed.

## The defect

`decide_verdict` forced `SIDEGRADE` at a score of 50.0 whenever `item_impact.pattern == "TRADEOFF"` and no guardrail applied. The pattern
only required one "significant" axis moving up and one moving down. Recovery counted as significant on a **relative** change alone and carries
no weight in the score, so a tiny absolute change could discard the whole score:

| Case | Measured | Old | Why |
| --- | --- | --- | --- |
| A (CORPUS-02H, life instead of ES helmet) | offense -17.9%, EHP -8.3%, recovery 37.1 -> 43.9/s (+6.8/s, 0.37% of max Life per second) | SIDEGRADE, 50.0 (raw 6.9) | +18% relative recovery |
| B (community boots) | EHP +32.9%, max hit +27.6%, movement +9.7 points, 3 resistances up, recovery 1.5 -> 0/s (-1.5/s, 0.12% of max Life per second) | SIDEGRADE, 50.0 (raw 79.3) | -100% relative recovery |

## Policy: direction -> materiality -> conflict -> verdict

1. **Direction** is unchanged (labels `POSITIVE`, `NEGATIVE`, `MIXED`, `NEUTRAL`; `pattern` stays as a descriptive, backward-compatible field).
2. **Materiality** (`ImpactAxis.material_positive` / `material_negative`): a movement is a real gain or loss when it reaches the axis threshold.
   - Offense, defense, movement, resistance targets: the existing thresholds (3%, 3%, 8 points, cap events / 5 deficit points).
   - **Recovery** additionally needs a real part of the Life pool: `|change in LifeRegenRecovery per second| / baseline max Life >= recovery_pool_pct`.
     Missing Life, or a pool of 1 (Chaos Inoculation), means recovery cannot be material; nothing is invented.
   - **MIXED axes** are material in a direction only when a component of that direction reaches the threshold. A -0.3% sibling next to a +9% gain
     no longer makes a trade-off.
3. **Conflict** (`ItemImpact.conflict.kind`): `MATERIAL` only if some axis is a material gain **and** some axis is a material loss; otherwise `NONE`.
   Opposing changes that are not material are recorded as `negligible_opposition` (disclosed, never decisive).
4. **Verdict** (`evaluation_outcome.decide_verdict`), in this precedence: FAILED, UNSUPPORTED, not-viable guardrails, PARTIAL -> UNCERTAIN, applied guardrails
   (unchanged ceiling behaviour), then conflict resolution:
   - `NONE`: `final_score = raw_score`, `verdict = classify_score_verdict(final_score)`. Nothing is forced to 50.
   - `MATERIAL`, `raw <= SCORE_SCALE.meaningful_downgrade`: the ordinary downgrade (the score is decisive).
   - `MATERIAL`, `raw >= SCORE_SCALE.useful`: the score path, capped at `MINOR_UPGRADE_CEILING` because a real loss exists.
   - `MATERIAL`, otherwise: the canonical SIDEGRADE at 50.0 ("Meaningful trade-off: ...").

No dominance ratio, weight change or new score is introduced: importance still comes from the existing profile-weighted score.

## `recovery_pool_pct` = 0.5 (% of max Life per second)

A provisional, conservative default derived from gameplay meaning rather than tuned to a case: 0.5% of max Life per second restores, over a short (about
6 second) engagement, the same 3% of the pool that `defense_pct` already treats as a significant defensive change. Cases A (0.37) and B (0.12) sit below it, but
the tests demonstrate that neither result depends on the exact value (Case A is a downgrade whether or not its recovery counts; Case B stays a non-conflict for
any value above 0.12 and becomes a conflict below it). SCORING-01b revisits the value with more builds.

## User-facing consistency

`pattern` may still say `TRADEOFF`, but no surface calls a non-conflict a trade-off: the verdict reason ("Net score ... Small opposing change not large
enough to offset: ..."), the overlay/More Info explanation, the build-intel `TRADEOFF` product verdict / headline and its pareto override (which now follow `conflict.kind`) and the
reasons / trade-off lists (negligible rows moved to `explanation.negligible_opposition`) all agree. Richer presentation is SCORING-01b.

## Replay infrastructure

`tests/policy_replay/`: data-only fixtures (measured values, no item text or build identity) replayed through the production `enrich_slot_comparison`;
`capture.py` builds a fixture from a real `evaluate_item` row, `flip_report.py` prints the old-vs-new table
(`PYTHONPATH=src python -m tests.policy_replay.flip_report`). Fixtures record the outcome at `origin/main` c2c3974 for comparison.

## Old vs new (replay of real measurements)

| Fixture | Old | New | Raw | Conflict | Intended |
| --- | --- | --- | --- | --- | --- |
| Case B boots | SIDEGRADE 50.0 | MEANINGFUL_UPGRADE 79.3 | 79.3 | NONE (recovery negligible) | yes |
| Case A helmet | SIDEGRADE 50.0 | MEANINGFUL_DOWNGRADE 6.9 | 6.9 | NONE (recovery negligible) | yes |
| CORE-04 ring (+21.7% offense, -4.3% EHP) | SIDEGRADE 50.0 | MINOR_UPGRADE 59.0 | 62.5 | MATERIAL | yes: lopsided conflict, capped |
| CORPUS-02D1 gloves (+11.0% / -10.9%) | SIDEGRADE | SIDEGRADE | 47.9 | MATERIAL | unchanged |
| CORPUS-02B minion ring (-10.6% / +5.3%) | SIDEGRADE | SIDEGRADE | 43.5 | MATERIAL | unchanged |
| CORPUS-02H chaos cap lost | MINOR_DOWNGRADE 47.0 | same | 73.7 | MATERIAL + RES_CAP_LOST | unchanged |
| CORPUS-02G requirement lost | NOT_VIABLE | same | 2.8 | NONE | unchanged |
| CORPUS-02F ignite only | UNCERTAIN | same | 50.0 | NONE (PARTIAL) | unchanged |
| CORPUS-02D1 controls | MEANINGFUL_DOWNGRADE / MEANINGFUL_UPGRADE | same | 27.4 / 68.2 | NONE | unchanged |

## Known consequences reserved for SCORING-01b

- Crossing raw 40 upward inside a material conflict moves the verdict from MEANINGFUL DOWNGRADE straight to SIDEGRADE, skipping MINOR DOWNGRADE (the specified rule).
- A change from zero regeneration to some regeneration has no relative percentage and is therefore never material (unchanged behaviour).
- The legacy build-intel `pareto_status` still uses 0.5% sign counting and can read TRADEOFF for a non-conflict; it is internal and unchanged.
- The legacy Resource axis reports a percentage against a negative sustain baseline with an inverted sign (Case B shows "-2.6% Resource" for an improvement).
