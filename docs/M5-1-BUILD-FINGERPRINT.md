# M5.1 — Build Fingerprint 1.0

`src/exilelens/analysis/fingerprint.py`. A structured, evidence-labelled summary of what the loaded build is and what
it responds to. It normalises data ExileLens already has; it is not a new sensitivity engine.

## Two different "fingerprints"

| | Identity fingerprint | Build fingerprint (this task) |
|---|---|---|
| Question | Is this the exact same build state? | What kind of build is this, what does it depend on? |
| Form | hash (`fingerprint_hash`, `tree_fingerprint`, `equipment_fingerprint`) | structured facts + signals |
| Role | cache key / staleness | summary contract for M5.2/M5.3, Upgrade Finder, search intent |

The identity hash is carried inside as `identity.baseline_fingerprint` and is the only binding.

## Inputs (all existing; zero extra PoB recalculation)

Baseline raw PoB metrics, build info, `resolve_primary_metric` (`PrimaryMetricSelection`), `build_state_audit`
(resistance caps, worst max hit, mana pressure), and optionally the existing `ProbeEngine` global probes. Construction
is pure and microseconds; no file, network, worker or database. `analyze_build()` attaches
`result["build_fingerprint"]` right after the audit (base) and again at the end (base + signals). Item Check never waits for it.

## Schema (`schema_version: 1`)

`identity` (hash, generation, build path/name, loadout, item set, context, primary skill) · `offense` (owner
PLAYER/MINION/TOTEM/SECONDARY_ACTOR, skill, metric, scope, quantity, kind, provenance, confidence, damage, speed, crit,
dot_present) · `defense` (Life/ES value+present, pool share, armour, evasion, block, EHP, worst max hit, per-element
resistance cap state) · `resources` (mana pool/cost/regen/sustain; Life and ES recovery kept separate; spirit) ·
`requirements` (Str/Dex/Int value, PoB highest requirement, margin, MET/DEFICIT) · `mobility` · `signals` · `coverage`.

Every fact is a leaf `{"value", "evidence"}` with evidence:

* `OBSERVED` read from PoB output; `DERIVED` arithmetic on observed values (margin, pool share, cap state, sustain);
* `MEASURED` an existing probe result; `UNAVAILABLE` not reported or not applicable (e.g. player crit for a minion build).
* `INFERRED` is reserved and unused: no judgement-based claim is made.

## Signals (existing ProbeEngine, never re-run)

`with_probe_signals(fp, global_probes)` keeps one signal per probe id: `MEASURED` (raw `offense_percent`, `ehp_percent`,
`max_hit_percent`, breakpoint codes) or `NO_SIGNAL` / `REJECTED` / `UNSUPPORTED` / `RESTORE_FAILED` / `INVALID`. These stay
distinct and carry no relevance claim: NO_SIGNAL is not "unsupported", REJECTED/UNSUPPORTED/RESTORE_FAILED are not "low
value". Curves, nonlinear samples and exact-breakpoint probes stay in the analysis result. Raw evidence is not copied.

## Profile independence

Nothing reads a value profile. The only profile-dependent numbers (`score_delta`, `marginal_value_per_unit`) sit under each
signal's `profile_dependent`; `rescore_analysis` refreshes just those. `profile_independent(fp)` strips them for equality.

## Lifecycle

Bound to `AnalysisBaseline` (hash, build path, loadout, item set, context, generation). `is_fingerprint_stale(fp, baseline)`
reuses `analysis.identity.is_stale`; a different baseline means rebuild. Probe evidence is only valid for the baseline it
was measured on, as in the existing `ProbeCache`.

## Deliberately not inferred

No archetype labels ("crit ES caster"), no "tank/glass cannon", no relevance ranking, no attack/cast orientation, triggered
mechanics, minion defences, ES recharge, leech or recoup (`coverage.not_modelled`). Low-confidence offense stays `LOW`.
M5.2 formalises the sensitivity profile on the existing probes; M5.3 owns player-facing priorities.

## Example (abbreviated)

```json
{
  "schema_version": 1,
  "identity": {"baseline_fingerprint": "9f3a1c", "generation": 2, "loadout": "Default", "item_set": "1", "context": "MAP", "primary_skill": "Spark"},
  "offense": {"owner": "PLAYER", "skill": "Spark", "metric": "CombinedDPS", "scope": "STAT_SET_PART", "confidence": "HIGH",
              "damage": {"value": 412300.0, "evidence": "OBSERVED"},
              "crit": {"chance": {"value": 62.4, "evidence": "OBSERVED"}, "present": {"value": true, "evidence": "OBSERVED"}}},
  "defense": {"energy_shield": {"value": {"value": 9284.0, "evidence": "OBSERVED"}, "present": {"value": true, "evidence": "OBSERVED"}},
              "total_ehp": {"value": 21000.0, "evidence": "OBSERVED"},
              "resistances": {"fire": {"state": {"value": "CAPPED", "evidence": "DERIVED"}}}},
  "resources": {"mana": {"sustain": {"value": "SUSTAINED", "evidence": "DERIVED"}}},
  "requirements": {"intelligence": {"margin": {"value": 124.0, "evidence": "DERIVED"}, "state": {"value": "MET", "evidence": "DERIVED"}}},
  "mobility": {"movement_speed_mod": {"value": 1.2, "evidence": "OBSERVED"}},
  "signals": {
    "CAST_SPEED": {"status": "MEASURED", "offense_percent": 9.8, "ehp_percent": 0.0, "profile_dependent": {"score_delta": 6.2}},
    "ARMOUR": {"status": "NO_SIGNAL"}
  },
  "coverage": {"offense_confidence": "HIGH", "signals_by_status": {"MEASURED": ["CAST_SPEED"], "NO_SIGNAL": ["ARMOUR"]}}
}
```
