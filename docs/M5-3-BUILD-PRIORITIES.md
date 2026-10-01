# M5.3 — Build Priorities

`src/exilelens/analysis/priorities.py`, returned as `analyze_build()["build_priorities"]` and shown first in the Analyze Build
window. It answers "what does this build respond to most strongly?" from the M5.2 sensitivity profile.

> Build Priorities are measured responses to a bounded probe catalog, not a claim that all possible PoE2 stats were tested.

Player copy therefore says "Strongest measured responses among tested stats" and "Based on stats ExileLens tested against this
PoB build". It never says best, optimal or perfect.

## Why there is no universal score

Offense %, EHP %, max hit %, resistance breakpoints and movement are different axes, and each probe is one local increment
(+10% Cast Speed, +50 Life). No profile-independent scalar ranks them truthfully, so none exists: no priority score, no
per-point value, no weighting, no tiers from Build Value / `score_delta` / `marginal_value_per_unit` / SearchIntent. The old
SearchIntent tiers stay untouched and are not used.

## Structure (schema 1)

`identity` (same baseline binding as M5.1/M5.2, no profile field) · `offense_context` · `offense_limited_confidence` ·
`fix_first` · `offense` · `ehp` · `max_hit` · `mobility` · `multi_axis` · `coverage`.

* **Lanes** (`offense`, `ehp`, `max_hit`, `mobility`): only `MEASURED` signals; each lane is sorted by ONE native measured axis at the
  exact default tested increment, descending, ties in catalog order, at most 3 rows. Every row carries `tested_change` (the
  tested line, e.g. "+1 to Level of all Spell Skills") beside `response_percent`. EHP and Max Hit are separate lanes (a probe can
  be in one, both or neither); defence rows may carry Life/ES/Armour/Evasion as secondary detail. Responses at or below 0.05% are
  not shown; unavailable axes are never zero. Resistance probes never enter lanes.
* **`fix_first`**: breakpoints and deficits from existing authoritative evidence only: audit `needs` (`RES_CAP_MISSING`,
  `LOW_CHAOS_RES`, `RESOURCE_PRESSURE`; the score-based OFFENSE/MOVEMENT_OPPORTUNITY needs are excluded), the exact resistance
  breakpoint measured in sensitivity (preferred over the audit deficit), and an attribute requirement deficit from the M5.1
  fingerprint. Ordered by the existing severity, then source order. No numbers, no per-point conversion.
* **`multi_axis`**: a measured signal whose responses (at or above 1%) span at least two kinds of effect (offense / defence /
  resource / mobility). A defence probe that only raises defence numbers does not qualify; +Intelligence moving Damage, ES and
  Mana does, and keeps every axis. It may also appear in a lane.
* **`coverage`**: signals considered, status counts, `no_signal` labels, `not_established` (rejected, unsupported, restore
  failed, invalid), lanes without response, `axes_not_captured` (from M5.2), and the basis sentence.

`NO_SIGNAL` means only "no measured response at this magnitude" and is never shown as low priority;
`REJECTED/UNSUPPORTED/RESTORE_FAILED/INVALID` mean "not established". Both live in coverage.

## Confidence

Row confidence is the M5.2 one. When offense confidence is `LOW` the damage lane stays but is titled "limited confidence"; defence
lanes are unaffected.

## Profile independence and staleness

Nothing reads `profile_dependent` or the value profile, so BALANCED and MAPPING give an identical payload (tested).
`rescore_analysis()` rebuilds it purely. `is_priorities_stale` reuses `analysis.identity.is_stale` through the same identity
(hash, build, loadout, item set, context, generation). Zero PoB recalculations.

## UI

The Analyze Build list gets a first entry "BUILD PRIORITIES" (selected on completion) rendered by `format_priorities()`: FIX FIRST,
DAMAGE, EHP, MAX HIT, MOVEMENT, MULTI-IMPACT, then the qualifier. Slot entries and their detail are unchanged. Probe ids, hashes,
Build Value and per-unit numbers are never shown.

```
BUILD PRIORITIES
Strongest measured responses among tested stats.

FIX FIRST
  Fire Resistance
    +17% reaches cap

DAMAGE
  +1 to Level of all Spell Skills   +8.7%
  10% increased Cast Speed          +6.1%
EHP
  +50 to maximum Energy Shield      +3.1%   (ES +1% )
MULTI-IMPACT
  +20 to Intelligence
    Damage +2.1% · ES +4.3% · Mana +3%

Based on stats ExileLens tested against this PoB build.
```
