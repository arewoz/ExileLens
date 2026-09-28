# MAIN-SKILL-01 — Actionable main-skill diagnostics and recovery

Branch `feat/main-skill-01-diagnostics`, based on `origin/main` at `b999ad9`
(CORPUS-02D2, PR #49). Supported PoB 0.23.1.

**Result.** When the skill selected as PoB's main skill has no calculated offense,
Item Check no longer just says "some mechanics are not measured". It now:

1. names the selected skill by its real PoB identity and calculation context;
2. explains why offense cannot get a confident verdict;
3. lists the other skills **of the same imported build** that PoB actually calculated
   offense for;
4. gives the recovery path (select the intended skill in PoB, save, reload the build);
5. keeps every independently measured defensive result.

It never switches the skill, never calls a zero-damage buff a wrong choice, and never
turns a substituted fallback component into a primary-skill verdict. A build whose
selected skill PoB measures is untouched.

## 1. What was inspected (and reused)

| Area | Finding |
| --- | --- |
| Selection and identity | `resolve_primary_metric` already reports the selected skill (`PrimarySkill`: name, id, PoB group, stat set, part, actor) and returns `UNRESOLVED` when every offensive output is ~0. |
| Skill discovery | The bridge's `get_skill_report` already calculates every enabled group (`GlobalCache`, bounded by `MAX_REPORT_GROUPS`), and native discovery's `_selection` already decides which groups have a real, identity-stable offensive output. `get_build_info` already carries PoB's effect catalog of the **selected group**. |
| Quality/diagnostic reasons | `assess_quality` produces the reasons; tooltip, More Info, companion and diagnostics all read `evaluation_quality_reasons`. |
| Presentation | The compact tooltip shows the first reason as its one quality note; More Info renders ordered sections. |
| Refresh workflow | `Engine.ensure_source_ready` reloads whenever the build file's revision changes, and the tray has **Reload Build**. |

No new PoB calculation, bridge change or scoring rule was needed.

## 2. Two builds, two different causes

The symptom "UNCERTAIN for every item" looked alike; the causes are not the same.

| | Voltaic Barrier build (CORPUS-02D2) | Djinn build, Command selected (CORPUS-02B) |
| --- | --- | --- |
| Selected skill | Virtuous Barrier, PoB group 3, its own socket group | Command, PoB group 2 |
| Why zero offense | Pure reservation buff | Utility effect; its **sibling** effect in the *same* group, Navira, is the damage skill |
| Alternatives found | 5 in other groups: Crossbow Shot, Permafrost Bolts, **Voltaic Barrier**, Incendiary Shot, Explosive Shot | 15: Navira (**same group**, 467,530 minion DPS), Ruzhan, Kelari, and other minions/skills |
| Fallback component | Substituted for Ring 1 (`OFFENSE_FALLBACK_COMPONENT`) | Not substituted: native discovery is bounded off (16 damage-hint groups > 8), so `OFFENSE_MISSING` |
| Why a report row is not enough | Alternatives live in other groups | The report shows one row per group (the selected Command), so Navira is invisible there; the selected group's effect catalog supplies it |
| Recovery | Select Voltaic Barrier's group | Choose Navira from the selected group's own skill list |

Mace Strike (group 2, Voltaic build) is deliberately absent from the list: PoB
calculates zero for it because its two-hand mace is in the inactive weapon set. Only
PoB-calculated skills are ever listed.

## 3. Behavior

`src/exilelens/items/main_skill_diagnostics.py`:

- **Trigger (narrow):** the resolver found nothing to measure (`UNRESOLVED`, not the
  mixed DoT/ailment case) **and** every offensive PoB field is ~0.
- **Alternatives:** enabled, slot-enabled, known skill, resolved stat set/part,
  HIGH-confidence resolver result, significant value (native discovery's own test),
  plus effect-catalog siblings of the selected group that PoB calculated. Listed in
  PoB group order, then position in the group. **Never ranked by damage**, so nothing is
  implied to be the "best" skill. Display is capped at 6 with an honest total.
- **Bounded cost:** one cached `get_skill_report` per baseline, skipped above
  `MAX_REPORT_GROUPS` groups (the diagnostic then says so). Siblings need no extra call.
- **Neutral wording:** "the selected main skill, X, has no calculated offense in Path
  of Building…". It is not called incorrect unless the player says so (a test asserts
  the wording).

Surfacing:

- `EvaluationOutcome.main_skill_diagnostic` (per outcome, so replacement choices and
  every slot carry it) and a top-level `main_skill_diagnostic` in the result.
- New quality reason `MAIN_SKILL_NO_OFFENSE`, placed **first**, so the tooltip's quality
  note, the More Info header and the verdict reason lead with the actionable cause. The
  original `OFFENSE_*` reasons still follow. The evaluation stays PARTIAL / UNCERTAIN.
- More Info: a **MAIN SKILL** section directly after the verdict header (normal, not
  advanced): selected skill, why, alternatives, numbered recovery steps, "ExileLens does
  not change your selected skill.", and "Defensive changes below are still measured."
  when the DEFENSE axis is measured.
- Error catalog entry for the new code; diagnostics copy includes the field.

The compact tooltip needed no layout change: its existing one-line quality note now
carries the actionable text.

## 4. Before / after (real PoB, same candidates)

Voltaic Barrier as exported, ring with +300 Life:

| | Before (`origin/main`) | After |
| --- | --- | --- |
| Ring 1 verdict / quality | UNCERTAIN / PARTIAL | UNCERTAIN / PARTIAL (unchanged, truthful) |
| Ring 1 leading reason | "the main skill produced no usable damage output; a secondary measured component stands in for it" | "the selected main skill, Virtuous Barrier, has no calculated offense in Path of Building, so damage cannot get a confident verdict; to evaluate another skill, select it in Path of Building, save, and reload the build" |
| Ring 2 leading reason | "damage change could not be measured for this build" | the same actionable reason |
| Skill named / alternatives / steps | none | Virtuous Barrier (group 3, MAP); 5 alternatives incl. Voltaic Barrier; 3 steps |
| DEFENSE | measured, +8.4% / +6.2% | unchanged |

Djinn Command, ring with +30% minion damage: before, `OFFENSE_MISSING` +
`PRIMARY_METRIC_LOW_CONFIDENCE` with no hint of Navira; after, the same verdict with the
diagnostic and Navira listed as a same-group alternative.

After the player selects the skill and saves (Voltaic group 9 / Djinn Navira), the same
Item Check is FULL with no diagnostic, section or reason (a weapon upgrade on Voltaic
Barrier is FULL / MEANINGFUL_UPGRADE).

## 5. Phase 3 — direct selection: deferred

The architecture has no safe existing path to select an imported skill from ExileLens:
no engine/worker call sets the main skill, and doing it correctly needs (a) a worker RPC
applying the selection after load, (b) a selection bound to the build source, revision,
weapon set and skill set and revalidated on every reload (group indices shift when the
build changes), (c) baseline recapture and cache invalidation, and (d) a control in the
UI. That is more than reuse of existing infrastructure, so it is left for a separate
milestone. The diagnostic's structured alternatives (`group_index`, `effect_selector`,
`same_group`, owner) are the intended input for it.

## 6. Verification

Real PoB, `tests/integration/test_main_skill_01_real_pob.py` (5 tests):

1. As-exported Voltaic build: both ring slots carry the diagnostic (identity, MAP
   context, reason first, exact alternative list and group order, no Mace Strike or War
   Banner), stay UNCERTAIN/PARTIAL, keep DEFENSE measured, Ring 1's fallback component
   never becomes a verdict, restore passes, and PoB's selection is unchanged afterwards.
2. Every listed alternative is backed by a fresh PoB load with that skill selected
   (Voltaic Barrier and Explosive Shot values equal a cold load's).
3. Recovery on one build file: evaluate → save the selection → evaluate again; ExileLens
   reloads the changed file and the weapon check is FULL / MEANINGFUL_UPGRADE.
4. Djinn Command: different cause (no fallback, `OFFENSE_MISSING`), Navira offered as a
   same-group alternative, its listed value equals a fresh load, and selecting it
   yields FULL.
5. Poison and default-Djinn builds are unaffected (no diagnostic, no reason, no section).

Unit, `tests/test_main_skill_diagnostics.py` (13): trigger boundaries, eligibility and
ordering, duplicate labels, owners, bounded display, honest totals, neutral wording,
reason ordering/quality, and More Info content.

See §7 for suite results.

## 7. Results and remaining limitations

- **Default unit suite** (`itemcheck and not integration`): 403 passed (390 baseline + 13 new).
- **Real-PoB gate**, run once via `scripts/generate_corpus_coverage_report.py`: every
  suite passed (build_corpus 45; public_real_pob 26; weapon-set contexts 8; contextual
  placement 3; contextual diagnostics 2; effect enumeration 5; CORPUS-02A 6; 02B 7; 02C 37;
  02D1 7; 02D2 6; MAIN-SKILL-01 5; policy units 51+11+33+16+13).
- **Headline** (methodology unchanged): 125/125 → **131/131** supported.
- **Functional coverage:** 14/18 → **16/22** fully measured. The 6 new classified cases
  are 2 fully measured (recovery to FULL, measurable builds unaffected) and 2 expected
  uncertainty (Voltaic diagnostic, Djinn Command diagnostic); the diagnostic refusals are
  not counted as functional coverage. 61 verdict-level cases outside these families stay
  unclassified.

**Limitations**

1. No direct in-app skill selection (Phase 3) — recovery is via PoB.
2. Alternatives are shown with PoB's own value but are **not** a recommendation and are
   not ranked; ExileLens cannot know which skill the player intends.
3. Skills PoB calculates as zero in the current configuration (for example an attack
   whose required weapon sits in the inactive weapon set) are not listed; PoB has no
   number to show for them.
4. Above `MAX_REPORT_GROUPS` (24) skill groups only same-group siblings can be listed;
   the diagnostic says so.
5. The diagnostic is baseline-only. A candidate that *changes* whether the selected
   skill works is still handled by the existing skill-validity guardrails.
6. The unrelated fallback-substitution edge case recorded in CORPUS-02D2 §2.6 is
   unchanged.
