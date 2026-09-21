# PoB2 Engine Contract (Phase 1)

Stable product-facing API implemented by the persistent worker (`runtime/lua/bridge.lua`) and exposed through `poe2value.engine.Engine`.

## Lifecycle

| Method | Description |
|---|---|
| `ping()` | Worker health check |
| `load_build(path, context=MAP)` | Load XML via real PoB headless engine |
| `unload_build()` | Clear loaded build state |
| `shutdown()` | Tear down worker |

## Inspection

| Method | Returns |
|---|---|
| `get_build_info()` | class, ascendancy, main skill, passive counts |
| `get_equipment()` | slot inventory with item raw text |
| `get_metrics(context?)` | raw PoB metrics + normalized product metrics + fingerprint |

## Evaluation

```python
evaluate_candidate(slot: str, item_raw: str, context: str | None = None)
```

Returns:

- `baseline` — metrics, equipment, fingerprint before change
- `candidate` — metrics after temporary equip, `item_present` proof flag
- `restored` — post-restore metrics/equipment
- `delta` — normalized metric deltas
- `restore.pass` — boolean gate

## Contexts

| Context | PoB config overrides |
|---|---|
| `MAP` | `enemyIsBoss=None`, level 82, mapping resist profile |
| `BOSS` | `enemyIsBoss=Boss`, level 84, boss resist profile |

Contexts are **in-memory only**. Saved build files are never modified.

## Normalized metrics

Product layer maps raw PoB fields via `poe2value.metrics.normalize_metrics`:

- `offense.primary_dps` ← `CombinedDPS` (fallback `FullDPS`, `AverageDamage`)
- `defense.ehp` ← `TotalEHP`
- plus structured life/resist/resource fields

Raw PoB fields are always included in worker responses under `metrics` / `raw`.

## Fingerprint

Deterministic components hashed by Python (`fingerprint_hash`):

- equipped item raw text per slot
- allocated tree node ids
- evaluation context config inputs
- main skill label / socket group index
- build name + source path

Used only for restore safety, not DRM.

Application `load_build` goes through `EvaluationController` so loadout, numeric item-set id, tree set, fingerprints, and generation stay canonical. Direct `Engine.load_build` remains valid for CLI/tests.

## Error codes

`POB_PATH_INVALID`, `POB_BOOT_FAILED`, `UNSUPPORTED_POB_REVISION`, `BUILD_NOT_FOUND`, `BUILD_PARSE_FAILED`, `NO_BUILD_LOADED`, `ITEM_PARSE_FAILED`, `ITEM_INCOMPATIBLE`, `ITEM_UNSUPPORTED`, `SLOT_INVALID`, `SLOT_RESOLUTION_FAILED`, `SLOT_RESOLUTION_AMBIGUOUS`, `NO_COMPATIBLE_SLOT`, `NOT_POE2_ITEM`, `EVALUATION_INVALID_BUILD_STATE`, `PRIMARY_METRIC_UNRESOLVED`, `CALC_FAILED`, `RESTORE_FAILED`, `WORKER_UNHEALTHY`

## Product slot mapping (Phase 2)

| Product slot | PoB slot | Notes |
|---|---|---|
| `HELMET` | `Helmet` | |
| `BODY_ARMOUR` | `Body Armour` | |
| `GLOVES` | `Gloves` | |
| `BOOTS` | `Boots` | |
| `BELT` | `Belt` | |
| `AMULET` | `Amulet` | |
| `RING_1` | `Ring 1` | |
| `RING_2` | `Ring 2` | |
| `WEAPON_1` | `Weapon 1` | Main hand / 2H |
| `WEAPON_2` | `Weapon 2` | Dual-wield second weapon |
| `OFFHAND_1` | `Weapon 2` | Shield / Focus / Quiver. Logical "currently-active offhand": the M1.1 `active_weapon_slot` bridge translation (`runtime/lua/bridge.lua`) transparently resolves this to the physical `Weapon 2 Swap` slot whenever the build's active item set has `useSecondWeaponSet=true`, so product code never needs a distinct "active second weapon set" offhand concept — see M1.2 offhand-support coverage (`docs/CORE_04_ITEM_CHECK_COVERAGE_MATRIX.md`). |
| `OFFHAND_2` | `Weapon 2 Swap` | **Confirmed unreachable from live data (re-verified M1.2).** Declared only for `product_slot_to_pob`'s enum completeness; `EVALUABLE_SLOTS` in `runtime/lua/bridge.lua` never reports `"Weapon 2 Swap"` as a compatible slot, so `pob_slot_to_product` can never produce `OFFHAND_2` from a real engine response, even during an active second weapon set (see `src/poe2value/items/slots.py`'s in-code comment). Do not build new logic on this branch. |

Phase 2 engine methods:

| Method | Description |
|---|---|
| `parse_item(item_raw)` | PoB parse + compatible slots for loaded build |
| `resolve_compatible_slots(item_raw)` | Slot resolution only |

## Phase 5A probes

Marginal stat probes reuse `evaluate_candidate`: append a real modifier line to a cloned equipped item, recalc, restore, verify fingerprint. Build XML is never written.

Product analysis methods (Python, not extra Lua verbs): `analyze_build`, `analyze_slot`, Search Intent export.

## Phase 5A.5 tree

| Method | Description |
|---|---|
| `get_tree_snapshot` | Graph metadata, allocation, tree set (no XML write) |
| `evaluate_tree_path(node_ids)` | Undo snapshot → `AllocNode` complete path → recalc → `RestoreUndoState` → fingerprint |

Tree probes are in-memory only. Restore failure marks the worker unhealthy.

Python: `get_frontier_nodes`, `get_targets_within_cost`, `rank_next_passive_points`, `rank_targets`. CLI: `tree-info`, `next-passive`, `tree-targets`, `evaluate-node`.

## Tested engine revision

`97cb973f8a114d32010bc1a4195c170628771714`
