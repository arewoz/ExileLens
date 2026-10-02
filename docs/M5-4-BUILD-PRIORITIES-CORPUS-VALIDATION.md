# M5.4 — Build Priorities Corpus Validation

Diagnosis only. No production code, threshold, ordering rule, probe or score was changed. Raw data (generated locally, not tracked in Git):
`artifacts/m5_4_priorities_validation.json`; harness: `scripts/m5_4_priorities_validation.py` (reuses the existing public corpus,
`Engine`, `analyze_build` and `rescore_analysis`; slots are skipped because Build Priorities only read the global probe stage).
Base: `main` @ `4795f4f`.

## Executive summary

* **18 of 21** public-corpus builds were run once each (216 PoB probe recalculations, about 197 s). Skipped as duplicate mechanics:
  `core04_weapon_swap` (same as poison), `core04_onehand_weapon` (Shield Wall, non-damage), `corpus02f_mortar_cannon` (same as ballista).
* Archetypes covered: spell/DoT/ignite casters, melee, ranged/projectile, grenade/ballista, totem, minion (Hound, Djinn), crit and
  low-crit, Life, ES, hybrid, Blood Mage, stat-stacking (Brutus Strength), ES-recovery, mana-based (Eldritch Battery), non-damage (Virtuous Barrier).
* **Overall: useful where the existing probes apply (spell builds, defence, resistance breakpoints), with two correctness gaps and one large
  coverage gap.** Strongest: spell builds get build-specific damage rows; attack builds correctly get none from spell stats; resistance
  breakpoints are exact and only emitted for real deficits; profile independence holds (4/4); score-based needs never leak.
  Weakest: (1) a ring carrier that cannot carry mods makes every probe `NO_SIGNAL` on 2 builds (a false "no response"); (2) `FIX FIRST: Mana
  sustain` fires on 12/18 builds, including a 13,303 mana/s deficit; (3) attack, crit, minion, ailment and attribute probes never reach the
  sensitivity profile, so 12/18 builds have an empty DAMAGE lane and there is no attribute multi-impact.
* Blockers: none for item verdicts (unchanged); the P0 items below should be fixed before Build Intelligence drives other features.

## Why attack / minion / attribute rows are missing (code-verified)

`catalog.stage2_ids()` (the global probes) is only Cast Speed, Spell Damage, Life, Energy Shield, Mana, four resistances, Movement
Speed and Spell Skill Levels. Attack Damage/Speed, Crit Chance/Multiplier, Projectile levels, Minion probes, Ignite/Poison, and
Strength/Dex/Int are catalogued but only run as per-slot probes, and `build_sensitivity` reads only `global_probes`. This holds for a
full analysis too, not just this harness.

## Coverage matrix

Lanes: DAMAGE / EHP / MAX HIT / MOVEMENT (Y = has rows, - = empty), then FIX FIRST (F) and MULTI-IMPACT (M). Probe dimensions available to
every build: spell offense, Life, ES, Mana, resistances, movement. Never available: attack, crit, minion, ailment, attribute, regeneration.
"Pool" is a rough label from the observed Life and ES values.

| Build | Class/Asc | Primary skill | Owner | Metric | Pool | Crit | Lanes |
|---|---|---|---|---|---|---|---|
| core04_bow_quiver | Ranger/Deadeye | Ice Shot | PLAYER | TotalDPS | Life+ES | crit | –YYY/F/– |
| core04_melee_weapon | Warrior/Warbringer | Sunder | PLAYER | TotalDPS | Life | crit | –YYY/F/– |
| core04_minion_actor | Witch/Infernalist | Summon Infernal Hound | MINION | Minion.CombinedDPS | Life+ES | n/a | –YYY/–/– |
| core04_mixed_hit_ailment | Witch/Infernalist | Comet | PLAYER | CombinedDPS | Life | crit | YYYY/F/– |
| core04_poison_ailment | Huntress/Ritualist | Poisonburst Arrow | PLAYER | PoisonDPS | ES | crit | –YYY/F/– |
| core04_skill_native_dot | Monk/Acolyte of Chayula | Profane Ritual | PLAYER | TotalDot | ES | crit | YYYY/F/– |
| core04_stage_context | Mercenary/Gemling Legionnaire | Flameblast | PLAYER | IgniteDPS | Life+ES | crit | YYYY/F/– |
| corpus02_giants_blood_shield | Mercenary/Gemling Legionnaire | Supercharged Slam | PLAYER | CombinedDPS | Life | crit | –YYY/F/– |
| corpus02b_varashta_djinn | Sorceress/Disciple of Varashta | Navira, the Last Mirage | MINION | Minion.CombinedDPS | ES | n/a | –YYY/F/– |
| corpus02c_stonefist_martial_artist | Monk/Martial Artist | Twister | PLAYER | CombinedDPS | Life+ES | crit | –YYY/F/– |
| corpus02d2_voltaic_barrier | Mercenary/Gemling Legionnaire | Virtuous Barrier | PLAYER | CombinedDPS | Life | non-crit | –YYY/F/– |
| corpus02e_spell_totem_titan | Warrior/Titan | Grim Pillars | PLAYER | TotalDPS | Life+ES | crit | ––––/F/– |
| corpus02f_ballista_warbringer | Warrior/Warbringer | Explosive Grenade | PLAYER | CombinedDPS | Life | crit | –YYY/–/– |
| corpus02g_dex_int_acolyte_hand_of_wisdom | Monk/Acolyte of Chayula | Fragments of the Past | PLAYER | TotalDPS | Life | crit | –YYY/F/M |
| corpus02g_strength_oracle_brutus | Druid/Oracle | Molten Blast | PLAYER | CombinedDPS | ES | crit | YYYY/F/– |
| corpus02h_eldritch_battery_shaman | Druid/Shaman | Spark | PLAYER | TotalDPS | Life | crit | ––––/F/– |
| life01_blood_mage_ember_fusillade | Witch/Blood Mage | Ember Fusillade | PLAYER | TotalDPS | Life | crit | YYYY/F/M |
| recovery02a_es_regen_invoker | None/None | n/a | PLAYER | CombinedDPS | ES | crit | YYYY/F/M |
Unavailable categories (no corpus build; none added): a dedicated non-crit attack build, a trigger-only build, a Life+ES hybrid with comparable pools, and a pure Mana-stacker without Eldritch Battery.

## Per-build results

Classification codes refer to the findings below.

#### core04_bow_quiver
Ice Shot · owner PLAYER · `TotalDPS` (PRIMARY_SKILL, HIGH) · Life 1724 / ES 3420 · crit 60.9894826944 · 13 recalcs, 17.1s
- FIX FIRST: Lightning Resistance +12% reaches cap [sensitivity]; Chaos Resistance +53% reaches cap [sensitivity]; Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: —
- EHP: +50 to maximum Energy Shield → +4.26%; +50 to maximum Life → +0.33%
- MAX HIT: +50 to maximum Energy Shield → +4.07%; +50 to maximum Life → +0.53%
- MOVEMENT: 10% increased Movement Speed → +5.50%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 6, 'NO_SIGNAL': 5}; NO_SIGNAL 5; empty lanes ['offense']
- Classification: MISSING_EXPECTED_SIGNAL (X1,X2); GOOD (G3,G8); PLAUSIBLE (P1); MISLEADING (M1)

#### core04_melee_weapon
Sunder · owner PLAYER · `TotalDPS` (PRIMARY_SKILL, HIGH) · Life 2629 / ES 0 · crit 5.0 · 12 recalcs, 13.2s
- FIX FIRST: Chaos Resistance +1% reaches cap [sensitivity]; Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: —
- EHP: +50 to maximum Life → +2.27%; +50 to maximum Energy Shield → +0.96%
- MAX HIT: +50 to maximum Life → +1.68%; +50 to maximum Energy Shield → +1.43%
- MOVEMENT: 10% increased Movement Speed → +6.89%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 5, 'NO_SIGNAL': 6}; NO_SIGNAL 6; empty lanes ['offense']
- Classification: MISSING_EXPECTED_SIGNAL (X1,X2); GOOD (G2,G7); MISLEADING (M1)

#### core04_minion_actor
Summon Infernal Hound · owner MINION · `Minion.CombinedDPS` (PRIMARY_SKILL, HIGH) · Life 1787 / ES 13114 · crit n/a · 11 recalcs, 11.6s
- FIX FIRST: —
- DAMAGE: —
- EHP: +50 to maximum Energy Shield → +2.24%; +50 to maximum Life → +0.70%
- MAX HIT: +50 to maximum Energy Shield → +2.12%; +50 to maximum Life → +0.58%
- MOVEMENT: 10% increased Movement Speed → +9.34%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 4, 'NO_SIGNAL': 7}; NO_SIGNAL 7; empty lanes ['offense']
- Classification: MISSING_EXPECTED_SIGNAL (X4); GOOD (G9)

#### core04_mixed_hit_ailment
Comet · owner PLAYER · `CombinedDPS` (STAT_SET_PART, HIGH) · Life 1047 / ES 308 · crit 88.53 · 12 recalcs, 14.9s
- FIX FIRST: Chaos Resistance +9% reaches cap [sensitivity]; Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: +1 to Level of all Spell Skills → +16.00%; 20% increased Spell Damage → +3.23%; 10% increased Cast Speed → +0.65%
- EHP: +50 to maximum Energy Shield → +7.04%; +50 to maximum Life → +1.93%
- MAX HIT: +50 to maximum Energy Shield → +3.29%; +50 to maximum Life → +0.68%
- MOVEMENT: 10% increased Movement Speed → +7.63%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 8, 'NO_SIGNAL': 3}; NO_SIGNAL 3; empty lanes none
- Classification: GOOD (G1); PLAUSIBLE (P1,P7); MISLEADING (M1); MISSING (X2)

#### core04_poison_ailment
Poisonburst Arrow · owner PLAYER · `PoisonDPS` (STAT_SET_PART, HIGH) · Life 296 / ES 5679 · crit 39.2235 · 11 recalcs, 11.3s
- FIX FIRST: Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: —
- EHP: +50 to maximum Energy Shield → +10.10%
- MAX HIT: +50 to maximum Energy Shield → +9.95%
- MOVEMENT: 10% increased Movement Speed → +10.97%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 4, 'NO_SIGNAL': 7}; NO_SIGNAL 7; empty lanes ['offense']
- Classification: MISSING_EXPECTED_SIGNAL (X1,X5); MISLEADING (M1)

#### core04_skill_native_dot
Profane Ritual · owner PLAYER · `TotalDot` (STAT_SET_PART, HIGH) · Life 1 / ES 10492 · crit 12.5 · 13 recalcs, 8.7s
- FIX FIRST: Lightning Resistance +5% reaches cap [sensitivity]; Chaos Resistance +56% reaches cap [sensitivity]; Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: 20% increased Spell Damage → +16.39%; +1 to Level of all Spell Skills → +15.93%
- EHP: +50 to maximum Energy Shield → +3.09%; +50 to maximum Mana → +0.37%
- MAX HIT: +50 to maximum Energy Shield → +3.04%; +50 to maximum Mana → +0.37%
- MOVEMENT: 10% increased Movement Speed → +7.46%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 8, 'NO_SIGNAL': 3}; NO_SIGNAL 3; empty lanes none
- Classification: GOOD (G1,G3); PLAUSIBLE (P1,P7); MISLEADING (M1)

#### core04_stage_context
Flameblast · owner PLAYER · `IgniteDPS` (STAT_SET_PART, HIGH) · Life 1748 / ES 13579 · crit 11.92 · 11 recalcs, 13.6s
- FIX FIRST: Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: +1 to Level of all Spell Skills → +31.81%; 20% increased Spell Damage → +5.82%
- EHP: +50 to maximum Energy Shield → +2.57%; +50 to maximum Life → +0.38%
- MAX HIT: +50 to maximum Energy Shield → +2.74%; +50 to maximum Life → +0.34%
- MOVEMENT: 10% increased Movement Speed → +7.14%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 6, 'NO_SIGNAL': 5}; NO_SIGNAL 5; empty lanes none
- Classification: GOOD (G1); MISSING (X5); MISLEADING (M1)

#### corpus02_giants_blood_shield
Supercharged Slam · owner PLAYER · `CombinedDPS` (STAT_SET_PART, HIGH) · Life 3277 / ES 458 · crit 5.0 · 12 recalcs, 12.5s
- FIX FIRST: Chaos Resistance +40% reaches cap [sensitivity]; Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: —
- EHP: +50 to maximum Life → +2.03%; +50 to maximum Energy Shield → +0.91%
- MAX HIT: +50 to maximum Life → +1.70%; +50 to maximum Energy Shield → +1.53%
- MOVEMENT: 10% increased Movement Speed → +6.99%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 5, 'NO_SIGNAL': 6}; NO_SIGNAL 6; empty lanes ['offense']
- Classification: MISSING_EXPECTED_SIGNAL (X1); GOOD (G2,G7); MISLEADING (M1)

#### corpus02b_varashta_djinn
Navira, the Last Mirage · owner MINION · `Minion.CombinedDPS` (PRIMARY_SKILL, HIGH) · Life 1 / ES 12298 · crit n/a · 12 recalcs, 26.2s
- FIX FIRST: Chaos Resistance +75% reaches cap [sensitivity]
- DAMAGE: —
- EHP: +50 to maximum Energy Shield → +2.29%
- MAX HIT: +50 to maximum Energy Shield → +2.22%
- MOVEMENT: 10% increased Movement Speed → +7.33%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 4, 'NO_SIGNAL': 7}; NO_SIGNAL 7; empty lanes ['offense']
- Classification: MISSING_EXPECTED_SIGNAL (X4); GOOD (G9); PLAUSIBLE (P1)

#### corpus02c_stonefist_martial_artist
Twister · owner PLAYER · `CombinedDPS` (STAT_SET_PART, HIGH) · Life 1603 / ES 9717 · crit 72.317091282975 · 11 recalcs, 13.2s
- FIX FIRST: Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: —
- EHP: +50 to maximum Energy Shield → +2.07%; +50 to maximum Life → +0.48%
- MAX HIT: +50 to maximum Energy Shield → +2.55%; +50 to maximum Life → +0.47%
- MOVEMENT: 10% increased Movement Speed → +9.38%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 4, 'NO_SIGNAL': 7}; NO_SIGNAL 7; empty lanes ['offense']
- Classification: MISSING_EXPECTED_SIGNAL (X1,X2); MISLEADING (M1)

#### corpus02d2_voltaic_barrier
Virtuous Barrier · owner PLAYER · `CombinedDPS` (PRIMARY_SKILL, LOW) · Life 2839 / ES 0 · crit 0.0 · 12 recalcs, 6.0s
- FIX FIRST: Chaos Resistance +75% reaches cap [sensitivity]
- DAMAGE: — (limited confidence)
- EHP: +50 to maximum Life → +2.20%; +50 to maximum Energy Shield → +1.40%
- MAX HIT: +50 to maximum Life → +2.00%; +50 to maximum Energy Shield → +1.28%
- MOVEMENT: 10% increased Movement Speed → +6.33%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 5, 'NO_SIGNAL': 6}; NO_SIGNAL 6; empty lanes ['offense']
- Classification: EXPECTED_UNSUPPORTED (U1); GOOD (G10); MISLEADING (M2)

#### corpus02e_spell_totem_titan
Grim Pillars · owner PLAYER · `TotalDPS` (PRIMARY_SKILL, HIGH) · Life 3991 / ES 803 · crit 53.64 · 11 recalcs, 10.0s
- FIX FIRST: Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: —
- EHP: —
- MAX HIT: —
- MOVEMENT: —
- MULTI-IMPACT: —
- Coverage: {'NO_SIGNAL': 11}; NO_SIGNAL 11; empty lanes ['offense', 'ehp', 'max_hit', 'mobility']
- Classification: ENGINE_OR_STATE_FAILURE (E2); MISLEADING (M1 by omission)

#### corpus02f_ballista_warbringer
Explosive Grenade · owner PLAYER · `CombinedDPS` (STAT_SET_PART, HIGH) · Life 2364 / ES 0 · crit 5.6 · 11 recalcs, 7.6s
- FIX FIRST: —
- DAMAGE: —
- EHP: +50 to maximum Life → +2.48%; +50 to maximum Energy Shield → +1.13%
- MAX HIT: +50 to maximum Life → +2.67%; +50 to maximum Energy Shield → +2.42%
- MOVEMENT: 10% increased Movement Speed → +8.66%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 4, 'NO_SIGNAL': 7}; NO_SIGNAL 7; empty lanes ['offense']
- Classification: MISSING_EXPECTED_SIGNAL (X1); GOOD (G7)

#### corpus02g_dex_int_acolyte_hand_of_wisdom
Fragments of the Past · owner PLAYER · `TotalDPS` (PRIMARY_SKILL, HIGH) · Life 2375 / ES 492 · crit 33.216 · 12 recalcs, 6.4s
- FIX FIRST: Chaos Resistance +85% reaches cap [sensitivity]
- DAMAGE: —
- EHP: +50 to maximum Mana → +1.06%; +50 to maximum Energy Shield → +0.94%; +50 to maximum Life → +0.37%
- MAX HIT: +50 to maximum Mana → +0.91%; +50 to maximum Energy Shield → +0.80%; +50 to maximum Life → +0.31%
- MOVEMENT: 10% increased Movement Speed → +5.35%
- MULTI-IMPACT: +50 to maximum Mana → EHP +1.06%, Max Hit +0.91%, Mana +1.42%
- Coverage: {'MEASURED': 5, 'NO_SIGNAL': 6}; NO_SIGNAL 6; empty lanes ['offense']
- Classification: MISSING (X1,X3); PLAUSIBLE (P4)

#### corpus02g_strength_oracle_brutus
Molten Blast · owner PLAYER · `CombinedDPS` (STAT_SET_PART, HIGH) · Life 1 / ES 11938 · crit 100.0 · 13 recalcs, 9.2s
- FIX FIRST: Lightning Resistance +25% reaches cap [sensitivity]; Chaos Resistance +76% reaches cap [sensitivity]; Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: 20% increased Spell Damage → +0.75%
- EHP: +50 to maximum Energy Shield → +5.35%
- MAX HIT: +50 to maximum Energy Shield → +5.22%
- MOVEMENT: 10% increased Movement Speed → +7.25%
- MULTI-IMPACT: —
- Coverage: {'MEASURED': 6, 'NO_SIGNAL': 5}; NO_SIGNAL 5; empty lanes none
- Classification: MISSING_EXPECTED_SIGNAL (X2,X3); PLAUSIBLE (P5); GOOD (G3); MISLEADING (M1)

#### corpus02h_eldritch_battery_shaman
Spark · owner PLAYER · `TotalDPS` (PRIMARY_SKILL, HIGH) · Life 1854 / ES 0 · crit 60.21 · 11 recalcs, 5.1s
- FIX FIRST: Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: —
- EHP: —
- MAX HIT: —
- MOVEMENT: —
- MULTI-IMPACT: —
- Coverage: {'NO_SIGNAL': 11}; NO_SIGNAL 11; empty lanes ['offense', 'ehp', 'max_hit', 'mobility']
- Classification: ENGINE_OR_STATE_FAILURE (E1); MISLEADING (M1: 13,303 mana/s deficit)

#### life01_blood_mage_ember_fusillade
Ember Fusillade · owner PLAYER · `TotalDPS` (PRIMARY_SKILL, HIGH) · Life 7436 / ES 0 · crit 99.3 · 14 recalcs, 4.9s
- FIX FIRST: Fire Resistance +75% reaches cap [audit]; Cold Resistance +75% reaches cap [audit]; Lightning Resistance +75% reaches cap [audit]; Mana sustain Current skill costs more mana per second than regeneration [audit]
- DAMAGE: +1 to Level of all Spell Skills → +13.58%; 10% increased Cast Speed → +5.07%; 20% increased Spell Damage → +2.33%
- EHP: +50 to maximum Life → +1.06%; +50 to maximum Energy Shield → +0.47%; +50 to maximum Mana → +0.47%
- MAX HIT: +50 to maximum Life → +1.06%; +50 to maximum Energy Shield → +0.47%; +50 to maximum Mana → +0.47%
- MOVEMENT: 10% increased Movement Speed → +7.25%
- MULTI-IMPACT: +50 to maximum Life → Damage +1.37%, EHP +1.06%, Max Hit +1.06%, Life +1.18%
- Coverage: {'MEASURED': 7, 'NO_SIGNAL': 4}; NO_SIGNAL 4; empty lanes none
- Classification: GOOD (G1,G6); ENGINE_OR_STATE_FAILURE (E3); MISLEADING (M1)

#### recovery02a_es_regen_invoker
n/a · owner PLAYER · `CombinedDPS` (STAT_SET_PART, HIGH) · Life 1 / ES 9284 · crit 66.672 · 14 recalcs, 5.8s
- FIX FIRST: Chaos Resistance +75% reaches cap [sensitivity]
- DAMAGE: +1 to Level of all Spell Skills → +28.89%; 10% increased Cast Speed → +13.51%; 20% increased Spell Damage → +8.63%
- EHP: +50 to maximum Energy Shield → +6.11%
- MAX HIT: +50 to maximum Energy Shield → +6.11%
- MOVEMENT: 10% increased Movement Speed → +18.62%
- MULTI-IMPACT: +50 to maximum Mana → Damage +1.01%, Mana +5.94%
- Coverage: {'MEASURED': 7, 'NO_SIGNAL': 4}; NO_SIGNAL 4; empty lanes none
- Classification: GOOD (G1,G8); PLAUSIBLE (P2,P4,P7); EXPECTED_UNSUPPORTED (U2)

## Findings

### Correct / useful (GOOD)
* **G1** Spell builds get build-specific damage rows: Comet (+1 spell level +16.0%, spell damage +3.2%), Profane Ritual (spell damage +16.4%, levels +15.9%),
  Flameblast (levels +31.8%), ES Invoker (levels +28.9%, cast speed +13.5%), Blood Mage (levels +13.6%, cast speed +5.1%).
* **G2** Attack/melee/minion builds get no spell rows: Cast Speed, Spell Damage and Spell Skill Levels are `NO_SIGNAL` on Bow, Sunder, Twister, Giants, Hound, Djinn, Ballista.
* **G3** Resistance breakpoints are exact (sensitivity-sourced) and only for real deficits: Bow lightning +12 and chaos +53, Brutus lightning +25, Profane lightning +5. Over-capped resistances never appear.
* **G4** Score-based `OFFENSE_OPPORTUNITY` / `MOVEMENT_OPPORTUNITY` needs existed on 5 builds and never entered FIX FIRST.
* **G5** Profile independence: priorities identical after a MAPPING rescore on Bow, Hound, Acolyte, Blood Mage (4/4).
* **G6** Blood Mage +50 Life is a genuine multi-impact (Damage +1.37%, EHP +1.06%, Life +1.18%).
* **G7** EHP and Max Hit differ where defences differ: Sunder EHP Life 2.27 / ES 0.96 vs Max Hit Life 1.68 / ES 1.43; Ballista Max Hit ES 2.42 vs EHP ES 1.13.
* **G8** Defence rows follow the build's layer: ES +4.26% EHP vs Life +0.33% on the ES-heavy bow; Life leads on Life builds.
* **G9** Minion ownership kept (Hound, Djinn): no fabricated player crit.
* **G10** Virtuous Barrier (damage 0): empty DAMAGE lane, nothing invented.

### Questionable presentation / order (PLAUSIBLE_BUT_NEEDS_REVIEW)
* **P1** `Chaos Resistance +N% reaches cap` is FIX FIRST on 10/18 builds, often +53 to +85 (Acolyte +85, Invoker +75): a real deficit but rarely actionable, listed at the same tier as a missing elemental cap.
* **P2** The MOVEMENT lane appears on 16/18 builds and shows the probe's own stat (+10% movement gives +5 to +19%): low information.
* **P3** EHP and Max Hit are near-duplicates on most builds (Bow ES 4.26 vs 4.07, Poison ES 10.1 vs 9.95); the split only informs where defences differ (G7).
* **P4** Acolyte EHP lane ranks +50 Mana (1.06%) above +50 ES (0.94%), and its MULTI-IMPACT row is Mana (Mana +1.42%, EHP +1.06%): mostly the stat's own pool.
* **P5** Brutus (Molten Blast, Strength 1782 over requirement, crit 100%) has one DAMAGE row, Spell Damage +0.75%, while its real scaling is unmeasured.
* **P7** Skill-level rows (confidence MEDIUM) top damage lanes with the largest numbers; the tested increment (+1 level) is shown but is not comparable with percent stats.

### Misleading
* **M1** `FIX FIRST: Mana sustain` on 12/18 builds. It comes from ManaPerSecondCost > ManaRegenRecovery in the audit and ignores leech, flasks and ES or Life payment: Eldritch Battery shows a 13,302.9 mana/s deficit, Blood Mage 395/s, Bow 205/s. It crowds out real fixes.
* **M2** Virtuous Barrier: its Life/ES/Movement rows are all labelled LOW confidence only because primary offense is low-confidence (M5.2 caps any signal that carries an offense axis, even at 0%).

### Missing signals (MISSING_EXPECTED_SIGNAL)
* **X1** No attack/projectile probes in the sensitivity profile: DAMAGE empty on Bow, Sunder, Poisonburst, Twister, Giants, Ballista, Acolyte, Hound, Djinn, Barrier, Titan, Shaman (12/18).
* **X2** No crit probes although crit is present on 17/18 builds (Brutus 100%, Blood Mage 99%, Comet 89%, Bow 61%).
* **X3** No attribute probes: no attribute multi-impact (Brutus Strength 1782 over requirement, Acolyte Int +1330).
* **X4** No minion probes: Hound and Djinn damage lanes empty.
* **X5** No ailment/DoT magnitude probes: PoisonDPS (Poisonburst) and IgniteDPS (Flameblast) offense unexplained.

### Unsupported mechanics (EXPECTED_UNSUPPORTED)
* **U1** Non-damage primary skill (Virtuous Barrier): offense unmeasurable by design.
* **U2** Life/ES/mana regeneration response is not captured (`axes_not_captured` on every build); ES-recovery builds (Invoker) cannot show it.

### Technical failures (ENGINE_OR_STATE_FAILURE)
* **E1** `corpus02h_eldritch_battery_shaman` (Spark, 2.56M DPS): all 11 probes `NO_SIGNAL`, including Life +50 at 1854 Life. The analysis carrier is Ring 1, the unique Kalandra's Touch ("Reflects opposite Ring"); a direct `evaluate_candidate` with `+50 to maximum Life` appended leaves Life, EHP and DPS unchanged. The probe never applied, yet it is reported as `NO_SIGNAL` ("no measured response") rather than not established.
* **E2** `corpus02e_spell_totem_titan` (Grim Pillars): same carrier, same result (11/11 `NO_SIGNAL`, all lanes empty).
* **E3** `life01_blood_mage_ember_fusillade`: Fire/Cold/Lightning resistance are 0% and `+20% to Fire Resistance` on the Snakepit carrier changes nothing (`NO_SIGNAL`), while Life probes apply. FIX FIRST shows `+75% reaches cap` from the audit, not a measured breakpoint. Cause not diagnosed; the resistance probes should not be treated as established.

No `REJECTED`, `UNSUPPORTED`, `RESTORE_FAILED` or `INVALID` status occurred on any build, so the NO_SIGNAL vs not-established distinction is exercised in one direction only, and E1/E2 show a case where `NO_SIGNAL` hides "not applicable".

## Quantitative summary

| Metric | Value |
|---|---|
| Builds tested | 18 (216 recalcs, about 197 s, 0 harness errors) |
| Builds with a non-empty DAMAGE, EHP or MAX HIT lane | 16 (the 2 empty ones are E1/E2) |
| Empty DAMAGE / EHP / MAX HIT lanes | 12 / 2 / 2 |
| Empty MOVEMENT lane | 2 |
| Builds with FIX FIRST / with MULTI-IMPACT | 16 / 3 |
| FIX FIRST containing Mana sustain / Chaos resistance | 12 / 10 |
| Signals MEASURED / NO_SIGNAL / not established | 88 / 110 / 0 |
| Profile-independence checks | 4 of 4 identical |
| Findings GOOD / PLAUSIBLE / MISLEADING / MISSING / EXPECTED_UNSUPPORTED / ENGINE_OR_STATE | 10 / 6 / 2 / 5 / 2 / 3 |

There is no single accuracy score; counts are of distinct findings, not rows.

## Recommended remediation backlog

**P0 — correctness / misleading**
1. Carrier selection (`pipeline._carrier`) can pick an item that ignores appended mods (Kalandra's Touch, E1/E2). A probe whose intervention provably did not apply must be reported as not established, not `NO_SIGNAL`, and another carrier should be tried.
2. `FIX FIRST: Mana sustain` (M1): 12/18 builds, 13,302.9 mana/s on Eldritch Battery. Do not present the audit's raw cost-vs-regen as a first-tier fix without a build-aware basis, or add context.

**P1 — meaningful usefulness gap**
3. Feed attack, crit, projectile, minion, ailment and attribute probes into the sensitivity profile (X1 to X5), for example by running the applicable catalog probes in the global stage.
4. M2: do not downgrade defence and movement signal confidence because offense is low-confidence.
5. Diagnose E3 (resistance probes inert at 0% on Blood Mage).

**P2 — polish / interpretation**
6. Chaos resistance tiering and wording (P1); collapse or hide near-identical EHP/Max Hit rows (P3); drop or reframe the MOVEMENT self-response lane (P2); treat own-pool Mana rows (P4); mark skill-level rows (MEDIUM) leading a lane (P7). P5 resolves with item 3.

**KNOWN UNSUPPORTED**
7. Non-damage primary skills (U1); regeneration axes (U2).

## Verdict

`M5 NEEDS TARGETED REMEDIATION`. The two P0 items are scoped fixes (carrier applicability, one fix-first rule), not a design flaw; P1 item 3 is the main value unlock.
