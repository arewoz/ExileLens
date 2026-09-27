# CORPUS-02C — Way of the Stonefist Item Check support

Branch `test/corpus-02c-stonefist`, based on `origin/main` at `be634ca` (CORPUS-02B, PR #43).

**Result.** Ordinary glove candidates on a Way of the Stonefist build are evaluated as
the Fists of Stone item the character would equip. ExileLens builds that transformed
item in memory from PoB's own game data; PoB calculates every statistic.

- **Exact evaluation** applies when every modifier transforms to a fixed value and the
  displayed lines fit exactly one modifier combination.
- **Verified range evaluation** applies when the transformed item is not unique:
  - the game rolls a transformed value on equip (§1), or
  - the displayed lines fit several modifier combinations.

  PoB measures every combination at its worst, middle and best rolls. A verdict is
  reported only when it holds in every case, together with the verified impact range.
- **Tested gloves:** 8 of the 10 real ordinary corpus gloves receive usable verdicts. The
  two remaining (a unique, and one item whose lines fit no modifier combination) stay
  explicitly UNSUPPORTED with the reason.

## 1. The mechanic and the evidence for each rule

Martial Artist notable "Way of the Stonefist" (node 39595): *"Gloves you equip have their
Base Type transformed to Fists of Stone while equipped, and their Explicit Modifiers are
transformed into more powerful related Modifiers. Ignore Attribute Requirements to equip
Gloves."*

Evidence sources:
- the supported PoB's data;
- raw GGG item data for **176 distinct real transformed gloves** from **45** public
  poe.ninja Runes of Aldur Stonefist characters, which include each modifier's game mod ID
  and raw stat values. Only item-level data was kept, never account or character names.

| Rule | Evidence |
| --- | --- |
| Explicit mod `<Id>` becomes `HandWraps<Id>`, tier for tier, same affix name | Every real transformed mod uses a `HandWraps…` ID. PoB's data pairs 410 of 411 `HandWraps` mods with a same-ID source, and every pair has the same affix name. Sources are split across PoB's `Item`, `Desecrated` (Abyss) and `Exclusive` tables. |
| Transformed values and ranges | All **589** real transformed stat values (80 distinct mod IDs) lie inside PoB's `HandWraps` ranges or equal its fixed values. |
| Base becomes Fists of Stone (+3 Evasion, +1 ES per level) or Runeforged Fists of Stone (+2 Evasion, +1 ES, +1 Runic Ward per level) | Every real item matches (89 plain, 87 Runeforged). A runic original (Runeforged/Runemastered) becomes Runeforged Fists of Stone. PoB flags runic items, and only the Runeforged variant carries Runic Ward. |
| Per-level values use the character's level | The game's level binding `local_hand_wraps_player_level_to_use` equals the character level on all 176 items. PoB scales by the build level. |
| Rune/enchant lines, quality, sockets and corruption are kept | Real exports keep their rune lines unchanged. |
| **A ranged transformed value is rolled independently of the original roll** | Fixed source "+2 to Level of all Melee Skills" → "(10-12)% to Quality of all Skills" observed at 10, 11 and 12. `CriticalMultiplier4` shows 23 distinct transformed values from a 5-value source. In total 5 tiers show more transformed values than their source can display. |

**Decomposition ambiguity is real.** For example, "42% increased Armour" plus "+191 to
maximum Life" fits both of these, which transform into different items:
- an Armour% prefix plus a Life T12 prefix;
- a hybrid Armour/Life prefix plus a Life T9 prefix.

**Consequence.** The actual transformed roll exists only once the gloves are equipped;
nothing in a copied ordinary item determines it. No exact pairs (the same item seen
before and after transformation) were found in any poe.ninja snapshot. They are not
needed for the value rule, because the rolls are independent anyway.

**Not used as evidence:**
- **Mobalytics' guide:** not readable from this environment (HTTP 403).
- **Community converters:** "datamined, verify in-game".

## 2. Implementation

Everything happens in memory; the user's PoB build is never modified.

**Bridge (`runtime/lua/bridge.lua`):**
- `get_item_transform_mods`: PoB's source → `HandWraps` mapping.
- `describe_item`: PoB's parse of an item by modifier category.
- `rebuild_item`: PoB re-emits the item with a new base and implicit/explicit lines.
- `get_base_implicits`.
- `item_base_transforms` in `build_info`.

**`items/stonefist.py`:**
- Decomposes the displayed explicit lines into their source modifiers, respecting one
  modifier per group and at most 3 prefixes and 3 suffixes.
- Handles lines the game merges (e.g. %ES plus a hybrid %ES/Life prefix shown as one
  line) and lines PoB lists separately (one modifier each).
- Fixed transformed values are exact.
- **Decompositions:**
  - those yielding the same transformed lines with different values (e.g. overlapping
    Adds Physical tiers 6 and 7) merge into wider bounds;
  - those yielding different lines become numbered **alternatives**, and each one is
    evaluated.
- An already-transformed item (`Fists of Stone` base) passes through untouched, so gloves
  are never transformed twice.

**`items/stonefist_rolls.py`:** bound rules put every ranged transformed value at its
worst end, at a displayable middle roll, or at its best end. Lines that are worse when
larger ("…% slower") are inverted. The rules never use the source roll, since the game
rolls independently.

**`items/evaluation.py`:**
- **Exact candidates:** the transformed item is measured once.
- **Roll-dependent or ambiguous candidates:** PoB measures every alternative (at most 4)
  at its worst, middle and best configurations. The result is reported only if both
  conditions hold:
  1. **each alternative's scored PoB outputs are ordered worst ≤ middle ≤ best** (primary
     damage, EHP, Life/ES/Mana, Evasion/Armour/Ward, the four resistances, block and
     maximum-hit values), which shows the outcome is monotone in the rolls, so these
     configurations bound every other roll;
  2. **every measured configuration gives the same public verdict with the same verdict
     structure**: impact pattern, per-axis direction and significance, applied
     guardrails and quality (see §7).
- Otherwise the comparison is UNSUPPORTED with the reason: the verdict changes, the
  results are not ordered, or there are too many alternatives.
- **Reported numbers are a verified range over all configurations:**
  - the `[range x% to y%]` label on impact rows;
  - a `STONEFIST_ROLL_DEPENDENT` disclosure;
  - a summary such as "…Twister −9.9% to −6.0%; EHP −37.3% to −26.5%: a downgrade in every
    at each measured roll; rolls in between were not measured individually". The summary
    states only what PoB measured.

  The detail rows show the lowest-damage configuration, labelled with the full range.
- **Ordinary equipped gloves** (a hand-built PoB) are transformed exactly and passed as a
  `baseline_overrides` item, so every slot's check uses the in-game baseline. The
  transaction restores the true build.

**The UNSUPPORTED guard** (`ITEM_TRANSFORM_UNMODELED`) remains only for genuinely
unresolved cases, and names the reason.

No scoring weights or verdict policy changed.

## 3. Verified results (supported PoB 0.23.1, real Stonefist fixture)

| Candidate | Evaluation | Result |
| --- | --- | --- |
| Ordinary glove, fixed-value modifiers (ES, Life, life on kill) | exact | FULL, matches the hand-transformed reference (level 100 and level 70) |
| Exported Fists of Stone gloves, as candidate and baseline | exact, not re-transformed | SIDEGRADE, zero delta, metrics equal the export |
| Fists of Stone vs Fists of Stone (export minus a line) | exact | FULL / MEANINGFUL_DOWNGRADE |
| Hand-built baseline with ordinary gloves, amulet candidate | exact baseline transform | Baseline and candidate equal reference loads; the user's build is unchanged |
| Better ordinary glove on that hand-built baseline | roll-dependent | MEANINGFUL_UPGRADE, "an upgrade in every case": Twister +14.6% to +17.3%, endpoints equal hand-transformed reference loads |
| Massive Mitts (Giant's Blood fixture) | roll-dependent | Worst/best runs equal hand-written worst/best reference items; verdict holds at every roll |
| Vaal Gloves; Secured Wraps; corrupted Secured Wraps; Massive Mitts; Sirenscale Gloves (separate same-stat lines); Plate Gauntlets (overlapping tiers) | roll-dependent, 3 configurations each | All FULL / MEANINGFUL_DOWNGRADE in every case, restore exact |
| Runeforged Massive Mitts | 2 decomposition alternatives × 3 rolls | FULL / MEANINGFUL_DOWNGRADE in all 6 configurations; DPS −9.9% to −6.0%, EHP −37.3% to −26.5% |
| Unique gloves (Layered Gauntlets) | unsupported | Game `HandWrapsUnique*` mods are missing from PoB's data |
| Djinn build's Vaal Gloves | unsupported | Lines fit no legal glove-modifier combination (e.g. "+65% to Cold Resistance" exceeds every tier with no second source) |

**Totals:**
- **Real ordinary corpus gloves:** 8 of 10 receive usable verdicts. All 8 are
  roll-dependent (one also has two decomposition alternatives).
- **Exact evaluations:** the exported gloves, the Fists of Stone variant, the fixed-value
  glove (at levels 100 and 70) and the hand-built baseline.
- **Guaranteed upgrade:** one real-PoB case.
- **Refusal path not needed:** every roll-dependent real case on this build gave an
  ordered range with one verdict. The verdict-spanning, disagreeing-middle,
  disagreeing-alternative and non-monotone refusals are covered by stubbed unit tests;
  no legal real candidate crossing a verdict boundary was found among those tried.

## 4. Upstream PoB PR #2350 (unchanged findings)

The PR is OPEN, unmerged, conflicting, unreviewed and based on PoB 0.22.0.
- It transforms already-transformed exported gloves again, which raised this character's
  baseline EHP by 12% in an isolated comparison.
- It uses averaged modifier values.

ExileLens does not depend on it. A PoB revision that starts parsing the passive trips the
detection tripwire test and must be re-validated before its behaviour is trusted.

## 5. Tests

- **`tests/integration/test_corpus02c_stonefist.py`:** 19 real-PoB tests.
  - Detection tripwire.
  - Transformed-vs-transformed comparison.
  - Exact fixed-value glove.
  - Double-transformation prevention.
  - Independent worst/best reference items.
  - Seven real ordinary gloves (one of them with two alternatives).
  - Deterministic repeat and restore.
  - Hand-built baseline.
  - Character level.
  - A guaranteed upgrade checked against references.
  - Two unresolvable gloves.
  - Non-glove scope.
- **`tests/test_stonefist_transform.py`:** 18 unit tests.
  - Fixed versus ranged targets.
  - Independent ranged modifiers and the "slower" inversion.
  - Merged and separate same-stat lines.
  - A merged line blocking only a source-dependent rule.
  - Overlapping tiers.
  - Impossible items.
  - Pass-through of transformed items.
  - Unique and runic bases.
  - Stubbed refusals: verdict spanning, middle disagreement, non-monotone results and
    disagreeing alternatives.
  - Guaranteed-range and union-range reporting.
  - Single evaluation of exact candidates.
- **`tests/test_item_transform_guard.py`:** 11 unit tests (guard scope and quality).
- **Solver bug found and fixed by these tests:** the partial-search pruning was inverted,
  which wrongly refused genuinely merged lines as "no combination".
  - **Consequence of the fix:** the solver then exposed the Runeforged Massive Mitts'
    second valid decomposition. That motivated alternatives: the earlier single-item FULL
    verdict for that glove had been unjustified.

## 6. Remaining limitations and missing data

- **Unique gloves.** *(Superseded by §10. The earlier claim that PoB's data lacks the
  `HandWrapsUnique…` modifiers was wrong: PoB 0.23.1 has 171 of them, in
  `ModItemExclusive.lua`. The bridge only looked in `ModItem.lua`.)* Unique gloves are now
  supported where real items evidence their modifiers; others stay refused (§10).
- **`HandWrapsEnergyShieldRechargeRate5`** *(fixed, §11)*: its source is
  `EnergyShieldRechargeRate5______`, with six trailing underscores in the game id.
- **Unmatched lines.** Gloves whose displayed lines fit no legal modifier combination are
  refused. The game data has no missing ordinary families (§11). The Djinn gloves'
  "+65% to Cold Resistance" is not reachable by any legal glove modifier.
- **Hand-built baselines with ranged or ambiguous transformed gloves.** The baseline must
  be exact, so it is not overridden; the glove slot is then guarded and other slots use
  PoB's untransformed baseline. Importing from the game (transformed export) avoids this.
- **"Ignore Attribute Requirements to equip Gloves"** is not modelled; it does not affect
  PoB's calculated statistics.
- **Monotonicity is checked, not assumed:** the ordering check runs over the scored
  outputs, and a PoB interaction outside those fields would not be detected by it.
  Single-roll probes (§12) add a per-roll check when affordable.
- **Cost:** a roll-dependent candidate costs 3 PoB evaluations per alternative (at most 4
  alternatives, i.e. 12), on Stonefist builds only. More than 4 alternatives are refused.

## 7. Correctness review (post-b98e90b)

**Confirmed defects, both fixed:**

1. **A verdict-agreement gap.** Matching verdicts at the sampled rolls did not prove
   intermediate rolls. `decide_verdict` is not order-preserving: a TRADEOFF pattern with no
   guardrail forces SIDEGRADE regardless of score. So SIDEGRADE at the worst roll (forced)
   and SIDEGRADE at the best roll (score band) can surround an intermediate roll that
   leaves the TRADEOFF pattern with a downgrade-band score. **Fix:** every measured
   configuration of an alternative must now also share the verdict structure (pattern,
   per-axis direction and significance, applied guardrail codes, quality). Stubbed
   regression: `test_same_verdict_reached_through_different_patterns_is_refused`.
2. **Hover latency of 19–50 s.** The earlier pruning fix had removed the solver's only
   upper-bound prune, so the search enumerated about 235,000 modifier subsets (7–14 s per
   PoB run), repeated for every configuration. **Fix:**
   - a sound upper-bound prune (the remaining gain per merged line is at most the sum,
     over modifier groups, of each group's largest remaining tier);
   - precomputed line data;
   - one decomposition per item shared by all roll configurations.

   Result: 7.1 s becomes 0.011 s, with identical solutions for all nine corpus gloves.

**Additional truthfulness fix:** on a hand-built PoB whose equipped ordinary gloves cannot
be transformed exactly, comparisons in other slots are PARTIAL / UNCERTAIN
(`STONEFIST_BASELINE_UNTRANSFORMED`) rather than confident. An item's effect can depend on
the unknown transformed gloves, and that dependence need not be monotone. Imported builds
(already transformed gloves) and exactly transformable gloves are unaffected.

**What is established, sampled, or needs evidence:**

- **Mathematically established, given assumption (A) below:**
  - For each alternative, the all-worst and all-best roll corners bound every roll
    configuration of every scored output.
  - With the verdict structure identical at the measured rolls, every intermediate roll
    has the same structure and the same score band. The score, guardrail thresholds and
    axis directions are monotone in those outputs; axis significance is sandwiched
    because both ends share it.
  - Displayed ranges are therefore true bounds.
- **Assumption (A):** each scored PoB output is monotone in each transformed roll, in the
  direction where a larger value is better for the character.
  - **Supported by:** static orientation of all 94 ranged `HandWraps` line types (every
    one strengthens the character when larger; the "Leech … slower" lines are inverted);
    and the worst ≤ middle ≤ best ordering check on the scored outputs.
  - **Not proven:** a PoB interaction that makes an output decrease in a beneficial stat,
    or an output outside the checked fields, would not be caught.
- **Empirically sampled:** the middle roll, as corroboration of (A) along the diagonal.
  Alternatives are discrete and are all measured.
- **Would need more evidence for full certainty:**
  - per-roll one-at-a-time PoB measurements to verify each roll's direction (k extra runs
    per alternative);
  - exhaustive corners (2^k runs) where (A) is in doubt.

  Both were not added because of their latency cost (below).

**Transactions:**
- Every configuration is a separate PoB transaction with verified restore. A deferred
  first restore is finalized before further runs; `finalize_transaction` is idempotent.
- Baseline overrides are applied per transaction and never persist.
- Tests cover repeated evaluation across alternatives, and the fingerprint and equipment
  after them.

**Performance (measured):**

| Case | Hover cost |
| --- | --- |
| Exact glove | ~0.9 s |
| Roll-dependent glove (3 runs) | ~4 s |
| Two alternatives (6 runs) | ~7 s |
| Worst case: 4 alternatives × 3 runs | ~14 s, estimated |

- Non-glove items and non-Stonefist builds are unaffected (one run).
- **Residual risk:** roll-dependent gloves exceed the 4 s "still working" hint. It is
  feedback, not cancellation. Batching configurations into one PoB transaction would be
  the next optimisation. *(Done: see §9.)*

## 8. Final pre-integration checks

- **UI wording:** summaries and labels state only what was measured: "[measured x% to y%]"
  and "the verdict was … at each measured roll; rolls in between were not measured
  individually". The range claim over unmeasured rolls rests on assumption (A) and is not
  presented as a guarantee.
- **Uncertain hand-built baseline:** non-glove recommendations against untransformed,
  inexactly transformable gloves are UNCERTAIN, as described above.

## 9. Batched configuration measurement

A PoB transaction costs three recalculation frames of ~250 ms each: baseline settle,
candidate, and restore. Profiling showed that the per-item pipeline (recognition,
metadata, parse, transform, offense coverage, components) was under 5% of a
roll-dependent hover. The PoB transactions were the cost, so they are what was batched.

**Design:**
- **One transaction per candidate.** Bridge `evaluate_item_variants` measures N item
  texts for the same slots in one transaction:
  - one baseline read;
  - one measurement frame per variant;
  - between measurements, a revert plus the same structural check used between the
    slots of `evaluate_item_slots`;
  - one `tx_finish` restore, verified against the true baseline.

  It is never deferred, and a `RESTORE_FAILED` always aborts the whole batch.
- **Evaluation split at the measurement.** `_evaluate_item_steps` is the unchanged item
  evaluation, split at its single measurement: it yields a `_MeasurementRequest` and
  receives the `evaluate_item_slots`-shaped result. `_evaluate_item_impl` drives it with
  one `evaluate_item_slots` call, so non-Stonefist, non-glove and exact glove items use
  exactly the previous path, deferred restore included.
- **Batched Stonefist configurations.** `_evaluate_with_stonefist_bounds` prepares every
  configuration (alternatives × worst/middle/best) up to its measurement, then measures
  them all in one batch.
  - Configurations are batched only when they share slots, context, component keys and
    baseline overrides; otherwise each is measured separately.
  - Each configuration receives its own variant's result and is scored by the ordinary
    evaluation code. Verdict-structure, ordering and agreement checks are unchanged.
  - A refusal still runs one normal evaluation of the untransformed item.
  - A failed batch goes to the first configuration's normal failure handling.
    `RestoreFailed` invalidates the build and raises `EvaluationInvalidBuildState`.
- **Restore check.** The post-restore fingerprint check (`get_metrics`) now runs whenever
  the restore actually ran, including for a deferred-requested evaluation measured in a
  batch.

**Measured** (median of 3 hovers; the same machine and session order for both;
`corpus02c_stonefist_martial_artist.xml`):

| Candidate | Configurations | Before (s) | After (s) | PoB transactions |
| --- | --- | --- | --- | --- |
| Fixed glove (exact) | 1 | 0.88 | 0.93 | 1 → 1 |
| Vaal Gloves | 3 | 2.73 | 1.45 | 3 → 1 |
| Plate gauntlets (overlap) | 3 | 2.68 | 1.32 | 3 → 1 |
| Runeforged mitts (2 alternatives) | 6 | 5.05 | 2.78 | 6 → 1 |
| Sirenscale | 3 | 2.87 | 1.57 | 3 → 1 |
| Giants mitts | 3 | 2.60 | 1.52 | 3 → 1 |

- **Same results:** for every candidate, before and after agree on verdict, quality,
  candidate metrics, disclosure notes, every measured range and the configuration count.
- **Worst case:** 12 configurations drop from 36 frames (~14 s) to 14 (~3.5 s, estimated).
- **Tests** (`tests/integration/test_corpus02c_stonefist.py`):
  - A batch measures, per variant, exactly the metrics and candidate fingerprint of a
    separate transaction.
  - A roll-dependent candidate uses exactly one transaction.
  - A corrupted batch restore raises `RestoreFailed` and forces a re-parse.

## 10. Unique gloves

**Evidence.** Real items from poe.ninja character data (Runes of Aldur, snapshot
2026-09-27). Only item fields were kept; no account or character identifiers were
stored. The set covers 32 unique gloves:

- 87 transformed instances, worn by Way of the Stonefist characters.
- 87 untransformed instances, worn by any character.

Each item carries the game's modifier ids.

**The rule, verified on all 231 untransformed/transformed pairs:**
- A unique glove is transformed like any other glove: base Fists of Stone (Runeforged for
  runic uniques, e.g. `RunicUnique` Dreadfist).
- Each modifier `X` becomes `HandWrapsX` when the game has that modifier. Otherwise it
  stays unchanged: e.g. `UnarmedStrikeRangeUnique1` and Atziri's `UniqueAtziriHeraldSkill1`.
- Six `HandWraps…` targets have no displayed stat, so the source line disappears. Example:
  Facebreaker loses "increased Stun Buildup".
- Ranged transformed values re-roll, e.g. Facebreaker's "+4 to +5" becomes "+3 to +5".
  They are bounded worst/middle/best exactly as for ordinary gloves.

**What PoB's data answers, and what it cannot:**
- PoB 0.23.1 has 199 of the game's 208 `HandWrapsUnique…` targets, with lines and ranges
  (171 in `ModItemExclusive.lua`, 28 Vaal-mutation targets in `ModItem.lua`).
  These were checked against the GGPK export: repoe-fork `mods.json`, 2026-09-11.
- PoB cannot say which modifiers a unique carries. Its unique definitions are text, and 77
  of the 217 glove lines are printed identically by several modifiers that transform
  differently. For example, Lochtonial Caress's "+(40-60) to maximum Life" matches 13
  modifiers.
- PoB's own export source (`src/Export/Uniques/gloves.lua`) names a different modifier
  than the game for 21 of the 32 uniques.
- The game-data export has no unique → modifier table either.

**Implementation:**
- `items/stonefist_unique_evidence.py` records the modifiers observed on real items per
  unique (32 uniques), plus the game-only targets:
  - removed: 6 ids with no displayed stat;
  - unavailable: 3 ids PoB lacks.

  Every line and value still comes from PoB (`get_mod_lines`, `get_item_transform_mods`).
- `items/stonefist_uniques.py` requires the candidate's own lines to match those modifiers
  one to one: same text, and each value within PoB's range for that modifier.
  - A value outside PoB's older range is accepted only when the line's text belongs to
    exactly one of the unique's modifiers and one candidate line. It is reported in
    `source_values_outside_pob_data`. Example: Facebreaker "per 4 Strength" on current
    items, "per 5" in PoB 0.23.1. The value is never used: transformed rolls are
    independent, and kept lines are copied.
  - A Vaal-mutated line is accepted only when exactly one of PoB's mutated modifiers
    prints it.
  - Everything else refuses with the line or modifier named.
- Rare gloves never decompose into unique or mutated modifiers. Only pairs whose source is
  an ordinary, essence or desecrated modifier are used for rares.

**Verified against the game** (`test_unique_gloves_transform_exactly_like_the_games_transformed_items`,
real-PoB): for ten uniques (Facebreaker, Northpaw, Painter's Servant, Hand of Wisdom and
Action, Deathblow, Maligaro's Virtuosity, Grip of Winter, Candlemaker, Horror's Flight,
Doedre's Tenure), and for the corpus Aurseize:
- the transformed modifiers equal the real transformed items';
- every real transformed value lies within the measured worst..best lines.

Fixture: `fixtures/items/stonefist_unique_gloves_poeninja.json`.

**Results on the real Stonefist fixture:**
- **Verified verdicts:** 9 of the 10 fixture uniques, plus the corpus Aurseize, get
  verified FULL verdicts.
- **Candlemaker is refused.** PoB's CombinedDPS falls, from 228,016 to 212,084, when
  "Enemies Ignited or Chilled by you have -#% to Elemental Resistances" alone goes from
  -15% to -25%. So no verdict holds for every roll. A single-roll probe identified the line.
- **Roll orientation:** `stonefist_rolls._WORSE_WHEN_LARGER` now also treats the
  character's own "reduced … Speed" and "increased … Duration on you" as worse when larger.
  Doedre's Tenure was refused before this change. A wrong orientation can only cause a
  refusal, never a verdict.

**Not supported:** uniques without real-item evidence (Treefingers, Death Articulated,
Killjoy, The Prisoner's Manacles, Blessed Bonds), and modifiers PoB lacks
(`HandWrapsUniqueIntelligence51`, `…IncreasedLife62`,
`…LocalIncreasedArmourAndEnergyShield30`). To extend support, add observed items to the
evidence table; newer PoB data may add the missing targets.

## 11. Missing transformation data (ordinary gloves)

- **Only one gap.** The GGPK export has 598 `HandWraps…` modifiers. For ordinary gloves,
  every target except `HandWrapsEnergyShieldRechargeRate5` already had its same-id source
  in PoB's data.
- **The one gap is an id quirk, not missing data.** The game and PoB both name the source
  `EnergyShieldRechargeRate5______`. The bridge tried at most three trailing underscores;
  it now takes the same id with any number of them, preferring the fewest.
- **Affixes cross-check the mapping.** All ordinary pairs share their affix name, e.g.
  "of Ardour".
- **PoB's ranges match current game data.** PoB's source and target ranges equal the GGPK
  export's for every mapped pair. The only differences are wording numbers such as
  "3 metres".
- **Djinn gloves** (`corpus02b_varashta_djinn.xml`), "+65% to Cold Resistance":
  - The largest glove cold-resistance modifier is `ColdResist8`, (41-45)%.
  - No glove hybrid, essence or desecrated modifier grants cold resistance.
  - Corruption cold resistance spawns on boots and belts only.

  No legal combination reaches 65%. The item has a jewel socket (Cadigan's Epiphany), and
  the source of the extra resistance cannot be read from the export. It stays refused.

## 12. Assumption (A): single-roll probes

**What the old check could miss.** The worst ≤ middle ≤ best check only moves every roll
together. A roll that lowers an output on its own, offset by another roll, would pass it.

**The probe.** Each ranged transformed line is set alone to its best roll, with every
other line at its worst. It is measured in the same batched PoB transaction; each probe is
one more recalculation.

**What must hold for every probe:**
- each scored output lies between the worst and best configurations;
- the verdict structure and the verdict are identical.

The verdict policy and scoring are unchanged.

**Budget.** Probes run for alternatives with 2–8 ranged lines (with one line, a probe is
the best configuration). They run only while the candidate stays within 8 configurations,
e.g. one alternative with up to 5 ranged lines. Otherwise the diagonal check stands alone,
as before.

**Measured cost** (median of 3; `corpus02c_stonefist_martial_artist.xml`; batching already
in place):

| Glove | Probes | Without | With |
| --- | --- | --- | --- |
| Vaal Gloves | 4 | 1.45 s | 2.88 s |
| Sirenscale | 5 | 1.57 s | 3.26 s |
| Giants mitts | 5 | 1.52 s | 3.52 s |
| Plate gauntlets (6 lines, over budget) | 0 | 1.32 s | 1.49 s |
| Runeforged mitts (2 alternatives) | 0 | 2.78 s | 2.95 s |

- A probe costs about 0.35–0.4 s: one recalculation, per the bridge's perf payload.
- All six gloves keep identical verdicts and ranges.
- Candlemaker (§10) shows the kind of line a probe isolates.

