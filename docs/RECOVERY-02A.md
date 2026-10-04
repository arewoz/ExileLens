# RECOVERY-02A — Energy Shield regeneration

RECOVERY-02A adds `EnergyShieldRegenRecovery` as an authoritative continuous recovery output from the pinned PoB worker. It intentionally excludes Energy Shield recharge, leech, recoup, costs, and any derived recovery score.

## Evidence

`fixtures/builds/public_corpus/recovery02a_es_regen_invoker.xml` is the public export (R4 removed only the per-item GGG `Unique ID:` lines and the importing character's hash; PoB's metrics, equipment and skill identity are unchanged) from `pobb.in/K6bp-LNAo507`. The public viewer recorded 9,365 Energy Shield and zero `EnergyShieldRegenRecovery`; the pinned local PoB revision recalculates the unchanged export at 9,284 ES, still with zero regeneration.

The integration candidate is built at runtime from that build's actually equipped boots and adds exactly `Regenerate 1% of maximum Energy Shield per second`. Pinned PoB's `Data/ModRunes.lua` identifies this as the bonded boots effect of **Warding Rune of Symbiosis** (`Bonded: Regenerate 1% of maximum Energy Shield per second`). No XML or custom modifier is fabricated.

## Interpretation

Life regeneration and Energy Shield regeneration are separate recovery metrics. Each is normalised against its own resource pool, uses the existing 3% relative and 0.5%-of-pool materiality thresholds, and has explicit zero-to-positive handling without an invented relative percentage. When a baseline has no usable ES pool but a candidate introduces one, the candidate ES pool is used solely as the denominator for that ES channel.

Recovery remains explanatory: it does not alter raw score calculations. Build Intelligence exposes `life_regen` and `energy_shield_regen` as named components of its composite Recovery axis rather than merging them into a scalar.
