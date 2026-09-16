# Search Intent contract

Version: `1` (`contract_version`)

Phase 5A emits **semantic** Search Intent. It is **not** a trade URL, not a price, and not a network query.

```json
{
  "contract_version": 1,
  "kind": "SearchIntent",
  "baseline": {
    "build_path": "...",
    "build_name": "...",
    "loadout": "...",
    "item_set": "...",
    "context": "MAP",
    "profile": "BALANCED",
    "generation": 1,
    "fingerprint": "..."
  },
  "slot": "RING_2",
  "pob_slot": "Ring 2",
  "profile": "BALANCED",
  "required": [
    {
      "stat": "lightning_res",
      "probe_id": "LIGHTNING_RES",
      "minimum": 12,
      "reason": "RESTORE_CAP",
      "confidence": "high",
      "tier": "REQUIRED"
    }
  ],
  "high_value": [],
  "useful": [],
  "low_value": [],
  "avoid": [],
  "constraints": {
    "slot": "RING_2",
    "context": "MAP",
    "offline": true,
    "market": false
  },
  "opportunity_score": 91,
  "opportunity_band": "VERY HIGH",
  "SLOT_COMPATIBILITY_CONFIDENCE": "high",
  "price": null,
  "trade_query": null,
  "network": false
}
```

## Tiers

| Tier | Meaning |
|---|---|
| REQUIRED | Preserve/fix a critical property (e.g. exact res to cap) |
| HIGH_VALUE | Strong local marginal benefit |
| USEFUL | Positive but secondary |
| LOW_VALUE | Weak at this baseline |
| AVOID | Would break a detected critical condition |

Do not promote every positive stat to REQUIRED.

## Future adapter

Phase 5B maps this document to `CandidateSource.search(intent, plan)` via `FixtureCandidateSource` and `ImportedCandidateSource`.
