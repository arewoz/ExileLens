# Tree Evaluation Contract (Phase 5A.5)

Machine JSON used by CLI (`--json`) and future Tree Coach UI. No Lua tables leak.

## Result states

`VALID` | `UNREACHABLE` | `ALREADY_ALLOCATED` | `UNSUPPORTED_SPECIAL_NODE` | `INVALID_NODE`

Unreachable and unsupported nodes are **not** given a fake Build Value.

## `evaluate-node` / path evaluation

```json
{
  "status": "VALID",
  "baseline": { "build_path": "...", "loadout": "", "tree_set": "Default", "item_set": "", "context": "MAP", "profile": "BALANCED", "generation": 0, "fingerprint": "...", "tree_fingerprint": "..." },
  "target": { "node_id": 123, "name": "Arcane Tempo", "type": "NOTABLE" },
  "path": [111, 122, 123],
  "cost": 3,
  "node_value": null,
  "path_value": 10.5,
  "build_value_delta": 10.5,
  "value_per_point": 3.5,
  "metrics": {},
  "breakpoints": [],
  "warnings": [],
  "confidence": "high",
  "restore_verified": true,
  "pob_recalc": true,
  "cache_hit": false
}
```

- **NODE VALUE** is filled only when `cost == 1` (frontier / already-connected). It is not a far notable divided by N.
- **PATH VALUE** is Phase 4 `score_delta` after allocating the **complete missing path** in one PoB recalc.
- Product ranking uses **PATH VALUE** (and `value_per_point` in efficiency mode).

## NextPassiveRecommendation

```json
{
  "rank": 1,
  "node": { "id": 123, "name": "Arcane Tempo", "type": "NOTABLE" },
  "cost": 1,
  "total_build_value": 7.1,
  "value_per_point": 7.1,
  "top_metric_drivers": [],
  "breakpoints": [],
  "warnings": [],
  "confidence": "high"
}
```

## `tree-info --json`

Graph export: `nodes` (id, name, type, x/y if PoB has them, allocated, neighbors), `edges`, `tree_set`, `stats`. No raw PoB mod lists.

## TreeHeatmapData (Phase 5A.6)

Consumed by Tree Coach. Fields: `node_id`, `x`/`y`, `allocated`, `reachable`, `cost`, `build_value`, `value_per_point`, `profile_scores`, `breakpoints`, `confidence`, `evaluation_status`, `path`, `heatmap_source` (`MY_BUILD_VALUE`).

Heatmap metric is `value_per_point` (default) or total `build_value`. Bands are absolute product thresholds. UNEVALUATED ≠ LOW.

## Cache / identity

Raw evals key: build fingerprint + tree fingerprint + loadout + tree set + item set + context + generation + path identity.

Value Profile change → rescore stored raw metrics, **no** PoB recalc.

MAP/BOSS context change → invalidate raw evals.

## Safety

In-memory `AllocNode` + undo restore. Worker unhealthy if restore/fingerprint fails. Serialized PoB lane. Ctrl+C preempts **between** tree transactions, never mid-AllocNode.
