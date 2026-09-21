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

## Jewels (M1.3)

Unlike every other supported category, a Jewel socket is not a fixed equipment slot: PoB
creates one `ItemSlotControl` per allocated passive-tree jewel-socket node (name
`"Jewel <nodeId>"`, PoB's `ItemsTab.lua`), and the jewel-to-socket assignment itself
lives on the tree spec, `spec.jewels[nodeId] = itemId` (`0`/absent = empty), not on
`itemsTab.activeItemSet` like ordinary equipment. Both `evaluate_item_slots` and the
underlying `tx_begin`/`tx_measure`/`tx_finish` transaction machinery already work on
these slot names unchanged (`slot:SetSelItemId` branches internally on whether the slot
has a `nodeId`), so no separate jewel transaction verb was needed — the two real gaps
were (1) `resolve_compatible_slots_for_item` never enumerated jewel-socket names (they
are dynamic and per-build, so cannot be a static table like `EVALUABLE_SLOTS`), and (2)
`tx_begin` never tracked/restored jewel-socket slots (added in M1.3).

Compatible-socket discovery reuses PoB's own `ItemsTabClass:IsItemValidForSlot`
(sinister sockets, ascendancy-embedded sockets, cluster-jewel size rules) against every
ALLOCATED socket (`slot.inactive` gates this — an unallocated socket is never a valid
placement target), occupied or empty alike.

### Inter-slot verification: two paths

A jewel-socket batch cannot always use the cheap, frame-skipped structural check
equipment batches use between slots (`tx_assert_reverted_structural`): a Timeless Jewel
can change which tree-granted skill groups exist on removal, which that check — by
design, to avoid a recalculation — cannot see. `tx_assert_reverted_jewel_batch` tries the
cheap check first and only pays for one confirming recalculation
(`tx_assert_reverted_full`) when it looks suspicious, so an ordinary jewel batch costs
exactly what an equivalent equipment batch would.

### Known bounded restore-safety limitations (real corpus evidence)

Two real, reproducible restore-safety findings from the M1.3 audit, both correctly
caught by the existing transaction verification (never a delivered wrong answer — the
engine is invalidated and the next evaluation reloads a clean build):

- **Connectivity-affecting jewels** ("Intuitive Leap"-like; PoE's "From Nothing" is the
  named example, `item.jewelData.intuitiveLeapLike`). Temporarily removing such a jewel
  deallocates the passives it was making reachable without a connected path; restoring
  the original jewel via `SetSelItemId` does not automatically reinstate them the way
  PoB's own `ItemsTabClass:DeleteItem` does when a jewel is fully removed. Sockets whose
  current jewel sets this flag are excluded from `allocated_jewel_socket_slots()`
  entirely (`excluded_connectivity_risky_socket_count`). One corpus fixture
  (`core04_skill_native_dot.xml`) carries a sanitized item that reproduces the same
  underlying risk without PoB recognizing the flag, so the filter is a best-effort,
  evidence-based improvement, not a complete guarantee — the transaction's own
  `tree_nodes` fingerprint check is the actual safety net.
- **Stateful/accumulating main skills** (stage-based skills, e.g. Flameblast; some
  ailment/DoT-averaging skills, e.g. Comet; some minion-actor chains with count-based
  unique jewels, e.g. "Grand Spectrum"). On 3 of the 9 public corpus fixtures
  (`core04_stage_context.xml`, `core04_mixed_hit_ailment.xml`, `core04_minion_actor.xml`),
  a jewel-socket transaction's post-recalculation primary metric measurably differs
  (well beyond tolerance, sometimes 1.5-3x) from the pre-transaction baseline, even
  though the exact same build evaluated via equipment (Ring/Shield/etc.) is stable. Root
  cause not fully pinned down within M1.3 (a PoB calc-engine sensitivity to jewel-touch
  recalculation for these specific skill archetypes); `tx_begin`/`tx_finish`'s existing
  metrics comparison correctly detects and refuses (`RESTORE_FAILED` →
  `EvaluationInvalidBuildState`) rather than ever reporting the wrong number.

## Tested engine revision

`97cb973f8a114d32010bc1a4195c170628771714`
