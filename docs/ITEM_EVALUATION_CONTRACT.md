# Item Evaluation Contract (Phase 2)

## Entry point

```bash
poe2value evaluate-item --build fixtures/builds/V3.2-Fast-Mapper.xml --item fixtures/items/ring1_candidate.txt
Get-Content fixtures/items/ring1_candidate.txt | poe2value evaluate-item --build fixtures/builds/V3.2-Fast-Mapper.xml
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

## Verdict values

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

## Error codes

| Code | When |
|---|---|
| `NOT_POE2_ITEM` | Recognition failed |
| `ITEM_UNSUPPORTED` | Jewel/flask or PoB base unresolved |
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
