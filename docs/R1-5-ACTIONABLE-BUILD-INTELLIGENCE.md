# R1.5 — Actionable Build Intelligence

Base: `main` @ `c07fe50` (R1 — Build Intelligence Productization). Branch `feature/r1-5-actionable-build-intelligence`.

R1 answers "what does my build respond to?". R1.5 answers "what should I do next?" from the same measurements. It is a
derived layer: M5 sensitivity / priorities, the R1 strongest responses, `ProbeEngine`, Item Check scoring and verdicts are
unchanged. The only new measurement is a bounded follow-up probe for response curves.

## Product goal

| Question | Where |
|---|---|
| What is the biggest weakness right now? | CURRENT FOCUS card |
| What should I do next? | NEXT ACTIONS (max 3) |
| What are my top useful stats? | STAT PRIORITIES (up to 5 per axis) |
| Does a stat stay valuable if I add more? | the "next step" note on a ladder row |
| What combination fits what I need? | STAT FOCUS |
| How is the build doing overall? | BUILD HEALTH (qualitative) |
| How complete is this analysis? | ANALYSIS COVERAGE |
| What changed since last time? | WHAT CHANGED |
| Does this item solve a current priority? | Item Check build context |

Deterministic, measurement-driven, no runtime LLM.

## Truthfulness rules

* A hard problem (resistance cap, attribute requirement, one-use mana affordability) always outranks an optimisation.
* Strong sensitivity means "the build responds to this stat", never "the build is weak here". There is no "your damage
  is bad" and no build score.
* Unlike tested increments are never converted to a per-point value. Package percentages are never summed.
* Different axes are never ranked against each other by size.
* A claim the coverage cannot support is reported as not established.

## Data contract

`analyze_build()` gains two keys; every M5 / R1 key is unchanged.

```
response_curves   { schema_version, budget, new_recalcs, curves[] }          measurement evidence
actionable        { schema_version, identity,
                    current_focus  { kind, title, headline, detail, action_id }
                    action_plan[]  { number, id, kind FIX|IMPROVE, title, detail, subject, ... }   max 3
                    best_response  { status, axis_label, label, tested_change, response_percent | reason }
                    ladders        { damage[], ehp[], max_hit[], movement[] }   rows: position, label, tested_change,
                                                                                response_percent, confidence, also
                    response_curves[]                      copy of the measured curves
                    breakpoints[]  { kind, key, title, status, current, target, needed, text }
                    stat_packages[] { key, title, stats[] { label, tested_change, evidence } }
                    build_health[] { key, title, state, reason }
                    coverage       { level, label, established, relevant, summary, notes[] }
                    multi_impact[] labels
                    changes        { comparable, items[] { kind, key, text } } }
```

`analysis/actionable.py` (`build_actionable`, `diff_actionable`) is pure. `analysis/curves.py` is the only R1.5 code that
calls PoB. `rescore_analysis` rebuilds `actionable` purely and carries `response_curves` over without measuring.

## Stat Priority Ladder

The Build Priorities lane ordering (M5.3), kept longer: `MEASURED` signals only, one native axis at the tested increment,
descending, ties in catalog order, resistances excluded. Up to 5 rows; the first three are exactly the M5.3 lane, and a
fourth or fifth row must be a meaningful response (≥ 1%). Every row keeps its tested change. `NO_SIGNAL`, rejected and
unsupported tests cannot appear. A damage ladder is not produced when damage confidence is LOW. Zero PoB calls.

## Response curves

One sensitivity probe (baseline B → B + Δ) cannot show whether a stat keeps paying off. For a small set of top stats the
analysis measures one more point, B + 2Δ, with the same catalog probe at twice its canonical increment, through the same
`ProbeEngine.run_probe` (same restore verification) and compares the two **steps**, both in percent of the baseline value:

```
first step   = response(B + Δ)
second step  = response(B + 2Δ) − response(B + Δ)
ratio        = second step / first step
```

The raw 2Δ response is never presented as a marginal value.

**Targets** (`curve_targets`, at most `MAX_CURVES = 3` distinct stats, in this order): the strongest damage stat, the
strongest Max Hit stat, the strongest EHP stat, the runner-up damage stat.

**Eligibility.** A stat is measured only if its first response on that axis is meaningful (≥ 1%), its first probe was
applied and measured, and it is not a resistance. Damage stats are skipped when damage confidence is LOW. Movement is not
curved. A doubled probe that PoB rejects, cannot restore from, or reports no response for is "Could not establish" — never
an error and never a zero.

**Classification** (`classify`), by ratio:

| Ratio | State | Player wording |
|---|---|---|
| > 1.15 | GROWS | Response grows |
| 0.85 – 1.15 | HOLDS | Response remains similar |
| 0.50 – 0.85 | WEAKENS | Response weakens |
| 0.05 – 0.50 | DROPS | Response drops sharply |
| < 0.05 | NO_FURTHER_VALUE | No further measured value |

The bands were set after looking at real results (see Validation) and are not tuned per build: flat and "increased"
stats measured 1.00, attack / cast speed 0.88–1.00, skill levels 1.09–1.26, visibly tapering stats 0.74–0.79.

**Cost.** Only inside an explicit Analyze Build, after the M5 stages. Cached by the existing `ProbeCache` key (baseline
fingerprint, generation, context, probe, magnitude), so a repeat analysis of the same baseline re-measures nothing, and
any baseline change invalidates the evidence with the rest of the cache. A first-step result is always reused.

## Explicit breakpoints

Resistance caps, attribute requirements and one-use mana affordability are stated as facts with their real values and are
never described with curve language:

* below cap: `42% → 75% · 33% needed` (the amount measured in sensitivity is preferred when present);
* at cap: `At cap — more of it does not improve this measured breakpoint.` No overcap purpose is invented;
* pinned by an item: `… is fixed by an equipped item; gear cannot raise it.`

## Action plan (NEXT ACTIONS)

At most three, in this order:

1. Hard problems, in the existing FIX FIRST severity order (critical first): `Cap Chaos Resistance`,
   `Meet your Strength requirement`, `Make one use of your main skill affordable`, each with its breakpoint values.
2. The strongest well-supported directions: the defensive one (Max Hit, else EHP), then Damage — each naming the stat,
   its tested change and measured response. Two axes cannot be ranked against each other without a universal score, so
   this order is fixed rather than computed.

A direction is offered only when its top response is meaningful (≥ 1%); damage is not offered at LOW confidence. No item,
slot purchase, passive, gem or unique is ever recommended.

## Current focus

* a hard problem exists → `BIGGEST CURRENT ISSUE` with action #1 (`Chaos Resistance is below cap.`);
* otherwise → `CURRENT FOCUS: No critical issue detected.` with the first direction as detail;
* nothing established → `Could not establish a current focus.`

The largest percentage never overrides a breakpoint: the best measured response is shown separately
(`best_response`, the strongest-responses cards).

## Stat focus packages

`OFFENSE FOCUS` (top two damage stats), `DEFENCE FOCUS` (top Max Hit and EHP stats, up to two), `HYBRID FOCUS` (multi-impact
stats, up to two). Built from individual measured evidence; each stat shows its own result. No combined percentage exists
because no combined package was measured. Zero PoB calls.

## Build health

Rows: Damage, EHP, Max Hit, Resistances, Requirements (only when there is a deficit), Resources (when mana per-use data
exists), Movement. States:

| State | Rule |
|---|---|
| Needs attention | an explicit breakpoint problem on that dimension |
| Opportunity | the dimension is one of the current next actions |
| No urgent issue detected | measured, no problem, not a current action |
| Limited analysis | no measured response / not established / LOW-confidence damage |

A state never follows from sensitivity size alone, and there is no numeric score.

## Analysis coverage

Coverage = share of the relevant tests PoB actually applied (`MEASURED` or `NO_SIGNAL`); it is not a confidence in any
number.

| Level | Rule |
|---|---|
| High | ≥ 90% applied and damage established |
| Partial | 50–90% applied, or damage could not be established reliably |
| Limited | < 50% applied, or nothing ran |

Notes explain the level: tests that could not be applied, unreliable damage, follow-up measurements not established, and
"Weapon optimization remains limited." (a slot limit; it does not lower the build's level). Measurement confidence stays
internal and surfaces only where it changes interpretation ("Limited confidence", "Could not establish").

## What Changed

The controller keeps the last successful actionable analysis for the session (`_previous_actionable`; not persisted, never
read by Item Check). A new analysis is compared with it by `diff_actionable`.

**Identity rule.** Comparable when build file (path, case/slash-insensitive), loadout and context are the same. Gear, tree
or item-set edits to one build are compared; another build, loadout or context starts a new baseline and shows nothing.
The same PoB state analysed twice reports no change.

**What is reported** (semantic identities, max 6 lines): a hard problem resolved or added; no critical issue remaining;
the strongest response of an axis changing; the same top stat's response moving by ≥ 1 point and ≥ 25%; a ladder stat
moving by ≥ 2 positions; an axis gaining or losing its measured response; a new multi-impact stat; a coverage level change.
One continuity line (`↔ … remains your strongest Damage response.`) is added only when something else changed.

## Item Check integration

The cached snapshot now carries the action plan. `items/build_context.py`:

* an item that resolves a FIX FIRST issue says which priority it was: `Fixes your current #1 priority: Chaos Resistance
  reaches the cap (42% → 75%).` (or `a current priority` when it is not first); progress toward one says
  `Moves toward your current #1 priority: …`;
* when the direct explanation already gives the cap and its values, the short form is used
  (`Fixes your current #1 priority: Chaos Resistance.`) — no second number;
* current-priority context leads the broader context ("… your strongest measured damage response");
* the R1 rules stand: direct evidence owns every item delta, at most two context lines in the tooltip.

Item Check never runs R1.5 analysis. No analysis → normal Item Check. A stale analysis (any baseline identity change) is
never used; the controller also drops the cache on every baseline change.

## Analyze Build UX

Top to bottom: build and freshness → **CURRENT FOCUS** and **NEXT ACTIONS** side by side → strongest measured responses
(R1 cards, unchanged semantics) → the Overview pane: WHAT CHANGED (only when there is something), BUILD HEALTH, STAT
PRIORITIES with the next-step note, STAT FOCUS, ANALYSIS COVERAGE. The former FIX FIRST panel is replaced by the focus
and actions cards. Curve arithmetic, breakpoint facts and the R1 details stay under Show measurement details. The slot
list, slot guidance and advanced actions are as in R1.

## Performance budget

| Step | PoB calls |
|---|---|
| Ladder, action plan, focus, packages, health, coverage, What Changed | 0 |
| Item Check contextual tie-in | 0 |
| Rescore | 0 |
| Response curves, cold | ≤ 3 per analysis |
| Response curves, repeat on the same baseline | 0 |

## Validation

`scripts/r1_5_validation.py`, one real-PoB pass (output `artifacts/r1_5_validation.json`, not tracked). 11 builds, 0 errors.

### Cost

| | R1 | R1.5 |
|---|---|---|
| Cold PoB calculations per build (global stage) | 19–24 | 20–27 |
| Added by response curves, cold | — | 3 on 10 builds, 1 on the non-damage build (average 2.8, max 3) |
| Repeat analysis on the same baseline | — | 0 (curves 0) |
| PoB calls made by the actionable layer / by rescore | — | 0 / 0 on every build |

The actionable payload was identical for BALANCED and MAPPING on every build. A full analysis including slots on Ice Shot
made 49 calculations, 3 of them for curves.

### Product output

| Build (why selected) | Current focus | Next actions | Top damage ladder | Curves (second step / first) |
|---|---|---|---|---|
| Spark, Eldritch Battery (spell, ES, Kalandra) | No critical issue | Improve Max Hit (ES); Improve Damage (Spell Skill Levels) | Spell Levels +23.4%, Projectile Levels +22.0%, Cast Speed +6.8%, Crit Damage +5.1%, ES +3.2% | Spell Levels 1.25 grows; ES 1.00; Projectile Levels 1.26 grows |
| Sunder (melee) | Chaos Resistance below cap (74% → 75%) | Cap Chaos; Max Hit (Life); Damage (Attack Speed) | Attack Speed +4.4%, Attack Damage +4.2%, Crit Damage +1.0% | 1.00 / 1.00 / 1.00 similar |
| Ice Shot (bow) | Lightning Resistance below cap (63% → 75%) | Cap Lightning; Cap Chaos (22% → 75%); Max Hit (ES) | Projectile Levels +6.6%, Attack Speed +6.3%, Crit Damage +3.2%, Attack Damage +3.1%, Crit Chance +1.3% | 1.09 / 1.00 / 1.00 similar |
| Molten Blast, Brutus (crit, Strength) | Lightning Resistance below cap (51% → 76%) | Cap Lightning; Cap Chaos; Max Hit (ES) | Projectile Levels +7.7%, Strength +4.2%, Crit Damage +4.0%, Attack Speed +4.0%, Ignite Magnitude +3.3% | Projectile Levels 1.09; ES 1.00; **Strength 0.74 weakens** |
| Poisonburst Arrow (ailment) | No critical issue | Max Hit (ES); Damage (Poison Duration) | Poison Duration +24.1%, Attack Speed +15.4%, Projectile Levels +10.4%, Attack Damage +10.3%, Crit Damage +6.5% | **Poison Duration 0.79 weakens**; ES 1.02; Attack Speed 0.88 |
| Infernal Hound (minion) | No critical issue | Max Hit (ES); Damage (Minion Skill Levels) | Minion Levels +11.2%, Minion Attack Speed +4.7%, Minion Damage +2.7% | Minion Levels 1.18 grows; ES 1.01; Minion Attack Speed 1.00 |
| Grim Pillars (totem, Kalandra) | No critical issue | Max Hit (ES); Damage (Spell Skill Levels) | Spell Levels +34.0%, Cast Speed +6.5%, Spell Damage +6.5%, Crit Damage +6.4%, Crit Chance +1.6% | **Spell Levels 0.61 weakens**; ES 1.00; Life 1.00 |
| Supercharged Slam (Life, shield) | Chaos Resistance below cap (40% → 80%) | Cap Chaos; Max Hit (Life); Damage (Attack Damage) | Attack Damage +3.9%, Ignite Magnitude +2.0%, Crit Damage +1.0% | 1.00 / 1.01 / 1.00 similar |
| Spark, ES Invoker (ES) | Chaos Resistance below cap (0% → 75%) | Cap Chaos; Max Hit (ES); Damage (Spell Skill Levels) | Spell Levels +28.9%, Projectile Levels +24.7%, Cast Speed +13.5%, Spell Damage +8.6%, Crit Damage +7.2% | Spell Levels 1.21 grows; ES 1.01; Projectile Levels 1.25 grows |
| Ember Fusillade, Blood Mage (pinned resistances) | No critical issue | Max Hit (Life); Damage (Spell Skill Levels) | Spell Levels +13.6%, Projectile Levels +13.6%, Cast Speed +5.1%, Crit Damage +2.8%, Spell Damage +2.3% | Spell Levels 1.20 grows; Life 1.02; Projectile Levels 1.14 |
| Virtuous Barrier (non-damage skill) | Chaos Resistance below cap (0% → 75%) | Cap Chaos; Max Hit (Life) — no damage action | none (damage not established) | Life 1.00 (one curve only) |

Health and coverage behaved as specified: Resistances `Needs attention` on the six builds with a deficit; the Blood Mage
row reports its three elemental resistances as fixed by an equipped item rather than as a problem; Virtuous Barrier has
Damage `Limited analysis` and coverage `Partial` ("Damage could not be established reliably for this build's main
skill.") while every other build is `High` (all 19–22 relevant measurements established). Packages show component
evidence only, e.g. Brutus OFFENSE FOCUS: `+1 to Level of all Projectile Skills · Damage +7.7%`,
`+20 to Strength · Damage +4.2%`.

### Controlled before / after

A modified copy of an equipped ring was equipped in the loaded build (PoB live equipment) and the build re-analysed.

| Build | Change | What Changed |
|---|---|---|
| Ice Shot | +60% Chaos Resistance, +15% Lightning Resistance | ✓ Lightning Resistance is no longer a priority. ✓ Chaos Resistance is no longer a priority. → No critical issue remains. ↔ Projectile Skill Levels remains your strongest Damage response. |
| Molten Blast, Brutus | +30% Lightning Resistance | ✓ Lightning Resistance is no longer a priority. ↔ Projectile Skill Levels remains your strongest Damage response. (focus moved to Chaos Resistance) |
| Spark, Eldritch Battery | +150 Energy Shield, +3 Spell Skill Levels | → Cast Speed is now your strongest Damage response (was Spell Skill Levels). ↑ Critical Damage Bonus moved from #4 to #2 for Damage. ↑ Energy Shield moved from #5 to #3 for Damage. |

In all three the baseline fingerprint changed, the analyses were comparable, and a different build analysed afterwards was
not comparable (no diff shown).

### Item Check (Ice Shot, a ring with Chaos Resistance and Energy Shield, 8 warm checks each way)

| | Status | Context PoB calls | Context lines | Verdict / score |
|---|---|---|---|---|
| No analysis | NOT_ANALYZED | 0 | none | MINOR UPGRADE / 53.0 |
| Cached R1.5 analysis | AVAILABLE | 0 (0.33 ms) | "Moves toward a current priority: Chaos Resistance (22% → 62%)." · "More Energy Shield — your strongest measured EHP / Max Hit response." | MINOR UPGRADE / 53.0 |
| Stale (generation changed) | STALE | 0 | none | unchanged |

The only worker calls during the cached checks were the Item Check's own (`get_metrics`, `get_build_info`, `parse_item`,
`evaluate_item_slots`, once per check). Median warm check 802 ms without and 721 ms with the cache on this machine, which
is within its run-to-run noise.

### Tests

`tests/test_r1_5_actionable.py` (21), `tests/test_r1_5_item_check.py` (5), R1.5 additions in
`tests/test_r1_analyze_build_ui.py`.

## Breakpoint severity and Hybrid presentation (final polish)

This section supersedes the Action plan, Current focus, Build health and Stat focus rules above where they differ.

### Severity is not existence

Whether a breakpoint problem exists is decided by the unchanged FIX FIRST evidence. How loudly R1.5 presents it is decided
by a separate, explicit severity (`breakpoint_severity`), per issue type:

| Issue | Severity |
|---|---|
| Resistance below cap by less than 5 points (the existing `RES_MATERIAL_DEFICIT_POINTS` "materially below cap" edge) | MINOR — "nearly capped" |
| Elemental resistance below cap by 5 points or more | CRITICAL |
| Chaos resistance below cap by 5 points or more | MATERIAL |
| Unmet attribute requirement | CRITICAL at any size |
| Mana pool smaller than one use of the main skill | CRITICAL at any size |

Observed real gaps were 1, 12, 25, 40, 53, 75 and 76 points; only the 1-point gap (Sunder, Chaos 74% → 75%) is minor.
Severity is not confidence: coverage, measurement confidence and every measured number are unaffected, and the raw
evidence (`build_priorities.fix_first`, the breakpoint row with its values) is unchanged.

### Order

Next actions: critical and material problems (existing FIX FIRST order) → the well-supported directions (defensive, then
damage) → minor gaps. A minor gap stays actionable: `Finish capping Chaos Resistance — 74% → 75% · nearly capped`. When
the plan would overflow, the first minor gap takes the last place instead of an optimisation. Only when three critical or
material problems already fill the plan is a minor gap left to Build Health.

Current focus is the plan's first action: `BIGGEST CURRENT ISSUE` only for a critical or material problem; otherwise
`CURRENT FOCUS: <the first direction>` (e.g. `Improve Max Hit`) with "No critical issue detected." as the first line of its supporting text. "No critical issue detected." is the headline only when there is no action at all. A minor gap is the focus
(`CURRENT FOCUS: Chaos Resistance is nearly capped.`) only when nothing else is actionable.

Build health, Resistances: `Needs attention` for a critical or material deficit (a nearly capped one is mentioned beside
it); `Nearly capped` when the only deficits are minor (`Chaos Resistance is 1% below cap.`). The other rows are unchanged
and there is still no score.

Item Check follows the plan: "your current #1 priority" refers to action #1, so a nearly capped resistance is
"a current priority".

### Hybrid focus

A multi-impact stat that is already listed under Offense or Defence is not repeated as a third package. Its existing row
says which other results it also moves (`+50 to maximum Energy Shield · Max Hit +1.8% · EHP +1.8% · also moves Damage and
Mana`), and HYBRID FOCUS keeps only stats that add something new. If none do, the Hybrid package is not shown. The full
multi-impact composition stays in the data (`stat_packages[].all_stats`) and under measurement details. No percentage is
ever added to another.

## Limitations

* Curves have two points. They show whether the next equal step pays the same, not the whole shape or where a cap lies.
* Curve targets come from the lanes' top rows; a stat outside them has no curve.
* The order "defensive direction, then damage" in the action plan is a fixed convention, not a measurement.
* A doubled skill-level probe can run into a gem level cap; the result is the measured one for that build.
* Build health and coverage thresholds (1% meaningful response, 90% / 50% coverage) are simple documented conventions.
* What Changed is session-local and compares only with the immediately previous analysis.
* Everything inherits the R1 limits: text-based stat matching for item context, limited weapon analysis, mana-only
  one-use affordability, no regeneration responses.
