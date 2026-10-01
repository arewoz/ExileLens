# M5.2 — Build Sensitivity Profile

`src/exilelens/analysis/sensitivity.py`. Answers "how did this build respond to a controlled PoB intervention?".
It normalises results the existing `ProbeEngine` already produced; it adds no probe, no magnitude, no sampling and
**zero PoB recalculations**. `analyze_build()` returns it as `result["build_sensitivity"]` after probe collection, and
`rescore_analysis()` rebuilds it purely from the rescored probes (no PoB).

## Relationship to M5.1

`build_fingerprint` = what the build *is* (observed facts). `build_sensitivity` = how it *responds* (measured). They share one
baseline identity (hash, generation, build path, loadout, item set, context) and are not merged; sensitivity reads the
fingerprint only for offense ownership/metric/scope/confidence. Staleness uses the same `analysis.identity.is_stale`
(`is_sensitivity_stale`).

## Data sources

`global_probes` of the analysis result (default-magnitude result, `nonlinear_sample` rows, `curve` row, exact
`breakpoint_exact` rows) and each probe's own `metric_profile`. Probe status mapping is the M5.1 one.

## Standard increments

The `ProbeCatalog` default magnitude is the canonical local intervention (e.g. Cast Speed +10%, Spell Damage +20%, Spell
Skill Levels +1, Energy Shield +50, resistance +20). It is stored in every signal (`probe.magnitude`, `unit`, `line`).
Increments are not economically equivalent; nothing here compares them.

## Signal

`probe_id`, `family` (the intervention family, not a statement about what it affects), `label`, `probe`, `status`, `confidence`,
`response`, `response_per_unit`, `samples`, `breakpoints`, `profile_dependent`.

* **Response vector** (`MEASURED`, from the existing `metric_profile`; unavailable axes omitted, never 0): offense, EHP, max
  hit, Life, Energy Shield, Mana, Armour, Evasion, movement, speed (each with absolute and percent) and the four resistances
  (absolute); plus `resource_failure` if the probe's own warnings reported it. An attribute probe therefore records offense,
  defense and resource response together. Life regen, ES regen and mana-sustain numbers are not in `metric_profile` and are
  listed under `coverage.axes_not_captured` (not recomputed).
* **`response_per_unit`**: `offense/ehp/max_hit_percent_per_unit` = percent / probe magnitude, `DERIVED`, for the same stat
  only; not for cross-stat ranking.
* **`profile_dependent`** (everything that needs the scoring profile): `score_delta`, `marginal_value_per_unit`, and the
  existing `linearity` classification (it is computed from `score_delta`). `profile_independent_sensitivity()` removes only these.

There is deliberately no universal scalar, rank, "importance" or priority. Offense %, EHP %, max hit %, breakpoints and
movement are different axes; M5.3 decides presentation.

## Status and NO_SIGNAL

`MEASURED`, `NO_SIGNAL`, `REJECTED`, `UNSUPPORTED`, `RESTORE_FAILED`, `INVALID` stay distinct and only `MEASURED` carries a
response. `NO_SIGNAL` means only "no measured response at this probe magnitude"; it is not low sensitivity, not "the build does
not benefit", and not unsupported. Confidence is the probe's, `UNSUPPORTED` for non-measured signals, and capped at `LOW` for
the offense response when the primary offense is low-confidence (owner, metric, scope, provenance are kept in `offense_context`).

## Nonlinearity and breakpoints

Existing samples are preserved (`samples`: magnitude and measured percent per sample). Nothing is fitted, extrapolated or
added. Resistance cap events and exact deficit probes are `breakpoints` (`kind: RESISTANCE_CAP`, `required_increment`,
response at the breakpoint) and are never turned into a per-point marginal value.

## Invalidation

Bound to the baseline identity above. A value-profile-only change leaves measured response byte-equal and only refreshes
`profile_dependent`; a different build/loadout/item set/context/generation/hash makes it stale.

## Truthfulness limits

Ownership is the existing M5.1/primary-metric ownership: a minion build is not given player offense relevance. The profile
describes one controlled increment on the current baseline, not other magnitudes. No archetype or crit classification is made here.

## Abbreviated example

```json
{
  "schema_version": 1,
  "identity": {"baseline_fingerprint": "9f3a1c", "generation": 2, "loadout": "Default", "item_set": "1", "context": "MAP"},
  "offense_context": {"owner": "PLAYER", "metric": "CombinedDPS", "scope": "STAT_SET_PART", "confidence": "HIGH"},
  "signals": [
    {"probe_id": "ENERGY_SHIELD", "family": "defense", "probe": {"magnitude": 50.0, "unit": "flat"}, "status": "MEASURED",
     "confidence": "HIGH",
     "response": {"energy_shield": {"absolute": 50.0, "percent": 0.5, "evidence": "MEASURED"},
                  "ehp": {"absolute": 400.0, "percent": 1.9, "evidence": "MEASURED"}},
     "response_per_unit": {"evidence": "DERIVED", "ehp_percent_per_unit": 0.038},
     "samples": [{"magnitude": 50.0, "status": "MEASURED", "ehp_percent": 1.9}],
     "breakpoints": [],
     "profile_dependent": {"score_delta": 2.4, "marginal_value_per_unit": 0.048, "linearity": "UNKNOWN"}},
    {"probe_id": "CAST_SPEED", "family": "offense", "probe": {"magnitude": 10.0, "unit": "percent"}, "status": "NO_SIGNAL",
     "confidence": "UNSUPPORTED", "breakpoints": []}
  ],
  "coverage": {"counts": {"MEASURED": 1, "NO_SIGNAL": 1, "REJECTED": 0, "UNSUPPORTED": 0, "RESTORE_FAILED": 0, "INVALID": 0},
               "not_measured": ["CAST_SPEED"], "axes_not_captured": ["life_regen", "energy_shield_regen", "mana_sustain_numbers"]}
}
```
