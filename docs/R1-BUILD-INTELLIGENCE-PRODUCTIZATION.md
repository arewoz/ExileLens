# R1 — Build Intelligence Productization

Base: `main` @ `b9ab35a` (Release 0.6.0, includes M5 and M5.5). Branch `feature/r1-build-intelligence-productization`.

M5/M5.5 proved ExileLens can measure what the player's own PoB build responds to. R1 turns that measurement into a product
feature without changing any of it: M5 measurement semantics, `ProbeEngine`, Item Check scoring, verdicts, guardrails,
restore behaviour, Build Value and SearchIntent are untouched.

## Product objective

After R1 a player can answer, without knowing any ExileLens internals:

| Question | Where |
|---|---|
| What does my build currently need? | Analyze Build → **FIX FIRST** |
| Which tested stats give the strongest measured response? | Analyze Build → **STRONGEST MEASURED RESPONSES** |
| What helps my damage / my survivability? | Analyze Build → DAMAGE, EHP, MAX HIT lanes |
| Which stats help several things at once? | Analyze Build → MULTI-IMPACT |
| Why is this item good for my build? What does it break? | Item Check tooltip and More Info → **FOR YOUR BUILD** |

The product rule is unchanged: **the direct candidate-vs-equipped PoB evaluation decides whether an item is better.**
Build Intelligence only explains. It is not a second verdict.

## Player-facing terminology

| Term | Meaning |
|---|---|
| Strongest measured response | The tested stat change that moved one result the most. Always shown with the tested change. |
| Tested change | The exact line ExileLens tested, e.g. `+1 to Level of all Spell Skills`. |
| Measured | PoB applied the tested change and the build responded. |
| No measurable response | PoB applied the tested change and nothing moved. Not "low priority". |
| Already at cap, so more does nothing | A resistance that showed no response because it is capped. |
| Could not establish | The test could not be applied (for example an item PoB rewrites), so nothing is claimed. |
| Not currently supported | ExileLens does not capture this response (regeneration, mana sustain). |
| FIX FIRST | A breakpoint or deficit: resistance below cap, unmet attribute requirement, mana pool smaller than one use of the main skill. |
| Multi-impact | One tested stat that moves more than one kind of result (damage / defence / resource / movement). |
| Up to date / Out of date | Whether the analysis belongs to the build that is loaded now. |

Never shown: probe ids, status enums, hashes, cache counters, per-unit values, Build Value on the priorities view.

## Strongest measured responses ("Highest-Return Stat")

`src/exilelens/analysis/strongest.py`, returned as `analyze_build()["strongest_responses"]` (and rebuilt by
`rescore_analysis`). Contract (schema 1):

```
identity      same baseline binding as M5.1-M5.3 (never rendered)
basis         "Strongest measured response among the tested stat changes."
caveat        "Tested amounts differ between stats, so this is not a per-point comparison."
damage | ehp | max_hit | movement
    status            MEASURED | NO_MEASURABLE_RESPONSE | COULD_NOT_ESTABLISH
    axis_label        "Damage" | "EHP" | "Max Hit" | "Movement"
    label             stat name                         (MEASURED only)
    tested_change     the tested line                   (MEASURED only, always present)
    response_percent  measured response on that axis    (MEASURED only)
    confidence        the M5.2 axis confidence
    also              secondary defence detail, when the lane row has it
    tied_with         tested changes that display the same response
    limited_confidence   damage only, when offense confidence is LOW
multi_impact
    status, label, tested_change, responses {axis: percent}, confidence, others
```

Derivation rules:

* It is a **derivation, not a ranking engine**. A lane in Build Priorities is already ordered by one native measured axis at
  the tested increment; the strongest response is that lane's first row. No probe runs, no PoB call is made, nothing reads a
  value profile, `score_delta` or `marginal_value_per_unit`.
* Only `MEASURED` signals can win. `NO_SIGNAL`, `REJECTED`, `UNSUPPORTED`, `RESTORE_FAILED` and `INVALID` never enter a lane,
  so they can never be a winner.
* **Ties** are deterministic: exact ties keep the M5 catalog order (the lane sort is stable). A runner-up that *displays* the
  same response (one decimal) is listed in `tied_with` instead of being silently beaten by a rounding-level difference.
* **Empty states are truthful**: if PoB applied tests and this axis did not move → `NO_MEASURABLE_RESPONSE`; if no test could
  be applied at all → `COULD_NOT_ESTABLISH`. Nothing is synthesised.
* **Multi-impact** picks the row that spans the most kinds of effect (breadth), ties in catalog order. It never sums
  percentages across axes.
* Max Hit is reported separately; when the same tested change leads both EHP and Max Hit the page shows one merged tile.

### Why there is no universal per-point score

`+1 Skill Level`, `10% Cast Speed`, `+20 Intelligence` and `+50 Energy Shield` are not equal-sized changes, and Damage %, EHP %,
Max Hit % and movement are different axes. A "best stat per point" would need a normalisation model that does not exist, so
R1 does not claim one. Every entry keeps its tested change, the wording is always "strongest measured response among the
tested stat changes", and M5.2's per-unit arithmetic stays a same-stat diagnostic that is not surfaced.

## Analyze Build UX

`src/exilelens/ui/analysis_window.py` (layout) and `src/exilelens/analysis/view.py` (all wording). It is a dashboard page
("Analyze Build" in the sidebar, also reachable from the tray) and uses the existing dashboard primitives and styles.

Build Analysis had been a parked module with no entry point in the shipped app; R1 makes `BUILD_ANALYSIS` a supported
module. No other parked module changed.

Reading order, top to bottom:

1. **Build and freshness** — build name, main skill, loadout, context; a status line (`Not analyzed yet`, `Analyzing in the
   background — Item Check stays available`, `Up to date · analyzed at HH:MM`, `Out of date — your build changed after this
   analysis`, `Analysis could not complete`) and the one action (`Analyze Build` / `Analyzing…` / `Re-analyze` / `Retry`).
2. **STRONGEST MEASURED RESPONSES** — one compact tile per axis: the measured response, and under it the tested change.
   An axis without a response shows `—` and the reason.
3. **FIX FIRST** — its own panel, visually separate from optimisation. Hidden when there is nothing to fix. The old
   continuous mana-sustain warning is not reintroduced (M5.5).
4. **Build Priorities** — DAMAGE, EHP, MAX HIT, MOVEMENT, MULTI-IMPACT. Empty lanes render nothing.
5. **What ExileLens measured** — coverage in player words.
6. **Show measurement details** (off by default) — what damage was measured on, PoB's full-speed mana assumption as
   context, run time and number of PoB calculations.

Slot entries, their detail view, Copy Search Intent and list indexing are unchanged (row 0 is BUILD PRIORITIES when the
result has priorities). Before the first analysis the page shows only the explanation and the button — no empty panes.

The analysis stays explicit, asynchronous and cache-aware: it runs on the existing analysis scheduler lane, yields to Item
Check and resumes, and repeated runs reuse `ProbeCache`. R1 fixes one defect on that path: the "cancelled" flag left set by a
build load made an Analyze Build that yielded to Item Check report "cancelled" instead of resuming.

## Build-aware Item Check explanation

`src/exilelens/items/build_context.py`. A structured, deterministic model (no LLM): each note is
`{code, kind, source, text, subject, detail}`; `code` and `kind` are the stable semantics, text can change freely.

| Code | Source | Meaning |
|---|---|---|
| `HIGH_RESPONSE_GAIN` / `HIGH_RESPONSE_LOSS` | build intelligence | The item has more / less of a stat that is among the build's strongest measured responses |
| `MULTI_AXIS_GAIN` / `MULTI_AXIS_LOSS` | build intelligence | Same, for a multi-impact stat |
| `FIX_FIRST_RESOLVED` / `FIX_FIRST_PROGRESS` | build intelligence | The swap fixes (or moves toward) an issue listed in FIX FIRST |
| `RESISTANCE_CAP_BROKEN` / `RESISTANCE_CAP_RESTORED` | direct | Cap lost / reached, with the actual values |
| `ATTRIBUTE_REQUIREMENT_BROKEN` / `ATTRIBUTE_REQUIREMENT_RESTORED` | direct | PoB reports a requirement shortfall after the swap (never a guess about future gear) |
| `RESOURCE_USE_BLOCKED` / `RESOURCE_USE_RESTORED` | direct | Unreserved mana no longer / again covers one use of the main skill (M5.5 semantics; no sustain heuristic) |
| `MAX_HIT_TRADEOFF` | direct | A material EHP-vs-Max-Hit or Damage-vs-Max-Hit split, using the existing `IMPACT_THRESHOLDS` |

### Direct result first

The tooltip hierarchy is: verdict → measured gains and losses (the existing deterministic Why) → build context → critical
notes. Build context is appended below the measured reasons (at most two lines in the compact tooltip, never replacing one),
and facts the tooltip already states (a cap break, a requirement blocker, a metric the Why already explains) are not
repeated. More Info gets a **FOR YOUR BUILD** section directly after **WHY THIS VERDICT**, with the evidence for each note
(`Tested +1 to Level of all Spell Skills → Damage +8.7%.`) and the line: "Build context comes from your last Analyze Build.
The verdict comes from testing this exact item in Path of Building."

Wording keeps the two apart: a context line says a stat is "your build's strongest measured damage response" or "one of
your build's strongest measured … responses". It never says the item is good because of it; the measured delta says that.

A stat counts as gained or lost only when the item line is the same kind of stat the analysis tested (for example
`24% increased Cast Speed`, `+2 to Level of all Spell Skills`, `+60 to maximum Life`), comparing the candidate with the item
it replaces. A damage response with limited confidence is not used to characterise an item.

### Architecture and the hot path

```
Analyze Build (explicit)  ──►  analyze_build()  ──►  controller keeps {priorities, strongest}
                                                              │  read only
Shift+C ─► direct PoB evaluation ─► verdict / score / Why ─► build_item_context() ─► tooltip, More Info
```

* The controller stores the last full Analyze Build result (`_build_intelligence`). Tree and single-slot analyses do not
  replace it.
* `_deliver_evaluation_result` attaches `result["build_context"]` after the result cache store, next to `build_freshness`.
  It is pure, takes no engine, and is wrapped so a failure can never break Item Check.
* Item Check never submits an analysis and never waits for one.

### Cache and staleness

The cached analysis is used only when it is bound to exactly the baseline the item was evaluated against. This is the M5
staleness rule (`is_priorities_stale`): baseline fingerprint, generation, build path, loadout, item set and context. The
fingerprint compared is the one in the Item Check result itself. The cache is also dropped on every baseline change
(build reload, generation bump). A value-profile-only change is never stale, as in M5.1–M5.3.

| Status | Behaviour |
|---|---|
| `AVAILABLE` | Build Intelligence notes are produced |
| `NOT_ANALYZED` | Direct notes only; More Info ends with "Run Analyze Build to see how items match your build's strongest measured stats." |
| `STALE` | Same as not analyzed. A stale analysis is never used |
| `NO_SIGNAL` | The analysis measured nothing; direct notes only |

### No-analysis fallback (journey A)

Load PoB → Shift+C works exactly as before: same verdict, same score, same Why. The only additions are direct-evidence notes
(when a breakage or split exists) and the one-line hint in More Info.

## Performance

* Strongest responses and the page view: 0 additional PoB calculations (pure functions over the analysis result).
* Explanation context: 0 PoB calls, sub-millisecond; rescoring stays pure.
* Item Check does not trigger sensitivity analysis, carrier canaries, priorities or the Analyze Build pipeline.

Measured numbers are in the validation section below.

## Validation

`scripts/r1_product_validation.py` runs one real-PoB pass (output `artifacts/r1_product_validation.json`, not tracked).

### Representative builds (12, one run each, 0 errors)

Deriving the strongest responses and the page view made **0** PoB worker calls on every build; the three profile checks
(BALANCED vs MAPPING) were identical.

| Build (why selected) | Damage | EHP | Max Hit | Multi-impact | FIX FIRST |
|---|---|---|---|---|---|
| Spark, Eldritch Battery (spell, ES, Kalandra carrier) | +1 Spell Skills → +23.4% | +50 ES → +1.8% (tied with +50 Mana) | +50 ES → +1.8% | +50 ES → Damage +3.2% · EHP +1.8% · Max Hit +1.8% · Mana +1.8% | none |
| Sunder (melee) | 10% Attack Speed → +4.4% | +50 Life → +2.3% | +50 Life → +1.7% | no measurable response | Chaos +1% |
| Ice Shot (bow) | +1 Projectile Skills → +6.6% | +50 ES → +4.3% | +50 ES → +4.1% | no measurable response | Lightning +12% (Critical), Chaos +53% |
| Molten Blast, Brutus (crit, Strength) | +1 Projectile Skills → +7.7% | +50 ES → +5.3% | +50 ES → +5.2% | +20 Strength → Damage +4.2% · EHP +1.5% · Max Hit +1.5% · ES +1.5% | Lightning +25% (Critical), Chaos +76% |
| Poisonburst Arrow (ailment) | 20% Poison Duration → +24.1% | +50 ES → +10.1% | +50 ES → +9.9% | no measurable response | none |
| Infernal Hound (minion) | +1 Minion Skills → +11.2% | +50 ES → +2.2% | +50 ES → +2.1% | no measurable response | none |
| Grim Pillars (totem, Kalandra carrier) | +1 Spell Skills → +34.0% | +50 Life → +3.1% | +50 ES → +2.5% | +50 Mana → Damage +1.4% · Mana +8.5% | none |
| Supercharged Slam (Life, shield) | 20% Attack Damage → +3.9% | +50 Life → +2.0% | +50 Life → +1.7% | no measurable response | Chaos +40% |
| Spark, ES regen Invoker (ES) | +1 Spell Skills → +28.9% | +50 ES → +6.1% | +50 ES → +6.1% | +50 Mana → Damage +1.0% · Mana +5.9% | Chaos +75% |
| Fragments of the Past (Dex/Int) | +1 Projectile Skills → +7.9% | +20 Intelligence → +1.5% | +20 Intelligence → +1.3% | +20 Intelligence → Damage +1.8% · EHP +1.5% · Max Hit +1.3% · Mana +2.0% | Chaos +85% |
| Ember Fusillade, Blood Mage (pinned resistances) | +1 Spell Skills → +13.6% (tied with +1 Projectile Skills) | +50 Life → +1.1% | +50 Life → +1.1% | +50 Life → Damage +1.4% · EHP +1.1% · Max Hit +1.1% · Life +1.2% | none; coverage says Cold, Fire and Lightning Resistance are fixed by an equipped item |
| Virtuous Barrier (non-damage main skill) | No measurable response | +50 Life → +2.2% | +50 Life → +2.0% | no measurable response | Chaos +75% |

Movement was measured on all 12 (10% Movement Speed → +5.3% to +18.6%). Coverage wording example (Spark):
"Measured: 12 tested stat changes moved this build. / No measurable response: Attack Damage, Attack Speed, Dexterity. /
Already at cap, so more does nothing: Fire Resistance, Cold Resistance, Lightning Resistance and Chaos Resistance. /
Not currently supported: Life regeneration, Energy Shield regeneration and Mana sustain responses."

### Item Check journeys (3 builds × 3 rings × 10 warm checks each way)

* Journey A (no Analyze Build): status `NOT_ANALYZED`, context 0 PoB calls, ~0.08 ms.
* Journey B (cached Analyze Build): status `AVAILABLE` on all 9, context 0 PoB calls, 0.4–0.7 ms. The only worker calls
  during journey B were the Item Check's own (`get_metrics`, `get_build_info`, `parse_item`, `evaluate_item_slots`, once
  per check). The Item Check baseline fingerprint equalled the analysis fingerprint on all 9.
* Verdict and final score were identical in A and B for all 9 items.
* Example (Spark, caster ring, MEANINGFUL DOWNGRADE in both journeys): "Adds Spell Skill Levels (+2) — your build's
  strongest measured damage response. Tested +1 to Level of all Spell Skills → Damage +23.4%." Example (Brutus):
  "Loses Strength (+72) — one of your build's strongest measured damage, EHP and Max Hit responses." and
  "Fire Resistance falls from 77% to 43%, below the 77% cap." Example (Ice Shot): "Moves Chaos Resistance closer to the cap
  (22% → 49%) — a Fix First issue for your build."
* Latency: warm Item Check on this machine is 0.7–2.0 s per check depending on the build, with ±20% run-to-run noise
  (the same build measured 0.77 s and 1.29 s in two consecutive processes). In an alternating run on one worker
  (identical PoB state) checks with and without cached context were within that noise (Spark 672 vs 734 ms, Ice Shot
  1970 vs 2227 ms; the no-analysis control showed differences of the same size, 2040 vs 1933 ms and 1335 vs 1560 ms).
  The work R1 adds is measured directly: under 1 ms and no PoB call.
* Analyze Build: 40–68 s for a full run including slots (44–46 PoB calculations); a repeat on the same baseline reuses the
  cache (8 calculations, 6–8 s) and yields identical strongest responses.

### Tests

`tests/test_r1_strongest_responses.py` (10), `tests/test_r1_item_build_context.py` (20: the twelve required fixtures,
resource semantics, tooltip / More Info wiring, unchanged verdict and Why), `tests/test_r1_analyze_build_ui.py` (17: view
wording, page states, slot / Search Intent / indexing, controller cache and no-analysis-on-Item-Check).

## Known limitations

* Analysis coverage is the M5.5 probe catalog; stats outside it never appear as a strongest response or as item context.
* Item context matches item lines to tested stats by text. Local weapon and armour modifiers that are a different stat
  (for example `% increased Energy Shield` on armour, local physical damage) are deliberately not matched, so an item can
  be good for reasons the context does not name; the measured result still shows it.
* Weapon slots are not analysed per slot (unchanged from M5).
* Only the mana resource has one-use affordability; Life-paid costs are not interpreted. Regeneration responses are not
  captured.
* The existing Item Check guardrail for mana sustain (`RESOURCE_SUSTAIN_LOST`) is unchanged, because R1 does not change
  verdict semantics. R1 itself adds no sustain warning.
* Build Intelligence is per session: it is not persisted across restarts and must be re-run after the build changes.
* Tie detection only sees the three rows a lane keeps.
