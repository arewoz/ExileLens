# CORPUS-02C — Way of the Stonefist coverage

Branch `test/corpus-02c-stonefist`, based on `origin/main` at `be634ca` (CORPUS-02B, PR #43).

**Answer: partly.** ExileLens can truthfully evaluate a Stonefist build except for one case,
glove *candidates* that the game would transform. Before this change those candidates got
confident but wrong verdicts. They are now explicitly UNSUPPORTED.

## 1. Existing support in ExileLens

- There was no Stonefist handling anywhere in the repository (code, fixtures, docs).
- The only record is an unanswered support question in the Reddit feedback thread
  (`1wniams`), which came with no build.
- Item Check hands every item to PoB. So Stonefist support depends entirely on what the
  supported PoB revision does.

## 2. The mechanic: confirmed rules vs claims

| Statement | Status | Evidence |
| --- | --- | --- |
| "Gloves you equip have their Base Type transformed to Fists of Stone while equipped, and their Explicit Modifiers are transformed into more powerful related Modifiers. Ignore Attribute Requirements to equip Gloves." | **Confirmed** (game data) | Martial Artist notable "Way of the Stonefist", node 39595, `TreeData/0_5/tree.lua` of the supported PoB |
| The equipped gloves appear **already transformed** in a character export | **Confirmed** (real export) | The public Stonefist character's poe.ninja export carries "Runeforged Fists of Stone" with per-level and transformed lines ("Has +2 to Evasion Rating per player level", "+2.34% to Critical Hit Chance", "20% more Global Evasion Rating and Energy Shield", …) |
| Rune-socket lines are not transformed | **Supported by the export** | The exported gloves keep ordinary rune lines ("+22% to Cold Resistance", Bonded lines) |
| Fists of Stone base: +3 Evasion Rating and +1 maximum Energy Shield per player level; transformed "HandWraps" modifiers are largely per-player-level values | **Datamined** (poe2db) | Consistent with the exported item and PoB's `Fists of Stone` base data |
| Specific conversions (e.g. Critical Damage Bonus → base critical hit chance) and how a rolled value maps to the transformed value | **Community / unverified** | The Mobalytics guide was not readable from this environment (HTTP 403). Other guides and converter tools agree only qualitatively. The roll mapping is unknown (see PR #2350 below). |

## 3. Upstream PoB PR #2350 (PathOfBuilding-PoE2)

"Add logic for way of the stonefist ascendency" by BligenN.

**Status:** **OPEN**, not merged. Created and last updated 2026-07-05. No reviews, no
checks, `mergeable_state: dirty` (conflicts with `dev`). The branch reports PoB **0.22.0**,
older than ExileLens's supported 0.23.1 (`97cb973`).

**Implementation:**
- `ModParser`: the passive line becomes a `WayOfTheStonefist` flag.
- `CalcSetup`: every equipped Gloves item is replaced by `item:CreateStonefistVariant()`.
- Transformation data: a generated mod map, `DataStonefistMap.lua` (original → goal), and
  `ModFistsOfStone.lua`.

The PR was not integrated. It was compared in isolation: both revisions were extracted as
source tarballs into a scratch directory and driven by this branch's ExileLens. Nothing was
installed and the supported-revision pin was not changed.

| On the Stonefist build | Supported PoB (0.23.1 source) | PR #2350 head `114b092` |
| --- | --- | --- |
| Passive parsed (bridge `modeled`) | False | True |
| Baseline Evasion / Energy Shield / EHP | 22,440 / 9,717 / 123,176 | **24,196 / 10,456 / 138,224** |
| Own transformed gloves → same gloves | FULL SIDEGRADE | FULL SIDEGRADE |
| Own gloves without "+2.34% crit" | FULL MEANINGFUL_DOWNGRADE, 358,269 → 308,109 | FULL MEANINGFUL_DOWNGRADE |
| Ordinary Vaal Gloves candidate | UNSUPPORTED (this branch) | FULL MEANINGFUL_DOWNGRADE, EHP 142,902 |
| Ordinary Plate Gauntlets candidate | UNSUPPORTED (this branch) | FULL MEANINGFUL_DOWNGRADE, DPS 262,607 |

Supported-engine baseline defences match the `<PlayerStat>` cache poe.ninja computed for this
character (Evasion 22,440, ES 9,717).

**Defects found in the PR (upstream dependencies, not fixed here):**

1. **Double transformation.** `CreateStonefistVariant` runs on every equipped Gloves item
   with armour data, including gloves that already arrive transformed ("Runeforged Fists of
   Stone"), which is how game exports provide them. It prepends the Fists of Stone per-level
   base implicits again. That is why the PR raises this character's baseline evasion by 7.8%,
   ES by 7.6% and EHP by 12%.
2. **Averaged values.** Transformed modifier values come from `stonefistAverageRanges` (the
   mid-point of the transformed modifier's range), not from the item's actual roll. Results
   for candidates are estimates.
3. **Not integrable as-is.** It is based on 0.22.0, has conflicts, and has no review or CI.

## 4. Classification of item comparisons on a Stonefist build (supported PoB)

**Correctly calculated (FULL, matches a cold PoB load):**
- Non-glove candidates, e.g. an amulet (the baseline gloves are the exported, transformed
  item, which PoB parses; only two unrelated rune lines are unparsed).
- Glove comparisons where both sides are Fists of Stone items. The main practical case is the
  player's own equipped gloves or variants of them.

**Incorrectly calculated before this change, now guarded:** ordinary glove candidates (any
non-Fists-of-Stone base, including unique gloves). The supported PoB compares the candidate
**untransformed** against the transformed baseline. On the real build this gave confident
FULL / MEANINGFUL_DOWNGRADE verdicts:

| Candidate | DPS | EHP |
| --- | --- | --- |
| Vaal Gloves | −33.8% | −29.9% |
| Plate Gauntlets | −25.4% | −41.4% |
| Massive Mitts | −27.1% | −37.4% |

In game, all three would be transformed on equip.

**Legitimately UNCERTAIN:** none specific to Stonefist. The missing transformation is an
explicit PoB gap, so the correct label is UNSUPPORTED rather than UNCERTAIN.

**Unsupported:**
- Every glove comparison that is not Fists-of-Stone on both sides.
- A hand-built PoB where the equipped gloves are *not* transformed: its whole baseline
  understates the gloves. The guard only covers the glove slot; other slots are computed on
  that baseline (a limitation).

## 5. The truthfulness guard (smallest justified change)

**`runtime/lua/bridge.lua`: `build_info.item_base_transforms`.**
- Lists allocated passives whose stat reads "<Slot> you equip have their Base Type
  transformed to <Base> while equipped".
- For each one it reports PoB's own parse state (`modeled`), taken from the parse result
  (`node.mods`). No node id is hard-coded.

**`items/baseline_item.py`: `unmodeled_item_transform`.**
- Flags a comparison in that slot unless both the equipped item and the candidate already
  carry the transformed base (an empty equipped slot counts only the candidate).
- PoB's `modeled` claim is reported (`pob_modeled`) but **not trusted**. The only known
  implementation (PR #2350) is demonstrably wrong for exported gloves, so lifting the guard
  requires deliberately validating a PoB revision.

**`items/evaluation.py`:** attaches the flag to each slot comparison.

**`items/offense_coverage.py` (`apply_primary_skill_guard`):** a flagged comparison's damage
delta becomes `UNSUPPORTED`, the existing convention, so no damage number is rendered and the
offense axis is UNKNOWN.

**`items/evaluation_outcome.py` (`assess_quality`):**
- A flagged comparison is `EvaluationQuality.UNSUPPORTED` with reason
  `ITEM_TRANSFORM_UNMODELED`, and so `PublicVerdict.UNSUPPORTED`.
- The reason text names the passive and appears in More Info under "CONDITIONAL / UNMODELED".

No scoring weights or verdict policy changed. The guard never raises confidence.

## 6. Tests and evidence

- **Fixture:** `fixtures/builds/public_corpus/corpus02c_stonefist_martial_artist.xml`,
  manifest id `CORPUS02C-STONEFIST`.
  - Source: a real public level-100 Monk / Martial Artist from the poe.ninja Runes of Aldur
    ladder, taken from the predecessor Build Corpus V1 (C01, acquired 2026-09-12).
  - Chosen by scanning every available real fixture for node 39595.
  - Re-sanitized: 21 `Unique ID` lines and the 108-line `<PlayerStat>` cache removed.

**`tests/integration/test_corpus02c_stonefist.py`** (5 real-PoB tests; numbers checked
against cold PoB loads):

| Test | Result |
| --- | --- |
| `test_stonefist_is_detected_and_the_supported_pob_does_not_model_it` | Bridge reports Stonefist, `modeled: False`. A **re-pin tripwire**: a PoB that parses the passive fails this test and forces re-validation. |
| `test_transformed_glove_comparison_is_measured` | Fists of Stone vs Fists of Stone: FULL / MEANINGFUL_DOWNGRADE matching PoB. |
| `test_ordinary_glove_candidate_is_unsupported_not_confident` [vaal_gloves, plate_gauntlets] | UNSUPPORTED, `ITEM_TRANSFORM_UNMODELED`, offense delta UNSUPPORTED, restore verified. With the guard removed it fails with `'MEANINGFUL_DOWNGRADE' == 'UNSUPPORTED'`. |
| `test_non_glove_candidates_on_a_stonefist_build_stay_measured` | Amulet candidate: FULL, matching PoB. The guard is scoped to gloves. |

**`tests/test_item_transform_guard.py`** (11 unit tests): scope matrix, the untrusted PoB
modelling claim, and the UNSUPPORTED quality with its reason text.

**Registry:**
- 1 identity case.
- `CORPUS_02C_REAL_POB_CASES` (4): three tagged `ascendancy`, because the measured mechanic
  is an ascendancy passive. The non-glove scope check carries no archetype.
- 3 policy-unit cases.

**Coverage report: 89/89** supported (78 PASS, 8 EXPECTED_UNCERTAIN, 3 UNSUPPORTED), up from
81/81.

## 7. Validation (executed locally)

Environment: Windows 11, Python 3.14.3, PoB2 0.23.1 (auto-detected).

| Command | Result |
| --- | --- |
| `pytest tests/test_item_transform_guard.py` | 11 passed |
| `pytest tests/integration/test_corpus02c_stonefist.py -m real_pob` | 5 passed |
| Ordinary-glove test with the four Python guard files reverted to `origin/main` | 2 failed (`MEANINGFUL_DOWNGRADE`); guard restored |
| `pytest tests/test_corpus_coverage_report.py` | 20 passed |
| `python scripts/generate_corpus_coverage_report.py` (real-PoB corpus gate): build_corpus 42, test_public_real_pob 26, weapon-set 8, placement 3, diagnostic 2, effect enumeration 5, CORPUS-02A 6, CORPUS-02B 7, CORPUS-02C 5, adversarial 51, transform guard 11 | all passed; 89/89 |

The gate ran twice with identical results. The first run exposed a registry case that matched
no test (NOT_RUN): a bare `test_` prefix, which the matcher does not support. It was split
into one case per test, and the report was regenerated from a fresh run rather than
hand-edited. The full test suite was not run. The experimental independent engine was not
touched.

## 8. Upstream dependencies and remaining gaps

- **Glove upgrades on Stonefist builds** need a PoB revision that transforms *untransformed*
  candidate gloves correctly and leaves already-transformed exports alone. It must also map
  real rolls, or at least document its estimates.
- **PR #2350 as it stands would regress baselines.** Report the double transformation
  upstream before relying on it.
- **When re-pinning PoB,** the tripwire test fails if the new revision parses the passive.
  Validate against this fixture before lifting the guard.
- **Untested:** unique gloves (covered by the guard because their base is not Fists of
  Stone), "Ignore Attribute Requirements" effects, and hand-built PoB baselines with
  untransformed gloves (only the glove slot is guarded).
- **No transformation modelling was reimplemented in ExileLens,** by design.
