# M5.5 — Build Intelligence Remediation

Remediation of the five correctness/usefulness findings and the P2 list from `docs/M5-4-BUILD-PRIORITIES-CORPUS-VALIDATION.md`, revalidated
on the same 18 public-corpus builds. Evidence (generated locally by the harness, not tracked in Git; summarized in these reports): `artifacts/m5_4_priorities_validation.json` (before), `artifacts/m5_5_priorities_validation.json`
(after); `scripts/m5_5_compare.py` produces the comparison. Base: `main` @ `4795f4f`. Item Check scoring, verdicts, Build Value, SearchIntent and
`ProbeEngine` are unchanged.

## Summary

| Finding | Status |
|---|---|
| 1. False NO_SIGNAL from an inert carrier (Kalandra's Touch) | **FIXED** |
| 2. Mana sustain FIX FIRST noise (12/18 builds) | **FIXED** (moved to context; hard failure only) |
| 3. Attack / crit / minion / ailment / attribute probes missing from sensitivity | **FIXED** |
| 4. Defence confidence downgraded by low offense confidence | **FIXED** |
| 5. Blood Mage resistance probes inert | **FIXED** (root cause established; was VALID_AS_DESIGNED mechanics, FIX FIRST was wrong) |
| P2 chaos tiering / EHP vs Max Hit / movement lane / mana rows | **VALID_AS_DESIGNED** (no change, see below) |

## Finding 1 — false NO_SIGNAL

* **Evidence (M5.4 E1/E2):** Eldritch Battery Spark and Grim Pillars: 11/11 probes `NO_SIGNAL` (including +50 Life at 1854 Life).
* **Diagnosis:** the global carrier was the first equipped slot in a fixed order, Ring 1 = Kalandra's Touch. PoB rewrites that item from the opposite ring
  (`CalcSetup`: `item.name:match("Kalandra's Touch")`), so appended mod lines are discarded. The probe never applied but was recorded as "applied, no response".
  Cache keys do not include the slot, so this was a pure carrier problem, not ProbeEngine logic.
* **Change (`analysis/pipeline.py`):** a capability check, not a name check. `item_applies_probe_mods` runs one canary evaluation (+50 Life / ES / Mana
  appended) and requires restore to pass and Life, Energy Shield or Mana to rise. `_validated_carrier` takes the first equipped carrier that passes. If none does,
  every global probe is reported `REJECTED` with `error: PROBE_NOT_APPLIED` (not established, never NO_SIGNAL) and the skip reason is `carrier_ignores_probe_mods`.
  The slot stage runs the same canary before running a probe on a slot's item (global results are still reused). Sensitivity signals gain `applied`
  (`true` for MEASURED/NO_SIGNAL only).
* **Tests:** `test_m5_5_remediation.py` (capability detection, skipping an inert first carrier, no valid carrier → all REJECTED and coverage not-established, slot stage).
* **Before → after:** Spark and totem 0 measured / 11 NO_SIGNAL → 12 and 11 measured; builds with all signals NO_SIGNAL 2 → 0.
* **Other false-zero paths:** a resistance probe cannot distinguish "pinned" from "capped" on its own (handled in Finding 5); restore failures stay `RESTORE_FAILED`. Slot-stage
  probes that reuse a global result keep the existing `measured_on` semantics. No other path was found.

## Finding 2 — mana sustain

* **Evidence:** `FIX FIRST: Mana sustain` on 12/18 builds; Spark showed a 13,302.9 mana/s deficit.
* **Diagnosis (traced through PoB):** `ManaPerSecondCost = ManaCost × use speed` (`CalcOffence`: cost per use times cast/attack/trap/totem speed) assumes uninterrupted
  use at full speed, and the audit compares it with passive `ManaRegenRecovery` only. It excludes PoB's own `ManaLeechGainRate` (leech and on-hit), flasks and burst/idle
  patterns. Not a unit bug: it is a continuous-use assumption that nearly every working build exceeds (12/18); for Spark PoB reports 15,332/s (per use 2,746 at 3.1 uses/s plus its other per-second costs) against 2,029/s regeneration with a 13,316 pool. It is
  a description of full-speed drain, not an actionable problem, and no threshold separates them: pool-time-to-empty is 1 to 4 s on most builds.
* **Change:** the bridge now exports `ManaCost`, `ManaLeechGainRate` and `ESPerSecondCost`; the fingerprint records per-use cost, leech gain and the
  continuous-use deficit (recovery = regen + leech). Build Priorities no longer turn the audit's `RESOURCE_PRESSURE` into FIX FIRST (the audit need itself, and therefore
  SearchIntent, is unchanged). FIX FIRST now states a hard fact only: `Mana pool` when unreserved mana is smaller than one use of the main skill. The full-speed deficit is kept as
  `resource_context.mana` (deficit/s, seconds to empty, whether leech was counted, the assumption) and is not rendered as a fix.
* **Tests:** the M5.4 false positive (13,303/s, pool 13,316), a genuine pool below one use, a leech-covered stable build, a no-cost build.
* **Before → after:** builds with Mana in FIX FIRST 12 → 0. Legitimate detection is preserved for the hard case; the corpus contains no build that cannot afford one use.

## Finding 3 — global probe families

* **Evidence:** DAMAGE lane empty on 12/18 builds; no crit, attack, minion, ailment or attribute probes in sensitivity.
* **Diagnosis:** `catalog.stage2_ids()` listed 11 probes; the other 17 catalogued probes ran only per slot, and `build_sensitivity` reads only the global stage.
* **Change (`catalog.global_ids`, pipeline global loop):** reuse the existing definitions and canonical increments. Always added: Attack Damage, Attack Speed, Projectile Skill
  Levels, Strength, Dexterity, Intelligence. Gated by observed PoB facts only (cost control, not value judgement): Crit Chance and Crit Damage Bonus when crit chance > 0; the four Minion
  probes when the offense owner is MINION; Ignite Magnitude when IgniteDPS > 0; Poison Magnitude and Duration when PoisonDPS > 0. The measurement alone decides the signal, so spell probes on
  attack builds stay NO_SIGNAL and no spell row is invented. Slot-stage reuse already de-duplicates equivalent default-magnitude results.
* **Tests:** `test_global_probe_set_covers_attack_attribute_and_gates_the_rest_on_observed_facts`, attribute multi-axis priority test.
* **Before → after:** builds with a DAMAGE lane 6 → 17 (the 18th is the non-damage Virtuous Barrier, correctly empty); builds with MULTI-IMPACT 3 → 6; the attribute probes now yield genuine
  rows (Brutus +20 Strength: Damage +4.21%, EHP +1.54%, Max Hit +1.47%, ES +1.50%); minion builds get Minion Skill Levels/Damage/Attack Speed rows; Poisonburst gets Poison Duration +24%.

## Finding 4 — axis-aware confidence

* **Diagnosis:** `build_sensitivity` capped the whole signal to LOW whenever it had an offense axis (even at 0%), so Virtuous Barrier's EHP/Max Hit/Movement rows read LOW.
* **Change:** the cap now applies to `response.offense.confidence` only; signal and defence rows keep the probe's own confidence; offense lane rows read the offense axis confidence.
* **Test:** defence rows HIGH and offense axis LOW on a low-confidence-offense build.
* **Before → after:** Voltaic Barrier EHP/Max Hit/Movement rows LOW → HIGH; its offense lane remains empty and flagged limited confidence.

## Finding 5 — Blood Mage resistances

* **Investigation:** direct `evaluate_candidate` on Ring 1, Ring 2, Amulet and Belt: `+50 Life` works on all four, `+20% to Fire Resistance` and `+20% to all Elemental Resistances` change nothing
  on any of them (so not carrier, loadout or extraction), while a normal build (Sunder) moves `FireResistTotal` 89 → 109. Baseline `FireResist`/`FireResistTotal` are 0 with `FireResistMax` 75.
* **Root cause:** the build wears an item with the line `You have no Elemental Resistances` (fixture line 595); PoB parses it as `FireResist/ColdResist/LightningResist OVERRIDE 0` (`ModParser`). Resistances are pinned at 0, so the
  probes are genuinely inert and the audit's "+75% reaches cap" was unactionable, not a PoB or probe defect.
* **Change:** sensitivity records `own_resistance_delta` for applied resistance NO_SIGNAL probes; Build Priorities treat a below-cap element whose applied probe left its own resistance unchanged as pinned: it is not
  listed in FIX FIRST and appears in `coverage.resistance_pinned`. A capped element is never labelled pinned; a probe that was not applied (REJECTED) is never evidence of pinning.
* **Tests:** pinned vs real deficit vs capped vs not-applied.
* **Before → after:** Blood Mage FIX FIRST (3 unfixable resistances + mana) → none; coverage lists fire/cold/lightning as pinned.

## P2 review (after the upstream fixes)

* **Chaos resistance tiering — VALID_AS_DESIGNED.** Order and severity come from the audit's existing semantics (chaos `high`, elemental `critical`), so an elemental cap problem already precedes chaos; still shown on 10/18
  builds because the deficit is real. No new priority rule was invented.
* **EHP vs Max Hit near-duplicates — VALID_AS_DESIGNED.** They diverge where defences differ (Sunder, Ballista, Totem Titan ordering differs); identical rows only reflect identical measurements. No dedupe.
* **Movement lane — VALID_AS_DESIGNED.** Measured and present on 18/18; it is the build's response to the tested +10%, shown with its tested change. No dedicated-lane change.
* **Mana rows — preserved.** Mana EHP/Mana multi-axis rows are measured responses independent of sustain and are unchanged.

## Before / after

Same 18 builds, one run each. Lanes D/E/M/V/X = Damage, EHP, Max Hit, Movement, Multi-impact (letter = populated).

| Build | Lanes D/E/M/V/X before → after | FIX FIRST before → after | measured/no-signal/not-established | recalcs |
|---|---|---|---|---|
| core04_bow_quiver | -EMM- → OEMM- | Lightning Resistance, Chaos Resistance, Mana sustain → Lightning Resistance, Chaos Resistance | 6/5/0 → 13/6/0 | 13 → 22 |
| core04_melee_weapon | -EMM- → OEMM- | Chaos Resistance, Mana sustain → Chaos Resistance | 5/6/0 → 11/9/0 | 12 → 22 |
| core04_minion_actor | -EMM- → OEMM- | - → - | 4/7/0 → 9/12/0 | 11 → 22 |
| core04_mixed_hit_ailment | OEMM- → OEMM- | Chaos Resistance, Mana sustain → Chaos Resistance | 8/3/0 → 13/7/0 | 12 → 22 |
| core04_poison_ailment | -EMM- → OEMM- | Mana sustain → - | 4/7/0 → 12/10/0 | 11 → 23 |
| core04_skill_native_dot | OEMM- → OEMM- | Lightning Resistance, Chaos Resistance, Mana sustain → Lightning Resistance, Chaos Resistance | 8/3/0 → 9/10/0 | 13 → 22 |
| core04_stage_context | OEMM- → OEMM- | Mana sustain → - | 6/5/0 → 11/9/0 | 11 → 21 |
| corpus02_giants_blood_shield | -EMM- → OEMM- | Chaos Resistance, Mana sustain → Chaos Resistance | 5/6/0 → 12/8/0 | 12 → 22 |
| corpus02b_varashta_djinn | -EMM- → OEMM- | Chaos Resistance → Chaos Resistance | 4/7/0 → 7/14/0 | 12 → 23 |
| corpus02c_stonefist_martial_artist | -EMM- → OEMM- | Mana sustain → - | 4/7/0 → 12/8/0 | 11 → 21 |
| corpus02d2_voltaic_barrier | -EMM- → -EMM- | Chaos Resistance → Chaos Resistance | 5/6/0 → 7/10/0 | 12 → 19 |
| corpus02e_spell_totem_titan | ----- → OEMMM | Mana sustain → - | 0/11/0 → 11/8/0 | 11 → 21 |
| corpus02f_ballista_warbringer | -EMM- → OEMM- | - → - | 4/7/0 → 12/8/0 | 11 → 21 |
| corpus02g_dex_int_acolyte_hand_of_wisdom | -EMMM → OEMMM | Chaos Resistance → Chaos Resistance | 5/6/0 → 13/6/0 | 12 → 21 |
| corpus02g_strength_oracle_brutus | OEMM- → OEMMM | Lightning Resistance, Chaos Resistance, Mana sustain → Lightning Resistance, Chaos Resistance | 6/5/0 → 13/7/0 | 13 → 23 |
| corpus02h_eldritch_battery_shaman | ----- → OEMMM | Mana sustain → - | 0/11/0 → 12/7/0 | 11 → 21 |
| life01_blood_mage_ember_fusillade | OEMMM → OEMMM | Fire Resistance, Cold Resistance, Lightning Resistance, Mana sustain → - | 7/4/0 → 12/7/0 | 14 → 23 |
| recovery02a_es_regen_invoker | OEMMM → OEMMM | Chaos Resistance → Chaos Resistance | 7/4/0 → 12/8/0 | 14 → 24 |

- builds with non-empty DAMAGE: 6 → 17
- non-empty EHP: 16 → 18
- non-empty MAX HIT: 16 → 18
- non-empty MOVEMENT: 16 → 18
- with FIX FIRST: 16 → 10
- with MULTI-IMPACT: 3 → 6
- FIX FIRST containing mana: 12 → 0
- FIX FIRST containing chaos: 10 → 10
- MEASURED signals: 88 → 201
- NO_SIGNAL signals: 110 → 154
- not established: 0 → 0
- PoB recalculations: 216 → 393
- builds where all signals NO_SIGNAL: 2 → 0
- profile checks: [('core04_bow_quiver', True), ('core04_minion_actor', True), ('corpus02g_dex_int_acolyte_hand_of_wisdom', True), ('life01_blood_mage_ember_fusillade', True)]

## Quantitative comparison (M5.4 → M5.5)

| Metric | M5.4 | M5.5 |
|---|---|---|
| Builds with a DAMAGE lane | 6 | 17 (the 18th is non-damage Virtuous Barrier) |
| Non-empty EHP / Max Hit / Movement lanes | 16 / 16 / 16 | 18 / 18 / 18 |
| Builds with FIX FIRST | 16 | 10 |
| FIX FIRST containing Mana / Chaos | 12 / 10 | 0 / 10 |
| Builds with MULTI-IMPACT | 3 | 6 |
| Signals MEASURED / NO_SIGNAL / not established | 88 / 110 / 0 | 201 / 154 / 0 |
| Builds where every signal is NO_SIGNAL | 2 | 0 |
| Profile-independence checks (4 builds) | 4 of 4 | 4 of 4 |
| Harness errors | 0 | 0 |
| PoB recalculations | 216 | 393 (+82%) |

Recalculation increase (+177): six always-on probes (Attack Damage/Speed, Projectile levels, Str/Dex/Int) 108; Crit Chance and Crit Damage Bonus on 15 builds 30; Ignite 9; Minion probes 8; Poison 2; the carrier
canary 18 (one per build); exact-breakpoint and curve samples vary by build (+1). No obvious duplicate was found to remove; slot-stage reuse already avoids re-running default-magnitude probes. A full analysis also adds one canary per
equipped slot item that needs its own probes.

## Classifications

| | M5.4 | M5.5 |
|---|---|---|
| GOOD | 10 | 21 |
| PLAUSIBLE_BUT_NEEDS_REVIEW | 6 | 5 (P1 chaos, P2 movement, P3 EHP/Max Hit near-duplicates, P4 own-pool mana rows, P7 skill-level confidence) |
| MISLEADING | 2 | 0 |
| MISSING_EXPECTED_SIGNAL | 5 | 0 |
| EXPECTED_UNSUPPORTED | 2 | 2 (non-damage primary skill; regeneration response) |
| ENGINE_OR_STATE_FAILURE | 3 | 0 |

Re-classified GOOD (11): E1, E2, E3, M1, M2, X1 to X5, and P5 (Brutus now has Strength, Projectile levels and Crit Damage rows). Same 28-finding catalogue; counts re-derived by re-checking each against the M5.5 output. Attack/crit/minion/ailment/attribute rows are now build-specific (Brutus Strength, Hound Minion Skill Levels, Poisonburst Poison Duration), carrier fix, pinned resistance handling, mana noise removal, axis confidence.

## Truthfulness answers

* An unapplied probe can no longer become NO_SIGNAL on the global or slot-run path (`applied` flag, canary, REJECTED). No other false-zero path was found.
* Restore remains exact: the canary requires `restore.pass`, and all 18 builds ran with the existing restore verification.
* NO_SIGNAL (154) vs not established (0) are still separate; the corpus did not hit a not-established case after the fix (it is exercised by the no-valid-carrier regression).
* Blood Mage resistance behaviour is understood (item pinning resistances to 0).
* Resistance breakpoints are still exact (Bow +12, Brutus +25, Profane +5 from sensitivity); attribute requirement fixes are unchanged (no corpus build has a deficit).
* Nothing increased confident output by hiding a failure: FIX FIRST shrank only where the audit claim was unactionable (mana, pinned resistance).

## Unresolved / limits

* Chaos resistance still leads FIX FIRST on 10/18 builds (valid deficit; presentation left).
* Life/ES/mana regeneration response is still not captured (known unsupported).
* Life-paid costs (Blood Mage 3,812 life/s) are not interpreted; only the mana resource was reviewed.
* Gating of crit/minion/ailment probes uses observed PoB output; a build with an unobserved fact never gets those probes in the global stage.

## Performance review

Where it runs: global sensitivity (and the canary) execute only inside `analyze_build`, i.e. the explicit **Analyze Build** action, asynchronously on the analysis scheduler
(yielding to gameplay checks), with results kept in the shared `ProbeCache` until the baseline changes. Normal Shift+C Item Check never calls it (`items/` imports only the
catalog/ProbeEngine, unchanged). Rescoring (`rescore_analysis`) is pure and runs no PoB. Single-slot callers (`analyze_slot`: market search, SearchIntent) now pass `build_intelligence=False` and keep the
original 11-probe global stage, so M5.5 adds nothing to them.

Benchmark (full `analyze_build`, real PoB, 6 builds incl. the Kalandra's Touch Spark; cold then repeat with the same cache):

| | main | M5.5 before reuse | M5.5 final |
|---|---|---|---|
| Cold recalcs, 6 builds | 223 | 272 (+22%) | about +8 per build (+22%) |
| Repeat-run recalcs per build | 8 | 16 | 8 |
| Item Check warm median (16 runs, alternating) | 0.87 to 0.94 s | n/a | 0.93 to 0.96 s (within noise) |

The full-analysis increase is far below the corpus +82% because the slot stage already ran every catalog probe per slot and reuses default-magnitude global results; the new global
probes mostly replace slot-stage runs. The remaining +8 cold recalcs are the new global families and the canary. Optimizations: carrier validity is cached in `ProbeCache` by baseline identity
(fingerprint, build, loadout, item set, context, generation) + slot + item text, cleared on invalidation, never cached for engine errors or restore failures (repeat analysis +8 to +0); single-slot
callers skip Build Intelligence. Probe gating was not loosened.
