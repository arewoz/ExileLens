# Item Evaluation Contract (Phase 2)

## Entry point

```bash
exilelens evaluate-item --build fixtures/builds/V3.2-Fast-Mapper.xml --item fixtures/items/ring1_candidate.txt
Get-Content fixtures/items/ring1_candidate.txt | exilelens evaluate-item --build fixtures/builds/V3.2-Fast-Mapper.xml
```

## Success payload

```json
{
  "ok": true,
  "raw_input": {
    "raw_text": "...",
    "content_hash": "...",
    "source": "file|stdin|test",
    "detected_format": "poe2_clipboard",
    "normalized_line_endings": true
  },
  "recognition": {
    "recognized": true,
    "confidence": "high",
    "reason": "...",
    "classification": "equipment"
  },
  "metadata": { "rarity": "RARE", "name": "...", "base_type": "...", "...": "..." },
  "pob_parse": {
    "parse_ok": true,
    "display_name": "...",
    "compatible_slots": ["Ring 1", "Ring 2"],
    "weapon_layout": "SUPPORTED|AMBIGUOUS_WEAPON_LAYOUT|UNSUPPORTED_EQUIPMENT_LAYOUT",
    "mismatches": []
  },
  "primary_metric": {
    "metric_key": "primary_offense",
    "pob_field": "CombinedDPS",
    "selected": "PRIMARY_DPS|SUSTAINED_DPS|HIT_DPS|DOT_DPS|UNRESOLVED",
    "confidence": "high|low",
    "reason": "...",
    "raw_source_fields": ["CombinedDPS", "FullDPS", "TotalDPS", "TotalDot", "FullDotDPS"]
  },
  "value_profile": "BALANCED",
  "presentation": { "item_name": "...", "rows": [], "warnings": [], "verdict": "..." },
  "compatible_slots": [
    { "product_slot": "RING_1", "pob_slot": "Ring 1" }
  ],
  "slot_comparisons": [
    {
      "product_slot": "RING_1",
      "pob_slot": "Ring 1",
      "metric_profile": {
        "primary_offense": { "current": 0, "candidate": 0, "absolute_delta": 0, "percent_delta": null },
        "ehp": { "...": "..." }
      },
      "verdict": "OFFENSE_UPGRADE",
      "restore": { "pass": true }
    }
  ],
  "recommendation": { "...": "best slot comparison" },
  "pareto": { "status": "DOMINATES|TRADEOFF|NEITHER_DOMINATES", "verdict": "...", "slot": "RING_1" },
  "timings": { "total_ms": 0, "...": "..." }
}
```

## Verdict values (internal ranking verdicts)

The table below lists the **internal** Ranking V2 verdicts, kept as regression signals. The one player-facing verdict is
`evaluation_outcome.verdict`, described in [Public verdict policy](#public-verdict-policy-evaluationoutcomeverdict) below.

| Verdict | Meaning |
|---|---|
| `STRONG_UPGRADE` | Large offense and defense gains, no cap-loss guardrail |
| `CLEAR_UPGRADE` | Offense and defense metrics improve |
| `OFFENSE_UPGRADE` | Offense improves without defense loss |
| `DEFENSE_UPGRADE` | Defense improves without offense loss **and** without an active uncapped elemental-res deficit getting worse |
| `TRADEOFF` | Mixed direction, resistance cap lost, or already-below-cap elemental resist worsened |
| `SIDEGRADE` | Small mixed/no meaningful movement |
| `NO_CHANGE` | Candidate matches equipped item |
| `DOWNGRADE` | Offense and defense worsen |
| `STRONG_DOWNGRADE` | Severe dual loss or skill/build invalid |
| `UNRESOLVED` | Insufficient signal under thresholds |

Value Profile scores (`rating` 0–100, `score_delta` vs 50) are heuristics. Raw PoB metrics remain on each comparison.

Manual price is optional (`source=MANUAL`). Power per Currency is omitted when no price is set. Currencies are never auto-converted.

## Public verdict policy (`evaluation_outcome.verdict`)

Introduced by SCORING-01a and finished by SCORING-01b (`docs/SCORING-01A.md`, `docs/SCORING-01B.md`). PoB measures; the policy only combines
already-measured effects, and it keeps four questions apart: **direction -> materiality -> conflict -> verdict**.

**Precedence** (unchanged by SCORING-01): FAILED -> `NOT_EVALUATED`; UNSUPPORTED -> `UNSUPPORTED`; any not-viable guardrail
(`ATTRIBUTE_REQUIREMENT_LOST`, `MAIN_SKILL_INVALID`, `RESOURCE_*`, `BUILD_INVALID`) -> `NOT_VIABLE`; PARTIAL -> `UNCERTAIN`; then any applied guardrail
(`RES_CAP_LOST`, `RES_DEFICIT_*`, `REQUIRED_DEFENCE_THRESHOLD`) limits the score to its ceiling and the ordinary score band decides. Quality and guardrails are never
outvoted by a good damage or EHP number. Only after all of that is a conflict considered.

**Materiality.** An axis is a real gain or loss (`material_positive` / `material_negative`) when it reaches its threshold: offense 3%, defense 3% (EHP or worst
max hit), movement 8 points, resistance-target events (cap reached/lost, or a deficit change of 5+ points). A `MIXED` axis is material in a direction only when a
component of that direction reaches the threshold, so a 0.3% sibling next to a +9% gain is not a trade-off. **Recovery** (`LifeRegenRecovery`) additionally needs a
real part of the Life pool: `|change per second| / baseline max Life >= recovery_pool_pct` (0.5% of max Life per second, provisional; see SCORING-01B). Relative
percentage alone never makes recovery material, so 37 -> 44 life/s or 1.5 -> 0 life/s does not. A baseline of exactly 0 has no percentage; it is judged by the pool
fraction alone (nothing is invented). Missing Life, or a pool of 1 (Chaos Inoculation), means recovery cannot be material.

**Conflict** (`item_impact.conflict.kind`). `MATERIAL` only if at least one axis is a material gain **and** at least one is a material loss; otherwise `NONE`.
`item_impact.pattern` stays a descriptive label ("there is some opposing movement") and does not decide the verdict. Opposing changes that are not material are
recorded as `negligible_opposition`: they stay visible ("Recovery -1.5 life/s (0.12% of max Life per second) is too small to offset the larger defense and utility
gains.") and are never decisive.

**Resolution.**

| Situation (no guardrail, quality FULL) | Verdict |
|---|---|
| `NONE` | ordinary score: `final_score = raw_score`, `verdict = classify_score_verdict(final_score)` |
| `MATERIAL`, `raw <= 47` (minor-downgrade edge) | the ordinary downgrade stands (MINOR or MEANINGFUL); the reason appends "Trade-off: ..." |
| `MATERIAL`, `47 < raw < 60` | canonical `SIDEGRADE` at 50.0, reason "Meaningful trade-off: ..." |
| `MATERIAL`, `raw >= 60` | the score path, capped at `MINOR_UPGRADE` (59.0), reason "... Limited to MINOR UPGRADE." |

**When SIDEGRADE is appropriate.** Either the ordinary score is in the sidegrade band (47-53), or the item is a genuine two-sided trade-off whose score is not
decisive in either direction (47-60). A tiny, absolutely negligible change never makes a sidegrade.

**Why a lopsided conflict is a capped MINOR_UPGRADE or a downgrade.** A material trade-off may hold an *upgrade* back by one band (a real, named loss keeps a strong
score from reading MEANINGFUL) but it never softens a *downgrade* the score already reads. So +21.7% offense against -4.3% EHP is a MINOR UPGRADE that names the
loss, and -10.6% minion offense against +5.3% EHP is a MINOR DOWNGRADE that names the gain. The bands are adjacent (MEANINGFUL DOWNGRADE, MINOR DOWNGRADE, SIDEGRADE,
MINOR UPGRADE): making a negative side slightly worse never improves the verdict.

`result["pareto"].status` follows the same reading: a `SIDEGRADE` is `TRADEOFF` only when the outcome found a material conflict, otherwise `NEITHER_DOMINATES`.

## Error codes

| Code | When |
|---|---|
| `NOT_POE2_ITEM` | Recognition failed |
| `ITEM_UNSUPPORTED` | Flask, or PoB base unresolved. (Jewel is no longer unconditionally terminal here as of M1.3 — see below.) |
| `SLOT_RESOLUTION_FAILED` | Weapon/layout unsupported |
| `SLOT_RESOLUTION_AMBIGUOUS` | Reserved for future hard-fail cases |
| `NO_COMPATIBLE_SLOT` | PoB reports zero valid slots |
| `EVALUATION_INVALID_BUILD_STATE` | Restore/fingerprint failure |
| `PRIMARY_METRIC_UNRESOLVED` | Reserved for builds without usable offense metric |
| `BASELINE_ITEM_UNRESOLVED` | Target slot baseline could not be resolved; never guess an item |

## Metric profile fields

`primary_offense`, `ehp`, `life`, `energy_shield`, `mana`, `fire_res`, `cold_res`, `lightning_res`, `chaos_res`, `movement_speed`

Each field exposes `current`, `candidate`, `absolute_delta`, `percent_delta` (null when denominator is zero), plus V2 fields `direction`, `importance`, `availability`, `confidence`, `display_format`.

## Product slot mapping

See `docs/POB2_ENGINE_CONTRACT.md` for PoB slot identifiers.

## Jewel evaluation (M1.3)

A Jewel candidate is routed to the same pipeline as equipment (`compatible_slots` →
`evaluate_item_slots` → `rank_slot_comparisons`), but its `compatible_slots` are dynamic,
per-build jewel-socket names (`"Jewel <nodeId>"`, one per allocated passive-tree jewel
socket), not a fixed `ProductSlot`. Every allocated, compatible socket — occupied or
empty — is evaluated in one batched transaction; the existing ranking/truthfulness/
guardrail machinery selects the single best, most-truthful placement, exactly as it
already does for Ring 1 vs Ring 2. `NoCompatibleSlot` for a Jewel candidate carries
`allocated_jewel_socket_count` in its details so a build with zero allocated jewel
sockets is distinguishable from a build whose sockets simply do not accept this jewel
family. See `docs/POB2_ENGINE_CONTRACT.md`'s Jewel section for the PoB-side model and
known bounded limitations.
