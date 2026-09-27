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
  2. **every measured configuration gives the same public verdict.**
- Otherwise the comparison is UNSUPPORTED with the reason: the verdict changes, the
  results are not ordered, or there are too many alternatives.
- **Reported numbers are a verified range over all configurations:**
  - the `[range x% to y%]` label on impact rows;
  - a `STONEFIST_ROLL_DEPENDENT` disclosure;
  - a summary such as "…Twister −9.9% to −6.0%; EHP −37.3% to −26.5%: a downgrade in every
    case", or "an upgrade in every case".

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

- **Unique gloves.** The game has `HandWrapsUnique…` mods (observed:
  `HandWrapsUniqueIncreasedSkillSpeed1`, `…IncreasedLife9`,
  `…LocalIncreasedPhysicalDamageReductionRating3`, `…MaximumManaIncrease3`,
  `…ShareChargesWithAllies1`), but PoB's data lacks them. Needed: those mod definitions in
  PoB data, plus a unique → transformed mapping.
- **`HandWrapsEnergyShieldRechargeRate5`** has no same-ID source in PoB's data.
- **Unmatched lines.** Gloves whose displayed lines fit no legal modifier combination are
  refused. That can include essence or other special modifiers without a mapped family.
- **Hand-built baselines with ranged or ambiguous transformed gloves.** The baseline must
  be exact, so it is not overridden; the glove slot is then guarded and other slots use
  PoB's untransformed baseline. Importing from the game (transformed export) avoids this.
- **"Ignore Attribute Requirements to equip Gloves"** is not modelled; it does not affect
  PoB's calculated statistics.
- **Monotonicity is checked, not assumed:** the ordering check runs over the scored
  outputs, and a PoB interaction outside those fields would not be detected by it.
- **Cost:** a roll-dependent candidate costs 3 PoB evaluations per alternative (at most 4
  alternatives, i.e. 12), on Stonefist builds only. More than 4 alternatives are refused.
