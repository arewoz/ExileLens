# CORPUS-02D1 — Poison and ailment Item Check

Branch `test/corpus-02d1-poison-ailment`, based on `origin/main` at `25558c7` (CORPUS-02C
follow-up, PR #47). Supported PoB 0.23.1.

**Result.** Poison Item Checks on the real poison fixtures are now complete PoB-measured
evaluations instead of blanket PARTIAL / UNCERTAIN results:

- **Poison fixture, 10 realistic candidates** (upgrades, downgrades, a trade-off, and
  duration, stack, chance and magnitude interactions): **0/10 → 10/10 FULL**. On
  `origin/main` every one was PARTIAL / UNCERTAIN with the same reason.
- **Real-hit variant** of the same build, 4 candidates: **0/4 → 4/4 FULL**.
- **Weapon-swap poison build:** the score now uses the real poison damage (+20.70%)
  instead of a figure inflated by PoB's fake hit (+26.94%).

Uncertainty remains only where a specific piece of evidence is missing:

- the stack count is fixed by the build's configuration;
- ignite or bleed scope is unverified;
- a real hit and the scored ailment move in opposite directions.

PoB performs every calculation. ExileLens only chooses which PoB outputs to compare and
checks that they are consistent.

## 1. Why poison comparisons were PARTIAL / UNCERTAIN

Traced on `core04_poison_ailment.xml` (Huntress/Ritualist, Poisonburst Arrow, "Poison
Burst" stat set) with the existing "+200% increased Physical Damage" bow candidate.

1. **The only quality reason** was `OFFENSE_MECHANICS_PARTIAL` ("some build mechanics
   are not fully measured"). PoB measured the change itself exactly: PoisonDPS
   793,727 → 1,226,922 (+54.58%), `delta_kind = MEASURED`.
2. **Where it came from:** `offense_coverage._classify_from_probes` set every
   `AILMENT_DPS` audit to `state = PARTIAL`, `offense_trustworthy = False` with the reason
   "full build/stage/stack scope unproven". It did this **unconditionally**: the audit's
   own probes had all passed:

   | Probe | Result |
   | --- | --- |
   | Attack speed | +15.37% |
   | Projectile levels | +10.36% |
   | Poison duration | +24.15% |
   | Spell-damage control | 0.00% |

   `build_damage_claim` turned that into `whole_build_status = PARTIAL`, and
   `assess_quality` turned that into PARTIAL / UNCERTAIN. Nothing specific was missing;
   the rule never tested what "stack scope" would require.
3. **Misread bridge fields:** the bridge asked PoB for `PoisonChance`, `PoisonStacks`,
   `MaxPoisonStacks` and `PoisonApplicationRate`. PoB2 never writes those. It writes
   `PoisonChancePerHit`, `PoisonStacksMax`, `PoisonStackPotential`,
   `PoisonMagnitudeEffect`, `PoisonRollAverage` and `PoisonEffMult`, so the stack,
   chance and magnitude evidence never reached ExileLens.
4. **Fake hit:** the Poison Burst stat set carries the game-data stat
   `display_statset_no_hit_damage`, plus `display_fake_attack_hit_poison`, which PoB maps
   to a 100% poison chance. PoB still reports a `TotalDPS` (101,952 here) for the fake
   hit it uses to size the poison, and `CombinedDPS` adds it.
   - **Poison fixture:** poison dominates, so the resolver happened to pick PoisonDPS.
   - **Weapon-swap fixture** (same skill, a weaker bow): fake hit 12,381 > poison 8,931,
     so the resolver picked `CombinedDPS` and scored PoB's fake hit as damage.
5. **Hidden audit bug:** on the weapon-swap build the audit's probe carrier was Ring 1,
   Kalandra's Touch ("Reflects opposite Ring"). PoB ignores lines added to that ring, so
   every probe was an exact no-op. This never surfaced because that build was never
   audited: it scored `CombinedDPS`.

## 2. Which PoB measurements are independent

From PoB2 `CalcOffence.lua`:

- **`calcDamagingAilmentOutputs`:**
  `<Ailment>DPS = per-application DPS × effect × rate × min(stacks, max stacks) × enemy mitigation`
  - `stacks = hit chance × ailment chance × duration × hit rate`, unless the enemy config
    `Multiplier:<Ailment>Stacks` ("# of Poisons on enemy") overrides it.
  - The roll average shifts upward once stack potential exceeds 1.
- **"Calculate combined DPS estimate":**
  `CombinedDPS = (TotalDPS + ImpaleDPS + mirage + TotalDotDPS) × cull × reservation`
  - `TotalDotDPS` = skill `TotalDot` + each ailment DPS + caustic/burning ground.

| PoB output | Classification | Treatment |
| --- | --- | --- |
| `TotalDPS`, `PoisonDPS`, `IgniteDPS`, `BleedDPS`, `TotalDot`, ground DPS, `ImpaleDPS` | additive damage streams of `CombinedDPS` | scored stream, `ADDITIVE`, or `EXCLUDED_NO_HIT_DAMAGE` for a fake hit |
| `<Ailment>Duration`, `ChancePerHit`, `StackPotential`, `StacksMax`, `MagnitudeEffect`, `RollAverage`, `EffMult`, skill speed | already multiplied into `<Ailment>DPS` | `INCORPORATED` factors: explain a change, never added |
| `<Ailment>Damage` (= DPS × duration) | a different quantity (damage of the whole active set) | `DERIVED`, never added to DPS |

The composition check reconciles `CombinedDPS` with those streams on both sides of every
comparison.

- **Poison fixture:** residual 0.0 (baseline) and −4e-8 (candidate).
- **Mirage builds:** composition is reported as `NOT_ASSESSED`.

## 3. Changes

### Bridge (`runtime/lua/bridge.lua`)

- **Ailment fields:** the ailment field list now includes PoB2's real outputs:
  - `ChancePerHit`, `StacksMax`, `StackPotential`, `MagnitudeEffect`, `RollAverage` and
    `EffMult` for poison, ignite and bleed;
  - `CausticGroundDPS`, `BurningGroundDPS`, `ImpaleDPS` and `MirageDPS`;
  - `CullMultiplier` and `ReservationDpsMultiplier`.

  The legacy names stay listed. These fields also join the exact-restore comparison.
- **Identity flag:** the skill identity carries `stat_set_no_hit_damage`, read from the
  selected stat set's own stats.

### Primary quantity (`items/primary_metric.py`)

- **No-hit stat set:** the dominant ailment output is primary even when the fake hit is
  larger.
- **Material real hit:** a stat set whose real hit is ≥ 15% of `CombinedDPS` is compared
  on PoB's `CombinedDPS` (`HIT_PLUS_AILMENT`). 15% is the resolver's existing
  "negligible DoT" bound.
- **Otherwise:** the established ailment-dominant rule is unchanged.

Skill, actor, damage owner and calculation context are never changed. The stat set is
read, never selected.

### Poison audit (`items/offense_coverage.py`)

An ailment audit is `FULL` / trustworthy only when all of the following hold:

1. the ailment-specific **stack-scope probe** (`POISON_DURATION`) is responsive, which
   proves PoB derives the stacks;
2. a **hit-rate/damage probe** is responsive;
3. the **actor control** did not move the output.

Otherwise the audit names the missing evidence in `scope_gap` and shows it as the quality
reason:

| Gap | Condition |
| --- | --- |
| `AILMENT_STACK_SCOPE_UNPROVEN` | Stacks fixed by configuration |
| `AILMENT_SCOPE_UNVERIFIED` | Ignite or bleed; no verified proof exists yet |
| `AILMENT_RESPONSE_UNVERIFIED` | Probes unresponsive or the control leaked |

**Carrier fix:** if every probe is an exact no-op, the carrier is checked with a
movement-speed line. An inert carrier (Kalandra's Touch) is skipped for the next equipped
item. Cache version: 1 → 2.

### Breakdown and guard

- **`items/ailment_intel.py`:** adds `ailment_breakdown` to each comparison. It contains
  the streams with roles, the incorporated factors, the ailment total damage, the
  composition status, and the hit/ailment deltas.
- **`evaluation_outcome.assess_quality`:** if the scored ailment and a material real hit
  move in opposite directions (possible only when the candidate crosses the 15% share),
  the comparison is PARTIAL (`AILMENT_HIT_COMPONENTS_DISAGREE`). This reason is added to
  the error catalog.
- **`build_intel/thresholds.py`:** a main skill that can no longer be used leaves PoB's
  `PoisonDPS` absent and `CombinedDPS` at 0. That is now the same `MAIN_SKILL_INVALID`
  collapse. Without this fix the weapon-swap "spear replaces bow" sentinel lost its
  `NOT_VIABLE` once the fake hit stopped being scored.

No scoring weights, thresholds or verdict policy changed.

## 4. Real-build verification

**Fixtures:** the existing `core04_poison_ailment.xml` and `core04_weapon_swap.xml`. Edited
copies (written to `tmp_path`) cover two mechanics the corpus lacked:

- the really-hitting **"Arrow"** stat set of the same build;
- a configured **"# of Poisons on enemy" = 3**.

No new authentic build was needed: these are the missing mechanics, and they are
isolated edits of an authentic build. Every number below equals an independent cold PoB
load of the edited build (`tests/integration/test_corpus02d1_poison_ailment.py`).

| Candidate (poison fixture) | PoB change | Result |
| --- | --- | --- |
| Quiver + 40% increased Magnitude of Poison | PoisonDPS +9.24% (magnitude effect 9.526 → 10.406) | FULL / MEANINGFUL_UPGRADE |
| Quiver + 30% increased Poison Duration | duration +20%, stack potential 0.94 → 1.13, capped at 4 stacks: PoisonDPS +15.59% | FULL / MEANINGFUL_UPGRADE |
| Quiver + "+1 of your Poisons" | max stacks 4 → 5, stacks not capped: +0.00% | FULL / SIDEGRADE (measured zero) |
| Quiver + both | +20.00% | FULL / MEANINGFUL_UPGRADE |
| Quiver − "30% chance to Poison" | chance already 100% (fake hit): +0.00% | FULL / SIDEGRADE |
| Gloves − 14% attack speed | fewer active poisons: −11.48% | FULL / MEANINGFUL_DOWNGRADE |
| Gloves − 99% ES + 16% attack speed | offense +10.95%, EHP −10.83% | FULL / SIDEGRADE "Meaningful trade-off" |
| Bow − "+3 projectile levels" / amulet − levels + life | −13.47% | FULL / MEANINGFUL_DOWNGRADE |
| Bow + 200% physical (existing test) | +54.58% | FULL / MEANINGFUL_UPGRADE (was PARTIAL / UNCERTAIN) |

| Other build | Result |
| --- | --- |
| "Arrow" variant: quiver − poison chance + 60% bow damage | hit +12.43%, poison −42.02%, `CombinedDPS` −31.54%: FULL / MEANINGFUL_DOWNGRADE (was PARTIAL / UNCERTAIN, scoring poison only) |
| Configured 3 poisons, gloves − attack speed | duration probe INSENSITIVE: PARTIAL / UNCERTAIN, `AILMENT_STACK_SCOPE_UNPROVEN` |
| Weapon-swap quiver + 50% attack speed | Ring 1 (Kalandra's Touch) skipped, Ring 2 probed; PoisonDPS +20.70%: FULL / MEANINGFUL_UPGRADE |
| Weapon-swap spear replacing the bow | NOT_VIABLE ("The main skill can no longer be used"), unchanged from `origin/main` |

**Repeatability and restore:**

- Repeated evaluations give identical FULL results.
- After the transaction, the restored build's PoisonDPS, CombinedDPS, stack potential,
  magnitude effect and EHP equal the baseline exactly.
- Every comparison's restore passed.

**Not a defect:** "increased Damage with Poison" measures zero. PoB parses the line
(checked with `describe_item`), but PoE2 poison scales through hit damage and magnitude,
and PoB2 applies it that way. ExileLens faithfully reports that PoB measured no change.

## 5. Functional coverage

`docs/corpus_coverage/COVERAGE_REPORT.md` has a new section, **"Functional coverage
(separate from the headline metric)"**. The historical headline methodology is unchanged.
Verdict-level cases declare `FunctionalMeasurement`:

- `FULLY_MEASURED`
- `PARTIALLY_MEASURED`
- `EXPECTED_UNCERTAINTY`
- `UNSUPPORTED_MECHANIC`

Only `FULLY_MEASURED` counts. A drift test checks every declaration against the quality
its test body asserts; it caught one new test that had not asserted FULL.

**Poison and ailment cases on `origin/main`** (the same rules applied to its assertions):

| Case | Classification |
| --- | --- |
| POISON-AILMENT-OFFENSE | PARTIALLY_MEASURED |
| STAGE-IGNITE | PARTIALLY_MEASURED |
| MIXED-HIT-AILMENT | FULLY_MEASURED |
| SKILL-NATIVE-DOT | FULLY_MEASURED |

That is **2 of 4** fully measured, and poison-dominant was **0 of 1**.

**On this branch** (generated report):

- **Fully measured: 10/12 (83%)** classified cases (dot 10/12, ailment 9/11).
- **1 partially measured:** STAGE-CHANNEL-RELEASE-IGNITE.
- **1 expected uncertainty:** configured poison stacks.
- **Poison:** 8 of 9 poison cases are fully measured; the ninth is the deliberate
  configured-stack refusal.
- **Not yet classified:** 61 verdict-level cases outside this mechanic family are left
  unclassified and are reported as such, not guessed.

**Historical headline:** 109/109 → 118/118 supported. Its distribution changed as
follows: PASS 92 → 99, EXPECTED_UNCERTAIN 9 → 11, UNSUPPORTED 8 → 8.

## 6. Test results

- **Focused unit tests:** `tests/test_corpus02d1_ailment_intel.py` (15) and the
  coverage-report tests.
- **Default unit suite** (`itemcheck and not integration`): 389 passed.
- **Real-PoB gate** (run once after implementation via
  `scripts/generate_corpus_coverage_report.py`): every suite passed.

  | Suite | Result |
  | --- | --- |
  | build_corpus | 42 passed |
  | public_real_pob | 26 passed |
  | weapon-set contexts | 8 passed |
  | contextual placement | 3 passed |
  | contextual diagnostics | 2 passed |
  | effect enumeration | 5 passed |
  | CORPUS-02A | 6 passed |
  | CORPUS-02B | 7 passed |
  | CORPUS-02C | 37 passed |
  | CORPUS-02D1 | 7 passed |
  | policy units | 51 + 11 + 33 + 15 passed |

- **Engine tests outside the generator** (jewel, jewel restore, socket normalization):
  19 passed, 1 pre-existing intentional skip (no fixture with an empty allocated jewel
  socket).

## 7. Remaining concrete limitations

1. **Ignite and bleed are not fully measured.**
   - Ignite does not stack, and its selected-stage scope has no single-probe proof like
     poison's duration probe. It stays PARTIAL (`AILMENT_SCOPE_UNVERIFIED`), e.g.
     STAGE-CHANNEL-RELEASE-IGNITE.
   - Bleed has no audit probes at all.
2. **No authentic bleed-dominant build** is in the corpus, nor an authentic real-hit
   poison build. The real-hit case is an edited stat-set variant of an authentic build.
3. **Dominance-boundary crossings.**
   - When a candidate moves a real hit across 15% of `CombinedDPS` against a falling
     ailment, the result is PARTIAL (`AILMENT_HIT_COMPONENTS_DISAGREE`).
   - When the dominant ailment flips between baseline and candidate, the result stays
     the existing `SEMANTIC_METRIC_CHANGED` (UNMEASURED).
4. **A configured poison-stack count** is refused specifically rather than measured,
   because PoB then ignores application rate and duration.
5. **Multi-source poison** (C14 Vine Arrow and C15 Gas Grenade in
   `POB_NATIVE_DAMAGE_POLICY.md`) and mirage composition are unchanged:
   `NOT_ASSESSED` / component-only.
6. **Unparsed candidate lines are not detected.** The bridge does not report candidate
   lines PoB could not parse, so a line PoB ignores would be a measured zero. This is
   general, not poison-specific.
